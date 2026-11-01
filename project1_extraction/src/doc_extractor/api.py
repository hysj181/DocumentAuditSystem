from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from doc_extractor.core.batch_io import (
    EXPORT_FORMATS,
    ensure_output_layout,
    export_batch,
    load_batch,
    load_batch_by_id,
    load_latest_batch,
    restore_batch,
    save_batch,
)
from doc_extractor.core.environmental_pipeline import extract_batch
from doc_extractor.core.extraction_batch import ExtractionBatch
from doc_extractor.core.pdf_parser import PARSE_MODE_LOCAL
from doc_extractor.core.paddle_structure import (
    PageStructureParser,
    ensure_paddle_cache_dir,
)
from doc_extractor.core.pdf_renderer import PdfRenderer


def extract_files(
    paths: Iterable[str | Path] | str | Path,
    *,
    structure_parser: PageStructureParser | None = None,
    renderer: PdfRenderer | None = None,
    structure_dpi: int = 200,
    mode: str = PARSE_MODE_LOCAL,
    cloud_client: Any | None = None,
    cloud_options: Any | None = None,
    request_timeout: float = 300.0,
    poll_timeout: float = 600.0,
    progress_callback=None,
) -> ExtractionBatch:
    ensure_paddle_cache_dir()
    if isinstance(paths, (str, Path)):
        path_list: list[str | Path] = [paths]
    else:
        path_list = list(paths)
    return extract_batch(
        path_list,
        structure_parser=structure_parser,
        renderer=renderer,
        structure_dpi=structure_dpi,
        mode=mode,
        cloud_client=cloud_client,
        cloud_options=cloud_options,
        request_timeout=request_timeout,
        poll_timeout=poll_timeout,
        progress_callback=progress_callback,
    )


def extract_file(path: str | Path, **kwargs: Any) -> ExtractionBatch:
    return extract_files([path], **kwargs)


def extract_and_save(
    paths: Iterable[str | Path] | str | Path,
    *,
    output_root: str | Path | None = None,
    formats: Iterable[str] = EXPORT_FORMATS,
    **kwargs: Any,
) -> tuple[ExtractionBatch, dict[str, Path]]:
    batch = extract_files(paths, **kwargs)
    outputs = save_batch(batch, output_root, formats=formats)
    return batch, outputs


__all__ = [
    "EXPORT_FORMATS",
    "ExtractionBatch",
    "ensure_output_layout",
    "export_batch",
    "extract_and_save",
    "extract_file",
    "extract_files",
    "load_batch",
    "load_batch_by_id",
    "load_latest_batch",
    "restore_batch",
    "save_batch",
]
