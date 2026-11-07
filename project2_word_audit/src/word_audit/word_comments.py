"""Run indexing and safe run splitting for native Word comments.

This module intentionally does not create comments yet. It provides the
low-level, testable pieces needed by the native comment writer:

* index the text of a paragraph by run, including hyperlink runs;
* locate a text span and map it to run offsets;
* split simple text runs while preserving ``w:rPr``;
* reject complex run structures that cannot be split safely.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.hyperlink import Hyperlink
from docx.text.paragraph import Paragraph
from docx.text.run import Run

COMMENT_AUTHOR = "DocumentAuditSystem"
COMMENT_INITIALS = "DAS"

STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

PARAGRAPH_KIND_BODY = "body"
PARAGRAPH_KIND_TABLE_CELL = "table_cell"

STATUS_LOCATED = "located"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NOT_FOUND = "not_found"
STATUS_UNSUPPORTED = "unsupported"
STATUS_SPLIT = "split"
STATUS_NOOP = "noop"
STATUS_PREPARED = "prepared"

REASON_EMPTY_TEXT = "empty_text"
REASON_TEXT_NOT_FOUND = "text_not_found"
REASON_AMBIGUOUS_TEXT = "ambiguous_text_occurrence"
REASON_OCCURRENCE_OUT_OF_RANGE = "occurrence_index_out_of_range"
REASON_INVALID_OFFSET = "invalid_offset"
REASON_RUN_PARENT = "run_parent_not_paragraph"
REASON_LOCATION_NOT_LOCATED = "location_not_located"
REASON_HYPERLINK = "hyperlink"
REASON_CONTENT_CONTROL = "content_control"
REASON_EXISTING_COMMENT = "existing_comment_range"
REASON_TRACKED_CHANGE = "tracked_change"
REASON_UNSUPPORTED_STRUCTURE = "unsupported_structure"
REASON_TAB = "tab"
REASON_BREAK = "break"
REASON_CR = "carriage_return"
REASON_DRAWING = "drawing"
REASON_OBJECT = "object_or_picture"
REASON_FIELD = "field_code"
REASON_FOOTNOTE = "footnote_or_endnote_reference"
REASON_UNSUPPORTED_TEXT = "unsupported_text_element"
REASON_UNSUPPORTED_RUN_CONTENT = "unsupported_run_content"
REASON_EMPTY_COMMENT = "empty_comment_text"
REASON_CROSS_RUN = "cross_run_not_supported"
REASON_OVERLAPPING_COMMENT = "overlapping_comment_range"
REASON_UNSAFE_EXISTING_COMMENT = "unsafe_existing_comment_range"
REASON_COMMENT_CREATION_FAILED = "comment_creation_failed"
REASON_COMMENT_SNAPSHOT_FAILED = "comment_transaction_snapshot_failed"
REASON_COMMENT_ROLLBACK_FAILED = "comment_rollback_failed"
REASON_OUTPUT_OVERWRITES_SOURCE = "output_path_overwrites_source"
REASON_SOURCE_FILE_NOT_FOUND = "source_file_not_found"
REASON_SOURCE_OPEN_FAILED = "source_open_failed"
REASON_PARAGRAPH_INDEX = "paragraph_index_out_of_range"
REASON_PARAGRAPH_POSITION = "paragraph_position_not_found"
REASON_OUTPUT_SAVE_FAILED = "output_save_failed"
REASON_OUTPUT_REOPEN_FAILED = "output_reopen_failed"
REASON_SOURCE_CHANGED = "source_file_changed"
REASON_PARAGRAPH_TEXT_CHANGED = "paragraph_text_changed_after_split"

_ALLOWED_RUN_CHILDREN = {
    qn("w:rPr"),
    qn("w:t"),
}

_BLOCKING_PARAGRAPH_XPATHS = (
    (".//w:sdt", REASON_CONTENT_CONTROL),
    (".//w:fldSimple", REASON_FIELD),
    (".//w:ins | .//w:del", REASON_TRACKED_CHANGE),
    (".//w:smartTag | .//w:customXml", REASON_UNSUPPORTED_STRUCTURE),
)

_COMMENT_XPATHS = (
    "./w:commentRangeStart | ./w:commentRangeEnd | .//w:commentReference"
)


type RunOrNone = Run | None


@dataclass(frozen=True)
class RunTextSegment:
    """One run's text and its character range inside a paragraph."""

    run: Run
    text: str
    start: int
    end: int
    segment_index: int
    safe_to_split: bool
    unsupported_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParagraphTextIndex:
    """Ordered text index of a paragraph, including hyperlink runs."""

    paragraph: Paragraph
    text: str
    segments: tuple[RunTextSegment, ...]
    unsupported_reasons: tuple[str, ...] = ()


