from __future__ import annotations

import importlib.util
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Protocol

import pymupdf

from doc_extractor.core.models import (
    FILE_TYPE_PDF,
    DocumentResult,
    ExtractionRecord,
    Location,
)
from doc_extractor.core.paddle_structure import (
    ENGINE_NAME,
    StructureLine,
    tables_from_ppstructure_result,
)
from doc_extractor.core.patterns import entities_as_dicts
from doc_extractor.core.table_models import (
    ParsedTable,
    TableData,
    parsed_table_from_grid,
    table_record_metadata,
)

logger = logging.getLogger(__name__)

EXTRACTION_MODE_CLOUD = "cloud_api"
CLOUD_ENGINE = ENGINE_NAME
TOKEN_ENV_VAR = "PADDLEOCR_ACCESS_TOKEN"


class CloudApiError(RuntimeError):
    pass


class CloudApiUnavailableError(CloudApiError):
    pass


class CloudApiTokenMissingError(CloudApiUnavailableError):
    pass


class CloudClientProtocol(Protocol):
    def parse_document(self, **kwargs: Any) -> Any:
        ...


def cloud_api_status() -> dict[str, Any]:
    token_configured = bool(os.environ.get(TOKEN_ENV_VAR, "").strip())
    # 只检查顶层包，避免 find_spec 子模块时提前导入 paddleocr/paddlex，
    # 从而在模型缓存路径修正前锁定错误的中文缓存目录。
    client_available = (
        importlib.util.find_spec("paddleocr") is not None
        and importlib.util.find_spec("requests") is not None
    )
    if not client_available:
        text = "PaddleOCR 官方 API 客户端不可用"
    elif token_configured:
        text = "Token 已配置（未验证连接）"
    else:
        text = "Token 未配置"
    return {
        "token_configured": token_configured,
        "client_available": client_available,
        "status": text,
    }


def token_configured() -> bool:
    return bool(os.environ.get(TOKEN_ENV_VAR, "").strip())


def create_cloud_client(
    *,
    request_timeout: float = 300.0,
    poll_timeout: float = 600.0,
) -> CloudClientProtocol:
    if not token_configured():
        raise CloudApiTokenMissingError(
            f"未配置 {TOKEN_ENV_VAR}。请通过系统环境变量配置 PaddleOCR 访问令牌；"
            "程序不会读取、输出或记录 Token 内容。"
        )
    try:
        from paddleocr._api_client.client import PaddleOCRClient
    except ImportError as exc:
        raise CloudApiUnavailableError(
            "当前环境缺少 PaddleOCR 官方云端 API 客户端。请安装 paddleocr>=3.7。"
        ) from exc
    except Exception as exc:
        raise CloudApiUnavailableError(
            f"PaddleOCR 云端 API 客户端初始化失败：{type(exc).__name__}: {exc}"
        ) from exc
    try:
        return PaddleOCRClient(
            request_timeout=request_timeout,
            poll_timeout=poll_timeout,
            client_platform="DocumentAuditSystem/project1_extraction",
        )
    except Exception as exc:
        raise CloudApiUnavailableError(
            f"PaddleOCR 云端 API 客户端创建失败：{type(exc).__name__}: {exc}"
        ) from exc


def _cloud_options() -> Any:
    try:
        from paddleocr._api_client.models import PPStructureV3Options
    except ImportError as exc:
        raise CloudApiUnavailableError(
            "当前 PaddleOCR 版本不包含 PP-StructureV3 云端 API 选项。"
        ) from exc
    return PPStructureV3Options(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_seal_recognition=False,
        use_formula_recognition=False,
        use_chart_recognition=False,
        use_region_detection=False,
        use_table_recognition=True,
        use_table_orientation_classify=False,
        use_ocr_results_with_table_cells=True,
    )


def _snake_case_key(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()


def _normalize_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            _snake_case_key(str(key)): _normalize_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_keys(item) for item in value]
    return value


def _pdf_page_sizes(path: Path) -> list[tuple[int, float, float]]:
    with pymupdf.open(str(path)) as document:
        if document.needs_pass:
            raise ValueError("PDF 文件已加密，无法读取，请先解除密码保护。")
        return [
            (index + 1, document[index].rect.width, document[index].rect.height)
            for index in range(document.page_count)
        ]


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


def _make_table_record(
    *,
    document_id: str,
    source_file: str,
    table_index: int,
    page_number: int,
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
            page_number=page_number,
            bbox=table.table_bbox,
        ),
        metadata={
            "source": "paddle_cloud_api",
            "extraction_engine": CLOUD_ENGINE,
            "extraction_mode": EXTRACTION_MODE_CLOUD,
            "page_table_index": page_table_index,
            "row_count": table.rows,
            "column_count": table.columns,
            "rows": rows,
            "cells": cells,
            "entities": entities_as_dicts(table_text),
            "table_id": table.table_id,
            "headers": table.headers,
            "header_row_count": table.header_row_count,
            "needs_review": table.needs_review,
            "review_reasons": table.review_reasons,
            "coordinate_transform": table.coordinate_transform,
            "unified_table": table.to_dict(),
        },
    )


