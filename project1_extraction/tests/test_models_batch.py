from __future__ import annotations

import json
from pathlib import Path

from doc_extractor.core.extractor import extract_document, extract_documents


def test_unified_model_is_json_serializable(word_file: Path, pdf_file: Path) -> None:
    word_result = extract_document(word_file)
    pdf_result = extract_document(pdf_file)

    for result in (word_result, pdf_result):
        payload = result.to_dict()
        encoded = json.dumps(payload, ensure_ascii=False)
        assert encoded

        for record in payload["records"]:
            assert set(record) == {
                "document_id",
                "source_file",
                "file_type",
                "content_type",
                "text",
                "location",
                "metadata",
            }
            assert record["document_id"] == result.document_id
            assert record["source_file"] == result.source_file
            assert set(record["location"]) == {
                "paragraph_index",
                "table_index",
                "row_index",
                "column_index",
                "page_number",
                "bbox",
                "block_index",
                "reading_order",
            }


def test_documents_have_unique_ids_and_isolated_records(
    word_file: Path, pdf_file: Path
) -> None:
    results = extract_documents([word_file, pdf_file])

    assert len(results) == 2
    assert results[0].document_id != results[1].document_id
    for result in results:
        for record in result.records:
            assert record.document_id == result.document_id
            assert record.source_file == result.source_file


def test_extracting_same_file_twice_creates_isolated_documents(word_file: Path) -> None:
    results = extract_documents([word_file, word_file])

    assert results[0].document_id != results[1].document_id
    assert results[0].records[0].document_id != results[1].records[0].document_id


def test_batch_progress_callback(word_file: Path, pdf_file: Path) -> None:
    events: list[tuple[int, int, str]] = []
    extract_documents(
        [word_file, pdf_file],
        progress_callback=lambda current, total, message: events.append(
            (current, total, message)
        ),
    )

    assert events[-1][0] == 2
    assert events[-1][1] == 2
    assert any("sample.docx" in message for _, _, message in events)


def test_unsupported_file_returns_error(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")

    result = extract_document(path)

    assert result.error is not None
    assert "不支持" in result.error


def test_missing_file_returns_error(tmp_path: Path) -> None:
    result = extract_document(tmp_path / "missing.pdf")

    assert result.error is not None
    assert "不存在" in result.error
