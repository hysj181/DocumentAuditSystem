"""CLI 帮助、输入解析、项目一提取和项目二审核集成测试。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from project3_cli_workflow.cli import app
from project3_cli_workflow.lock import TaskLock

runner = CliRunner()


def _create_project(
    root: Path,
    *,
    with_main: bool = False,
    version: str = "0.1.0",
) -> tuple[Path, Path]:
    """创建模拟项目目录、版本文件和 Python 解释器文件。"""

    root.mkdir(parents=True, exist_ok=True)
    python = root / "python.exe"
    python.write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "fake"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    if with_main:
        (root / "main.py").write_text("", encoding="utf-8")
    return root, python


def _write_batch(
    output_root: Path,
    inputs: list[Path],
    *,
    batch_id: str = "batch-test",
    failed_indexes: set[int] | None = None,
) -> Path:
    """按项目一真实结构写入模拟 batch.json。"""

    failed_indexes = failed_indexes or set()
    documents = []
    for index, source in enumerate(inputs):
        error = "模拟提取失败" if index in failed_indexes else None
        file_type = "word" if source.suffix.casefold() == ".docx" else "pdf"
        documents.append(
            {
                "document_id": f"doc-{index}",
                "source_name": source.name,
                "source_file": str(source.resolve()),
                "file_type": file_type,
                "record_count": 1 if error is None else 0,
                "table_count": 0,
                "records": (
                    [
                        {
                            "document_id": f"doc-{index}",
                            "source_file": str(source.resolve()),
                            "file_type": file_type,
                            "content_type": "paragraph",
                            "text": "测试内容",
                            "location": {},
                            "metadata": {},
                        }
                    ]
                    if error is None
                    else []
                ),
                "tables": [],
                "warnings": [],
                "error": error,
                "metadata": {},
            }
        )
    payload = {
        "schema_version": "1.0",
        "batch_id": batch_id,
        "extracted_at": "2026-11-01T00:00:00+00:00",
        "document_count": len(documents),
        "table_count": 0,
        "documents": documents,
        "tables": [],
        "environmental": {"records": [], "warnings": []},
    }
    batch_path = output_root / "batches" / batch_id / "batch.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return batch_path


def _base_counts() -> dict[str, int]:
    """返回项目二真实 counts 字段。"""

    return {
        "record_count": 5,
        "verified_count": 0,
        "unverified_count": 5,
        "issue_count": 0,
        "located_count": 0,
        "annotation_applied_count": 0,
        "annotation_failed_count": 0,
        "annotation_manual_review_count": 0,
        "issues_flagged_for_manual_review": 0,
    }


def _base_typo_counts() -> dict[str, int]:
    """返回项目二真实 typo_counts 字段。"""

    return {
        "typo_issue_count": 0,
        "typo_verified_count": 0,
        "typo_manual_review_count": 0,
        "typo_annotation_success_count": 0,
        "typo_annotation_failed_count": 0,
    }


def _write_audit_report(
    audit_root: Path,
    batch_id: str,
    *,
    complete_success: bool = True,
    counts: dict[str, int] | None = None,
    typo_counts: dict[str, int] | None = None,
    output_files: list[str] | None = None,
    warnings: list[str] | None = None,
) -> Path:
    """写入模拟项目二审核报告及声明产物。"""

    reports = audit_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / f"audit_report_{batch_id}.json"
    markdown_path = reports / f"audit_report_{batch_id}.md"
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

    payload = {
        "schema_version": "1.0",
        "report_id": "audit-test",
        "batch_id": batch_id,
        "generated_at": "2026-11-01T00:00:00+00:00",
        "source_batch": str(audit_root.parent / "batch.json"),
        "documents": [],
        "summary": {},
        "issues": [],
        "annotations": [],
        "warnings": effective_warnings,
        "metadata": {
            "annotation_task": {},
            "pipeline": {
                "synthetic_data": False,
                "complete_success": complete_success,
                "input": {},
                "timing": {},
                "counts": effective_counts,
                "typo_counts": effective_typos,
                "stages": {},
                "output_files": annotated_files,
                "stage_reports": {
                    "audit_json": str(json_path),
                    "audit_markdown": str(markdown_path),
                    "annotation_json": str(annotation_path),
                    "annotation_markdown": str(annotation_md_path),
                    "math_validation": str(math_path),
                },
                "warnings": effective_warnings,
                "errors": [],
            },
        },
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return json_path


def _project_arguments(tmp_path: Path) -> list[str]:
    """返回有效的项目一、项目二覆盖参数。"""

    project1_root, project1_python = _create_project(
        tmp_path / "project1",
        with_main=True,
    )
    project2_root, project2_python = _create_project(
        tmp_path / "project2",
        with_main=True,
    )
    return [
        "--project1-root",
        str(project1_root),
        "--project1-python",
        str(project1_python),
        "--project2-root",
        str(project2_root),
        "--project2-python",
        str(project2_python),
    ]


def _run_arguments(
    tmp_path: Path,
    input_files: list[Path],
    output_root: Path,
    *extra: str,
) -> list[str]:
    """构造包含有效项目配置的 run 参数。"""

    arguments = ["run"]
    arguments.extend(str(path) for path in input_files)
    arguments.extend(["--output-root", str(output_root)])
    arguments.extend(extra)
    arguments.extend(_project_arguments(tmp_path))
    return arguments


def _install_fake_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failed_indexes: set[int] | None = None,
    extraction_no_batch: bool = False,
    extraction_returncode: int = 0,
    extraction_stdout: str = "",
    extraction_stderr: str = "",
    audit_no_report: bool = False,
    audit_complete_success: bool = True,
    audit_counts: dict[str, int] | None = None,
    audit_typo_counts: dict[str, int] | None = None,
    audit_output_files: list[str] | None = None,
    audit_stdout: str = "",
    audit_stderr: str = "",
) -> list[tuple[list[str], dict[str, object]]]:
    """替换 subprocess.run，同时模拟项目一提取和项目二审核。"""

    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        stage = command[2]
        if stage == "extract":
            if not extraction_no_batch:
                output_root = Path(
                    command[command.index("--output-root") + 1]
                )
                inputs = [
                    Path(command[index + 1])
                    for index, item in enumerate(command)
                    if item == "--input"
                ]
                _write_batch(
                    output_root,
                    inputs,
                    failed_indexes=failed_indexes,
                )
            return subprocess.CompletedProcess(
                command,
                extraction_returncode,
                stdout=extraction_stdout,
                stderr=extraction_stderr,
            )
        if stage == "audit":
            if not audit_no_report:
                output_dir = Path(
                    command[command.index("--output-dir") + 1]
                )
                batch_path = Path(
                    command[command.index("--batch-json") + 1]
                )
                batch_id = json.loads(
                    batch_path.read_text(encoding="utf-8")
                )["batch_id"]
                _write_audit_report(
                    output_dir,
                    batch_id,
                    complete_success=audit_complete_success,
                    counts=audit_counts,
                    typo_counts=audit_typo_counts,
                    output_files=audit_output_files,
                )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=audit_stdout,
                stderr=audit_stderr,
            )
        raise AssertionError(f"未知子命令：{stage}")

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )
    return calls


def _load_manifest(output_root: Path) -> tuple[Path, dict[str, object]]:
    """读取任务目录中的 manifest。"""

    manifest_path = next(output_root.glob("*/manifest.json"))
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest_path, payload


def test_root_help() -> None:
    """project3 --help 应显示 run 命令。"""

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.output


def test_run_help() -> None:
    """project3 run --help 应显示项目一、项目二参数。"""

    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--output-root" in result.output
    assert "--project1-root" in result.output
    assert "--project1-python" in result.output
    assert "--project2-root" in result.output
    assert "--project2-python" in result.output
    assert "--mode" in result.output
    assert "--extraction-timeout" in result.output
    assert "--audit-timeout" in result.output


def test_run_generates_manifest_and_audit_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功流程应记录提取和审核两个阶段的真实结果。"""

    content = "测试 Word 内容".encode()
    input_file = tmp_path / "报告.docx"
    input_file.write_bytes(content)
    output_root = tmp_path / "output"
    _install_fake_pipeline(
        monkeypatch,
        extraction_stdout="提取完成",
        audit_stdout="审核完成",
        audit_counts={
            "issue_count": 2,
            "unverified_count": 5,
            "annotation_manual_review_count": 1,
            "issues_flagged_for_manual_review": 2,
        },
        audit_typo_counts={"typo_issue_count": 1},
    )

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 0
    manifest_path, payload = _load_manifest(output_root)
    assert payload["status"] == "audit_success"
    assert payload["overall_status"] == "success"
    assert payload["extraction_status"] == "extraction_success"
    assert payload["audit_status"] == "audit_success"
    assert payload["batch_id"] == "batch-test"
    assert payload["document_count"] == 1
    assert payload["successful_document_count"] == 1
    assert payload["failed_document_count"] == 0
    assert payload["audit_complete_success"] is True
    assert payload["audit_issue_count"] == 2
    assert payload["audit_unverified_count"] == 5
    assert payload["audit_manual_review_count"] == 1
    assert payload["audit_issues_flagged_for_manual_review_count"] == 2
    assert payload["audit_typo_counts"]["typo_issue_count"] == 1

    batch_path = Path(payload["batch_json_path"])
    assert batch_path.is_file()
    assert manifest_path.parent / "01_extraction" in batch_path.parents
    assert Path(payload["extraction_stdout_log"]).is_file()
    assert Path(payload["extraction_stderr_log"]).is_file()
    assert Path(payload["audit_stdout_log"]).is_file()
    assert Path(payload["audit_stderr_log"]).is_file()
    assert Path(payload["audit_report_json"]).is_file()
    assert Path(payload["audit_report_markdown"]).is_file()
    assert Path(payload["annotation_report"]).is_file()
    assert Path(payload["math_validation_report"]).is_file()
    assert payload["delivery_status"] == "delivery_success"
    assert payload["delivery_missing_artifact_count"] == 0
    assert Path(payload["delivery_directory"]).is_dir()
    assert Path(payload["delivery_report_json"]).is_file()
    assert Path(payload["delivery_report_markdown"]).is_file()
    assert Path(payload["delivery_summary_markdown"]).is_file()
    assert Path(payload["delivery_manifest_json"]).is_file()
    assert "阶段 4" in result.output
    assert "阶段 5" in result.output


