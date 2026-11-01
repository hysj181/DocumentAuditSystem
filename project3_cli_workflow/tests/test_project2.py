"""项目二命令构造、子进程调用和审核报告校验测试。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from project3_cli_workflow.config import ProjectConfig
from project3_cli_workflow.errors import AuditValidationError, InputError
from project3_cli_workflow.models import (
    AUDIT_STATUS_FAILED,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_SUCCESS,
)
from project3_cli_workflow.project2 import (
    build_audit_command,
    find_audit_report,
    load_audit_report,
    read_batch_id,
    run_project2_audit,
)


def _create_project(tmp_path: Path) -> ProjectConfig:
    """创建模拟项目一和项目二配置。"""

    project1_root = tmp_path / "project1"
    project1_root.mkdir()
    (project1_root / "main.py").write_text("", encoding="utf-8")
    project1_python = project1_root / "python.exe"
    project1_python.write_text("", encoding="utf-8")

    project2_root = tmp_path / "project2"
    project2_root.mkdir()
    (project2_root / "main.py").write_text("", encoding="utf-8")
    project2_python = project2_root / "python.exe"
    project2_python.write_text("", encoding="utf-8")

    return ProjectConfig.from_overrides(
        project1_root=project1_root,
        project1_python=project1_python,
        project2_root=project2_root,
        project2_python=project2_python,
    )


def _write_batch_json(tmp_path: Path, batch_id: str = "batch-test") -> Path:
    """写入最小项目一批次 JSON。"""

    path = tmp_path / "extraction" / "batches" / batch_id / "batch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "batch_id": batch_id,
                "documents": [],
                "environmental": {"records": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _base_counts() -> dict[str, int]:
    """返回项目二真实 counts 字段。"""

    return {
        "record_count": 5,
        "verified_count": 0,
        "unverified_count": 5,
        "issue_count": 2,
        "located_count": 2,
        "annotation_applied_count": 1,
        "annotation_failed_count": 0,
        "annotation_manual_review_count": 1,
        "issues_flagged_for_manual_review": 2,
    }


def _base_typo_counts() -> dict[str, int]:
    """返回项目二真实 typo_counts 字段。"""

    return {
        "typo_issue_count": 1,
        "typo_verified_count": 1,
        "typo_manual_review_count": 0,
        "typo_annotation_success_count": 1,
        "typo_annotation_failed_count": 0,
    }


def _write_audit_report(
    audit_root: Path,
    batch_id: str = "batch-test",
    *,
    complete_success: bool = True,
    counts: dict[str, int] | None = None,
    typo_counts: dict[str, int] | None = None,
    warnings: list[str] | None = None,
    output_files: list[str] | None = None,
    remove_pipeline_keys: tuple[str, ...] = (),
    remove_stage_keys: tuple[str, ...] = (),
    missing_markdown: bool = False,
    invalid_json: bool = False,
) -> dict[str, Path]:
    """写入模拟项目二审核报告及声明产物。"""

    reports = audit_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / f"audit_report_{batch_id}.json"
    if invalid_json:
        json_path.write_text("{invalid json", encoding="utf-8")
        return {"json": json_path}

    markdown_path = reports / f"audit_report_{batch_id}.md"
    if not missing_markdown:
        markdown_path.write_text("# 审核报告\n", encoding="utf-8")
    annotation_path = reports / f"annotation_report_{batch_id}.json"
    annotation_path.write_text("{}", encoding="utf-8")
    annotation_md_path = reports / f"annotation_report_{batch_id}.md"
    annotation_md_path.write_text("# 批注报告\n", encoding="utf-8")
    math_path = reports / f"{batch_id}_math_validation.json"
    math_path.write_text("{}", encoding="utf-8")

    annotated_files = list(output_files or [])
    for path_text in annotated_files:
        path = Path(path_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("annotated", encoding="utf-8")

    effective_counts = _base_counts()
    effective_counts.update(counts or {})
    effective_typos = _base_typo_counts()
    effective_typos.update(typo_counts or {})
    effective_warnings = list(warnings or [])

    stage_reports: dict[str, str] = {
        "audit_json": str(json_path),
        "audit_markdown": str(markdown_path),
        "annotation_json": str(annotation_path),
        "annotation_markdown": str(annotation_md_path),
        "math_validation": str(math_path),
    }
    for key in remove_stage_keys:
        stage_reports.pop(key, None)

    pipeline: dict[str, object] = {
        "synthetic_data": False,
        "complete_success": complete_success,
        "input": {},
        "timing": {},
        "counts": effective_counts,
        "typo_counts": effective_typos,
        "stages": {},
        "output_files": annotated_files,
        "stage_reports": stage_reports,
        "warnings": effective_warnings,
        "errors": [],
    }
    for key in remove_pipeline_keys:
        pipeline.pop(key, None)

    payload = {
        "schema_version": "1.0",
        "report_id": "audit-test",
        "batch_id": batch_id,
        "generated_at": "2026-11-01T00:00:00+00:00",
        "source_batch": str(
            audit_root.parent / "extraction" / "batches" / batch_id
            / "batch.json"
        ),
        "documents": [],
        "summary": {},
        "issues": [],
        "annotations": [],
        "warnings": effective_warnings,
        "metadata": {"annotation_task": {}, "pipeline": pipeline},
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "json": json_path,
        "markdown": markdown_path,
        "annotation": annotation_path,
        "annotation_markdown": annotation_md_path,
        "math": math_path,
    }


def _install_fake_audit(
    monkeypatch: pytest.MonkeyPatch,
    *,
    report_kwargs: dict[str, object] | None = None,
    no_report: bool = False,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> list[tuple[list[str], dict[str, object]]]:
    """替换 subprocess.run，按 audit 命令生成模拟报告。"""

    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        if not no_report:
            output_dir = Path(command[command.index("--output-dir") + 1])
            batch_path = Path(command[command.index("--batch-json") + 1])
            batch_id = json.loads(
                batch_path.read_text(encoding="utf-8")
            )["batch_id"]
            _write_audit_report(
                output_dir,
                batch_id,
                **(report_kwargs or {}),
            )
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )
    return calls


def test_build_audit_command_uses_real_cli(tmp_path: Path) -> None:
    """审核命令应使用项目二真实参数和绝对路径。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)
    audit_root = tmp_path / "task" / "02_audit"

    command = build_audit_command(config, batch_path, audit_root)

    assert command[0] == str(config.project2_python)
    assert command[1] == str(config.project2_root / "main.py")
    assert command[2] == "audit"
    assert command[command.index("--batch-json") + 1] == str(
        batch_path.resolve()
    )
    assert command[command.index("--output-dir") + 1] == str(
        audit_root.resolve()
    )


