"""项目一命令构造、子进程适配和 batch.json 校验测试。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from project3_cli_workflow.config import ProjectConfig
from project3_cli_workflow.errors import (
    BatchValidationError,
    InputError,
    Project1StageError,
)
from project3_cli_workflow.models import (
    EXTRACTION_STATUS_FAILED,
    EXTRACTION_STATUS_PARTIAL,
    EXTRACTION_STATUS_SUCCESS,
)
from project3_cli_workflow.project1 import (
    build_extract_command,
    find_batch_json,
    load_batch_summary,
    run_project1_extraction,
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
    project2_python = project2_root / "python.exe"
    project2_python.write_text("", encoding="utf-8")

    return ProjectConfig.from_overrides(
        project1_root=project1_root,
        project1_python=project1_python,
        project2_root=project2_root,
        project2_python=project2_python,
    )


def _write_batch(
    output_root: Path,
    inputs: list[Path],
    *,
    batch_id: str = "batch-test",
    failed_indexes: set[int] | None = None,
) -> Path:
    """在项目一输出目录中写入模拟 batch.json。"""

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


def _write_json(path: Path, payload: object) -> Path:
    """写入任意 JSON 测试内容。"""

    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_build_extract_command_uses_real_cli_form(tmp_path: Path) -> None:
    """命令应使用项目一真实参数并重复传递 --input。"""

    config = _create_project(tmp_path)
    first = tmp_path / "报告1.docx"
    second = tmp_path / "报告2.pdf"
    output_root = tmp_path / "01_extraction"

    command = build_extract_command(
        config,
        [first, second],
        output_root,
        "local_gpu",
    )

    assert command[0] == str(config.project1_python)
    assert command[1] == str(config.project1_root / "main.py")
    assert command[2] == "extract"
    assert command.count("--input") == 2
    assert str(first.resolve()) in command
    assert str(second.resolve()) in command
    assert command[command.index("--mode") + 1] == "local_gpu"
    assert command[command.index("--output-root") + 1] == str(
        output_root.resolve()
    )
    assert command[command.index("--save-format") + 1] == "json"


def test_build_extract_command_rejects_invalid_mode(tmp_path: Path) -> None:
    """不支持的模式必须在启动子进程前失败。"""

    config = _create_project(tmp_path)

    with pytest.raises(InputError, match="不支持的项目一解析模式"):
        build_extract_command(
            config,
            [tmp_path / "报告.docx"],
            tmp_path / "out",
            "invalid",
        )


def test_load_batch_summary_valid_and_partial(tmp_path: Path) -> None:
    """正常 batch.json 应统计成功、失败和警告数量。"""

    first = tmp_path / "a.docx"
    second = tmp_path / "b.pdf"
    batch_path = _write_batch(
        tmp_path / "extraction",
        [first, second],
        failed_indexes={1},
    )

    summary = load_batch_summary(batch_path)

    assert summary.batch_id == "batch-test"
    assert summary.schema_version == "1.0"
    assert summary.document_count == 2
    assert summary.successful_document_count == 1
    assert summary.failed_document_count == 1
    assert summary.warning_count == 0
    assert summary.documents[1].error == "模拟提取失败"


def test_load_batch_summary_missing_file(tmp_path: Path) -> None:
    """batch.json 不存在应抛 BatchValidationError。"""

    with pytest.raises(BatchValidationError, match="不存在"):
        load_batch_summary(tmp_path / "missing.json")


def test_load_batch_summary_invalid_json(tmp_path: Path) -> None:
    """batch.json 不是合法 JSON 时应明确失败。"""

    path = tmp_path / "batch.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(BatchValidationError, match="无法解析"):
        load_batch_summary(path)


def test_load_batch_summary_missing_required_field(tmp_path: Path) -> None:
    """缺少 batch_id 或 documents 时应明确失败。"""

    path = _write_json(
        tmp_path / "batch.json",
        {
            "schema_version": "1.0",
            "documents": [],
            "document_count": 0,
            "environmental": {},
        },
    )

    with pytest.raises(BatchValidationError, match="batch_id"):
        load_batch_summary(path)


def test_load_batch_summary_document_count_mismatch(tmp_path: Path) -> None:
    """document_count 与 documents 数量不一致应失败。"""

    path = _write_json(
        tmp_path / "batch.json",
        {
            "schema_version": "1.0",
            "batch_id": "batch-test",
            "document_count": 2,
            "documents": [
                {
                    "document_id": "doc-1",
                    "source_file": "a.docx",
                    "file_type": "word",
                    "records": [],
                    "warnings": [],
                    "error": None,
                }
            ],
            "environmental": {"warnings": []},
        },
    )

    with pytest.raises(BatchValidationError, match="数量不一致"):
        load_batch_summary(path)


def test_find_batch_json(tmp_path: Path) -> None:
    """应在 batches/<batch_id>/batch.json 中查找批次。"""

    source = tmp_path / "报告.docx"
    batch_path = _write_batch(tmp_path / "01_extraction", [source])

    assert find_batch_json(tmp_path / "01_extraction") == batch_path


def test_run_project1_extraction_success_uses_task_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """子进程 cwd、输出目录和 batch 读取应正确。"""

    config = _create_project(tmp_path)
    source = tmp_path / "报告.docx"
    source.write_text("docx", encoding="utf-8")
    task_dir = tmp_path / "task"
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        output_root = Path(command[command.index("--output-root") + 1])
        _write_batch(output_root, [source])
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="提取完成",
            stderr="",
        )

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_project1_extraction(
        config,
        [source],
        task_dir,
        mode="local_gpu",
        timeout=30,
    )

    assert result.status == EXTRACTION_STATUS_SUCCESS
    assert result.batch is not None
    assert result.batch.batch_id == "batch-test"
    assert result.batch_path == (
        task_dir / "01_extraction" / "batches" / "batch-test" / "batch.json"
    )
    assert captured["cwd"] == str(config.project1_root)
    assert captured["timeout"] == 30
    assert captured["shell"] is False
    assert result.stdout == "提取完成"
    assert result.stdout_log_path.is_file()
    assert result.stderr_log_path.is_file()


def test_run_project1_extraction_partial(tmp_path: Path, monkeypatch) -> None:
    """部分文档失败应标记 extraction_partial。"""

    config = _create_project(tmp_path)
    first = tmp_path / "a.docx"
    second = tmp_path / "b.pdf"
    task_dir = tmp_path / "task"

    def fake_run(command, **kwargs):
        output_root = Path(command[command.index("--output-root") + 1])
        _write_batch(output_root, [first, second], failed_indexes={1})
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_project1_extraction(
        config,
        [first, second],
        task_dir,
        mode="local_gpu",
        timeout=30,
    )

    assert result.status == EXTRACTION_STATUS_PARTIAL
    assert result.batch is not None
    assert result.batch.successful_document_count == 1
    assert result.batch.failed_document_count == 1
    assert "失败文档" in (result.error or "")


def test_run_project1_extraction_start_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """子进程启动失败应返回 extraction_failed 并写日志。"""

    config = _create_project(tmp_path)
    source = tmp_path / "报告.docx"
    task_dir = tmp_path / "task"

    def fake_run(command, **kwargs):
        raise FileNotFoundError("python.exe")

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_project1_extraction(
        config,
        [source],
        task_dir,
        mode="local_gpu",
        timeout=30,
    )

    assert result.status == EXTRACTION_STATUS_FAILED
    assert result.error is not None
    assert result.stdout_log_path.is_file()
    assert result.stderr_log_path.is_file()


def test_run_project1_extraction_timeout(tmp_path: Path, monkeypatch) -> None:
    """子进程超时应返回 extraction_failed。"""

    config = _create_project(tmp_path)
    source = tmp_path / "报告.docx"
    task_dir = tmp_path / "task"

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

    result = run_project1_extraction(
        config,
        [source],
        task_dir,
        mode="local_gpu",
        timeout=30,
    )

    assert result.status == EXTRACTION_STATUS_FAILED
    assert "超时" in (result.error or "")
    assert result.stdout == "部分输出"
    assert result.stderr == "部分错误"


def test_run_project1_extraction_nonzero_without_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """非零退出码且没有 batch.json 时应失败。"""

    config = _create_project(tmp_path)
    source = tmp_path / "报告.docx"
    task_dir = tmp_path / "task"

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="项目一错误",
        )

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_project1_extraction(
        config,
        [source],
        task_dir,
        mode="local_gpu",
        timeout=30,
    )

    assert result.status == EXTRACTION_STATUS_FAILED
    assert "未生成 batch.json" in (result.error or "")
    assert "项目一错误" in (result.error or "")


def test_access_token_is_redacted_from_logs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """PaddleOCR Access Token 不得出现在日志或结果文本中。"""

    config = _create_project(tmp_path)
    source = tmp_path / "报告.docx"
    task_dir = tmp_path / "task"
    secret = "secret-token-value"
    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", secret)

    def fake_run(command, **kwargs):
        output_root = Path(command[command.index("--output-root") + 1])
        _write_batch(output_root, [source])
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"token={secret}",
            stderr=f"error {secret}",
        )

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_project1_extraction(
        config,
        [source],
        task_dir,
        mode="local_gpu",
        timeout=30,
    )

    assert secret not in result.stdout
    assert secret not in result.stderr
    assert secret not in (
        result.stdout_log_path.read_text(encoding="utf-8")
    )
    assert secret not in (
        result.stderr_log_path.read_text(encoding="utf-8")
    )


def test_missing_main_script_raises(tmp_path: Path) -> None:
    """项目一入口不存在时应在启动前明确失败。"""

    config = _create_project(tmp_path)
    (config.project1_root / "main.py").unlink()

    with pytest.raises(Project1StageError, match="项目一入口不存在"):
        run_project1_extraction(
            config,
            [tmp_path / "报告.docx"],
            tmp_path / "task",
            mode="local_gpu",
            timeout=30,
        )


def test_adapter_does_not_modify_project_root_or_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """适配器不得修改项目一目录和原始输入文件。"""

    config = _create_project(tmp_path)
    source = tmp_path / "报告.docx"
    source.write_bytes(b"original input")
    main_before = (config.project1_root / "main.py").read_bytes()
    project_files_before = {
        path.name for path in config.project1_root.iterdir()
    }

    def fake_run(command, **kwargs):
        output_root = Path(command[command.index("--output-root") + 1])
        _write_batch(output_root, [source])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    run_project1_extraction(
        config,
        [source],
        tmp_path / "task",
        mode="local_gpu",
        timeout=30,
    )

    assert source.read_bytes() == b"original input"
    assert (config.project1_root / "main.py").read_bytes() == main_before
    assert {
        path.name for path in config.project1_root.iterdir()
    } == project_files_before
