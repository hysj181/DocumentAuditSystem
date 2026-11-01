"""项目二 audit 子进程适配与审核报告校验。

本模块只通过命令行调用项目二，不导入项目二内部模块。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from project3_cli_workflow.config import ProjectConfig
from project3_cli_workflow.errors import (
    AuditValidationError,
    InputError,
    ManifestError,
    Project2StageError,
)
from project3_cli_workflow.manifest import utc_now_iso
from project3_cli_workflow.models import (
    AUDIT_STATUS_FAILED,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_SUCCESS,
)
from project3_cli_workflow.process import redact_text, run_process

AUDIT_REPORT_SCHEMA_VERSION = "1.0"
STDERR_TAIL_LIMIT = 2000
COUNT_FIELDS = (
    "record_count",
    "verified_count",
    "unverified_count",
    "issue_count",
    "located_count",
    "annotation_applied_count",
    "annotation_failed_count",
    "annotation_manual_review_count",
    "issues_flagged_for_manual_review",
)
TYPO_COUNT_FIELDS = (
    "typo_issue_count",
    "typo_verified_count",
    "typo_manual_review_count",
    "typo_annotation_success_count",
    "typo_annotation_failed_count",
)
STAGE_REPORT_KEYS = (
    "audit_json",
    "audit_markdown",
    "annotation_json",
    "annotation_markdown",
    "math_validation",
)


@dataclass(frozen=True)
class AuditSummary:
    """项目二审核报告的结构化摘要。"""

    batch_id: str
    complete_success: bool
    counts: dict[str, int]
    typo_counts: dict[str, int]
    warnings: list[str]
    stage_reports: dict[str, str]
    output_files: list[Path]
    audit_json_path: Path
    audit_markdown_path: Path | None
    annotation_report_path: Path | None
    math_validation_path: Path | None


@dataclass(frozen=True)
class Project2AuditResult:
    """项目二审核阶段结果。"""

    status: str
    command: list[str]
    started_at: str
    finished_at: str
    duration_seconds: float
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_log_path: Path
    stderr_log_path: Path
    report_path: Path | None = None
    summary: AuditSummary | None = None
    error: str | None = None
    errors: list[str] = field(default_factory=list)


def _require_dict(value: Any, field_name: str) -> dict[str, Any]:
    """校验字典字段。"""

    if not isinstance(value, dict):
        raise AuditValidationError(f"{field_name} 必须是对象。")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    """校验列表字段。"""

    if not isinstance(value, list):
        raise AuditValidationError(f"{field_name} 必须是数组。")
    return value


def _require_non_empty_string(value: Any, field_name: str) -> str:
    """校验非空字符串字段。"""

    if not isinstance(value, str) or not value.strip():
        raise AuditValidationError(f"{field_name} 必须是非空字符串。")
    return value


def _require_int(value: Any, field_name: str) -> int:
    """校验整数字段。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise AuditValidationError(f"{field_name} 必须是整数。")
    return value


def _resolve_artifact(value: Any, report_path: Path) -> Path | None:
    """把报告中的产物路径解析为绝对路径。"""

    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = report_path.parent / path
    return path.resolve()


