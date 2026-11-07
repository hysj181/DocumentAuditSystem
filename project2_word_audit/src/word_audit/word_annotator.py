"""Write native Word comments into a copy of a Word document."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from docx import Document

from word_audit.annotation_common import (
    anchor_for,
    build_comment_text,
    is_synthetic_issue,
    unique_path,
)
from word_audit.models import AnnotationResult, AuditIssue, LocationResult
from word_audit.project1_batch import DocumentView, Project1Batch
from word_audit.word_comments import (
    STATUS_APPLIED,
    STATUS_FAILED,
    STATUS_LOCATED,
    STATUS_SKIPPED,
    add_span_comment,
    find_document_paragraph,
    index_paragraph,
    locate_text,
)
from word_audit.word_target import (
    TARGET_STATUS_RESOLVED,
    ResolvedWordTarget,
    resolve_word_target,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _word_anchor(
    target: ResolvedWordTarget,
    *,
    comment_id: int | None = None,
) -> dict[str, Any]:
    position = target.position
    if position is None:
        return {}
    anchor: dict[str, Any] = {
        "insertion": "native_comment",
        "paragraph_index": position.body_paragraph_index,
        "table_index": None,
        "row_index": None,
        "column_index": None,
        "cell_paragraph_index": position.cell_paragraph_index,
        "document_order": position.document_order,
        "table_cells": [cell.to_dict() for cell in position.table_cells],
        "position": position.to_dict(),
        "anchor_text": target.anchor_text,
        "occurrence_index": target.occurrence_index,
        "anchor_strategy": target.anchor_strategy,
        "target_status": target.status,
    }
    if position.table_cells:
        cell = position.table_cells[-1]
        anchor["table_index"] = cell.table_index
        anchor["row_index"] = cell.row_index
        anchor["column_index"] = cell.cell_index
    if comment_id is not None:
        anchor["comment_id"] = comment_id
    return anchor


def _annotation_result(
    issue: AuditIssue,
    location: LocationResult,
    document: DocumentView,
    target: ResolvedWordTarget | None,
    *,
    status: str,
    reason: str | None = None,
    comment_id: int | None = None,
    error_detail: str | None = None,
) -> AnnotationResult:
    metadata: dict[str, Any] = {
        "locator_status": location.locator_status,
        "locator_confidence": location.locator_confidence,
        "annotation_kind": "word_native_comment",
        "synthetic": (
            is_synthetic_issue(issue)
            or bool(location.metadata.get("synthetic", False))
        ),
        "manual_review": status == STATUS_SKIPPED,
        "target_status": target.status if target is not None else "unresolved",
        "target_failure_reason": (
            target.failure_reason if target is not None else reason
        ),
        "comment_id": comment_id,
        "anchor_text": target.anchor_text if target is not None else None,
        "anchor_strategy": (
            target.anchor_strategy if target is not None else None
        ),
        "occurrence_index": (
            target.occurrence_index if target is not None else None
        ),
        "position": (
            target.position.to_dict()
            if target is not None and target.position is not None
            else None
        ),
        "target_metadata": dict(target.metadata) if target is not None else {},
    }
    if error_detail:
        metadata["error_detail"] = error_detail
    return AnnotationResult(
        annotation_id=uuid.uuid4().hex,
        issue_id=issue.issue_id,
        document_id=location.document_id or document.document_id,
        comment_text=build_comment_text(issue),
        anchor=anchor_for(location, document),
        status=status,
        error=reason,
        word_anchor=(
            _word_anchor(target, comment_id=comment_id)
            if target is not None and target.position is not None
            else None
        ),
        metadata=metadata,
    )


def _mark_failed(
    annotation: AnnotationResult,
    error: str,
    detail: str | None = None,
) -> None:
    annotation.status = STATUS_FAILED
    annotation.error = error
    annotation.applied_at = None
    annotation.metadata["output_file"] = None
    annotation.metadata["manual_review"] = False
    if detail:
        annotation.metadata["error_detail"] = detail


def _target_failure_annotation(
    issue: AuditIssue,
    location: LocationResult,
    document: DocumentView,
    target: ResolvedWordTarget,
) -> AnnotationResult:
    reason = target.failure_reason or target.status
    return _annotation_result(
        issue,
        location,
        document,
        target,
        status=STATUS_SKIPPED,
        reason=reason,
    )


def _comment_failure_annotation(
    issue: AuditIssue,
    location: LocationResult,
    document: DocumentView,
    target: ResolvedWordTarget,
    *,
    reason: str,
    error_detail: str | None = None,
) -> AnnotationResult:
    return _annotation_result(
        issue,
        location,
        document,
        target,
        status=STATUS_FAILED,
        reason=reason,
        error_detail=error_detail,
    )


def _resolve_and_annotate(
    word_document: Document,
    batch: Project1Batch,
    document: DocumentView,
    issue: AuditIssue,
    location: LocationResult,
) -> AnnotationResult:
    try:
        target = resolve_word_target(
            word_document,
            batch,
            issue,
            location,
        )
    except Exception as exc:  # noqa: BLE001 - report a stable failure reason
        return _annotation_result(
            issue,
            location,
            document,
            None,
            status=STATUS_FAILED,
            reason="word_target_resolution_failed",
            error_detail=str(exc),
        )

    if target.status != TARGET_STATUS_RESOLVED:
        return _target_failure_annotation(
            issue,
            location,
            document,
            target,
        )

    if (
        target.position is None
        or target.anchor_text is None
        or target.occurrence_index is None
    ):
        return _comment_failure_annotation(
            issue,
            location,
            document,
            target,
            reason="word_target_incomplete",
            error_detail="resolved target is missing position, anchor or occurrence",
        )

    paragraph = find_document_paragraph(word_document, target.position)
    if paragraph is None:
        return _comment_failure_annotation(
            issue,
            location,
            document,
            target,
            reason="word_target_paragraph_not_found",
        )

    index = index_paragraph(
        paragraph,
        include_existing_comments=False,
    )
    located = locate_text(
        index,
        target.anchor_text,
        occurrence_index=target.occurrence_index,
    )
    if located.status != STATUS_LOCATED:
        return _comment_failure_annotation(
            issue,
            location,
            document,
            target,
            reason=located.reason or located.status,
        )

    try:
        native = add_span_comment(
            word_document,
            index,
            located,
            build_comment_text(issue),
        )
    except Exception as exc:  # noqa: BLE001 - report a stable failure reason
        return _comment_failure_annotation(
            issue,
            location,
            document,
            target,
            reason="word_comment_creation_failed",
            error_detail=str(exc),
        )

    if native.status == STATUS_APPLIED:
        return _annotation_result(
            issue,
            location,
            document,
            target,
            status=STATUS_APPLIED,
            comment_id=native.comment_id,
        )
    if native.status == STATUS_SKIPPED:
        return _annotation_result(
            issue,
            location,
            document,
            target,
            status=STATUS_SKIPPED,
            reason=native.reason,
        )
    return _comment_failure_annotation(
        issue,
        location,
        document,
        target,
        reason=native.reason or "word_comment_creation_failed",
        error_detail=native.error_detail,
    )


def annotate_word_document(
    batch: Project1Batch,
    document: DocumentView,
    items: list[tuple[AuditIssue, LocationResult]],
    output_dir: str | Path,
) -> tuple[list[AnnotationResult], Path | None]:
    """Annotate one Word document with native comments and return results."""

    if not items:
        return [], None

    source_path = Path(document.source_file)
    if not source_path.is_file():
        return [
            _annotation_result(
                issue,
                location,
                document,
                None,
                status=STATUS_FAILED,
                reason="word_file_not_found",
            )
            for issue, location in items
        ], None

    source_hash = _sha256_file(source_path)
    try:
        word_document = Document(str(source_path))
    except Exception as exc:  # noqa: BLE001 - report a stable failure reason
        return [
            _annotation_result(
                issue,
                location,
                document,
                None,
                status=STATUS_FAILED,
                reason="word_open_failed",
                error_detail=str(exc),
            )
            for issue, location in items
        ], None

    annotations: list[AnnotationResult] = []
    applied: list[AnnotationResult] = []
    for issue, location in items:
        annotation = _resolve_and_annotate(
            word_document,
            batch,
            document,
            issue,
            location,
        )
        annotations.append(annotation)
        if annotation.status == STATUS_APPLIED:
            applied.append(annotation)

    if not applied:
        return annotations, None

    output_path = unique_path(
        output_dir,
        source_path.stem + "_annotated",
        source_path.suffix or ".docx",
    )
    if output_path.resolve() == source_path.resolve():
        for annotation in applied:
            _mark_failed(
                annotation,
                "word_output_overwrites_source",
            )
        return annotations, None

    try:
        word_document.save(str(output_path))
    except Exception as exc:  # noqa: BLE001 - report a stable failure reason
        output_path.unlink(missing_ok=True)
        for annotation in applied:
            _mark_failed(
                annotation,
                "word_save_failed",
                str(exc),
            )
        return annotations, None

    after_hash = _sha256_file(source_path)
    if after_hash != source_hash:
        output_path.unlink(missing_ok=True)
        for annotation in applied:
            _mark_failed(
                annotation,
                "word_source_changed",
                f"source hash changed: {source_hash} -> {after_hash}",
            )
        return annotations, None

    for annotation in applied:
        annotation.metadata["output_file"] = str(output_path)
    return annotations, output_path
