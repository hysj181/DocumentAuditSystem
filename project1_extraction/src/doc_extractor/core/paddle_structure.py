from __future__ import annotations

import html as html_lib
import importlib.util
import os
import re
import threading
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol

from doc_extractor.core.table_models import (
    ParsedTable,
    TableCell,
    parsed_table_from_grid,
)

PADDLE_INSTALL_HINT = 'pip install "paddleocr>=3" "paddlepaddle>=3"'
ENGINE_NAME = "PaddleOCR PP-StructureV3"
LOW_CONFIDENCE_THRESHOLD = 0.75


class PaddleStructureError(RuntimeError):
    pass


class PaddleStructureUnavailableError(PaddleStructureError):
    pass


@dataclass
class StructureLine:
    text: str
    bbox: list[float]
    confidence: float | None = None


@dataclass
class StructurePageResult:
    tables: list[ParsedTable] = field(default_factory=list)
    text: str = ""
    lines: list[StructureLine] = field(default_factory=list)
    engine: str = ENGINE_NAME
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PageStructureParser(Protocol):
    name: str

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
        ...


def _has_ascii_path(path: Path | str) -> bool:
    return all(ord(character) < 128 for character in str(path))


def default_cache_dir() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    candidate = project_root / ".paddlex_cache"
    if _has_ascii_path(candidate):
        return candidate
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    return program_data / "DocumentAuditSystem" / "paddlex_cache"


def ensure_paddle_cache_dir() -> Path:
    """Paddle 原生推理在 Windows 上无法打开含中文的模型路径。

    在导入 PaddleOCR 前将模型缓存目录指向 ASCII 路径，避免
    ``Cannot open file ...inference.json`` 错误。
    """

    configured = os.environ.get("PADDLE_PDX_CACHE_HOME")
    if configured and _has_ascii_path(Path(configured)):
        return Path(configured)

    # 已配置路径可能来自其他测试环境且包含中文。Paddle 原生推理无法打开
    # 中文路径，即使文件存在也会报 Cannot open file。此时强制切换到 ASCII
    # 项目缓存目录。
    cache_dir = default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_dir)
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    return cache_dir


def paddle_structure_available() -> bool:
    return (
        importlib.util.find_spec("paddleocr") is not None
        and importlib.util.find_spec("paddle") is not None
    )


def paddle_structure_backend_name() -> str:
    if not paddle_structure_available():
        return "未安装 PaddleOCR/PaddlePaddle"
    try:
        import paddle
        import paddleocr
    except Exception as exc:
        return f"PaddleOCR 不可用：{type(exc).__name__}: {exc}"
    return f"PaddleOCR {paddleocr.__version__} / PaddlePaddle {paddle.__version__}"


class _TableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self.current_row: list[dict[str, Any]] | None = None
        self.current_cell: dict[str, Any] | None = None
        self.table_depth = 0
        self.saw_table = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            if self.saw_table:
                self.table_depth += 1
            else:
                self.saw_table = True
            return
        if not self.saw_table or self.table_depth > 0:
            return
        if tag == "tr":
            self.current_row = []
            self.rows.append(self.current_row)
            return
        if tag in {"td", "th"} and self.current_row is not None:
            attributes = {key.lower(): value for key, value in attrs}
            self.current_cell = {
                "text": "",
                "rowspan": _span_value(attributes.get("rowspan")),
                "colspan": _span_value(attributes.get("colspan")),
                "is_header": tag == "th",
            }
            self.current_row.append(self.current_cell)
            return
        if tag == "br" and self.current_cell is not None:
            self.current_cell["text"] += "\n"

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "table":
            if self.table_depth > 0:
                self.table_depth -= 1
            return
        if not self.saw_table or self.table_depth > 0:
            return
        if tag in {"td", "th"}:
            self.current_cell = None
        elif tag == "tr":
            self.current_row = None

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None and self.table_depth == 0:
            self.current_cell["text"] += data


def _span_value(value: Any) -> int:
    try:
        return max(1, int(str(value).strip()))
    except (TypeError, ValueError):
        return 1


