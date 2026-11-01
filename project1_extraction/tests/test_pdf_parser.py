from __future__ import annotations

from pathlib import Path

from doc_extractor.core.extractor import extract_document
from doc_extractor.core.pdf_parser import parse_pdf
from doc_extractor.core.paddle_structure import StructurePageResult


def test_pdf_pages_text_and_tables_use_paddle(pdf_file: Path) -> None:
    result = parse_pdf(pdf_file)

    assert result.error is None
    assert result.file_type == "pdf"
    assert result.metadata["page_count"] == 2
    assert result.metadata["parse_engine"] == "paddleocr"
    assert result.metadata["structure_used"] is True
    assert result.metadata["table_count"] >= 1

    page_records = [record for record in result.records if record.content_type == "ocr_page"]
    assert [record.location.page_number for record in page_records] == [1, 2]
    assert "采购合同" in page_records[0].text
    assert "Page two" in page_records[1].text
    assert all(record.location.bbox for record in page_records)

    text_records = [record for record in result.records if record.content_type == "ocr_text"]
    assert text_records
    for record in text_records:
        assert record.location.page_number in {1, 2}
        assert record.location.bbox is not None
        assert len(record.location.bbox) == 4
        assert record.metadata["source"] == "paddle_structure"

    table = next(record for record in result.records if record.content_type == "table")
    assert table.location.page_number == 1
    assert table.location.table_index == 0
    assert table.location.bbox is not None
    assert len(table.location.bbox) == 4
    assert table.metadata["extraction_engine"] == "PaddleOCR PP-StructureV3"
    assert table.metadata["row_count"] >= 2
    assert "Service" in table.text or "1200.50" in table.text


def test_pdf_entities_and_reading_order(pdf_file: Path) -> None:
    result = parse_pdf(pdf_file)

    text_records = [
        record for record in result.records if record.content_type == "ocr_text"
    ]
    entity_types = {
        entity["type"]
        for record in text_records
        for entity in record.metadata["entities"]
    }
    assert {"amount", "percentage", "date"}.issubset(entity_types)

    first_page_records = [
        record for record in text_records if record.location.page_number == 1
    ]
    reading_orders = [record.location.reading_order for record in first_page_records]
    assert reading_orders == sorted(reading_orders)


def test_raw_text_does_not_repeat_page_text(pdf_file: Path) -> None:
    result = parse_pdf(pdf_file)

    raw_text = result.raw_text()
    assert raw_text.count("采购合同") == 1
    assert "Page two" in raw_text


def test_blank_pdf_with_paddle_returns_empty_content(blank_pdf_file: Path) -> None:
    result = parse_pdf(blank_pdf_file)

    assert result.error is None
    assert result.metadata["page_count"] == 1
    assert result.raw_text() == ""
    assert result.metadata["table_count"] == 0


def test_blank_pdf_injected_parser_keeps_page_record(blank_pdf_file: Path) -> None:
    class EmptyParser:
        name = "EmptyPaddle"

        def parse_page(self, image, **kwargs) -> StructurePageResult:
            return StructurePageResult(engine=self.name)

    result = parse_pdf(blank_pdf_file, structure_parser=EmptyParser())

    assert result.error is None
    assert result.metadata["page_count"] == 1
    assert result.raw_text() == ""
    assert [record.content_type for record in result.records] == ["ocr_page"]


def test_damaged_pdf_returns_error(corrupt_pdf: Path) -> None:
    result = extract_document(corrupt_pdf)

    assert result.error is not None
    assert result.records == []
    assert result.file_type == "pdf"
