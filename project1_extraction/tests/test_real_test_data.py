from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from doc_extractor.core.environmental_models import (
    ENV_MANAGEMENT,
    ENV_MONITORING,
    ENV_STATISTICS,
    FLAG_DETECTION_LIMIT,
    FLAG_MISSING_VALUE,
)
from doc_extractor.core.exporters import export_excel, export_json
from doc_extractor.core.models import Location
from evaluation_support import (
    TEST_DATA_DIR,
    Evaluation,
    canonical_unit,
    list_test_data_files,
    normalize_name,
    run_evaluation,
)


@pytest.fixture(scope="module")
def evaluation() -> Evaluation:
    return run_evaluation()


def _document(evaluation: Evaluation, filename: str):
    return next(
        document
        for document in evaluation.batch.documents
        if Path(document.source_file).name == filename
    )


def _records_for(evaluation: Evaluation, filename: str):
    return [
        record
        for record in evaluation.batch.environmental.records
        if Path(record.source_file).name == filename
    ]


def _find(records, indicator: str):
    matches = [record for record in records if record.indicator == indicator]
    assert matches, f"未找到指标 {indicator}"
    return matches[0]


def test_test_data_files_and_standard_workbook_exist(evaluation: Evaluation) -> None:
    files = list_test_data_files()
    names = {path.name for path in files}
    assert names == {
        "01_企业废水监测报告.docx",
        "02_企业废气监测报告.pdf",
        "03_企业环保管理台账.docx",
        "04_企业年度环境统计报告.pdf",
        "05_企业综合环境数据报告.docx",
        "06_环境数据提取标准答案.xlsx",
    }
    assert sum(path.suffix == ".docx" for path in files) == 3
    assert sum(path.suffix == ".pdf" for path in files) == 2
    assert evaluation.standard_file.name == "06_环境数据提取标准答案.xlsx"
    assert evaluation.standard_sheet == "标准答案"
    assert len(evaluation.standard_rows) == 21
    assert evaluation.standard_headers == [
        "来源文件",
        "企业名称",
        "数据类别",
        "监测点位/范围",
        "指标",
        "原始值",
        "单位",
        "预期位置提示",
        "说明",
    ]


def test_word_text_heading_table_enterprise_and_sources(evaluation: Evaluation) -> None:
    for filename in (
        "01_企业废水监测报告.docx",
        "03_企业环保管理台账.docx",
        "05_企业综合环境数据报告.docx",
    ):
        document = _document(evaluation, filename)
        assert document.error is None

        content_types = {record.content_type for record in document.records}
        assert "heading" in content_types
        assert "paragraph" in content_types
        assert "table" in content_types

        heading = next(
            record for record in document.records if record.content_type == "heading"
        )
        assert "报告" in heading.text or "台账" in heading.text
        assert heading.location.paragraph_index == 0

        table = next(
            record for record in document.records if record.content_type == "table"
        )
        assert table.location.table_index == 0
        assert table.metadata["rows"]
        assert table.location.row_index is None

        enterprise = evaluation.batch.environmental.enterprise_for_document(
            document.document_id
        )
        assert enterprise is not None
        assert normalize_name(enterprise.enterprise_name) == normalize_name(
            "青禾环保材料有限公司（虚构）"
        )


def test_word_environmental_values_units_dates_and_cell_locations(
    evaluation: Evaluation,
) -> None:
    records = _records_for(evaluation, "01_企业废水监测报告.docx")
    assert {record.category for record in records} == {ENV_MONITORING}

    cod = _find(records, "COD")
    assert cod.value == 85
    assert cod.unit == "mg/L"
    assert cod.time == "2026-10-20"
    assert cod.point == "DW001 废水总排口"
    assert cod.source_location["table_index"] == 0
    assert cod.source_location["row_index"] == 1
    assert cod.source_location["column_index"] == 0

    ammonia = _find(records, "氨氮")
    assert ammonia.value == 12.5
    assert ammonia.unit == "mg/L"

    ph = _find(records, "pH")
    assert ph.value == 7.3
    assert ph.unit == "无量纲"

    management = _records_for(evaluation, "03_企业环保管理台账.docx")
    runtime = _find(management, "设施运行时间")
    assert runtime.value == 720
    assert runtime.unit == "h"
    assert runtime.point == "污水处理设施A"
    assert runtime.time == "2026年"
    assert runtime.source_location["row_index"] == 1

    maintenance = _find(management, "维护次数")
    assert maintenance.value == 2
    assert maintenance.unit == "次"

    sludge = _find(management, "污泥转移量")
    assert sludge.value == 1.25
    assert sludge.unit == "t"