def test_run_default_local_gpu_and_repeated_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认模式为 local_gpu，多文件必须重复 --input。"""

    first = tmp_path / "a.docx"
    second = tmp_path / "b.pdf"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    output_root = tmp_path / "output"
    calls = _install_fake_pipeline(monkeypatch)

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [first, second], output_root),
    )

    assert result.exit_code == 0
    extract_command, extract_kwargs = calls[0]
    audit_command, audit_kwargs = calls[1]
    assert extract_command.count("--input") == 2
    assert extract_command[extract_command.index("--mode") + 1] == (
        "local_gpu"
    )
    assert extract_kwargs["cwd"] == str(
        (tmp_path / "project1").resolve()
    )
    assert extract_kwargs["shell"] is False
    assert audit_command[2] == "audit"
    assert audit_kwargs["cwd"] == str(
        (tmp_path / "project2").resolve()
    )
    assert audit_kwargs["shell"] is False


def test_run_cloud_api_must_be_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式 cloud_api 应传入项目一命令。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    calls = _install_fake_pipeline(monkeypatch)

    result = runner.invoke(
        app,
        _run_arguments(
            tmp_path,
            [input_file],
            output_root,
            "--mode",
            "cloud_api",
        ),
    )

    assert result.exit_code == 0
    command, _ = calls[0]
    assert command[command.index("--mode") + 1] == "cloud_api"


def test_run_extraction_partial_still_audits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """提取部分失败时项目二仍审核，整体状态保持部分完成。"""

    first = tmp_path / "a.docx"
    second = tmp_path / "b.pdf"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    output_root = tmp_path / "output"
    calls = _install_fake_pipeline(monkeypatch, failed_indexes={1})

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [first, second], output_root),
    )

    assert result.exit_code == 3
    assert len(calls) == 2
    _, payload = _load_manifest(output_root)
    assert payload["extraction_status"] == "extraction_partial"
    assert payload["audit_status"] == "audit_success"
    assert payload["overall_status"] == "partial"
    assert payload["successful_document_count"] == 1
    assert payload["failed_document_count"] == 1
    assert "失败文档" in str(payload["extraction_error"])


def test_run_audit_complete_success_false_returns_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """complete_success=False 时审核完成但整体返回 3。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(
        monkeypatch,
        audit_complete_success=False,
        audit_counts={"annotation_manual_review_count": 1},
    )

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 3
    _, payload = _load_manifest(output_root)
    assert payload["extraction_status"] == "extraction_success"
    assert payload["audit_status"] == "audit_partial"
    assert payload["overall_status"] == "partial"
    assert payload["audit_complete_success"] is False