def _load_json(path: Path) -> dict[str, Any]:
    """读取并解析审核报告 JSON。"""

    if not path.is_file():
        raise AuditValidationError(f"审核报告不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditValidationError(
            f"审核报告无法解析：{path}；{exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AuditValidationError(f"审核报告顶层必须是对象：{path}")
    return payload


def load_audit_report(
    path: str | Path,
    expected_batch_id: str,
) -> AuditSummary:
    """读取并校验项目二真实审核报告。"""

    report_path = Path(path).expanduser().resolve()
    payload = _load_json(report_path)

    schema_version = payload.get("schema_version")
    if schema_version != AUDIT_REPORT_SCHEMA_VERSION:
        raise AuditValidationError(
            "不支持的审核报告 schema_version："
            f"{schema_version!r}，当前仅支持 "
            f"{AUDIT_REPORT_SCHEMA_VERSION!r}。"
        )

    _require_non_empty_string(payload.get("report_id"), "report_id")
    batch_id = _require_non_empty_string(payload.get("batch_id"), "batch_id")
    if batch_id != expected_batch_id:
        raise AuditValidationError(
            "审核报告 batch_id 与输入批次不一致："
            f"{batch_id!r} != {expected_batch_id!r}。"
        )
    _require_list(payload.get("warnings"), "warnings")

    metadata = _require_dict(payload.get("metadata"), "metadata")
    pipeline = _require_dict(metadata.get("pipeline"), "metadata.pipeline")
    complete_success = pipeline.get("complete_success")
    if not isinstance(complete_success, bool):
        raise AuditValidationError(
            "metadata.pipeline.complete_success 必须是布尔值。"
        )

    counts_payload = _require_dict(
        pipeline.get("counts"),
        "metadata.pipeline.counts",
    )
    counts = {
        name: _require_int(
            counts_payload.get(name),
            f"metadata.pipeline.counts.{name}",
        )
        for name in COUNT_FIELDS
    }

    typo_payload = _require_dict(
        pipeline.get("typo_counts"),
        "metadata.pipeline.typo_counts",
    )
    typo_counts = {
        name: _require_int(
            typo_payload.get(name),
            f"metadata.pipeline.typo_counts.{name}",
        )
        for name in TYPO_COUNT_FIELDS
    }

    pipeline_warnings = _require_list(
        pipeline.get("warnings"),
        "metadata.pipeline.warnings",
    )
    warnings = list(
        dict.fromkeys(
            [
                str(item)
                for item in payload.get("warnings", [])
                + pipeline_warnings
            ]
        )
    )

    stage_payload = _require_dict(
        pipeline.get("stage_reports"),
        "metadata.pipeline.stage_reports",
    )
    stage_reports: dict[str, str] = {}
    for key in STAGE_REPORT_KEYS:
        value = stage_payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AuditValidationError(
                f"metadata.pipeline.stage_reports.{key} 必须是非空字符串。"
            )
        stage_reports[key] = value

    output_payload = _require_list(
        pipeline.get("output_files"),
        "metadata.pipeline.output_files",
    )
    output_files = [
        path
        for path in (
            _resolve_artifact(item, report_path) for item in output_payload
        )
        if path is not None
    ]

    audit_markdown_path = _resolve_artifact(
        stage_reports["audit_markdown"],
        report_path,
    )
    annotation_report_path = _resolve_artifact(
        stage_reports["annotation_json"],
        report_path,
    )
    math_validation_path = _resolve_artifact(
        stage_reports["math_validation"],
        report_path,
    )

    return AuditSummary(
        batch_id=batch_id,
        complete_success=complete_success,
        counts=counts,
        typo_counts=typo_counts,
        warnings=warnings,
        stage_reports=stage_reports,
        output_files=output_files,
        audit_json_path=report_path,
        audit_markdown_path=audit_markdown_path,
        annotation_report_path=annotation_report_path,
        math_validation_path=math_validation_path,
    )


def find_audit_report(
    audit_root: str | Path,
    expected_batch_id: str,
) -> Path | None:
    """在项目二输出目录中查找匹配 batch_id 的审核报告。"""

    report_dir = Path(audit_root).expanduser() / "reports"
    if not report_dir.is_dir():
        return None
    candidates = list(report_dir.glob("audit_report_*.json"))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (item.stat().st_mtime_ns, str(item)),
        reverse=True,
    )
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("batch_id") == (
            expected_batch_id
        ):
            return candidate
    return candidates[0]


def read_batch_id(batch_json: str | Path) -> str:
    """从项目一 batch.json 读取 batch_id。"""

    batch_path = Path(batch_json).expanduser()
    if not batch_path.is_file():
        raise AuditValidationError(f"项目一 batch.json 不存在：{batch_path}")
    try:
        payload = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditValidationError(
            f"无法读取项目一 batch.json：{batch_path}；{exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AuditValidationError("项目一 batch.json 顶层必须是对象。")
    return _require_non_empty_string(payload.get("batch_id"), "batch_id")


def build_audit_command(
    config: ProjectConfig,
    batch_json: str | Path,
    output_dir: str | Path,
) -> list[str]:
    """根据项目二真实 CLI 构造 audit 命令。"""

    batch_path = Path(batch_json).expanduser().resolve()
    if not batch_path.is_file():
        raise AuditValidationError(f"项目一 batch.json 不存在：{batch_path}")
    return [
        str(config.project2_python),
        str(config.project2_root / "main.py"),
        "audit",
        "--batch-json",
        str(batch_path),
        "--output-dir",
        str(Path(output_dir).expanduser().resolve()),
    ]


def _write_log(path: Path, content: str) -> Path:
    """写入 UTF-8 日志文件。"""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"无法写入审核日志：{path}；{exc}") from exc
    return path


