from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook

from doc_extractor.api import (
    extract_and_save,
    extract_file,
    load_batch,
    load_latest_batch,
)
from doc_extractor.core.batch_io import export_batch, save_batch
from doc_extractor.core.extraction_batch import ExtractionBatch

ROOT = Path(__file__).resolve().parents[1]


def test_headless_api_extracts_saves_and_restores(
    word_file: Path, tmp_path: Path
) -> None:
    batch, outputs = extract_and_save(
        [word_file],
        output_root=tmp_path,
        formats=("json", "markdown", "excel"),
    )

    assert batch.batch_id
    assert batch.extracted_at
    assert batch.document_count == 1
    assert set(outputs) == {"batch", "json", "markdown", "excel"}
    assert all(path.is_file() for path in outputs.values())

    payload = json.loads(outputs["json"].read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["batch_id"] == batch.batch_id
    assert payload["extracted_at"] == batch.extracted_at
    document = payload["documents"][0]
    assert document["source_name"] == "sample.docx"
    assert document["source_file"] == str(word_file.resolve())
    assert document["file_type"] == "word"
    assert document["records"]
    table_records = [
        record for record in document["records"] if record["content_type"] == "table"
    ]
    assert table_records
    assert table_records[0]["metadata"]["rows"]

    markdown = outputs["markdown"].read_text(encoding="utf-8")
    assert "sample.docx" in markdown
    assert str(word_file.resolve()) in markdown
    assert "表格 0" in markdown
    assert "| 项目 | 金额 |" in markdown
    assert "来源：" in markdown

    workbook = load_workbook(outputs["excel"], read_only=True)
    assert "文件汇总" in workbook.sheetnames
    workbook.close()

    restored = load_batch(outputs["batch"])
    assert isinstance(restored, ExtractionBatch)
    assert restored.batch_id == batch.batch_id
    assert restored.extracted_at == batch.extracted_at
    assert restored.document_count == batch.document_count
    assert restored.documents[0].source_file == str(word_file.resolve())
    assert restored.documents[0].record_count == batch.documents[0].record_count
    assert restored.documents[0].table_count == batch.documents[0].table_count

    restored_from_json = load_batch(outputs["json"])
    assert restored_from_json.batch_id == batch.batch_id
    assert restored_from_json.documents[0].records


def test_batch_serialization_preserves_environmental_records(
    environmental_word_file: Path,
) -> None:
    batch = extract_file(environmental_word_file)
    encoded = json.dumps(batch.to_dict(), ensure_ascii=False)
    restored = ExtractionBatch.from_dict(json.loads(encoded))

    assert restored.environmental.record_count == batch.environmental.record_count
    assert restored.environmental.record_count > 0
    assert len(restored.environmental.enterprises) == len(batch.environmental.enterprises)
    assert {
        record.record_id for record in restored.environmental.records
    } == {record.record_id for record in batch.environmental.records}


def test_save_batch_and_export_never_overwrite_existing_files(
    word_file: Path, tmp_path: Path
) -> None:
    batch = extract_file(word_file)
    first = save_batch(batch, tmp_path, formats=("json",))
    second = save_batch(batch, tmp_path, formats=("json",))

    assert first["batch"] != second["batch"]
    assert first["json"] != second["json"]
    assert first["batch"].is_file()
    assert second["batch"].is_file()
    assert first["json"].is_file()
    assert second["json"].is_file()

    markdown_one = export_batch(batch, "markdown", tmp_path)
    markdown_two = export_batch(batch, "markdown", tmp_path)
    assert markdown_one != markdown_two
    assert markdown_one.is_file()
    assert markdown_two.is_file()

    latest = load_latest_batch(tmp_path)
    assert latest.batch_id == batch.batch_id


def test_cli_help_extract_and_export(word_file: Path, tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    help_result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )
    assert help_result.returncode == 0
    assert "extract" in help_result.stdout
    assert "export" in help_result.stdout

    extract_result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "extract",
            "--input",
            str(word_file),
            "--output-root",
            str(tmp_path),
            "--quiet",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )
    assert extract_result.returncode == 0, extract_result.stderr
    match = re.search(r"批次 ID：(\S+)", extract_result.stdout)
    assert match is not None
    batch_id = match.group(1)

    batches = list((tmp_path / "batches").glob("*/batch.json"))
    assert len(batches) == 1
    assert list((tmp_path / "json").glob("*.json"))

    for output_format, suffix in (
        ("json", ".json"),
        ("markdown", ".md"),
        ("excel", ".xlsx"),
    ):
        export_result = subprocess.run(
            [
                sys.executable,
                "main.py",
                "export",
                "--format",
                output_format,
                "--batch-id",
                batch_id,
                "--output-root",
                str(tmp_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=180,
        )
        assert export_result.returncode == 0, export_result.stderr
        exported = list((tmp_path / output_format).glob(f"*{suffix}"))
        assert exported

    latest_result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "export",
            "--format",
            "markdown",
            "--output-root",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )
    assert latest_result.returncode == 0, latest_result.stderr
    assert len(list((tmp_path / "markdown").glob("*.md"))) >= 2


def test_cli_export_from_batch_file(word_file: Path, tmp_path: Path) -> None:
    batch = extract_file(word_file)
    outputs = save_batch(batch, tmp_path, formats=())
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "export",
            "--format",
            "json",
            "--batch-file",
            str(outputs["batch"]),
            "--output",
            str(tmp_path / "restored.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads((tmp_path / "restored.json").read_text(encoding="utf-8"))
    assert payload["batch_id"] == batch.batch_id
    assert payload["documents"][0]["source_name"] == "sample.docx"