def test_run_extraction_failed_skips_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """项目一未生成 batch.json 时不得调用项目二。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    calls = _install_fake_pipeline(
        monkeypatch,
        extraction_no_batch=True,
        extraction_stderr="未生成结果",
    )

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 4
    assert len(calls) == 1
    assert calls[0][0][2] == "extract"
    _, payload = _load_manifest(output_root)
    assert payload["extraction_status"] == "extraction_failed"
    assert payload["audit_status"] == "audit_skipped"
    assert payload["overall_status"] == "failed"
    assert payload["delivery_status"] == "delivery_failed"
    assert "未执行项目二审核" in str(payload["audit_error"])


def test_run_audit_missing_report_returns_external_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """项目二未生成审核报告时返回 4。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(
        monkeypatch,
        audit_no_report=True,
        audit_stderr="审核未生成报告",
    )

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 4
    _, payload = _load_manifest(output_root)
    assert payload["audit_status"] == "audit_failed"
    assert payload["overall_status"] == "failed"
    assert "未生成审核报告" in str(payload["audit_error"])


def test_run_timeout_returns_external_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """项目一超时应返回 4 并保留失败状态。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"

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

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 4
    _, payload = _load_manifest(output_root)
    assert payload["status"] == "audit_skipped"
    assert "超时" in str(payload["extraction_error"])


def test_run_start_failure_returns_external_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """项目一子进程启动失败应返回 4。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"

    def fake_run(command, **kwargs):
        raise FileNotFoundError("python.exe")

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 4
    _, payload = _load_manifest(output_root)
    assert payload["extraction_status"] == "extraction_failed"
    assert "无法启动项目一进程" in str(payload["extraction_error"])


