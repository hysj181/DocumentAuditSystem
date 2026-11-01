from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf
from docx import Document
from docx.shared import RGBColor

from word_audit.annotation import annotate_issues
from word_audit.location import locate_issues
from word_audit.pipeline import run_audit
from word_audit.project1_batch import Project1Batch
from word_audit.typo_audit import scan_batch_typos

REAL_BATCH_PATH = (
    Path(__file__).resolve().parents[2]
    / "project1_extraction"
    / "output"
    / "batches"
    / "20261101T053459830362Z_0e022780"
    / "batch.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_word_typo_batch(
    root: Path,
    *,
    paragraphs: list[str],
    table_rows: list[list[str]] | None = None,
    paragraph_indices: list[int] | None = None,
) -> tuple[Path, Path]:
    docx_path = root / "synthetic_typo_word.docx"
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table_rows:
        column_count = max(len(row) for row in table_rows)
        table = document.add_table(rows=len(table_rows), cols=column_count)
        for row_index, row in enumerate(table_rows):
            for column_index, text in enumerate(row):
                table.rows[row_index].cells[column_index].text = text
    document.save(docx_path)

    source_file = str(docx_path)
    document_id = "synthetic-typo-word-doc"
    records: list[dict] = []
    indices = paragraph_indices or list(range(len(paragraphs)))
    for index, text in zip(indices, paragraphs):
        records.append(
            {
                "document_id": document_id,
                "source_file": source_file,
                "file_type": "word",
                "content_type": "paragraph",
                "text": text,
                "location": {
                    "paragraph_index": index,
                    "table_index": None,
                    "row_index": None,
                    "column_index": None,
                    "page_number": None,
                    "bbox": None,
                    "block_index": None,
                    "reading_order": None,
                },
                "metadata": {},
            }
        )
    if table_rows:
        rows = [list(row) for row in table_rows]
        cells = [
            {
                "row_index": row_index,
                "column_index": column_index,
                "text": text,
                "entities": [],
            }
            for row_index, row in enumerate(rows)
            for column_index, text in enumerate(row)
        ]
        records.append(
            {
                "document_id": document_id,
                "source_file": source_file,
                "file_type": "word",
                "content_type": "table",
                "text": "\n".join("\t".join(row) for row in rows),
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
                    "row_count": len(rows),
                    "column_count": max(len(row) for row in rows),
                    "rows": rows,
                    "cells": cells,
                },
            }
        )

    payload = {
        "schema_version": "1.0",
        "batch_id": "synthetic-typo-word-batch",
        "extracted_at": "2026-01-01T00:00:00+00:00",
        "metadata": {"synthetic_data": True},
        "documents": [
            {
                "document_id": document_id,
                "source_name": docx_path.name,
                "source_file": source_file,
                "file_type": "word",
                "record_count": len(records),
                "table_count": 1 if table_rows else 0,
                "records": records,
                "tables": [],
                "warnings": [],
                "error": None,
                "metadata": {},
            }
        ],
        "tables": [],
        "environmental": {"records": []},
    }
    batch_path = root / "synthetic_typo_word_batch.json"
    batch_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return batch_path, docx_path


