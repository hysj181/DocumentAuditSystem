from __future__ import annotations

import json
from pathlib import Path

from openpyxl import load_workbook

from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.exporters import export_excel, export_json
from doc_extractor.core.paddle_structure import paddle_structure_available
from doc_extractor.core.pdf_parser import parse_pdf
from table_test_support import (
    SIMULATED_STANDARD_ANSWERS,
    make_mixed_scanned_pdf,
    make_mixed_scanned_structure_parser,
    make_native_environment_pdf,
    make_row_oriented_native_pdf,
)


def _by_indicator_values(records):
    return {
        (record.indicator, record.value, record.detection_limit): record
        for record in records
    }


def test_native_pdf_table_uses_paddle_and_keeps_cell_coordinates(
    tmp_path: Path,
) -> None:
    path = make_native_environment_pdf(tmp_path / "native_environment.pdf")

    result = parse_pdf(path)

    assert result.error is None
    assert result.metadata["table_count"] == 1
    assert result.metadata["parse_engine"] == "paddleocr"
    assert result.metadata["structure_used"] is True
    assert len(result.tables) == 1

    table = result.tables[0]
    assert table.extraction_engine == "PaddleOCR PP-StructureV3"
    assert table.page_number == 1
    assert table.table_bbox is not None
    assert table.rows >= 2
    assert table.columns >= 5
    assert table.cells
    assert all(cell.bbox is not None for cell in table.cells if cell.text)

    table_record = next(
        record for record in result.records if record.content_type == "table"
    )
    assert table_record.metadata["extraction_engine"] == "PaddleOCR PP-StructureV3"
    assert table_record.metadata["unified_table"]["table_id"] == table.table_id


def test_native_column_oriented_table_maps_pollutants_values_and_units(
    tmp_path: Path,
) -> None:
    path = make_native_environment_pdf(tmp_path / "native_environment.pdf")
    result = parse_pdf(path)
    environmental = extract_environmental_data([result])

    assert environmental.record_count >= 4
    records = _by_indicator_values(environmental.records)

    cod = records[("COD", 45.2, None)]
    assert cod.unit == "mg/L"
    assert cod.point == "废水总排口"
    assert cod.time == "2024-05-01"
    assert cod.source_location["row_index"] == 1
    assert cod.source_location["column_index"] == 1

    ammonia = records[("氨氮", 1.23, None)]
    assert ammonia.unit == "mg/L"
    assert ammonia.point == "废水总排口"

    total_phosphorus = records[("总磷", None, "<0.01")]
    assert total_phosphorus.unit == "mg/L"
    assert total_phosphorus.point == "废水总排口"

    ph = records[("pH", 7.3, None)]
    assert ph.unit is None
    assert ph.point == "废水总排口"

    assert not any(
        record.indicator == "COD" and record.point == "废气排放口"
        for record in environmental.records
    )


def test_native_row_oriented_table_still_extracts_values(tmp_path: Path) -> None:
    path = make_row_oriented_native_pdf(tmp_path / "row_oriented.pdf")
    result = parse_pdf(path)
    environmental = extract_environmental_data([result])
    records = _by_indicator_values(environmental.records)

    cod = records[("COD", 52.5, None)]
    assert cod.unit == "mg/L"
    assert cod.point == "废水排放口"
    assert cod.time == "2024-05-03"

    ammonia = records[("氨氮", 1.8, None)]
    assert ammonia.unit == "mg/L"
    assert ammonia.point == "废水排放口"


def test_all_pdf_pages_use_injected_paddle_parser(tmp_path: Path) -> None:
    path = make_mixed_scanned_pdf(tmp_path / "mixed_scanned.pdf")
    parser = make_mixed_scanned_structure_parser()

    result = parse_pdf(path, structure_parser=parser)

    assert result.error is None
    assert result.metadata["parse_engine"] == "paddleocr"
    assert result.metadata["structure_used"] is True
    assert result.metadata["engine_usage"] == {"FakePPStructure": 2}
    assert [call["page_number"] for call in parser.calls] == [1, 2]

    page_records = [
        record for record in result.records if record.content_type == "ocr_page"
    ]
    assert len(page_records) == 2
    assert "模拟环境科技有限公司" in page_records[0].text
    assert "COD 45.2" in page_records[1].text


