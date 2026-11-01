from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

import pymupdf


@dataclass(frozen=True)
class RenderedPage:
    page_number: int
    page_count: int
    width: float
    height: float
    image_width: int
    image_height: int
    dpi: int
    image: Any


class PdfRenderer(Protocol):
    name: str

    def page_count(self, path: str | Path) -> int:
        ...

    def render_pages(
        self,
        path: str | Path,
        *,
        dpi: int = 200,
    ) -> Iterable[RenderedPage]:
        ...


def _pixmap_to_bgr(pixmap: pymupdf.Pixmap) -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("缺少 numpy，无法渲染 PDF 页面。") from exc

    array = np.frombuffer(pixmap.samples, dtype=np.uint8)
    array = array.reshape(pixmap.height, pixmap.width, pixmap.n)
    if pixmap.n == 4:
        array = array[:, :, :3]
    return np.ascontiguousarray(array[:, :, ::-1])


class PyMuPdfRenderer:
    """仅负责把 PDF 页面渲染为图像。

    该类刻意不调用 PyMuPDF 的文字提取、表格识别或文本块接口。
    """

    name = "PyMuPDF (render only)"

    def _open(self, path: str | Path) -> pymupdf.Document:
        source_path = Path(path).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"PDF 文件不存在: {source_path}")
        document = pymupdf.open(str(source_path))
        if document.needs_pass:
            document.close()
            raise ValueError("PDF 文件已加密，无法读取，请先解除密码保护。")
        return document

    def page_count(self, path: str | Path) -> int:
        document = self._open(path)
        try:
            return document.page_count
        finally:
            document.close()

    def render_pages(
        self,
        path: str | Path,
        *,
        dpi: int = 200,
    ) -> Iterable[RenderedPage]:
        document = self._open(path)
        try:
            total = document.page_count
            for page_index in range(total):
                page = document[page_index]
                pixmap = page.get_pixmap(dpi=dpi, alpha=False)
                yield RenderedPage(
                    page_number=page_index + 1,
                    page_count=total,
                    width=page.rect.width,
                    height=page.rect.height,
                    image_width=pixmap.width,
                    image_height=pixmap.height,
                    dpi=dpi,
                    image=_pixmap_to_bgr(pixmap),
                )
        finally:
            document.close()
