from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf
from docx import Document
from docx.shared import RGBColor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from real_batch_support import real_batch_path

from main import main as cli_main
from word_audit.pipeline import PipelineInputError, run_audit
from word_audit.project1_batch import Project1Batch

REQUIRED_COUNT_KEYS = {
    "record_count",
    "verified_count",
    "unverified_count",
    "issue_count",
    "located_count",
    "annotation_applied_count",
    "annotation_failed_count",
    "annotation_manual_review_count",
    "issues_flagged_for_manual_review",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _run_cli(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli_main(args)
    return code, stdout.getvalue(), stderr.getvalue()


def _base_payload(
    *,
    batch_id: str,
    documents: list[dict],
    environmental: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    payload = {
        "schema_version": "1.0",
        "batch_id": batch_id,
        "extracted_at": "2026-01-01T00:00:00+00:00",
        "document_count": len(documents),
        "documents": documents,
        "tables": [],
    }
    if environmental is not None:
        payload["environmental"] = environmental
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def _make_synthetic_word_batch(root: Path) -> tuple[Path, Path]:
    docx_path = root / "synthetic_word_report.docx"
    document = Document()
    document.add_paragraph("合成测试数据，非真实审核结果")
    table = document.add_table(rows=2, cols=4)
    headers = ["项目", "监测结果", "单位", "备注"]
    row = ["合成测试-去除率", "12.5", "%", "去除率 = (100-85)/100*100"]
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = text
    for cell, text in zip(table.rows[1].cells, row):
        cell.text = text
    document.save(docx_path)

    rows = [headers, row]
    cells = [
        {
            "row_index": row_index,
            "column_index": column_index,
            "text": text,
            "entities": [],
        }
        for row_index, values in enumerate(rows)
        for column_index, text in enumerate(values)
    ]
    row_text = "\t".join(row)
    source_file = str(docx_path)
    document_id = "synthetic-word-doc"
    table_record = {
        "document_id": document_id,
        "source_file": source_file,
        "file_type": "word",
        "content_type": "table",
        "text": "\n".join("\t".join(values) for values in rows),
        "location": {
            "paragraph_index": None,
            "table_index": 0,
            "row_index": None,
            "column_index": None,
            "page_number": None,
            "bbox": None,
            "block_index": None,
            "reading_order": None,
        },
        "metadata": {
            "row_count": 2,
            "column_count": 4,
            "rows": rows,
            "cells": cells,
        },
    }
    environmental_record = {
        "record_id": "synthetic-word-calc",
        "category": "environmental_monitoring",
        "subcategory": "wastewater",
        "document_id": document_id,
        "source_file": source_file,
        "file_type": "word",
        "indicator": "合成测试-去除率",
        "value": 12.5,
        "unit": "%",
        "time": "2026-01-01",
        "point": "合成测试点位",
        "detection_limit": None,
        "source_location": {
            "paragraph_index": None,
            "table_index": 0,
            "row_index": 1,
            "column_index": 0,
            "page_number": None,
            "bbox": None,
            "block_index": None,
            "reading_order": None,
        },
        "source_content_type": "table",
        "source_text": row_text,
        "raw_expression": row_text,
        "extraction_engine": "PaddleOCR",
        "extraction_mode": None,
        "flags": [],
        "status": "complete",
        "confidence": 0.9,
        "metadata": {},
    }
    payload = _base_payload(
        batch_id="synthetic-word-batch",
        documents=[
            {
                "document_id": document_id,
                "source_name": docx_path.name,
                "source_file": source_file,
                "file_type": "word",
                "record_count": 1,
                "table_count": 0,
                "records": [table_record],
                "tables": [],
                "warnings": [],
                "error": None,
                "metadata": {"paragraph_count": 1, "table_count": 1},
            }
        ],
        environmental={"records": [environmental_record], "warnings": []},
        metadata={
            "synthetic_data": True,
            "synthetic_note": "合成测试数据，非项目一真实审核结果",
        },
    )
    batch_path = _write_json(root / "synthetic_word_batch.json", payload)
    return batch_path, docx_path


def _make_synthetic_pdf_batch(root: Path) -> tuple[Path, Path, list[float]]:
    pdf_path = root / "synthetic_pdf_report.pdf"
    text = "synthetic-rate 12.5 % rate = (100-85)/100*100"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((72, 100), text, fontsize=12)
        words = page.get_text("words")
        bbox = [
            min(word[0] for word in words),
            min(word[1] for word in words),
            max(word[2] for word in words),
            max(word[3] for word in words),
        ]
        pdf.save(pdf_path)

    document_id = "synthetic-pdf-doc"
    source_file = str(pdf_path)
    environmental_record = {
        "record_id": "synthetic-pdf-calc",
        "category": "environmental_monitoring",
        "subcategory": "waste_gas",
        "document_id": document_id,
        "source_file": source_file,
        "file_type": "pdf",
        "indicator": "synthetic-rate",
        "value": 12.5,
        "unit": "%",
        "time": "2026-01-01",
        "point": "synthetic point",
        "detection_limit": None,
        "source_location": {
            "paragraph_index": None,
            "table_index": None,
            "row_index": None,
            "column_index": None,
            "page_number": 1,
            "bbox": bbox,
            "block_index": None,
            "reading_order": None,
        },
        "source_content_type": "text_block",
        "source_text": text,
        "raw_expression": text,
        "extraction_engine": "PaddleOCR",
        "extraction_mode": "local_gpu",
        "flags": [],
        "status": "complete",
        "confidence": 0.9,
        "metadata": {},
    }
    payload = _base_payload(
        batch_id="synthetic-pdf-batch",
        documents=[
            {
                "document_id": document_id,
                "source_name": pdf_path.name,
                "source_file": source_file,
                "file_type": "pdf",
                "record_count": 0,
                "table_count": 0,
                "records": [],
                "tables": [],
                "warnings": [],
                "error": None,
                "metadata": {"page_count": 1},
            }
        ],
        environmental={"records": [environmental_record], "warnings": []},
        metadata={
            "synthetic_data": True,
            "synthetic_note": "合成测试数据，非项目一真实审核结果",
        },
    )
    batch_path = _write_json(root / "synthetic_pdf_batch.json", payload)
    return batch_path, pdf_path, bbox


class RealBatchPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.batch_path = real_batch_path()

    def test_real_batch_completes_and_reports_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_audit(self.batch_path, root / "output")
            counts = result.report.metadata["pipeline"]["counts"]
            self.assertEqual(
                counts,
                {
                    "record_count": 9,
                    "verified_count": 0,
                    "unverified_count": 9,
                    "issue_count": 0,
                    "located_count": 0,
                    "annotation_applied_count": 0,
                    "annotation_failed_count": 0,
                    "annotation_manual_review_count": 0,
                    "issues_flagged_for_manual_review": 0,
                },
            )
            self.assertEqual(result.report.metadata["pipeline"]["synthetic_data"], False)
            self.assertEqual(result.report.metadata["pipeline"]["complete_success"], True)
            self.assertEqual(result.output_files, [])
            for path in (
                result.audit_json_path,
                result.audit_markdown_path,
                result.math_validation_path,
                result.annotation.json_path,
                result.annotation.markdown_path,
            ):
                self.assertTrue(path.is_file(), path)
            payload = json.loads(result.audit_json_path.read_text(encoding="utf-8"))
            self.assertTrue(REQUIRED_COUNT_KEYS <= set(payload["metadata"]["pipeline"]["counts"]))
            self.assertEqual(payload["issues"], [])
            self.assertEqual(payload["annotations"], [])
            markdown = result.audit_markdown_path.read_text(encoding="utf-8")
            self.assertIn("# 完整审核报告", markdown)
            self.assertIn("## 数量统计", markdown)
            self.assertIn("unverified", markdown)
            self.assertIn("## 警告与异常", markdown)
            self.assertFalse(
                (root / "output" / "annotated").exists()
            )

    def test_real_batch_hashes_unchanged(self) -> None:
        batch = Project1Batch.load(self.batch_path)
        paths = [
            self.batch_path,
            *[Path(document.source_file) for document in batch.documents],
        ]
        before = {str(path): _sha256(path) for path in paths}
        with tempfile.TemporaryDirectory() as directory:
            run_audit(self.batch_path, Path(directory) / "output")
        after = {str(path): _sha256(path) for path in paths}
        self.assertEqual(before, after)

    def test_cli_audit_real_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, stdout, stderr = _run_cli(
                [
                    "audit",
                    "--batch-json",
                    str(self.batch_path),
                    "--output-dir",
                    str(root / "output"),
                ]
            )
            self.assertEqual(code, 0, stderr)
            self.assertIn("issues: 0", stdout)
            self.assertIn("unverified: 9", stdout)
            self.assertIn("complete_success: True", stdout)
            self.assertIn("audit_report_json:", stdout)
            self.assertTrue(
                (root / "output" / "reports").is_dir()
            )


class PipelineInputValidationTests(unittest.TestCase):
    def test_invalid_json_returns_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path = root / "invalid.json"
            batch_path.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(PipelineInputError) as context:
                run_audit(batch_path, root / "output")
            self.assertIn("格式无效", str(context.exception))
            code, _, stderr = _run_cli(
                [
                    "audit",
                    "--batch-json",
                    str(batch_path),
                    "--output-dir",
                    str(root / "output"),
                ]
            )
            self.assertEqual(code, 2)
            self.assertIn("error:", stderr)
            self.assertIn("格式无效", stderr)

    def test_missing_batch_file_returns_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, _, stderr = _run_cli(
                [
                    "audit",
                    "--batch-json",
                    str(root / "missing.json"),
                    "--output-dir",
                    str(root / "output"),
                ]
            )
            self.assertEqual(code, 2)
            self.assertIn("不存在", stderr)

    def test_missing_environmental_is_an_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = _base_payload(
                batch_id="missing-environmental",
                documents=[
                    {
                        "document_id": "doc-1",
                        "source_name": "report.docx",
                        "source_file": "report.docx",
                        "file_type": "word",
                        "records": [],
                    }
                ],
            )
            batch_path = _write_json(root / "batch.json", payload)
            with self.assertRaises(PipelineInputError) as context:
                run_audit(batch_path, root / "output")
            self.assertIn("environmental", str(context.exception))

    def test_missing_environmental_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = _base_payload(
                batch_id="missing-environmental-cli",
                documents=[
                    {
                        "document_id": "doc-1",
                        "source_name": "report.docx",
                        "source_file": "report.docx",
                        "file_type": "word",
                        "records": [],
                    }
                ],
            )
            batch_path = _write_json(root / "batch.json", payload)
            code, _, stderr = _run_cli(
                [
                    "audit",
                    "--batch-json",
                    str(batch_path),
                    "--output-dir",
                    str(root / "output"),
                ]
            )
            self.assertEqual(code, 2)
            self.assertIn("environmental", stderr)

    def test_empty_environmental_records_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docx_path = root / "empty.docx"
            Document().save(docx_path)
            payload = _base_payload(
                batch_id="empty-records",
                documents=[
                    {
                        "document_id": "doc-1",
                        "source_name": docx_path.name,
                        "source_file": str(docx_path),
                        "file_type": "word",
                        "records": [],
                    }
                ],
                environmental={"records": []},
            )
            batch_path = _write_json(root / "batch.json", payload)
            result = run_audit(batch_path, root / "output")
            counts = result.report.metadata["pipeline"]["counts"]
            self.assertEqual(counts["record_count"], 0)
            self.assertEqual(counts["issue_count"], 0)
            self.assertEqual(result.report.metadata["pipeline"]["complete_success"], True)

    def test_missing_document_fields_are_input_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = _base_payload(
                batch_id="missing-fields",
                documents=[
                    {
                        "document_id": "doc-1",
                        "file_type": "word",
                        "records": [],
                    }
                ],
                environmental={"records": []},
            )
            batch_path = _write_json(root / "batch.json", payload)
            with self.assertRaises(PipelineInputError) as context:
                run_audit(batch_path, root / "output")
            message = str(context.exception)
            self.assertIn("source_file", message)

    def test_missing_documents_is_an_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema_version": "1.0",
                "batch_id": "missing-documents",
                "environmental": {"records": []},
            }
            batch_path = _write_json(root / "batch.json", payload)
            with self.assertRaises(PipelineInputError) as context:
                run_audit(batch_path, root / "output")
            self.assertIn("documents", str(context.exception))


class SyntheticWordPipelineTests(unittest.TestCase):
    def test_synthetic_word_calculation_error_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, docx_path = _make_synthetic_word_batch(root)
            batch = Project1Batch.load(batch_path)
            self.assertTrue(batch.metadata.get("synthetic_data"))
            source_hash = _sha256(docx_path)

            result = run_audit(batch_path, root / "output")
            pipeline = result.report.metadata["pipeline"]
            counts = pipeline["counts"]
            self.assertEqual(
                counts,
                {
                    "record_count": 1,
                    "verified_count": 0,
                    "unverified_count": 0,
                    "issue_count": 1,
                    "located_count": 1,
                    "annotation_applied_count": 1,
                    "annotation_failed_count": 0,
                    "annotation_manual_review_count": 0,
                    "issues_flagged_for_manual_review": 1,
                },
            )
            self.assertEqual(pipeline["synthetic_data"], True)
            self.assertEqual(pipeline["complete_success"], True)
            self.assertEqual(len(result.output_files), 1)
            annotated_path = result.output_files[0]
            self.assertTrue(annotated_path.name.endswith("_annotated.docx"))

            annotated = Document(str(annotated_path))
            annotations = [
                paragraph
                for paragraph in annotated.paragraphs
                if paragraph.text.startswith("#")
            ]
            cell = annotated.tables[0].rows[1].cells[1]
            cell_annotations = [
                paragraph
                for paragraph in cell.paragraphs
                if paragraph.text.startswith("#")
            ]
            self.assertEqual(len(annotations), 0)
            self.assertEqual(len(cell_annotations), 1)
            annotation = cell_annotations[0]
            self.assertIn("[合成测试数据]", annotation.text)
            self.assertIn("经计算为 15 %", annotation.text)
            self.assertIn("原文：", annotation.text)
            for run in annotation.runs:
                self.assertEqual(run.font.color.rgb, RGBColor(0xFF, 0x00, 0x00))

            self.assertEqual(len(annotated.tables), 1)
            self.assertEqual(len(annotated.tables[0].rows), 2)
            self.assertEqual(len(annotated.tables[0].columns), 4)
            self.assertEqual(_sha256(docx_path), source_hash)

            payload = json.loads(result.audit_json_path.read_text(encoding="utf-8"))
            self.assertTrue(REQUIRED_COUNT_KEYS <= set(payload["metadata"]["pipeline"]["counts"]))
            self.assertEqual(payload["metadata"]["pipeline"]["synthetic_data"], True)
            self.assertIn("合成测试数据", result.audit_markdown_path.read_text(encoding="utf-8"))
            self.assertTrue(result.math_validation_path.is_file())
            self.assertTrue(result.annotation.json_path.is_file())

    def test_synthetic_word_duplicate_outputs_are_numbered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _ = _make_synthetic_word_batch(root)
            first = run_audit(batch_path, root / "output")
            second = run_audit(batch_path, root / "output")
            self.assertNotEqual(first.output_files[0], second.output_files[0])
            self.assertNotEqual(first.audit_json_path, second.audit_json_path)
            self.assertTrue(first.output_files[0].is_file())
            self.assertTrue(second.output_files[0].is_file())
            self.assertTrue(first.audit_json_path.is_file())
            self.assertTrue(second.audit_json_path.is_file())

    def test_missing_word_source_is_not_complete_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, docx_path = _make_synthetic_word_batch(root)
            docx_path.unlink()
            result = run_audit(batch_path, root / "output")
            pipeline = result.report.metadata["pipeline"]
            counts = pipeline["counts"]
            self.assertEqual(counts["issue_count"], 1)
            self.assertEqual(counts["located_count"], 0)
            self.assertEqual(counts["annotation_applied_count"], 0)
            self.assertEqual(counts["annotation_manual_review_count"], 1)
            self.assertEqual(pipeline["complete_success"], False)
            self.assertTrue(
                any("源文件不存在" in warning for warning in pipeline["warnings"])
            )
            self.assertEqual(pipeline["stages"]["location"]["not_found"], 1)
            self.assertTrue(result.audit_json_path.is_file())
            self.assertEqual(result.output_files, [])


class SyntheticPdfPipelineTests(unittest.TestCase):
    def test_synthetic_pdf_marker_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, pdf_path, bbox = _make_synthetic_pdf_batch(root)
            source_hash = _sha256(pdf_path)
            with pymupdf.open(pdf_path) as original_pdf:
                original_text = original_pdf.load_page(0).get_text("text")

            result = run_audit(batch_path, root / "output")
            pipeline = result.report.metadata["pipeline"]
            counts = pipeline["counts"]
            self.assertEqual(counts["record_count"], 1)
            self.assertEqual(counts["issue_count"], 1)
            self.assertEqual(counts["located_count"], 1)
            self.assertEqual(counts["annotation_applied_count"], 1)
            self.assertEqual(counts["annotation_failed_count"], 0)
            self.assertEqual(counts["annotation_manual_review_count"], 0)
            self.assertEqual(counts["issues_flagged_for_manual_review"], 1)
            self.assertEqual(pipeline["synthetic_data"], True)
            self.assertEqual(pipeline["complete_success"], True)
            self.assertEqual(len(result.output_files), 1)
            annotated_path = result.output_files[0]
            self.assertTrue(annotated_path.name.endswith("_annotated.pdf"))

            with pymupdf.open(str(annotated_path)) as annotated_pdf:
                self.assertEqual(annotated_pdf.page_count, 1)
                page = annotated_pdf.load_page(0)
                self.assertEqual(page.get_text("text"), original_text)
                red = [
                    drawing
                    for drawing in page.get_drawings()
                    if drawing.get("color")
                    and drawing["color"][0] > 0.99
                    and drawing["color"][1] < 0.01
                    and drawing["color"][2] < 0.01
                ]
                self.assertEqual(len(red), 1)
                self.assertAlmostEqual(red[0]["rect"].x0, bbox[0], places=1)
                self.assertAlmostEqual(red[0]["rect"].y0, bbox[1], places=1)
                self.assertAlmostEqual(red[0]["rect"].x1, bbox[2], places=1)
                self.assertAlmostEqual(red[0]["rect"].y1, bbox[3], places=1)

            self.assertEqual(_sha256(pdf_path), source_hash)
            payload = json.loads(result.audit_json_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["metadata"]["pipeline"]["synthetic_data"])
            self.assertTrue(result.math_validation_path.is_file())


class PipelineSyntheticIsolationTests(unittest.TestCase):
    def test_real_batch_is_not_marked_synthetic(self) -> None:
        batch = Project1Batch.load(real_batch_path())
        self.assertFalse(batch.metadata.get("synthetic_data", False))

    def test_synthetic_marker_is_loaded_from_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _ = _make_synthetic_word_batch(root)
            batch = Project1Batch.load(batch_path)
            self.assertEqual(batch.metadata.get("synthetic_data"), True)


if __name__ == "__main__":
    unittest.main()
