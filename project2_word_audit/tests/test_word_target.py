from __future__ import annotations

from pathlib import Path

from docx import Document
from word_audit.models import (
    LOCATION_LOCATED,
    VERIFICATION_NOT_ATTEMPTED,
    VERIFICATION_VERIFIED,
    AuditIssue,
    CalculationInfo,
    LocationResult,
    SourceLocation,
)
from word_audit.project1_batch import DocumentView, Project1Batch
from word_audit.word_target import (
    REASON_ANCHOR_AMBIGUOUS,
    REASON_ANCHOR_MISSING,
    REASON_CELL_PARAGRAPH_AMBIGUOUS,
    REASON_COLUMN_OUT_OF_RANGE,
    REASON_DOCUMENT_ID_MISMATCH,
    REASON_MATH_ANCHOR_NOT_PRECISE,
    REASON_NESTED_TABLE,
    REASON_NOT_WORD_FILE,
    REASON_PARAGRAPH_OUT_OF_RANGE,
    REASON_ROW_OUT_OF_RANGE,
    REASON_TABLE_OUT_OF_RANGE,
    REASON_TYPO_MANUAL_REVIEW,
    STRATEGY_BODY_EXACT,
    STRATEGY_MATH_REPORTED_VALUE,
    STRATEGY_MATH_VALUE_CELL,
    STRATEGY_TABLE_EXACT,
    STRATEGY_TYPO_CONTEXT,
    STRATEGY_TYPO_EXACT,
    TARGET_STATUS_AMBIGUOUS,
    TARGET_STATUS_RESOLVED,
    TARGET_STATUS_SKIPPED,
    resolve_word_target,
)


def _document_view(
    *,
    document_id: str = "doc-1",
    file_type: str = "word",
) -> DocumentView:
    return DocumentView(
        document_id=document_id,
        source_name="source.docx",
        source_file="D:/tmp/source.docx",
        file_type=file_type,
        records=[],
        metadata={},
        tables=[],
    )


def _batch(document_view: DocumentView) -> Project1Batch:
    return Project1Batch(
        batch_id="batch-1",
        schema_version="1.0",
        extracted_at=None,
        documents=[document_view],
        environmental_records=[],
        environmental={},
        path=Path("batch.json"),
        metadata={},
        environmental_present=True,
    )


def _source(
    *,
    document_id: str = "doc-1",
    file_type: str = "word",
    paragraph_index: int | None = None,
    table_index: int | None = None,
    row_index: int | None = None,
    column_index: int | None = None,
    value_row_index: int | None = None,
    value_column_index: int | None = None,
    page_number: int | None = None,
    metadata: dict | None = None,
) -> SourceLocation:
    if table_index is not None:
        method = "table_cell"
    elif page_number is not None:
        method = "text_match"
    else:
        method = "exact_index"
    return SourceLocation(
        document_id=document_id,
        source_file="D:/tmp/source.docx",
        file_type=file_type,
        paragraph_index=paragraph_index,
        table_index=table_index,
        row_index=row_index,
        column_index=column_index,
        value_row_index=value_row_index,
        value_column_index=value_column_index,
        page_number=page_number,
        locator_method=method,
        locator_confidence=0.95,
        metadata=dict(metadata or {}),
    )


def _location(
    source: SourceLocation,
    *,
    issue_id: str = "issue-1",
    document_id: str | None = None,
    metadata: dict | None = None,
) -> LocationResult:
    return LocationResult(
        issue_id=issue_id,
        document_id=document_id or source.document_id,
        file_type=source.file_type,
        locator_status=LOCATION_LOCATED,
        paragraph_index=source.paragraph_index,
        table_index=source.table_index,
        row_index=source.row_index,
        column_index=source.column_index,
        locator_confidence=source.locator_confidence,
        needs_manual_review=False,
        source_location=source,
        metadata=dict(metadata or {}),
    )