def test_read_batch_id(tmp_path: Path) -> None:
    """应从项目一 batch.json 读取 batch_id。"""

    batch_path = _write_batch_json(tmp_path, "batch-123")
    assert read_batch_id(batch_path) == "batch-123"


def test_load_audit_report_valid(tmp_path: Path) -> None:
    """应解析真实审核报告的关键字段和产物路径。"""

    output_file = tmp_path / "02_audit" / "annotated" / "a_annotated.docx"
    report = _write_audit_report(
        tmp_path / "02_audit",
        counts={"issue_count": 3, "unverified_count": 4},
        output_files=[str(output_file)],
        warnings=["警告一"],
    )

    summary = load_audit_report(report["json"], "batch-test")

    assert summary.batch_id == "batch-test"
    assert summary.complete_success is True
    assert summary.counts["issue_count"] == 3
    assert summary.counts["unverified_count"] == 4
    assert summary.counts["annotation_manual_review_count"] == 1
    assert summary.typo_counts["typo_issue_count"] == 1
    assert summary.warnings == ["警告一"]
    assert summary.output_files == [output_file.resolve()]
    assert summary.audit_markdown_path == report["markdown"].resolve()
    assert summary.annotation_report_path == report["annotation"].resolve()
    assert summary.math_validation_path == report["math"].resolve()


def test_load_audit_report_missing_required_field(tmp_path: Path) -> None:
    """缺少 pipeline.counts 时应失败。"""

    report = _write_audit_report(
        tmp_path / "02_audit",
        remove_pipeline_keys=("counts",),
    )

    with pytest.raises(AuditValidationError, match="counts"):
        load_audit_report(report["json"], "batch-test")


def test_load_audit_report_batch_id_mismatch(tmp_path: Path) -> None:
    """报告 batch_id 不一致时应失败。"""

    report = _write_audit_report(tmp_path / "02_audit")

    with pytest.raises(AuditValidationError, match="batch_id"):
        load_audit_report(report["json"], "other-batch")


def test_find_audit_report_matches_batch_id(tmp_path: Path) -> None:
    """应优先查找与 batch_id 匹配的报告。"""

    audit_root = tmp_path / "02_audit"
    older = _write_audit_report(audit_root, "batch-old")
    expected = _write_audit_report(audit_root, "batch-test")
    assert older["json"].exists()

    assert find_audit_report(audit_root, "batch-test") == expected["json"]


def test_run_project2_audit_success(tmp_path: Path, monkeypatch) -> None:
    """正常审核应记录命令、日志、报告和统计。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)
    task_dir = tmp_path / "task"
    output_file = task_dir / "02_audit" / "annotated" / "a_annotated.docx"
    calls = _install_fake_audit(
        monkeypatch,
        report_kwargs={"output_files": [str(output_file)]},
        stdout="审核完成",
        stderr="",
    )

    result = run_project2_audit(
        config,
        batch_path,
        task_dir,
        timeout=60,
    )

    assert result.status == AUDIT_STATUS_SUCCESS
    assert result.summary is not None
    assert result.summary.audit_json_path.is_file()
    assert result.summary.audit_markdown_path is not None
    assert result.summary.audit_markdown_path.is_file()
    assert result.summary.output_files == [output_file.resolve()]
    assert result.stdout == "审核完成"
    assert result.stdout_log_path.is_file()
    assert result.stderr_log_path.is_file()
    command, kwargs = calls[0]
    assert command[0] == str(config.project2_python)
    assert kwargs["cwd"] == str(config.project2_root)
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 60


def test_run_project2_audit_complete_success_false(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """complete_success=False 应标记 audit_partial。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)
    _install_fake_audit(
        monkeypatch,
        report_kwargs={"complete_success": False},
    )

    result = run_project2_audit(
        config,
        batch_path,
        tmp_path / "task",
        timeout=60,
    )

    assert result.status == AUDIT_STATUS_PARTIAL
    assert result.summary is not None
    assert result.summary.complete_success is False
    assert "人工核实" in (result.error or "")


