"""Write red-text audit comments into a copy of a Word document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.shared import RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph

from word_audit.annotation_common import (
    anchor_for,
    build_comment_text,
    is_synthetic_issue,
    unique_path,
)
from word_audit.models import AnnotationResult, AuditIssue, LocationResult
from word_audit.project1_batch import DocumentView


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


def _write_red_paragraph(paragraph: Paragraph, text: str) -> None:
    run = paragraph.add_run()
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if index:
            run.add_break()
        run.add_text(line)
    run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)


def _annotation_metadata(result: LocationResult) -> dict[str, Any]:
    return {
        "locator_status": result.locator_status,
        "locator_confidence": result.locator_confidence,
        "annotation_kind": "word",
        "synthetic": bool(result.metadata.get("synthetic", False)),
        "source_bbox_source": result.metadata.get("bbox_source"),
    }


def _applied_annotation(
    issue: AuditIssue,
    result: LocationResult,
    document: DocumentView,
    *,
    word_anchor: dict[str, Any],
    kind: str,
) -> AnnotationResult:
    metadata = _annotation_metadata(result)
    metadata["synthetic"] = is_synthetic_issue(issue) or metadata["synthetic"]
    metadata["annotation_kind"] = kind
    return AnnotationResult(
        annotation_id=uuid.uuid4().hex,
        issue_id=issue.issue_id,
        document_id=result.document_id or document.document_id,
        comment_text=build_comment_text(issue),
        anchor=anchor_for(result, document),
        status="applied",
        word_anchor=dict(word_anchor),
        metadata=metadata,
    )


def _failed_annotation(
    issue: AuditIssue,
    result: LocationResult,
    document: DocumentView | None,
    error: str,
    *,
    word_anchor: dict[str, Any] | None = None,
) -> AnnotationResult:
    metadata = _annotation_metadata(result)
    metadata["synthetic"] = is_synthetic_issue(issue) or metadata["synthetic"]
    return AnnotationResult(
        annotation_id=uuid.uuid4().hex,
        issue_id=issue.issue_id,
        document_id=result.document_id or (document.document_id if document else "unknown"),
        comment_text=build_comment_text(issue),
        anchor=anchor_for(result, document),
        status="failed",
        error=error,
        word_anchor=dict(word_anchor) if word_anchor else None,
        metadata=metadata,
    )


def _mark_failed(annotation: AnnotationResult, error: str) -> None:
    annotation.status = "failed"
    annotation.error = error
    annotation.applied_at = None
    annotation.metadata["output_file"] = None


def _cell_indices(result: LocationResult) -> tuple[int | None, int | None]:
    row_index = result.row_index
    column_index = result.column_index
    location = result.source_location
    if location is not None:
        if row_index is None:
            row_index = (
                location.value_row_index
                if location.value_row_index is not None
                else location.row_index
            )
        if column_index is None:
            column_index = (
                location.value_column_index
                if location.value_column_index is not None
                else location.column_index
            )
    return row_index, column_index


def annotate_word_document(
    document: DocumentView,
    items: list[tuple[AuditIssue, LocationResult]],
    output_dir: str | Path,
) -> tuple[list[AnnotationResult], Path | None]:
    """Annotate one Word document and return annotations plus output path."""

    if not items:
        return [], None

    source_path = Path(document.source_file)
    if not source_path.is_file():
        return [
            _failed_annotation(
                issue, result, document, "word_file_not_found"
            )
            for issue, result in items
        ], None

    try:
        index = _WordIndex.load(source_path)
    except Exception as exc:
        return [
            _failed_annotation(
                issue, result, document, f"word_open_failed: {exc}"
            )
            for issue, result in items
        ], None

    annotations: list[AnnotationResult] = []
    applied: list[AnnotationResult] = []
    paragraph_insert_state: dict[int, Any] = {}

    for issue, result in items:
        if result.table_index is not None:
            table_index = result.table_index
            row_index, column_index = _cell_indices(result)
            word_anchor = {
                "table_index": table_index,
                "row_index": row_index,
                "column_index": column_index,
                "insertion": "inside_table_cell",
            }
            if table_index < 0 or table_index >= len(index.tables):
                annotations.append(
                    _failed_annotation(
                        issue,
                        result,
                        document,
                        "table_index_out_of_range",
                        word_anchor=word_anchor,
                    )
                )
                continue
            table = index.tables[table_index]
            if row_index is None or row_index < 0 or row_index >= len(table.rows):
                annotations.append(
                    _failed_annotation(
                        issue,
                        result,
                        document,
                        "row_index_out_of_range",
                        word_anchor=word_anchor,
                    )
                )
                continue
            row = table.rows[row_index]
            if (
                column_index is None
                or column_index < 0
                or column_index >= len(row.cells)
            ):
                annotations.append(
                    _failed_annotation(
                        issue,
                        result,
                        document,
                        "column_index_out_of_range",
                        word_anchor=word_anchor,
                    )
                )
                continue
            try:
                cell = row.cells[column_index]
                paragraph = cell.add_paragraph()
                _write_red_paragraph(paragraph, build_comment_text(issue))
            except Exception as exc:  # pragma: no cover - defensive
                annotations.append(
                    _failed_annotation(
                        issue,
                        result,
                        document,
                        f"word_cell_annotation_failed: {exc}",
                        word_anchor=word_anchor,
                    )
                )
                continue
            annotation = _applied_annotation(
                issue,
                result,
                document,
                word_anchor=word_anchor,
                kind="word_table_cell",
            )
            annotations.append(annotation)
            applied.append(annotation)
            continue

        paragraph_index = result.paragraph_index
        word_anchor = {
            "paragraph_index": paragraph_index,
            "table_index": None,
            "row_index": None,
            "column_index": None,
            "insertion": "after_paragraph",
        }
        if (
            paragraph_index is None
            or paragraph_index < 0
            or paragraph_index >= len(index.paragraphs)
        ):
            annotations.append(
                _failed_annotation(
                    issue,
                    result,
                    document,
                    "paragraph_index_out_of_range",
                    word_anchor=word_anchor,
                )
            )
            continue

        try:
            target = index.paragraphs[paragraph_index]
            anchor_xml = paragraph_insert_state.get(paragraph_index, target._p)
            new_paragraph_xml = OxmlElement("w:p")
            anchor_xml.addnext(new_paragraph_xml)
            paragraph_insert_state[paragraph_index] = new_paragraph_xml
            new_paragraph = Paragraph(new_paragraph_xml, target._parent)
            _write_red_paragraph(new_paragraph, build_comment_text(issue))
        except Exception as exc:  # pragma: no cover - defensive
            annotations.append(
                _failed_annotation(
                    issue,
                    result,
                    document,
                    f"word_paragraph_annotation_failed: {exc}",
                    word_anchor=word_anchor,
                )
            )
            continue

        annotation = _applied_annotation(
            issue,
            result,
            document,
            word_anchor=word_anchor,
            kind="word_paragraph",
        )
        annotations.append(annotation)
        applied.append(annotation)

    if not applied:
        return annotations, None

    output_path = unique_path(
        output_dir,
        source_path.stem + "_annotated",
        source_path.suffix or ".docx",
    )
    try:
        index.document.save(str(output_path))
    except Exception as exc:  # pragma: no cover - defensive
        for annotation in applied:
            _mark_failed(annotation, f"word_save_failed: {exc}")
        return annotations, None

    for annotation in applied:
        annotation.metadata["output_file"] = str(output_path)
    return annotations, output_path