def _issue(
    original_text: str,
    source: SourceLocation,
    *,
    issue_id: str = "issue-1",
    issue_type: str = "other",
    metadata: dict | None = None,
    calculation: CalculationInfo | None = None,
    needs_manual_review: bool = False,
) -> AuditIssue:
    return AuditIssue(
        issue_id=issue_id,
        issue_type=issue_type,
        description="target test",
        original_text=original_text,
        location=source,
        calculation=calculation,
        needs_manual_review=needs_manual_review,
        metadata=dict(metadata or {}),
    )


def _body_paragraph(document: Document, text: str):
    paragraph = document.add_paragraph(text)
    return paragraph


def _table_cell_document(values) -> Document:
    document = Document()
    table = document.add_table(rows=len(values), cols=len(values[0]))
    for row_index, row in enumerate(values):
        for column_index, value in enumerate(row):
            table.cell(row_index, column_index).text = value
    return document


def test_resolve_body_success() -> None:
    document = Document()
    _body_paragraph(document, "COD 85 mg/L")
    source = _source(paragraph_index=0)
    issue = _issue("85", source)
    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.position is not None
    assert result.position.kind == "body"
    assert result.position.body_paragraph_index == 0
    assert result.anchor_text == "85"
    assert result.occurrence_index == 0
    assert result.anchor_strategy == STRATEGY_BODY_EXACT


