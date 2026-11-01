from __future__ import annotations

from doc_extractor.core.paddle_structure import (
    LOW_CONFIDENCE_THRESHOLD,
    parse_html_table,
    tables_from_ppstructure_result,
)
from table_test_support import (
    COLUMN_TABLE_HTML,
    environment_table_parsed,
)


def _ppstructure_payload(
    *,
    with_table_res: bool = True,
    scores: float = 0.97,
) -> dict:
    table = environment_table_parsed()
    cell_boxes = [
        cell.bbox if cell.bbox is not None else [0, 0, 1, 1]
        for cell in table.cells
    ]
    ocr_texts = [cell.text for cell in table.cells if cell.text]
    ocr_boxes = [
        cell.bbox
        for cell in table.cells
        if cell.text and cell.bbox is not None
    ]
    payload: dict = {
        "width": 1240,
        "height": 1754,
        "parsing_res_list": [
            {
                "block_label": "table",
                "block_content": COLUMN_TABLE_HTML,
                "block_bbox": [80, 180, 1120, 580],
                "block_id": 0,
            }
        ],
        "layout_det_res": {
            "boxes": [
                {
                    "label": "table",
                    "score": 0.99,
                    "coordinate": [80, 180, 1120, 580],
                }
            ]
        },
        "overall_ocr_res": {
            "rec_texts": ocr_texts,
            "rec_boxes": ocr_boxes,
            "rec_scores": [scores] * len(ocr_texts),
        },
    }
    if with_table_res:
        payload["table_res_list"] = [
            {
                "res": {
                    "cell_box_list": cell_boxes,
                    "pred_html": COLUMN_TABLE_HTML,
                    "table_ocr_pred": {
                        "rec_texts": ocr_texts,
                        "rec_boxes": ocr_boxes,
                        "rec_scores": [scores] * len(ocr_texts),
                    },
                }
            }
        ]
    return payload


def test_tables_from_ppstructure_result_parses_html_cells_and_spans() -> None:
    tables, lines, warnings = tables_from_ppstructure_result(
        _ppstructure_payload()
    )

    assert not warnings
    assert len(tables) == 1
    table = tables[0]
    assert table.row_count == 5
    assert table.column_count == 8
    assert table.header_row_count == 2
    assert table.bbox == [80.0, 180.0, 1120.0, 580.0]
    assert table.needs_review is True
    assert "merged_cells_detected" in table.review_reasons
    assert table.confidence is not None
    assert table.confidence >= LOW_CONFIDENCE_THRESHOLD

    point_cell = next(
        cell
        for cell in table.cells
        if cell.row_index == 2 and cell.column_index == 0
    )
    assert point_cell.row_span == 2
    assert point_cell.bbox is not None
    assert point_cell.confidence is not None

    cod_cell = next(
        cell
        for cell in table.cells
        if cell.row_index == 2 and cell.column_index == 1
    )
    assert cod_cell.text == "45.2"
    assert cod_cell.confidence == 0.97
    assert len(lines) > 0


def test_low_confidence_cells_are_marked_for_review() -> None:
    tables, _lines, _warnings = tables_from_ppstructure_result(
        _ppstructure_payload(scores=0.5)
    )

    table = tables[0]
    assert table.needs_review is True
    assert "low_confidence_cell" in table.review_reasons
    assert table.confidence == 0.5


def test_parsing_res_list_fallback_keeps_html_structure_without_cell_boxes() -> None:
    tables, _lines, _warnings = tables_from_ppstructure_result(
        _ppstructure_payload(with_table_res=False)
    )

    assert len(tables) == 1
    table = tables[0]
    assert table.row_count == 5
    assert table.column_count == 8
    assert table.header_row_count == 2
    assert "cell_bbox_missing" in table.review_reasons
    assert all(cell.bbox is None for cell in table.cells)


def test_parse_html_table_returns_none_for_non_table_content() -> None:
    assert parse_html_table("") is None
    assert parse_html_table("not a table") is None
    assert parse_html_table("<html><body><p>text</p></body></html>") is None
