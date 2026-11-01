"""Locate audit issues in the original Word or PDF document.

The locator is read-only. It verifies indices and text against the real file
before reporting ``located``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf
from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from word_audit.models import (
    LOCATION_AMBIGUOUS,
    LOCATION_INVALID,
    LOCATION_LOCATED,
    LOCATION_MANUAL_REVIEW,
    LOCATION_NOT_FOUND,
    AuditIssue,
    LocationResult,
    SourceLocation,
)
from word_audit.project1_batch import (
    DocumentView,
    Project1Batch,
    TableView,
)


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    text = text.replace("\u3000", " ")
    return re.sub(r"\s+", "", text).casefold()


def _text_matches(expected: str, actual: str) -> bool:
    expected_text = _normalize_text(expected)
    actual_text = _normalize_text(actual)
    if not expected_text or not actual_text:
        return False
    return expected_text in actual_text


def _snippet(value: str, limit: int = 500) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


@dataclass
class _WordIndex:
    document: Any
    paragraphs: list[Paragraph]
    tables: list[Table]

    @classmethod
    def load(cls, path: Path) -> "_WordIndex":
        document = Document(str(path))
        paragraphs: list[Paragraph] = []
        tables: list[Table] = []
        for child in document.element.body.iterchildren():
            if isinstance(child, CT_P):
                paragraphs.append(Paragraph(child, document))
            elif isinstance(child, CT_Tbl):
                tables.append(Table(child, document))
        return cls(document=document, paragraphs=paragraphs, tables=tables)

    def paragraph_text(self, index: int) -> str:
        return self.paragraphs[index].text

    def table(self, index: int) -> Table:
        return self.tables[index]

    def row_text(self, table: Table, row_index: int) -> str:
        row = table.rows[row_index]
        return "\t".join(cell.text for cell in row.cells)

    def cell_text(self, table: Table, row_index: int, column_index: int) -> str:
        return table.rows[row_index].cells[column_index].text


@dataclass(frozen=True)
class _Candidate:
    kind: str
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "paragraph_index": self.paragraph_index,
            "table_index": self.table_index,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "text": _snippet(self.text, 120),
        }


def _search_word_candidates(
    index: _WordIndex,
    expected: str,
    *,
    limit: int = 200,
) -> list[_Candidate]:
    if not expected.strip():
        return []
    candidates: list[_Candidate] = []
    for paragraph_index, paragraph in enumerate(index.paragraphs):
        if _text_matches(expected, paragraph.text):
            candidates.append(
                _Candidate(
                    kind="paragraph",
                    paragraph_index=paragraph_index,
                    text=paragraph.text,
                )
            )
            if len(candidates) >= limit:
                return candidates
    for table_index, table in enumerate(index.tables):
        for row_index, row in enumerate(table.rows):
            for column_index, cell in enumerate(row.cells):
                if _text_matches(expected, cell.text):
                    candidates.append(
                        _Candidate(
                            kind="table_cell",
                            table_index=table_index,
                            row_index=row_index,
                            column_index=column_index,
                            text=cell.text,
                        )
                    )
                    if len(candidates) >= limit:
                        return candidates
    return candidates


def _base_result(
    issue: AuditIssue,
    location: SourceLocation | None,
    *,
    status: str,
    document_id: str,
    file_type: str,
    needs_manual_review: bool,
    confidence: float,
    failure_reason: str | None = None,
    page_number: int | None = None,
    paragraph_index: int | None = None,
    table_index: int | None = None,
    row_index: int | None = None,
    column_index: int | None = None,
    bbox: list[float] | None = None,
    matched_text: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> LocationResult:
    return LocationResult(
        issue_id=issue.issue_id,
        document_id=document_id or "unknown",
        file_type=file_type or "unknown",
        locator_status=status,
        page_number=page_number,
        paragraph_index=paragraph_index,
        table_index=table_index,
        row_index=row_index,
        column_index=column_index,
        bbox=bbox,
        matched_text=matched_text,
        locator_confidence=confidence,
        needs_manual_review=needs_manual_review,
        failure_reason=failure_reason,
        source_location=location,
        metadata=metadata or {},
    )


def _located(
    issue: AuditIssue,
    location: SourceLocation,
    *,
    document_id: str,
    file_type: str,
    confidence: float,
    matched_text: str,
    page_number: int | None = None,
    paragraph_index: int | None = None,
    table_index: int | None = None,
    row_index: int | None = None,
    column_index: int | None = None,
    bbox: list[float] | None = None,
    metadata: dict[str, Any] | None = None,
) -> LocationResult:
    return _base_result(
        issue,
        location,
        status=LOCATION_LOCATED,
        document_id=document_id,
        file_type=file_type,
        needs_manual_review=False,
        confidence=confidence,
        page_number=page_number,
        paragraph_index=paragraph_index,
        table_index=table_index,
        row_index=row_index,
        column_index=column_index,
        bbox=bbox,
        matched_text=matched_text,
        metadata=metadata,
    )


def _manual(
    issue: AuditIssue,
    location: SourceLocation | None,
    *,
    document_id: str,
    file_type: str,
    reason: str,
    confidence: float = 0.0,
    **kwargs: Any,
) -> LocationResult:
    return _base_result(
        issue,
        location,
        status=LOCATION_MANUAL_REVIEW,
        document_id=document_id,
        file_type=file_type,
        needs_manual_review=True,
        confidence=confidence,
        failure_reason=reason,
        **kwargs,
    )


def _invalid(
    issue: AuditIssue,
    location: SourceLocation | None,
    *,
    document_id: str,
    file_type: str,
    reason: str,
    **kwargs: Any,
) -> LocationResult:
    return _base_result(
        issue,
        location,
        status=LOCATION_INVALID,
        document_id=document_id,
        file_type=file_type,
        needs_manual_review=True,
        confidence=0.0,
        failure_reason=reason,
        **kwargs,
    )


def _not_found(
    issue: AuditIssue,
    location: SourceLocation | None,
    *,
    document_id: str,
    file_type: str,
    reason: str,
    **kwargs: Any,
) -> LocationResult:
    return _base_result(
        issue,
        location,
        status=LOCATION_NOT_FOUND,
        document_id=document_id,
        file_type=file_type,
        needs_manual_review=True,
        confidence=0.0,
        failure_reason=reason,
        **kwargs,
    )


def _ambiguous(
    issue: AuditIssue,
    location: SourceLocation | None,
    *,
    document_id: str,
    file_type: str,
    reason: str,
    candidates: list[_Candidate],
    confidence: float = 0.3,
    **kwargs: Any,
) -> LocationResult:
    metadata = dict(kwargs.pop("metadata", {}) or {})
    metadata["candidate_count"] = len(candidates)
    metadata["candidates"] = [candidate.to_dict() for candidate in candidates[:20]]
    return _base_result(
        issue,
        location,
        status=LOCATION_AMBIGUOUS,
        document_id=document_id,
        file_type=file_type,
        needs_manual_review=True,
        confidence=confidence,
        failure_reason=reason,
        metadata=metadata,
        **kwargs,
    )


def _resolve_document(
    batch: Project1Batch,
    issue: AuditIssue,
) -> tuple[DocumentView | None, SourceLocation | None]:
    location = issue.location
    if location is None:
        return None, None
    if not location.document_id:
        return None, location
    return batch.document(location.document_id), location


def _word_target(
    location: SourceLocation,
) -> tuple[int, int, int, bool] | None:
    """Return ``(table, row, column, used_value_cell)``."""

    if location.table_index is None:
        return None
    value_ready = (
        location.value_row_index is not None
        and location.value_column_index is not None
    )
    if value_ready:
        return (
            location.table_index,
            location.value_row_index,
            location.value_column_index,
            True,
        )
    if location.row_index is None or location.column_index is None:
        return None
    return (location.table_index, location.row_index, location.column_index, False)


def _locate_word(
    batch: Project1Batch,
    issue: AuditIssue,
    document: DocumentView,
    location: SourceLocation,
    path: Path,
) -> LocationResult:
    if not path.is_file():
        return _not_found(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            reason="word_file_not_found",
        )

    try:
        index = _WordIndex.load(path)
    except Exception as exc:  # pragma: no cover - defensive
        return _not_found(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            reason=f"word_open_failed: {exc}",
        )

    expected = issue.original_text
    if not expected.strip():
        return _manual(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            reason="no_expected_text",
        )

    target = _word_target(location)
    if location.table_index is None and location.paragraph_index is not None:
        paragraph_index = location.paragraph_index
        if paragraph_index < 0 or paragraph_index >= len(index.paragraphs):
            return _invalid(
                issue,
                location,
                document_id=document.document_id,
                file_type="word",
                reason="paragraph_index_out_of_range",
                paragraph_index=paragraph_index,
            )
        actual = index.paragraph_text(paragraph_index)
        if _text_matches(expected, actual):
            return _located(
                issue,
                location,
                document_id=document.document_id,
                file_type="word",
                confidence=0.95,
                matched_text=_snippet(actual),
                paragraph_index=paragraph_index,
                metadata={"match_scope": "paragraph", "source_file": str(path)},
            )
        candidates = _search_word_candidates(index, expected)
        if len(candidates) > 1:
            return _ambiguous(
                issue,
                location,
                document_id=document.document_id,
                file_type="word",
                reason="text_mismatch_multiple_candidates",
                candidates=candidates,
                paragraph_index=paragraph_index,
                matched_text=_snippet(actual),
            )
        return _manual(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            reason=(
                "text_mismatch_unique_candidate"
                if candidates
                else "text_mismatch"
            ),
            confidence=0.3,
            paragraph_index=paragraph_index,
            matched_text=_snippet(actual),
            metadata={
                "candidate": candidates[0].to_dict() if candidates else None,
                "source_file": str(path),
            },
        )

    if target is None:
        if location.table_index is None:
            return _invalid(
                issue,
                location,
                document_id=document.document_id,
                file_type="word",
                reason="missing_word_index",
            )
        return _invalid(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            reason="incomplete_table_cell_index",
            table_index=location.table_index,
        )

    table_index, row_index, column_index, used_value_cell = target
    if table_index < 0 or table_index >= len(index.tables):
        return _invalid(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            reason="table_index_out_of_range",
            table_index=table_index,
        )
    table = index.table(table_index)
    if row_index < 0 or row_index >= len(table.rows):
        return _invalid(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            reason="row_index_out_of_range",
            table_index=table_index,
            row_index=row_index,
        )
    row_cells = table.rows[row_index].cells
    if column_index < 0 or column_index >= len(row_cells):
        return _invalid(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            reason="column_index_out_of_range",
            table_index=table_index,
            row_index=row_index,
            column_index=column_index,
        )

    actual = index.cell_text(table, row_index, column_index)
    row_text = index.row_text(table, row_index)

    common = {
        "table_index": table_index,
        "row_index": row_index,
        "column_index": column_index,
    }
    if _text_matches(expected, actual):
        return _located(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            confidence=0.95,
            matched_text=_snippet(actual),
            metadata={
                "match_scope": "cell",
                "used_value_cell": used_value_cell,
                "source_file": str(path),
            },
            **common,
        )
    if _text_matches(expected, row_text):
        return _located(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            confidence=0.85,
            matched_text=_snippet(actual),
            metadata={
                "match_scope": "row",
                "used_value_cell": used_value_cell,
                "row_text": _snippet(row_text),
                "source_file": str(path),
            },
            **common,
        )

    if used_value_cell and (
        location.row_index is not None and location.column_index is not None
    ):
        anchor_actual = index.cell_text(
            table, location.row_index, location.column_index
        )
        if _text_matches(expected, anchor_actual):
            return _located(
                issue,
                location,
                document_id=document.document_id,
                file_type="word",
                confidence=0.8,
                matched_text=_snippet(anchor_actual),
                table_index=table_index,
                row_index=location.row_index,
                column_index=location.column_index,
                metadata={
                    "match_scope": "anchor_cell_fallback",
                    "source_file": str(path),
                },
            )

    candidates = _search_word_candidates(index, expected)
    if len(candidates) > 1:
        return _ambiguous(
            issue,
            location,
            document_id=document.document_id,
            file_type="word",
            reason="text_mismatch_multiple_candidates",
            candidates=candidates,
            matched_text=_snippet(actual),
            **common,
        )
    return _manual(
        issue,
        location,
        document_id=document.document_id,
        file_type="word",
        reason=(
            "text_mismatch_unique_candidate" if candidates else "text_mismatch"
        ),
        confidence=0.3,
        matched_text=_snippet(actual),
        metadata={
            "candidate": candidates[0].to_dict() if candidates else None,
            "row_text": _snippet(row_text),
            "used_value_cell": used_value_cell,
            "source_file": str(path),
        },
        **common,
    )


def _pdf_cell_bbox(
    batch: Project1Batch,
    location: SourceLocation,
) -> list[float] | None:
    if location.table_index is None:
        return None
    row_index = location.value_row_index
    column_index = location.value_column_index
    if row_index is None or column_index is None:
        row_index = location.row_index
        column_index = location.column_index
    if row_index is None or column_index is None:
        return None
    table = batch.table(location.document_id, location.table_index)
    if table is None:
        return None
    for cell in table.cells:
        if (
            cell.get("row_index") == row_index
            and cell.get("column_index") == column_index
        ):
            bbox = cell.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                return [float(item) for item in bbox]
    return None


def _pdf_row_text(
    batch: Project1Batch,
    location: SourceLocation,
) -> str | None:
    if location.table_index is None:
        return None
    row_index = location.value_row_index
    if row_index is None:
        row_index = location.row_index
    if row_index is None:
        return None
    table = batch.table(location.document_id, location.table_index)
    if table is None or row_index < 0 or row_index >= len(table.rows):
        return None
    return "\t".join(str(cell) for cell in table.rows[row_index])


def _bbox_is_valid(bbox: list[float] | None, width: float, height: float) -> tuple[bool, str]:
    if bbox is None or len(bbox) != 4:
        return False, "bbox_invalid"
    if not all(isinstance(value, (int, float)) for value in bbox):
        return False, "bbox_invalid"
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0:
        return False, "bbox_invalid"
    tolerance = 1.0
    if (
        x0 < -tolerance
        or y0 < -tolerance
        or x1 > width + tolerance
        or y1 > height + tolerance
    ):
        return False, "bbox_outside_page"
    return True, ""


def _locate_pdf(
    batch: Project1Batch,
    issue: AuditIssue,
    document: DocumentView,
    location: SourceLocation,
    path: Path,
) -> LocationResult:
    if not path.is_file():
        return _not_found(
            issue,
            location,
            document_id=document.document_id,
            file_type="pdf",
            reason="pdf_file_not_found",
        )

    cell_row = (
        location.value_row_index
        if location.value_row_index is not None
        and location.value_column_index is not None
        else location.row_index
    )
    cell_column = (
        location.value_column_index
        if location.value_row_index is not None
        and location.value_column_index is not None
        else location.column_index
    )
    if location.page_number is None:
        return _invalid(
            issue,
            location,
            document_id=document.document_id,
            file_type="pdf",
            reason="pdf_page_number_missing",
            table_index=location.table_index,
            row_index=cell_row,
            column_index=cell_column,
        )
    page_number = location.page_number


    table = (
        batch.table(location.document_id, location.table_index)
        if location.table_index is not None
        else None
    )
    coordinate_space: str | None = None
    if table is not None:
        unified = table.metadata.get("unified_table")
        if isinstance(unified, dict):
            coordinate_space = unified.get("coordinate_space")
        coordinate_space = coordinate_space or table.metadata.get("coordinate_space")

    chosen_bbox = location.bbox
    bbox_source = "issue_location"
    cell_bbox = _pdf_cell_bbox(batch, location)
    if cell_bbox is not None:
        chosen_bbox = cell_bbox
        bbox_source = "project1_cell"

    try:
        pdf = pymupdf.open(str(path))
    except Exception as exc:  # pragma: no cover - defensive
        return _not_found(
            issue,
            location,
            document_id=document.document_id,
            file_type="pdf",
            reason=f"pdf_open_failed: {exc}",
        )

    try:
        if page_number < 1 or page_number > pdf.page_count:
            return _invalid(
                issue,
                location,
                document_id=document.document_id,
                file_type="pdf",
                reason="page_number_out_of_range",
                page_number=page_number,
                table_index=location.table_index,
                row_index=cell_row,
                column_index=cell_column,
            )
        page = pdf.load_page(page_number - 1)
        page_rect = page.rect

        if coordinate_space is not None and coordinate_space != "pdf":
            return _manual(
                issue,
                location,
                document_id=document.document_id,
                file_type="pdf",
                reason="coordinate_space_not_pdf",
                confidence=0.2,
                page_number=page_number,
                table_index=location.table_index,
                row_index=cell_row,
                column_index=cell_column,
                bbox=chosen_bbox,
                metadata={"coordinate_space": coordinate_space},
            )

        valid, reason = _bbox_is_valid(
            chosen_bbox, float(page_rect.width), float(page_rect.height)
        )
        if not valid and bbox_source == "project1_cell":
            valid, reason = _bbox_is_valid(
                location.bbox, float(page_rect.width), float(page_rect.height)
            )
            if valid:
                chosen_bbox = location.bbox
                bbox_source = "issue_location"
        if not valid:
            return _invalid(
                issue,
                location,
                document_id=document.document_id,
                file_type="pdf",
                reason=reason,
                page_number=page_number,
                table_index=location.table_index,
                row_index=cell_row,
                column_index=cell_column,
                bbox=chosen_bbox,
                metadata={
                    "page_size": [float(page_rect.width), float(page_rect.height)],
                    "bbox_source": bbox_source,
                },
            )

        if page.rotation:
            return _manual(
                issue,
                location,
                document_id=document.document_id,
                file_type="pdf",
                reason="page_rotation_not_supported",
                confidence=0.2,
                page_number=page_number,
                table_index=location.table_index,
                row_index=cell_row,
                column_index=cell_column,
                bbox=chosen_bbox,
                metadata={
                    "page_rotation": int(page.rotation),
                    "page_size": [float(page_rect.width), float(page_rect.height)],
                    "bbox_source": bbox_source,
                },
            )

        expected = issue.original_text
        if not expected.strip():
            return _manual(
                issue,
                location,
                document_id=document.document_id,
                file_type="pdf",
                reason="no_expected_text",
                page_number=page_number,
                table_index=location.table_index,
                row_index=cell_row,
                column_index=cell_column,
                bbox=chosen_bbox,
            )

        rect = pymupdf.Rect(chosen_bbox)
        try:
            extracted = page.get_textbox(rect)
        except Exception as exc:  # pragma: no cover - defensive
            return _manual(
                issue,
                location,
                document_id=document.document_id,
                file_type="pdf",
                reason=f"text_extraction_failed: {exc}",
                page_number=page_number,
                table_index=location.table_index,
                row_index=cell_row,
                column_index=cell_column,
                bbox=chosen_bbox,
            )

        if not extracted.strip():
            return _manual(
                issue,
                location,
                document_id=document.document_id,
                file_type="pdf",
                reason="no_text_in_bbox",
                confidence=0.2,
                page_number=page_number,
                table_index=location.table_index,
                row_index=cell_row,
                column_index=cell_column,
                bbox=chosen_bbox,
                metadata={
                    "page_size": [float(page_rect.width), float(page_rect.height)],
                    "bbox_source": bbox_source,
                },
            )

        common = {
            "page_number": page_number,
            "table_index": location.table_index,
            "row_index": cell_row,
            "column_index": cell_column,
            "bbox": chosen_bbox,
            "metadata": {
                "page_size": [float(page_rect.width), float(page_rect.height)],
                "page_rotation": int(page.rotation),
                "bbox_source": bbox_source,
                "coordinate_space": "pdf",
                "source_file": str(path),
            },
        }
        if _text_matches(expected, extracted):
            return _located(
                issue,
                location,
                document_id=document.document_id,
                file_type="pdf",
                confidence=0.95 if bbox_source == "project1_cell" else 0.9,
                matched_text=_snippet(extracted),
                metadata={**common["metadata"], "match_scope": "cell"},
                **{key: value for key, value in common.items() if key != "metadata"},
            )

        row_text = _pdf_row_text(batch, location)
        if row_text and _text_matches(expected, row_text):
            return _located(
                issue,
                location,
                document_id=document.document_id,
                file_type="pdf",
                confidence=0.85,
                matched_text=_snippet(extracted),
                metadata={
                    **common["metadata"],
                    "match_scope": "row",
                    "row_text": _snippet(row_text),
                },
                **{key: value for key, value in common.items() if key != "metadata"},
            )

        page_text = page.get_text("text")
        found_on_page = _text_matches(expected, page_text)
        return _manual(
            issue,
            location,
            document_id=document.document_id,
            file_type="pdf",
            reason=(
                "text_mismatch_found_on_page"
                if found_on_page
                else "text_mismatch"
            ),
            confidence=0.3,
            matched_text=_snippet(extracted),
            metadata={**common["metadata"], "page_text_matched": found_on_page},
            **{key: value for key, value in common.items() if key != "metadata"},
        )
    finally:
        pdf.close()


def locate_issue(batch: Project1Batch, issue: AuditIssue) -> LocationResult:
    document, location = _resolve_document(batch, issue)
    if location is None:
        return _manual(
            issue,
            None,
            document_id="unknown",
            file_type="unknown",
            reason="location_missing",
        )
    if document is None:
        return _not_found(
            issue,
            location,
            document_id=location.document_id or "unknown",
            file_type=location.file_type or "unknown",
            reason="document_not_found_in_batch",
        )

    file_type = (location.file_type or document.file_type or "").lower()
    if file_type != document.file_type.lower():
        return _invalid(
            issue,
            location,
            document_id=document.document_id,
            file_type=file_type or document.file_type,
            reason="file_type_mismatch",
        )

    path = Path(document.source_file)
    if file_type == "word":
        return _locate_word(batch, issue, document, location, path)
    if file_type == "pdf":
        return _locate_pdf(batch, issue, document, location, path)
    return _invalid(
        issue,
        location,
        document_id=document.document_id,
        file_type=file_type or "unknown",
        reason="unsupported_file_type",
    )


def locate_issues(
    batch: Project1Batch,
    issues: list[AuditIssue],
) -> list[LocationResult]:
    return [locate_issue(batch, issue) for issue in issues]


def summarize_location_results(results: list[LocationResult]) -> dict[str, Any]:
    counts = {
        LOCATION_LOCATED: 0,
        LOCATION_AMBIGUOUS: 0,
        LOCATION_NOT_FOUND: 0,
        LOCATION_INVALID: 0,
        LOCATION_MANUAL_REVIEW: 0,
    }
    for result in results:
        counts[result.locator_status] = counts.get(result.locator_status, 0) + 1
    return {
        "total": len(results),
        "located": counts[LOCATION_LOCATED],
        "ambiguous": counts[LOCATION_AMBIGUOUS],
        "not_found": counts[LOCATION_NOT_FOUND],
        "invalid_location": counts[LOCATION_INVALID],
        "manual_review": counts[LOCATION_MANUAL_REVIEW],
        "needs_manual_review": sum(
            1 for result in results if result.needs_manual_review
        ),
    }

