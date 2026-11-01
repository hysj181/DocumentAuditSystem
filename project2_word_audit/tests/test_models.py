from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from word_audit.error_list import ErrorList, load_error_list, save_error_list
from word_audit.models import (
    ANNOTATION_APPLIED,
    ISSUE_TYPE_CALCULATION,
    LOCATOR_EXACT_INDEX,
    LOCATOR_TABLE_CELL,
    LOCATOR_UNKNOWN,
    SEVERITY_ERROR,
    VERIFICATION_NOT_ATTEMPTED,
    VERIFICATION_VERIFIED,
    AnnotationResult,
    AuditIssue,
    AuditReport,
    CalculationInfo,
    CalculationOperand,
    LocationResult,
    SourceLocation,
)


def word_table_location() -> SourceLocation:
    return SourceLocation(
        document_id="19353a83da7e47c1b236f87ff7036c71",
        source_file="D:\\sample\\01_企业废水监测报告.docx",
        source_name="01_企业废水监测报告.docx",
        file_type="word",
        table_index=0,
        row_index=1,
        column_index=0,
        value_row_index=1,
        value_column_index=1,
        source_content_type="table",
        locator_method=LOCATOR_TABLE_CELL,
        locator_confidence=0.95,
        notes=["数值列由表头“监测结果”映射"],
    )


class SourceLocationTests(unittest.TestCase):
    def test_round_trip_preserves_word_indices(self) -> None:
        location = word_table_location()
        restored = SourceLocation.from_dict(location.to_dict())
        self.assertEqual(restored.to_dict(), location.to_dict())
        self.assertTrue(restored.is_word_anchor)
        self.assertTrue(restored.is_table_anchor)
        self.assertTrue(restored.has_value_cell)

    def test_paragraph_anchor_is_word_anchor(self) -> None:
        location = SourceLocation(
            document_id="doc-1",
            source_file="D:\\sample\\report.docx",
            file_type="word",
            paragraph_index=3,
            source_content_type="paragraph",
            locator_method=LOCATOR_EXACT_INDEX,
            locator_confidence=0.99,
        )
        self.assertTrue(location.is_word_anchor)
        self.assertFalse(location.is_table_anchor)
        self.assertFalse(location.has_value_cell)

    def test_rejects_invalid_confidence(self) -> None:
        with self.assertRaises(ValueError):
            SourceLocation(
                document_id="doc-1",
                source_file="D:\\sample\\report.docx",
                paragraph_index=0,
                locator_method=LOCATOR_EXACT_INDEX,
                locator_confidence=1.5,
            )

    def test_rejects_fractional_index(self) -> None:
        with self.assertRaises(ValueError):
            SourceLocation(
                document_id="doc-1",
                source_file="D:\\sample\\report.docx",
                paragraph_index=3.5,
                locator_method=LOCATOR_EXACT_INDEX,
                locator_confidence=0.9,
            )

    def test_rejects_claimed_location_without_indices(self) -> None:
        with self.assertRaises(ValueError):
            SourceLocation(
                document_id="doc-1",
                source_file="D:\\sample\\report.docx",
                locator_method=LOCATOR_EXACT_INDEX,
                locator_confidence=0.9,
            )

    def test_unknown_location_is_allowed(self) -> None:
        location = SourceLocation(
            document_id="doc-1",
            source_file="D:\\sample\\report.docx",
        )
        self.assertEqual(location.locator_method, LOCATOR_UNKNOWN)
        self.assertEqual(location.locator_confidence, 0.0)
        self.assertFalse(location.is_word_anchor)

    def test_missing_document_identity_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SourceLocation(document_id="", source_file="D:\\sample\\report.docx")


class CalculationInfoTests(unittest.TestCase):
    def test_rejects_computed_value_without_verified_status(self) -> None:
        with self.assertRaises(ValueError):
            CalculationInfo(
                formula="1 + 1",
                computed_value=2.0,
                verification_status=VERIFICATION_NOT_ATTEMPTED,
            )

    def test_rejects_verified_without_computed_value(self) -> None:
        with self.assertRaises(ValueError):
            CalculationInfo(
                formula="1 + 1",
                verification_status=VERIFICATION_VERIFIED,
            )

    def test_verified_calculation_round_trip(self) -> None:
        calculation = CalculationInfo(
            formula="(100 - 85) / 100 * 100",
            substituted_formula="(100 - 85) / 100 * 100",
            operands=[
                CalculationOperand(name="进水", numeric_value=100.0, unit="mg/L"),
                CalculationOperand(name="出水", numeric_value=85.0, unit="mg/L"),
            ],
            reported_value=12.5,
            computed_value=15.0,
            unit="%",
            tolerance=0.1,
            verification_status=VERIFICATION_VERIFIED,
            verification_method="decimal",
            verification_detail="15.0",
        )
        self.assertTrue(calculation.is_verified)
        self.assertIsNotNone(calculation.verified_at)
        restored = CalculationInfo.from_dict(calculation.to_dict())
        self.assertEqual(restored.to_dict(), calculation.to_dict())

    def test_computed_value_in_json_requires_verified_status(self) -> None:
        payload = {
            "formula": "1 + 1",
            "computed_value": 2.0,
            "verification_status": "not_attempted",
        }
        with self.assertRaises(ValueError):
            CalculationInfo.from_dict(payload)


