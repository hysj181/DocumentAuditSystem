from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest

from doc_extractor.core import paddle_pdf_parser, pdf_renderer
from doc_extractor.core.extractor import extract_document
from doc_extractor.core.paddle_pdf_parser import parse_pdf
from doc_extractor.core.paddle_structure import (
    PaddleStructureUnavailableError,
    StructureLine,
    StructurePageResult,
)


class RecordingPaddleParser:
    name = "Fake PaddleOCR PP-StructureV3"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "page_number": page_number,
                "image_shape": getattr(image, "shape", None),
                "image_size": image_size,
                "pdf_size": pdf_size,
                "dpi": dpi,
            }
        )
        if self.fail:
            raise RuntimeError("模拟 PaddleOCR 推理失败")
        return StructurePageResult(
            text=f"PAGE{page_number} 示例文字",
            lines=[
                StructureLine(
                    text=f"PAGE{page_number} 示例文字",
                    bbox=[100.0, 100.0, 400.0, 200.0],
                    confidence=0.95,
                )
            ],
            engine=self.name,
        )


def test_scanned_pdf_uses_injected_paddle_and_keeps_page_coordinates(
    scanned_pdf_file: Path,
) -> None:
    parser = RecordingPaddleParser()
    result = parse_pdf(scanned_pdf_file, structure_parser=parser)

    assert result.error is None
    assert result.metadata["structure_used"] is True
    assert result.metadata["ocr_used"] is True
    assert result.metadata["parse_engine"] == "paddleocr"
    assert result.metadata["engine_usage"] == {parser.name: 1}
    assert len(parser.calls) == 1

    ocr_pages = [record for record in result.records if record.content_type == "ocr_page"]
    ocr_lines = [record for record in result.records if record.content_type == "ocr_text"]
    assert len(ocr_pages) == 1
    assert len(ocr_lines) == 1
    assert ocr_lines[0].location.page_number == 1
    assert ocr_lines[0].location.bbox is not None
    assert 0 <= ocr_lines[0].location.bbox[0] < ocr_lines[0].location.bbox[2] <= 600
    assert 0 <= ocr_lines[0].location.bbox[1] < ocr_lines[0].location.bbox[3] <= 300
    assert ocr_lines[0].metadata["source"] == "paddle_structure"
    assert ocr_lines[0].metadata["possible_error"] is True


def test_text_pdf_also_uses_paddle_engine(pdf_file: Path) -> None:
    parser = RecordingPaddleParser()
    result = parse_pdf(pdf_file, structure_parser=parser)

    assert result.error is None
    assert result.metadata["page_count"] == 2
    assert result.metadata["structure_used"] is True
    assert [call["page_number"] for call in parser.calls] == [1, 2]
    page_records = [
        record for record in result.records if record.content_type == "ocr_page"
    ]
    assert len(page_records) == 2
    assert "PAGE1" in page_records[0].text
    assert "PAGE2" in page_records[1].text


def test_paddle_failure_returns_error_without_fallback(scanned_pdf_file: Path) -> None:
    parser = RecordingPaddleParser(fail=True)
    result = parse_pdf(scanned_pdf_file, structure_parser=parser)

    assert result.error is not None
    assert "PaddleOCR" in result.error
    assert result.records == []
    assert result.tables == []
    assert any("未切换到 RapidOCR" in warning for warning in result.warnings)
    assert parser.calls


def test_paddle_unavailable_returns_error(
    scanned_pdf_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> None:
        raise PaddleStructureUnavailableError("测试环境未安装 PaddleOCR")

    monkeypatch.setattr(
        paddle_pdf_parser, "get_paddle_structure_parser", unavailable
    )
    result = parse_pdf(scanned_pdf_file)

    assert result.error is not None
    assert "PaddleOCR" in result.error
    assert result.records == []
    assert result.tables == []
    assert any("未启用 RapidOCR" in warning for warning in result.warnings)


def test_pdf_parse_does_not_import_rapidocr(
    scanned_pdf_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if "rapidocr" in name.casefold():
            raise AssertionError(f"PDF 解析不应导入 RapidOCR: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = parse_pdf(
        scanned_pdf_file,
        structure_parser=RecordingPaddleParser(),
    )

    assert result.error is None


def test_pdf_modules_do_not_use_pymupdf_text_or_table_extraction() -> None:
    forbidden = ("get_text(", "find_tables(", "get_textpage(")
    for module in (paddle_pdf_parser, pdf_renderer):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{module.__name__} 包含禁止调用: {token}"


def test_renderer_does_not_call_pymupdf_text_or_table_api(
    scanned_pdf_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pymupdf

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("PDF 解析不应调用 PyMuPDF 文字/表格提取接口")

    monkeypatch.setattr(pymupdf.Page, "get_text", forbidden)
    monkeypatch.setattr(pymupdf.Page, "find_tables", forbidden)
    result = parse_pdf(
        scanned_pdf_file,
        structure_parser=RecordingPaddleParser(),
    )

    assert result.error is None
    assert result.records


def test_word_document_does_not_use_pdf_parser(
    word_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_parse_pdf(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Word 解析不应调用 PDF 解析器")

    monkeypatch.setattr(
        "doc_extractor.core.extractor.parse_pdf", forbidden_parse_pdf
    )
    result = extract_document(word_file)

    assert result.error is None
    assert result.records


def test_non_ascii_paddle_cache_path_is_overridden(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from doc_extractor.core.paddle_structure import ensure_paddle_cache_dir

    monkeypatch.setenv(
        "PADDLE_PDX_CACHE_HOME",
        str(tmp_path / "测试用户" / ".paddlex"),
    )
    resolved = ensure_paddle_cache_dir()

    assert all(ord(character) < 128 for character in str(resolved))
    assert str(resolved).endswith(".paddlex_cache")
