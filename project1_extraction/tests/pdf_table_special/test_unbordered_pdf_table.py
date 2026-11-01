from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from doc_extractor.core.paddle_structure import tables_from_ppstructure_result
from doc_extractor.core.pdf_parser import parse_pdf
from pdf_table_special.support import (
    BORDERLESS_ROWS,
    make_borderless_native_pdf,
)


def _html_from_rows(rows: list[list[str]]) -> str:
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    return "<html><body><table>" + "".join(body) + "</table></body></html>"


def test_unbordered_native_pdf_is_a_known_detection_limitation(
    tmp_path: Path,
) -> None:
    path = make_borderless_native_pdf(tmp_path / "borderless.pdf")
    result = parse_pdf(path)

    assert result.error is None
    assert result.metadata["table_count"] == 0
    assert result.tables == []
    raw_text = result.raw_text()
    assert "监测点位" in raw_text
    assert "COD" in raw_text
    assert "45.2" in raw_text


def test_unbordered_table_html_structure_is_supported_when_model_returns_it() -> None:
    data = {
        "parsing_res_list": [
            {
                "block_label": "table",
                "block_content": _html_from_rows(BORDERLESS_ROWS),
                "block_bbox": [40, 100, 700, 250],
            }
        ],
        "table_res_list": [
            {
                "res": {
                    "pred_html": _html_from_rows(BORDERLESS_ROWS),
                    "cell_box_list": [
                        [40, 100, 190, 130],
                        [190, 100, 310, 130],
                        [310, 100, 430, 130],
                        [430, 100, 550, 130],
                        [550, 100, 620, 130],
                        [620, 100, 750, 130],
                        [40, 130, 190, 160],
                        [190, 130, 310, 160],
                        [310, 130, 430, 160],
                        [430, 130, 550, 160],
                        [550, 130, 620, 160],
                        [620, 130, 750, 160],
                        [40, 160, 190, 190],
                        [190, 160, 310, 190],
                        [310, 160, 430, 190],
                        [430, 160, 550, 190],
                        [550, 160, 620, 190],
                        [620, 160, 750, 190],
                    ],
                }
            }
        ],
    }

    tables, _lines, warnings = tables_from_ppstructure_result(data)

    assert not warnings
    assert len(tables) == 1
    table = tables[0]
    assert table.row_count == 3
    assert table.column_count == 6
    assert table.header_row_count == 1
    assert table.grid()[1][0] == "DW001 废水总排口"
    assert table.grid()[1][1] == "45.2"
    assert table.grid()[2][0] == "DA001 废气排放口"