class AuditIssueTests(unittest.TestCase):
    def test_issue_exposes_required_fields(self) -> None:
        issue = AuditIssue(
            issue_id="issue-1",
            issue_type=ISSUE_TYPE_CALCULATION,
            severity=SEVERITY_ERROR,
            description="计算结果不一致",
            original_text="COD 85 mg/L",
            location=word_table_location(),
            calculation=CalculationInfo(
                formula="1 + 1",
                reported_value=3,
                computed_value=2.0,
                verification_status=VERIFICATION_VERIFIED,
                verification_method="decimal",
            ),
            needs_manual_review=False,
            suggestion="请核对",
        )
        self.assertEqual(issue.issue_id, "issue-1")
        self.assertEqual(issue.formula, "1 + 1")
        self.assertEqual(issue.reported_value, 3)
        self.assertEqual(issue.computed_value, 2.0)
        self.assertEqual(issue.location_confidence, 0.95)
        self.assertTrue(issue.is_calculation_verified)
        self.assertEqual(issue.location.table_index, 0)

    def test_missing_location_forces_manual_review_reason(self) -> None:
        issue = AuditIssue(
            issue_id="issue-2",
            issue_type="other",
            description="无法定位",
        )
        self.assertTrue(issue.needs_manual_review)
        self.assertIn("location_missing", issue.review_reasons)

    def test_missing_location_cannot_skip_manual_review(self) -> None:
        with self.assertRaises(ValueError):
            AuditIssue(
                issue_id="issue-3",
                issue_type="other",
                description="无法定位",
                needs_manual_review=False,
            )

    def test_issue_round_trip(self) -> None:
        issue = AuditIssue(
            issue_id="issue-4",
            issue_type=ISSUE_TYPE_CALCULATION,
            description="计算结果不一致",
            original_text="COD 85 mg/L",
            location=word_table_location(),
            calculation=CalculationInfo(
                formula="1 + 1",
                computed_value=2.0,
                verification_status=VERIFICATION_VERIFIED,
                verification_method="decimal",
            ),
            needs_manual_review=False,
        )
        restored = AuditIssue.from_dict(issue.to_dict())
        self.assertEqual(restored.to_dict(), issue.to_dict())


class AnnotationResultTests(unittest.TestCase):
    def test_applied_status_sets_timestamp(self) -> None:
        annotation = AnnotationResult(
            annotation_id="annotation-1",
            issue_id="issue-1",
            document_id="19353a83da7e47c1b236f87ff7036c71",
            comment_text="请核对计算结果。",
            anchor=word_table_location(),
            status=ANNOTATION_APPLIED,
        )
        self.assertIsNotNone(annotation.applied_at)
        self.assertEqual(annotation.anchor_confidence, 0.95)

    def test_document_mismatch_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AnnotationResult(
                annotation_id="annotation-1",
                issue_id="issue-1",
                document_id="another-document",
                comment_text="请核对。",
                anchor=word_table_location(),
            )

    def test_annotation_round_trip(self) -> None:
        annotation = AnnotationResult(
            annotation_id="annotation-1",
            issue_id="issue-1",
            document_id="19353a83da7e47c1b236f87ff7036c71",
            comment_text="请核对计算结果。",
            anchor=word_table_location(),
        )
        restored = AnnotationResult.from_dict(annotation.to_dict())
        self.assertEqual(restored.to_dict(), annotation.to_dict())


class LocationResultTests(unittest.TestCase):
    def test_located_result_round_trip(self) -> None:
        result = LocationResult(
            issue_id="issue-1",
            document_id="doc-1",
            file_type="word",
            locator_status="located",
            paragraph_index=2,
            matched_text="示例段落",
            locator_confidence=0.95,
            needs_manual_review=False,
        )
        restored = LocationResult.from_dict(result.to_dict())
        self.assertEqual(restored.to_dict(), result.to_dict())
        self.assertTrue(restored.is_located)

        payload = result.to_dict()
        del payload["needs_manual_review"]
        inferred = LocationResult.from_dict(payload)
        self.assertFalse(inferred.needs_manual_review)

    def test_located_result_cannot_require_manual_review(self) -> None:
        with self.assertRaises(ValueError):
            LocationResult(
                issue_id="issue-1",
                document_id="doc-1",
                file_type="word",
                locator_status="located",
                paragraph_index=2,
                locator_confidence=0.95,
                needs_manual_review=True,
            )

    def test_manual_review_result_must_require_review(self) -> None:
        with self.assertRaises(ValueError):
            LocationResult(
                issue_id="issue-1",
                document_id="doc-1",
                file_type="word",
                locator_status="manual_review",
                needs_manual_review=False,
            )