def _markdown_table_rows(markdown: str) -> list[list[list[str]]]:
    lines = markdown.splitlines()
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    separator = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")

    def flush() -> None:
        nonlocal current
        if len(current) >= 2:
            tables.append(current)
        current = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if separator.match(stripped):
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            current.append(cells)
        else:
            flush()
    flush()
    return tables


def _markdown_text_lines(markdown: str) -> list[str]:
    lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        if stripped:
            lines.append(stripped)
    return lines


def _cloud_page_content(
    *,
    page: Any,
    page_number: int,
    page_width: float,
    page_height: float,
    source_file: str,
    document_id: str,
    table_index_start: int,
) -> tuple[list[ExtractionRecord], list[TableData], int]:
    records: list[ExtractionRecord] = []
    tables: list[TableData] = []
    table_index = table_index_start
    pruned = _normalize_keys(getattr(page, "pruned_result", None) or {})
    markdown = str(getattr(page, "markdown_text", "") or "").strip()

    image_width = int(pruned.get("width") or 0) if isinstance(pruned, dict) else 0
    image_height = int(pruned.get("height") or 0) if isinstance(pruned, dict) else 0
    has_image_size = image_width > 0 and image_height > 0

    parsed_tables: list[ParsedTable] = []
    lines: list[StructureLine] = []
    warnings: list[str] = []
    if isinstance(pruned, dict) and pruned:
        try:
            parsed_tables, lines, warnings = tables_from_ppstructure_result(pruned)
        except Exception as exc:
            warnings.append(f"云端 prunedResult 解析失败：{type(exc).__name__}: {exc}")

    markdown_tables = _markdown_table_rows(markdown)
    if not parsed_tables and markdown_tables:
        for rows in markdown_tables:
            parsed = parsed_table_from_grid(
                rows,
                bbox=None,
                metadata={"source": "cloud_markdown"},
            )
            parsed.review_reasons.append("cloud_markdown_table")
            parsed.needs_review = True
            parsed_tables.append(parsed)

    for page_table_index, parsed_table in enumerate(parsed_tables):
        table = TableData.from_parsed(
            parsed_table,
            source_file=source_file,
            page_number=page_number,
            table_id=f"p{page_number}-t{page_table_index}",
            extraction_engine=CLOUD_ENGINE,
            image_size=[image_width, image_height] if has_image_size else None,
            pdf_size=[page_width, page_height] if has_image_size else None,
            dpi=None,
            coordinate_transform={
                "mode": EXTRACTION_MODE_CLOUD,
                "cloud_image_size": [image_width, image_height]
                if has_image_size
                else None,
            },
        )
        table.metadata["extraction_mode"] = EXTRACTION_MODE_CLOUD
        table.metadata["extraction_engine"] = "PaddleOCR"
        if not has_image_size:
            table.coordinate_space = "cloud"
            table.review_reasons.append("cloud_coordinates_unknown")
            table.needs_review = True
        tables.append(table)
        records.append(
            _make_table_record(
                document_id=document_id,
                source_file=source_file,
                table_index=table_index,
                page_number=page_number,
                page_table_index=page_table_index,
                table=table,
            )
        )
        table_index += 1

    page_text = markdown or "\n".join(line.text for line in lines).strip()
    records.append(
        ExtractionRecord(
            document_id=document_id,
            source_file=source_file,
            file_type=FILE_TYPE_PDF,
            content_type="ocr_page",
            text=page_text,
            location=Location(
                page_number=page_number,
                bbox=[0.0, 0.0, round(page_width, 3), round(page_height, 3)],
            ),
            metadata={
                "source": "paddle_cloud_api",
                "engine": CLOUD_ENGINE,
                "extraction_mode": EXTRACTION_MODE_CLOUD,
                "possible_error": True,
                "line_count": len(lines) if lines else len(_markdown_text_lines(markdown)),
                "warnings": warnings,
                "entities": entities_as_dicts(page_text) if page_text else [],
            },
        )
    )

    if lines:
        for reading_order, line in enumerate(lines):
            if has_image_size:
                pdf_bbox = _scale_bbox(
                    line.bbox,
                    image_width=image_width,
                    image_height=image_height,
                    page_width=page_width,
                    page_height=page_height,
                )
            else:
                pdf_bbox = None
            records.append(
                ExtractionRecord(
                    document_id=document_id,
                    source_file=source_file,
                    file_type=FILE_TYPE_PDF,
                    content_type="ocr_text",
                    text=line.text,
                    location=Location(
                        page_number=page_number,
                        bbox=pdf_bbox,
                        reading_order=reading_order,
                    ),
                    metadata={
                        "source": "paddle_cloud_api",
                        "engine": CLOUD_ENGINE,
                        "extraction_mode": EXTRACTION_MODE_CLOUD,
                        "confidence": line.confidence,
                        "possible_error": True,
                        "entities": entities_as_dicts(line.text),
                    },
                )
            )
    else:
        for reading_order, text in enumerate(_markdown_text_lines(markdown)):
            records.append(
                ExtractionRecord(
                    document_id=document_id,
                    source_file=source_file,
                    file_type=FILE_TYPE_PDF,
                    content_type="ocr_text",
                    text=text,
                    location=Location(
                        page_number=page_number,
                        bbox=None,
                        reading_order=reading_order,
                    ),
                    metadata={
                        "source": "paddle_cloud_api",
                        "engine": CLOUD_ENGINE,
                        "extraction_mode": EXTRACTION_MODE_CLOUD,
                        "confidence": None,
                        "possible_error": True,
                        "entities": entities_as_dicts(text),
                    },
                )
            )

    return records, tables, table_index


