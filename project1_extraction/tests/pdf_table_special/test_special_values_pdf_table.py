from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.pdf_parser import parse_pdf
from pdf_table_special.support import (
    SPECIAL_ROWS,
    SPECIAL_STANDARD_ANSWERS,
    make_special_values_pdf,
)


def _find_record(records, indicator, value, detection_limit):
    for record in records:
        if record.indicator != indicator:
            continue
        if record.value != value:
            continue
        if (record.detection_limit or "") != (detection_limit or ""):
            continue
        return record
    raise AssertionError(
        f"未找到记录 indicator={indicator} value={value} detection_limit={detection_limit}"
    )


def test_special_values_pdf_table_structure(tmp_path: Path) -> None:
    path = make_special_values_pdf(tmp_path / "special_values.pdf")
    result = parse_pdf(path)

    assert result.error is None
    assert result.metadata["table_count"] == 1
    assert len(result.tables) == 1

    table = result.tables[0]
    assert table.page_number == 1
    assert table.rows == len(SPECIAL_ROWS)
    assert table.columns == 5
    assert table.header_row_count == 1
    assert table.headers[0] == ["监测点位", "指标", "数值", "单位", "监测日期"]
    assert table.table_bbox is not None
    assert all(cell.bbox is not None for cell in table.cells if cell.text)
    assert table.grid()[1] == [
        "DW001 废水总排口",
        "COD",
        "45.2",
        "mg/L",
        "2024-07-01",
    ]
    assert table.grid()[5][2] == "ND"
    assert table.grid()[6][2] == "35.2"


def test_special_values_multiple_points_dates_and_mixed_units(
    tmp_path: Path,
) -> None:
    path = make_special_values_pdf(tmp_path / "special_values.pdf")
    result = parse_pdf(path)
    environmental = extract_environmental_data([result])

    assert environmental.record_count == len(SPECIAL_STANDARD_ANSWERS)
    for expected in SPECIAL_STANDARD_ANSWERS:
        record = _find_record(
            environmental.records,
            expected["indicator"],
            expected["value"],
            expected["detection_limit"],
        )
        assert record.unit == expected["unit"]
        assert expected["point"] in (record.point or "")
        assert record.time == expected["time"]
        assert record.source_location["table_index"] == 0
        assert record.source_location["row_index"] == expected["row_index"]
        assert record.source_location["column_index"] == 1
        assert record.source_location["page_number"] == 1

    points = {record.point for record in environmental.records}
    times = {record.time for record in environmental.records}
    units = {record.unit for record in environmental.records}
    assert {"废水总排口", "废气排放口", "厂界东侧"}.issubset(points)
    assert {"2024-07-01", "2024-07-02"}.issubset(times)
    assert {"mg/L", "mg/m³", "无量纲", "dB(A)"}.issubset(units)


def test_special_values_are_preserved_not_converted_to_zero(tmp_path: Path) -> None:
    path = make_special_values_pdf(tmp_path / "special_values.pdf")
    result = parse_pdf(path)
    environmental = extract_environmental_data([result])

    detection = _find_record(environmental.records, "总磷", None, "<0.01")
    assert detection.value is None
    assert detection.detection_limit == "<0.01"
    assert detection.value != 0
    assert "<0.01" in detection.raw_expression or "<0.01" in detection.source_text

    nd = _find_record(environmental.records, "二氧化硫", None, "ND")
    assert nd.value is None
    assert nd.unit == "mg/m³"
    assert nd.value != 0
    assert "ND" in nd.raw_expression or "ND" in nd.source_text

    missing = _find_record(environmental.records, "悬浮物", None, None)
    assert missing.value is None
    assert missing.unit == "mg/L"
    assert missing.value != 0
    assert "—" in missing.raw_expression or "—" in missing.source_text
    assert "missing_value" in missing.flags
