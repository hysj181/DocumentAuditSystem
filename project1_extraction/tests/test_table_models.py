from __future__ import annotations

from doc_extractor.core.table_models import TableData, table_record_metadata
from table_test_support import (
    COLUMN_TABLE_HTML,
    environment_table_parsed,
    parsed_table_from_html,
    row_table_parsed,
)


def test_html_table_parses_multi_level_headers_and_merged_cells() -> None:
    table = environment_table_parsed()

    assert table.row_count == 5
    assert table.column_count == 8
    assert table.header_row_count == 2
    assert table.headers[0][0] == "监测点位"
    assert table.headers[0][1] == "废水污染物"
    assert table.headers[1][1] == "COD\nmg/L"
    assert table.headers[1][2] == "氨氮\nmg/L"

    point_cell = next(
        cell
        for cell in table.cells
        if cell.row_index == 2 and cell.column_index == 0
    )
    assert point_cell.row_span == 2
    assert "废水总排口" in (point_cell.text or "")

    grid = table.grid()
    assert grid[3][0] == grid[2][0]
    assert grid[2][5] == ""
    blank_cell = next(
        cell
        for cell in table.cells
        if cell.row_index == 2 and cell.column_index == 5
    )
    assert blank_cell.text is None


def test_table_data_preserves_image_and_pdf_coordinates() -> None:
    parsed = environment_table_parsed()
    table = TableData.from_parsed(
        parsed,
        source_file="simulated.pdf",
        page_number=2,
        table_id="p2-t0",
        extraction_engine="PaddleOCR PP-StructureV3",
        image_size=[1240, 1754],
        pdf_size=[595.0, 842.0],
        dpi=200,
    )

    assert table.coordinate_space == "pdf"
    assert table.image_table_bbox == [80.0, 180.0, 1120.0, 580.0]
    assert table.table_bbox == [38.387, 86.408, 537.419, 278.426]
    assert table.coordinate_transform["scale_x"] == round(595 / 1240, 8)
    assert table.coordinate_transform["scale_y"] == round(842 / 1754, 8)
    assert table.image_size == [1240, 1754]
    assert table.pdf_size == [595.0, 842.0]

    first_cell = table.cells[0]
    assert first_cell.image_bbox is not None
    assert first_cell.bbox is not None
    assert first_cell.bbox[0] == round(first_cell.image_bbox[0] * 595 / 1240, 3)

    payload = table.to_dict()
    assert payload["page_number"] == 2
    assert payload["table_id"] == "p2-t0"
    assert payload["extraction_engine"] == "PaddleOCR PP-StructureV3"
    assert payload["cells"][0]["row_span"] == 2
    assert payload["coordinate_transform"]["dpi"] == 200


def test_row_oriented_table_header_detection() -> None:
    table = row_table_parsed()

    assert table.header_row_count == 1
    assert table.headers == [["监测点位", "指标", "数值", "单位", "监测日期"]]
    assert table.grid()[1] == [
        "DW002 废水排放口",
        "COD",
        "50.1",
        "mg/L",
        "2024-06-01",
    ]


def test_table_record_metadata_exposes_unified_model() -> None:
    parsed = parsed_table_from_html(
        COLUMN_TABLE_HTML,
        bbox=[10.0, 20.0, 300.0, 200.0],
    )
    table = TableData.from_parsed(
        parsed,
        source_file="simulated.pdf",
        page_number=1,
        table_id="p1-t0",
        extraction_engine="PaddleOCR PP-StructureV3",
    )
    metadata = table_record_metadata(table)

    assert metadata["table_id"] == "p1-t0"
    assert metadata["extraction_engine"] == "PaddleOCR PP-StructureV3"
    assert metadata["unified_table"]["rows"] == table.rows
    assert metadata["rows"][2][1] == "45.2"
    assert metadata["cells"][0]["row_index"] == 0
    assert "needs_review" in metadata
