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
from word_audit.location import locate_issue, locate_issues
from word_audit.math_audit import validate_batch
from word_audit.models import (
    LOCATION_LOCATED,
    LOCATION_MANUAL_REVIEW,
    AuditIssue,
    CalculationInfo,
    LocationResult,
    SourceLocation,
    VERIFICATION_VERIFIED,
)
from word_audit.project1_batch import Project1Batch

BATCH_PATH = (
    Path(__file__).resolve().parents[2]
    / "project1_extraction"
    / "output"
    / "batches"
    / "20261101T053459830362Z_0e022780"
    / "batch.json"
)

RED = RGBColor(0xFF, 0x00, 0x00)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _synthetic_issue(
    issue_id: str,
    description: str,
    original_text: str,
    location: SourceLocation,
    *,
    suggestion: str = "合成测试建议：仅验证批注写入，不代表真实审核结论。",
    calculation: CalculationInfo | None = None,
) -> AuditIssue:
    return AuditIssue(
        issue_id=issue_id,
        issue_type="calculation_error" if calculation else "value_mismatch",
        description=f"合成测试：{description}",
        original_text=original_text,
        location=location,
        calculation=calculation,
        suggestion=suggestion,
        needs_manual_review=False,
        metadata={
            "synthetic": True,
            "synthetic_note": "合成测试数据，非项目一真实计算错误",
        },
    )


@unittest.skipUnless(BATCH_PATH.is_file(), f"real batch not found: {BATCH_PATH}")
class AnnotationTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.batch = Project1Batch.load(BATCH_PATH)
        cls.word = next(d for d in cls.batch.documents if d.file_type == "word")
        cls.pdf = next(d for d in cls.batch.documents if d.file_type == "pdf")
        cls.word_table = next(
            record for record in cls.word.records if record.content_type == "table"
        )
        cls.validation = validate_batch(cls.batch)
        cls.validation_by_id = {
            item.record_id: item for item in cls.validation.records
        }
        cls.pdf_record = next(
            record
            for record in cls.batch.environmental_records
            if record.file_type == "pdf"
        )

    def paragraph_record(self, index: int):
        return next(
            record
            for record in self.word.records
            if record.paragraph_index == index
            and record.content_type in {"heading", "paragraph"}
        )

    def word_paragraph_location(self, index: int) -> SourceLocation:
        return SourceLocation(
            document_id=self.word.document_id,
            source_file=self.word.source_file,
            source_name=self.word.source_name,
            file_type="word",
            paragraph_index=index,
            source_content_type="paragraph",
            locator_method="exact_index",
            locator_confidence=0.95,
        )

    def word_cell_location(self, row: int, column: int) -> SourceLocation:
        return SourceLocation(
            document_id=self.word.document_id,
            source_file=self.word.source_file,
            source_name=self.word.source_name,
            file_type="word",
            table_index=0,
            row_index=row,
            column_index=column,
            source_content_type="table",
            locator_method="table_cell",
            locator_confidence=0.95,
        )

    def word_paragraph_issue(
        self,
        issue_id: str,
        index: int = 1,
        *,
        description: str = "Word 段落批注",
        suggestion: str = "合成测试建议：仅验证批注写入，不代表真实审核结论。",
        calculation: CalculationInfo | None = None,
    ) -> AuditIssue:
        record = self.paragraph_record(index)
        return _synthetic_issue(
            issue_id,
            description,
            record.text,
            self.word_paragraph_location(index),
            suggestion=suggestion,
            calculation=calculation,
        )

    def word_cell_issue(
        self,
        issue_id: str,
        row: int = 1,
        column: int = 1,
        *,
        description: str = "Word 表格单元格批注",
    ) -> AuditIssue:
        text = self.word_table.rows[row][column]
        return _synthetic_issue(
            issue_id,
            description,
            text,
            self.word_cell_location(row, column),
        )

    def pdf_source_location(self) -> SourceLocation:
        record = self.pdf_record
        validation = self.validation_by_id[record.record_id]
        return SourceLocation(
            document_id=record.document_id,
            source_file=record.source_file,
            source_name=self.pdf.source_name,
            file_type="pdf",
            table_index=record.table_index,
            row_index=record.row_index,
            column_index=record.column_index,
            value_row_index=validation.value_cell.row_index,
            value_column_index=validation.value_cell.column_index,
            page_number=record.page_number,
            bbox=record.bbox,
            source_content_type="table",
            locator_method="table_cell",
            locator_confidence=0.95,
        )

    def pdf_issue(self, issue_id: str = "synthetic-pdf") -> AuditIssue:
        return _synthetic_issue(
            issue_id,
            "PDF 页面标记",
            self.pdf_record.raw_expression,
            self.pdf_source_location(),
        )

    def located(self, issues: list[AuditIssue]) -> list[LocationResult]:
        return locate_issues(self.batch, issues)

    def assert_red_paragraph(self, paragraph) -> None:
        self.assertTrue(paragraph.text.startswith("#"))
        self.assertTrue(paragraph.runs)
        for run in paragraph.runs:
            self.assertEqual(run.font.color.rgb, RED)

    def assert_original_word_preserved(self, annotated_path: Path) -> None:
        original = Document(self.word.source_file)
        annotated = Document(str(annotated_path))

        original_texts = [paragraph.text for paragraph in original.paragraphs]
        annotated_texts = [paragraph.text for paragraph in annotated.paragraphs]
        cursor = 0
        for text in annotated_texts:
            if cursor < len(original_texts) and text == original_texts[cursor]:
                cursor += 1
        self.assertEqual(cursor, len(original_texts))

        self.assertEqual(len(annotated.tables), len(original.tables))
        for original_table, annotated_table in zip(original.tables, annotated.tables):
            self.assertEqual(len(annotated_table.rows), len(original_table.rows))
            self.assertEqual(
                len(annotated_table.columns), len(original_table.columns)
            )
            for row_index, original_row in enumerate(original_table.rows):
                for column_index, original_cell in enumerate(original_row.cells):
                    annotated_cell = annotated_table.rows[row_index].cells[column_index]
                    self.assertEqual(
                        annotated_cell.paragraphs[0].text,
                        original_cell.paragraphs[0].text,
                    )