def test_run_token_is_not_written_to_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Access Token 不得出现在 CLI 输出、manifest 或日志中。"""

    secret = "secret-token-value"
    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", secret)
    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(
        monkeypatch,
        extraction_stdout=f"token={secret}",
        extraction_stderr=f"error {secret}",
        audit_stdout=f"token={secret}",
        audit_stderr=f"error {secret}",
    )

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 0
    _, payload = _load_manifest(output_root)
    stdout_log = Path(str(payload["extraction_stdout_log"]))
    stderr_log = Path(str(payload["extraction_stderr_log"]))
    audit_stdout_log = Path(str(payload["audit_stdout_log"]))
    audit_stderr_log = Path(str(payload["audit_stderr_log"]))
    assert secret not in result.output
    assert secret not in json.dumps(payload, ensure_ascii=False)
    for path in (
        stdout_log,
        stderr_log,
        audit_stdout_log,
        audit_stderr_log,
    ):
        assert secret not in path.read_text(encoding="utf-8")


def test_run_uses_command_line_paths_over_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命令行路径覆盖无效环境变量，避免误用错误项目。"""

    input_file = tmp_path / "报告.docx"
    input_file.write_text("", encoding="utf-8")
    output_root = tmp_path / "output"
    missing_root = tmp_path / "missing_project1"
    monkeypatch.setenv("PROJECT1_ROOT", str(missing_root))
    _install_fake_pipeline(monkeypatch)

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 0


