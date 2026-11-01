from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest

from doc_extractor.core.paddle_pdf_parser import parse_pdf
from doc_extractor.core.paddle_structure import (
    PaddleStructureUnavailableError,
    StructurePageResult,
)


class RecordingParser:
    name = "Recording Paddle"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[int] = []

    def parse_page(self, image: Any, **kwargs: Any) -> StructurePageResult:
        self.calls.append(kwargs.get("page_number", 0))
        if self.fail:
            raise RuntimeError("模拟 PaddleOCR 失败")
        return StructurePageResult(engine=self.name)


def test_pdf_parse_calls_paddle_for_every_page(tmp_path: Path) -> None:
    path = tmp_path / "two_pages.pdf"
    import pymupdf

    document = pymupdf.open()
    document.new_page()
    document.new_page()
    document.save(path)
    document.close()

    parser = RecordingParser()
    result = parse_pdf(path, structure_parser=parser)

    assert result.error is None
    assert parser.calls == [1, 2]
    assert result.metadata["parse_engine"] == "paddleocr"
    assert result.metadata["engine_usage"] == {parser.name: 2}


def test_pdf_parse_does_not_import_rapidocr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pymupdf

    path = tmp_path / "one_page.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()

    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if "rapidocr" in name.casefold():
            raise AssertionError(f"PDF 解析不应导入 RapidOCR: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = parse_pdf(path, structure_parser=RecordingParser())

    assert result.error is None


def test_paddle_failure_returns_error_without_fallback(tmp_path: Path) -> None:
    import pymupdf

    path = tmp_path / "one_page.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()

    result = parse_pdf(path, structure_parser=RecordingParser(fail=True))

    assert result.error is not None
    assert "PaddleOCR" in result.error
    assert result.tables == []
    assert any("未切换到 RapidOCR" in warning for warning in result.warnings)


def test_paddle_unavailable_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pymupdf
    from doc_extractor.core import paddle_pdf_parser

    path = tmp_path / "one_page.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()

    def unavailable() -> None:
        raise PaddleStructureUnavailableError("测试环境未安装 PaddleOCR")

    monkeypatch.setattr(
        paddle_pdf_parser, "get_paddle_structure_parser", unavailable
    )
    result = parse_pdf(path)

    assert result.error is not None
    assert result.records == []
    assert result.tables == []
