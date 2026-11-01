from __future__ import annotations

import os
from pathlib import Path

import pymupdf
import pytest

from doc_extractor.core.paddle_structure import paddle_structure_available
from doc_extractor.core.pdf_parser import parse_pdf
from table_test_support import make_native_environment_pdf

REAL_PADDLE_ENABLED = (
    os.environ.get("RUN_PADDLE_STRUCTURE_TESTS", "").strip() == "1"
)


def _render_pdf_to_image_only_pdf(source: Path, target: Path) -> Path:
    with pymupdf.open(source) as document:
        page = document[0]
        pixmap = page.get_pixmap(dpi=200, alpha=False)
        width = page.rect.width
        height = page.rect.height
    scanned = pymupdf.open()
    scanned_page = scanned.new_page(width=width, height=height)
    scanned_page.insert_image(scanned_page.rect, stream=pixmap.tobytes("png"))
    scanned.save(target)
    scanned.close()
    return target


@pytest.mark.skipif(
    not REAL_PADDLE_ENABLED or not paddle_structure_available(),
    reason="设置 RUN_PADDLE_STRUCTURE_TESTS=1 且安装 PaddleOCR 后运行真实模型测试",
)
def test_real_ppstructure_recognizes_scanned_table(tmp_path: Path) -> None:
    native = make_native_environment_pdf(tmp_path / "native.pdf")
    scanned = _render_pdf_to_image_only_pdf(
        native, tmp_path / "scanned_table.pdf"
    )

    result = parse_pdf(scanned, dpi=200)

    assert result.error is None
    assert result.metadata["parse_engine"] == "paddleocr"
    assert result.metadata["structure_used"] is True
    assert result.metadata["table_count"] >= 1
    assert result.tables

    combined = "\n".join(
        cell.text or "" for table in result.tables for cell in table.cells
    )
    assert "COD" in combined or "45.2" in combined
    assert any(table.needs_review is not None for table in result.tables)