def _clean_cell_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html_lib.unescape(str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    cleaned = "\n".join(line for line in lines if line).strip()
    return cleaned or None


def parse_html_table(html: str) -> tuple[list[TableCell], int, int] | None:
    if not html or "<td" not in html.casefold() and "<th" not in html.casefold():
        return None
    parser = _TableHtmlParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    if not parser.rows:
        return None

    row_count = len(parser.rows)
    occupancy: set[tuple[int, int]] = set()
    cells: list[TableCell] = []
    max_column = 0
    for row_index, raw_row in enumerate(parser.rows):
        column_index = 0
        for raw_cell in raw_row:
            while (row_index, column_index) in occupancy:
                column_index += 1
            row_span = max(1, int(raw_cell.get("rowspan", 1)))
            column_span = max(1, int(raw_cell.get("colspan", 1)))
            row_span = min(row_span, row_count - row_index)
            if row_span <= 0:
                continue
            text = _clean_cell_text(raw_cell.get("text"))
            cell = TableCell(
                row_index=row_index,
                column_index=column_index,
                text=text,
                row_span=row_span,
                column_span=column_span,
                is_header=bool(raw_cell.get("is_header", False)),
            )
            cells.append(cell)
            for rr in range(row_index, row_index + row_span):
                for cc in range(column_index, column_index + column_span):
                    occupancy.add((rr, cc))
            max_column = max(max_column, column_index + column_span)
            column_index += column_span

    if not cells or max_column <= 0:
        return None
    return cells, row_count, max_column


def _bbox_from_points(points: Any) -> list[float] | None:
    if points is None:
        return None
    try:
        if len(points) == 4 and not isinstance(points[0], (list, tuple)):
            return [float(value) for value in points]
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    except (TypeError, ValueError, IndexError):
        return None
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_union(boxes: list[list[float] | None]) -> list[float] | None:
    valid = [box for box in boxes if box and len(box) == 4]
    if not valid:
        return None
    return [
        min(box[0] for box in valid),
        min(box[1] for box in valid),
        max(box[2] for box in valid),
        max(box[3] for box in valid),
    ]


def _overlap_ratio(inner: list[float], outer: list[float]) -> float:
    if not inner or not outer or len(inner) != 4 or len(outer) != 4:
        return 0.0
    x0 = max(inner[0], outer[0])
    y0 = max(inner[1], outer[1])
    x1 = min(inner[2], outer[2])
    y1 = min(inner[3], outer[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = (x1 - x0) * (y1 - y0)
    inner_area = max(0.0, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    if inner_area <= 0:
        return 0.0
    return intersection / inner_area


def _assign_cell_confidence(
    cells: list[TableCell],
    ocr_lines: list[StructureLine],
) -> None:
    if not ocr_lines:
        return
    for cell in cells:
        if not cell.text or not cell.bbox:
            continue
        candidates: list[tuple[float, float, str]] = []
        for line in ocr_lines:
            if line.confidence is None:
                continue
            ratio = _overlap_ratio(line.bbox, cell.bbox)
            if ratio <= 0.15 and line.text not in cell.text:
                continue
            candidates.append((ratio, float(line.confidence), line.text))
        if not candidates:
            continue
        candidates.sort(
            key=lambda item: (
                0 if item[2] in (cell.text or "") else 1,
                -item[0],
                -item[1],
            )
        )
        cell.confidence = round(candidates[0][1], 4)


def _assign_cell_boxes(
    cells: list[TableCell],
    cell_boxes: list[Any] | None,
) -> tuple[int, int]:
    if not cell_boxes:
        return 0, len(cells)
    anchors = [cell for cell in cells]
    assigned = 0
    for index, cell in enumerate(anchors):
        if index >= len(cell_boxes):
            break
        bbox = _bbox_from_points(cell_boxes[index])
        if bbox is None:
            continue
        cell.bbox = bbox
        assigned += 1
    return assigned, len(anchors)


def _find_table_bbox(
    index: int,
    table_res: dict[str, Any],
    table_blocks: list[dict[str, Any]],
    layout_boxes: list[dict[str, Any]],
) -> list[float] | None:
    if index < len(table_blocks):
        bbox = _bbox_from_points(table_blocks[index].get("block_bbox"))
        if bbox:
            return bbox
    if index < len(layout_boxes):
        bbox = _bbox_from_points(layout_boxes[index].get("coordinate"))
        if bbox:
            return bbox
    region_box = _bbox_from_points(table_res.get("table_bbox"))
    if region_box:
        return region_box
    return _bbox_union(
        [
            box
            for box in (
                _bbox_from_points(item)
                for item in table_res.get("cell_box_list", []) or []
            )
            if box
        ]
    )


def _table_from_result(
    index: int,
    table_res: dict[str, Any],
    *,
    table_blocks: list[dict[str, Any]],
    layout_boxes: list[dict[str, Any]],
    ocr_lines: list[StructureLine],
) -> ParsedTable | None:
    data = table_res.get("res", table_res)
    if not isinstance(data, dict):
        return None
    html = data.get("pred_html")
    parsed_html = parse_html_table(html) if isinstance(html, str) else None
    table_bbox = _find_table_bbox(index, data, table_blocks, layout_boxes)
    review_reasons: list[str] = []

    if parsed_html is None:
        fallback_cells = _fallback_cells_from_ocr(data, ocr_lines)
        if not fallback_cells:
            return None
        grid = [
            [cell.text or "" for cell in row]
            for row in fallback_cells
        ]
        parsed = parsed_table_from_grid(
            grid,
            bbox=table_bbox,
            html=html if isinstance(html, str) else None,
            metadata={"fallback": "ocr_lines"},
        )
        parsed.review_reasons.append("html_table_parse_fallback")
        parsed.needs_review = True
        return parsed

    cells, row_count, column_count = parsed_html
    assigned, anchor_count = _assign_cell_boxes(
        cells, data.get("cell_box_list")
    )
    if assigned < anchor_count:
        review_reasons.append("cell_bbox_missing")
    if anchor_count and data.get("cell_box_list") is not None:
        if len(data.get("cell_box_list") or []) != anchor_count:
            review_reasons.append("cell_box_count_mismatch")

    _assign_cell_confidence(cells, ocr_lines)

    confidences = [
        cell.confidence for cell in cells if cell.confidence is not None
    ]
    table_confidence = (
        round(sum(confidences) / len(confidences), 4) if confidences else None
    )
    if any(
        cell.confidence is not None
        and cell.confidence < LOW_CONFIDENCE_THRESHOLD
        for cell in cells
    ):
        review_reasons.append("low_confidence_cell")
    if any((cell.row_span or 1) > 1 or (cell.column_span or 1) > 1 for cell in cells):
        review_reasons.append("merged_cells_detected")
    if table_bbox is None:
        review_reasons.append("missing_table_bbox")
    if not any((cell.text or "").strip() for cell in cells):
        review_reasons.append("empty_table")

    parsed = ParsedTable(
        cells=cells,
        row_count=row_count,
        column_count=column_count,
        bbox=table_bbox,
        html=html if isinstance(html, str) else None,
        confidence=table_confidence,
        needs_review=bool(review_reasons),
        review_reasons=list(dict.fromkeys(review_reasons)),
        metadata={
            "table_region_id": data.get("table_region_id"),
            "cell_box_count": len(data.get("cell_box_list") or []),
            "anchor_cell_count": anchor_count,
            "assigned_cell_boxes": assigned,
        },
    )
    parsed.finalize()
    if parsed.header_row_count == 0 and "no_header_detected" not in parsed.review_reasons:
        parsed.review_reasons.append("no_header_detected")
        parsed.needs_review = True
    return parsed


def _fallback_cells_from_ocr(
    data: dict[str, Any],
    ocr_lines: list[StructureLine],
) -> list[list[TableCell]] | None:
    ocr = data.get("table_ocr_pred")
    if not isinstance(ocr, dict):
        return None
    texts = ocr.get("rec_texts") or []
    boxes = ocr.get("rec_boxes") or []
    scores = ocr.get("rec_scores") or []
    entries: list[tuple[float, float, str, float | None]] = []
    for index, text in enumerate(texts):
        if index >= len(boxes):
            break
        bbox = _bbox_from_points(boxes[index])
        if not bbox:
            continue
        score = None
        if index < len(scores):
            try:
                score = float(scores[index])
            except (TypeError, ValueError):
                score = None
        entries.append((bbox[1], bbox[0], str(text), score))
    if not entries:
        return None
    entries.sort()
    rows: list[list[tuple[float, str, float | None]]] = []
    for y, x, text, score in entries:
        placed = False
        for row in rows:
            if abs(row[0][0] - y) <= 12:
                row.append((x, text, score))
                placed = True
                break
        if not placed:
            rows.append([(x, text, score)])
    grid: list[list[TableCell]] = []
    for row_index, row in enumerate(rows):
        row.sort(key=lambda item: item[0])
        grid.append(
            [
                TableCell(
                    row_index=row_index,
                    column_index=column_index,
                    text=text or None,
                    confidence=score,
                )
                for column_index, (_x, text, score) in enumerate(row)
            ]
        )
    return grid


def _ocr_lines_from_result(data: dict[str, Any]) -> list[StructureLine]:
    ocr = data.get("overall_ocr_res")
    if not isinstance(ocr, dict):
        return []
    texts = ocr.get("rec_texts") or []
    boxes = ocr.get("rec_boxes") or []
    scores = ocr.get("rec_scores") or []
    lines: list[StructureLine] = []
    for index, text in enumerate(texts):
        bbox = _bbox_from_points(boxes[index]) if index < len(boxes) else None
        if bbox is None:
            continue
        confidence = None
        if index < len(scores):
            try:
                confidence = round(float(scores[index]), 4)
            except (TypeError, ValueError):
                confidence = None
        lines.append(StructureLine(text=str(text), bbox=bbox, confidence=confidence))
    lines.sort(key=lambda line: (line.bbox[1], line.bbox[0]))
    return lines


def tables_from_ppstructure_result(
    data: dict[str, Any],
) -> tuple[list[ParsedTable], list[StructureLine], list[str]]:
    warnings: list[str] = []
    if not isinstance(data, dict):
        return [], [], ["PP-StructureV3 返回结果格式无法识别。"]

    ocr_lines = _ocr_lines_from_result(data)
    parsing_blocks = data.get("parsing_res_list") or []
    table_blocks = [
        block
        for block in parsing_blocks
        if isinstance(block, dict) and block.get("block_label") == "table"
    ]
    layout = data.get("layout_det_res") or {}
    layout_boxes = [
        box
        for box in (layout.get("boxes") or [])
        if isinstance(box, dict) and box.get("label") == "table"
    ]

    table_results = data.get("table_res_list") or []
    parsed_tables: list[ParsedTable] = []
    for index, table_res in enumerate(table_results):
        parsed = _table_from_result(
            index,
            table_res,
            table_blocks=table_blocks,
            layout_boxes=layout_boxes,
            ocr_lines=ocr_lines,
        )
        if parsed is not None:
            parsed_tables.append(parsed)

    if not parsed_tables and table_blocks:
        for index, block in enumerate(table_blocks):
            html = block.get("block_content")
            parsed_html = parse_html_table(html) if isinstance(html, str) else None
            if parsed_html is None:
                continue
            cells, row_count, column_count = parsed_html
            parsed = ParsedTable(
                cells=cells,
                row_count=row_count,
                column_count=column_count,
                bbox=_bbox_from_points(block.get("block_bbox")),
                html=html,
                needs_review=True,
                review_reasons=["cell_bbox_missing"],
                metadata={"source": "parsing_res_list"},
            )
            parsed.finalize()
            parsed_tables.append(parsed)

    if not parsed_tables:
        warnings.append("PP-StructureV3 未检测到表格区域。")
    return parsed_tables, ocr_lines, warnings


class PaddleStructureParser:
    name = ENGINE_NAME

    def __init__(self, **kwargs: Any) -> None:
        ensure_paddle_cache_dir()
        try:
            from paddleocr import PPStructureV3
        except ImportError as exc:
            raise PaddleStructureUnavailableError(
                f"未安装 PaddleOCR 3.x。可执行：{PADDLE_INSTALL_HINT}"
            ) from exc
        except Exception as exc:
            raise PaddleStructureUnavailableError(
                f"PaddleOCR 导入失败：{type(exc).__name__}: {exc}"
            ) from exc

        options: dict[str, Any] = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "use_seal_recognition": False,
            "use_formula_recognition": False,
            "use_chart_recognition": False,
            "use_region_detection": False,
            "use_table_recognition": True,
            "enable_mkldnn": False,
        }
        options.update(kwargs)
        try:
            self._pipeline = PPStructureV3(**options)
        except Exception as exc:
            raise PaddleStructureUnavailableError(
                f"PP-StructureV3 初始化失败：{type(exc).__name__}: {exc}"
            ) from exc

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
        array = _to_bgr_array(image)
        try:
            results = self._pipeline.predict(
                array,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                use_seal_recognition=False,
                use_formula_recognition=False,
                use_chart_recognition=False,
                use_region_detection=False,
                use_table_recognition=True,
            )
        except Exception as exc:
            raise PaddleStructureError(
                f"PP-StructureV3 推理失败：{type(exc).__name__}: {exc}"
            ) from exc

        if not results:
            return StructurePageResult(
                engine=ENGINE_NAME,
                warnings=["PP-StructureV3 未返回结果。"],
                metadata={"source_file": source_file, "page_number": page_number},
            )

        first = results[0]
        try:
            payload = first.json
        except Exception:
            payload = first
        if isinstance(payload, dict) and "res" in payload:
            payload = payload["res"]
        if not isinstance(payload, dict):
            raise PaddleStructureError("PP-StructureV3 返回结果格式无法识别。")

        tables, lines, warnings = tables_from_ppstructure_result(payload)
        text = "\n".join(line.text for line in lines).strip()
        if not text:
            text = "\n".join(
                str(block.get("block_content", ""))
                for block in payload.get("parsing_res_list") or []
                if isinstance(block, dict)
                and block.get("block_label") != "table"
                and block.get("block_content")
            ).strip()

        width = payload.get("width")
        height = payload.get("height")
        metadata = {
            "source_file": source_file,
            "page_number": page_number,
            "page_index": payload.get("page_index"),
            "width": width,
            "height": height,
            "image_size": image_size,
            "pdf_size": pdf_size,
            "dpi": dpi,
            "model_settings": payload.get("model_settings", {}),
            "table_count": len(tables),
        }
        if not tables:
            warnings.append("未识别到表格结构，已保留 OCR 文本。")
        return StructurePageResult(
            tables=tables,
            text=text,
            lines=lines,
            engine=ENGINE_NAME,
            warnings=warnings,
            metadata=metadata,
        )


def _to_bgr_array(image: Any) -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise PaddleStructureError("缺少 numpy，无法执行 PaddleOCR 推理。") from exc

    if isinstance(image, np.ndarray):
        array = image
    elif isinstance(image, (bytes, bytearray, memoryview)):
        try:
            from io import BytesIO

            from PIL import Image
        except ImportError as exc:
            raise PaddleStructureError("缺少 Pillow，无法解析页面图像。") from exc
        with Image.open(BytesIO(bytes(image))) as pillow_image:
            rgb = np.array(pillow_image.convert("RGB"))
        array = np.ascontiguousarray(rgb[:, :, ::-1])
    else:
        raise PaddleStructureError(
            f"不支持的页面图像类型：{type(image).__name__}，需要 numpy.ndarray 或 PNG 字节。"
        )

    if array.ndim == 2:
        array = np.stack([array] * 3, axis=-1)
    if array.ndim != 3 or array.shape[2] < 3:
        raise PaddleStructureError(f"页面图像数组维度不正确：{array.shape}")
    if array.shape[2] == 4:
        array = array[:, :, :3]
    return np.ascontiguousarray(array)


_ENGINE: PaddleStructureParser | None = None
_ENGINE_LOCK = threading.Lock()


def get_paddle_structure_parser() -> PaddleStructureParser:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = PaddleStructureParser()
        return _ENGINE


def reset_paddle_structure_parser() -> None:
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None


def paddle_structure_parser_loaded() -> bool:
    return _ENGINE is not None
