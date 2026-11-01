from __future__ import annotations

import logging
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from doc_extractor.core.device_status import local_device_status
from doc_extractor.core.models import (
    FILE_TYPE_PDF,
    DocumentResult,
    ExtractionRecord,
    Location,
)
from doc_extractor.core.paddle_structure import (
    ENGINE_NAME,
    PageStructureParser,
    PaddleStructureUnavailableError,
    StructurePageResult,
    get_paddle_structure_parser,
    paddle_structure_available,
)
from doc_extractor.core.patterns import entities_as_dicts
from doc_extractor.core.pdf_renderer import PdfRenderer, PyMuPdfRenderer, RenderedPage
from doc_extractor.core.table_models import (
    ParsedTable,
    TableData,
    table_record_metadata,
)

EXTRACTION_MODE_LOCAL = "local_gpu"

logger = logging.getLogger(__name__)

ENGINE_PADDLE = ENGINE_NAME
PDF_PARSE_ENGINE = "paddleocr"


class PaddlePdfParseError(RuntimeError):
    """PaddleOCR 单引擎 PDF 解析失败。"""


def _scale_bbox(
    bbox: list[float],
    *,
    image_width: int,
    image_height: int,
    page_width: float,
    page_height: float,
) -> list[float]:
    scale_x = page_width / image_width if image_width else 1.0
    scale_y = page_height / image_height if image_height else 1.0
    return [
        round(bbox[0] * scale_x, 3),
        round(bbox[1] * scale_y, 3),
        round(bbox[2] * scale_x, 3),
        round(bbox[3] * scale_y, 3),
    ]


def _make_table_data(
    *,
    parsed: ParsedTable,
    source_file: str,
    page: RenderedPage,
    page_table_index: int,
) -> TableData:
    table = TableData.from_parsed(
        parsed,
        source_file=source_file,
        page_number=page.page_number,
        table_id=f"p{page.page_number}-t{page_table_index}",
        extraction_engine=ENGINE_PADDLE,
        image_size=[page.image_width, page.image_height],
        pdf_size=[page.width, page.height],
        dpi=page.dpi,
    )
    table.metadata["extraction_mode"] = EXTRACTION_MODE_LOCAL
    table.metadata["extraction_engine"] = "PaddleOCR"
    return table


def _make_table_record(
    *,
    document_id: str,
    source_file: str,
    table_index: int,
    page: RenderedPage,
    page_table_index: int,
    table: TableData,
) -> ExtractionRecord:
    rows = table.grid()
    unified_metadata = table_record_metadata(table)
    cells: list[dict[str, Any]] = []
    for cell in unified_metadata["cells"]:
        item = dict(cell)
        item["entities"] = entities_as_dicts(item.get("text", ""))
        cells.append(item)

    table_text = "\n".join("\t".join(row) for row in rows)
    return ExtractionRecord(
        document_id=document_id,
        source_file=source_file,
        file_type=FILE_TYPE_PDF,
        content_type="table",
        text=table_text,
        location=Location(
            table_index=table_index,
            page_number=page.page_number,
            bbox=table.table_bbox,
        ),
        metadata={
            "source": "paddle_structure",
            "extraction_engine": ENGINE_PADDLE,
            "extraction_mode": EXTRACTION_MODE_LOCAL,
            "page_table_index": page_table_index,
            "row_count": table.rows,
            "column_count": table.columns,
            "rows": rows,
            "cells": cells,
            "entities": entities_as_dicts(table_text),
            "table_id": table.table_id,
            "extraction_engine": table.extraction_engine,
            "headers": table.headers,
            "header_row_count": table.header_row_count,
            "needs_review": table.needs_review,
            "review_reasons": table.review_reasons,
            "coordinate_transform": table.coordinate_transform,
            "unified_table": table.to_dict(),
        },
    )


