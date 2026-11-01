from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUMBER_CELL_RE = re.compile(
    r"^[\s¥￥$]?[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:%|％)?$"
)
_DATE_CELL_RE = re.compile(
    r"^(?:19|20)\d{2}\s*[-/.年]\s*\d{1,2}(?:\s*[-/.月]\s*\d{1,2})?\s*日?$"
)
_HEADER_KEYWORDS = (
    "指标",
    "项目",
    "点位",
    "单位",
    "数值",
    "名称",
    "日期",
    "时间",
    "类别",
    "参数",
    "监测",
    "污染物",
    "统计",
    "排放",
    "浓度",
    "编号",
    "备注",
    "结果",
    "限值",
    "标准",
    "序号",
    "因子",
    "样品",
)
def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _looks_numeric(text: str) -> bool:
    compact = text.replace(" ", "")
    if not compact:
        return False
    if compact.upper() in {"ND", "N.D.", "N.D"}:
        return False
    if compact.startswith(("<", "≤")):
        return True
    return bool(_NUMBER_CELL_RE.match(compact))


def _looks_date(text: str) -> bool:
    return bool(_DATE_CELL_RE.match(text.replace(" ", "")))


def _looks_like_header_row(row: list[str]) -> bool:
    texts = [text for text in row if text]
    if not texts:
        return False
    if any(keyword in text for text in texts for keyword in _HEADER_KEYWORDS):
        return True
    return not any(_looks_numeric(text) or _looks_date(text) for text in texts)


def _row_has_data(texts: list[str]) -> bool:
    return any(_looks_numeric(text) or _looks_date(text) for text in texts if text)


def cell_grid(
    cells: list["TableCell"],
    row_count: int,
    column_count: int,
    *,
    fill_merged: bool = True,
) -> list[list[str]]:
    grid = [["" for _ in range(column_count)] for _ in range(row_count)]
    for cell in cells:
        text = cell.text or ""
        row_span = max(1, int(cell.row_span or 1))
        column_span = max(1, int(cell.column_span or 1))
        for row_index in range(cell.row_index, min(cell.row_index + row_span, row_count)):
            for column_index in range(
                cell.column_index, min(cell.column_index + column_span, column_count)
            ):
                if grid[row_index][column_index]:
                    continue
                if fill_merged or (
                    row_index == cell.row_index and column_index == cell.column_index
                ):
                    grid[row_index][column_index] = text
    return grid


def detect_header_rows(
    cells: list["TableCell"],
    row_count: int,
    column_count: int,
) -> list[int]:
    if row_count <= 0 or column_count <= 0:
        return []
    grid = cell_grid(cells, row_count, column_count)
    explicit_header_rows = sorted(
        {
            cell.row_index
            for cell in cells
            if cell.is_header and 0 <= cell.row_index < row_count
        }
    )
    if explicit_header_rows:
        # PP-StructureV3 有时只在分组标题行使用 <th>，真正的列名行仍为 <td>。
        # 若紧跟其后的文本行也呈表头特征，且再下一行已出现数据，则一并视为表头。
        extended = list(explicit_header_rows)
        next_index = extended[-1] + 1
        if next_index < row_count and len(extended) < 3:
            next_texts = [text for text in grid[next_index] if text]
            following_texts = (
                [text for text in grid[next_index + 1] if text]
                if next_index + 1 < row_count
                else []
            )
            if (
                next_texts
                and not _row_has_data(next_texts)
                and _looks_like_header_row(next_texts)
                and (not following_texts or _row_has_data(following_texts))
            ):
                extended.append(next_index)
        return extended

    leading_rows: list[int] = []
    for row_index in range(min(row_count, 4)):
        texts = [text for text in grid[row_index] if text]
        if not texts or _row_has_data(texts):
            break
        if not _looks_like_header_row(texts):
            break
        leading_rows.append(row_index)

    if not leading_rows:
        return []

    has_keyword = any(
        keyword in text
        for row_index in leading_rows
        for text in grid[row_index]
        if text
        for keyword in _HEADER_KEYWORDS
    )
    next_row_index = leading_rows[-1] + 1
    next_row_has_data = (
        _row_has_data([text for text in grid[next_row_index] if text])
        if next_row_index < row_count
        else False
    )
    if not has_keyword and not next_row_has_data:
        return []
    return leading_rows


def build_headers(
    grid: list[list[str]],
    header_rows: list[int],
) -> list[list[str | None]]:
    headers: list[list[str | None]] = []
    for row_index in header_rows:
        if 0 <= row_index < len(grid):
            headers.append([text if text else None for text in grid[row_index]])
    return headers


