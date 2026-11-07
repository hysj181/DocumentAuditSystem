from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

import pymupdf
from real_batch_support import real_batch_path

from word_audit.location import (
    locate_issue,
    locate_issues,
    summarize_location_results,
)
from word_audit.math_audit import validate_batch
from word_audit.models import AuditIssue, SourceLocation
from word_audit.project1_batch import Project1Batch


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _issue(
    issue_id: str,
    original_text: str,
    location: SourceLocation | None,
    *,
    needs_manual_review: bool = False,
) -> AuditIssue:
    return AuditIssue(
        issue_id=issue_id,
        issue_type="other",
        description=f"location test {issue_id}",
        original_text=original_text,
        location=location,
        needs_manual_review=needs_manual_review,
    )


class RealLocationTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.batch_path = real_batch_path()
        cls.batch = Project1Batch.load(cls.batch_path)
        cls.word = next(d for d in cls.batch.documents if d.file_type == "word")
        cls.pdf = next(d for d in cls.batch.documents if d.file_type == "pdf")
        cls.word_table = next(
            r for r in cls.word.records if r.content_type == "table"
        )
        cls.validation = validate_batch(cls.batch)

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

    def env_location(self, record_id: str) -> tuple[SourceLocation, str, str]:
        record = next(
            item
            for item in self.batch.environmental_records
            if item.record_id == record_id
        )
        validation = next(
            item for item in self.validation.records if item.record_id == record_id
        )
        document = self.batch.document(record.document_id)
        location = SourceLocation(
            document_id=record.document_id,
            source_file=record.source_file,
            source_name=document.source_name if document else None,
            file_type=record.file_type,
            paragraph_index=record.source_location.get("paragraph_index"),
            table_index=record.table_index,
            row_index=record.row_index,
            column_index=record.column_index,
            value_row_index=validation.value_cell.row_index,
            value_column_index=validation.value_cell.column_index,
            page_number=record.page_number,
            bbox=record.bbox,
            source_content_type=record.source_content_type,
            locator_method=(
                "table_cell" if validation.value_cell.found else "exact_index"
            ),
            locator_confidence=(
                validation.value_cell.confidence
                if validation.value_cell.found
                else 0.8
            ),
        )
        return location, record.raw_expression, record.file_type

    def all_real_issues(self) -> list[AuditIssue]:
        issues: list[AuditIssue] = []
        for record in self.word.records:
            if record.content_type not in {"heading", "paragraph"}:
                continue
            issues.append(
                _issue(
                    f"para-{record.paragraph_index}",
                    record.text,
                    self.word_paragraph_location(record.paragraph_index or 0),
                )
            )
        for row_index, row in enumerate(self.word_table.rows):
            for column_index, text in enumerate(row):
                issues.append(
                    _issue(
                        f"cell-{row_index}-{column_index}",
                        text,
                        self.word_cell_location(row_index, column_index),
                    )
                )
        for record in self.batch.environmental_records:
            location, raw_expression, _ = self.env_location(record.record_id)
            issues.append(
                _issue(f"env-{record.record_id}", raw_expression, location)
            )
        return issues