def _add_page_records(
    *,
    page: RenderedPage,
    document_id: str,
    source_file: str,
    structure: StructurePageResult,
    records: list[ExtractionRecord],
) -> int:
    page_bbox = [0.0, 0.0, round(page.width, 3), round(page.height, 3)]
    lines = [line for line in structure.lines if line.text.strip()]
    lines.sort(key=lambda line: (line.bbox[1], line.bbox[0]))
    normalized_lines = [
        (line, unicodedata.normalize("NFKC", line.text)) for line in lines
    ]
    page_text = (
        "\n".join(text for _line, text in normalized_lines).strip()
        or unicodedata.normalize("NFKC", structure.text).strip()
    )

    records.append(
        ExtractionRecord(
            document_id=document_id,
            source_file=source_file,
            file_type=FILE_TYPE_PDF,
            content_type="ocr_page",
            text=page_text,
            location=Location(page_number=page.page_number, bbox=page_bbox),
            metadata={
                "source": "paddle_structure",
                "engine": structure.engine,
                "possible_error": True,
                "line_count": len(lines),
                "page_image_size": [page.image_width, page.image_height],
                "page_pdf_size": [page.width, page.height],
                "dpi": page.dpi,
                "entities": entities_as_dicts(page_text) if page_text else [],
            },
        )
    )

    for reading_order, (line, normalized_text) in enumerate(normalized_lines):
        pdf_bbox = _scale_bbox(
            line.bbox,
            image_width=page.image_width,
            image_height=page.image_height,
            page_width=page.width,
            page_height=page.height,
        )
        records.append(
            ExtractionRecord(
                document_id=document_id,
                source_file=source_file,
                file_type=FILE_TYPE_PDF,
                content_type="ocr_text",
                text=normalized_text,
                location=Location(
                    page_number=page.page_number,
                    bbox=pdf_bbox,
                    reading_order=reading_order,
                ),
                metadata={
                    "source": "paddle_structure",
                    "engine": structure.engine,
                    "confidence": line.confidence,
                    "possible_error": True,
                    "raw_text": line.text,
                    "entities": entities_as_dicts(normalized_text),
                },
            )
        )
    return len(lines)