def test_run_missing_project_root_returns_user_input_code(tmp_path: Path) -> None:
    """配置路径无效时返回用户输入错误退出码 2。"""

    input_file = tmp_path / "报告.docx"
    input_file.write_text("", encoding="utf-8")
    project2_root, project2_python = _create_project(
        tmp_path / "project2",
        with_main=True,
    )

    result = runner.invoke(
        app,
        [
            "run",
            str(input_file),
            "--output-root",
            str(tmp_path / "output"),
            "--project1-root",
            str(tmp_path / "missing_project1"),
            "--project1-python",
            str(tmp_path / "missing_python.exe"),
            "--project2-root",
            str(project2_root),
            "--project2-python",
            str(project2_python),
        ],
    )

    assert result.exit_code == 2


def test_run_records_filtered_and_duplicate_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI 集成过滤清单和重复输入记录。"""

    docx = tmp_path / "报告.docx"
    docx.write_text("docx", encoding="utf-8")
    txt = tmp_path / "说明.txt"
    txt.write_text("txt", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)

    result = runner.invoke(
        app,
        _run_arguments(
            tmp_path,
            [docx, docx, txt],
            output_root,
        ),
    )

    assert result.exit_code == 0
    _, payload = _load_manifest(output_root)
    assert payload["input_count"] == 1
    serialized = json.dumps(payload, ensure_ascii=False)
    assert '"duplicate_input"' in serialized
    assert '"unsupported_extension"' in serialized
    assert "过滤输入：2" in result.output


def test_run_collects_annotated_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """审核报告声明的批注文件应写入 manifest。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    annotated = tmp_path / "output" / "annotated" / "a_annotated.docx"
    _install_fake_pipeline(
        monkeypatch,
        audit_output_files=[str(annotated)],
    )

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 0
    _, payload = _load_manifest(output_root)
    assert payload["annotated_files"] == [str(annotated.resolve())]


def test_deliver_command_regenerates_existing_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """deliver 命令应只读取现有任务并重新生成交付目录。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)
    run_result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert run_result.exit_code == 0
    manifest_path, payload = _load_manifest(output_root)
    shutil.rmtree(Path(str(payload["delivery_directory"])))

    result = runner.invoke(
        app,
        ["deliver", "--manifest", str(manifest_path)],
    )

    assert result.exit_code == 0
    _, refreshed = _load_manifest(output_root)
    assert Path(str(refreshed["delivery_directory"])).is_dir()
    assert Path(str(refreshed["delivery_manifest_json"])).is_file()
    assert refreshed["delivery_status"] == "delivery_success"


def test_delivery_failure_keeps_extraction_and_audit_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """交付整理失败时不能覆盖已有提取和审核状态。"""

    from project3_cli_workflow.errors import ManifestError

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)

    def fail_delivery(manifest, manifest_path):
        raise ManifestError("模拟交付失败")

    monkeypatch.setattr(
        "project3_cli_workflow.cli.run_delivery",
        fail_delivery,
    )

    result = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert result.exit_code == 5
    _, payload = _load_manifest(output_root)
    assert payload["extraction_status"] == "extraction_success"
    assert payload["audit_status"] == "audit_success"
    assert payload["delivery_status"] == "delivery_failed"
    assert payload["overall_status"] == "failed"
    assert "模拟交付失败" in str(payload["delivery_error"])


def test_run_nonexistent_input_returns_user_input_code(tmp_path: Path) -> None:
    """输入路径不存在时返回用户输入错误退出码 2。"""

    output_root = tmp_path / "output"
    result = runner.invoke(
        app,
        _run_arguments(
            tmp_path,
            [tmp_path / "不存在.docx"],
            output_root,
        ),
    )

    assert result.exit_code == 2
    assert not output_root.exists()


def test_run_requires_input_and_output_root() -> None:
    """缺少输入或输出目录时由 Typer 返回参数错误退出码 2。"""

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 2


def _fail_subprocess(*args, **kwargs):
    """验证不应再调用外部项目。"""

    raise AssertionError("不应调用项目一或项目二")


def test_run_same_input_reuses_all_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """相同输入和配置应完全复用已有任务。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("same", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 0
    manifest_path, first_payload = _load_manifest(output_root)
    first_job_id = first_payload["job_id"]

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        _fail_subprocess,
    )
    second = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert second.exit_code == 0
    manifest_path, payload = _load_manifest(output_root)
    assert payload["job_id"] == first_job_id
    assert payload["extraction_reused"] is True
    assert payload["audit_reused"] is True
    assert payload["delivery_reused"] is True
    history = payload["stage_history"]
    assert [item["stage"] for item in history[-3:]] == [
        "extraction",
        "audit",
        "delivery",
    ]
    assert all(
        item["execution"] == "reused" for item in history[-3:]
    )
    assert manifest_path.is_file()


