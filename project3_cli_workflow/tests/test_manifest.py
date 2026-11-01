"""SHA-256 和 manifest.json 测试。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from project3_cli_workflow.errors import InputError, ManifestError
from project3_cli_workflow.manifest import (
    build_manifest,
    calculate_sha256,
    save_manifest,
    write_manifest,
)
from project3_cli_workflow.models import (
    FILTER_REASON_UNSUPPORTED,
    FilteredInput,
)


def _write(path: Path, content: bytes) -> Path:
    """创建带指定字节内容的测试文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_sha256_matches_hashlib_and_chunking(tmp_path: Path) -> None:
    """分块计算的 SHA-256 应与一次性计算一致。"""

    content = "企业环境监测数据".encode() * 100
    source = _write(tmp_path / "报告.docx", content)
    expected = hashlib.sha256(content).hexdigest()

    assert calculate_sha256(source) == expected
    assert calculate_sha256(source, chunk_size=7) == expected


def test_build_manifest_fields(tmp_path: Path) -> None:
    """manifest 必须包含任务、输入、SHA-256 和状态信息。"""

    content = b"fake docx content"
    source = _write(tmp_path / "监测报告.docx", content)
    filtered = FilteredInput(
        source_path=str(tmp_path / "说明.txt"),
        file_name="说明.txt",
        file_type="txt",
        reason=FILTER_REASON_UNSUPPORTED,
        message="不支持的文件类型",
    )

    manifest = build_manifest(
        [source],
        [filtered],
        job_id="job-test",
        created_at="2026-11-01T00:00:00+00:00",
    )
    payload = manifest.to_dict()

    assert payload["schema_version"] == "1.0"
    assert payload["job_id"] == "job-test"
    assert payload["created_at"] == "2026-11-01T00:00:00+00:00"
    assert payload["status"] == "initialized"
    assert payload["input_count"] == 1
    assert payload["filtered_inputs"][0]["reason"] == FILTER_REASON_UNSUPPORTED

    item = payload["inputs"][0]
    assert item["input_id"]
    assert item["source_path"] == str(source.resolve())
    assert item["file_name"] == "监测报告.docx"
    assert item["file_type"] == "docx"
    assert item["file_size"] == len(content)
    assert item["sha256"] == hashlib.sha256(content).hexdigest()
    assert item["status"] == "pending"
    assert item["error"] is None
    assert datetime.fromisoformat(item["modified_at"]).tzinfo is not None


def test_save_manifest_creates_task_directory_and_utf8_file(
    tmp_path: Path,
) -> None:
    """manifest 写入输出根目录下的任务目录，中文不转义。"""

    source = _write(tmp_path / "输入" / "废水报告.pdf", b"pdf")
    manifest = build_manifest([source], job_id="job-001")
    output_root = tmp_path / "输出"

    manifest_path = save_manifest(manifest, output_root)

    assert manifest_path == output_root.resolve() / "job-001" / "manifest.json"
    assert manifest_path.is_file()
    raw = manifest_path.read_text(encoding="utf-8")
    assert "废水报告.pdf" in raw
    payload = json.loads(raw)
    assert payload["job_id"] == "job-001"
    assert payload["inputs"][0]["sha256"] == hashlib.sha256(b"pdf").hexdigest()


def test_original_file_is_not_modified(tmp_path: Path) -> None:
    """计算 SHA-256 和写 manifest 不改变原始文件内容。"""

    content = b"original file bytes"
    source = _write(tmp_path / "原始.docx", content)
    before = source.read_bytes()

    manifest = build_manifest([source], job_id="job-002")
    save_manifest(manifest, tmp_path / "output")

    assert source.read_bytes() == before


def test_output_root_is_file_raises(tmp_path: Path) -> None:
    """输出根目录是文件时返回用户输入错误。"""

    source = _write(tmp_path / "报告.docx", b"docx")
    output_file = _write(tmp_path / "output", b"not a directory")
    manifest = build_manifest([source], job_id="job-003")

    with pytest.raises(InputError, match="输出根目录不是目录"):
        save_manifest(manifest, output_file)


def test_existing_task_directory_raises(tmp_path: Path) -> None:
    """任务目录已存在时不覆盖旧任务。"""

    source = _write(tmp_path / "报告.docx", b"docx")
    output_root = tmp_path / "output"
    (output_root / "job-004").mkdir(parents=True)
    manifest = build_manifest([source], job_id="job-004")

    with pytest.raises(ManifestError, match="任务目录已存在"):
        save_manifest(manifest, output_root)


def test_write_manifest_replaces_existing_file(tmp_path: Path) -> None:
    """更新 manifest 应原子替换旧文件，不留下临时文件。"""

    source = _write(tmp_path / "报告.docx", b"docx")
    manifest = build_manifest([source], job_id="job-005")
    manifest_path = save_manifest(manifest, tmp_path / "output")
    manifest.extraction_status = "extraction_running"

    write_manifest(manifest, manifest_path)

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["extraction_status"] == "extraction_running"
    assert not (manifest_path.parent / ".manifest.json.tmp").exists()
