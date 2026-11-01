from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from word_audit.math_audit import validate_batch
from word_audit.project1_batch import Project1Batch

BATCH_PATH = (
    Path(__file__).resolve().parents[2]
    / "project1_extraction"
    / "output"
    / "batches"
    / "20261101T053459830362Z_0e022780"
    / "batch.json"
)

EXPECTED_INDICATORS = [
    "COD",
    "氨氮",
    "总磷",
    "总氮",
    "pH",
    "颗粒物",
    "二氧化硫",
    "氮氧化物",
    "排放速率",
]

EXPECTED_VALUES = [85, 12.5, None, 18.2, 7.3, 8.6, None, 35.2, 0.035]

EXPECTED_UNITS = [
    "mg/L",
    "mg/L",
    "mg/L",
    "mg/L",
    "无量纲",
    "mg/m³",
    "mg/m³",
    "mg/m³",
    "kg/h",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@unittest.skipUnless(BATCH_PATH.is_file(), f"real batch not found: {BATCH_PATH}")
class RealBatchValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.batch = Project1Batch.load(BATCH_PATH)
        cls.result = validate_batch(cls.batch)

    def test_reads_real_indicators_values_units_and_raw_expressions(self) -> None:
        records = self.batch.environmental_records
        self.assertEqual(self.batch.batch_id, "20261101T053459830362Z_0e022780")
        self.assertEqual(len(self.batch.documents), 2)
        self.assertEqual(len(records), 9)
        self.assertEqual([record.indicator for record in records], EXPECTED_INDICATORS)
        self.assertEqual([record.value for record in records], EXPECTED_VALUES)
        self.assertEqual([record.unit for record in records], EXPECTED_UNITS)
        self.assertEqual(records[0].raw_expression, "COD\t85\tmg/L\t模拟检测")
        self.assertEqual(records[3].raw_expression, "总氮\t18.2\tmg/L\t模拟检测")
        self.assertEqual(
            records[5].raw_expression, "颗粒物\t8.6\tmg/m\t模拟检测"
        )
        self.assertEqual(
            records[8].raw_expression, "排放速率\t0.035\tkg/h\t模拟数据"
        )

    def test_distinguishes_indicator_anchor_from_value_cell(self) -> None:
        self.assertEqual(len(self.result.records), 9)
        for validation in self.result.records:
            with self.subTest(indicator=validation.indicator):
                self.assertTrue(validation.value_cell.found)
                self.assertEqual(validation.anchor_location.column_index, 0)
                self.assertEqual(validation.value_cell.column_index, 1)
                self.assertEqual(
                    validation.anchor_location.row_index,
                    validation.value_cell.row_index,
                )

        cod = self.result.records[0]
        self.assertEqual(cod.value_cell.text, "85")
        self.assertEqual(cod.value_cell.header_text, "监测结果")

        particulate = self.result.records[5]
        self.assertEqual(particulate.value_cell.text, "8.6")
        self.assertEqual(particulate.file_type, "pdf")

    def test_no_false_calculation_errors_for_plain_values(self) -> None:
        self.assertEqual(self.result.issues, [])
        self.assertEqual(self.result.summary()["issue_count"], 0)
        self.assertEqual(self.result.summary()["error_count"], 0)
        for validation in self.result.records:
            with self.subTest(indicator=validation.indicator):
                self.assertEqual(validation.validation_status, "unverified")
                self.assertIsNotNone(validation.calculation)
                self.assertIsNone(validation.calculation.computed_value)
                self.assertEqual(validation.issues, [])

    def test_real_batch_has_no_explicit_calculation_expression(self) -> None:
        self.assertEqual(self.result.summary()["expression_count"], 0)
        self.assertEqual(self.result.summary()["no_calculation_expression_count"], 9)
        for validation in self.result.records:
            self.assertEqual(validation.expressions, [])
            self.assertIn("no_calculation_expression", validation.review_reasons)

    def test_detection_limit_records_remain_unverified(self) -> None:
        total_phosphorus = self.result.records[2]
        sulfur_dioxide = self.result.records[6]
        self.assertIsNone(total_phosphorus.parsed_value)
        self.assertEqual(total_phosphorus.detection_limit, "<0.01")
        self.assertEqual(total_phosphorus.value_cell.text, "<0.01")
        self.assertIn(
            "detection_limit_no_numeric_value",
            total_phosphorus.review_reasons,
        )
        self.assertIsNone(sulfur_dioxide.parsed_value)
        self.assertEqual(sulfur_dioxide.detection_limit, "ND")
        self.assertEqual(sulfur_dioxide.value_cell.text, "ND")
        self.assertIn(
            "detection_limit_no_numeric_value",
            sulfur_dioxide.review_reasons,
        )

    def test_real_files_are_not_modified(self) -> None:
        files = [BATCH_PATH]
        for document in self.batch.documents:
            source = Path(document.source_file)
            if source.is_file():
                files.append(source)
        before = {str(path): _sha256(path) for path in files}

        Project1Batch.load(BATCH_PATH)
        validate_batch(Project1Batch.load(BATCH_PATH))

        after = {str(path): _sha256(path) for path in files}
        self.assertEqual(before, after)

    def test_report_records_actual_input_and_status(self) -> None:
        payload = self.result.to_dict()
        self.assertEqual(payload["batch_id"], "20261101T053459830362Z_0e022780")
        self.assertEqual(len(payload["records"]), 9)
        first = payload["records"][0]
        self.assertEqual(first["indicator"], "COD")
        self.assertEqual(first["input"]["value"], 85)
        self.assertEqual(first["input"]["unit"], "mg/L")
        self.assertEqual(first["value_cell"]["column_index"], 1)
        self.assertEqual(first["validation_status"], "unverified")
        self.assertEqual(first["issues"], [])


if __name__ == "__main__":
    unittest.main()
