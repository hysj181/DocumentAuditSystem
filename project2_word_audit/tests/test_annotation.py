from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree

import pymupdf
from docx import Document
from docx.document import Document as DocumentClass
from real_batch_support import real_batch_path
from word_audit import word_annotator
from word_audit.annotation import annotate_issues
from word_audit.annotation_common import build_comment_text
from word_audit.location import locate_issue, locate_issues
from word_audit.math_audit import validate_batch
from word_audit.models import (
    LOCATION_LOCATED,
    LOCATION_MANUAL_REVIEW,
    VERIFICATION_VERIFIED,
    AuditIssue,
    CalculationInfo,
    LocationResult,
    SourceLocation,
)
from word_audit.project1_batch import Project1Batch

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_read(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


def _comments(path: Path) -> list[ElementTree.Element]:
    root = ElementTree.fromstring(_zip_read(path, "word/comments.xml"))
    return list(root.findall(f"{W}comment"))


def _comment_by_id(path: Path, comment_id: int) -> ElementTree.Element:
    identifier = str(comment_id)
    matches = [
        comment
        for comment in _comments(path)
        if comment.get(f"{W}id") == identifier
    ]
    assert len(matches) == 1
    return matches[0]


def _comment_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag == f"{W}t":
            parts.append(element.text or "")
        elif element.tag == f"{W}tab":
            parts.append("\t")
        elif element.tag == f"{W}br":
            parts.append("\n")
    return "".join(parts)


def _comment_text(comment: ElementTree.Element) -> str:
    paragraphs = comment.findall(f"{W}p")
    return "\n".join(
        _comment_paragraph_text(paragraph) for paragraph in paragraphs
    )


def _marker_counts(path: Path, comment_id: int) -> tuple[int, int, int]:
    root = ElementTree.fromstring(_zip_read(path, "word/document.xml"))
    identifier = str(comment_id)
    starts = [
        element
        for element in root.iter(f"{W}commentRangeStart")
        if element.get(f"{W}id") == identifier
    ]
    ends = [
        element
        for element in root.iter(f"{W}commentRangeEnd")
        if element.get(f"{W}id") == identifier
    ]
    references = [
        element
        for element in root.iter(f"{W}commentReference")
        if element.get(f"{W}id") == identifier
    ]
    return len(starts), len(ends), len(references)


def _comment_range_text(path: Path, comment_id: int) -> str:
    root = ElementTree.fromstring(_zip_read(path, "word/document.xml"))
    identifier = str(comment_id)
    inside = False
    parts: list[str] = []
    for element in root.iter():
        if (
            element.tag == f"{W}commentRangeStart"
            and element.get(f"{W}id") == identifier
        ):
            inside = True
            continue
        if (
            element.tag == f"{W}commentRangeEnd"
            and element.get(f"{W}id") == identifier
        ):
            inside = False
            continue
        if inside and element.tag == f"{W}t":
            parts.append(element.text or "")
    return "".join(parts)


def _assert_native_comment_annotation(
    output_path: Path,
    annotation,
) -> None:
    comment_id = annotation.metadata.get("comment_id")
    assert comment_id is not None
    anchor_text = annotation.word_anchor.get("anchor_text") if annotation.word_anchor else None
    assert anchor_text
    comment = _comment_by_id(output_path, comment_id)
    assert _comment_text(comment) == annotation.comment_text
    assert comment.get(f"{W}author") == "DocumentAuditSystem"
    assert comment.get(f"{W}initials") == "DAS"
    assert _marker_counts(output_path, comment_id) == (1, 1, 1)
    assert _comment_range_text(output_path, comment_id) == anchor_text


def _table_text_snapshot(tables) -> list:
    snapshot = []
    for table in tables:
        rows = []
        for row in table.rows:
            rows.append(
                [
                    {
                        "paragraphs": [
                            paragraph.text for paragraph in cell.paragraphs
                        ],
                        "tables": _table_text_snapshot(cell.tables),
                    }
                    for cell in row.cells
                ]
            )
        snapshot.append(rows)
    return snapshot


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
        issue_type="calculation_error" if calculation else "other",
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


class AnnotationTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.batch_path = real_batch_path()
        cls.batch = Project1Batch.load(cls.batch_path)
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

    def word_cell_location(
        self,
        row: int,
        column: int,
        *,
        value_row: int | None = None,
        value_column: int | None = None,
    ) -> SourceLocation:
        return SourceLocation(
            document_id=self.word.document_id,
            source_file=self.word.source_file,
            source_name=self.word.source_name,
            file_type="word",
            table_index=0,
            row_index=row,
            column_index=column,
            value_row_index=value_row,
            value_column_index=value_column,
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
        original_text: str | None = None,
    ) -> AuditIssue:
        record = self.paragraph_record(index)
        return _synthetic_issue(
            issue_id,
            description,
            original_text if original_text is not None else record.text,
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

    def assert_original_word_preserved(self, annotated_path: Path) -> None:
        original = Document(self.word.source_file)
        annotated = Document(str(annotated_path))

        self.assertEqual(
            [paragraph.text for paragraph in annotated.paragraphs],
            [paragraph.text for paragraph in original.paragraphs],
        )
        self.assertFalse(
            any(
                paragraph.text.startswith("#")
                for paragraph in annotated.paragraphs
            )
        )
        self.assertEqual(
            _table_text_snapshot(annotated.tables),
            _table_text_snapshot(original.tables),
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

            body_annotation = next(
                item
                for item in result.report.annotations
                if item.issue_id == "word-paragraph"
            )
            table_annotation = next(
                item
                for item in result.report.annotations
                if item.issue_id == "word-cell"
            )
            _assert_native_comment_annotation(docx_path, body_annotation)
            _assert_native_comment_annotation(docx_path, table_annotation)
            self.assertEqual(
                body_annotation.comment_text,
                build_comment_text(issues[0]),
            )
            self.assertEqual(
                table_annotation.comment_text,
                build_comment_text(issues[1]),
            )
            self.assertEqual(len(_comments(docx_path)), 2)
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
            self.assertEqual(
                [item.status for item in result.report.annotations],
                ["applied", "skipped"],
            )
            self.assertEqual(
                result.report.metadata["annotation_task"]["counts"],
                {"total": 2, "applied": 1, "failed": 0, "manual_review": 1},
            )
            first = result.report.annotations[0]
            second = result.report.annotations[1]
            self.assertIn(
                second.error,
                {"overlapping_comment_range", "existing_comment_range"},
            )
            docx_path = next(
                path for path in result.output_files if path.suffix == ".docx"
            )
            _assert_native_comment_annotation(docx_path, first)
            self.assertEqual(len(_comments(docx_path)), 1)
            self.assert_original_word_preserved(docx_path)

    def test_same_paragraph_non_overlapping_comments(self) -> None:
        record = self.paragraph_record(1)
        text = record.text.strip()
        self.assertGreater(len(text), 8)
        first_anchor = text[:4]
        second_anchor = text[-4:]
        self.assertNotEqual(first_anchor, second_anchor)
        issues = [
            self.word_paragraph_issue(
                "non-overlap-1",
                index=1,
                original_text=first_anchor,
            ),
            self.word_paragraph_issue(
                "non-overlap-2",
                index=1,
                original_text=second_anchor,
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
            self.assertEqual(
                [item.status for item in result.report.annotations],
                ["applied", "applied"],
            )
            docx_path = next(
                path for path in result.output_files if path.suffix == ".docx"
            )
            for annotation in result.report.annotations:
                _assert_native_comment_annotation(docx_path, annotation)
            self.assertEqual(len(_comments(docx_path)), 2)
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
            applied = [
                item
                for item in result.report.annotations
                if item.status == "applied"
            ]
            self.assertEqual(len(applied), 1)
            _assert_native_comment_annotation(docx_path, applied[0])
            self.assertEqual(len(_comments(docx_path)), 1)
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
        issue = _synthetic_issue(
            "verified-calculation",
            "verified calculation",
            self.word_table.rows[2][1],
            self.word_cell_location(
                2,
                1,
                value_row=2,
                value_column=1,
            ),
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
            annotation = result.report.annotations[0]
            self.assertEqual(annotation.status, "applied")
            self.assertEqual(annotation.metadata["anchor_text"], "12.5")
            _assert_native_comment_annotation(docx_path, annotation)
            self.assertIn(
                "\u7ecf\u8ba1\u7b97\u4e3a 15 %",
                annotation.comment_text,
            )
            self.assertNotIn(
                "\u4e0d\u5e94\u4f7f\u7528\u7684\u672a\u9a8c\u8bc1\u5efa\u8bae",
                annotation.comment_text,
            )
            self.assert_original_word_preserved(docx_path)

    def test_word_writer_failure_is_reported(self) -> None:
        issue = self.word_paragraph_issue("writer-failure", index=1)
        location = locate_issue(self.batch, issue)
        self.assertEqual(location.locator_status, LOCATION_LOCATED)
        source_hash = _sha256(Path(self.word.source_file))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(
                word_annotator,
                "add_span_comment",
                side_effect=RuntimeError("writer failed"),
            ):
                result = annotate_issues(
                    self.batch,
                    [issue],
                    [location],
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
            self.assertEqual(annotation.error, "word_comment_creation_failed")
            self.assertIn(
                "writer failed",
                annotation.metadata.get("error_detail", ""),
            )

        self.assertEqual(_sha256(Path(self.word.source_file)), source_hash)

    def test_word_save_failure_is_reported(self) -> None:
        issue = self.word_paragraph_issue("save-failure", index=1)
        location = locate_issue(self.batch, issue)
        source_hash = _sha256(Path(self.word.source_file))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(
                DocumentClass,
                "save",
                side_effect=RuntimeError("save failed"),
            ):
                result = annotate_issues(
                    self.batch,
                    [issue],
                    [location],
                    output_dir=root / "annotated",
                    report_dir=root / "reports",
                )
            self.assertEqual(result.output_files, [])
            counts = result.report.metadata["annotation_task"]["counts"]
            self.assertEqual(counts["applied"], 0)
            self.assertEqual(counts["failed"], 1)
            annotation = result.report.annotations[0]
            self.assertEqual(annotation.status, "failed")
            self.assertEqual(annotation.error, "word_save_failed")
            self.assertIn(
                "save failed",
                annotation.metadata.get("error_detail", ""),
            )

        self.assertEqual(_sha256(Path(self.word.source_file)), source_hash)

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
            self.batch_path,
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
