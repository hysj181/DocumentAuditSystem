from __future__ import annotations

from pathlib import Path

from docx import Document

from doc_extractor.core.environmental_models import (
    ENV_MONITORING,
    FLAG_AMBIGUOUS_VALUE,
    FLAG_DETECTION_LIMIT,
    FLAG_MISSING_POINT,
    FLAG_MISSING_UNIT,
)
from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.extractor import extract_document


def _environmental_result(path: Path):
    document = extract_document(path)
    assert document.error is None
    return extract_environmental_data([document])


def _find(records, indicator: str, contains: str):
    matches = [
        record
        for record in records
        if record.indicator == indicator and contains in record.source_text
    ]
    assert matches, f"未找到指标 {indicator} / {contains}"
    return matches[0]


def test_monitoring_values_units_time_points_and_locations(
    environmental_word_file: Path,
) -> None:
    result = _environmental_result(environmental_word_file)
    monitoring = result.records_by_category(ENV_MONITORING)
    assert monitoring

    cod = _find(monitoring, "COD", "废水总排口")
    assert cod.value == 45.2
    assert cod.unit == "mg/L"
    assert cod.time == "2024-05-01"
    assert cod.point == "废水总排口"
    assert cod.subcategory == "wastewater"
    assert cod.flags == []
    assert cod.source_location["paragraph_index"] is not None

    ammonia = _find(monitoring, "氨氮", "废水总排口")
    assert ammonia.value == 1.23
    assert ammonia.unit == "mg/L"
    assert ammonia.point == "废水总排口"

    ph = _find(monitoring, "pH", "废水总排口")
    assert ph.value == 7.2
    assert ph.unit is None
    assert "missing_unit" not in ph.flags

    sulfur = _find(monitoring, "二氧化硫", "二氧化硫 12.5")
    assert sulfur.value == 12.5
    assert sulfur.unit == "mg/m³"
    assert sulfur.subcategory == "waste_gas"
    assert FLAG_MISSING_POINT in sulfur.flags

    noise = _find(monitoring, "噪声", "厂界噪声")
    assert noise.value == 55.6
    assert noise.unit == "dB(A)"
    assert noise.point == "厂界"
    assert noise.subcategory == "noise"


def test_monitoring_detection_limits_missing_units_and_ambiguity(
    environmental_word_file: Path,
) -> None:
    result = _environmental_result(environmental_word_file)
    monitoring = result.records_by_category(ENV_MONITORING)

    total_phosphorus = _find(monitoring, "总磷", "<0.01")
    assert total_phosphorus.value is None
    assert total_phosphorus.unit == "mg/L"
    assert total_phosphorus.detection_limit == "<0.01"
    assert FLAG_DETECTION_LIMIT in total_phosphorus.flags

    total_nitrogen = _find(monitoring, "总氮", "未检出")
    assert total_nitrogen.value is None
    assert total_nitrogen.detection_limit == "未检出"
    assert FLAG_DETECTION_LIMIT in total_nitrogen.flags

    missing_unit = _find(monitoring, "总磷", "补充监测")
    assert missing_unit.value == 0.5
    assert missing_unit.unit is None
    assert FLAG_MISSING_UNIT in missing_unit.flags

    ambiguous = _find(monitoring, "COD", "平行样")
    assert FLAG_AMBIGUOUS_VALUE in ambiguous.flags
    assert ambiguous.value == 45.2


def test_monitoring_missing_value_and_unrecognized_data(tmp_path: Path) -> None:
    path = tmp_path / "monitoring_missing.docx"
    document = Document()
    document.add_heading("测试企业有限公司 监测报告", level=1)
    document.add_paragraph("企业名称：测试企业有限公司")
    document.add_paragraph("统一社会信用代码：91310115MA1K4A2B3C")
    document.add_paragraph("监测日期：2024-05-01")
    document.add_paragraph("废水总排口：COD")
    document.add_paragraph("废水总排口：流量 12.5 m3/h")
    document.save(path)

    result = _environmental_result(path)
    monitoring = result.records_by_category(ENV_MONITORING)

    cod = _find(monitoring, "COD", "COD")
    assert cod.value is None
    assert "missing_value" in cod.flags

    unrecognized = [
        record
        for record in monitoring
        if record.indicator is None and "unrecognized" in record.flags
    ]
    assert len(unrecognized) == 1
    assert unrecognized[0].value == 12.5
    assert unrecognized[0].unit == "m³/h"
    assert unrecognized[0].point == "废水总排口"
    assert unrecognized[0].source_text


def test_monitoring_source_tracking(environmental_word_file: Path) -> None:
    result = _environmental_result(environmental_word_file)
    cod = _find(result.records_by_category(ENV_MONITORING), "COD", "废水总排口")

    assert cod.document_id
    assert cod.source_file.endswith("environmental.docx")
    assert cod.file_type == "word"
    assert cod.source_content_type == "paragraph"
    assert cod.source_location["row_index"] is None
    assert "COD 45.2" in cod.raw_expression