def test_run_same_input_with_partial_status_stays_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extraction_partial 任务完全复用后仍为 partial。"""

    first = tmp_path / "a.docx"
    second_input = tmp_path / "b.pdf"
    first.write_text("a", encoding="utf-8")
    second_input.write_text("b", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch, failed_indexes={1})
    first_result = runner.invoke(
        app,
        _run_arguments(
            tmp_path,
            [first, second_input],
            output_root,
        ),
    )
    assert first_result.exit_code == 3

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        _fail_subprocess,
    )
    second_result = runner.invoke(
        app,
        _run_arguments(
            tmp_path,
            [first, second_input],
            output_root,
        ),
    )

    assert second_result.exit_code == 3
    _, payload = _load_manifest(output_root)
    assert payload["extraction_status"] == "extraction_partial"
    assert payload["overall_status"] == "partial"
    assert payload["extraction_reused"] is True


def test_run_same_input_with_audit_partial_stays_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """audit_partial 任务完全复用后仍为 partial。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch, audit_complete_success=False)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 3

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        _fail_subprocess,
    )
    second = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert second.exit_code == 3
    _, payload = _load_manifest(output_root)
    assert payload["audit_status"] == "audit_partial"
    assert payload["overall_status"] == "partial"
    assert payload["audit_reused"] is True


