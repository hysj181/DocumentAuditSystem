from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from doc_extractor.core.paddle_structure import (
    StructureLine,
    StructurePageResult,
    parse_html_table,
)
from doc_extractor.core.table_models import ParsedTable, TableCell

ENTERPRISE_NAME = "模拟环境科技有限公司"
ENTERPRISE_CODE = "91310115MA1K4A2B3C"
MONITORING_DATE = "2024-05-01"
SECOND_DATE = "2024-05-02"
GAS_DATE = "2024-05-01"

COLUMN_TABLE_HTML = """
<html><body><table>
<tr>
  <th rowspan="2">监测点位</th>
  <th colspan="4">废水污染物</th>
  <th colspan="2">废气污染物</th>
  <th rowspan="2">监测日期</th>
</tr>
<tr>
  <th>COD<br/>mg/L</th>
  <th>氨氮<br/>mg/L</th>
  <th>总磷<br/>mg/L</th>
  <th>pH</th>
  <th>SO2<br/>mg/m3</th>
  <th>NOx<br/>mg/m3</th>
</tr>
<tr>
  <td rowspan="2">DW001 废水总排口</td>
  <td>45.2</td>
  <td>1.23</td>
  <td>&lt;0.01</td>
  <td>7.3</td>
  <td></td>
  <td></td>
  <td>2024-05-01</td>
</tr>
<tr>
  <td>46.0</td>
  <td>1.30</td>
  <td>0.02</td>
  <td>7.2</td>
  <td></td>
  <td></td>
  <td>2024-05-02</td>
</tr>
<tr>
  <td>DA001 废气排放口</td>
  <td></td>
  <td></td>
  <td></td>
  <td></td>
  <td>12.5</td>
  <td>35.2</td>
  <td>2024-05-01</td>
</tr>
</table></body></html>
"""

ROW_TABLE_HTML = """
<html><body><table>
<tr><th>监测点位</th><th>指标</th><th>数值</th><th>单位</th><th>监测日期</th></tr>
<tr><td>DW002 废水排放口</td><td>COD</td><td>50.1</td><td>mg/L</td><td>2024-06-01</td></tr>
<tr><td></td><td>氨氮</td><td>1.50</td><td>mg/L</td><td>2024-06-01</td></tr>
</table></body></html>
"""

SIMULATED_STANDARD_ANSWERS: list[dict[str, Any]] = [
    {
        "indicator": "COD",
        "value": 45.2,
        "unit": "mg/L",
        "point": "废水总排口",
        "time": MONITORING_DATE,
        "detection_limit": None,
        "row_index": 2,
        "column_index": 1,
    },
    {
        "indicator": "氨氮",
        "value": 1.23,
        "unit": "mg/L",
        "point": "废水总排口",
        "time": MONITORING_DATE,
        "detection_limit": None,
        "row_index": 2,
        "column_index": 2,
    },
    {
        "indicator": "总磷",
        "value": None,
        "unit": "mg/L",
        "point": "废水总排口",
        "time": MONITORING_DATE,
        "detection_limit": "<0.01",
        "row_index": 2,
        "column_index": 3,
    },
    {
        "indicator": "pH",
        "value": 7.3,
        "unit": None,
        "point": "废水总排口",
        "time": MONITORING_DATE,
        "detection_limit": None,
        "row_index": 2,
        "column_index": 4,
    },
    {
        "indicator": "二氧化硫",
        "value": 12.5,
        "unit": "mg/m³",
        "point": "废气排放口",
        "time": GAS_DATE,
        "detection_limit": None,
        "row_index": 4,
        "column_index": 5,
    },
    {
        "indicator": "氮氧化物",
        "value": 35.2,
        "unit": "mg/m³",
        "point": "废气排放口",
        "time": GAS_DATE,
        "detection_limit": None,
        "row_index": 4,
        "column_index": 6,
    },
    {
        "indicator": "COD",
        "value": 46.0,
        "unit": "mg/L",
        "point": "废水总排口",
        "time": SECOND_DATE,
        "detection_limit": None,
        "row_index": 3,
        "column_index": 1,
    },
    {
        "indicator": "氨氮",
        "value": 1.30,
        "unit": "mg/L",
        "point": "废水总排口",
        "time": SECOND_DATE,
        "detection_limit": None,
        "row_index": 3,
        "column_index": 2,
    },
    {
        "indicator": "总磷",
        "value": 0.02,
        "unit": "mg/L",
        "point": "废水总排口",
        "time": SECOND_DATE,
        "detection_limit": None,
        "row_index": 3,
        "column_index": 3,
    },
    {
        "indicator": "pH",
        "value": 7.2,
        "unit": None,
        "point": "废水总排口",
        "time": SECOND_DATE,
        "detection_limit": None,
        "row_index": 3,
        "column_index": 4,
    },
]