def test_word_mixed_categories(evaluation: Evaluation) -> None:
    records = _records_for(evaluation, "05_企业综合环境数据报告.docx")
    by_indicator = {record.indicator: record for record in records}

    assert by_indicator["COD"].category == ENV_MONITORING
    assert by_indicator["颗粒物"].category == ENV_MONITORING
    assert by_indicator["设施运行时间"].category == ENV_MANAGEMENT
    assert by_indicator["年度用水量"].category == ENV_STATISTICS
    assert by_indicator["年度用水量"].value == 12500
    assert by_indicator["年度用水量"].unit == "m³"


def test_pdf_text_tables_pages_and_coordinates(evaluation: Evaluation) -> None:
    for filename in ("02_企业废气监测报告.pdf", "04_企业年度环境统计报告.pdf"):
        document = _document(evaluation, filename)
        assert document.error is None
        assert document.file_type == "pdf"

        text = document.raw_text()
        assert "青禾环保材料有限公司" in text

        page_records = [
            record for record in document.records if record.content_type == "ocr_page"
        ]
        assert page_records[0].location.page_number == 1
        assert page_records[0].location.bbox is not None

        table = next(
            record for record in document.records if record.content_type == "table"
        )
        assert table.location.page_number == 1
        assert table.location.bbox is not None
        assert len(table.location.bbox) == 4
        assert table.metadata["rows"]

        text_blocks = [
            record for record in document.records if record.content_type == "ocr_text"
        ]
        assert text_blocks
        assert all(block.location.page_number == 1 for block in text_blocks)
        assert all(block.location.bbox for block in text_blocks)
        assert all(block.metadata["source"] == "paddle_structure" for block in text_blocks)


def test_pdf_environmental_indicators_values_and_units(evaluation: Evaluation) -> None:
    waste_gas = _records_for(evaluation, "02_企业废气监测报告.pdf")
    assert {record.category for record in waste_gas} == {ENV_MONITORING}

    particulate = _find(waste_gas, "颗粒物")
    assert particulate.value == 8.6
    assert particulate.unit == "mg/m³"
    assert particulate.point == "DA001 废气排放口"
    assert particulate.source_location["page_number"] == 1

    sulfur = _find(waste_gas, "二氧化硫")
    assert sulfur.value is None
    assert sulfur.detection_limit == "ND"
    assert sulfur.unit == "mg/m³"

    nitrogen = _find(waste_gas, "氮氧化物")
    assert nitrogen.value == 35.2
    assert nitrogen.unit == "mg/m³"

    rate = _find(waste_gas, "排放速率")
    assert rate.value == 0.035
    assert rate.unit == "kg/h"

    statistics = _records_for(evaluation, "04_企业年度环境统计报告.pdf")
    assert {record.category for record in statistics} == {ENV_STATISTICS}

    water = _find(statistics, "年度用水量")
    assert water.value == 12500
    assert water.unit == "m³"
    assert water.source_location["page_number"] == 1
    assert water.source_location["bbox"] is not None

    electricity = _find(statistics, "年度用电量")
    assert electricity.value == 286000
    assert electricity.unit == "kWh"

    gas = _find(statistics, "天然气用量")
    assert gas.value == 7800
    assert gas.unit == "m³"

    pollutant = _find(statistics, "污染物产生量")
    assert pollutant.value == 4.8
    assert pollutant.unit == "t/a"


def test_special_values_are_not_converted_to_zero(evaluation: Evaluation) -> None:
    tp = _find(_records_for(evaluation, "01_企业废水监测报告.docx"), "总磷")
    assert tp.value is None
    assert tp.detection_limit == "<0.01"
    assert FLAG_DETECTION_LIMIT in tp.flags
    assert tp.value != 0

    sulfur = _find(_records_for(evaluation, "02_企业废气监测报告.pdf"), "二氧化硫")
    assert sulfur.value is None
    assert sulfur.detection_limit == "ND"
    assert sulfur.value != 0

    particulate = _find(
        _records_for(evaluation, "05_企业综合环境数据报告.docx"), "颗粒物"
    )
    assert particulate.value is None
    assert particulate.detection_limit == "ND"
    assert particulate.value != 0

    downtime = _find(_records_for(evaluation, "03_企业环保管理台账.docx"), "停机时长")
    assert downtime.value is None
    assert downtime.unit == "h"
    assert "—" in downtime.raw_expression
    assert FLAG_MISSING_VALUE in downtime.flags
    assert downtime.value != 0

    units = {
        record.unit
        for record in evaluation.batch.environmental.records
        if record.unit is not None
    }
    assert {"mg/L", "mg/m³", "无量纲", "h", "次", "t", "m³", "kWh", "t/a", "kg/h"}.issubset(
        units
    )

    times = {
        record.time
        for record in evaluation.batch.environmental.records
        if record.time is not None
    }
    assert {"2026-10-20", "2026-10-21", "2026年"}.issubset(times)