def _stderr_tail(stderr: str) -> str:
    """截取 stderr 末尾内容。"""

    text = stderr.strip()
    if len(text) <= STDERR_TAIL_LIMIT:
        return text
    return text[-STDERR_TAIL_LIMIT:]


def _audit_environment() -> dict[str, str]:
    """构造项目二子进程环境，不记录敏感环境变量。"""

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _artifact_problems(summary: AuditSummary) -> list[str]:
    """检查报告中声明的产物是否存在。"""

    problems: list[str] = []
    if (
        summary.audit_markdown_path is None
        or not summary.audit_markdown_path.is_file()
    ):
        problems.append("审核报告 Markdown 不存在。")
    if (
        summary.annotation_report_path is None
        or not summary.annotation_report_path.is_file()
    ):
        problems.append("批注阶段 JSON 报告不存在。")
    if (
        summary.math_validation_path is None
        or not summary.math_validation_path.is_file()
    ):
        problems.append("数学校验报告不存在。")
    missing_outputs = [
        str(path) for path in summary.output_files if not path.is_file()
    ]
    if missing_outputs:
        problems.append("批注文件不存在：" + "；".join(missing_outputs))
    return problems


def run_project2_audit(
    config: ProjectConfig,
    batch_json: str | Path,
    task_dir: str | Path,
    *,
    timeout: float,
) -> Project2AuditResult:
    """调用项目二 audit 并读取、校验审核报告。"""

    if timeout <= 0:
        raise InputError("项目二审核超时时间必须大于 0 秒。")

    batch_path = Path(batch_json).expanduser().resolve()
    if not batch_path.is_file():
        raise AuditValidationError(f"项目一 batch.json 不存在：{batch_path}")
    main_script = config.project2_root / "main.py"
    if not main_script.is_file():
        raise Project2StageError(f"项目二入口不存在：{main_script}")
    expected_batch_id = read_batch_id(batch_path)

    task_path = Path(task_dir).expanduser().resolve()
    audit_root = task_path / "02_audit"
    log_dir = task_path / "04_logs"
    command = build_audit_command(config, batch_path, audit_root)
    started_at = utc_now_iso()
    process = run_process(
        command,
        cwd=config.project2_root,
        timeout=timeout,
        env=_audit_environment(),
    )
    finished_at = utc_now_iso()

    token = os.environ.get("PADDLEOCR_ACCESS_TOKEN", "")
    secrets = (token,) if token else ()
    stdout = redact_text(process.stdout, secrets)
    stderr = redact_text(process.stderr, secrets)
    stdout_log = _write_log(log_dir / "project2_audit.stdout.log", stdout)
    stderr_log = _write_log(log_dir / "project2_audit.stderr.log", stderr)

    status = AUDIT_STATUS_FAILED
    error: str | None = None
    report_path: Path | None = None
    summary: AuditSummary | None = None
    errors: list[str] = []

    if process.start_failed:
        error = redact_text(process.error or "项目二进程启动失败。", secrets)
    elif process.timed_out:
        error = redact_text(process.error or "项目二审核超时。", secrets)
    else:
        report_path = find_audit_report(audit_root, expected_batch_id)
        if report_path is None:
            tail = _stderr_tail(stderr)
            error = f"项目二未生成审核报告，退出码：{process.exit_code}。"
            if tail:
                error = f"{error} stderr：{tail}"
        else:
            try:
                summary = load_audit_report(report_path, expected_batch_id)
            except AuditValidationError as exc:
                error = redact_text(exc.message, secrets)
            else:
                if not summary.complete_success:
                    status = AUDIT_STATUS_PARTIAL
                    error = "项目二审核完成，但存在人工核实或结果不完整。"
                elif process.exit_code != 0:
                    status = AUDIT_STATUS_PARTIAL
                    error = f"项目二退出码非 0：{process.exit_code}。"
                else:
                    status = AUDIT_STATUS_SUCCESS

                artifact_problems = _artifact_problems(summary)
                if artifact_problems:
                    status = AUDIT_STATUS_PARTIAL
                    errors.extend(artifact_problems)
                    if error is None:
                        error = "审核产物不完整。"
                error = redact_text(error, secrets) if error else None

    return Project2AuditResult(
        status=status,
        command=command,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=process.duration_seconds,
        exit_code=process.exit_code,
        stdout=stdout,
        stderr=stderr,
        stdout_log_path=stdout_log,
        stderr_log_path=stderr_log,
        report_path=report_path,
        summary=summary,
        error=error,
        errors=errors,
    )
