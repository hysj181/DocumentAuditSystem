from __future__ import annotations

from pathlib import Path

from doc_extractor.core.extractor import extract_document
from doc_extractor.core.word_parser import parse_word


def test_word_paragraphs_headings_and_tables(word_file: Path) -> None:
    result = parse_word(word_file)

    assert result.error is None
    assert result.file_type == "word"
    assert result.metadata["paragraph_count"] == 3
    assert result.metadata["table_count"] == 1

    content_types = [record.content_type for record in result.records]
    assert content_types == ["heading", "paragraph", "paragraph", "table"]

    paragraph_records = [
        record for record in result.records if record.content_type in {"heading", "paragraph"}
    ]
    assert [record.location.paragraph_index for record in paragraph_records] == [0, 1, 2]
    assert [record.metadata["document_order"] for record in result.records] == [0, 1, 2, 3]

    table = next(record for record in result.records if record.content_type == "table")
    assert table.location.table_index == 0
    assert table.metadata["row_count"] == 2
    assert table.metadata["column_count"] == 2
    assert table.metadata["rows"] == [["项目", "金额"], ["服务费", "8,800.00"]]
    assert table.metadata["cells"][3]["row_index"] == 1
    assert table.metadata["cells"][3]["column_index"] == 1
    assert table.metadata["cells"][3]["text"] == "8,800.00"


def test_word_entities_are_attached_to_records(word_file: Path) -> None:
    result = parse_word(word_file)

    first_paragraph = next(
        record for record in result.records if record.text.startswith("合同金额")
    )
    entity_types = {entity["type"] for entity in first_paragraph.metadata["entities"]}
    assert entity_types == {"amount", "percentage"}

    date_paragraph = next(
        record for record in result.records if "签署日期" in record.text
    )
    assert date_paragraph.metadata["entities"][0]["type"] == "date"

    table = next(record for record in result.records if record.content_type == "table")
    assert table.metadata["cells"][3]["entities"][0]["type"] == "decimal"


def test_blank_word_document(blank_word_file: Path) -> None:
    result = parse_word(blank_word_file)

    assert result.error is None
    assert result.records == []
    assert result.raw_text() == ""


def test_damaged_word_returns_error(corrupt_docx: Path) -> None:
    result = extract_document(corrupt_docx)

    assert result.error is not None
    assert result.records == []
    assert result.file_type == "word"


def test_missing_word_returns_error(tmp_path: Path) -> None:
    result = extract_document(tmp_path / "missing.docx")

    assert result.error is not None
    assert "不存在" in result.error
