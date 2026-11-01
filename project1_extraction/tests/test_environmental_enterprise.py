from __future__ import annotations

from pathlib import Path

from doc_extractor.core.environmental_models import (
    ENTERPRISE_NAME_MATCHED,
    ENTERPRISE_NAME_ONLY,
    ENTERPRISE_UNCLEAR,
    ENTERPRISE_VERIFIED,
    FLAG_ENTERPRISE_UNCLEAR,
    FLAG_ENTERPRISE_UNVERIFIED,
)
from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.extractor import extract_document


def _documents(*paths: Path):
    documents = [extract_document(path) for path in paths]
    assert all(document.error is None for document in documents)
    return documents


def test_same_uscc_merges_documents(
    environmental_word_file: Path,
    environmental_word_file_same_uscc: Path,
) -> None:
    result = extract_environmental_data(
        _documents(environmental_word_file, environmental_word_file_same_uscc)
    )

    assert len(result.enterprises) == 1
    enterprise = result.enterprises[0]
    assert enterprise.identity_status == ENTERPRISE_VERIFIED
    assert enterprise.document_count == 2
    assert enterprise.unified_social_credit_code == "91310115MA1K4A2B3C"
    assert {record.enterprise_id for record in result.records} == {enterprise.enterprise_id}


def test_same_name_without_uscc_is_merged_but_flagged(
    environmental_word_file: Path,
    environmental_word_file_same_name: Path,
) -> None:
    result = extract_environmental_data(
        _documents(environmental_word_file, environmental_word_file_same_name)
    )

    assert len(result.enterprises) == 1
    enterprise = result.enterprises[0]
    assert enterprise.identity_status == ENTERPRISE_NAME_MATCHED
    assert enterprise.document_count == 2
    assert any("建议人工核实" in warning for warning in enterprise.warnings)

    name_only_records = [
        record
        for record in result.records
        if record.source_file.endswith("environmental_same_name.docx")
    ]
    assert name_only_records
    assert all(FLAG_ENTERPRISE_UNVERIFIED in record.flags for record in name_only_records)


def test_different_enterprises_are_not_merged(
    environmental_word_file: Path,
    environmental_word_file_other_enterprise: Path,
) -> None:
    result = extract_environmental_data(
        _documents(
            environmental_word_file,
            environmental_word_file_other_enterprise,
        )
    )

    assert len(result.enterprises) == 2
    ids = {enterprise.enterprise_id for enterprise in result.enterprises}
    assert len(ids) == 2
    names = {enterprise.enterprise_name for enterprise in result.enterprises}
    assert names == {"华清化工有限公司", "清源环保科技有限公司"}


def test_unclear_enterprise_is_isolated_and_flagged(
    environmental_word_file: Path,
    environmental_word_no_identity: Path,
) -> None:
    result = extract_environmental_data(
        _documents(environmental_word_file, environmental_word_no_identity)
    )

    unclear = [
        enterprise
        for enterprise in result.enterprises
        if enterprise.identity_status == ENTERPRISE_UNCLEAR
    ]
    assert len(unclear) == 1
    assert unclear[0].enterprise_name is None
    assert unclear[0].document_count == 1

    unclear_records = [
        record
        for record in result.records
        if record.source_file.endswith("environmental_no_identity.docx")
    ]
    assert unclear_records
    assert all(FLAG_ENTERPRISE_UNCLEAR in record.flags for record in unclear_records)


def test_two_unknown_documents_are_not_auto_merged(
    environmental_word_no_identity: Path,
) -> None:
    result = extract_environmental_data(
        _documents(environmental_word_no_identity, environmental_word_no_identity)
    )

    unclear = [
        enterprise
        for enterprise in result.enterprises
        if enterprise.identity_status == ENTERPRISE_UNCLEAR
    ]
    assert len(unclear) == 2
    assert unclear[0].enterprise_id != unclear[1].enterprise_id


def test_same_name_without_uscc_merges_with_each_other(
    environmental_word_file_same_name: Path,
) -> None:
    result = extract_environmental_data(
        _documents(environmental_word_file_same_name, environmental_word_file_same_name)
    )

    assert len(result.enterprises) == 1
    assert result.enterprises[0].identity_status == ENTERPRISE_NAME_ONLY
    assert result.enterprises[0].document_count == 2