def test_mixed_pdf_uses_paddle_for_scanned_page_and_keeps_page_bboxes(
    tmp_path: Path,
) -> None:
    path = make_mixed_scanned_pdf(tmp_path / "mixed_scanned.pdf")
    parser = make_mixed_scanned_structure_parser()

    result = parse_pdf(path, structure_parser=parser)

    assert result.error is None
    assert result.metadata["structure_used"] is True
    assert len(result.tables) == 1
    table = result.tables[0]
    assert table.page_number == 2
    assert table.extraction_engine == "PaddleOCR PP-StructureV3"
    assert table.header_row_count == 2
    assert table.needs_review is True
    assert "merged_cells_detected" in table.review_reasons

    call = next(call for call in parser.calls if call["page_number"] == 2)
    scale_x = call["pdf_size"][0] / call["image_size"][0]
    scale_y = call["pdf_size"][1] / call["image_size"][1]
    expected_bbox = [
        round(80 * scale_x, 3),
        round(180 * scale_y, 3),
        round(1120 * scale_x, 3),
        round(580 * scale_y, 3),
    ]
    assert table.table_bbox == expected_bbox
    assert table.coordinate_transform["dpi"] == 200
    assert table.coordinate_transform["image_size"] == list(call["image_size"])

    table_record = next(
        record for record in result.records if record.content_type == "table"
    )
    assert table_record.location.page_number == 2
    assert table_record.metadata["extraction_engine"] == "PaddleOCR PP-StructureV3"
    assert table_record.metadata["needs_review"] is True
    assert "merged_cells_detected" in table_record.metadata["review_reasons"]


def test_mixed_pdf_environmental_association_matches_standard_answers(
    tmp_path: Path,
) -> None:
    path = make_mixed_scanned_pdf(tmp_path / "mixed_scanned.pdf")
    parser = make_mixed_scanned_structure_parser()
    result = parse_pdf(path, structure_parser=parser)
    environmental = extract_environmental_data([result])

    assert environmental.record_count == len(SIMULATED_STANDARD_ANSWERS)
    records = _by_indicator_values(environmental.records)
    for expected in SIMULATED_STANDARD_ANSWERS:
        key = (
            expected["indicator"],
            expected["value"],
            expected["detection_limit"],
        )
        if key not in records:
            key = (
                expected["indicator"],
                float(expected["value"]),
                expected["detection_limit"],
            )
        record = records[key]
        assert record.unit == expected["unit"]
        assert expected["point"] in (record.point or "")
        assert record.time == expected["time"]
        assert record.source_location["row_index"] == expected["row_index"]
        assert record.source_location["column_index"] == expected["column_index"]
        assert record.source_content_type == "table"

    total_phosphorus = next(
        record for record in environmental.records if record.indicator == "总磷"
    )
    assert total_phosphorus.value is None
    assert total_phosphorus.detection_limit == "<0.01"
    assert total_phosphorus.value != 0

    assert not any(
        record.indicator == "COD" and "废气" in (record.point or "")
        for record in environmental.records
    )
    assert not any(
        record.value is None and record.indicator == "pH"
        for record in environmental.records
    )


def test_json_and_excel_export_include_unified_tables_and_environmental_data(
    tmp_path: Path,
) -> None:
    path = make_mixed_scanned_pdf(tmp_path / "mixed_scanned.pdf")
    parser = make_mixed_scanned_structure_parser()
    result = parse_pdf(path, structure_parser=parser)
    environmental = extract_environmental_data([result])

    json_path = export_json([result], tmp_path / "result.json", environmental)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["table_count"] == 1
    assert payload["tables"][0]["table_id"] == "p2-t0"
    assert payload["tables"][0]["extraction_engine"] == "PaddleOCR PP-StructureV3"
    assert payload["tables"][0]["cells"][0]["text"] is not None
    assert payload["environmental"]["record_count"] == len(
        SIMULATED_STANDARD_ANSWERS
    )

    excel_path = export_excel([result], tmp_path / "result.xlsx", environmental)
    workbook = load_workbook(excel_path, read_only=True)
    table_rows = list(workbook["表格数据"].iter_rows(values_only=True))
    env_rows = list(workbook["环境数据"].iter_rows(values_only=True))
    assert table_rows[0][7] == "表格ID"
    assert table_rows[0][8] == "提取引擎"
    assert any(
        row[6] == "45.2" and row[8] == "PaddleOCR PP-StructureV3"
        for row in table_rows[1:]
    )
    assert any(row[8] == "COD" and row[9] == 45.2 for row in env_rows[1:])
    workbook.close()


def test_paddle_structure_is_installed_or_reported() -> None:
    assert isinstance(paddle_structure_available(), bool)
