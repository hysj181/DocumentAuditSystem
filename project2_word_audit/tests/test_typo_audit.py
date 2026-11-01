from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from word_audit.project1_batch import Project1Batch
from word_audit.typo_audit import scan_batch_typos
from word_audit.typo_rules import DEFAULT_TYPO_ENTRIES, TypoEntry


def _write_word_batch(
    root: Path,
    *,
    paragraphs: list[str],
    table_rows: list[list[str]] | None = None,
    synthetic: bool = True,
) -> Path:
    source_file = str(root / "synthetic_typo.docx")
    document_id = "synthetic-typo-doc"
    records: list[dict] = []
    for paragraph_index, text in enumerate(paragraphs):
        records.append(
            {
                "document_id": document_id,
                "source_file": source_file,
                "file_type": "word",
                "content_type": "paragraph",
                "text": text,
                "location": {
                    "paragraph_index": paragraph_index,
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
    if table_rows is not None:
        cells = [
            {
                "row_index": row_index,
                "column_index": column_index,
                "text": text,
                "entities": [],
            }
            for row_index, row in enumerate(table_rows)
            for column_index, text in enumerate(row)
        ]
        records.append(
            {
                "document_id": document_id,
                "source_file": source_file,
                "file_type": "word",
                "content_type": "table",
                "text": "\n".join("\t".join(row) for row in table_rows),
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
                    "row_count": len(table_rows),
                    "column_count": max((len(row) for row in table_rows), default=0),
                    "rows": table_rows,
                    "cells": cells,
                },
            }
        )
    payload = {
        "schema_version": "1.0",
        "batch_id": "synthetic-typo-batch",
        "extracted_at": "2026-01-01T00:00:00+00:00",
        "documents": [
            {
                "document_id": document_id,
                "source_name": "synthetic_typo.docx",
                "source_file": source_file,
                "file_type": "word",
                "record_count": len(records),
                "table_count": 1 if table_rows is not None else 0,
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
    if synthetic:
        payload["metadata"] = {"synthetic_data": True}
    path = root / "synthetic_typo_batch.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


class TypoAuditCoreTests(unittest.TestCase):
    def scan(
        self,
        *,
        paragraphs: list[str],
        table_rows: list[list[str]] | None = None,
        entries=DEFAULT_TYPO_ENTRIES,
        synthetic: bool = True,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_word_batch(
                root,
                paragraphs=paragraphs,
                table_rows=table_rows,
                synthetic=synthetic,
            )
            batch = Project1Batch.load(path)
            return scan_batch_typos(batch, entries=entries)

    def test_common_typo_detected_with_required_metadata(self) -> None:
        result = self.scan(paragraphs=["本次数剧由合成测试生成。"])
        self.assertEqual(len(result.issues), 1)
        issue = result.issues[0]
        self.assertEqual(issue.issue_type, "typo")
        self.assertEqual(issue.original_text, "数剧")
        self.assertEqual(issue.suggestion, "数据")
        self.assertEqual(issue.location.paragraph_index, 0)
        self.assertFalse(issue.needs_manual_review)
        self.assertIn("“数剧”疑似错别字", issue.description)
        metadata = issue.metadata
        self.assertEqual(metadata["audit_rule"], "typo")
        self.assertEqual(metadata["issue_type_label"], "错别字")
        self.assertEqual(metadata["typo_confidence"], "high")
        self.assertEqual(metadata["error_text"], "数剧")
        self.assertEqual(metadata["suggested_text"], "数据")
        self.assertIn("数剧", metadata["context"])
        self.assertTrue(metadata["typo_reason"])
        self.assertTrue(metadata["typo_rule_id"])
        self.assertEqual(metadata["occurrence_count"], 1)
        self.assertEqual(metadata["location_granularity"], "word_paragraph")
        self.assertTrue(metadata["auto_annotate"])
        self.assertTrue(metadata["synthetic"])
        self.assertEqual(result.verified_count, 1)
        self.assertEqual(result.low_confidence_count, 0)

    def test_correct_words_not_flagged(self) -> None:
        result = self.scan(
            paragraphs=["本次数据由企业监测报告记录，检测结果正确。"]
        )
        self.assertEqual(result.issues, [])

    def test_professional_terms_not_flagged(self) -> None:
        result = self.scan(
            paragraphs=[
                "化学需氧量、氨氮、总磷、总氮、悬浮物、二氧化硫、"
                "氮氧化物、颗粒物均按监测方法检测。"
            ]
        )
        self.assertEqual(result.issues, [])

    def test_enterprise_name_and_organization_not_flagged(self) -> None:
        result = self.scan(
            paragraphs=[
                "青禾环保材料有限公司（虚构）",
                "数剧环保有限公司",
            ]
        )
        self.assertEqual(result.issues, [])

    def test_standard_numbers_not_flagged(self) -> None:
        result = self.scan(
            paragraphs=[
                "执行标准 GB 3838-2002、HJ 828-2017、DB44/T 1234-2020。"
            ]
        )
        self.assertEqual(result.issues, [])

    def test_repeated_characters_detected(self) -> None:
        result = self.scan(
            paragraphs=["企业业。", "数据据。", "企企业。", "数数据。"]
        )
        self.assertEqual(len(result.issues), 4)
        corrections = {issue.suggestion for issue in result.issues}
        self.assertEqual(corrections, {"企业", "数据"})
        self.assertTrue(
            all(issue.metadata["typo_confidence"] == "high" for issue in result.issues)
        )

    def test_legitimate_reduplication_not_flagged(self) -> None:
        result = self.scan(paragraphs=["年年岁岁，常常检查，一一记录。"])
        self.assertEqual(result.issues, [])

    def test_low_confidence_entry_is_not_auto_annotated(self) -> None:
        result = self.scan(paragraphs=["临测数据。"])
        self.assertEqual(len(result.issues), 1)
        issue = result.issues[0]
        self.assertEqual(issue.original_text, "临测")
        self.assertEqual(issue.suggestion, "监测")
        self.assertTrue(issue.needs_manual_review)
        self.assertFalse(issue.metadata["auto_annotate"])
        self.assertEqual(issue.metadata["typo_confidence"], "low")
        self.assertEqual(result.verified_count, 0)
        self.assertEqual(result.low_confidence_count, 1)

    def test_same_unit_occurrences_are_grouped(self) -> None:
        result = self.scan(paragraphs=["数剧数剧。"])
        self.assertEqual(len(result.issues), 1)
        issue = result.issues[0]
        self.assertEqual(issue.metadata["occurrence_count"], 2)
        self.assertEqual(len(issue.metadata["contexts"]), 2)

    def test_different_units_are_not_merged(self) -> None:
        result = self.scan(paragraphs=["数剧。", "数剧。"])
        self.assertEqual(len(result.issues), 2)
        self.assertEqual(
            {issue.location.paragraph_index for issue in result.issues},
            {0, 1},
        )
        self.assertTrue(
            all(issue.metadata["occurrence_count"] == 1 for issue in result.issues)
        )

    def test_word_table_cell_location(self) -> None:
        result = self.scan(
            paragraphs=[],
            table_rows=[["数剧", "正确"]],
        )
        self.assertEqual(len(result.issues), 1)
        issue = result.issues[0]
        self.assertEqual(issue.location.table_index, 0)
        self.assertEqual(issue.location.row_index, 0)
        self.assertEqual(issue.location.column_index, 0)
        self.assertEqual(issue.metadata["location_granularity"], "word_table_cell")

    def test_custom_low_confidence_entry(self) -> None:
        entry = TypoEntry(
            wrong="检则",
            correct="检测",
            reason="测试低置信度",
            confidence="low",
            rule_id="TEST_LOW",
        )
        result = self.scan(paragraphs=["检则数据。"], entries=(entry,))
        self.assertEqual(len(result.issues), 1)
        issue = result.issues[0]
        self.assertTrue(issue.needs_manual_review)
        self.assertFalse(issue.metadata["auto_annotate"])

    def test_real_synthetic_flag_false(self) -> None:
        result = self.scan(paragraphs=["数剧。"], synthetic=False)
        self.assertNotIn("synthetic", result.issues[0].metadata)


class TypoRuleTests(unittest.TestCase):
    def test_rule_ids_are_unique(self) -> None:
        rule_ids = [entry.rule_id for entry in DEFAULT_TYPO_ENTRIES]
        self.assertEqual(len(rule_ids), len(set(rule_ids)))

    def test_entries_have_valid_confidence(self) -> None:
        self.assertTrue(
            all(entry.confidence in {"high", "low"} for entry in DEFAULT_TYPO_ENTRIES)
        )


if __name__ == "__main__":
    unittest.main()