def test_body_paragraph_out_of_range() -> None:
    document = Document()
    _body_paragraph(document, "COD 85")
    source = _source(paragraph_index=99)
    issue = _issue("85", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_PARAGRAPH_OUT_OF_RANGE


def test_body_anchor_missing() -> None:
    document = Document()
    _body_paragraph(document, "COD 12")
    source = _source(paragraph_index=0)
    issue = _issue("85", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_ANCHOR_MISSING


def test_body_duplicate_text_is_ambiguous_without_occurrence() -> None:
    document = Document()
    _body_paragraph(document, "COD COD")
    source = _source(paragraph_index=0)
    issue = _issue("COD", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_AMBIGUOUS
    assert result.failure_reason == REASON_ANCHOR_AMBIGUOUS

    explicit = _issue(
        "COD",
        source,
        metadata={"occurrence_index": 1},
    )
    resolved = resolve_word_target(
        document,
        _batch(_document_view()),
        explicit,
        _location(source),
    )
    assert resolved.status == TARGET_STATUS_RESOLVED
    assert resolved.occurrence_index == 1


def test_resolve_plain_table_cell() -> None:
    document = _table_cell_document([["COD", "85"]])
    source = _source(
        table_index=0,
        row_index=0,
        column_index=1,
    )
    issue = _issue("85", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.position is not None
    assert result.position.kind == "table_cell"
    assert result.position.table_cells[0].cell_index == 1
    assert result.position.cell_paragraph_index == 0
    assert result.anchor_text == "85"
    assert result.anchor_strategy == STRATEGY_TABLE_EXACT


def test_table_index_out_of_range() -> None:
    document = _table_cell_document([["COD", "85"]])
    source = _source(table_index=9, row_index=0, column_index=0)
    issue = _issue("COD", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_TABLE_OUT_OF_RANGE


def test_table_row_and_column_out_of_range() -> None:
    document = _table_cell_document([["COD", "85"]])
    row_source = _source(table_index=0, row_index=9, column_index=0)
    row_result = resolve_word_target(
        document,
        _batch(_document_view()),
        _issue("COD", row_source),
        _location(row_source),
    )
    assert row_result.failure_reason == REASON_ROW_OUT_OF_RANGE

    column_source = _source(table_index=0, row_index=0, column_index=9)
    column_result = resolve_word_target(
        document,
        _batch(_document_view()),
        _issue("COD", column_source),
        _location(column_source),
    )
    assert column_result.failure_reason == REASON_COLUMN_OUT_OF_RANGE


def test_merged_cell_maps_to_canonical_cell() -> None:
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "COD 85"
    table.cell(0, 0).merge(table.cell(0, 1))
    source = _source(table_index=0, row_index=0, column_index=1)
    issue = _issue("85", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.position is not None
    assert result.position.table_cells[0].cell_index == 0


def test_different_cells_with_same_text_are_not_confused() -> None:
    document = _table_cell_document([["85", "85"]])
    source = _source(table_index=0, row_index=0, column_index=1)
    issue = _issue("85", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.position is not None
    assert result.position.table_cells[0].cell_index == 1


def test_cell_multiple_paragraphs_resolves_correct_paragraph() -> None:
    document = Document()
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = "COD 85"
    cell.add_paragraph("氨氮 12.5")
    source = _source(table_index=0, row_index=0, column_index=0)
    issue = _issue("12.5", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.position is not None
    assert result.position.cell_paragraph_index == 1
    assert result.anchor_text == "12.5"


def test_cell_multiple_paragraphs_with_duplicate_text_is_ambiguous() -> None:
    document = Document()
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = "85"
    cell.add_paragraph("85")
    source = _source(table_index=0, row_index=0, column_index=0)
    issue = _issue("85", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_AMBIGUOUS
    assert result.failure_reason == REASON_CELL_PARAGRAPH_AMBIGUOUS


def test_high_confidence_typo_resolves() -> None:
    document = Document()
    _body_paragraph(document, "本次数剧由合成测试生成。")
    source = _source(paragraph_index=0)
    issue = _issue(
        "数剧",
        source,
        issue_type="typo",
        metadata={
            "auto_annotate": True,
            "typo_confidence": "high",
            "occurrence_count": 1,
        },
    )

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "数剧"
    assert result.anchor_strategy == STRATEGY_TYPO_EXACT


def test_low_confidence_typo_is_rejected() -> None:
    document = Document()
    _body_paragraph(document, "本次数剧由合成测试生成。")
    source = _source(paragraph_index=0)
    issue = _issue(
        "数剧",
        source,
        issue_type="typo",
        needs_manual_review=True,
        metadata={
            "auto_annotate": False,
            "typo_confidence": "low",
            "occurrence_count": 1,
        },
    )

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_TYPO_MANUAL_REVIEW


def test_repeated_typo_requires_context_or_explicit_occurrence() -> None:
    document = Document()
    _body_paragraph(document, "数剧和数剧")
    source = _source(paragraph_index=0)
    issue = _issue(
        "数剧",
        source,
        issue_type="typo",
        metadata={
            "auto_annotate": True,
            "typo_confidence": "high",
            "occurrence_count": 2,
        },
    )

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_AMBIGUOUS
    assert result.failure_reason == REASON_ANCHOR_AMBIGUOUS

    explicit = _issue(
        "数剧",
        source,
        issue_type="typo",
        metadata={
            "auto_annotate": True,
            "typo_confidence": "high",
            "occurrence_count": 2,
            "occurrence_index": 1,
        },
    )
    resolved = resolve_word_target(
        document,
        _batch(_document_view()),
        explicit,
        _location(source),
    )
    assert resolved.status == TARGET_STATUS_RESOLVED
    assert resolved.occurrence_index == 1


def test_repeated_typo_context_can_disambiguate() -> None:
    document = Document()
    text = "数剧" + ("甲" * 100) + "数剧" + ("乙" * 20)
    _body_paragraph(document, text)
    source = _source(paragraph_index=0)
    context = ("甲" * 20) + "数剧" + ("乙" * 10)
    issue = _issue(
        "数剧",
        source,
        issue_type="typo",
        metadata={
            "auto_annotate": True,
            "typo_confidence": "high",
            "occurrence_count": 2,
            "contexts": [context],
        },
    )

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.occurrence_index == 1
    assert result.anchor_strategy == STRATEGY_TYPO_CONTEXT


def test_math_uses_value_cell_not_raw_expression() -> None:
    document = _table_cell_document(
        [["监测项目", "监测结果"], ["COD", "85"]]
    )
    source = _source(
        table_index=0,
        row_index=1,
        column_index=0,
        value_row_index=1,
        value_column_index=1,
    )
    calculation = CalculationInfo(
        formula="100-15",
        reported_value=85,
        verification_status=VERIFICATION_NOT_ATTEMPTED,
    )
    issue = _issue(
        "COD\t85\tmg/L\t模拟检测",
        source,
        issue_type="calculation_error",
        calculation=calculation,
    )

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "85"
    assert result.anchor_strategy == STRATEGY_MATH_VALUE_CELL
    assert result.position is not None
    assert result.position.table_cells[0].cell_index == 1


def test_math_without_precise_value_is_skipped() -> None:
    document = _table_cell_document(
        [["监测项目", "监测结果"], ["COD", "85"]]
    )
    source = _source(table_index=0, row_index=1, column_index=0)
    calculation = CalculationInfo(
        formula="100-15",
        reported_value=85,
        verification_status=VERIFICATION_NOT_ATTEMPTED,
    )
    issue = _issue(
        "COD\t85\tmg/L\t模拟检测",
        source,
        issue_type="calculation_error",
        calculation=calculation,
    )

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_MATH_ANCHOR_NOT_PRECISE


def _math_issue(
    original_text: str,
    source: SourceLocation,
    *,
    reported_value: float | str,
    computed_value: float | str | None = None,
    issue_type: str = "calculation_error",
) -> AuditIssue:
    return _issue(
        original_text,
        source,
        issue_type=issue_type,
        calculation=CalculationInfo(
            formula="100-15",
            reported_value=reported_value,
            computed_value=computed_value,
            verification_status=(
                VERIFICATION_VERIFIED
                if computed_value is not None
                else VERIFICATION_NOT_ATTEMPTED
            ),
        ),
    )


def _math_table_result(
    cell_text: str,
    *,
    reported_value: float | str,
    computed_value: float | str | None = None,
):
    document = _table_cell_document(
        [["监测项目", "监测结果"], ["COD", cell_text]]
    )
    source = _source(
        table_index=0,
        row_index=1,
        column_index=0,
        value_row_index=1,
        value_column_index=1,
    )
    issue = _math_issue(
        "COD\t85\tmg/L",
        source,
        reported_value=reported_value,
        computed_value=computed_value,
    )
    return resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )


def test_math_anchor_with_unit_cell_uses_numeric_token() -> None:
    result = _math_table_result("85 mg/L", reported_value=85)

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "85"
    assert result.anchor_strategy == STRATEGY_MATH_VALUE_CELL


def test_math_anchor_with_multiple_numbers_uses_reported_token() -> None:
    result = _math_table_result(
        "85 (70.5)",
        reported_value=85,
        computed_value=70.5,
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "85"
    assert "70.5" not in result.anchor_text


def test_math_anchor_with_text_cell_uses_numeric_token() -> None:
    result = _math_table_result("COD 85 mg/L", reported_value=85)

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "85"


def test_math_anchor_with_only_computed_value_is_skipped() -> None:
    result = _math_table_result(
        "70.5",
        reported_value=85,
        computed_value=70.5,
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_MATH_ANCHOR_NOT_PRECISE


def test_math_anchor_repeated_reported_value_is_ambiguous() -> None:
    result = _math_table_result("85 / 85", reported_value=85)

    assert result.status == TARGET_STATUS_AMBIGUOUS
    assert result.failure_reason == REASON_ANCHOR_AMBIGUOUS


def test_math_anchor_without_value_cell_does_not_fallback() -> None:
    document = _table_cell_document([["COD 85", "备注"], ["其他", "内容"]])
    source = _source(table_index=0, row_index=0, column_index=0)
    issue = _math_issue("COD\t85", source, reported_value=85)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_MATH_ANCHOR_NOT_PRECISE


def test_math_body_uses_numeric_token_not_raw_expression() -> None:
    document = Document()
    _body_paragraph(document, "COD 85 mg/L")
    source = _source(paragraph_index=0)
    issue = _math_issue(
        "COD\t85\tmg/L\t模拟检测",
        source,
        reported_value=85,
    )

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "85"
    assert result.anchor_strategy == STRATEGY_MATH_REPORTED_VALUE


def test_math_body_missing_reported_value_is_skipped() -> None:
    document = Document()
    _body_paragraph(document, "COD 12 mg/L")
    source = _source(paragraph_index=0)
    issue = _math_issue("COD\t12\tmg/L", source, reported_value=85)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_MATH_ANCHOR_NOT_PRECISE


def test_math_body_repeated_reported_value_is_ambiguous() -> None:
    document = Document()
    _body_paragraph(document, "85 / 85")
    source = _source(paragraph_index=0)
    issue = _math_issue("85 / 85", source, reported_value=85)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_AMBIGUOUS
    assert result.failure_reason == REASON_ANCHOR_AMBIGUOUS


def test_math_without_calculation_is_skipped() -> None:
    document = Document()
    _body_paragraph(document, "85")
    source = _source(paragraph_index=0)
    issue = _issue("85", source, issue_type="value_mismatch")

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_MATH_ANCHOR_NOT_PRECISE


def test_math_decimal_equivalent_token_is_matched() -> None:
    result = _math_table_result("85.0", reported_value=85)

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "85.0"


def test_math_thousands_separator_token_is_matched() -> None:
    result = _math_table_result("1,200.50", reported_value=1200.5)

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "1,200.50"


def test_math_does_not_match_substring_of_larger_number() -> None:
    result = _math_table_result("185", reported_value=85)

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_MATH_ANCHOR_NOT_PRECISE


def test_math_negative_reported_value_uses_signed_token() -> None:
    result = _math_table_result("-85", reported_value=-85)

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "-85"


def test_math_value_cell_multiple_paragraphs_unique_match() -> None:
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "监测项目"
    table.cell(0, 1).text = "监测结果"
    table.cell(1, 0).text = "COD"
    cell = table.cell(1, 1)
    cell.paragraphs[0].text = "85"
    cell.add_paragraph("备注")
    source = _source(
        table_index=0,
        row_index=1,
        column_index=0,
        value_row_index=1,
        value_column_index=1,
    )
    issue = _math_issue("COD\t85\tmg/L", source, reported_value=85)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "85"
    assert result.position is not None
    assert result.position.table_cells[0].cell_index == 1


def test_math_value_cell_multiple_matching_paragraphs_is_ambiguous() -> None:
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "监测项目"
    table.cell(0, 1).text = "监测结果"
    table.cell(1, 0).text = "COD"
    cell = table.cell(1, 1)
    cell.paragraphs[0].text = "85"
    cell.add_paragraph("85")
    source = _source(
        table_index=0,
        row_index=1,
        column_index=0,
        value_row_index=1,
        value_column_index=1,
    )
    issue = _math_issue("COD\t85\tmg/L", source, reported_value=85)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_AMBIGUOUS
    assert result.failure_reason == REASON_CELL_PARAGRAPH_AMBIGUOUS


def test_math_computed_value_is_not_used_as_anchor() -> None:
    result = _math_table_result(
        "COD 85 mg/L (计算值 70.5)",
        reported_value=85,
        computed_value=70.5,
    )

    assert result.status == TARGET_STATUS_RESOLVED
    assert result.anchor_text == "85"
    assert "70.5" not in result.anchor_text


def test_nested_table_metadata_is_skipped() -> None:
    document = _table_cell_document([["COD", "85"]])
    source = _source(table_index=0, row_index=0, column_index=0)
    issue = _issue("COD", source)
    location = _location(source, metadata={"nested_table": True})

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        location,
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_NESTED_TABLE


def test_non_word_file_is_skipped() -> None:
    document = Document()
    _body_paragraph(document, "COD 85")
    source = _source(file_type="pdf", page_number=1)
    issue = _issue("COD", source)
    location = _location(source)
    document_view = _document_view(file_type="pdf")

    result = resolve_word_target(
        document,
        _batch(document_view),
        issue,
        location,
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_NOT_WORD_FILE


def test_document_id_mismatch_is_skipped() -> None:
    document = Document()
    _body_paragraph(document, "COD 85")
    source = _source(paragraph_index=0)
    issue = _issue("85", source)
    location = _location(source, document_id="missing-doc")

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        location,
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_DOCUMENT_ID_MISMATCH


def test_no_global_text_search_fallback() -> None:
    document = Document()
    _body_paragraph(document, "85")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "COD"
    source = _source(table_index=0, row_index=0, column_index=0)
    issue = _issue("85", source)

    result = resolve_word_target(
        document,
        _batch(_document_view()),
        issue,
        _location(source),
    )

    assert result.status == TARGET_STATUS_SKIPPED
    assert result.failure_reason == REASON_ANCHOR_MISSING
    assert result.position is None