def parse_pdf(
    path: str | Path,
    document_id: str | None = None,
    *,
    structure_parser: PageStructureParser | None = None,
    renderer: PdfRenderer | None = None,
    dpi: int = 200,
) -> DocumentResult:
    """使用 PaddleOCR PP-StructureV3 单引擎解析 PDF。

    页面图像由独立渲染器生成；本函数不会调用 RapidOCR，也不会调用
    PyMuPDF 的文字提取或表格识别接口。
    """

    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"PDF 文件不存在: {source_path}")

    document_id = document_id or uuid.uuid4().hex
    source_file = str(source_path)
    renderer = renderer or PyMuPdfRenderer()
    parser = structure_parser

    if parser is None:
        try:
            parser = get_paddle_structure_parser()
        except PaddleStructureUnavailableError as exc:
            logger.exception("PaddleOCR PP-StructureV3 初始化失败")
            return DocumentResult(
                document_id=document_id,
                source_file=source_file,
                file_type=FILE_TYPE_PDF,
                error=f"PaddleOCR PP-StructureV3 不可用：{exc}",
                warnings=["PDF 解析仅使用 PaddleOCR，未启用 RapidOCR 或 PyMuPDF 解析回退。"],
                metadata={
                    "parse_engine": PDF_PARSE_ENGINE,
                    "parser": ENGINE_PADDLE,
                    "extraction_engine": "PaddleOCR",
                    "extraction_mode": EXTRACTION_MODE_LOCAL,
                    "local_ocr_used": False,
                    "cloud_api_used": False,
                    "paddle_structure_available": paddle_structure_available(),
                    "rendering_engine": renderer.name,
                },
            )
        except Exception as exc:
            logger.exception("PaddleOCR PP-StructureV3 初始化异常")
            return DocumentResult(
                document_id=document_id,
                source_file=source_file,
                file_type=FILE_TYPE_PDF,
                error=f"PaddleOCR PP-StructureV3 初始化失败：{type(exc).__name__}: {exc}",
                warnings=["PDF 解析仅使用 PaddleOCR，未启用 RapidOCR 或 PyMuPDF 解析回退。"],
                metadata={
                    "parse_engine": PDF_PARSE_ENGINE,
                    "parser": ENGINE_PADDLE,
                    "extraction_engine": "PaddleOCR",
                    "extraction_mode": EXTRACTION_MODE_LOCAL,
                    "local_ocr_used": False,
                    "cloud_api_used": False,
                    "paddle_structure_available": paddle_structure_available(),
                    "rendering_engine": renderer.name,
                },
            )

    records: list[ExtractionRecord] = []
    warnings: list[str] = []
    errors: list[str] = []
    tables: list[TableData] = []
    table_index = 0
    engine_usage: dict[str, int] = {}
    table_engine_counts: dict[str, int] = {}

    try:
        page_count = renderer.page_count(source_path)
    except Exception:
        logger.exception("PDF 页面数量读取失败")
        raise

    structure_used = False
    ocr_used = False
    for page in renderer.render_pages(source_path, dpi=dpi):
        try:
            structure = parser.parse_page(
                page.image,
                source_file=source_file,
                page_number=page.page_number,
                image_size=(page.image_width, page.image_height),
                pdf_size=(page.width, page.height),
                dpi=page.dpi,
            )
        except Exception as exc:
            logger.exception(
                "第%s页 PaddleOCR PP-StructureV3 解析失败", page.page_number
            )
            message = (
                f"第{page.page_number}页 PaddleOCR PP-StructureV3 解析失败："
                f"{type(exc).__name__}: {exc}"
            )
            errors.append(message)
            warnings.append(message)
            continue

        structure_used = True
        engine_usage[structure.engine] = engine_usage.get(structure.engine, 0) + 1
        line_count = _add_page_records(
            page=page,
            document_id=document_id,
            source_file=source_file,
            structure=structure,
            records=records,
        )
        if line_count:
            ocr_used = True

        for page_table_index, parsed_table in enumerate(structure.tables):
            table_data = _make_table_data(
                parsed=parsed_table,
                source_file=source_file,
                page=page,
                page_table_index=page_table_index,
            )
            tables.append(table_data)
            table_engine_counts[table_data.extraction_engine] = (
                table_engine_counts.get(table_data.extraction_engine, 0) + 1
            )
            records.append(
                _make_table_record(
                    document_id=document_id,
                    source_file=source_file,
                    table_index=table_index,
                    page=page,
                    page_table_index=page_table_index,
                    table=table_data,
                )
            )
            table_index += 1

        for structure_warning in structure.warnings:
            warnings.append(f"第{page.page_number}页 {structure_warning}")

    if not structure_used and not errors:
        errors.append("PaddleOCR PP-StructureV3 未解析任何页面。")
    if errors:
        warnings.append("PDF 解析失败，未切换到 RapidOCR 或 PyMuPDF，请人工检查。")
        logger.error("PDF 解析存在错误: %s", "；".join(errors))

    metadata: dict[str, Any] = {
        "page_count": page_count,
        "table_count": table_index,
        "ocr_used": ocr_used,
        "parse_engine": PDF_PARSE_ENGINE,
        "parser": ENGINE_PADDLE,
        "extraction_engine": "PaddleOCR",
        "extraction_mode": EXTRACTION_MODE_LOCAL,
        "local_ocr_used": True,
        "cloud_api_used": False,
        "local_device": local_device_status(),
        "structure_used": structure_used,
        "paddle_structure_available": paddle_structure_available(),
        "rendering_engine": renderer.name,
        "engine_usage": engine_usage,
        "table_engine_counts": table_engine_counts,
        "dpi": dpi,
    }

    return DocumentResult(
        document_id=document_id,
        source_file=source_file,
        file_type=FILE_TYPE_PDF,
        records=records,
        warnings=warnings,
        error="；".join(errors) if errors else None,
        metadata=metadata,
        tables=tables,
    )