class SyntheticWordTypoTests(unittest.TestCase):
    def test_word_paragraph_and_table_typo_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, docx_path = _make_word_typo_batch(
                root,
                paragraphs=["本次数剧由合成测试生成。"],
                table_rows=[["数剧", "正确"]],
            )
            source_hash = _sha256(docx_path)
            batch = Project1Batch.load(batch_path)
            typo_result = scan_batch_typos(batch)
            self.assertEqual(len(typo_result.issues), 2)
            self.assertEqual(typo_result.verified_count, 2)

            locations = locate_issues(batch, typo_result.issues)
            self.assertEqual(
                [location.locator_status for location in locations],
                ["located", "located"],
            )
            annotation = annotate_issues(
                batch,
                typo_result.issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(
                annotation.report.metadata["annotation_task"]["counts"],
                {"total": 2, "applied": 2, "failed": 0, "manual_review": 0},
            )
            self.assertEqual(len(annotation.output_files), 1)
            annotated_path = annotation.output_files[0]
            self.assertTrue(annotated_path.name.endswith("_annotated.docx"))

            annotated = Document(str(annotated_path))
            self.assertEqual(annotated.paragraphs[0].text, "本次数剧由合成测试生成。")
            body_annotation = annotated.paragraphs[1]
            self.assertTrue(body_annotation.text.startswith("#"))
            self.assertIn("[合成测试数据]", body_annotation.text)
            self.assertIn("[错别字]", body_annotation.text)
            self.assertIn("“数剧”疑似错别字", body_annotation.text)
            self.assertIn("建议修改为“数据”", body_annotation.text)
            self.assertIn("原文：数剧", body_annotation.text)
            self.assertIn("建议核实：数据", body_annotation.text)
            for run in body_annotation.runs:
                self.assertEqual(run.font.color.rgb, RGBColor(0xFF, 0x00, 0x00))

            cell = annotated.tables[0].rows[0].cells[0]
            self.assertEqual(cell.paragraphs[0].text, "数剧")
            cell_annotation = cell.paragraphs[-1]
            self.assertTrue(cell_annotation.text.startswith("#"))
            self.assertIn("“数剧”疑似错别字", cell_annotation.text)
            for run in cell_annotation.runs:
                self.assertEqual(run.font.color.rgb, RGBColor(0xFF, 0x00, 0x00))

            self.assertEqual(len(annotated.tables), 1)
            self.assertEqual(len(annotated.tables[0].rows), 1)
            self.assertEqual(len(annotated.tables[0].columns), 2)
            # Original text is not replaced.
            self.assertIn("数剧", annotated.paragraphs[0].text)
            self.assertEqual(_sha256(docx_path), source_hash)
            self.assertTrue(annotation.json_path.is_file())
            self.assertTrue(annotation.markdown_path.is_file())

    def test_low_confidence_word_issue_is_not_annotated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _ = _make_word_typo_batch(
                root,
                paragraphs=["临测数据。"],
            )
            batch = Project1Batch.load(batch_path)
            typo_result = scan_batch_typos(batch)
            self.assertEqual(len(typo_result.issues), 1)
            issue = typo_result.issues[0]
            self.assertEqual(issue.metadata["typo_confidence"], "low")
            self.assertFalse(issue.metadata["auto_annotate"])

            locations = locate_issues(batch, typo_result.issues)
            self.assertEqual(locations[0].locator_status, "located")
            annotation = annotate_issues(
                batch,
                typo_result.issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(annotation.output_files, [])
            counts = annotation.report.metadata["annotation_task"]["counts"]
            self.assertEqual(counts["applied"], 0)
            self.assertEqual(counts["manual_review"], 1)
            self.assertEqual(
                annotation.report.annotations[0].error,
                "issue_requires_manual_review",
            )

    def test_professional_terms_enterprise_and_standard_not_annotated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _ = _make_word_typo_batch(
                root,
                paragraphs=[
                    "化学需氧量、氨氮、总磷、总氮、二氧化硫、氮氧化物、颗粒物。",
                    "青禾环保材料有限公司（虚构）",
                    "执行标准 GB 3838-2002 和 HJ 828-2017。",
                ],
            )
            batch = Project1Batch.load(batch_path)
            typo_result = scan_batch_typos(batch)
            self.assertEqual(typo_result.issues, [])

    def test_word_location_failure_enters_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _ = _make_word_typo_batch(
                root,
                paragraphs=["数剧。"],
                paragraph_indices=[999],
            )
            batch = Project1Batch.load(batch_path)
            typo_result = scan_batch_typos(batch)
            self.assertEqual(len(typo_result.issues), 1)
            locations = locate_issues(batch, typo_result.issues)
            self.assertEqual(locations[0].locator_status, "invalid_location")
            annotation = annotate_issues(
                batch,
                typo_result.issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(annotation.output_files, [])
            counts = annotation.report.metadata["annotation_task"]["counts"]
            self.assertEqual(counts["applied"], 0)
            self.assertEqual(counts["manual_review"], 1)
            self.assertEqual(
                annotation.report.annotations[0].status,
                "skipped",
            )


def _cjk_font_path() -> Path:
    candidates = [
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("no Windows CJK font found for PDF typo tests")


def _make_pdf_typo_batch(
    root: Path,
    *,
    text: str,
    page_number: int = 1,
    include_bbox: bool = True,
) -> tuple[Path, Path, list[float] | None]:
    pdf_path = root / "synthetic_typo_pdf.pdf"
    font_path = _cjk_font_path()
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text(
            (72, 100),
            text,
            fontsize=12,
            fontname="cjk",
            fontfile=str(font_path),
        )
        words = page.get_text("words")
        bbox = None
        if include_bbox and words:
            bbox = [
                min(word[0] for word in words),
                min(word[1] for word in words),
                max(word[2] for word in words),
                max(word[3] for word in words),
            ]
        pdf.save(pdf_path)

    source_file = str(pdf_path)
    document_id = "synthetic-typo-pdf-doc"
    record = {
        "document_id": document_id,
        "source_file": source_file,
        "file_type": "pdf",
        "content_type": "ocr_text",
        "text": text,
        "location": {
            "paragraph_index": None,
            "table_index": None,
            "row_index": None,
            "column_index": None,
            "page_number": page_number,
            "bbox": bbox,
            "block_index": None,
            "reading_order": 0,
        },
        "metadata": {"confidence": 0.99},
    }
    payload = {
        "schema_version": "1.0",
        "batch_id": "synthetic-typo-pdf-batch",
        "extracted_at": "2026-01-01T00:00:00+00:00",
        "metadata": {"synthetic_data": True},
        "documents": [
            {
                "document_id": document_id,
                "source_name": pdf_path.name,
                "source_file": source_file,
                "file_type": "pdf",
                "record_count": 1,
                "table_count": 0,
                "records": [record],
                "tables": [],
                "warnings": [],
                "error": None,
                "metadata": {"page_count": 1},
            }
        ],
        "tables": [],
        "environmental": {"records": []},
    }
    batch_path = root / "synthetic_typo_pdf_batch.json"
    batch_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return batch_path, pdf_path, bbox


class SyntheticPdfTypoTests(unittest.TestCase):
    def test_pdf_text_typo_marked_with_line_granularity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, pdf_path, bbox = _make_pdf_typo_batch(
                root,
                text="本次数剧由合成测试生成。",
            )
            source_hash = _sha256(pdf_path)
            batch = Project1Batch.load(batch_path)
            typo_result = scan_batch_typos(batch)
            self.assertEqual(len(typo_result.issues), 1)
            issue = typo_result.issues[0]
            self.assertEqual(issue.original_text, "数剧")
            self.assertEqual(
                issue.metadata["location_granularity"], "pdf_text_line"
            )
            self.assertTrue(issue.metadata["synthetic"])

            locations = locate_issues(batch, typo_result.issues)
            self.assertEqual(locations[0].locator_status, "located")
            self.assertEqual(locations[0].page_number, 1)
            annotation = annotate_issues(
                batch,
                typo_result.issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(len(annotation.output_files), 1)
            annotated_path = annotation.output_files[0]
            self.assertTrue(annotated_path.name.endswith("_annotated.pdf"))
            self.assertEqual(
                annotation.report.metadata["annotation_task"]["counts"],
                {"total": 1, "applied": 1, "failed": 0, "manual_review": 0},
            )
            self.assertEqual(
                annotation.report.annotations[0].metadata["annotation_kind"],
                "pdf_red_rect",
            )

            with pymupdf.open(pdf_path) as original_pdf:
                original_text = original_pdf.load_page(0).get_text("text")
            with pymupdf.open(str(annotated_path)) as annotated_pdf:
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
                self.assertIsNotNone(bbox)
                self.assertAlmostEqual(red[0]["rect"].x0, bbox[0], places=1)
                self.assertAlmostEqual(red[0]["rect"].y0, bbox[1], places=1)
                self.assertAlmostEqual(red[0]["rect"].x1, bbox[2], places=1)
                self.assertAlmostEqual(red[0]["rect"].y1, bbox[3], places=1)
            self.assertEqual(_sha256(pdf_path), source_hash)

    def test_low_confidence_pdf_issue_is_not_marked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _, _ = _make_pdf_typo_batch(
                root,
                text="临测数据。",
            )
            batch = Project1Batch.load(batch_path)
            typo_result = scan_batch_typos(batch)
            self.assertEqual(len(typo_result.issues), 1)
            self.assertFalse(typo_result.issues[0].metadata["auto_annotate"])
            locations = locate_issues(batch, typo_result.issues)
            annotation = annotate_issues(
                batch,
                typo_result.issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(annotation.output_files, [])
            counts = annotation.report.metadata["annotation_task"]["counts"]
            self.assertEqual(counts["applied"], 0)
            self.assertEqual(counts["manual_review"], 1)

    def test_pdf_professional_terms_and_standard_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _, _ = _make_pdf_typo_batch(
                root,
                text="执行标准 GB 3838-2002；化学需氧量、氨氮、总磷。",
            )
            batch = Project1Batch.load(batch_path)
            typo_result = scan_batch_typos(batch)
            self.assertEqual(typo_result.issues, [])

    def test_pdf_location_failure_enters_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _, _ = _make_pdf_typo_batch(
                root,
                text="数剧。",
                page_number=99,
            )
            batch = Project1Batch.load(batch_path)
            typo_result = scan_batch_typos(batch)
            self.assertEqual(len(typo_result.issues), 1)
            locations = locate_issues(batch, typo_result.issues)
            self.assertEqual(locations[0].locator_status, "invalid_location")
            annotation = annotate_issues(
                batch,
                typo_result.issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(annotation.output_files, [])
            self.assertEqual(
                annotation.report.annotations[0].status,
                "skipped",
            )

    def test_pdf_missing_bbox_is_recorded_as_unknown_and_manual(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _, _ = _make_pdf_typo_batch(
                root,
                text="数剧。",
                include_bbox=False,
            )
            batch = Project1Batch.load(batch_path)
            typo_result = scan_batch_typos(batch)
            self.assertEqual(len(typo_result.issues), 1)
            self.assertEqual(
                typo_result.issues[0].metadata["location_granularity"],
                "pdf_unknown",
            )
            locations = locate_issues(batch, typo_result.issues)
            self.assertNotEqual(locations[0].locator_status, "located")
            annotation = annotate_issues(
                batch,
                typo_result.issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(annotation.output_files, [])
            self.assertEqual(
                annotation.report.annotations[0].status,
                "skipped",
            )


class TypoPipelineTests(unittest.TestCase):
    def test_word_high_confidence_typo_pipeline_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, docx_path = _make_word_typo_batch(
                root,
                paragraphs=["本次数剧由合成测试生成。"],
                table_rows=[["数剧", "正确"]],
            )
            source_hash = _sha256(docx_path)
            result = run_audit(batch_path, root / "output")
            pipeline = result.report.metadata["pipeline"]
            self.assertEqual(
                pipeline["counts"],
                {
                    "record_count": 0,
                    "verified_count": 0,
                    "unverified_count": 0,
                    "issue_count": 2,
                    "located_count": 2,
                    "annotation_applied_count": 2,
                    "annotation_failed_count": 0,
                    "annotation_manual_review_count": 0,
                    "issues_flagged_for_manual_review": 0,
                },
            )
            self.assertEqual(
                pipeline["typo_counts"],
                {
                    "typo_issue_count": 2,
                    "typo_verified_count": 2,
                    "typo_manual_review_count": 0,
                    "typo_annotation_success_count": 2,
                    "typo_annotation_failed_count": 0,
                },
            )
            self.assertTrue(pipeline["synthetic_data"])
            self.assertTrue(pipeline["complete_success"])
            self.assertEqual(len(result.output_files), 1)
            self.assertEqual(_sha256(docx_path), source_hash)
            payload = json.loads(
                result.audit_json_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["metadata"]["pipeline"]["typo_counts"]["typo_issue_count"],
                2,
            )
            markdown = result.audit_markdown_path.read_text(encoding="utf-8")
            self.assertIn("## 错别字检查统计", markdown)
            self.assertIn("## 错别字检查明细", markdown)
            self.assertIn("本次数剧", markdown)

    def test_word_low_confidence_typo_is_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _ = _make_word_typo_batch(
                root,
                paragraphs=["临测数据。"],
            )
            result = run_audit(batch_path, root / "output")
            pipeline = result.report.metadata["pipeline"]
            self.assertEqual(pipeline["counts"]["issue_count"], 1)
            self.assertEqual(pipeline["counts"]["located_count"], 1)
            self.assertEqual(pipeline["counts"]["annotation_applied_count"], 0)
            self.assertEqual(pipeline["counts"]["annotation_manual_review_count"], 1)
            self.assertEqual(
                pipeline["typo_counts"],
                {
                    "typo_issue_count": 1,
                    "typo_verified_count": 0,
                    "typo_manual_review_count": 1,
                    "typo_annotation_success_count": 0,
                    "typo_annotation_failed_count": 0,
                },
            )
            self.assertFalse(pipeline["complete_success"])
            self.assertEqual(result.output_files, [])

    def test_word_typo_location_failure_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _ = _make_word_typo_batch(
                root,
                paragraphs=["数剧。"],
                paragraph_indices=[999],
            )
            result = run_audit(batch_path, root / "output")
            pipeline = result.report.metadata["pipeline"]
            self.assertEqual(pipeline["typo_counts"]["typo_issue_count"], 1)
            self.assertEqual(pipeline["typo_counts"]["typo_verified_count"], 1)
            self.assertEqual(pipeline["typo_counts"]["typo_manual_review_count"], 1)
            self.assertEqual(
                pipeline["typo_counts"]["typo_annotation_success_count"], 0
            )
            self.assertEqual(pipeline["counts"]["located_count"], 0)
            self.assertEqual(
                pipeline["counts"]["annotation_manual_review_count"], 1
            )
            self.assertFalse(pipeline["complete_success"])
            self.assertEqual(result.output_files, [])

    def test_pdf_high_confidence_typo_pipeline_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, pdf_path, _ = _make_pdf_typo_batch(
                root,
                text="本次数剧由合成测试生成。",
            )
            source_hash = _sha256(pdf_path)
            result = run_audit(batch_path, root / "output")
            pipeline = result.report.metadata["pipeline"]
            self.assertEqual(pipeline["counts"]["issue_count"], 1)
            self.assertEqual(pipeline["counts"]["located_count"], 1)
            self.assertEqual(pipeline["counts"]["annotation_applied_count"], 1)
            self.assertEqual(pipeline["counts"]["annotation_failed_count"], 0)
            self.assertEqual(pipeline["counts"]["annotation_manual_review_count"], 0)
            self.assertEqual(
                pipeline["typo_counts"],
                {
                    "typo_issue_count": 1,
                    "typo_verified_count": 1,
                    "typo_manual_review_count": 0,
                    "typo_annotation_success_count": 1,
                    "typo_annotation_failed_count": 0,
                },
            )
            self.assertTrue(pipeline["synthetic_data"])
            self.assertTrue(pipeline["complete_success"])
            self.assertEqual(len(result.output_files), 1)
            self.assertTrue(result.output_files[0].name.endswith("_annotated.pdf"))
            self.assertEqual(_sha256(pdf_path), source_hash)

    def test_professional_terms_pipeline_has_no_typo_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_path, _ = _make_word_typo_batch(
                root,
                paragraphs=[
                    "化学需氧量、氨氮、总磷、总氮、二氧化硫、氮氧化物、颗粒物。",
                    "青禾环保材料有限公司（虚构）",
                    "执行标准 GB 3838-2002 和 HJ 828-2017。",
                ],
            )
            result = run_audit(batch_path, root / "output")
            pipeline = result.report.metadata["pipeline"]
            self.assertEqual(pipeline["typo_counts"]["typo_issue_count"], 0)
            self.assertEqual(pipeline["counts"]["issue_count"], 0)
            self.assertEqual(result.output_files, [])

    def test_real_batch_typo_counts_are_consistent_and_not_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_audit(REAL_BATCH_PATH, root / "output")
            pipeline = result.report.metadata["pipeline"]
            typo_issues = [
                issue for issue in result.report.issues if issue.issue_type == "typo"
            ]
            self.assertEqual(
                pipeline["typo_counts"]["typo_issue_count"], len(typo_issues)
            )
            high_count = len(
                [
                    issue
                    for issue in typo_issues
                    if issue.metadata.get("typo_confidence") == "high"
                ]
            )
            low_count = len(
                [
                    issue
                    for issue in typo_issues
                    if issue.metadata.get("typo_confidence") == "low"
                ]
            )
            self.assertEqual(
                pipeline["typo_counts"]["typo_verified_count"], high_count
            )
            self.assertEqual(
                pipeline["typo_counts"]["typo_issue_count"],
                high_count + low_count,
            )
            self.assertFalse(pipeline["synthetic_data"])
            self.assertTrue(REAL_BATCH_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
