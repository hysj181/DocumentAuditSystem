from __future__ import annotations

import logging
from collections.abc import Sequence

from PySide6.QtCore import QObject, QThread, Signal

from doc_extractor.core.environmental_pipeline import extract_batch
from doc_extractor.core.paddle_structure import PageStructureParser
from doc_extractor.core.pdf_parser import PARSE_MODE_LOCAL
from doc_extractor.core.pdf_renderer import PdfRenderer

logger = logging.getLogger(__name__)


class ExtractionWorker(QThread):
    progress = Signal(int, int, str)
    results_ready = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        paths: Sequence[str],
        parent: QObject | None = None,
        *,
        mode: str = PARSE_MODE_LOCAL,
        structure_parser: PageStructureParser | None = None,
        renderer: PdfRenderer | None = None,
        structure_dpi: int = 200,
        cloud_client=None,
        cloud_options=None,
        request_timeout: float = 300.0,
        poll_timeout: float = 600.0,
    ) -> None:
        super().__init__(parent)
        self._paths = list(paths)
        self._mode = mode
        self._structure_parser = structure_parser
        self._renderer = renderer
        self._structure_dpi = structure_dpi
        self._cloud_client = cloud_client
        self._cloud_options = cloud_options
        self._request_timeout = request_timeout
        self._poll_timeout = poll_timeout

    def _report_progress(self, current: int, total: int, message: str) -> None:
        self.progress.emit(current, total, message)

    def run(self) -> None:
        try:
            results = extract_batch(
                self._paths,
                mode=self._mode,
                structure_parser=self._structure_parser,
                renderer=self._renderer,
                structure_dpi=self._structure_dpi,
                cloud_client=self._cloud_client,
                cloud_options=self._cloud_options,
                request_timeout=self._request_timeout,
                poll_timeout=self._poll_timeout,
                progress_callback=self._report_progress,
            )
        except Exception as exc:
            logger.exception("提取任务失败")
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.results_ready.emit(results)