def test_resume_corrupt_batch_reruns_extraction_and_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """batch.json 损坏时 resume 从提取阶段重新执行。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 0
    _, payload = _load_manifest(output_root)
    Path(str(payload["batch_json_path"])).write_text(
        "{broken",
        encoding="utf-8",
    )

    calls = _install_fake_pipeline(monkeypatch)
    result = runner.invoke(
        app,
        [
            "resume",
            str(payload["job_id"]),
            "--output-root",
            str(output_root),
            *_project_arguments(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert [item[0][2] for item in calls] == ["extract", "audit"]
    _, resumed = _load_manifest(output_root)
    assert resumed["extraction_reused"] is False
    assert resumed["audit_reused"] is False
    assert resumed["extraction_status"] == "extraction_success"
    assert resumed["audit_status"] == "audit_success"


def test_resume_corrupt_audit_report_only_reruns_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """审核报告损坏时 resume 只重新执行审核和交付。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 0
    _, payload = _load_manifest(output_root)
    Path(str(payload["audit_report_json"])).write_text(
        "{broken",
        encoding="utf-8",
    )

    calls = _install_fake_pipeline(monkeypatch)
    result = runner.invoke(
        app,
        [
            "resume",
            str(payload["job_id"]),
            "--output-root",
            str(output_root),
            *_project_arguments(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert [item[0][2] for item in calls] == ["audit"]
    _, resumed = _load_manifest(output_root)
    assert resumed["extraction_reused"] is True
    assert resumed["audit_reused"] is False


def test_resume_corrupt_manifest_fails_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """manifest 损坏时应安全报错且不覆盖旧数据。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 0
    manifest_path, payload = _load_manifest(output_root)
    manifest_path.write_text("{broken", encoding="utf-8")
    before = manifest_path.read_bytes()

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        _fail_subprocess,
    )
    result = runner.invoke(
        app,
        [
            "resume",
            str(payload["job_id"]),
            "--output-root",
            str(output_root),
            *_project_arguments(tmp_path),
        ],
    )

    assert result.exit_code == 5
    assert manifest_path.read_bytes() == before


def test_run_input_change_creates_new_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """输入内容变化后不得复用旧任务，且旧任务保留。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("first", encoding="utf-8")
    output_root = tmp_path / "output"
    first_calls = _install_fake_pipeline(monkeypatch)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 0
    assert len(first_calls) == 2
    _, first_payload = _load_manifest(output_root)
    first_job_id = first_payload["job_id"]

    input_file.write_text("second", encoding="utf-8")
    second_calls = _install_fake_pipeline(monkeypatch)
    second = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )

    assert second.exit_code == 0
    assert len(second_calls) == 2
    manifests = list(output_root.glob("*/manifest.json"))
    assert len(manifests) == 2
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in manifests
    ]
    assert first_job_id in {item["job_id"] for item in payloads}
    assert len({item["job_id"] for item in payloads}) == 2


def test_resume_after_audit_interruption_reuses_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """审核中断后恢复应复用提取，只重新执行审核和交付。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch, audit_no_report=True)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 4
    manifest_path, payload = _load_manifest(output_root)
    job_id = str(payload["job_id"])
    assert payload["extraction_status"] == "extraction_success"
    assert payload["audit_status"] == "audit_failed"

    calls = _install_fake_pipeline(monkeypatch)
    result = runner.invoke(
        app,
        [
            "resume",
            job_id,
            "--output-root",
            str(output_root),
            *_project_arguments(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert [item[0][2] for item in calls] == ["audit"]
    _, resumed = _load_manifest(output_root)
    assert resumed["extraction_reused"] is True
    assert resumed["audit_reused"] is False
    assert resumed["audit_status"] == "audit_success"
    assert resumed["delivery_status"] == "delivery_success"
    assert manifest_path.is_file()


def test_resume_corrupted_delivery_only_redelivers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """交付文件损坏时 resume 只重新整理交付。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 0
    _, payload = _load_manifest(output_root)
    delivery_report = Path(str(payload["delivery_report_markdown"]))
    delivery_report.write_text("corrupted", encoding="utf-8")

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        _fail_subprocess,
    )
    result = runner.invoke(
        app,
        [
            "resume",
            str(payload["job_id"]),
            "--output-root",
            str(output_root),
            *_project_arguments(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "# 审核报告汇总" in delivery_report.read_text(encoding="utf-8")
    _, resumed = _load_manifest(output_root)
    assert resumed["extraction_reused"] is True
    assert resumed["audit_reused"] is True
    assert resumed["delivery_reused"] is False
    assert resumed["delivery_status"] == "delivery_success"


def test_resume_refuses_when_input_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """输入变化时 resume 必须拒绝使用旧任务。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("first", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 0
    manifest_path, payload = _load_manifest(output_root)
    before = manifest_path.read_bytes()
    input_file.write_text("second", encoding="utf-8")

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        _fail_subprocess,
    )
    result = runner.invoke(
        app,
        [
            "resume",
            str(payload["job_id"]),
            "--output-root",
            str(output_root),
            *_project_arguments(tmp_path),
        ],
    )

    assert result.exit_code == 2
    assert manifest_path.read_bytes() == before


def test_run_active_task_lock_returns_internal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已有有效锁时必须拒绝并发修改同一任务。"""

    input_file = tmp_path / "a.docx"
    input_file.write_text("a", encoding="utf-8")
    output_root = tmp_path / "output"
    _install_fake_pipeline(monkeypatch)
    first = runner.invoke(
        app,
        _run_arguments(tmp_path, [input_file], output_root),
    )
    assert first.exit_code == 0
    manifest_path, payload = _load_manifest(output_root)
    task_dir = manifest_path.parent
    lock = TaskLock(task_dir, str(payload["job_id"]))
    lock.acquire()
    try:
        monkeypatch.setattr(
            "project3_cli_workflow.process.subprocess.run",
            _fail_subprocess,
        )
        result = runner.invoke(
            app,
            _run_arguments(tmp_path, [input_file], output_root),
        )
        assert result.exit_code == 5
    finally:
        lock.release()