class WordAnnotationTests(AnnotationTestBase):
    def test_word_paragraph_and_table_cell(self) -> None:
        issues = [
            self.word_paragraph_issue("word-paragraph", index=1),
            self.word_cell_issue("word-cell", row=1, column=1),
        ]
        locations = self.located(issues)
        self.assertEqual(
            [location.locator_status for location in locations],
            [LOCATION_LOCATED, LOCATION_LOCATED],
        )
        word_before = _sha256(Path(self.word.source_file))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(
                result.report.metadata["annotation_task"]["counts"],
                {"total": 2, "applied": 2, "failed": 0, "manual_review": 0},
            )
            docx_path = next(
                path for path in result.output_files if path.suffix == ".docx"
            )
            self.assertTrue(docx_path.name.endswith("_annotated.docx"))
            self.assertTrue(docx_path.is_file())

            annotated = Document(str(docx_path))
            original_paragraph = self.paragraph_record(1).text
            texts = [paragraph.text for paragraph in annotated.paragraphs]
            original_index = texts.index(original_paragraph)
            annotation_paragraph = annotated.paragraphs[original_index + 1]
            self.assert_red_paragraph(annotation_paragraph)
            self.assertIn("[合成测试数据]", annotation_paragraph.text)
            self.assertIn("原文：", annotation_paragraph.text)
            self.assertIn("建议核实：", annotation_paragraph.text)

            cell = annotated.tables[0].rows[1].cells[1]
            self.assertEqual(cell.paragraphs[0].text, "85")
            self.assert_red_paragraph(cell.paragraphs[-1])
            self.assertIn("[合成测试数据]", cell.paragraphs[-1].text)

            self.assert_original_word_preserved(docx_path)

            self.assertTrue(result.json_path.is_file())
            self.assertTrue(result.markdown_path.is_file())

        self.assertEqual(_sha256(Path(self.word.source_file)), word_before)

    def test_multiple_annotations_same_cell(self) -> None:
        issues = [
            self.word_cell_issue(
                "same-cell-1", row=2, column=1, description="同一单元格问题一"
            ),
            self.word_cell_issue(
                "same-cell-2", row=2, column=1, description="同一单元格问题二"
            ),
        ]
        locations = self.located(issues)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            docx_path = next(
                path for path in result.output_files if path.suffix == ".docx"
            )
            annotated = Document(str(docx_path))
            cell = annotated.tables[0].rows[2].cells[1]
            self.assertEqual(len(cell.paragraphs), 3)
            self.assert_red_paragraph(cell.paragraphs[-2])
            self.assert_red_paragraph(cell.paragraphs[-1])
            self.assertIn("同一单元格问题一", cell.paragraphs[-2].text)
            self.assertIn("同一单元格问题二", cell.paragraphs[-1].text)
            self.assert_original_word_preserved(docx_path)

    def test_non_located_statuses_are_not_annotated(self) -> None:
        located_issue = self.word_paragraph_issue("located", index=2)
        ambiguous_issue = _synthetic_issue(
            "ambiguous",
            "歧义问题",
            "模拟检测",
            self.word_paragraph_location(0),
        )
        manual_issue = _synthetic_issue(
            "manual",
            "文本不匹配问题",
            "完全不存在的文本 XYZ",
            self.word_paragraph_location(1),
        )
        invalid_issue = _synthetic_issue(
            "invalid",
            "无效索引问题",
            "COD",
            SourceLocation(
                document_id=self.word.document_id,
                source_file=self.word.source_file,
                file_type="word",
                paragraph_index=999,
                locator_method="exact_index",
                locator_confidence=0.9,
            ),
        )
        not_found_issue = _synthetic_issue(
            "not-found",
            "未知文档问题",
            "COD",
            SourceLocation(
                document_id="missing-document",
                source_file=self.word.source_file,
                file_type="word",
                paragraph_index=0,
                locator_method="exact_index",
                locator_confidence=0.9,
            ),
        )
        issues = [
            located_issue,
            ambiguous_issue,
            manual_issue,
            invalid_issue,
            not_found_issue,
        ]
        locations = self.located(issues)
        self.assertEqual(
            [location.locator_status for location in locations],
            [
                LOCATION_LOCATED,
                "ambiguous",
                LOCATION_MANUAL_REVIEW,
                "invalid_location",
                "not_found",
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            counts = result.report.metadata["annotation_task"]["counts"]
            self.assertEqual(counts["applied"], 1)
            self.assertEqual(counts["manual_review"], 4)
            docx_path = next(
                path for path in result.output_files if path.suffix == ".docx"
            )
            annotated = Document(str(docx_path))
            annotations = [
                paragraph
                for paragraph in annotated.paragraphs
                if paragraph.text.startswith("#")
            ]
            self.assertEqual(len(annotations), 1)
            self.assertNotIn("歧义问题", "\n".join(p.text for p in annotated.paragraphs))
            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            task = payload["metadata"]["annotation_task"]
            self.assertEqual(len(task["manual_review"]), 4)
            self.assertEqual(len(task["failed"]), 0)

    def test_comment_uses_verified_calculation_only(self) -> None:
        calculation = CalculationInfo(
            formula="(100-85)/100*100",
            reported_value=12.5,
            computed_value=15.0,
            unit="%",
            verification_status=VERIFICATION_VERIFIED,
            verification_method="decimal",
        )
        issue = self.word_paragraph_issue(
            "verified-calculation",
            index=3,
            description="已验证计算",
            suggestion="不应使用的未验证建议",
            calculation=calculation,
        )
        location = locate_issue(self.batch, issue)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                [issue],
                [location],
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            docx_path = next(
                path for path in result.output_files if path.suffix == ".docx"
            )
            annotated = Document(str(docx_path))
            annotation = next(
                paragraph
                for paragraph in annotated.paragraphs
                if paragraph.text.startswith("#")
            )
            self.assertIn("经计算为 15 %", annotation.text)
            self.assertNotIn("不应使用的未验证建议", annotation.text)

    def test_word_writer_failure_is_reported(self) -> None:
        issue = self.word_paragraph_issue("writer-failure", index=1)
        location = locate_issue(self.batch, issue)
        self.assertEqual(location.locator_status, LOCATION_LOCATED)
        broken_location = LocationResult(
            issue_id=issue.issue_id,
            document_id=self.word.document_id,
            file_type="word",
            locator_status=LOCATION_LOCATED,
            table_index=99,
            row_index=0,
            column_index=0,
            locator_confidence=0.9,
            needs_manual_review=False,
            source_location=location.source_location,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                [issue],
                [broken_location],
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(result.output_files, [])
            counts = result.report.metadata["annotation_task"]["counts"]
            self.assertEqual(counts["applied"], 0)
            self.assertEqual(counts["failed"], 1)
            self.assertEqual(counts["manual_review"], 0)
            annotation = result.report.annotations[0]
            self.assertEqual(annotation.status, "failed")
            self.assertEqual(annotation.error, "table_index_out_of_range")
            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(
                len(payload["metadata"]["annotation_task"]["failed"]), 1
            )

    def test_reports_and_unique_outputs(self) -> None:
        issue = self.word_paragraph_issue("unique", index=1)
        location = locate_issue(self.batch, issue)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "annotated"
            report_dir = root / "reports"
            first = annotate_issues(
                self.batch,
                [issue],
                [location],
                output_dir=output_dir,
                report_dir=report_dir,
            )
            second = annotate_issues(
                self.batch,
                [issue],
                [location],
                output_dir=output_dir,
                report_dir=report_dir,
            )
            self.assertNotEqual(first.output_files[0], second.output_files[0])
            self.assertNotEqual(first.json_path, second.json_path)
            self.assertTrue(first.output_files[0].is_file())
            self.assertTrue(second.output_files[0].is_file())
            self.assertTrue(first.markdown_path.is_file())
            self.assertTrue(second.markdown_path.is_file())

            payload = json.loads(first.json_path.read_text(encoding="utf-8"))
            task = payload["metadata"]["annotation_task"]
            self.assertTrue(task["synthetic_data"])
            self.assertEqual(task["counts"]["applied"], 1)
            self.assertEqual(len(task["success"]), 1)
            self.assertEqual(task["failed"], [])
            self.assertEqual(task["manual_review"], [])
            self.assertTrue(task["original_files"])
            self.assertTrue(task["output_files"])
            markdown = first.markdown_path.read_text(encoding="utf-8")
            self.assertIn("# 批注任务报告", markdown)
            self.assertIn("## 批注成功清单", markdown)
            self.assertIn("## 批注失败清单", markdown)
            self.assertIn("## 人工核实清单", markdown)
            self.assertIn("合成测试数据", markdown)


class PdfAnnotationTests(AnnotationTestBase):
    def test_pdf_red_rectangle_and_text_preservation(self) -> None:
        issue = self.pdf_issue()
        location = locate_issue(self.batch, issue)
        self.assertEqual(location.locator_status, LOCATION_LOCATED)
        self.assertIsNotNone(location.bbox)
        original_before = _sha256(Path(self.pdf.source_file))
        with pymupdf.open(self.pdf.source_file) as original_pdf:
            original_text = original_pdf.load_page(0).get_text("text")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                [issue],
                [location],
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            pdf_path = next(
                path for path in result.output_files if path.suffix == ".pdf"
            )
            self.assertTrue(pdf_path.name.endswith("_annotated.pdf"))
            with pymupdf.open(str(pdf_path)) as annotated_pdf:
                self.assertEqual(annotated_pdf.page_count, 1)
                page = annotated_pdf.load_page(0)
                self.assertEqual(page.get_text("text"), original_text)
                red_drawings = [
                    drawing
                    for drawing in page.get_drawings()
                    if drawing.get("color")
                    and abs(drawing["color"][0] - 1.0) < 0.01
                    and abs(drawing["color"][1]) < 0.01
                    and abs(drawing["color"][2]) < 0.01
                ]
                self.assertEqual(len(red_drawings), 1)
                rect = red_drawings[0]["rect"]
                expected = location.bbox or []
                self.assertAlmostEqual(rect.x0, expected[0], places=1)
                self.assertAlmostEqual(rect.y0, expected[1], places=1)
                self.assertAlmostEqual(rect.x1, expected[2], places=1)
                self.assertAlmostEqual(rect.y1, expected[3], places=1)
            self.assertEqual(
                result.report.metadata["annotation_task"]["counts"]["applied"], 1
            )
        self.assertEqual(_sha256(Path(self.pdf.source_file)), original_before)

    def test_pdf_located_but_invalid_coordinates_are_skipped(self) -> None:
        issue = self.pdf_issue("pdf-invalid-bbox")
        source_location = self.pdf_source_location()
        invalid_bbox_result = LocationResult(
            issue_id=issue.issue_id,
            document_id=self.pdf.document_id,
            file_type="pdf",
            locator_status=LOCATION_LOCATED,
            page_number=1,
            bbox=[0, 0, 9999, 9999],
            locator_confidence=0.9,
            needs_manual_review=False,
            source_location=source_location,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                [issue],
                [invalid_bbox_result],
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(result.output_files, [])
            counts = result.report.metadata["annotation_task"]["counts"]
            self.assertEqual(counts["applied"], 0)
            self.assertEqual(counts["manual_review"], 1)
            annotation = result.report.annotations[0]
            self.assertEqual(annotation.status, "skipped")
            self.assertEqual(annotation.error, "bbox_outside_page")

    def test_pdf_located_but_invalid_page_is_skipped(self) -> None:
        issue = self.pdf_issue("pdf-invalid-page")
        source_location = self.pdf_source_location()
        invalid_page_result = LocationResult(
            issue_id=issue.issue_id,
            document_id=self.pdf.document_id,
            file_type="pdf",
            locator_status=LOCATION_LOCATED,
            page_number=99,
            bbox=[0, 0, 10, 10],
            locator_confidence=0.9,
            needs_manual_review=False,
            source_location=source_location,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                [issue],
                [invalid_page_result],
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(result.output_files, [])
            counts = result.report.metadata["annotation_task"]["counts"]
            self.assertEqual(counts["applied"], 0)
            self.assertEqual(counts["manual_review"], 1)
            self.assertEqual(
                result.report.annotations[0].error,
                "page_number_out_of_range",
            )

    def test_pdf_non_located_is_not_marked(self) -> None:
        issue = self.pdf_issue("pdf-non-located")
        source_location = self.pdf_source_location()
        manual_result = LocationResult(
            issue_id=issue.issue_id,
            document_id=self.pdf.document_id,
            file_type="pdf",
            locator_status=LOCATION_MANUAL_REVIEW,
            page_number=1,
            bbox=source_location.bbox,
            locator_confidence=0.3,
            needs_manual_review=True,
            failure_reason="text_mismatch",
            source_location=source_location,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                [issue],
                [manual_result],
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(result.output_files, [])
            counts = result.report.metadata["annotation_task"]["counts"]
            self.assertEqual(counts["applied"], 0)
            self.assertEqual(counts["manual_review"], 1)


class AnnotationHashTests(AnnotationTestBase):
    def test_original_files_are_not_modified(self) -> None:
        word_issue = self.word_paragraph_issue("hash-word", index=1)
        pdf_issue = self.pdf_issue("hash-pdf")
        issues = [word_issue, pdf_issue]
        locations = self.located(issues)
        paths = [
            BATCH_PATH,
            Path(self.word.source_file),
            Path(self.pdf.source_file),
        ]
        before = {str(path): _sha256(path) for path in paths}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = annotate_issues(
                self.batch,
                issues,
                locations,
                output_dir=root / "annotated",
                report_dir=root / "reports",
            )
            self.assertEqual(
                result.report.metadata["annotation_task"]["counts"]["applied"], 2
            )
        after = {str(path): _sha256(path) for path in paths}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
