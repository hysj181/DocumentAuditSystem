from __future__ import annotations

import json
from pathlib import Path

from doc_extractor.core.environmental_models import (
    ENV_MANAGEMENT,
    ENV_MONITORING,
    ENV_STATISTICS,
)
from doc_extractor.core.environmental_pipeline import extract_batch


def test_batch_extraction_combines_documents_and_environmental_data(
    environmental_word_file: Path,
    environmental_word_file_same_uscc: Path,
    environmental_pdf_file: Path,
) -> None:
    progress: list[tuple[int, int, str]] = []
    batch = extract_batch(
        [
            environmental_word_file,
            environmental_word_file_same_uscc,
            environmental_pdf_file,
        ],
        progress_callback=lambda current, total, message: progress.append(
            (current, total, message)
        ),
    )

    assert batch.document_count == 3
    assert batch.record_count > 0
    assert batch.environmental.record_count > 0
    assert batch.environmental.category_counts[ENV_MONITORING] > 0
    assert batch.environmental.category_counts[ENV_MANAGEMENT] > 0
    assert batch.environmental.category_counts[ENV_STATISTICS] > 0

    assert len(batch.environmental.enterprises) == 1
    enterprise = batch.environmental.enterprises[0]
    assert enterprise.document_count == 3
    assert all(
        record.enterprise_id == enterprise.enterprise_id
        for record in batch.environmental.records
    )

    assert any("环境监测" in message for _, _, message in progress)
    payload = batch.to_dict()
    assert json.dumps(payload, ensure_ascii=False)
    assert payload["environmental"]["record_count"] == batch.environmental.record_count


def test_pdf_environmental_records_keep_page_and_bbox(environmental_pdf_file: Path) -> None:
    batch = extract_batch([environmental_pdf_file])
    monitoring = batch.environmental.records_by_category(ENV_MONITORING)

    assert monitoring
    cod = next(record for record in monitoring if record.indicator == "COD")
    assert cod.file_type == "pdf"
    assert cod.source_location["page_number"] == 1
    assert cod.source_location["bbox"] is not None
    assert len(cod.source_location["bbox"]) == 4
    assert cod.unit == "mg/L"
    assert cod.value == 45.2


def test_records_have_unique_ids_and_correct_document_isolation(
    environmental_word_file: Path,
    environmental_word_file_other_enterprise: Path,
) -> None:
    batch = extract_batch(
        [environmental_word_file, environmental_word_file_other_enterprise]
    )
    records = batch.environmental.records

    assert len({record.record_id for record in records}) == len(records)
    for record in records:
        document = next(
            document
            for document in batch.documents
            if document.document_id == record.document_id
        )
        assert record.source_file == document.source_file
        assert record.enterprise_id
