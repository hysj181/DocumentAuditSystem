"""PDF 解析统一入口：本地 PaddleOCR 与云端 PaddleOCR API 双模式。

两种模式都使用 PP-StructureV3，并返回统一的 DocumentResult / TableData。
Word 文档不经过本模块。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from doc_extractor.core.cloud_api_parser import (
    CloudApiError,
    CloudApiTokenMissingError,
    CloudApiUnavailableError,
    CloudClientProtocol,
    cloud_api_status,
    parse_pdf_cloud,
    token_configured,
)
from doc_extractor.core.paddle_pdf_parser import (
    ENGINE_PADDLE,
    PDF_PARSE_ENGINE,
    PaddlePdfParseError,
    parse_pdf as parse_pdf_local,
)
from doc_extractor.core.paddle_structure import PageStructureParser
from doc_extractor.core.pdf_renderer import PdfRenderer

PARSE_MODE_LOCAL = "local_gpu"
PARSE_MODE_CLOUD = "cloud_api"
PARSE_MODES = (PARSE_MODE_LOCAL, PARSE_MODE_CLOUD)

PARSE_ENGINE_PADDLE = PDF_PARSE_ENGINE
PARSE_ENGINES = (PARSE_ENGINE_PADDLE,)


def parse_pdf(
    path: str | Path,
    document_id: str | None = None,
    *,
    mode: str = PARSE_MODE_LOCAL,
    structure_parser: PageStructureParser | None = None,
    renderer: PdfRenderer | None = None,
    dpi: int = 200,
    cloud_client: CloudClientProtocol | None = None,
    cloud_options: Any | None = None,
    request_timeout: float = 300.0,
    poll_timeout: float = 600.0,
):
    if mode == PARSE_MODE_LOCAL:
        return parse_pdf_local(
            path,
            document_id=document_id,
            structure_parser=structure_parser,
            renderer=renderer,
            dpi=dpi,
        )
    if mode == PARSE_MODE_CLOUD:
        return parse_pdf_cloud(
            path,
            document_id=document_id,
            client=cloud_client,
            options=cloud_options,
            request_timeout=request_timeout,
            poll_timeout=poll_timeout,
        )
    raise ValueError(
        f"不支持的 PDF 解析模式: {mode}，可选 {', '.join(PARSE_MODES)}"
    )


__all__ = [
    "ENGINE_PADDLE",
    "PARSE_ENGINE_PADDLE",
    "PARSE_ENGINES",
    "PARSE_MODE_CLOUD",
    "PARSE_MODE_LOCAL",
    "PARSE_MODES",
    "PDF_PARSE_ENGINE",
    "PaddlePdfParseError",
    "CloudApiError",
    "CloudApiTokenMissingError",
    "CloudApiUnavailableError",
    "cloud_api_status",
    "token_configured",
    "parse_pdf",
]