def parsed_table_from_html(
    html: str,
    *,
    bbox: list[float] | None = None,
    cell_boxes: list[list[float]] | None = None,
    confidences: list[float] | None = None,
) -> ParsedTable:
    parsed_html = parse_html_table(html)
    assert parsed_html is not None
    cells, row_count, column_count = parsed_html
    if cell_boxes:
        for index, cell in enumerate(cells):
            if index < len(cell_boxes):
                cell.bbox = cell_boxes[index]
    if confidences:
        for index, cell in enumerate(cells):
            if index < len(confidences):
                cell.confidence = confidences[index]
    parsed = ParsedTable(
        cells=cells,
        row_count=row_count,
        column_count=column_count,
        bbox=bbox,
        html=html,
        confidence=sum(confidences) / len(confidences) if confidences else None,
        metadata={"source": "simulated"},
    )
    parsed.finalize()
    return parsed


def _grid_cell_boxes(
    *,
    x: float,
    y: float,
    column_widths: list[float],
    row_heights: list[float],
) -> list[list[float]]:
    boxes: list[list[float]] = []
    current_y = y
    for height in row_heights:
        current_x = x
        for width in column_widths:
            boxes.append(
                [
                    current_x,
                    current_y,
                    current_x + width,
                    current_y + height,
                ]
            )
            current_x += width
        current_y += height
    return boxes


def environment_table_parsed(
    *,
    bbox: list[float] | None = (80.0, 180.0, 1120.0, 580.0),
    with_confidence: bool = True,
) -> ParsedTable:
    column_widths = [240.0, 130.0, 130.0, 130.0, 90.0, 130.0, 130.0, 130.0]
    row_heights = [60.0, 60.0, 55.0, 55.0, 55.0]
    boxes = _grid_cell_boxes(
        x=80.0,
        y=180.0,
        column_widths=column_widths,
        row_heights=row_heights,
    )
    confidences = [0.98] * len(boxes) if with_confidence else None
    parsed = parsed_table_from_html(
        COLUMN_TABLE_HTML,
        bbox=list(bbox) if bbox else None,
        cell_boxes=boxes,
        confidences=confidences,
    )
    if any(
        (cell.row_span or 1) > 1 or (cell.column_span or 1) > 1
        for cell in parsed.cells
    ):
        parsed.review_reasons.append("merged_cells_detected")
        parsed.needs_review = True
    return parsed


def row_table_parsed() -> ParsedTable:
    return parsed_table_from_html(
        ROW_TABLE_HTML,
        bbox=[80.0, 180.0, 900.0, 360.0],
    )


@dataclass
class FakeStructureParser:
    by_page: dict[int, StructurePageResult] = field(default_factory=dict)
    name: str = "FakePPStructure"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def parse_page(
        self,
        image: Any,
        *,
        source_file: str,
        page_number: int,
        image_size: tuple[int, int] | None = None,
        pdf_size: tuple[float, float] | None = None,
        dpi: int | None = None,
    ) -> StructurePageResult:
        self.calls.append(
            {
                "image_shape": getattr(image, "shape", None),
                "source_file": source_file,
                "page_number": page_number,
                "image_size": image_size,
                "pdf_size": pdf_size,
                "dpi": dpi,
            }
        )
        return self.by_page.get(
            page_number,
            StructurePageResult(engine=self.name),
        )


def make_environment_structure_result(
    *,
    page_number: int = 2,
) -> StructurePageResult:
    table = environment_table_parsed()
    return StructurePageResult(
        tables=[table],
        text="",
        lines=[
            StructureLine(text="COD 45.2", bbox=[100.0, 300.0, 300.0, 330.0], confidence=0.97)
        ],
        engine="FakePPStructure",
        metadata={"page_number": page_number},
    )


