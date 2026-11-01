from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from doc_extractor.core.models import (
    FILE_TYPE_PDF,
    FILE_TYPE_WORD,
    DocumentResult,
)
from doc_extractor.core.paddle_structure import PageStructureParser
from doc_extractor.core.pdf_parser import PARSE_MODE_LOCAL, parse_pdf
from doc_extractor.core.pdf_renderer import PdfRenderer
from doc_extractor.core.word_parser import parse_word

ProgressCallback = Callable[[int, int, str], None]
logger = logging.getLogger(__name__)


def detect_file_type(path: str | Path) -> str | None:
    suffix = Path(path).suffix.casefold()
    if suffix == ".docx":
        return FILE_TYPE_WORD
    if suffix == ".pdf":
        return FILE_TYPE_PDF
    return None


def extract_document(
    path: str | Path,
    *,
    structure_parser: PageStructureParser | None = None,
    renderer: PdfRenderer | None = None,
    structure_dpi: int = 200,
    mode: str = PARSE_MODE_LOCAL,
    cloud_client=None,
    cloud_options=None,
    request_timeout: float = 300.0,
    poll_timeout: float = 600.0,
) -> DocumentResult:
    source_path = Path(path).expanduser().resolve()
    source_file = str(source_path)
    file_type = detect_file_type(source_path) or (
        source_path.suffix.lstrip(".").casefold() or "unknown"
    )
    document_id = uuid.uuid4().hex

    if not source_path.is_file():
        return DocumentResult(
            document_id=document_id,
            source_file=source_file,
            file_type=file_type,
            error=f"文件不存在: {source_file}",
        )

    if file_type not in {FILE_TYPE_WORD, FILE_TYPE_PDF}:
        return DocumentResult(
            document_id=document_id,
            source_file=source_file,
            file_type=file_type,
            error=(
                f"不支持的文件类型: {source_path.suffix or '(无扩展名)'}，"
                "仅支持 .docx 和 .pdf"
            ),
        )

    try:
        if file_type == FILE_TYPE_WORD:
            result = parse_word(source_path, document_id=document_id)
        else:
            result = parse_pdf(
                source_path,
                document_id=document_id,
                structure_parser=structure_parser,
                renderer=renderer,
                dpi=structure_dpi,
                mode=mode,
                cloud_client=cloud_client,
                cloud_options=cloud_options,
                request_timeout=request_timeout,
                poll_timeout=poll_timeout,
            )
        if result.error:
            logger.error("文档解析失败 %s: %s", source_file, result.error)
        return result
    except Exception as exc:
        logger.exception("文档解析异常 %s", source_file)
        return DocumentResult(
            document_id=document_id,
            source_file=source_file,
            file_type=file_type,
            error=f"{type(exc).__name__}: {exc}",
        )


def extract_documents(
    paths: Iterable[str | Path],
    *,
    structure_parser: PageStructureParser | None = None,
    renderer: PdfRenderer | None = None,
    structure_dpi: int = 200,
    mode: str = PARSE_MODE_LOCAL,
    cloud_client=None,
    cloud_options=None,
    request_timeout: float = 300.0,
    poll_timeout: float = 600.0,
    progress_callback: ProgressCallback | None = None,
) -> list[DocumentResult]:
    if isinstance(paths, (str, Path)):
        path_list = [Path(paths)]
    else:
        path_list = [Path(path) for path in paths]
    total = len(path_list)
    results: list[DocumentResult] = []

    for index, path in enumerate(path_list, start=1):
        if progress_callback is not None:
            progress_callback(index - 1, total, f"正在提取: {path.name}")
        results.append(
            extract_document(
                path,
                structure_parser=structure_parser,
                renderer=renderer,
                structure_dpi=structure_dpi,
                mode=mode,
                cloud_client=cloud_client,
                cloud_options=cloud_options,
                request_timeout=request_timeout,
                poll_timeout=poll_timeout,
            )
        )
        if progress_callback is not None:
            progress_callback(index, total, f"已处理: {path.name}")

    return results