def _merge_review_reasons(reasons: list[str]) -> list[str]:
    return list(dict.fromkeys(reason for reason in reasons if reason))


@dataclass
class TableCell:
    row_index: int
    column_index: int
    text: str | None
    bbox: list[float] | None = None
    row_span: int | None = 1
    column_span: int | None = 1
    confidence: float | None = None
    is_header: bool = False
    image_bbox: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_index": self.row_index,
            "column_index": self.column_index,
            "text": self.text,
            "bbox": self.bbox,
            "row_span": self.row_span,
            "column_span": self.column_span,
            "confidence": self.confidence,
            "is_header": self.is_header,
            "image_bbox": self.image_bbox,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TableCell":
        return cls(
            row_index=int(data.get("row_index", 0)),
            column_index=int(data.get("column_index", 0)),
            text=data.get("text"),
            bbox=data.get("bbox"),
            row_span=data.get("row_span", 1),
            column_span=data.get("column_span", 1),
            confidence=data.get("confidence"),
            is_header=bool(data.get("is_header", False)),
            image_bbox=data.get("image_bbox"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ParsedTable:
    cells: list[TableCell]
    row_count: int
    column_count: int
    bbox: list[float] | None = None
    html: str | None = None
    headers: list[list[str | None]] = field(default_factory=list)
    header_row_count: int = 0
    confidence: float | None = None
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def grid(self, *, fill_merged: bool = True) -> list[list[str]]:
        return cell_grid(
            self.cells,
            self.row_count,
            self.column_count,
            fill_merged=fill_merged,
        )

    def finalize(self) -> "ParsedTable":
        header_rows = detect_header_rows(self.cells, self.row_count, self.column_count)
        self.header_row_count = len(header_rows)
        self.headers = build_headers(self.grid(), header_rows)
        header_row_set = set(header_rows)
        for cell in self.cells:
            if cell.row_index in header_row_set:
                cell.is_header = True
        return self


@dataclass
class TableData:
    source_file: str
    page_number: int | None
    table_id: str
    table_bbox: list[float] | None
    extraction_engine: str
    rows: int
    columns: int
    headers: list[list[str | None]]
    cells: list[TableCell]
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    confidence: float | None = None
    header_row_count: int = 0
    coordinate_space: str = "pdf"
    image_table_bbox: list[float] | None = None
    image_size: list[int] | None = None
    pdf_size: list[float] | None = None
    coordinate_transform: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def grid(self, *, fill_merged: bool = True) -> list[list[str]]:
        return cell_grid(
            self.cells,
            self.rows,
            self.columns,
            fill_merged=fill_merged,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "page_number": self.page_number,
            "table_id": self.table_id,
            "table_bbox": self.table_bbox,
            "extraction_engine": self.extraction_engine,
            "rows": self.rows,
            "columns": self.columns,
            "headers": self.headers,
            "header_row_count": self.header_row_count,
            "cells": [cell.to_dict() for cell in self.cells],
            "needs_review": self.needs_review,
            "review_reasons": self.review_reasons,
            "confidence": self.confidence,
            "coordinate_space": self.coordinate_space,
            "image_table_bbox": self.image_table_bbox,
            "image_size": self.image_size,
            "pdf_size": self.pdf_size,
            "coordinate_transform": self.coordinate_transform,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TableData":
        return cls(
            source_file=data.get("source_file", ""),
            page_number=data.get("page_number"),
            table_id=data.get("table_id", ""),
            table_bbox=data.get("table_bbox"),
            extraction_engine=data.get("extraction_engine", ""),
            rows=int(data.get("rows", 0)),
            columns=int(data.get("columns", 0)),
            headers=data.get("headers", []),
            cells=[TableCell.from_dict(item) for item in data.get("cells", [])],
            needs_review=bool(data.get("needs_review", False)),
            review_reasons=list(data.get("review_reasons", [])),
            confidence=data.get("confidence"),
            header_row_count=int(data.get("header_row_count", 0)),
            coordinate_space=data.get("coordinate_space", "pdf"),
            image_table_bbox=data.get("image_table_bbox"),
            image_size=data.get("image_size"),
            pdf_size=data.get("pdf_size"),
            coordinate_transform=dict(data.get("coordinate_transform", {})),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_parsed(
        cls,
        parsed: ParsedTable,
        *,
        source_file: str,
        page_number: int | None,
        table_id: str,
        extraction_engine: str,
        image_size: list[int] | None = None,
        pdf_size: list[float] | None = None,
        dpi: int | None = None,
        coordinate_transform: dict[str, Any] | None = None,
    ) -> "TableData":
        scale_x = 1.0
        scale_y = 1.0
        if image_size and pdf_size and image_size[0] and image_size[1]:
            scale_x = float(pdf_size[0]) / float(image_size[0])
            scale_y = float(pdf_size[1]) / float(image_size[1])

        transform = {
            "image_size": image_size,
            "pdf_size": pdf_size,
            "dpi": dpi,
            "scale_x": round(scale_x, 8),
            "scale_y": round(scale_y, 8),
        }
        if coordinate_transform:
            transform.update(coordinate_transform)

        def convert(bbox: list[float] | None) -> list[float] | None:
            if not bbox or len(bbox) != 4:
                return None
            return [
                round(float(bbox[0]) * scale_x, 3),
                round(float(bbox[1]) * scale_y, 3),
                round(float(bbox[2]) * scale_x, 3),
                round(float(bbox[3]) * scale_y, 3),
            ]

        converted_cells: list[TableCell] = []
        for cell in parsed.cells:
            converted = TableCell(
                row_index=cell.row_index,
                column_index=cell.column_index,
                text=cell.text,
                bbox=convert(cell.bbox),
                row_span=cell.row_span,
                column_span=cell.column_span,
                confidence=cell.confidence,
                is_header=cell.is_header,
                image_bbox=cell.image_bbox if cell.image_bbox is not None else cell.bbox,
                metadata=dict(cell.metadata),
            )
            converted_cells.append(converted)

        return cls(
            source_file=source_file,
            page_number=page_number,
            table_id=table_id,
            table_bbox=convert(parsed.bbox),
            extraction_engine=extraction_engine,
            rows=parsed.row_count,
            columns=parsed.column_count,
            headers=parsed.headers,
            cells=converted_cells,
            needs_review=parsed.needs_review,
            review_reasons=_merge_review_reasons(parsed.review_reasons),
            confidence=parsed.confidence,
            header_row_count=parsed.header_row_count,
            coordinate_space="pdf" if pdf_size else "image",
            image_table_bbox=parsed.bbox,
            image_size=image_size,
            pdf_size=pdf_size,
            coordinate_transform=transform,
            metadata=dict(parsed.metadata),
        )


def parsed_table_from_grid(
    rows: list[list[str]],
    *,
    bbox: list[float] | None = None,
    cell_bboxes: list[list[list[float] | None]] | None = None,
    html: str | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> ParsedTable:
    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    cells: list[TableCell] = []
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            text = _clean_text(value) or None
            cell_bbox = None
            if cell_bboxes and row_index < len(cell_bboxes):
                if column_index < len(cell_bboxes[row_index]):
                    cell_bbox = cell_bboxes[row_index][column_index]
            cells.append(
                TableCell(
                    row_index=row_index,
                    column_index=column_index,
                    text=text,
                    bbox=cell_bbox,
                    row_span=1,
                    column_span=1,
                    confidence=confidence,
                )
            )

    review_reasons: list[str] = []
    if row_count == 0 or column_count == 0:
        review_reasons.append("empty_table")
    if bbox is None:
        review_reasons.append("missing_table_bbox")
    if row_count > 0 and column_count > 0 and not any(
        (cell.text or "").strip() for cell in cells
    ):
        review_reasons.append("empty_table")

    parsed = ParsedTable(
        cells=cells,
        row_count=row_count,
        column_count=column_count,
        bbox=bbox,
        html=html,
        confidence=confidence,
        needs_review=bool(review_reasons),
        review_reasons=review_reasons,
        metadata=dict(metadata or {}),
    )
    parsed.finalize()
    if parsed.header_row_count == 0:
        parsed.review_reasons.append("no_header_detected")
        parsed.needs_review = True
    return parsed


def table_record_metadata(table: TableData) -> dict[str, Any]:
    return {
        "rows": table.grid(),
        "cells": [
            {
                "row_index": cell.row_index,
                "column_index": cell.column_index,
                "text": cell.text or "",
                "bbox": cell.bbox,
                "image_bbox": cell.image_bbox,
                "row_span": cell.row_span,
                "column_span": cell.column_span,
                "confidence": cell.confidence,
                "is_header": cell.is_header,
            }
            for cell in table.cells
        ],
        "headers": table.headers,
        "header_row_count": table.header_row_count,
        "table_id": table.table_id,
        "extraction_engine": table.extraction_engine,
        "needs_review": table.needs_review,
        "review_reasons": table.review_reasons,
        "coordinate_transform": table.coordinate_transform,
        "unified_table": table.to_dict(),
    }