class RealWordLocationTests(RealLocationTestBase):
    def test_five_paragraph_indices(self) -> None:
        records = [
            record
            for record in self.word.records
            if record.content_type in {"heading", "paragraph"}
        ]
        self.assertEqual(len(records), 5)
        issues = [
            _issue(
                f"para-{record.paragraph_index}",
                record.text,
                self.word_paragraph_location(record.paragraph_index or 0),
            )
            for record in records
        ]
        results = locate_issues(self.batch, issues)
        self.assertEqual(summarize_location_results(results)["located"], 5)
        for record, result in zip(records, results):
            with self.subTest(paragraph_index=record.paragraph_index):
                self.assertEqual(result.locator_status, "located")
                self.assertEqual(result.paragraph_index, record.paragraph_index)
                self.assertEqual(result.matched_text, record.text.strip())
                self.assertIsNone(result.table_index)

    def test_six_by_four_table_cells(self) -> None:
        self.assertEqual(len(self.word_table.rows), 6)
        self.assertEqual(len(self.word_table.rows[0]), 4)
        issues = []
        for row_index, row in enumerate(self.word_table.rows):
            for column_index, text in enumerate(row):
                issues.append(
                    _issue(
                        f"cell-{row_index}-{column_index}",
                        text,
                        self.word_cell_location(row_index, column_index),
                    )
                )
        self.assertEqual(len(issues), 24)
        results = locate_issues(self.batch, issues)
        self.assertEqual(summarize_location_results(results)["located"], 24)
        for row_index, row in enumerate(self.word_table.rows):
            for column_index, text in enumerate(row):
                result = results[row_index * 4 + column_index]
                with self.subTest(row=row_index, column=column_index):
                    self.assertEqual(result.locator_status, "located")
                    self.assertEqual(result.table_index, 0)
                    self.assertEqual(result.row_index, row_index)
                    self.assertEqual(result.column_index, column_index)
                    self.assertEqual(result.matched_text, text.strip())

    def test_multiple_issues_same_cell(self) -> None:
        location = self.word_cell_location(1, 1)
        issues = [
            _issue("same-cell-1", "85", location),
            _issue("same-cell-2", "COD\t85\tmg/L\t模拟检测", location),
        ]
        results = locate_issues(self.batch, issues)
        self.assertEqual(summarize_location_results(results)["located"], 2)
        for result in results:
            self.assertEqual(result.locator_status, "located")
            self.assertEqual(result.table_index, 0)
            self.assertEqual(result.row_index, 1)
            self.assertEqual(result.column_index, 1)
        self.assertEqual(results[1].metadata["match_scope"], "row")

    def test_text_mismatch_goes_to_manual_review(self) -> None:
        issue = _issue(
            "mismatch",
            "完全不存在的文本 XYZ",
            self.word_paragraph_location(1),
            needs_manual_review=True,
        )
        result = locate_issue(self.batch, issue)
        self.assertEqual(result.locator_status, "manual_review")
        self.assertTrue(result.needs_manual_review)
        self.assertEqual(result.failure_reason, "text_mismatch")
        self.assertNotEqual(result.locator_status, "located")

    def test_ambiguous_text_goes_to_ambiguous(self) -> None:
        issue = _issue(
            "ambiguous",
            "模拟检测",
            self.word_paragraph_location(0),
            needs_manual_review=True,
        )
        result = locate_issue(self.batch, issue)
        self.assertEqual(result.locator_status, "ambiguous")
        self.assertGreater(result.metadata["candidate_count"], 1)

    def test_invalid_word_indices(self) -> None:
        cases = [
            (
                "paragraph-out-of-range",
                self.word_paragraph_location(999),
                "paragraph_index_out_of_range",
            ),
            (
                "table-out-of-range",
                SourceLocation(
                    document_id=self.word.document_id,
                    source_file=self.word.source_file,
                    file_type="word",
                    table_index=999,
                    row_index=0,
                    column_index=0,
                    locator_method="table_cell",
                    locator_confidence=0.9,
                ),
                "table_index_out_of_range",
            ),
            (
                "row-out-of-range",
                self.word_cell_location(99, 0),
                "row_index_out_of_range",
            ),
            (
                "column-out-of-range",
                self.word_cell_location(0, 99),
                "column_index_out_of_range",
            ),
        ]
        for issue_id, location, expected_reason in cases:
            with self.subTest(issue_id=issue_id):
                result = locate_issue(self.batch, _issue(issue_id, "COD", location))
                self.assertEqual(result.locator_status, "invalid_location")
                self.assertEqual(result.failure_reason, expected_reason)

    def test_missing_location_goes_to_manual_review(self) -> None:
        result = locate_issue(
            self.batch,
            _issue("no-location", "COD", None, needs_manual_review=True),
        )
        self.assertEqual(result.locator_status, "manual_review")
        self.assertEqual(result.failure_reason, "location_missing")

    def test_missing_expected_text_goes_to_manual_review(self) -> None:
        result = locate_issue(
            self.batch,
            _issue("no-text", "", self.word_paragraph_location(0)),
        )
        self.assertEqual(result.locator_status, "manual_review")
        self.assertEqual(result.failure_reason, "no_expected_text")

    def test_file_type_mismatch_is_invalid(self) -> None:
        location = SourceLocation(
            document_id=self.word.document_id,
            source_file=self.word.source_file,
            file_type="pdf",
            page_number=1,
            bbox=[0, 0, 10, 10],
            locator_method="text_match",
            locator_confidence=0.9,
        )
        result = locate_issue(self.batch, _issue("type-mismatch", "COD", location))
        self.assertEqual(result.locator_status, "invalid_location")
        self.assertEqual(result.failure_reason, "file_type_mismatch")

    def test_unknown_document_is_not_found(self) -> None:
        location = SourceLocation(
            document_id="missing-document",
            source_file=self.word.source_file,
            file_type="word",
            paragraph_index=0,
            locator_method="exact_index",
            locator_confidence=0.9,
        )
        result = locate_issue(self.batch, _issue("missing-doc", "COD", location))
        self.assertEqual(result.locator_status, "not_found")
        self.assertEqual(result.failure_reason, "document_not_found_in_batch")