class AuditReportTests(unittest.TestCase):
    def _issue(self, issue_id: str, severity: str = "warning") -> AuditIssue:
        return AuditIssue(
            issue_id=issue_id,
            issue_type="other",
            severity=severity,
            description="示例问题",
            location=word_table_location(),
        )

    def test_summary_counts(self) -> None:
        issue = self._issue("issue-1", SEVERITY_ERROR)
        report = AuditReport(
            report_id="report-1",
            batch_id="batch-1",
            issues=[issue],
            annotations=[
                AnnotationResult(
                    annotation_id="annotation-1",
                    issue_id="issue-1",
                    document_id="19353a83da7e47c1b236f87ff7036c71",
                    comment_text="请核对。",
                    anchor=word_table_location(),
                )
            ],
        )
        report.validate()
        summary = report.summary()
        self.assertEqual(summary["issue_count"], 1)
        self.assertEqual(summary["annotation_count"], 1)
        self.assertEqual(summary["needs_manual_review_count"], 1)
        self.assertEqual(summary["verified_calculation_count"], 0)
        self.assertEqual(summary["by_severity"]["error"], 1)
        self.assertEqual(summary["annotations_by_status"]["pending"], 1)

    def test_duplicate_issue_id_is_rejected(self) -> None:
        report = AuditReport(
            report_id="report-1",
            issues=[self._issue("issue-1"), self._issue("issue-1")],
        )
        with self.assertRaises(ValueError):
            report.validate()

    def test_annotation_with_unknown_issue_is_rejected(self) -> None:
        report = AuditReport(
            report_id="report-1",
            issues=[self._issue("issue-1")],
            annotations=[
                AnnotationResult(
                    annotation_id="annotation-1",
                    issue_id="issue-missing",
                    document_id="19353a83da7e47c1b236f87ff7036c71",
                    comment_text="请核对。",
                    anchor=word_table_location(),
                )
            ],
        )
        with self.assertRaises(ValueError):
            report.validate()

    def test_report_round_trip(self) -> None:
        report = AuditReport(
            report_id="report-1",
            batch_id="batch-1",
            documents=[
                {
                    "document_id": "19353a83da7e47c1b236f87ff7036c71",
                    "source_name": "01_企业废水监测报告.docx",
                    "source_file": "D:\\sample\\01_企业废水监测报告.docx",
                    "file_type": "word",
                }
            ],
            issues=[self._issue("issue-1")],
        )
        restored = AuditReport.from_dict(report.to_dict())
        self.assertEqual(restored.to_dict(), report.to_dict())


class ErrorListTests(unittest.TestCase):
    def _error_list(self) -> ErrorList:
        return ErrorList(
            batch_id="20261101T053459830362Z_0e022780",
            source={"producer": "test"},
            issues=[
                AuditIssue(
                    issue_id="issue-1",
                    issue_type=ISSUE_TYPE_CALCULATION,
                    description="计算结果不一致",
                    original_text="COD 85 mg/L",
                    location=word_table_location(),
                    needs_manual_review=False,
                )
            ],
        )

    def test_save_and_load_round_trip(self) -> None:
        error_list = self._error_list()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "errors.json"
            save_error_list(error_list, path)
            loaded = load_error_list(path)
            self.assertEqual(loaded.to_dict(), error_list.to_dict())
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
            self.assertEqual(payload["issue_count"], 1)
            self.assertIn("计算结果不一致", text)
            self.assertIn("企业废水监测报告", text)

    def test_duplicate_issue_id_is_rejected(self) -> None:
        error_list = ErrorList(
            issues=[
                AuditIssue(
                    issue_id="issue-1",
                    issue_type="other",
                    description="a",
                ),
                AuditIssue(
                    issue_id="issue-1",
                    issue_type="other",
                    description="b",
                ),
            ]
        )
        with self.assertRaises(ValueError):
            error_list.validate()

    def test_unsupported_schema_version_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ErrorList(schema_version="2.0")

    def test_missing_schema_version_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ErrorList.from_dict({"issues": []})

    def test_non_object_issue_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ErrorList.from_dict({"schema_version": "1.0", "issues": ["bad"]})

    def test_error_list_to_report(self) -> None:
        error_list = self._error_list()
        report = error_list.to_report(report_id="report-1")
        self.assertEqual(report.batch_id, error_list.batch_id)
        self.assertEqual(len(report.issues), 1)
        report.validate()


class ProjectOneShapeTests(unittest.TestCase):
    def test_project_one_environmental_location_shape(self) -> None:
        location = SourceLocation.from_dict(
            {
                "document_id": "19353a83da7e47c1b236f87ff7036c71",
                "source_file": "D:\\DocumentAuditSystem\\project1_extraction\\test_data\\01_企业废水监测报告.docx",
                "file_type": "word",
                "paragraph_index": None,
                "table_index": 0,
                "row_index": 1,
                "column_index": 0,
                "page_number": None,
                "bbox": None,
                "block_index": None,
                "reading_order": None,
                "source_content_type": "table",
                "locator_method": LOCATOR_TABLE_CELL,
                "locator_confidence": 0.9,
            }
        )
        self.assertEqual(location.table_index, 0)
        self.assertEqual(location.row_index, 1)
        self.assertEqual(location.column_index, 0)
        self.assertIsNone(location.page_number)
        self.assertFalse(location.has_value_cell)


if __name__ == "__main__":
    unittest.main()