def _validate_dict_keys(
    data: object,
    *,
    expected: set[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(data, dict):
        raise TypeError(f"{label} must be a dict")
    missing = expected - set(data)
    if missing:
        raise ValueError(
            f"{label} missing fields: {', '.join(sorted(missing))}"
        )
    unexpected = set(data) - expected
    if unexpected:
        raise ValueError(
            f"{label} has unexpected fields: {', '.join(sorted(unexpected))}"
        )
    return data


def _validate_non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


@dataclass(frozen=True)
class TableCellPath:
    """Stable path to one table cell inside a document container."""

    table_index: int
    row_index: int
    cell_index: int

    def to_dict(self) -> dict[str, int]:
        return {
            "table_index": self.table_index,
            "row_index": self.row_index,
            "cell_index": self.cell_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TableCellPath:
        expected = {"table_index", "row_index", "cell_index"}
        payload = _validate_dict_keys(
            data,
            expected=expected,
            label="table cell path",
        )
        return cls(
            table_index=_validate_non_negative_int(
                payload["table_index"],
                "table_index",
            ),
            row_index=_validate_non_negative_int(
                payload["row_index"],
                "row_index",
            ),
            cell_index=_validate_non_negative_int(
                payload["cell_index"],
                "cell_index",
            ),
        )


@dataclass(frozen=True)
class ParagraphPosition:
    """Stable position of a paragraph in the document body or a table cell."""

    kind: str
    body_paragraph_index: int | None = None
    table_cells: tuple[TableCellPath, ...] = ()
    cell_paragraph_index: int = 0
    document_order: int = 0
    text: str = ""

    @property
    def is_table_paragraph(self) -> bool:
        return bool(self.table_cells)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "body_paragraph_index": self.body_paragraph_index,
            "table_cells": [cell.to_dict() for cell in self.table_cells],
            "cell_paragraph_index": self.cell_paragraph_index,
            "document_order": self.document_order,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ParagraphPosition:
        expected = {
            "kind",
            "body_paragraph_index",
            "table_cells",
            "cell_paragraph_index",
            "document_order",
            "text",
        }
        payload = _validate_dict_keys(
            data,
            expected=expected,
            label="paragraph position",
        )
        kind = payload["kind"]
        if kind not in {PARAGRAPH_KIND_BODY, PARAGRAPH_KIND_TABLE_CELL}:
            raise ValueError(f"unknown paragraph position kind: {kind!r}")

        raw_cells = payload["table_cells"]
        if not isinstance(raw_cells, (list, tuple)):
            raise TypeError("table_cells must be a list or tuple")
        table_cells = tuple(
            TableCellPath.from_dict(cell) for cell in raw_cells
        )

        raw_body_index = payload["body_paragraph_index"]
        cell_paragraph_index = _validate_non_negative_int(
            payload["cell_paragraph_index"],
            "cell_paragraph_index",
        )
        document_order = _validate_non_negative_int(
            payload["document_order"],
            "document_order",
        )
        text = payload["text"]
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        if kind == PARAGRAPH_KIND_BODY:
            if raw_body_index is None:
                raise ValueError(
                    "body_paragraph_index is required for body paragraphs"
                )
            if table_cells:
                raise ValueError(
                    "body paragraphs must not have table_cells"
                )
            if cell_paragraph_index != 0:
                raise ValueError(
                    "body paragraphs must have cell_paragraph_index 0"
                )
            return cls(
                kind=kind,
                body_paragraph_index=_validate_non_negative_int(
                    raw_body_index,
                    "body_paragraph_index",
                ),
                table_cells=(),
                cell_paragraph_index=0,
                document_order=document_order,
                text=text,
            )

        if raw_body_index is not None:
            raise ValueError(
                "table paragraph body_paragraph_index must be null"
            )
        if not table_cells:
            raise ValueError("table paragraphs must have table_cells")
        return cls(
            kind=kind,
            body_paragraph_index=None,
            table_cells=table_cells,
            cell_paragraph_index=cell_paragraph_index,
            document_order=document_order,
            text=text,
        )


@dataclass(frozen=True)
class ParagraphHandle:
    """A paragraph proxy together with its stable position."""

    paragraph: Paragraph
    position: ParagraphPosition


@dataclass(frozen=True)
class TextLocationResult:
    """Result of locating a text span inside a ParagraphTextIndex."""

    status: str
    reason: str | None
    index: ParagraphTextIndex | None = None
    start: int | None = None
    end: int | None = None
    first_segment_index: int | None = None
    last_segment_index: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    occurrence_index: int | None = None
    occurrence_count: int = 0
    occurrences: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class RunSplitResult:
    """Result of splitting one simple text run at a character offset."""

    status: str
    reason: str | None
    left: RunOrNone
    right: RunOrNone


@dataclass(frozen=True)
class SpanPrepareResult:
    """Result of splitting boundary runs so a text span is isolated."""

    status: str
    reason: str | None
    first_run: RunOrNone
    last_run: RunOrNone
    splits: tuple[RunSplitResult, ...] = ()


def _dedupe(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reason for reason in reasons if reason))


def _ancestor_reasons(run: Run) -> list[str]:
    reasons: list[str] = []
    parent = run._r.getparent()
    while parent is not None:
        tag = parent.tag
        if tag == qn("w:hyperlink"):
            reasons.append(REASON_HYPERLINK)
        elif tag == qn("w:sdt"):
            reasons.append(REASON_CONTENT_CONTROL)
        elif tag == qn("w:fldSimple"):
            reasons.append(REASON_FIELD)
        elif tag in {qn("w:ins"), qn("w:del")}:
            reasons.append(REASON_TRACKED_CHANGE)
        elif tag in {qn("w:smartTag"), qn("w:customXml")}:
            reasons.append(REASON_UNSUPPORTED_STRUCTURE)
        parent = parent.getparent()
    return reasons


def run_unsupported_reasons(run: Run) -> tuple[str, ...]:
    """Return reasons this run cannot be split as a simple text run."""

    reasons = _ancestor_reasons(run)
    for child in run._r.iterchildren():
        tag = child.tag
        if tag in _ALLOWED_RUN_CHILDREN:
            continue
        if tag == qn("w:tab"):
            reasons.append(REASON_TAB)
        elif tag == qn("w:br"):
            reasons.append(REASON_BREAK)
        elif tag == qn("w:cr"):
            reasons.append(REASON_CR)
        elif tag == qn("w:drawing"):
            reasons.append(REASON_DRAWING)
        elif tag in {qn("w:object"), qn("w:pict")}:
            reasons.append(REASON_OBJECT)
        elif tag in {qn("w:fldChar"), qn("w:instrText")}:
            reasons.append(REASON_FIELD)
        elif tag in {qn("w:footnoteReference"), qn("w:endnoteReference")}:
            reasons.append(REASON_FOOTNOTE)
        elif tag in {qn("w:noBreakHyphen"), qn("w:softHyphen"), qn("w:ptab")}:
            reasons.append(REASON_UNSUPPORTED_TEXT)
        elif tag == qn("w:commentReference"):
            reasons.append(REASON_EXISTING_COMMENT)
        else:
            reasons.append(REASON_UNSUPPORTED_RUN_CONTENT)
    return _dedupe(reasons)


def is_simple_text_run(run: Run) -> bool:
    """Return True when a run contains only text and run properties."""

    return not run_unsupported_reasons(run)


def paragraph_unsupported_reasons(
    paragraph: Paragraph,
    *,
    include_existing_comments: bool = True,
) -> tuple[str, ...]:
    """Return paragraph-level structures that make safe anchoring impossible."""

    reasons: list[str] = []
    for xpath, reason in _BLOCKING_PARAGRAPH_XPATHS:
        if paragraph._p.xpath(xpath):
            reasons.append(reason)
    if include_existing_comments and paragraph._p.xpath(_COMMENT_XPATHS):
        reasons.append(REASON_EXISTING_COMMENT)
    return _dedupe(reasons)


def index_paragraph(
    paragraph: Paragraph,
    *,
    include_existing_comments: bool = True,
) -> ParagraphTextIndex:
    """Index all text-bearing runs of a paragraph in document order."""

    segments: list[RunTextSegment] = []
    text_parts: list[str] = []
    offset = 0

    for item in paragraph.iter_inner_content():
        if isinstance(item, Run):
            run_items = [item]
        elif isinstance(item, Hyperlink):
            run_items = list(item.runs)
        else:  # pragma: no cover - defensive for future python-docx types
            continue

        for run in run_items:
            run_text = run.text
            reasons = list(run_unsupported_reasons(run))
            if isinstance(item, Hyperlink) and REASON_HYPERLINK not in reasons:
                reasons.insert(0, REASON_HYPERLINK)
            reasons_tuple = _dedupe(reasons)
            start = offset
            end = start + len(run_text)
            segments.append(
                RunTextSegment(
                    run=run,
                    text=run_text,
                    start=start,
                    end=end,
                    segment_index=len(segments),
                    safe_to_split=not reasons_tuple,
                    unsupported_reasons=reasons_tuple,
                )
            )
            text_parts.append(run_text)
            offset = end

    return ParagraphTextIndex(
        paragraph=paragraph,
        text="".join(text_parts),
        segments=tuple(segments),
        unsupported_reasons=paragraph_unsupported_reasons(
            paragraph,
            include_existing_comments=include_existing_comments,
        ),
    )


def _find_occurrences(text: str, needle: str) -> tuple[tuple[int, int], ...]:
    occurrences: list[tuple[int, int]] = []
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            break
        occurrences.append((index, index + len(needle)))
        start = index + 1
    return tuple(occurrences)


def _segment_for_start(
    segments: tuple[RunTextSegment, ...],
    offset: int,
) -> int | None:
    for segment in segments:
        if segment.start <= offset < segment.end:
            return segment.segment_index
    return None


def _segment_for_end(
    segments: tuple[RunTextSegment, ...],
    offset: int,
) -> int | None:
    for segment in segments:
        if segment.start < offset <= segment.end:
            return segment.segment_index
    return None


def _unsupported_result(
    index: ParagraphTextIndex,
    reason: str,
    *,
    occurrence_count: int = 0,
    occurrences: tuple[tuple[int, int], ...] = (),
) -> TextLocationResult:
    return TextLocationResult(
        status=STATUS_UNSUPPORTED,
        reason=reason,
        index=index,
        occurrence_count=occurrence_count,
        occurrences=occurrences,
    )


def locate_text(
    index: ParagraphTextIndex,
    needle: str,
    *,
    occurrence_index: int | None = None,
) -> TextLocationResult:
    """Locate ``needle`` in a paragraph index without modifying the document.

    ``occurrence_index`` is zero-based. If it is omitted and the text occurs
    more than once, the result is ``ambiguous`` and no span is selected.
    """

    if not needle:
        return TextLocationResult(
            status=STATUS_NOT_FOUND,
            reason=REASON_EMPTY_TEXT,
            index=index,
        )

    if index.unsupported_reasons:
        return _unsupported_result(index, ",".join(index.unsupported_reasons))

    occurrences = _find_occurrences(index.text, needle)
    if not occurrences:
        return TextLocationResult(
            status=STATUS_NOT_FOUND,
            reason=REASON_TEXT_NOT_FOUND,
            index=index,
        )

    if occurrence_index is None:
        if len(occurrences) > 1:
            return TextLocationResult(
                status=STATUS_AMBIGUOUS,
                reason=REASON_AMBIGUOUS_TEXT,
                index=index,
                occurrence_count=len(occurrences),
                occurrences=occurrences,
            )
        selected_index = 0
    else:
        if occurrence_index < 0 or occurrence_index >= len(occurrences):
            return TextLocationResult(
                status=STATUS_NOT_FOUND,
                reason=REASON_OCCURRENCE_OUT_OF_RANGE,
                index=index,
                occurrence_count=len(occurrences),
                occurrences=occurrences,
            )
        selected_index = occurrence_index

    start, end = occurrences[selected_index]
    first_segment_index = _segment_for_start(index.segments, start)
    last_segment_index = _segment_for_end(index.segments, end)
    if first_segment_index is None or last_segment_index is None:
        return TextLocationResult(
            status=STATUS_NOT_FOUND,
            reason=REASON_TEXT_NOT_FOUND,
            index=index,
            occurrence_count=len(occurrences),
            occurrences=occurrences,
        )

    touched = index.segments[first_segment_index : last_segment_index + 1]
    unsupported: list[str] = []
    for segment in touched:
        unsupported.extend(segment.unsupported_reasons)
    if unsupported:
        return _unsupported_result(
            index,
            ",".join(_dedupe(unsupported)),
            occurrence_count=len(occurrences),
            occurrences=occurrences,
        )

    first_segment = index.segments[first_segment_index]
    last_segment = index.segments[last_segment_index]
    return TextLocationResult(
        status=STATUS_LOCATED,
        reason=None,
        index=index,
        start=start,
        end=end,
        first_segment_index=first_segment_index,
        last_segment_index=last_segment_index,
        start_offset=start - first_segment.start,
        end_offset=end - last_segment.start,
        occurrence_index=selected_index,
        occurrence_count=len(occurrences),
        occurrences=occurrences,
    )


def split_run(
    paragraph: Paragraph,
    run: Run,
    offset: int,
) -> RunSplitResult:
    """Split a simple text run at ``offset``, preserving ``w:rPr``.

    The original run keeps the left part and a copied run receives the right
    part. No comment markup is added by this function.
    """

    if isinstance(offset, bool) or not isinstance(offset, int):
        return RunSplitResult(STATUS_UNSUPPORTED, REASON_INVALID_OFFSET, None, None)

    if run._r.getparent() is not paragraph._p:
        return RunSplitResult(STATUS_UNSUPPORTED, REASON_RUN_PARENT, None, None)

    reasons = run_unsupported_reasons(run)
    if reasons:
        return RunSplitResult(
            STATUS_UNSUPPORTED,
            ",".join(reasons),
            None,
            None,
        )

    text = run.text
    if offset <= 0:
        return RunSplitResult(STATUS_NOOP, None, None, run)
    if offset >= len(text):
        return RunSplitResult(STATUS_NOOP, None, run, None)

    new_r = copy.deepcopy(run._r)
    run._r.addnext(new_r)
    left_text = text[:offset]
    right_text = text[offset:]
    run.text = left_text
    right_run = Run(new_r, run._parent)
    right_run.text = right_text
    return RunSplitResult(STATUS_SPLIT, None, run, right_run)


def _unsupported_span(reason: str) -> SpanPrepareResult:
    return SpanPrepareResult(STATUS_UNSUPPORTED, reason, None, None)


def prepare_text_span(
    index: ParagraphTextIndex,
    location: TextLocationResult,
) -> SpanPrepareResult:
    """Split boundary runs so ``location`` becomes one run range.

    This function only splits runs. It does not add a comment. The caller can
    later pass ``first_run`` and ``last_run`` to ``Document.add_comment()``.
    """

    if location.status != STATUS_LOCATED or location.index is not index:
        return _unsupported_span(REASON_LOCATION_NOT_LOCATED)

    if index.unsupported_reasons:
        return _unsupported_span(",".join(index.unsupported_reasons))

    first_index = location.first_segment_index
    last_index = location.last_segment_index
    start_offset = location.start_offset
    end_offset = location.end_offset
    if (
        first_index is None
        or last_index is None
        or start_offset is None
        or end_offset is None
    ):
        return _unsupported_span(REASON_LOCATION_NOT_LOCATED)

    touched = index.segments[first_index : last_index + 1]
    unsupported: list[str] = []
    for segment in touched:
        unsupported.extend(segment.unsupported_reasons)
    if unsupported:
        return _unsupported_span(",".join(_dedupe(unsupported)))

    splits: list[RunSplitResult] = []
    if first_index == last_index:
        segment = index.segments[first_index]
        run = segment.run
        target_run = run
        if end_offset < len(segment.text):
            end_split = split_run(index.paragraph, run, end_offset)
            splits.append(end_split)
            if end_split.status != STATUS_SPLIT:
                return _unsupported_span(
                    end_split.reason or REASON_UNSUPPORTED_RUN_CONTENT
                )
            target_run = end_split.left
        if start_offset > 0:
            start_split = split_run(index.paragraph, target_run, start_offset)
            splits.append(start_split)
            if start_split.status != STATUS_SPLIT:
                return _unsupported_span(
                    start_split.reason or REASON_UNSUPPORTED_RUN_CONTENT
                )
            target_run = start_split.right
        return SpanPrepareResult(
            STATUS_PREPARED,
            None,
            target_run,
            target_run,
            tuple(splits),
        )

    first_segment = index.segments[first_index]
    last_segment = index.segments[last_index]

    last_target = last_segment.run
    if end_offset < len(last_segment.text):
        end_split = split_run(index.paragraph, last_segment.run, end_offset)
        splits.append(end_split)
        if end_split.status != STATUS_SPLIT:
            return _unsupported_span(
                end_split.reason or REASON_UNSUPPORTED_RUN_CONTENT
            )
        last_target = end_split.left

    first_target = first_segment.run
    if start_offset > 0:
        start_split = split_run(index.paragraph, first_segment.run, start_offset)
        splits.append(start_split)
        if start_split.status != STATUS_SPLIT:
            return _unsupported_span(
                start_split.reason or REASON_UNSUPPORTED_RUN_CONTENT
            )
        first_target = start_split.right

    return SpanPrepareResult(
        STATUS_PREPARED,
        None,
        first_target,
        last_target,
        tuple(splits),
    )


@dataclass(frozen=True)
class NativeCommentResult:
    """Result of adding one native comment in an in-memory document."""

    status: str
    reason: str | None
    comment_id: int | None = None
    first_run: RunOrNone = None
    last_run: RunOrNone = None
    start: int | None = None
    end: int | None = None
    anchor_text: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class NativeCommentFileResult:
    """Result of annotating one single-run text span in a DOCX file."""

    status: str
    reason: str | None
    source_path: Path
    output_path: Path | None
    source_sha256: str
    output_sha256: str | None
    comment_id: int | None = None
    anchor_text: str | None = None
    error_detail: str | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix or ".docx"
    index = 1
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _body_paragraphs(document: Document) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraphs.append(Paragraph(child, document))
    return paragraphs


def _iter_cell_paragraphs(
    cell: object,
    cell_path: tuple[TableCellPath, ...],
    order_state: list[int],
) -> Iterator[ParagraphHandle]:
    paragraph_index = 0
    table_index = 0
    for child in cell._tc.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, cell)
            yield ParagraphHandle(
                paragraph=paragraph,
                position=ParagraphPosition(
                    kind=PARAGRAPH_KIND_TABLE_CELL,
                    table_cells=cell_path,
                    cell_paragraph_index=paragraph_index,
                    document_order=order_state[0],
                    text=paragraph.text,
                ),
            )
            order_state[0] += 1
            paragraph_index += 1
        elif isinstance(child, CT_Tbl):
            table = Table(child, cell)
            yield from _iter_table_paragraphs(
                table,
                table_index,
                cell_path,
                order_state,
            )
            table_index += 1


def _iter_table_paragraphs(
    table: Table,
    table_index: int,
    parent_cells: tuple[TableCellPath, ...],
    order_state: list[int],
) -> Iterator[ParagraphHandle]:
    seen_cells: set[int] = set()
    for row_index, row in enumerate(table.rows):
        for cell_index, cell in enumerate(row.cells):
            cell_identity = id(cell._tc)
            if cell_identity in seen_cells:
                continue
            seen_cells.add(cell_identity)
            cell_path = parent_cells + (
                TableCellPath(
                    table_index=table_index,
                    row_index=row_index,
                    cell_index=cell_index,
                ),
            )
            yield from _iter_cell_paragraphs(cell, cell_path, order_state)


def iter_document_paragraphs(document: Document) -> Iterator[ParagraphHandle]:
    """Yield body, table-cell, and nested-table paragraphs without duplicates."""

    order_state = [0]
    body_paragraph_index = 0
    body_table_index = 0
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            yield ParagraphHandle(
                paragraph=paragraph,
                position=ParagraphPosition(
                    kind=PARAGRAPH_KIND_BODY,
                    body_paragraph_index=body_paragraph_index,
                    document_order=order_state[0],
                    text=paragraph.text,
                ),
            )
            order_state[0] += 1
            body_paragraph_index += 1
        elif isinstance(child, CT_Tbl):
            table = Table(child, document)
            yield from _iter_table_paragraphs(
                table,
                body_table_index,
                (),
                order_state,
            )
            body_table_index += 1


def find_document_paragraph(
    document: Document,
    position: ParagraphPosition,
) -> Paragraph | None:
    """Resolve a stable ParagraphPosition back to a paragraph proxy."""

    if position.kind == PARAGRAPH_KIND_BODY:
        if position.body_paragraph_index is None:
            return None
        paragraphs = _body_paragraphs(document)
        index = position.body_paragraph_index
        if index < 0 or index >= len(paragraphs):
            return None
        return paragraphs[index]

    if not position.table_cells:
        return None

    container: object = document
    for cell_path in position.table_cells:
        tables = container.tables
        if cell_path.table_index < 0 or cell_path.table_index >= len(tables):
            return None
        table = tables[cell_path.table_index]
        if cell_path.row_index < 0 or cell_path.row_index >= len(table.rows):
            return None
        row = table.rows[cell_path.row_index]
        if cell_path.cell_index < 0 or cell_path.cell_index >= len(row.cells):
            return None
        container = row.cells[cell_path.cell_index]

    paragraphs = container.paragraphs
    index = position.cell_paragraph_index
    if index < 0 or index >= len(paragraphs):
        return None
    return paragraphs[index]


def _restore_paragraph(
    paragraph: Paragraph,
    backup: object,
    parent: object,
    position: int,
) -> None:
    current = paragraph._p
    if current.getparent() is parent:
        parent.remove(current)
    parent.insert(position, backup)


@dataclass(frozen=True)
class _CommentPartSnapshot:
    part: object | None
    element: object | None
    comment_ids: frozenset[int]
    relationship_ids: frozenset[str]


@dataclass(frozen=True)
class _CommentTransactionSnapshot:
    paragraph: Paragraph
    paragraph_backup: object
    paragraph_xml: str
    parent: object
    position: int
    comments: _CommentPartSnapshot


def _comments_part_or_none(document: Document) -> object | None:
    try:
        return document.part.part_related_by(RT.COMMENTS)
    except KeyError:
        return None


def _comment_ids_from_element(element: object) -> frozenset[int]:
    comment_ids: set[int] = set()
    for comment in element.xpath("./w:comment"):  # type: ignore[attr-defined]
        raw_id = comment.get(qn("w:id"))
        if raw_id is None:
            continue
        try:
            comment_ids.add(int(raw_id))
        except ValueError:
            continue
    return frozenset(comment_ids)


def _comment_relationship_ids(document: Document) -> frozenset[str]:
    return frozenset(
        rel_id
        for rel_id, relationship in document.part.rels.items()
        if relationship.reltype == RT.COMMENTS
    )


def _snapshot_comment_transaction(
    document: Document,
    paragraph: Paragraph,
) -> _CommentTransactionSnapshot:
    parent = paragraph._p.getparent()
    if parent is None:
        raise RuntimeError("paragraph has no parent")
    position = parent.index(paragraph._p)
    comments_part = _comments_part_or_none(document)
    if comments_part is None:
        comments_snapshot = _CommentPartSnapshot(
            part=None,
            element=None,
            comment_ids=frozenset(),
            relationship_ids=_comment_relationship_ids(document),
        )
    else:
        comments_element = copy.deepcopy(comments_part.element)
        comments_snapshot = _CommentPartSnapshot(
            part=comments_part,
            element=comments_element,
            comment_ids=_comment_ids_from_element(comments_element),
            relationship_ids=_comment_relationship_ids(document),
        )
    return _CommentTransactionSnapshot(
        paragraph=paragraph,
        paragraph_backup=copy.deepcopy(paragraph._p),
        paragraph_xml=paragraph._p.xml,
        parent=parent,
        position=position,
        comments=comments_snapshot,
    )


def _restore_paragraph_safely(
    paragraph: Paragraph,
    backup: object,
    parent: object,
    position: int,
) -> str | None:
    try:
        _restore_paragraph(paragraph, backup, parent, position)
    except Exception as exc:  # noqa: BLE001 - rollback must report failure
        return f"paragraph rollback failed: {exc}"
    return None


def _restore_comments_part(
    document: Document,
    snapshot: _CommentPartSnapshot,
) -> None:
    current_part = _comments_part_or_none(document)
    if snapshot.part is not None:
        if current_part is None:
            document.part.relate_to(snapshot.part, RT.COMMENTS)
            current_part = _comments_part_or_none(document)
        if current_part is not snapshot.part:
            raise RuntimeError("comments part changed unexpectedly")
        restored_element = copy.deepcopy(snapshot.element)
        current_part._element = restored_element  # type: ignore[attr-defined]
        current_part._comments = restored_element  # type: ignore[attr-defined]
        restored_ids = _comment_ids_from_element(restored_element)
        if restored_ids != snapshot.comment_ids:
            raise RuntimeError("comments content restore verification failed")
        return

    if current_part is not None:
        for rel_id, relationship in list(document.part.rels.items()):
            if (
                relationship.reltype == RT.COMMENTS
                and rel_id not in snapshot.relationship_ids
            ):
                document.part.rels.pop(rel_id, None)
        if _comment_relationship_ids(document) != snapshot.relationship_ids:
            raise RuntimeError("comments relationship rollback failed")


def _rollback_comment_transaction(
    document: Document,
    snapshot: _CommentTransactionSnapshot,
) -> str | None:
    errors: list[str] = []
    paragraph_error = _restore_paragraph_safely(
        snapshot.paragraph,
        snapshot.paragraph_backup,
        snapshot.parent,
        snapshot.position,
    )
    if paragraph_error:
        errors.append(paragraph_error)

    try:
        _restore_comments_part(document, snapshot.comments)
    except Exception as exc:  # noqa: BLE001 - rollback must report failure
        errors.append(f"comments rollback failed: {exc}")

    try:
        restored_paragraph = snapshot.parent[snapshot.position]
        if restored_paragraph is not snapshot.paragraph_backup:
            errors.append("paragraph rollback verification failed")
        elif snapshot.paragraph_backup.xml != snapshot.paragraph_xml:
            errors.append("paragraph content restore verification failed")
    except Exception as exc:  # noqa: BLE001 - rollback must report failure
        errors.append(f"paragraph rollback verification failed: {exc}")

    return "; ".join(errors) if errors else None


def _skipped_comment(reason: str) -> NativeCommentResult:
    return NativeCommentResult(STATUS_SKIPPED, reason)


def _failed_comment(
    reason: str,
    *,
    error_detail: str | None = None,
) -> NativeCommentResult:
    return NativeCommentResult(
        STATUS_FAILED,
        reason,
        error_detail=error_detail,
    )


def _target_range_text(
    paragraph: Paragraph,
    first_run: Run,
    last_run: Run,
) -> str:
    parts: list[str] = []
    collecting = False
    for child in paragraph._p.iterchildren():
        if child is first_run._r:
            collecting = True
        if collecting and child.tag == qn("w:r"):
            parts.append(Run(child, paragraph).text)
        if child is last_run._r:
            break
    return "".join(parts)


def _comment_marker_ids(
    paragraph: Paragraph,
) -> tuple[set[str], set[str], set[str]]:
    starts: set[str] = set()
    ends: set[str] = set()
    references: set[str] = set()
    for child in paragraph._p.iterchildren():
        if child.tag == qn("w:commentRangeStart"):
            identifier = child.get(qn("w:id"))
            if identifier is not None:
                starts.add(identifier)
        elif child.tag == qn("w:commentRangeEnd"):
            identifier = child.get(qn("w:id"))
            if identifier is not None:
                ends.add(identifier)
        elif child.tag == qn("w:r"):
            for reference in child.iter(qn("w:commentReference")):
                identifier = reference.get(qn("w:id"))
                if identifier is not None:
                    references.add(identifier)
    return starts, ends, references


def existing_comment_spans(
    paragraph: Paragraph,
) -> tuple[tuple[int, int], ...]:
    """Return closed existing comment ranges as paragraph character spans."""

    starts: dict[str, int] = {}
    spans: dict[str, list[int | None]] = {}
    offset = 0
    for child in paragraph._p.iterchildren():
        if child.tag == qn("w:commentRangeStart"):
            identifier = child.get(qn("w:id"))
            if identifier is not None and identifier not in spans:
                starts[identifier] = offset
                spans[identifier] = [offset, None]
        elif child.tag == qn("w:commentRangeEnd"):
            identifier = child.get(qn("w:id"))
            if identifier in spans and spans[identifier][1] is None:
                spans[identifier][1] = offset
        elif child.tag == qn("w:r"):
            offset += len(Run(child, paragraph).text)
        elif child.tag == qn("w:hyperlink"):
            offset += len(Hyperlink(child, paragraph).text)

    return tuple(
        (int(start), int(end))
        for start, end in spans.values()
        if start is not None and end is not None
    )


def _overlaps_existing_comment(
    start: int,
    end: int,
    spans: tuple[tuple[int, int], ...],
) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def _add_comment_impl(
    document: Document,
    index: ParagraphTextIndex,
    location: TextLocationResult,
    comment_text: str,
    *,
    author: str,
    initials: str,
    require_single_run: bool,
) -> NativeCommentResult:
    if not comment_text.strip():
        return _skipped_comment(REASON_EMPTY_COMMENT)
    if location.status != STATUS_LOCATED or location.index is not index:
        return _skipped_comment(location.reason or REASON_LOCATION_NOT_LOCATED)

    first_index = location.first_segment_index
    last_index = location.last_segment_index
    start = location.start
    end = location.end
    if (
        first_index is None
        or last_index is None
        or start is None
        or end is None
    ):
        return _skipped_comment(REASON_LOCATION_NOT_LOCATED)
    if require_single_run and first_index != last_index:
        return _skipped_comment(REASON_CROSS_RUN)
    if first_index > last_index:
        return _skipped_comment(REASON_LOCATION_NOT_LOCATED)

    paragraph = index.paragraph
    blocking = paragraph_unsupported_reasons(
        paragraph,
        include_existing_comments=False,
    )
    if blocking:
        return _skipped_comment(",".join(blocking))

    starts, ends, references = _comment_marker_ids(paragraph)
    if not (starts == ends == references):
        return _skipped_comment(REASON_UNSAFE_EXISTING_COMMENT)

    touched = index.segments[first_index : last_index + 1]
    unsupported: list[str] = []
    for segment in touched:
        unsupported.extend(segment.unsupported_reasons)
    if unsupported:
        return _skipped_comment(",".join(_dedupe(unsupported)))

    first_segment = index.segments[first_index]
    last_segment = index.segments[last_index]
    if start < first_segment.start or end > last_segment.end or start >= end:
        return _skipped_comment(REASON_TEXT_NOT_FOUND)

    target_text = index.text[start:end]
    if _overlaps_existing_comment(
        start,
        end,
        existing_comment_spans(paragraph),
    ):
        return _skipped_comment(REASON_OVERLAPPING_COMMENT)

    start_offset = start - first_segment.start
    end_offset = end - last_segment.start
    before_text = paragraph.text
    try:
        transaction = _snapshot_comment_transaction(document, paragraph)
    except Exception as exc:  # noqa: BLE001 - report a stable failure reason
        return _failed_comment(
            REASON_COMMENT_SNAPSHOT_FAILED,
            error_detail=str(exc),
        )
    backup = transaction.paragraph_backup
    parent = transaction.parent
    position = transaction.position

    splits: list[RunSplitResult] = []
    if first_index == last_index:
        target_run = first_segment.run
        if end_offset < len(first_segment.text):
            end_split = split_run(paragraph, target_run, end_offset)
            splits.append(end_split)
            if end_split.status != STATUS_SPLIT:
                _restore_paragraph(paragraph, backup, parent, position)
                return _skipped_comment(
                    end_split.reason or REASON_UNSUPPORTED_RUN_CONTENT
                )
            target_run = end_split.left
        if start_offset > 0:
            start_split = split_run(paragraph, target_run, start_offset)
            splits.append(start_split)
            if start_split.status != STATUS_SPLIT:
                _restore_paragraph(paragraph, backup, parent, position)
                return _skipped_comment(
                    start_split.reason or REASON_UNSUPPORTED_RUN_CONTENT
                )
            target_run = start_split.right
        first_target = target_run
        last_target = target_run
    else:
        last_target = last_segment.run
        if end_offset < len(last_segment.text):
            end_split = split_run(paragraph, last_target, end_offset)
            splits.append(end_split)
            if end_split.status != STATUS_SPLIT:
                _restore_paragraph(paragraph, backup, parent, position)
                return _skipped_comment(
                    end_split.reason or REASON_UNSUPPORTED_RUN_CONTENT
                )
            last_target = end_split.left

        first_target = first_segment.run
        if start_offset > 0:
            start_split = split_run(paragraph, first_target, start_offset)
            splits.append(start_split)
            if start_split.status != STATUS_SPLIT:
                _restore_paragraph(paragraph, backup, parent, position)
                return _skipped_comment(
                    start_split.reason or REASON_UNSUPPORTED_RUN_CONTENT
                )
            first_target = start_split.right

    if paragraph.text != before_text:
        _restore_paragraph(paragraph, backup, parent, position)
        return _failed_comment(REASON_PARAGRAPH_TEXT_CHANGED)
    if _target_range_text(paragraph, first_target, last_target) != target_text:
        _restore_paragraph(paragraph, backup, parent, position)
        return _failed_comment(REASON_TEXT_NOT_FOUND)

    runs: Run | list[Run]
    if first_target is last_target:
        runs = first_target
    else:
        runs = [first_target, last_target]
    try:
        comment = document.add_comment(
            runs,
            text=comment_text,
            author=author,
            initials=initials,
        )
    except Exception as exc:  # noqa: BLE001 - report a stable failure reason
        rollback_error = _rollback_comment_transaction(document, transaction)
        if rollback_error is not None:
            return _failed_comment(
                REASON_COMMENT_ROLLBACK_FAILED,
                error_detail=f"{exc}; {rollback_error}",
            )
        return _failed_comment(
            REASON_COMMENT_CREATION_FAILED,
            error_detail=str(exc),
        )

    return NativeCommentResult(
        status=STATUS_APPLIED,
        reason=None,
        comment_id=int(comment.comment_id),
        first_run=first_target,
        last_run=last_target,
        start=start,
        end=end,
        anchor_text=target_text,
    )


def add_span_comment(
    document: Document,
    index: ParagraphTextIndex,
    location: TextLocationResult,
    comment_text: str,
    *,
    author: str = COMMENT_AUTHOR,
    initials: str = COMMENT_INITIALS,
) -> NativeCommentResult:
    """Add a native comment for a same-paragraph span of simple text runs."""

    return _add_comment_impl(
        document,
        index,
        location,
        comment_text,
        author=author,
        initials=initials,
        require_single_run=False,
    )


def add_single_run_comment(
    document: Document,
    index: ParagraphTextIndex,
    location: TextLocationResult,
    comment_text: str,
    *,
    author: str = COMMENT_AUTHOR,
    initials: str = COMMENT_INITIALS,
) -> NativeCommentResult:
    """Add a native comment for a span fully inside one simple text run."""

    return _add_comment_impl(
        document,
        index,
        location,
        comment_text,
        author=author,
        initials=initials,
        require_single_run=True,
    )


def _file_result(
    status: str,
    reason: str | None,
    source: Path,
    source_hash: str,
    *,
    output: Path | None = None,
    output_hash: str | None = None,
    comment_id: int | None = None,
    anchor_text: str | None = None,
    error_detail: str | None = None,
) -> NativeCommentFileResult:
    return NativeCommentFileResult(
        status=status,
        reason=reason,
        source_path=source,
        output_path=output,
        source_sha256=source_hash,
        output_sha256=output_hash,
        comment_id=comment_id,
        anchor_text=anchor_text,
        error_detail=error_detail,
    )


def _annotate_file_impl(
    source_path: str | Path,
    output_path: str | Path,
    paragraph_lookup: Callable[[Document], Paragraph | None],
    missing_paragraph_reason: str,
    needle: str,
    comment_text: str,
    *,
    occurrence_index: int | None,
    author: str,
    initials: str,
    require_single_run: bool,
) -> NativeCommentFileResult:
    """Shared file-level implementation for body and table paragraphs."""

    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        return _file_result(
            STATUS_SKIPPED,
            REASON_SOURCE_FILE_NOT_FOUND,
            source,
            "",
        )

    source_hash = _sha256_file(source)
    output = Path(output_path).expanduser()
    if not output.suffix:
        output = output.with_suffix(".docx")
    if output.resolve() == source:
        return _file_result(
            STATUS_SKIPPED,
            REASON_OUTPUT_OVERWRITES_SOURCE,
            source,
            source_hash,
        )
    if not comment_text.strip():
        return _file_result(
            STATUS_SKIPPED,
            REASON_EMPTY_COMMENT,
            source,
            source_hash,
        )

    try:
        document = Document(str(source))
    except Exception:  # noqa: BLE001 - stable failure reason
        return _file_result(
            STATUS_FAILED,
            REASON_SOURCE_OPEN_FAILED,
            source,
            source_hash,
        )
    paragraph = paragraph_lookup(document)
    if paragraph is None:
        return _file_result(
            STATUS_SKIPPED,
            missing_paragraph_reason,
            source,
            source_hash,
        )

    index = index_paragraph(paragraph, include_existing_comments=False)
    location = locate_text(
        index,
        needle,
        occurrence_index=occurrence_index,
    )
    if location.status != STATUS_LOCATED:
        return _file_result(
            STATUS_SKIPPED,
            location.reason or location.status,
            source,
            source_hash,
        )

    result = _add_comment_impl(
        document,
        index,
        location,
        comment_text,
        author=author,
        initials=initials,
        require_single_run=require_single_run,
    )
    if result.status != STATUS_APPLIED:
        return _file_result(
            result.status,
            result.reason,
            source,
            source_hash,
            comment_id=result.comment_id,
            anchor_text=result.anchor_text,
            error_detail=result.error_detail,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output = _unique_output_path(output)
    try:
        document.save(str(output))
    except Exception:  # noqa: BLE001 - stable failure reason
        output.unlink(missing_ok=True)
        return _file_result(
            STATUS_FAILED,
            REASON_OUTPUT_SAVE_FAILED,
            source,
            source_hash,
            comment_id=result.comment_id,
            anchor_text=result.anchor_text,
        )

    after_source_hash = _sha256_file(source)
    if after_source_hash != source_hash:
        output.unlink(missing_ok=True)
        return _file_result(
            STATUS_FAILED,
            REASON_SOURCE_CHANGED,
            source,
            source_hash,
        )

    try:
        reopened = Document(str(output))
        _ = reopened.paragraphs
    except Exception:  # noqa: BLE001 - stable failure reason
        output.unlink(missing_ok=True)
        return _file_result(
            STATUS_FAILED,
            REASON_OUTPUT_REOPEN_FAILED,
            source,
            source_hash,
            comment_id=result.comment_id,
            anchor_text=result.anchor_text,
        )

    return _file_result(
        STATUS_APPLIED,
        None,
        source,
        source_hash,
        output=output,
        output_hash=_sha256_file(output),
        comment_id=result.comment_id,
        anchor_text=result.anchor_text,
    )


def _body_paragraph_lookup(
    paragraph_index: int,
) -> Callable[[Document], Paragraph | None]:
    def lookup(document: Document) -> Paragraph | None:
        paragraphs = _body_paragraphs(document)
        if paragraph_index < 0 or paragraph_index >= len(paragraphs):
            return None
        return paragraphs[paragraph_index]

    return lookup


def annotate_single_run_file(
    source_path: str | Path,
    output_path: str | Path,
    paragraph_index: int,
    needle: str,
    comment_text: str,
    *,
    occurrence_index: int | None = None,
    author: str = COMMENT_AUTHOR,
    initials: str = COMMENT_INITIALS,
) -> NativeCommentFileResult:
    """Annotate a text span that must be fully inside one simple run."""

    return _annotate_file_impl(
        source_path,
        output_path,
        _body_paragraph_lookup(paragraph_index),
        REASON_PARAGRAPH_INDEX,
        needle,
        comment_text,
        occurrence_index=occurrence_index,
        author=author,
        initials=initials,
        require_single_run=True,
    )


def annotate_span_file(
    source_path: str | Path,
    output_path: str | Path,
    paragraph_index: int,
    needle: str,
    comment_text: str,
    *,
    occurrence_index: int | None = None,
    author: str = COMMENT_AUTHOR,
    initials: str = COMMENT_INITIALS,
) -> NativeCommentFileResult:
    """Annotate a same-paragraph text span across one or more simple runs."""

    return _annotate_file_impl(
        source_path,
        output_path,
        _body_paragraph_lookup(paragraph_index),
        REASON_PARAGRAPH_INDEX,
        needle,
        comment_text,
        occurrence_index=occurrence_index,
        author=author,
        initials=initials,
        require_single_run=False,
    )


def annotate_document_file(
    source_path: str | Path,
    output_path: str | Path,
    position: ParagraphPosition,
    needle: str,
    comment_text: str,
    *,
    occurrence_index: int | None = None,
    author: str = COMMENT_AUTHOR,
    initials: str = COMMENT_INITIALS,
) -> NativeCommentFileResult:
    """Annotate a body, table-cell, or nested-table paragraph by position."""

    return _annotate_file_impl(
        source_path,
        output_path,
        lambda document: find_document_paragraph(document, position),
        REASON_PARAGRAPH_POSITION,
        needle,
        comment_text,
        occurrence_index=occurrence_index,
        author=author,
        initials=initials,
        require_single_run=False,
    )


__all__ = [
    "COMMENT_AUTHOR",
    "COMMENT_INITIALS",
    "PARAGRAPH_KIND_BODY",
    "PARAGRAPH_KIND_TABLE_CELL",
    "STATUS_AMBIGUOUS",
    "STATUS_APPLIED",
    "STATUS_FAILED",
    "STATUS_LOCATED",
    "STATUS_NOOP",
    "STATUS_NOT_FOUND",
    "STATUS_PREPARED",
    "STATUS_SKIPPED",
    "STATUS_SPLIT",
    "STATUS_UNSUPPORTED",
    "NativeCommentFileResult",
    "NativeCommentResult",
    "ParagraphHandle",
    "ParagraphPosition",
    "ParagraphTextIndex",
    "RunSplitResult",
    "RunTextSegment",
    "SpanPrepareResult",
    "TableCellPath",
    "TextLocationResult",
    "add_single_run_comment",
    "add_span_comment",
    "annotate_document_file",
    "annotate_single_run_file",
    "annotate_span_file",
    "find_document_paragraph",
    "index_paragraph",
    "is_simple_text_run",
    "iter_document_paragraphs",
    "locate_text",
    "paragraph_unsupported_reasons",
    "prepare_text_span",
    "run_unsupported_reasons",
    "split_run",
]