class RealPdfLocationTests(RealLocationTestBase):
    def pdf_issue(self, record_id: str | None = None) -> AuditIssue:
        record = (
            next(item for item in self.batch.environmental_records if item.record_id == record_id)
            if record_id
            else next(
                item
                for item in self.batch.environmental_records
                if item.file_type == "pdf"
            )
        )
        location, raw_expression, _ = self.env_location(record.record_id)
        return _issue(f"pdf-{record.record_id}", raw_expression, location)

    def test_pdf_page_information(self) -> None:
        with pymupdf.open(self.pdf.source_file) as pdf:
            self.assertEqual(pdf.page_count, 1)
            page = pdf.load_page(0)
            self.assertAlmostEqual(page.rect.width, 595.0, places=3)
            self.assertAlmostEqual(page.rect.height, 842.0, places=3)
            self.assertEqual(page.rotation, 0)

    def test_pdf_real_records_locate_with_valid_bbox(self) -> None:
        records = [
            record
            for record in self.batch.environmental_records
            if record.file_type == "pdf"
        ]
        self.assertEqual(len(records), 4)
        issues = [self.pdf_issue(record.record_id) for record in records]
        results = locate_issues(self.batch, issues)
        self.assertEqual(summarize_location_results(results)["located"], 4)
        with pymupdf.open(self.pdf.source_file) as pdf:
            page = pdf.load_page(0)
            for result in results:
                with self.subTest(issue_id=result.issue_id):
                    self.assertEqual(result.locator_status, "located")
                    self.assertEqual(result.page_number, 1)
                    self.assertIsNotNone(result.bbox)
                    x0, y0, x1, y1 = result.bbox or []
                    self.assertGreaterEqual(x0, 0)
                    self.assertGreaterEqual(y0, 0)
                    self.assertLessEqual(x1, page.rect.width)
                    self.assertLessEqual(y1, page.rect.height)
                    self.assertEqual(
                        result.metadata.get("bbox_source"), "project1_cell"
                    )

    def test_pdf_invalid_page_number(self) -> None:
        location = SourceLocation(
            document_id=self.pdf.document_id,
            source_file=self.pdf.source_file,
            file_type="pdf",
            page_number=99,
            bbox=[0, 0, 10, 10],
            locator_method="text_match",
            locator_confidence=0.9,
        )
        result = locate_issue(self.batch, _issue("bad-page", "COD", location))
        self.assertEqual(result.locator_status, "invalid_location")
        self.assertEqual(result.failure_reason, "page_number_out_of_range")

    def test_pdf_invalid_bbox(self) -> None:
        location = SourceLocation(
            document_id=self.pdf.document_id,
            source_file=self.pdf.source_file,
            file_type="pdf",
            page_number=1,
            bbox=[0, 0, 9999, 9999],
            locator_method="text_match",
            locator_confidence=0.9,
        )
        result = locate_issue(self.batch, _issue("bad-bbox", "COD", location))
        self.assertEqual(result.locator_status, "invalid_location")
        self.assertEqual(result.failure_reason, "bbox_outside_page")

    def test_pdf_missing_bbox(self) -> None:
        location = SourceLocation(
            document_id=self.pdf.document_id,
            source_file=self.pdf.source_file,
            file_type="pdf",
            page_number=1,
            locator_method="text_match",
            locator_confidence=0.9,
        )
        result = locate_issue(self.batch, _issue("no-bbox", "COD", location))
        self.assertEqual(result.locator_status, "invalid_location")
        self.assertEqual(result.failure_reason, "bbox_invalid")

    def test_pdf_text_mismatch_goes_to_manual_review(self) -> None:
        issue = self.pdf_issue()
        issue.original_text = "完全不存在的文本 XYZ"
        result = locate_issue(self.batch, issue)
        self.assertEqual(result.locator_status, "manual_review")
        self.assertEqual(result.failure_reason, "text_mismatch")

    def test_pdf_empty_bbox_area_goes_to_manual_review(self) -> None:
        location = SourceLocation(
            document_id=self.pdf.document_id,
            source_file=self.pdf.source_file,
            file_type="pdf",
            page_number=1,
            bbox=[10, 10, 20, 20],
            locator_method="text_match",
            locator_confidence=0.9,
        )
        result = locate_issue(self.batch, _issue("empty-area", "COD", location))
        self.assertEqual(result.locator_status, "manual_review")
        self.assertEqual(result.failure_reason, "no_text_in_bbox")

    def test_pdf_does_not_use_word_paragraph_index(self) -> None:
        location = SourceLocation(
            document_id=self.pdf.document_id,
            source_file=self.pdf.source_file,
            file_type="pdf",
            paragraph_index=0,
            locator_method="exact_index",
            locator_confidence=0.9,
        )
        result = locate_issue(self.batch, _issue("pdf-paragraph", "COD", location))
        self.assertEqual(result.locator_status, "invalid_location")
        self.assertEqual(result.failure_reason, "pdf_page_number_missing")


class RealLocationSummaryTests(RealLocationTestBase):
    def test_all_real_issue_locations(self) -> None:
        issues = self.all_real_issues()
        self.assertEqual(len(issues), 38)
        results = locate_issues(self.batch, issues)
        self.assertEqual(
            summarize_location_results(results),
            {
                "total": 38,
                "located": 38,
                "ambiguous": 0,
                "not_found": 0,
                "invalid_location": 0,
                "manual_review": 0,
                "needs_manual_review": 0,
            },
        )

    def test_original_files_are_not_modified(self) -> None:
        paths = [
            self.batch_path,
            Path(self.word.source_file),
            Path(self.pdf.source_file),
        ]
        before = {str(path): _sha256(path) for path in paths}
        locate_issues(self.batch, self.all_real_issues())
        after = {str(path): _sha256(path) for path in paths}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
