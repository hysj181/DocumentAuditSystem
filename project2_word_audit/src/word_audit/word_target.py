"""Resolve audit issues to stable Word paragraph/comment targets.

This module is read-only with respect to the Word document. It maps project
two ``AuditIssue``/``LocationResult`` data to ``ParagraphPosition`` plus the
exact anchor text that the native comment writer can use.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from word_audit.models import (
    LOCATION_LOCATED,
    AuditIssue,
    LocationResult,
)
from word_audit.project1_batch import DocumentView, Project1Batch
from word_audit.word_comments import (
    PARAGRAPH_KIND_BODY,
    STATUS_AMBIGUOUS,
    STATUS_LOCATED,
    STATUS_NOT_FOUND,
    STATUS_UNSUPPORTED,
    ParagraphHandle,
    ParagraphPosition,
    TableCellPath,
    TextLocationResult,
    find_document_paragraph,
    index_paragraph,
    iter_document_paragraphs,
    locate_text,
)

TARGET_STATUS_RESOLVED = "resolved"
TARGET_STATUS_AMBIGUOUS = "ambiguous"
TARGET_STATUS_SKIPPED = "skipped"

REASON_NOT_WORD_FILE = "not_word_file"
REASON_DOCUMENT_ID_MISMATCH = "document_id_mismatch"
REASON_LOCATION_NOT_LOCATED = "location_not_located"
REASON_UNSUPPORTED_LOCATION = "unsupported_location"
REASON_PARAGRAPH_OUT_OF_RANGE = "paragraph_index_out_of_range"
REASON_TABLE_OUT_OF_RANGE = "table_index_out_of_range"
REASON_ROW_OUT_OF_RANGE = "row_index_out_of_range"
REASON_COLUMN_OUT_OF_RANGE = "column_index_out_of_range"
REASON_CELL_PARAGRAPH_NOT_FOUND = "cell_paragraph_not_found"
REASON_CELL_PARAGRAPH_AMBIGUOUS = "cell_paragraph_ambiguous"
REASON_ANCHOR_EMPTY = "anchor_text_empty"
REASON_ANCHOR_MISSING = "anchor_text_missing"
REASON_ANCHOR_AMBIGUOUS = "ambiguous_text_occurrence"
REASON_OCCURRENCE_NOT_FOUND = "occurrence_not_found"
REASON_TYPO_MANUAL_REVIEW = "typo_manual_review_required"
REASON_TYPO_LOW_CONFIDENCE = "typo_low_confidence"
REASON_MATH_ANCHOR_NOT_PRECISE = "math_anchor_not_precise"
REASON_NESTED_TABLE = "nested_table_unsupported"
REASON_UNSUPPORTED_STRUCTURE = "unsupported_document_structure"

STRATEGY_BODY_EXACT = "body_exact"
STRATEGY_TABLE_EXACT = "table_cell_exact"
STRATEGY_TYPO_EXACT = "typo_exact"
STRATEGY_TYPO_CONTEXT = "typo_context"
STRATEGY_MATH_EXPRESSION = "math_expression"
STRATEGY_MATH_REPORTED_VALUE = "math_reported_value"
STRATEGY_MATH_VALUE_CELL = "math_value_cell"

_CONTEXT_RADIUS = 40
_NUMERIC_TOKEN_RE = re.compile(
    r"(?<![\d.,])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.,])"
)


@dataclass(frozen=True)
class ResolvedWordTarget:
    """A verified target for one native Word comment."""

    status: str
    position: ParagraphPosition | None = None
    anchor_text: str | None = None
    occurrence_index: int | None = None
    anchor_strategy: str | None = None
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return self.status == TARGET_STATUS_RESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "position": self.position.to_dict() if self.position else None,
            "anchor_text": self.anchor_text,
            "occurrence_index": self.occurrence_index,
            "anchor_strategy": self.anchor_strategy,
            "failure_reason": self.failure_reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class _AnchorCandidate:
    text: str
    strategy: str


@dataclass(frozen=True)
class _NumericToken:
    text: str
    value: Decimal
    start: int
    end: int


@dataclass(frozen=True)
class _ParagraphMatch:
    handle: ParagraphHandle
    match: TextLocationResult
    occurrence_index: int
    strategy: str


def _is_typo_issue(issue: AuditIssue) -> bool:
    return issue.issue_type == "typo" or issue.metadata.get("audit_rule") == "typo"


def _is_math_type(issue: AuditIssue) -> bool:
    return issue.calculation is not None or issue.issue_type in {
        "calculation_error",
        "formula_error",
        "value_mismatch",
        "unit_mismatch",
    }


def _to_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        text = str(value)
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "")
    else:
        return None
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _is_math_issue(issue: AuditIssue) -> bool:
    return (
        issue.calculation is not None
        and _to_decimal(issue.calculation.reported_value) is not None
    )


def _format_value(value: float | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _extract_numeric_tokens(text: str) -> list[_NumericToken]:
    tokens: list[_NumericToken] = []
    for match in _NUMERIC_TOKEN_RE.finditer(text):
        raw = match.group(0)
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            continue
        tokens.append(
            _NumericToken(
                text=raw,
                value=value,
                start=match.start(),
                end=match.end(),
            )
        )
    return tokens


def _select_math_anchor(
    text: str,
    reported_value: object,
) -> tuple[_NumericToken | None, str | None]:
    reported = _to_decimal(reported_value)
    if reported is None:
        return None, REASON_MATH_ANCHOR_NOT_PRECISE
    matches = [
        token
        for token in _extract_numeric_tokens(text)
        if token.value == reported
    ]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, REASON_ANCHOR_AMBIGUOUS
    return None, None


def _token_occurrence_index(text: str, token: _NumericToken) -> int | None:
    occurrence = 0
    start = 0
    while True:
        index = text.find(token.text, start)
        if index < 0:
            return None
        if index == token.start:
            return occurrence
        occurrence += 1
        start = index + 1


def _normalize_context(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _skip(
    reason: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> ResolvedWordTarget:
    return ResolvedWordTarget(
        status=TARGET_STATUS_SKIPPED,
        failure_reason=reason,
        metadata=dict(metadata or {}),
    )


def _ambiguous(
    reason: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> ResolvedWordTarget:
    return ResolvedWordTarget(
        status=TARGET_STATUS_AMBIGUOUS,
        failure_reason=reason,
        metadata=dict(metadata or {}),
    )


def _resolved(
    handle: ParagraphHandle,
    candidate: _AnchorCandidate,
    match: TextLocationResult,
    occurrence_index: int,
    *,
    strategy: str,
    metadata: dict[str, Any] | None = None,
) -> ResolvedWordTarget:
    return ResolvedWordTarget(
        status=TARGET_STATUS_RESOLVED,
        position=handle.position,
        anchor_text=candidate.text,
        occurrence_index=occurrence_index,
        anchor_strategy=strategy,
        metadata=dict(metadata or {}),
    )


def _typo_guard(issue: AuditIssue) -> str | None:
    if issue.metadata.get("auto_annotate", True) is False:
        return REASON_TYPO_MANUAL_REVIEW
    if issue.needs_manual_review:
        return REASON_TYPO_MANUAL_REVIEW
    confidence = issue.metadata.get("typo_confidence")
    if confidence is not None and confidence != "high":
        return REASON_TYPO_LOW_CONFIDENCE
    return None


def _paragraph_ancestor_tc(paragraph: Paragraph):
    parent = paragraph._p.getparent()
    while parent is not None:
        if parent.tag == qn("w:tc"):
            return parent
        parent = parent.getparent()
    return None


def _select_occurrence(
    match: TextLocationResult,
    issue: AuditIssue,
) -> int | None:
    explicit = issue.metadata.get("occurrence_index")
    if isinstance(explicit, int) and not isinstance(explicit, bool):
        if 0 <= explicit < match.occurrence_count:
            return explicit
        return None

    contexts = issue.metadata.get("contexts")
    if not isinstance(contexts, list):
        context = issue.metadata.get("context")
        contexts = [context] if isinstance(context, str) and context else []
    normalized_contexts = [
        _normalize_context(str(context))
        for context in contexts
        if isinstance(context, str) and context.strip()
    ]
    if not normalized_contexts or match.index is None:
        return None

    text = match.index.text
    candidates: list[int] = []
    for occurrence_index, (start, end) in enumerate(match.occurrences):
        window_start = max(0, start - _CONTEXT_RADIUS)
        window_end = min(len(text), end + _CONTEXT_RADIUS)
        window = _normalize_context(text[window_start:window_end])
        if any(
            context in window or window in context
            for context in normalized_contexts
        ):
            candidates.append(occurrence_index)

    if len(candidates) == 1:
        return candidates[0]
    return None


def _match_in_paragraph(
    handle: ParagraphHandle,
    candidate: _AnchorCandidate,
    issue: AuditIssue,
    *,
    require_context: bool,
) -> tuple[TextLocationResult | None, int | None, str | None]:
    paragraph = handle.paragraph
    index = index_paragraph(paragraph, include_existing_comments=False)
    match = locate_text(index, candidate.text)

    if match.status == STATUS_UNSUPPORTED:
        return None, None, match.reason or REASON_UNSUPPORTED_STRUCTURE
    if match.status == STATUS_NOT_FOUND:
        return None, None, None
    if match.status == STATUS_LOCATED:
        if require_context:
            occurrence = _select_occurrence(match, issue)
            if occurrence is None:
                return match, None, REASON_ANCHOR_AMBIGUOUS
            if occurrence != match.occurrence_index:
                match = locate_text(
                    index,
                    candidate.text,
                    occurrence_index=occurrence,
                )
            return match, occurrence, None
        return match, match.occurrence_index or 0, None

    if match.status == STATUS_AMBIGUOUS:
        occurrence = _select_occurrence(match, issue)
        if occurrence is None:
            return match, None, REASON_ANCHOR_AMBIGUOUS
        resolved_match = locate_text(
            index,
            candidate.text,
            occurrence_index=occurrence,
        )
        if resolved_match.status != STATUS_LOCATED:
            return resolved_match, None, resolved_match.reason or REASON_ANCHOR_AMBIGUOUS
        return resolved_match, occurrence, None

    return None, None, REASON_ANCHOR_MISSING


def _resolve_candidates(
    handles: list[ParagraphHandle],
    candidates: list[_AnchorCandidate],
    issue: AuditIssue,
    *,
    require_context: bool,
    location: LocationResult,
    word_missing_reason: str,
) -> ResolvedWordTarget:
    unsupported_reason: str | None = None

    for candidate in candidates:
        located: list[_ParagraphMatch] = []
        ambiguous = False
        for handle in handles:
            match, occurrence, failure = _match_in_paragraph(
                handle,
                candidate,
                issue,
                require_context=require_context,
            )
            if failure == REASON_ANCHOR_AMBIGUOUS:
                ambiguous = True
                continue
            if failure and failure != REASON_ANCHOR_MISSING:
                unsupported_reason = failure
                continue
            if match is None or occurrence is None:
                continue
            located.append(
                _ParagraphMatch(
                    handle=handle,
                    match=match,
                    occurrence_index=occurrence,
                    strategy=candidate.strategy,
                )
            )

        if ambiguous:
            reason = (
                REASON_CELL_PARAGRAPH_AMBIGUOUS
                if len(handles) > 1
                else REASON_ANCHOR_AMBIGUOUS
            )
            return _ambiguous(
                reason,
                metadata={
                    "candidate_text": candidate.text,
                    "candidate_count": len(located),
                },
            )
        if len(located) == 1:
            item = located[0]
            strategy = item.strategy
            if item.match.occurrence_count > 1:
                if item.strategy == STRATEGY_TYPO_EXACT:
                    strategy = STRATEGY_TYPO_CONTEXT
                else:
                    strategy = f"{strategy}_occurrence"
            return _resolved(
                item.handle,
                candidate,
                item.match,
                item.occurrence_index,
                strategy=strategy,
                metadata={
                    "locator_status": location.locator_status,
                    "matched_text": location.matched_text,
                    "occurrence_count": item.match.occurrence_count,
                },
            )
        if len(located) > 1:
            return _ambiguous(
                REASON_CELL_PARAGRAPH_AMBIGUOUS,
                metadata={
                    "candidate_text": candidate.text,
                    "candidate_count": len(located),
                },
            )

    if unsupported_reason:
        return _skip(unsupported_reason)
    return _skip(word_missing_reason)


def _body_candidates(
    issue: AuditIssue,
    *,
    is_typo: bool,
) -> list[_AnchorCandidate]:
    if is_typo:
        text = issue.original_text.strip()
        return [_AnchorCandidate(text, STRATEGY_TYPO_EXACT)] if text else []
    text = issue.original_text.strip()
    return [_AnchorCandidate(text, STRATEGY_BODY_EXACT)] if text else []


def _table_candidates(
    issue: AuditIssue,
    *,
    is_typo: bool,
) -> list[_AnchorCandidate]:
    if is_typo:
        text = issue.original_text.strip()
        return [_AnchorCandidate(text, STRATEGY_TYPO_EXACT)] if text else []
    text = issue.original_text.strip()
    return [_AnchorCandidate(text, STRATEGY_TABLE_EXACT)] if text else []


def _is_nested_table_location(location: LocationResult) -> bool:
    for metadata in (
        location.metadata,
        location.source_location.metadata if location.source_location else {},
    ):
        if not isinstance(metadata, dict):
            continue
        if metadata.get("nested_table") is True:
            return True
        table_path = metadata.get("table_path")
        if isinstance(table_path, (list, tuple)) and len(table_path) > 1:
            return True
    return False


def _resolve_body(
    document: Document,
    issue: AuditIssue,
    location: LocationResult,
    *,
    is_typo: bool,
) -> ResolvedWordTarget:
    paragraph_index = location.paragraph_index
    if paragraph_index is None:
        return _skip(REASON_UNSUPPORTED_LOCATION)
    position = ParagraphPosition(
        kind=PARAGRAPH_KIND_BODY,
        body_paragraph_index=paragraph_index,
    )
    paragraph = find_document_paragraph(document, position)
    if paragraph is None:
        return _skip(REASON_PARAGRAPH_OUT_OF_RANGE)
    handle = ParagraphHandle(paragraph=paragraph, position=position)
    candidates = _body_candidates(issue, is_typo=is_typo)
    if not candidates:
        return _skip(REASON_ANCHOR_EMPTY)
    require_context = is_typo and int(
        issue.metadata.get("occurrence_count", 1) or 1
    ) > 1
    return _resolve_candidates(
        [handle],
        candidates,
        issue,
        require_context=require_context,
        location=location,
        word_missing_reason=REASON_ANCHOR_MISSING,
    )


def _resolve_table_cell_handles(
    document: Document,
    table_index: int,
    row_index: int,
    column_index: int,
) -> tuple[list[ParagraphHandle], TableCellPath | None, str | None]:
    tables = document.tables
    if table_index < 0 or table_index >= len(tables):
        return [], None, REASON_TABLE_OUT_OF_RANGE
    table = tables[table_index]
    if row_index < 0 or row_index >= len(table.rows):
        return [], None, REASON_ROW_OUT_OF_RANGE
    row = table.rows[row_index]
    if column_index < 0 or column_index >= len(row.cells):
        return [], None, REASON_COLUMN_OUT_OF_RANGE
    target_cell = row.cells[column_index]
    target_tc_identity = id(target_cell._tc)

    handles: list[ParagraphHandle] = []
    canonical: TableCellPath | None = None
    for handle in iter_document_paragraphs(document):
        if len(handle.position.table_cells) != 1:
            continue
        cell_path = handle.position.table_cells[0]
        if cell_path.table_index != table_index:
            continue
        paragraph_tc = _paragraph_ancestor_tc(handle.paragraph)
        if paragraph_tc is None or id(paragraph_tc) != target_tc_identity:
            continue
        if canonical is None:
            canonical = cell_path
        handles.append(handle)

    if not handles:
        return [], None, REASON_CELL_PARAGRAPH_NOT_FOUND
    return handles, canonical, None


def _resolve_math_in_handles(
    handles: list[ParagraphHandle],
    issue: AuditIssue,
    *,
    strategy: str,
    location: LocationResult,
    table_cells: TableCellPath | None = None,
) -> ResolvedWordTarget:
    reported = _to_decimal(
        issue.calculation.reported_value if issue.calculation else None
    )
    if reported is None:
        return _skip(REASON_MATH_ANCHOR_NOT_PRECISE)

    matches: list[
        tuple[ParagraphHandle, _NumericToken, int, TextLocationResult]
    ] = []
    ambiguous = False
    unsupported_reason: str | None = None

    for handle in handles:
        index = index_paragraph(
            handle.paragraph,
            include_existing_comments=False,
        )
        token, selection_reason = _select_math_anchor(index.text, reported)
        if selection_reason == REASON_ANCHOR_AMBIGUOUS:
            ambiguous = True
            continue
        if token is None:
            continue
        occurrence = _token_occurrence_index(index.text, token)
        if occurrence is None:
            ambiguous = True
            continue
        match = locate_text(
            index,
            token.text,
            occurrence_index=occurrence,
        )
        if match.status == STATUS_UNSUPPORTED:
            unsupported_reason = match.reason or REASON_UNSUPPORTED_STRUCTURE
            continue
        if match.status != STATUS_LOCATED:
            continue
        if match.start != token.start or match.end != token.end:
            unsupported_reason = REASON_MATH_ANCHOR_NOT_PRECISE
            continue
        matches.append((handle, token, occurrence, match))

    if ambiguous or len(matches) > 1:
        reason = (
            REASON_CELL_PARAGRAPH_AMBIGUOUS
            if len(handles) > 1
            else REASON_ANCHOR_AMBIGUOUS
        )
        return _ambiguous(
            reason,
            metadata={
                "reported_value": str(reported),
                "candidate_count": len(matches),
            },
        )
    if not matches:
        return _skip(
            unsupported_reason or REASON_MATH_ANCHOR_NOT_PRECISE,
            metadata={"reported_value": str(reported)},
        )

    handle, token, occurrence, match = matches[0]
    metadata = {
        "locator_status": location.locator_status,
        "reported_value": str(reported),
        "computed_value": _format_value(
            issue.calculation.computed_value if issue.calculation else None
        ),
        "math_anchor_source": strategy,
        "token_start": token.start,
        "token_end": token.end,
    }
    if table_cells is not None:
        metadata["table_cells"] = [table_cells.to_dict()]
    return _resolved(
        handle,
        _AnchorCandidate(token.text, strategy),
        match,
        occurrence,
        strategy=strategy,
        metadata=metadata,
    )


def _resolve_math_body(
    document: Document,
    issue: AuditIssue,
    location: LocationResult,
) -> ResolvedWordTarget:
    paragraph_index = location.paragraph_index
    if paragraph_index is None:
        return _skip(REASON_UNSUPPORTED_LOCATION)
    position = ParagraphPosition(
        kind=PARAGRAPH_KIND_BODY,
        body_paragraph_index=paragraph_index,
    )
    paragraph = find_document_paragraph(document, position)
    if paragraph is None:
        return _skip(REASON_PARAGRAPH_OUT_OF_RANGE)
    return _resolve_math_in_handles(
        [ParagraphHandle(paragraph=paragraph, position=position)],
        issue,
        strategy=STRATEGY_MATH_REPORTED_VALUE,
        location=location,
    )


def _resolve_math_table(
    document: Document,
    issue: AuditIssue,
    location: LocationResult,
) -> ResolvedWordTarget:
    if _is_nested_table_location(location):
        return _skip(REASON_NESTED_TABLE)

    table_index = location.table_index
    if table_index is None:
        return _skip(REASON_UNSUPPORTED_LOCATION)
    source = location.source_location
    if (
        source is None
        or source.value_row_index is None
        or source.value_column_index is None
    ):
        return _skip(REASON_MATH_ANCHOR_NOT_PRECISE)

    handles, canonical, failure = _resolve_table_cell_handles(
        document,
        table_index,
        source.value_row_index,
        source.value_column_index,
    )
    if failure is not None or not handles or canonical is None:
        return _skip(failure or REASON_CELL_PARAGRAPH_NOT_FOUND)
    return _resolve_math_in_handles(
        handles,
        issue,
        strategy=STRATEGY_MATH_VALUE_CELL,
        location=location,
        table_cells=canonical,
    )


def _resolve_table(
    document: Document,
    issue: AuditIssue,
    location: LocationResult,
    *,
    is_typo: bool,
) -> ResolvedWordTarget:
    if _is_nested_table_location(location):
        return _skip(REASON_NESTED_TABLE)

    table_index = location.table_index
    if table_index is None:
        return _skip(REASON_UNSUPPORTED_LOCATION)

    row_index = location.row_index
    column_index = location.column_index
    if row_index is None or column_index is None:
        return _skip(REASON_UNSUPPORTED_LOCATION)

    handles, canonical, failure = _resolve_table_cell_handles(
        document,
        table_index,
        row_index,
        column_index,
    )
    if failure is not None or not handles or canonical is None:
        return _skip(failure or REASON_CELL_PARAGRAPH_NOT_FOUND)

    candidates = _table_candidates(issue, is_typo=is_typo)
    if not candidates:
        return _skip(REASON_ANCHOR_EMPTY)
    require_context = is_typo and int(
        issue.metadata.get("occurrence_count", 1) or 1
    ) > 1
    result = _resolve_candidates(
        handles,
        candidates,
        issue,
        require_context=require_context,
        location=location,
        word_missing_reason=REASON_ANCHOR_MISSING,
    )
    if result.resolved and result.metadata is not None:
        result.metadata["table_cells"] = [canonical.to_dict()]
    return result


def resolve_word_target(
    document: Document,
    batch: Project1Batch,
    issue: AuditIssue,
    location: LocationResult,
) -> ResolvedWordTarget:
    """Resolve an audit issue to a stable Word paragraph target.

    The document itself is not modified. The result only contains a target
    when the anchor text is verified inside the expected paragraph or cell.
    """

    document_view: DocumentView | None = batch.document(location.document_id)
    if document_view is None:
        return _skip(REASON_DOCUMENT_ID_MISMATCH)
    if (
        document_view.file_type != "word"
        or location.file_type != "word"
        or (issue.location is not None and issue.location.file_type != "word")
    ):
        return _skip(REASON_NOT_WORD_FILE)
    if issue.location is not None and (
        issue.location.document_id != location.document_id
    ):
        return _skip(REASON_DOCUMENT_ID_MISMATCH)
    if location.locator_status != LOCATION_LOCATED:
        return _skip(REASON_LOCATION_NOT_LOCATED)

    is_typo = _is_typo_issue(issue)
    if is_typo:
        reason = _typo_guard(issue)
        if reason is not None:
            return _skip(reason)

    is_math = _is_math_issue(issue)
    if _is_math_type(issue) and not is_math:
        return _skip(REASON_MATH_ANCHOR_NOT_PRECISE)

    if location.table_index is not None:
        if is_math:
            return _resolve_math_table(document, issue, location)
        return _resolve_table(
            document,
            issue,
            location,
            is_typo=is_typo,
        )
    if location.paragraph_index is not None:
        if is_math:
            return _resolve_math_body(document, issue, location)
        return _resolve_body(
            document,
            issue,
            location,
            is_typo=is_typo,
        )
    return _skip(REASON_UNSUPPORTED_LOCATION)


__all__ = [
    "REASON_ANCHOR_AMBIGUOUS",
    "REASON_ANCHOR_EMPTY",
    "REASON_ANCHOR_MISSING",
    "REASON_CELL_PARAGRAPH_AMBIGUOUS",
    "REASON_CELL_PARAGRAPH_NOT_FOUND",
    "REASON_COLUMN_OUT_OF_RANGE",
    "REASON_DOCUMENT_ID_MISMATCH",
    "REASON_LOCATION_NOT_LOCATED",
    "REASON_MATH_ANCHOR_NOT_PRECISE",
    "REASON_NESTED_TABLE",
    "REASON_NOT_WORD_FILE",
    "REASON_OCCURRENCE_NOT_FOUND",
    "REASON_PARAGRAPH_OUT_OF_RANGE",
    "REASON_ROW_OUT_OF_RANGE",
    "REASON_TABLE_OUT_OF_RANGE",
    "REASON_TYPO_LOW_CONFIDENCE",
    "REASON_TYPO_MANUAL_REVIEW",
    "REASON_UNSUPPORTED_LOCATION",
    "REASON_UNSUPPORTED_STRUCTURE",
    "STRATEGY_BODY_EXACT",
    "STRATEGY_MATH_EXPRESSION",
    "STRATEGY_MATH_REPORTED_VALUE",
    "STRATEGY_MATH_VALUE_CELL",
    "STRATEGY_TABLE_EXACT",
    "STRATEGY_TYPO_CONTEXT",
    "STRATEGY_TYPO_EXACT",
    "TARGET_STATUS_AMBIGUOUS",
    "TARGET_STATUS_RESOLVED",
    "TARGET_STATUS_SKIPPED",
    "ResolvedWordTarget",
    "resolve_word_target",
]
