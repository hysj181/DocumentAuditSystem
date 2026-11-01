"""项目三命令行入口（阶段 6：幂等复用与断点恢复）。

在阶段 1—5 的完整流程基础上，增加任务指纹、阶段有效性校验、任务锁
和 resume 断点恢复。复用阶段不会重复调用项目一或项目二。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from project3_cli_workflow.config import ProjectConfig, load_config
from project3_cli_workflow.delivery import DeliveryResult, run_delivery
from project3_cli_workflow.errors import (
    ExitCode,
    ExternalStageError,
    InputError,
    InternalError,
    PartialCompletionError,
    Project3Error,
)
from project3_cli_workflow.fingerprint import (
    apply_fingerprint,
    build_task_fingerprint,
)
from project3_cli_workflow.inputs import collect_inputs
from project3_cli_workflow.lock import TaskLock
from project3_cli_workflow.manifest import (
    build_manifest,
    calculate_sha256,
    load_manifest,
    save_manifest,
    utc_now_iso,
    write_manifest,
)
from project3_cli_workflow.models import (
    AUDIT_STATUS_FAILED,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_RUNNING,
    AUDIT_STATUS_SKIPPED,
    AUDIT_STATUS_SUCCESS,
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_RUNNING,
    EXTRACTION_STATUS_FAILED,
    EXTRACTION_STATUS_PARTIAL,
    EXTRACTION_STATUS_RUNNING,
    EXTRACTION_STATUS_SUCCESS,
    OVERALL_STATUS_FAILED,
    OVERALL_STATUS_PARTIAL,
    OVERALL_STATUS_RUNNING,
    OVERALL_STATUS_SUCCESS,
    InputFile,
    RunManifest,
)
from project3_cli_workflow.project1 import (
    Project1ExtractionResult,
    run_project1_extraction,
)
from project3_cli_workflow.project2 import (
    Project2AuditResult,
    run_project2_audit,
)
from project3_cli_workflow.reuse import (
    StageValidation,
    find_manifest_by_fingerprint,
    find_manifest_by_job_id,
    validate_audit,
    validate_delivery,
    validate_extraction,
)

DEFAULT_EXTRACTION_TIMEOUT = 1800.0
DEFAULT_AUDIT_TIMEOUT = 1800.0


class ParseMode(str, Enum):
    """项目一 PDF 解析模式。"""

    LOCAL_GPU = "local_gpu"
    CLOUD_API = "cloud_api"


app = typer.Typer(
    name="project3",
    help="企业环境数据智能审核系统 CLI 工作流（阶段 6 幂等复用与断点恢复）。",
    no_args_is_help=True,
    add_completion=False,
)


def _abort(exc: Project3Error) -> NoReturn:
    """输出错误并以统一退出码结束。"""

    typer.secho(f"错误：{exc.message}", err=True, fg=typer.colors.RED)
    raise typer.Exit(code=int(exc.exit_code))


@app.callback()
def root() -> None:
    """企业环境数据智能审核系统 CLI 工作流。"""


@app.command("run")
def run(
    inputs: Annotated[
        list[Path],
        typer.Argument(
            metavar="INPUT",
            help="输入 Word/PDF 文件或文件夹，可指定多个。",
        ),
    ],
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            "-o",
            help="运行结果输出根目录。",
        ),
    ],
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive",
            help="输入为文件夹时是否递归扫描子目录。",
        ),
    ] = False,
    mode: Annotated[
        ParseMode,
        typer.Option(
            "--mode",
            help="项目一 PDF 解析模式；cloud_api 必须显式指定。",
        ),
    ] = ParseMode.LOCAL_GPU,
    extraction_timeout: Annotated[
        float,
        typer.Option(
            "--extraction-timeout",
            help="项目一 extract 子进程超时秒数。",
        ),
    ] = DEFAULT_EXTRACTION_TIMEOUT,
    audit_timeout: Annotated[
        float,
        typer.Option(
            "--audit-timeout",
            help="项目二 audit 子进程超时秒数。",
        ),
    ] = DEFAULT_AUDIT_TIMEOUT,
    project1_root: Annotated[
        Path | None,
        typer.Option(
            "--project1-root",
            help="覆盖项目一根目录；默认读取环境变量或同级目录。",
        ),
    ] = None,
    project1_python: Annotated[
        Path | None,
        typer.Option(
            "--project1-python",
            help="覆盖项目一 Python 解释器；默认使用项目一 .venv。",
        ),
    ] = None,
    project2_root: Annotated[
        Path | None,
        typer.Option(
            "--project2-root",
            help="覆盖项目二根目录；默认读取环境变量或同级目录。",
        ),
    ] = None,
    project2_python: Annotated[
        Path | None,
        typer.Option(
            "--project2-python",
            help="覆盖项目二 Python 解释器；默认使用项目二 .venv。",
        ),
    ] = None,
) -> None:
    """运行项目一提取、项目二审核并生成最终交付目录。"""

    try:
        config = load_config(
            project1_root=project1_root,
            project1_python=project1_python,
            project2_root=project2_root,
            project2_python=project2_python,
        )
        scan = collect_inputs(inputs, recursive=recursive)
        candidate = build_manifest(scan.files, scan.filtered)
        fingerprint = build_task_fingerprint(
            candidate.inputs,
            mode.value,
            config,
        )
    except Project3Error as exc:
        _abort(exc)

    if not fingerprint.safe:
        typer.echo(
            "警告：无法确定项目一或项目二版本，已禁用任务复用。"
        )
    existing_path = find_manifest_by_fingerprint(
        output_root,
        fingerprint,
    )
    if existing_path is not None:
        try:
            with TaskLock(existing_path.parent, existing_path.parent.name):
                manifest = load_manifest(existing_path)
                _run_task(
                    manifest,
                    existing_path,
                    config,
                    current_inputs=candidate.inputs,
                    mode=mode.value,
                    extraction_timeout=extraction_timeout,
                    audit_timeout=audit_timeout,
                    reuse_enabled=True,
                    message="找到已有任务，按阶段复用或恢复",
                )
        except Project3Error as exc:
            _abort(exc)
        return

    apply_fingerprint(candidate, fingerprint)
    try:
        manifest_path = save_manifest(candidate, output_root)
    except Project3Error as exc:
        _abort(exc)

    try:
        with TaskLock(manifest_path.parent, candidate.job_id):
            _run_task(
                candidate,
                manifest_path,
                config,
                current_inputs=candidate.inputs,
                mode=mode.value,
                extraction_timeout=extraction_timeout,
                audit_timeout=audit_timeout,
                reuse_enabled=False,
                message="未找到匹配任务，创建新任务",
            )
    except Project3Error as exc:
        _abort(exc)


def _run_task(
    manifest: RunManifest,
    manifest_path: Path,
    config: ProjectConfig,
    *,
    current_inputs: list[InputFile],
    mode: str,
    extraction_timeout: float,
    audit_timeout: float,
    reuse_enabled: bool,
    message: str,
) -> None:
    """按阶段复用或执行任务。"""

    task_dir = manifest_path.parent
    typer.echo(f"任务：{manifest.job_id}（{message}）")

    extraction_check = (
        validate_extraction(
            manifest,
            task_dir,
            current_inputs,
            mode=mode,
        )
        if reuse_enabled
        else StageValidation(False, ["未启用复用"])
    )
    audit_check = (
        validate_audit(manifest, task_dir)
        if extraction_check.valid
        else StageValidation(False, ["提取结果不可复用"])
    )
    if extraction_check.valid and audit_check.valid:
        manifest.overall_status = _overall_status(
            manifest.extraction_status,
            manifest.audit_status,
        )
    delivery_check = (
        validate_delivery(manifest, task_dir)
        if audit_check.valid
        else StageValidation(False, ["审核结果不可复用"])
    )
    _print_stage_plan(
        extraction_check,
        audit_check,
        delivery_check,
    )

    if (
        extraction_check.valid
        and audit_check.valid
        and delivery_check.valid
    ):
        now = utc_now_iso()
        manifest.extraction_reused = True
        manifest.audit_reused = True
        manifest.delivery_reused = True
        _record_stage(
            manifest,
            "extraction",
            now,
            now,
            "reused",
            manifest.extraction_status,
            manifest.batch_json_path,
        )
        _record_stage(
            manifest,
            "audit",
            now,
            now,
            "reused",
            manifest.audit_status,
            manifest.audit_report_json,
        )
        _record_stage(
            manifest,
            "delivery",
            now,
            now,
            "reused",
            manifest.delivery_status,
            manifest.delivery_manifest_json,
        )
        write_manifest(manifest, manifest_path)
        typer.echo("所有阶段均有效，本次没有调用项目一或项目二。")
        _finalize_task(manifest)
        return

    extraction = None
    if extraction_check.valid:
        manifest.extraction_reused = True
        now = utc_now_iso()
        _record_stage(
            manifest,
            "extraction",
            now,
            now,
            "reused",
            manifest.extraction_status,
            manifest.batch_json_path,
        )
        typer.echo("阶段 3：复用已有项目一提取结果。")
    else:
        manifest.extraction_reused = False
        manifest.overall_status = OVERALL_STATUS_RUNNING
        _mark_extraction_running(
            manifest,
            mode=mode,
            timeout=extraction_timeout,
        )
        try:
            write_manifest(manifest, manifest_path)
            extraction = run_project1_extraction(
                config,
                [Path(item.source_path) for item in current_inputs],
                task_dir,
                mode=mode,
                timeout=extraction_timeout,
            )
            _apply_extraction_result(manifest, extraction)
            _record_stage(
                manifest,
                "extraction",
                extraction.started_at,
                extraction.finished_at,
                "executed",
                extraction.status,
                manifest.batch_json_path,
                extraction.error,
            )
            write_manifest(manifest, manifest_path)
        except Project3Error as exc:
            _mark_extraction_failed(
                manifest,
                exc.message,
                mode=mode,
                timeout=extraction_timeout,
            )
            manifest.overall_status = OVERALL_STATUS_FAILED
            try:
                write_manifest(manifest, manifest_path)
            except Project3Error:
                pass
            _abort(exc)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            internal = InternalError(
                f"项目一提取过程中发生内部错误：{exc}"
            )
            _mark_extraction_failed(
                manifest,
                internal.message,
                mode=mode,
                timeout=extraction_timeout,
            )
            manifest.overall_status = OVERALL_STATUS_FAILED
            try:
                write_manifest(manifest, manifest_path)
            except Project3Error:
                pass
            _abort(internal)
        _print_extraction_summary(
            extraction,
            manifest,
            manifest_path,
            task_dir,
            config,
        )

    if extraction is not None and (
        extraction.status == EXTRACTION_STATUS_FAILED
    ):
        reason = "项目一提取失败，未执行项目二审核。"
        _mark_audit_skipped(manifest, reason, timeout=audit_timeout)
        try:
            write_manifest(manifest, manifest_path)
        except Project3Error:
            pass
        _print_audit_skipped(task_dir, manifest, manifest_path)
        delivery = _execute_delivery(manifest, manifest_path)
        _print_delivery_summary(delivery, manifest_path, task_dir)
        _finalize_task(manifest)
        return

    if audit_check.valid:
        manifest.audit_reused = True
        now = utc_now_iso()
        _record_stage(
            manifest,
            "audit",
            now,
            now,
            "reused",
            manifest.audit_status,
            manifest.audit_report_json,
        )
        manifest.overall_status = _overall_status(
            manifest.extraction_status,
            manifest.audit_status,
        )
        typer.echo("阶段 4：复用已有项目二审核结果。")
    else:
        manifest.audit_reused = False
        if not manifest.batch_json_path:
            reason = "项目一 batch.json 不存在，未执行项目二审核。"
            _mark_audit_skipped(manifest, reason, timeout=audit_timeout)
            try:
                write_manifest(manifest, manifest_path)
            except Project3Error:
                pass
            _print_audit_skipped(task_dir, manifest, manifest_path)
            delivery = _execute_delivery(manifest, manifest_path)
            _print_delivery_summary(delivery, manifest_path, task_dir)
            _finalize_task(manifest)
            return
        _mark_audit_running(manifest, timeout=audit_timeout)
        try:
            write_manifest(manifest, manifest_path)
            audit = run_project2_audit(
                config,
                manifest.batch_json_path,
                task_dir,
                timeout=audit_timeout,
            )
            _apply_audit_result(manifest, audit)
            _record_stage(
                manifest,
                "audit",
                audit.started_at,
                audit.finished_at,
                "executed",
                audit.status,
                manifest.audit_report_json,
                audit.error,
            )
            write_manifest(manifest, manifest_path)
        except Project3Error as exc:
            _mark_audit_failed(
                manifest,
                exc.message,
                timeout=audit_timeout,
            )
            try:
                write_manifest(manifest, manifest_path)
            except Project3Error:
                pass
            _abort(exc)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            internal = InternalError(
                f"项目二审核过程中发生内部错误：{exc}"
            )
            _mark_audit_failed(
                manifest,
                internal.message,
                timeout=audit_timeout,
            )
            try:
                write_manifest(manifest, manifest_path)
            except Project3Error:
                pass
            _abort(internal)
        _print_audit_summary(
            audit,
            manifest,
            manifest_path,
            task_dir,
            config,
        )

    if delivery_check.valid:
        manifest.delivery_reused = True
        now = utc_now_iso()
        _record_stage(
            manifest,
            "delivery",
            now,
            now,
            "reused",
            manifest.delivery_status,
            manifest.delivery_manifest_json,
        )
        write_manifest(manifest, manifest_path)
        typer.echo("阶段 5：复用已有最终交付目录。")
    else:
        manifest.delivery_reused = False
        delivery = _execute_delivery(manifest, manifest_path)
        _record_stage(
            manifest,
            "delivery",
            delivery.started_at,
            delivery.finished_at,
            "executed",
            delivery.status,
            str(delivery.delivery_manifest_json),
            delivery.error,
        )
        write_manifest(manifest, manifest_path)
        _print_delivery_summary(delivery, manifest_path, task_dir)

    _finalize_task(manifest)


def _print_stage_plan(
    extraction: StageValidation,
    audit: StageValidation,
    delivery: StageValidation,
) -> None:
    """输出阶段复用判断。"""

    for name, check in (
        ("提取", extraction),
        ("审核", audit),
        ("交付", delivery),
    ):
        action = "复用" if check.valid else "重跑"
        reasons = "；".join(check.reasons)
        suffix = f"（{reasons}）" if reasons and not check.valid else ""
        typer.echo(f"- {name}阶段：{action}{suffix}")


def _record_stage(
    manifest: RunManifest,
    stage: str,
    started_at: str,
    finished_at: str,
    execution: str,
    status: str,
    output_path: str | None,
    error: str | None = None,
) -> None:
    """追加阶段历史。"""

    manifest.stage_history.append(
        {
            "stage": stage,
            "started_at": started_at,
            "finished_at": finished_at,
            "execution": execution,
            "input_fingerprint": manifest.task_fingerprint,
            "output_path": output_path,
            "status": status,
            "error": error,
        }
    )


def _finalize_task(manifest: RunManifest) -> None:
    """根据整体状态结束 CLI。"""

    if manifest.overall_status == OVERALL_STATUS_SUCCESS:
        return
    if manifest.overall_status == OVERALL_STATUS_PARTIAL:
        _abort(
            PartialCompletionError(
                "任务部分完成："
                f"提取状态 {manifest.extraction_status}，"
                f"审核状态 {manifest.audit_status}，"
                f"交付状态 {manifest.delivery_status}。"
            )
        )
    _abort(
        ExternalStageError(
            manifest.extraction_error
            or manifest.audit_error
            or manifest.delivery_error
            or "任务失败。"
        )
    )


@app.command("deliver")
def deliver(
    manifest: Annotated[
        Path,
        typer.Option(
            "--manifest",
            "-m",
            help="现有任务 manifest.json 路径。",
        ),
    ],
) -> None:
    """只为现有任务生成最终交付目录，不重新提取或审核。"""

    manifest_path = Path(manifest).expanduser().resolve()
    try:
        loaded = load_manifest(manifest_path)
    except Project3Error as exc:
        _abort(exc)

    try:
        with TaskLock(manifest_path.parent, loaded.job_id):
            delivery = _execute_delivery(loaded, manifest_path)
    except Project3Error as exc:
        _abort(exc)

    _print_delivery_summary(
        delivery,
        manifest_path,
        manifest_path.parent,
    )
    _finalize_task(loaded)


@app.command("resume")
def resume(
    job_id: Annotated[
        str,
        typer.Argument(help="要恢复的任务 ID。"),
    ],
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            "-o",
            help="任务输出根目录。",
        ),
    ] = Path("output"),
    extraction_timeout: Annotated[
        float,
        typer.Option(
            "--extraction-timeout",
            help="项目一 extract 子进程超时秒数。",
        ),
    ] = DEFAULT_EXTRACTION_TIMEOUT,
    audit_timeout: Annotated[
        float,
        typer.Option(
            "--audit-timeout",
            help="项目二 audit 子进程超时秒数。",
        ),
    ] = DEFAULT_AUDIT_TIMEOUT,
    project1_root: Annotated[
        Path | None,
        typer.Option(
            "--project1-root",
            help="覆盖项目一根目录；必须与任务指纹配置一致。",
        ),
    ] = None,
    project1_python: Annotated[
        Path | None,
        typer.Option(
            "--project1-python",
            help="覆盖项目一 Python 解释器；必须与任务指纹配置一致。",
        ),
    ] = None,
    project2_root: Annotated[
        Path | None,
        typer.Option(
            "--project2-root",
            help="覆盖项目二根目录；必须与任务指纹配置一致。",
        ),
    ] = None,
    project2_python: Annotated[
        Path | None,
        typer.Option(
            "--project2-python",
            help="覆盖项目二 Python 解释器；必须与任务指纹配置一致。",
        ),
    ] = None,
) -> None:
    """从 manifest 中有效阶段之后恢复任务。"""

    try:
        config = load_config(
            project1_root=project1_root,
            project1_python=project1_python,
            project2_root=project2_root,
            project2_python=project2_python,
        )
        manifest_path = find_manifest_by_job_id(output_root, job_id)
        if manifest_path is None:
            raise InputError(f"未找到任务：{job_id}")
    except Project3Error as exc:
        _abort(exc)

    try:
        with TaskLock(manifest_path.parent, job_id):
            manifest = load_manifest(manifest_path)
            mode = manifest.extraction_mode
            if not mode:
                raise InputError("任务缺少 extraction_mode，无法恢复。")
            refreshed = build_manifest(
                [item.source_path for item in manifest.inputs]
            )
            fingerprint = build_task_fingerprint(
                refreshed.inputs,
                mode,
                config,
            )
            if not fingerprint.safe:
                raise InputError(
                    "无法确定项目一或项目二版本，拒绝安全复用。"
                )
            if manifest.task_fingerprint != fingerprint.value:
                raise InputError(
                    "任务指纹不一致：输入文件或项目配置已变化，"
                    "拒绝恢复旧任务。请使用新输入重新运行。"
                )
            _run_task(
                manifest,
                manifest_path,
                config,
                current_inputs=refreshed.inputs,
                mode=mode,
                extraction_timeout=extraction_timeout,
                audit_timeout=audit_timeout,
                reuse_enabled=True,
                message="从断点恢复任务",
            )
    except Project3Error as exc:
        _abort(exc)


def _mark_extraction_running(
    manifest: RunManifest,
    *,
    mode: str,
    timeout: float,
) -> None:
    """将 manifest 标记为项目一提取运行中。"""

    manifest.status = EXTRACTION_STATUS_RUNNING
    manifest.extraction_status = EXTRACTION_STATUS_RUNNING
    manifest.extraction_started_at = utc_now_iso()
    manifest.extraction_finished_at = None
    manifest.extraction_mode = mode
    manifest.extraction_timeout_seconds = timeout
    manifest.extraction_error = None


def _apply_extraction_result(
    manifest: RunManifest,
    result: Project1ExtractionResult,
) -> None:
    """把项目一提取结果写入 manifest。"""

    manifest.status = result.status
    manifest.extraction_status = result.status
    manifest.extraction_started_at = result.started_at
    manifest.extraction_finished_at = result.finished_at
    manifest.extraction_mode = result.mode
    manifest.extraction_exit_code = result.exit_code
    manifest.extraction_command = list(result.command)
    manifest.extraction_stdout_log = str(result.stdout_log_path)
    manifest.extraction_stderr_log = str(result.stderr_log_path)
    manifest.extraction_error = result.error

    batch = result.batch
    if batch is not None:
        manifest.batch_id = batch.batch_id
        manifest.document_count = batch.document_count
        manifest.successful_document_count = (
            batch.successful_document_count
        )
        manifest.failed_document_count = batch.failed_document_count
        manifest.warning_count = batch.warning_count
    if result.batch_path is not None:
        manifest.batch_json_path = str(result.batch_path)
        if result.batch_path.is_file():
            manifest.batch_json_sha256 = calculate_sha256(
                result.batch_path
            )


def _mark_extraction_failed(
    manifest: RunManifest,
    message: str,
    *,
    mode: str,
    timeout: float,
) -> None:
    """把 manifest 标记为项目一提取失败。"""

    manifest.status = EXTRACTION_STATUS_FAILED
    manifest.extraction_status = EXTRACTION_STATUS_FAILED
    manifest.extraction_finished_at = utc_now_iso()
    manifest.extraction_mode = mode
    manifest.extraction_timeout_seconds = timeout
    manifest.extraction_error = message


def _mark_audit_running(manifest: RunManifest, *, timeout: float) -> None:
    """将 manifest 标记为项目二审核运行中。"""

    manifest.status = AUDIT_STATUS_RUNNING
    manifest.audit_status = AUDIT_STATUS_RUNNING
    manifest.audit_started_at = utc_now_iso()
    manifest.audit_finished_at = None
    manifest.audit_timeout_seconds = timeout
    manifest.audit_error = None
    manifest.overall_status = OVERALL_STATUS_RUNNING


def _mark_audit_skipped(
    manifest: RunManifest,
    reason: str,
    *,
    timeout: float,
) -> None:
    """记录项目二未执行。"""

    manifest.status = AUDIT_STATUS_SKIPPED
    manifest.audit_status = AUDIT_STATUS_SKIPPED
    manifest.audit_finished_at = utc_now_iso()
    manifest.audit_timeout_seconds = timeout
    manifest.audit_error = reason
    manifest.overall_status = OVERALL_STATUS_FAILED


def _mark_audit_failed(
    manifest: RunManifest,
    message: str,
    *,
    timeout: float,
) -> None:
    """把 manifest 标记为项目二审核失败。"""

    manifest.status = AUDIT_STATUS_FAILED
    manifest.audit_status = AUDIT_STATUS_FAILED
    manifest.audit_finished_at = utc_now_iso()
    manifest.audit_timeout_seconds = timeout
    manifest.audit_error = message
    manifest.overall_status = OVERALL_STATUS_FAILED


def _apply_audit_result(
    manifest: RunManifest,
    result: Project2AuditResult,
) -> None:
    """把项目二审核结果写入 manifest。"""

    manifest.status = result.status
    manifest.audit_status = result.status
    manifest.audit_started_at = result.started_at
    manifest.audit_finished_at = result.finished_at
    manifest.audit_exit_code = result.exit_code
    manifest.audit_command = list(result.command)
    manifest.audit_stdout_log = str(result.stdout_log_path)
    manifest.audit_stderr_log = str(result.stderr_log_path)
    manifest.audit_error = result.error
    manifest.overall_status = _overall_status(
        manifest.extraction_status,
        result.status,
    )

    summary = result.summary
    if result.report_path is not None:
        manifest.audit_report_json = str(result.report_path)
        if result.report_path.is_file():
            manifest.audit_report_sha256 = calculate_sha256(
                result.report_path
            )
    if summary is None:
        return

    manifest.audit_complete_success = summary.complete_success
    manifest.audit_issue_count = summary.counts["issue_count"]
    manifest.audit_unverified_count = summary.counts["unverified_count"]
    manifest.audit_manual_review_count = summary.counts[
        "annotation_manual_review_count"
    ]
    manifest.audit_issues_flagged_for_manual_review_count = summary.counts[
        "issues_flagged_for_manual_review"
    ]
    manifest.audit_warning_count = len(summary.warnings)
    manifest.audit_typo_counts = dict(summary.typo_counts)
    manifest.annotated_files = [str(path) for path in summary.output_files]
    if summary.audit_markdown_path is not None:
        manifest.audit_report_markdown = str(
            summary.audit_markdown_path
        )
    if summary.annotation_report_path is not None:
        manifest.annotation_report = str(summary.annotation_report_path)
    if summary.math_validation_path is not None:
        manifest.math_validation_report = str(summary.math_validation_path)


def _overall_status(extraction_status: str, audit_status: str) -> str:
    """计算提取和审核两个阶段的整体状态。"""

    if (
        extraction_status == EXTRACTION_STATUS_FAILED
        or audit_status in {AUDIT_STATUS_FAILED, AUDIT_STATUS_SKIPPED}
    ):
        return OVERALL_STATUS_FAILED
    if (
        extraction_status == EXTRACTION_STATUS_PARTIAL
        or audit_status == AUDIT_STATUS_PARTIAL
    ):
        return OVERALL_STATUS_PARTIAL
    if (
        extraction_status == EXTRACTION_STATUS_SUCCESS
        and audit_status == AUDIT_STATUS_SUCCESS
    ):
        return OVERALL_STATUS_SUCCESS
    return OVERALL_STATUS_PARTIAL


def _execute_delivery(
    manifest: RunManifest,
    manifest_path: Path,
) -> DeliveryResult:
    """执行最终交付整理并更新 manifest。"""

    _mark_delivery_running(manifest)
    try:
        write_manifest(manifest, manifest_path)
        result = run_delivery(manifest, manifest_path)
        _apply_delivery_result(manifest, result)
        write_manifest(manifest, manifest_path)
        return result
    except Project3Error as exc:
        _mark_delivery_failed(manifest, exc.message)
        try:
            write_manifest(manifest, manifest_path)
        except Project3Error:
            pass
        _abort(exc)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - 防御性边界
        internal = InternalError(f"最终交付整理发生内部错误：{exc}")
        _mark_delivery_failed(manifest, internal.message)
        try:
            write_manifest(manifest, manifest_path)
        except Project3Error:
            pass
        _abort(internal)


def _mark_delivery_running(manifest: RunManifest) -> None:
    """将 manifest 标记为交付整理运行中。"""

    manifest.delivery_status = DELIVERY_STATUS_RUNNING
    manifest.delivery_started_at = utc_now_iso()
    manifest.delivery_finished_at = None
    manifest.delivery_error = None


def _apply_delivery_result(
    manifest: RunManifest,
    result: DeliveryResult,
) -> None:
    """把交付结果写入 manifest。"""

    manifest.delivery_status = result.status
    manifest.delivery_started_at = result.started_at
    manifest.delivery_finished_at = result.finished_at
    manifest.delivery_directory = (
        str(result.directory) if result.directory is not None else None
    )
    manifest.delivery_report_json = (
        str(result.report_json)
        if result.report_json is not None
        else None
    )
    manifest.delivery_report_markdown = (
        str(result.report_markdown)
        if result.report_markdown is not None
        else None
    )
    manifest.delivery_summary_markdown = str(result.summary_markdown)
    manifest.delivery_manifest_json = str(result.delivery_manifest_json)
    manifest.delivery_artifact_count = len(result.artifacts)
    manifest.delivery_missing_artifact_count = len(
        result.missing_artifacts
    )
    manifest.delivery_error = result.error
    manifest.overall_status = result.overall_status


def _mark_delivery_failed(manifest: RunManifest, message: str) -> None:
    """记录交付整理失败，不覆盖提取和审核状态。"""

    manifest.delivery_status = DELIVERY_STATUS_FAILED
    manifest.delivery_finished_at = utc_now_iso()
    manifest.delivery_error = message
    manifest.overall_status = OVERALL_STATUS_FAILED


def _print_extraction_summary(
    result: Project1ExtractionResult,
    manifest: RunManifest,
    manifest_path: Path,
    task_dir: Path,
    config: ProjectConfig,
) -> None:
    """输出项目一提取结果摘要。"""

    typer.echo("阶段 3：项目一提取结果。")
    typer.echo(f"任务目录：{task_dir}")
    typer.echo(f"manifest：{manifest_path}")
    typer.echo(f"有效输入：{manifest.input_count}")
    typer.echo(f"过滤输入：{len(manifest.filtered_inputs)}")
    typer.echo(f"项目一根目录：{config.project1_root}")
    typer.echo(f"项目一 Python：{config.project1_python}")
    typer.echo(f"提取模式：{result.mode}")
    typer.echo(f"提取状态：{result.status}")
    typer.echo(f"退出码：{result.exit_code}")
    typer.echo(f"batch_id：{result.batch.batch_id if result.batch else '-'}")
    typer.echo(f"batch.json：{result.batch_path or '-'}")
    if result.batch is not None:
        typer.echo(f"文档总数：{result.batch.document_count}")
        typer.echo(
            f"成功文档：{result.batch.successful_document_count}"
        )
        typer.echo(f"失败文档：{result.batch.failed_document_count}")
        typer.echo(f"警告数量：{result.batch.warning_count}")
        for item in result.batch.documents:
            if not item.succeeded:
                typer.echo(
                    f"- 失败文档：{item.source_file}：{item.error}"
                )
    typer.echo(f"stdout 日志：{result.stdout_log_path}")
    typer.echo(f"stderr 日志：{result.stderr_log_path}")
    if result.error:
        typer.echo(f"提取错误：{result.error}")


def _print_audit_skipped(
    task_dir: Path,
    manifest: RunManifest,
    manifest_path: Path,
) -> None:
    """输出审核未执行摘要。"""

    typer.echo("阶段 4：项目二审核未执行。")
    typer.echo(f"任务目录：{task_dir}")
    typer.echo(f"manifest：{manifest_path}")
    typer.echo(f"审核状态：{manifest.audit_status}")
    typer.echo(f"整体状态：{manifest.overall_status}")
    typer.echo(f"原因：{manifest.audit_error or '-'}")


def _print_audit_summary(
    result: Project2AuditResult,
    manifest: RunManifest,
    manifest_path: Path,
    task_dir: Path,
    config: ProjectConfig,
) -> None:
    """输出项目二审核结果摘要。"""

    typer.echo("阶段 4：项目二审核结果。")
    typer.echo(f"任务目录：{task_dir}")
    typer.echo(f"manifest：{manifest_path}")
    typer.echo(f"项目二根目录：{config.project2_root}")
    typer.echo(f"项目二 Python：{config.project2_python}")
    typer.echo(f"审核状态：{result.status}")
    typer.echo(f"整体状态：{manifest.overall_status}")
    typer.echo(f"退出码：{result.exit_code}")
    if result.summary is not None:
        summary = result.summary
        typer.echo(
            "complete_success："
            f"{'是' if summary.complete_success else '否'}"
        )
        typer.echo(f"审核问题数：{summary.counts['issue_count']}")
        typer.echo(
            f"unverified：{summary.counts['unverified_count']}"
        )
        typer.echo(
            "批注人工核实数："
            f"{summary.counts['annotation_manual_review_count']}"
        )
        typer.echo(
            "问题级人工核实标记数："
            f"{summary.counts['issues_flagged_for_manual_review']}"
        )
        typer.echo(
            "错别字问题数："
            f"{summary.typo_counts['typo_issue_count']}"
        )
        typer.echo(f"审核警告数：{len(summary.warnings)}")
        typer.echo(f"审核报告 JSON：{summary.audit_json_path}")
        typer.echo(
            f"审核报告 Markdown：{summary.audit_markdown_path or '-'}"
        )
        typer.echo(
            f"批注阶段报告：{summary.annotation_report_path or '-'}"
        )
        typer.echo(
            f"数学校验报告：{summary.math_validation_path or '-'}"
        )
        typer.echo(f"批注文件数：{len(summary.output_files)}")
        for path in summary.output_files:
            typer.echo(f"- 批注文件：{path}")
    typer.echo(f"stdout 日志：{result.stdout_log_path}")
    typer.echo(f"stderr 日志：{result.stderr_log_path}")
    if result.error:
        typer.echo(f"审核错误：{result.error}")
    for item in result.errors:
        typer.echo(f"审核产物问题：{item}")


def _print_delivery_summary(
    result: DeliveryResult,
    manifest_path: Path,
    task_dir: Path,
) -> None:
    """输出最终交付摘要。"""

    typer.echo("阶段 5：最终交付目录。")
    typer.echo(f"任务目录：{task_dir}")
    typer.echo(f"manifest：{manifest_path}")
    typer.echo(f"交付状态：{result.status}")
    typer.echo(f"整体状态：{result.overall_status}")
    typer.echo(f"交付目录：{result.directory or '-'}")
    typer.echo(f"审核报告 JSON：{result.report_json or '-'}")
    typer.echo(f"审核报告 Markdown：{result.report_markdown or '-'}")
    typer.echo(f"运行摘要：{result.summary_markdown}")
    typer.echo(f"交付清单：{result.delivery_manifest_json}")
    typer.echo(f"交付文件数：{len(result.artifacts)}")
    typer.echo(f"缺失交付项：{len(result.missing_artifacts)}")
    for item in result.missing_artifacts:
        typer.echo(f"- 缺失：{item.name}：{item.reason}")
    for item in result.warnings:
        typer.echo(f"- 交付警告：{item}")
    if result.error:
        typer.echo(f"交付错误：{result.error}")


def main() -> None:
    """命令行脚本入口。"""

    try:
        app(prog_name="project3")
    except Project3Error as exc:
        _abort(exc)


__all__ = [
    "ExitCode",
    "ParseMode",
    "app",
    "deliver",
    "main",
    "resume",
    "run",
]