def test_run_project2_audit_missing_report(tmp_path: Path, monkeypatch) -> None:
    """未生成审核报告时应失败。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)
    _install_fake_audit(monkeypatch, no_report=True, stderr="审核错误")

    result = run_project2_audit(
        config,
        batch_path,
        tmp_path / "task",
        timeout=60,
    )

    assert result.status == AUDIT_STATUS_FAILED
    assert "未生成审核报告" in (result.error or "")
    assert "审核错误" in (result.error or "")


def test_run_project2_audit_invalid_report_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """审核报告 JSON 无效时应失败。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)
    _install_fake_audit(
        monkeypatch,
        report_kwargs={"invalid_json": True},
    )

    result = run_project2_audit(
        config,
        batch_path,
        tmp_path / "task",
        timeout=60,
    )

    assert result.status == AUDIT_STATUS_FAILED
    assert "无法解析" in (result.error or "")


def test_run_project2_audit_missing_markdown_is_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """报告声明 Markdown 但文件不存在时结果为不完整。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)
    _install_fake_audit(
        monkeypatch,
        report_kwargs={"missing_markdown": True},
    )

    result = run_project2_audit(
        config,
        batch_path,
        tmp_path / "task",
        timeout=60,
    )

    assert result.status == AUDIT_STATUS_PARTIAL
    assert any("Markdown" in item for item in result.errors)


def test_run_project2_audit_nonzero_with_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """非零退出码但有报告时应标记不完整。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)
    _install_fake_audit(monkeypatch, returncode=1)

    result = run_project2_audit(
        config,
        batch_path,
        tmp_path / "task",
        timeout=60,
    )

    assert result.status == AUDIT_STATUS_PARTIAL
    assert "退出码非 0" in (result.error or "")


def test_run_project2_audit_start_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """项目二启动失败应记录 failed 和日志。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)

    def fake_run(command, **kwargs):
        raise FileNotFoundError("python.exe")

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_project2_audit(
        config,
        batch_path,
        tmp_path / "task",
        timeout=60,
    )

    assert result.status == AUDIT_STATUS_FAILED
    assert result.stdout_log_path.is_file()
    assert result.stderr_log_path.is_file()


def test_run_project2_audit_timeout(tmp_path: Path, monkeypatch) -> None:
    """项目二超时应返回 failed。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command,
            kwargs["timeout"],
            output="部分输出",
            stderr="部分错误",
        )

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_project2_audit(
        config,
        batch_path,
        tmp_path / "task",
        timeout=60,
    )

    assert result.status == AUDIT_STATUS_FAILED
    assert "超时" in (result.error or "")


def test_run_project2_audit_invalid_timeout(tmp_path: Path) -> None:
    """非正超时时间应在启动前失败。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)

    with pytest.raises(InputError, match="超时时间"):
        run_project2_audit(
            config,
            batch_path,
            tmp_path / "task",
            timeout=0,
        )


def test_run_project2_audit_redacts_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """项目二日志不得包含敏感环境变量。"""

    secret = "secret-token-value"
    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", secret)
    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)
    _install_fake_audit(
        monkeypatch,
        stdout=f"token={secret}",
        stderr=f"error {secret}",
    )

    result = run_project2_audit(
        config,
        batch_path,
        tmp_path / "task",
        timeout=60,
    )

    assert secret not in result.stdout
    assert secret not in result.stderr
    assert secret not in result.stdout_log_path.read_text(encoding="utf-8")
    assert secret not in result.stderr_log_path.read_text(encoding="utf-8")


def test_adapter_does_not_modify_project2_root_or_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """适配器不得修改项目二目录和项目一批次文件。"""

    config = _create_project(tmp_path)
    batch_path = _write_batch_json(tmp_path)
    batch_before = batch_path.read_bytes()
    main_before = (config.project2_root / "main.py").read_bytes()
    project_files_before = {
        path.name for path in config.project2_root.iterdir()
    }
    _install_fake_audit(monkeypatch)

    run_project2_audit(
        config,
        batch_path,
        tmp_path / "task",
        timeout=60,
    )

    assert batch_path.read_bytes() == batch_before
    assert (config.project2_root / "main.py").read_bytes() == main_before
    assert {
        path.name for path in config.project2_root.iterdir()
    } == project_files_before