def make_enterprise_text_structure_result(
    *,
    page_number: int = 1,
) -> StructurePageResult:
    lines = [
        StructureLine(
            text=f"企业名称：{ENTERPRISE_NAME}",
            bbox=[40.0, 80.0, 500.0, 110.0],
            confidence=0.99,
        ),
        StructureLine(
            text=f"统一社会信用代码：{ENTERPRISE_CODE}",
            bbox=[40.0, 120.0, 560.0, 150.0],
            confidence=0.99,
        ),
        StructureLine(
            text=f"监测日期：{MONITORING_DATE}",
            bbox=[40.0, 160.0, 400.0, 190.0],
            confidence=0.99,
        ),
    ]
    return StructurePageResult(
        text="\n".join(line.text for line in lines),
        lines=lines,
        engine="FakePPStructure",
        metadata={"page_number": page_number},
    )


def make_mixed_scanned_structure_parser() -> FakeStructureParser:
    return FakeStructureParser(
        by_page={
            1: make_enterprise_text_structure_result(page_number=1),
            2: make_environment_structure_result(page_number=2),
        }
    )


def make_native_table_pdf(
    path: Path,
    rows: list[list[str]],
    *,
    title_lines: tuple[str, ...] = (
        f"企业名称：{ENTERPRISE_NAME}",
        f"统一社会信用代码：{ENTERPRISE_CODE}",
        "监测日期：2024-05-01",
    ),
    column_widths: list[float] | None = None,
) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=842, height=595)
    y = 40.0
    for line in title_lines:
        page.insert_text((40, y), line, fontname="china-s", fontsize=12)
        y += 22
    top = y + 10
    row_height = 30.0
    widths = column_widths or [130.0, 100.0, 100.0, 100.0, 70.0, 120.0]
    xs = [40.0]
    for width in widths:
        xs.append(xs[-1] + width)
    ys = [top + index * row_height for index in range(len(rows) + 1)]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), color=(0, 0, 0), width=1)
    for line_y in ys:
        page.draw_line((xs[0], line_y), (xs[-1], line_y), color=(0, 0, 0), width=1)
    for row_index, row in enumerate(rows):
        for column_index, text in enumerate(row):
            page.insert_text(
                (xs[column_index] + 4, ys[row_index] + 20),
                text,
                fontname="china-s",
                fontsize=9,
            )
    document.save(path)
    document.close()
    return path


def make_mixed_scanned_pdf(
    path: Path,
    *,
    table_image: Path | None = None,
) -> Path:
    document = pymupdf.open()
    first = document.new_page(width=595, height=842)
    first.insert_text(
        (50, 70),
        f"企业名称：{ENTERPRISE_NAME}",
        fontname="china-s",
        fontsize=14,
    )
    first.insert_text(
        (50, 100),
        f"统一社会信用代码：{ENTERPRISE_CODE}",
        fontname="china-s",
        fontsize=11,
    )
    first.insert_text(
        (50, 130),
        f"监测日期：{MONITORING_DATE}",
        fontname="china-s",
        fontsize=11,
    )
    first.insert_text(
        (50, 160),
        "以下为扫描版监测结果表。",
        fontname="china-s",
        fontsize=11,
    )
    second = document.new_page(width=595, height=842)
    if table_image is not None and table_image.exists():
        second.insert_image(second.rect, filename=str(table_image))
    else:
        second.draw_rect(second.rect, color=(0.8, 0.8, 0.8), width=1)
    document.save(path)
    document.close()
    return path


def make_native_environment_pdf(path: Path) -> Path:
    rows = [
        ["监测点位", "COD(mg/L)", "氨氮(mg/L)", "总磷(mg/L)", "pH", "监测日期"],
        ["DW001 废水总排口", "45.2", "1.23", "<0.01", "7.3", "2024-05-01"],
        ["DA001 废气排放口", "", "", "", "", ""],
    ]
    return make_native_table_pdf(
        path,
        rows,
        column_widths=[140.0, 110.0, 110.0, 110.0, 60.0, 120.0],
    )


def make_row_oriented_native_pdf(path: Path) -> Path:
    rows = [
        ["监测点位", "指标", "数值", "单位", "监测日期"],
        ["DW003 废水排放口", "COD", "52.5", "mg/L", "2024-05-03"],
        ["", "氨氮", "1.80", "mg/L", "2024-05-03"],
    ]
    return make_native_table_pdf(
        path,
        rows,
        column_widths=[150.0, 100.0, 100.0, 100.0, 120.0],
    )
