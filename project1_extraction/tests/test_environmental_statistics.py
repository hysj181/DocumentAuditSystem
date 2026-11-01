from __future__ import annotations

from pathlib import Path

from docx import Document

from doc_extractor.core.environmental_models import (
    ENV_STATISTICS,
    FLAG_DETECTION_LIMIT,
    FLAG_MISSING_UNIT,
)
from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.extractor import extract_document


def _environmental_result(path: Path):
    document = extract_document(path)
    assert document.error is None
    return extract_environmental_data([document])


def _find(records, indicator: str):
    matches = [record for record in records if record.indicator == indicator]
    assert matches, f"未找到指标 {indicator}"
    return matches[0]


def test_statistics_units_values_and_source_locations(
    environmental_word_file: Path,
) -> None:
    result = _environmental_result(environmental_word_file)
    statistics = result.records_by_category(ENV_STATISTICS)
    assert statistics

    water = _find(statistics, "新鲜用水量")
    assert water.value == 1200
    assert water.unit == "m³"
    assert water.time == "2024年"
    assert water.subcategory == "water"
    assert water.source_location["table_index"] == 0
    assert water.source_location["row_index"] == 1
    assert water.source_location["column_index"] == 0
    assert water.source_content_type == "table"
    assert "新鲜用水量" in water.raw_expression

    electricity = _find(statistics, "用电量")
    assert electricity.value == 8500
    assert electricity.unit == "kWh"
    assert electricity.subcategory == "energy"

    gas = _find(statistics, "天然气用量")
    assert gas.value == 1.2
    assert gas.unit == "万m³"

    cod_emission = _find(statistics, "COD排放量")
    assert cod_emission.value == 0.85
    assert cod_emission.unit == "吨"
    assert cod_emission.subcategory == "pollutant"

    ammonia_emission = _find(statistics, "氨氮排放量")
    assert ammonia_emission.value == 0.12
    assert ammonia_emission.unit == "t/a"

    wastewater = _find(statistics, "废水排放量")
    assert wastewater.value is None
    assert wastewater.unit == "t/a"
    assert wastewater.detection_limit == "未检出"
    assert FLAG_DETECTION_LIMIT in wastewater.flags


def test_statistics_generic_pollutant_emission(tmp_path: Path) -> None:
    path = tmp_path / "statistics_emission.docx"
    document = Document()
    document.add_heading("测试企业有限公司 环境统计", level=1)
    document.add_paragraph("企业名称：测试企业有限公司")
    document.add_paragraph("统一社会信用代码：91310115MA1K4A2B3C")
    document.add_paragraph("统计期间：2025年度")
    document.add_paragraph("污染物排放量 2.5 t/a")
    document.save(path)

    result = _environmental_result(path)
    record = _find(result.records_by_category(ENV_STATISTICS), "污染物排放量")
    assert record.value == 2.5
    assert record.unit == "t/a"
    assert record.category == ENV_STATISTICS


def test_statistics_missing_unit_is_flagged(tmp_path: Path) -> None:
    path = tmp_path / "statistics_missing.docx"
    document = Document()
    document.add_heading("测试企业有限公司 环境统计", level=1)
    document.add_paragraph("企业名称：测试企业有限公司")
    document.add_paragraph("统一社会信用代码：91310115MA1K4A2B3C")
    document.add_paragraph("统计期间：2024年度")
    document.add_paragraph("用水量 500")
    document.save(path)

    result = _environmental_result(path)
    water = _find(result.records_by_category(ENV_STATISTICS), "用水量")
    assert water.value == 500
    assert water.unit is None
    assert FLAG_MISSING_UNIT in water.flags
    assert water.time == "2024年"