def parse_pdf_cloud(
    path: str | Path,
    document_id: str | None = None,
    *,
    client: CloudClientProtocol | None = None,
    options: Any | None = None,
    request_timeout: float = 300.0,
    poll_timeout: float = 600.0,
) -> DocumentResult:
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"PDF 文件不存在: {source_path}")

    document_id = document_id or uuid.uuid4().hex
    source_file = str(source_path)
    metadata: dict[str, Any] = {
        "parse_engine": "cloud_api",
        "parser": f"{CLOUD_ENGINE} (Cloud API)",
        "extraction_engine": "PaddleOCR",
        "extraction_mode": EXTRACTION_MODE_CLOUD,
        "cloud_api_used": True,
        "local_ocr_used": False,
    }

    try:
        page_sizes = _pdf_page_sizes(source_path)
    except Exception as exc:
        return DocumentResult(
            document_id=document_id,
            source_file=source_file,
            file_type=FILE_TYPE_PDF,
            error=f"PDF 页面信息读取失败：{type(exc).__name__}: {exc}",
            metadata=metadata,
        )

    if client is None:
        try:
            client = create_cloud_client(
                request_timeout=request_timeout,
                poll_timeout=poll_timeout,
            )
        except CloudApiError as exc:
            logger.error("PaddleOCR 云端 API 不可用: %s", exc)
            return DocumentResult(
                document_id=document_id,
                source_file=source_file,
                file_type=FILE_TYPE_PDF,
                error=str(exc),
                warnings=["云端 API 模式未调用本地 PaddleOCR，也不会自动切换模式。"],
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("PaddleOCR 云端 API 初始化异常")
            return DocumentResult(
                document_id=document_id,
                source_file=source_file,
                file_type=FILE_TYPE_PDF,
                error=f"PaddleOCR 云端 API 初始化失败：{type(exc).__name__}: {exc}",
                warnings=["云端 API 模式未调用本地 PaddleOCR，也不会自动切换模式。"],
                metadata=metadata,
            )

    try:
        cloud_options = options if options is not None else _cloud_options()
        result = client.parse_document(
            model="PP-StructureV3",
            file_path=str(source_path),
            options=cloud_options,
        )
    except Exception as exc:
        logger.exception("PaddleOCR 云端 API 解析失败")
        return DocumentResult(
            document_id=document_id,
            source_file=source_file,
            file_type=FILE_TYPE_PDF,
            error=f"PaddleOCR 云端 API 解析失败：{type(exc).__name__}: {exc}",
            warnings=["云端 API 失败，未切换到本地 PaddleOCR，请检查 Token、网络和服务状态。"],
            metadata=metadata,
        )

    pages = list(getattr(result, "pages", []) or [])
    if not pages:
        return DocumentResult(
            document_id=document_id,
            source_file=source_file,
            file_type=FILE_TYPE_PDF,
            error="PaddleOCR 云端 API 未返回页面结果。",
            warnings=["未生成替代解析结果，请人工检查。"],
            metadata=metadata,
        )

    records: list[ExtractionRecord] = []
    tables: list[TableData] = []
    warnings: list[str] = []
    table_index = 0
    for index, page in enumerate(pages):
        page_number = index + 1
        if index < len(page_sizes):
            _num, page_width, page_height = page_sizes[index]
        else:
            page_width = float(getattr(page, "width", 0) or 0)
            page_height = float(getattr(page, "height", 0) or 0)
        page_records, page_tables, table_index = _cloud_page_content(
            page=page,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            source_file=source_file,
            document_id=document_id,
            table_index_start=table_index,
        )
        records.extend(page_records)
        tables.extend(page_tables)

    if len(pages) != len(page_sizes):
        warnings.append(
            f"云端返回页数 {len(pages)} 与本地 PDF 页数 {len(page_sizes)} 不一致，"
            "请人工核对缺失页面。"
        )
    metadata.update(
        {
            "page_count": len(pages),
            "expected_page_count": len(page_sizes),
            "table_count": len(tables),
            "ocr_used": any(record.content_type == "ocr_text" for record in records),
            "cloud_job_id": getattr(result, "job_id", None),
            "cloud_model": "PP-StructureV3",
        }
    )
    if any(table.needs_review for table in tables):
        warnings.append("云端返回的部分表格需要人工核实。")
    return DocumentResult(
        document_id=document_id,
        source_file=source_file,
        file_type=FILE_TYPE_PDF,
        records=records,
        warnings=warnings,
        metadata=metadata,
        tables=tables,
    )
