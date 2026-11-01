"""Write red rectangle markers into a copy of a PDF document."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pymupdf

from word_audit.annotation_common import (
    anchor_for,
    build_comment_text,
    is_synthetic_issue,
    unique_path,
)
from word_audit.models import (
    LOCATION_LOCATED,
    AnnotationResult,
    AuditIssue,
    LocationResult,
    SourceLocation,
)
from word_audit.project1_batch import DocumentView


def _valid_bbox(
    bbox: list[float] | None,
    width: float,
    height: float,
) -> tuple[bool, str]:
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


def _pdf_anchor(
    issue: AuditIssue,
    result: LocationResult,
    document: DocumentView,
    bbox: list[float] | None,
) -> SourceLocation:
    data = anchor_for(result, document).to_dict()
    if result.page_number is not None:
        data["page_number"] = result.page_number
    if bbox is not None:
        data["bbox"] = bbox
    return SourceLocation.from_dict(data)


def _metadata(
    issue: AuditIssue,
    result: LocationResult,
    bbox: list[float] | None,
    *,
    output_file: str | None = None,
) -> dict[str, Any]:
    return {
        "locator_status": result.locator_status,
        "locator_confidence": result.locator_confidence,
        "annotation_kind": "pdf_red_rect",
        "synthetic": is_synthetic_issue(issue),
        "page_number": result.page_number,
        "bbox": bbox,
        "source_bbox_source": result.metadata.get("bbox_source"),
        "output_file": output_file,
    }


def _applied(
    issue: AuditIssue,
    result: LocationResult,
    document: DocumentView,
    bbox: list[float] | None,
) -> AnnotationResult:
    return AnnotationResult(
        annotation_id=uuid.uuid4().hex,
        issue_id=issue.issue_id,
        document_id=result.document_id or document.document_id,
        comment_text=build_comment_text(issue),
        anchor=_pdf_anchor(issue, result, document, bbox),
        status="applied",
        metadata=_metadata(issue, result, bbox),
    )


def _failed(
    issue: AuditIssue,
    result: LocationResult,
    document: DocumentView | None,
    error: str,
    bbox: list[float] | None,
) -> AnnotationResult:
    location = (
        _pdf_anchor(issue, result, document, bbox)
        if document is not None
        else anchor_for(result, None)
    )
    return AnnotationResult(
        annotation_id=uuid.uuid4().hex,
        issue_id=issue.issue_id,
        document_id=result.document_id or (document.document_id if document else "unknown"),
        comment_text=build_comment_text(issue),
        anchor=location,
        status="failed",
        error=error,
        metadata=_metadata(issue, result, bbox),
    )


def _skipped(
    issue: AuditIssue,
    result: LocationResult,
    document: DocumentView | None,
    reason: str,
    bbox: list[float] | None,
) -> AnnotationResult:
    location = (
        _pdf_anchor(issue, result, document, bbox)
        if document is not None
        else anchor_for(result, None)
    )
    metadata = _metadata(issue, result, bbox)
    metadata["manual_review"] = True
    return AnnotationResult(
        annotation_id=uuid.uuid4().hex,
        issue_id=issue.issue_id,
        document_id=result.document_id or (document.document_id if document else "unknown"),
        comment_text=build_comment_text(issue),
        anchor=location,
        status="skipped",
        error=reason,
        metadata=metadata,
    )


def _mark_failed(annotation: AnnotationResult, error: str) -> None:
    annotation.status = "failed"
    annotation.error = error
    annotation.applied_at = None
    annotation.metadata["output_file"] = None


def annotate_pdf_document(
    document: DocumentView,
    items: list[tuple[AuditIssue, LocationResult]],
    output_dir: str | Path,
) -> tuple[list[AnnotationResult], Path | None]:
    """Annotate one PDF document and return annotations plus output path."""

    if not items:
        return [], None

    source_path = Path(document.source_file)
    if not source_path.is_file():
        return [
            _failed(issue, result, document, "pdf_file_not_found", result.bbox)
            for issue, result in items
        ], None

    try:
        pdf = pymupdf.open(str(source_path))
    except Exception as exc:
        return [
            _failed(issue, result, document, f"pdf_open_failed: {exc}", result.bbox)
            for issue, result in items
        ], None

    annotations: list[AnnotationResult] = []
    applied: list[AnnotationResult] = []

    try:
        for issue, result in items:
            if result.locator_status != LOCATION_LOCATED:
                annotations.append(
                    _skipped(
                        issue,
                        result,
                        document,
                        result.failure_reason or "locator_not_located",
                        result.bbox,
                    )
                )
                continue
            if result.page_number is None:
                annotations.append(
                    _skipped(
                        issue,
                        result,
                        document,
                        "pdf_page_number_missing",
                        result.bbox,
                    )
                )
                continue
            if result.page_number < 1 or result.page_number > pdf.page_count:
                annotations.append(
                    _skipped(
                        issue,
                        result,
                        document,
                        "page_number_out_of_range",
                        result.bbox,
                    )
                )
                continue

            page = pdf.load_page(result.page_number - 1)
            if page.rotation:
                annotations.append(
                    _skipped(
                        issue,
                        result,
                        document,
                        "page_rotation_not_supported",
                        result.bbox,
                    )
                )
                continue
            if not page.get_text("text").strip():
                annotations.append(
                    _skipped(
                        issue,
                        result,
                        document,
                        "scanned_page_no_text_layer",
                        result.bbox,
                    )
                )
                continue

            bbox = result.bbox
            valid, reason = _valid_bbox(
                bbox, float(page.rect.width), float(page.rect.height)
            )
            if not valid:
                annotations.append(
                    _skipped(issue, result, document, reason, bbox)
                )
                continue

            try:
                page.draw_rect(
                    pymupdf.Rect(bbox),
                    color=(1, 0, 0),
                    width=1.5,
                    fill=None,
                )
            except Exception as exc:  # pragma: no cover - defensive
                annotations.append(
                    _failed(
                        issue,
                        result,
                        document,
                        f"pdf_marker_failed: {exc}",
                        bbox,
                    )
                )
                continue

            annotation = _applied(issue, result, document, bbox)
            annotations.append(annotation)
            applied.append(annotation)

        if not applied:
            return annotations, None

        output_path = unique_path(
            output_dir,
            source_path.stem + "_annotated",
            ".pdf",
        )
        try:
            pdf.save(str(output_path))
        except Exception as exc:  # pragma: no cover - defensive
            for annotation in applied:
                _mark_failed(annotation, f"pdf_save_failed: {exc}")
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            return annotations, None

        for annotation in applied:
            annotation.metadata["output_file"] = str(output_path)
        return annotations, output_path
    finally:
        pdf.close()
