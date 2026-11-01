from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from word_audit.math_audit import (
    _is_arithmetic,
    detect_calculation_expressions,
    evaluate_expression,
    validate_batch,
)
from word_audit.project1_batch import Project1Batch


class ExpressionDetectionTests(unittest.TestCase):
    def test_plain_monitoring_values_are_not_expressions(self) -> None:
        texts = [
            "COD\t85\tmg/L\t模拟检测",
            "氨氮\t12.5\tmg/L\t模拟检测",
            "总磷\t<0.01\tmg/L\t低于报告限",
            "pH\t7.3\t无量纲\t模拟检测",
            "颗粒物\t8.6\tmg/m\t模拟检测",
            "排放速率\t0.035\tkg/h\t模拟数据",
            "mg/L",
            "mg/m3",
            "kg/h",
            "2026-10-20",
            "采样日期：2026年10月20日",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(detect_calculation_expressions(text), [])

    def test_detects_explicit_equals_formula(self) -> None:
        candidates = detect_calculation_expressions(
            "去除率 = (100-85)/100*100"
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].rhs, "(100-85)/100*100")
        value, error = evaluate_expression(candidates[0].rhs or "")
        self.assertIsNone(error)
        self.assertAlmostEqual(value or 0.0, 15.0)

    def test_detects_keyword_formula_without_equals(self) -> None:
        candidates = detect_calculation_expressions("去除率为(100-85)/100*100")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].rhs, "(100-85)/100*100")

    def test_percentage_formula_is_not_evaluated(self) -> None:
        value, error = evaluate_expression("(100-85)/100*100%")
        self.assertIsNone(value)
        self.assertEqual(error, "percentage_not_supported")

    def test_unit_only_text_is_not_arithmetic(self) -> None:
        self.assertFalse(_is_arithmetic("mg/L"))
        self.assertFalse(_is_arithmetic("kg/h"))
        self.assertFalse(_is_arithmetic("2026-10-20"))
        self.assertTrue(_is_arithmetic("100-85"))

    def test_non_numeric_tokens_are_not_evaluated(self) -> None:
        value, error = evaluate_expression("(100-85) mg/L")
        self.assertIsNone(value)
        self.assertEqual(error, "expression_contains_non_numeric_tokens")


def _environmental_record(
    *,
    record_id: str,
    indicator: str,
    value: object,
    raw_expression: str,
) -> dict:
    return {
        "record_id": record_id,
        "category": "environmental_monitoring",
        "subcategory": "wastewater",
        "document_id": "doc-1",
        "source_file": "D:\\sample\\report.docx",
        "file_type": "word",
        "indicator": indicator,
        "value": value,
        "unit": "%",
        "time": None,
        "point": None,
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
        "source_text": raw_expression,
        "raw_expression": raw_expression,
        "flags": [],
        "status": "complete",
        "confidence": 0.9,
        "metadata": {},
    }


def _write_synthetic_batch(path: Path, records: list[dict]) -> None:
    payload = {
        "schema_version": "1.0",
        "batch_id": "synthetic-batch",
        "extracted_at": "2026-11-01T00:00:00+00:00",
        "documents": [
            {
                "document_id": "doc-1",
                "source_name": "report.docx",
                "source_file": "D:\\sample\\report.docx",
                "file_type": "word",
                "records": [
                    {
                        "document_id": "doc-1",
                        "source_file": "D:\\sample\\report.docx",
                        "file_type": "word",
                        "content_type": "table",
                        "text": "项目\t监测结果\t单位\t备注",
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
                            "rows": [
                                ["项目", "监测结果", "单位", "备注"],
                                ["去除率", "15", "%", "计算值"],
                            ],
                            "cells": [],
                        },
                    }
                ],
                "tables": [],
                "warnings": [],
                "error": None,
                "metadata": {},
            }
        ],
        "tables": [],
        "environmental": {"records": records, "warnings": []},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class EndToEndMathValidationTests(unittest.TestCase):
    def test_explicit_matching_formula_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            _write_synthetic_batch(
                path,
                [
                    _environmental_record(
                        record_id="record-ok",
                        indicator="去除率",
                        value=15,
                        raw_expression="去除率 = (100-85)/100*100",
                    )
                ],
            )
            result = validate_batch(Project1Batch.load(path))
        self.assertEqual(result.summary()["issue_count"], 0)
        record = result.records[0]
        self.assertEqual(record.validation_status, "verified")
        self.assertEqual(record.calculation.computed_value, 15.0)

    def test_explicit_mismatching_formula_creates_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            _write_synthetic_batch(
                path,
                [
                    _environmental_record(
                        record_id="record-bad",
                        indicator="去除率",
                        value=12.5,
                        raw_expression="去除率 = (100-85)/100*100",
                    )
                ],
            )
            result = validate_batch(Project1Batch.load(path))
        self.assertEqual(result.summary()["issue_count"], 1)
        record = result.records[0]
        self.assertEqual(record.validation_status, "error")
        self.assertEqual(record.calculation.computed_value, 15.0)
        self.assertEqual(record.issues[0].computed_value, 15.0)

    def test_plain_value_without_formula_stays_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            _write_synthetic_batch(
                path,
                [
                    _environmental_record(
                        record_id="record-plain",
                        indicator="去除率",
                        value=15,
                        raw_expression="去除率\t15\t%\t监测结果",
                    )
                ],
            )
            result = validate_batch(Project1Batch.load(path))
        self.assertEqual(result.summary()["issue_count"], 0)
        record = result.records[0]
        self.assertEqual(record.validation_status, "unverified")
        self.assertIsNone(record.calculation.computed_value)


if __name__ == "__main__":
    unittest.main()