def test_all_source_locations_and_enterprise_grouping(evaluation: Evaluation) -> None:
    assert len(evaluation.batch.environmental.enterprises) == 1
    enterprise = evaluation.batch.environmental.enterprises[0]
    assert enterprise.document_count == 5
    assert normalize_name(enterprise.enterprise_name) == normalize_name(
        "青禾环保材料有限公司（虚构）"
    )

    for record in evaluation.batch.environmental.records:
        assert record.source_file
        assert record.document_id
        assert record.raw_expression
        assert record.source_text
        assert record.source_content_type in {
            "paragraph",
            "table",
            "text_block",
            "ocr_text",
            "ocr_page",
            "page_text",
            "heading",
        }
        location = Location.from_dict(record.source_location)
        assert (
            location.paragraph_index is not None
            or location.table_index is not None
            or location.page_number is not None
        )


def test_standard_answer_comparison_is_complete(evaluation: Evaluation) -> None:
    metrics = evaluation.metrics
    assert metrics["standard_total"] == 21
    assert metrics["actual_total"] == 21
    assert metrics["matched"] == 21
    assert metrics["ambiguous"] == 0
    assert metrics["missed"] == 0
    assert metrics["conflicts"] == 0
    assert metrics["extra"] == 0
    assert metrics["recall"] == pytest.approx(1.0)
    assert metrics["precision"] == pytest.approx(1.0)
    assert metrics["location_hint_mismatches"] == 0
    assert metrics["non_literal_point_rows"] == 8

    matched_ids = [
        comparison.actual.record_id
        for comparison in evaluation.matched_comparisons
        if comparison.actual is not None
    ]
    assert len(matched_ids) == 21
    assert len(set(matched_ids)) == 21


def test_json_export_for_real_test_data(
    evaluation: Evaluation, tmp_path: Path
) -> None:
    output = export_json(
        evaluation.batch.documents,
        tmp_path / "real_test_data.json",
        evaluation.batch.environmental,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["document_count"] == 5
    env = payload["environmental"]
    assert env["record_count"] == 21
    assert env["enterprise_count"] == 1
    assert len(env["enterprises"][0]["source_files"]) == 5

    special = next(
        record
        for record in env["records"]
        if record["indicator"] == "总磷" and record["source_file"].endswith(".docx")
    )
    assert special["value"] is None
    assert special["detection_limit"] == "<0.01"
    assert special["source_location"]["table_index"] == 0

    pdf_record = next(
        record
        for record in env["records"]
        if record["file_type"] == "pdf" and record["indicator"] == "颗粒物"
    )
    assert pdf_record["source_location"]["page_number"] == 1
    assert pdf_record["source_location"]["bbox"]


def test_excel_export_for_real_test_data(
    evaluation: Evaluation, tmp_path: Path
) -> None:
    output = export_excel(
        evaluation.batch.documents,
        tmp_path / "real_test_data.xlsx",
        evaluation.batch.environmental,
    )
    workbook = load_workbook(output, read_only=True)

    assert "环境数据" in workbook.sheetnames
    assert "企业汇总" in workbook.sheetnames
    env_rows = list(workbook["环境数据"].iter_rows(values_only=True))
    enterprise_rows = list(workbook["企业汇总"].iter_rows(values_only=True))

    assert len(env_rows) == 22
    assert env_rows[0][8] == "指标"
    assert any(row[8] == "COD" and row[9] == 85 for row in env_rows[1:])
    assert any(row[8] == "停机时长" and row[9] is None for row in env_rows[1:])
    assert any(row[8] == "颗粒物" and row[10] == "mg/m³" for row in env_rows[1:])
    assert any(row[1] == "青禾环保材料有限公司(虚构)" for row in enterprise_rows[1:])
    workbook.close()
