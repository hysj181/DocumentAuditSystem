from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.exporters import export_excel, export_json
from doc_extractor.core.extractor import extract_document


def test_json_export_contains_unified_records(
    tmp_path: Path, word_file: Path, pdf_file: Path
) -> None:
    documents = [extract_document(word_file), extract_document(pdf_file)]
    output = export_json(documents, tmp_path / "result.json")

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["document_count"] == 2
    assert len(payload["documents"]) == 2
    assert payload["documents"][0]["document_id"] != payload["documents"][1]["document_id"]
    assert payload["documents"][0]["records"]
    assert "location" in payload["documents"][0]["records"][0]
    assert "metadata" in payload["documents"][0]["records"][0]


def test_excel_export_contains_summary_records_tables_and_entities(
    tmp_path: Path, word_file: Path, pdf_file: Path
) -> None:
    documents = [extract_document(word_file), extract_document(pdf_file)]
    output = export_excel(documents, tmp_path / "result.xlsx")

    workbook = load_workbook(output, read_only=True)
    assert workbook.sheetnames == ["文件汇总", "记录", "表格数据", "实体信息"]

    summary_rows = list(workbook["文件汇总"].iter_rows(values_only=True))
    records_rows = list(workbook["记录"].iter_rows(values_only=True))
    table_rows = list(workbook["表格数据"].iter_rows(values_only=True))
    entity_rows = list(workbook["实体信息"].iter_rows(values_only=True))

    assert summary_rows[0][0] == "文档ID"
    assert len(summary_rows) == 3
    assert records_rows[0][0] == "文档ID"
    assert len(records_rows) > 3
    assert table_rows[0][0] == "文档ID"
    assert any(row[6] == "服务费" for row in table_rows)
    assert entity_rows[0][0] == "文档ID"
    assert any(row[2] == "amount" for row in entity_rows)
    assert any(row[2] == "date" for row in entity_rows)
    workbook.close()


def test_exporters_create_parent_directory(tmp_path: Path, word_file: Path) -> None:
    documents = [extract_document(word_file)]
    output = export_json(documents, tmp_path / "nested" / "dir" / "result.json")

    assert output.exists()


def test_json_export_includes_environmental_data_and_sources(
    tmp_path: Path, environmental_word_file: Path, environmental_pdf_file: Path
) -> None:
    documents = [
        extract_document(environmental_word_file),
        extract_document(environmental_pdf_file),
    ]
    environmental = extract_environmental_data(documents)
    output = export_json(documents, tmp_path / "environmental.json", environmental)

    payload = json.loads(output.read_text(encoding="utf-8"))
    env_payload = payload["environmental"]
    assert env_payload["record_count"] == environmental.record_count
    assert env_payload["enterprise_count"] == 1
    assert env_payload["category_counts"]["环境监测"] > 0
    assert env_payload["enterprises"][0]["unified_social_credit_code"] == "91310115MA1K4A2B3C"

    cod = next(
        record
        for record in env_payload["records"]
        if record["indicator"] == "COD" and record["file_type"] == "pdf"
    )
    assert cod["source_location"]["page_number"] == 1
    assert cod["source_location"]["bbox"]
    assert cod["source_file"].endswith("environmental.pdf")
    assert cod["raw_expression"]
    assert cod["status"]


def test_excel_export_includes_environmental_and_enterprise_sheets(
    tmp_path: Path, environmental_word_file: Path
) -> None:
    documents = [extract_document(environmental_word_file)]
    environmental = extract_environmental_data(documents)
    output = export_excel(documents, tmp_path / "environmental.xlsx", environmental)

    workbook = load_workbook(output, read_only=True)
    assert "环境数据" in workbook.sheetnames
    assert "企业汇总" in workbook.sheetnames

    env_rows = list(workbook["环境数据"].iter_rows(values_only=True))
    enterprise_rows = list(workbook["企业汇总"].iter_rows(values_only=True))

    assert env_rows[0][0] == "记录ID"
    assert env_rows[0][16] == "来源位置"
    assert any(row[8] == "COD" and row[9] == 45.2 for row in env_rows[1:])
    assert any(row[8] == "新鲜用水量" for row in env_rows[1:])
    assert any(row[14] == "待人工核实" for row in env_rows[1:])
    assert enterprise_rows[0][0] == "企业ID"
    assert any(row[1] == "华清化工有限公司" for row in enterprise_rows[1:])
    workbook.close()


@pytest.mark.parametrize("exporter,suffix", [(export_json, ".json"), (export_excel, ".xlsx")])
def test_export_refuses_to_overwrite_source(
    tmp_path: Path, word_file: Path, exporter, suffix: str
) -> None:
    documents = [extract_document(word_file)]
    target = tmp_path / f"source{suffix}"
    target.write_text("keep me", encoding="utf-8")
    documents[0].source_file = str(target)

    with pytest.raises(ValueError, match="原始文件"):
        exporter(documents, target)
