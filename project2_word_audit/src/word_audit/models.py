"""Unified data models for the Word audit project.

The models in this module are the contract between project one (data
extraction), the audit engine and the Word annotation writer.

Design rules:

* Locations reference project one indices without inventing new ones.
* ``CalculationInfo.computed_value`` may only be populated after a reliable
  calculation has been verified.
* Missing information stays ``None`` instead of being guessed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"

ISSUE_TYPE_CALCULATION = "calculation_error"
ISSUE_TYPE_FORMULA = "formula_error"
ISSUE_TYPE_VALUE = "value_mismatch"
ISSUE_TYPE_UNIT = "unit_mismatch"
ISSUE_TYPE_MISSING_DATA = "missing_data"
ISSUE_TYPE_INCONSISTENCY = "data_inconsistency"
ISSUE_TYPE_TEXT = "text_inconsistency"
ISSUE_TYPE_OTHER = "other"

ISSUE_TYPES = (
    ISSUE_TYPE_CALCULATION,
    ISSUE_TYPE_FORMULA,
    ISSUE_TYPE_VALUE,
    ISSUE_TYPE_UNIT,
    ISSUE_TYPE_MISSING_DATA,
    ISSUE_TYPE_INCONSISTENCY,
    ISSUE_TYPE_TEXT,
    ISSUE_TYPE_OTHER,
)

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

SEVERITIES = (SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR)

VERIFICATION_NOT_ATTEMPTED = "not_attempted"
VERIFICATION_VERIFIED = "verified"
VERIFICATION_FAILED = "failed"
VERIFICATION_ERROR = "error"

VERIFICATION_STATUSES = (
    VERIFICATION_NOT_ATTEMPTED,
    VERIFICATION_VERIFIED,
    VERIFICATION_FAILED,
    VERIFICATION_ERROR,
)

LOCATOR_EXACT_INDEX = "exact_index"
LOCATOR_TABLE_CELL = "table_cell"
LOCATOR_TEXT_MATCH = "text_match"
LOCATOR_MANUAL = "manual"
LOCATOR_UNKNOWN = "unknown"

LOCATOR_METHODS = (
    LOCATOR_EXACT_INDEX,
    LOCATOR_TABLE_CELL,
    LOCATOR_TEXT_MATCH,
    LOCATOR_MANUAL,
    LOCATOR_UNKNOWN,
)

ISSUE_STATUS_OPEN = "open"
ISSUE_STATUS_CONFIRMED = "confirmed"
ISSUE_STATUS_DISMISSED = "dismissed"

ISSUE_STATUSES = (ISSUE_STATUS_OPEN, ISSUE_STATUS_CONFIRMED, ISSUE_STATUS_DISMISSED)

ANNOTATION_PENDING = "pending"
ANNOTATION_APPLIED = "applied"
ANNOTATION_FAILED = "failed"
ANNOTATION_SKIPPED = "skipped"

ANNOTATION_STATUSES = (
    ANNOTATION_PENDING,
    ANNOTATION_APPLIED,
    ANNOTATION_FAILED,
    ANNOTATION_SKIPPED,
)

LOCATION_LOCATED = "located"
LOCATION_AMBIGUOUS = "ambiguous"
LOCATION_NOT_FOUND = "not_found"
LOCATION_INVALID = "invalid_location"
LOCATION_MANUAL_REVIEW = "manual_review"

LOCATION_STATUSES = (
    LOCATION_LOCATED,
    LOCATION_AMBIGUOUS,
    LOCATION_NOT_FOUND,
    LOCATION_INVALID,
    LOCATION_MANUAL_REVIEW,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _check_choice(value: str, allowed: tuple[str, ...], field_name: str) -> None:
    if value not in allowed:
        raise ValueError(
            f"{field_name} must be one of {', '.join(allowed)}, got {value!r}"
        )


def _check_confidence(value: float, field_name: str) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number between 0 and 1") from exc
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1, got {number!r}")


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer or null")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be an integer or null")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer or null") from exc


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number or null")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number or null") from exc


def _bbox(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("bbox must contain exactly four numbers or be null")
    return [float(item) for item in value]


@dataclass
class SourceLocation:
    """Location of an issue inside a source document.

    ``row_index`` / ``column_index`` point at the anchor cell reported by
    project one (usually the indicator cell). ``value_row_index`` /
    ``value_column_index`` optionally point at the numeric result cell and
    must only be filled after the cell mapping has been verified.
    """

    document_id: str
    source_file: str
    source_name: str | None = None
    file_type: str = ""
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    value_row_index: int | None = None
    value_column_index: int | None = None
    page_number: int | None = None
    bbox: list[float] | None = None
    block_index: int | None = None
    reading_order: int | None = None
    source_content_type: str = ""
    locator_method: str = LOCATOR_UNKNOWN
    locator_confidence: float = 0.0
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.document_id, "document_id")
        _require_text(self.source_file, "source_file")
        for name in (
            "paragraph_index",
            "table_index",
            "row_index",
            "column_index",
            "value_row_index",
            "value_column_index",
            "page_number",
            "block_index",
            "reading_order",
        ):
            setattr(self, name, _optional_int(getattr(self, name), name))
        self.bbox = _bbox(self.bbox)
        _check_choice(self.locator_method, LOCATOR_METHODS, "locator_method")
        _check_confidence(self.locator_confidence, "locator_confidence")
        if self.locator_method != LOCATOR_UNKNOWN or self.locator_confidence > 0.0:
            if not (
                self.paragraph_index is not None
                or self.table_index is not None
                or self.page_number is not None
            ):
                raise ValueError(
                    "a located issue needs paragraph_index, table_index or page_number"
                )

    @property
    def is_word_anchor(self) -> bool:
        return self.file_type == "word" and (
            self.paragraph_index is not None
            or (
                self.table_index is not None
                and self.row_index is not None
                and self.column_index is not None
            )
        )

    @property
    def is_table_anchor(self) -> bool:
        return self.table_index is not None and self.row_index is not None

    @property
    def has_value_cell(self) -> bool:
        return (
            self.value_row_index is not None
            and self.value_column_index is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_file": self.source_file,
            "source_name": self.source_name,
            "file_type": self.file_type,
            "paragraph_index": self.paragraph_index,
            "table_index": self.table_index,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "value_row_index": self.value_row_index,
            "value_column_index": self.value_column_index,
            "page_number": self.page_number,
            "bbox": self.bbox,
            "block_index": self.block_index,
            "reading_order": self.reading_order,
            "source_content_type": self.source_content_type,
            "locator_method": self.locator_method,
            "locator_confidence": self.locator_confidence,
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceLocation":
        return cls(
            document_id=str(data.get("document_id", "")),
            source_file=str(data.get("source_file", "")),
            source_name=data.get("source_name"),
            file_type=str(data.get("file_type", "")),
            paragraph_index=data.get("paragraph_index"),
            table_index=data.get("table_index"),
            row_index=data.get("row_index"),
            column_index=data.get("column_index"),
            value_row_index=data.get("value_row_index"),
            value_column_index=data.get("value_column_index"),
            page_number=data.get("page_number"),
            bbox=data.get("bbox"),
            block_index=data.get("block_index"),
            reading_order=data.get("reading_order"),
            source_content_type=str(data.get("source_content_type", "")),
            locator_method=str(data.get("locator_method", LOCATOR_UNKNOWN)),
            locator_confidence=float(data.get("locator_confidence", 0.0)),
            notes=list(data.get("notes", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class CalculationOperand:
    """One input of a calculation."""

    name: str
    numeric_value: float | None = None
    raw_value: str | None = None
    unit: str | None = None
    source_location: SourceLocation | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.name, "operand.name")
        self.numeric_value = _optional_float(self.numeric_value, "numeric_value")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "numeric_value": self.numeric_value,
            "raw_value": self.raw_value,
            "unit": self.unit,
            "source_location": (
                self.source_location.to_dict() if self.source_location else None
            ),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalculationOperand":
        location = data.get("source_location")
        return cls(
            name=str(data.get("name", "")),
            numeric_value=data.get("numeric_value"),
            raw_value=data.get("raw_value"),
            unit=data.get("unit"),
            source_location=(
                SourceLocation.from_dict(location) if isinstance(location, dict) else None
            ),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class CalculationInfo:
    """Calculation related to an audit issue.

    ``computed_value`` is the project two result. It is only accepted when
    ``verification_status`` is ``verified``; otherwise the field must stay
    ``None``. The reported value from the document is never overwritten.
    """

    formula: str | None = None
    substituted_formula: str | None = None
    operands: list[CalculationOperand] = field(default_factory=list)
    reported_value: float | str | None = None
    computed_value: float | None = None
    unit: str | None = None
    rounding: str | None = None
    tolerance: float | None = None
    verification_status: str = VERIFICATION_NOT_ATTEMPTED
    verification_method: str | None = None
    verification_detail: str | None = None
    verified_at: str | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_choice(
            self.verification_status, VERIFICATION_STATUSES, "verification_status"
        )
        self.computed_value = _optional_float(self.computed_value, "computed_value")
        self.tolerance = _optional_float(self.tolerance, "tolerance")
        if self.computed_value is not None and self.verification_status != VERIFICATION_VERIFIED:
            raise ValueError(
                "computed_value may only be set when verification_status is 'verified'"
            )
        if self.verification_status == VERIFICATION_VERIFIED and self.computed_value is None:
            raise ValueError(
                "verification_status 'verified' requires a computed_value"
            )
        if self.verification_status == VERIFICATION_VERIFIED and not self.verified_at:
            self.verified_at = utc_now_iso()

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VERIFICATION_VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula,
            "substituted_formula": self.substituted_formula,
            "operands": [operand.to_dict() for operand in self.operands],
            "reported_value": self.reported_value,
            "computed_value": self.computed_value,
            "unit": self.unit,
            "rounding": self.rounding,
            "tolerance": self.tolerance,
            "verification_status": self.verification_status,
            "verification_method": self.verification_method,
            "verification_detail": self.verification_detail,
            "verified_at": self.verified_at,
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalculationInfo":
        return cls(
            formula=data.get("formula"),
            substituted_formula=data.get("substituted_formula"),
            operands=[
                CalculationOperand.from_dict(item)
                for item in data.get("operands", [])
            ],
            reported_value=data.get("reported_value"),
            computed_value=data.get("computed_value"),
            unit=data.get("unit"),
            rounding=data.get("rounding"),
            tolerance=data.get("tolerance"),
            verification_status=str(
                data.get("verification_status", VERIFICATION_NOT_ATTEMPTED)
            ),
            verification_method=data.get("verification_method"),
            verification_detail=data.get("verification_detail"),
            verified_at=data.get("verified_at"),
            notes=list(data.get("notes", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AuditIssue:
    """One audit finding."""

    issue_id: str
    issue_type: str
    description: str
    severity: str = SEVERITY_WARNING
    original_text: str = ""
    location: SourceLocation | None = None
    calculation: CalculationInfo | None = None
    needs_manual_review: bool = True
    review_reasons: list[str] = field(default_factory=list)
    suggestion: str | None = None
    status: str = ISSUE_STATUS_OPEN
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.issue_id, "issue_id")
        _require_text(self.issue_type, "issue_type")
        _require_text(self.description, "description")
        _check_choice(self.severity, SEVERITIES, "severity")
        _check_choice(self.status, ISSUE_STATUSES, "status")
        if self.location is None and not self.needs_manual_review:
            raise ValueError(
                "an issue without a source location must require manual review"
            )
        if self.location is None and "location_missing" not in self.review_reasons:
            self.review_reasons.append("location_missing")

    @property
    def location_confidence(self) -> float:
        return self.location.locator_confidence if self.location else 0.0

    @property
    def formula(self) -> str | None:
        return self.calculation.formula if self.calculation else None

    @property
    def reported_value(self) -> float | str | None:
        return self.calculation.reported_value if self.calculation else None

    @property
    def computed_value(self) -> float | None:
        return self.calculation.computed_value if self.calculation else None

    @property
    def is_calculation_verified(self) -> bool:
        return bool(self.calculation and self.calculation.is_verified)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "description": self.description,
            "original_text": self.original_text,
            "location": self.location.to_dict() if self.location else None,
            "calculation": self.calculation.to_dict() if self.calculation else None,
            "needs_manual_review": self.needs_manual_review,
            "review_reasons": list(self.review_reasons),
            "suggestion": self.suggestion,
            "status": self.status,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditIssue":
        location = data.get("location")
        calculation = data.get("calculation")
        return cls(
            issue_id=str(data.get("issue_id", "")),
            issue_type=str(data.get("issue_type", "")),
            description=str(data.get("description", "")),
            severity=str(data.get("severity", SEVERITY_WARNING)),
            original_text=str(data.get("original_text", "")),
            location=(
                SourceLocation.from_dict(location)
                if isinstance(location, dict)
                else None
            ),
            calculation=(
                CalculationInfo.from_dict(calculation)
                if isinstance(calculation, dict)
                else None
            ),
            needs_manual_review=bool(data.get("needs_manual_review", True)),
            review_reasons=list(data.get("review_reasons", [])),
            suggestion=data.get("suggestion"),
            status=str(data.get("status", ISSUE_STATUS_OPEN)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AnnotationResult:
    """Result of writing one issue as a Word comment.

    This phase only defines the structure. No Word document is modified.
    """

    annotation_id: str
    issue_id: str
    document_id: str
    comment_text: str
    anchor: SourceLocation
    status: str = ANNOTATION_PENDING
    applied_at: str | None = None
    word_anchor: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.annotation_id, "annotation_id")
        _require_text(self.issue_id, "issue_id")
        _require_text(self.document_id, "document_id")
        _require_text(self.comment_text, "comment_text")
        _check_choice(self.status, ANNOTATION_STATUSES, "status")
        if self.anchor.document_id != self.document_id:
            raise ValueError(
                "annotation.document_id must match anchor.document_id"
            )
        if self.status == ANNOTATION_APPLIED and not self.applied_at:
            self.applied_at = utc_now_iso()

    @property
    def anchor_confidence(self) -> float:
        return self.anchor.locator_confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "issue_id": self.issue_id,
            "document_id": self.document_id,
            "comment_text": self.comment_text,
            "anchor": self.anchor.to_dict(),
            "status": self.status,
            "applied_at": self.applied_at,
            "word_anchor": dict(self.word_anchor) if self.word_anchor else None,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnnotationResult":
        anchor = data.get("anchor")
        if not isinstance(anchor, dict):
            raise ValueError("annotation.anchor is required")
        return cls(
            annotation_id=str(data.get("annotation_id", "")),
            issue_id=str(data.get("issue_id", "")),
            document_id=str(data.get("document_id", "")),
            comment_text=str(data.get("comment_text", "")),
            anchor=SourceLocation.from_dict(anchor),
            status=str(data.get("status", ANNOTATION_PENDING)),
            applied_at=data.get("applied_at"),
            word_anchor=data.get("word_anchor"),
            error=data.get("error"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class LocationResult:
    """Result of locating one audit issue in its source document.

    ``located`` requires a successful index/coordinate check and a text
    check. Anything uncertain is kept out of ``located``.
    """

    issue_id: str
    document_id: str
    file_type: str
    locator_status: str
    page_number: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    bbox: list[float] | None = None
    matched_text: str | None = None
    locator_confidence: float = 0.0
    needs_manual_review: bool = True
    failure_reason: str | None = None
    source_location: SourceLocation | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.issue_id, "issue_id")
        _require_text(self.document_id, "document_id")
        _require_text(self.file_type, "file_type")
        _check_choice(self.locator_status, LOCATION_STATUSES, "locator_status")
        for name in (
            "page_number",
            "paragraph_index",
            "table_index",
            "row_index",
            "column_index",
        ):
            setattr(self, name, _optional_int(getattr(self, name), name))
        self.bbox = _bbox(self.bbox)
        _check_confidence(self.locator_confidence, "locator_confidence")
        if self.locator_status == LOCATION_LOCATED:
            if self.needs_manual_review:
                raise ValueError("a located result cannot require manual review")
            if self.failure_reason:
                raise ValueError("a located result cannot have a failure_reason")
        elif not self.needs_manual_review:
            raise ValueError(
                "a non-located result must require manual review"
            )

    @property
    def is_located(self) -> bool:
        return self.locator_status == LOCATION_LOCATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "document_id": self.document_id,
            "file_type": self.file_type,
            "page_number": self.page_number,
            "paragraph_index": self.paragraph_index,
            "table_index": self.table_index,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "bbox": self.bbox,
            "matched_text": self.matched_text,
            "locator_confidence": self.locator_confidence,
            "locator_status": self.locator_status,
            "needs_manual_review": self.needs_manual_review,
            "failure_reason": self.failure_reason,
            "source_location": (
                self.source_location.to_dict() if self.source_location else None
            ),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocationResult":
        location = data.get("source_location")
        status = str(data.get("locator_status", LOCATION_MANUAL_REVIEW))
        needs_manual_review = data.get("needs_manual_review")
        if needs_manual_review is None:
            needs_manual_review = status != LOCATION_LOCATED
        return cls(
            issue_id=str(data.get("issue_id", "")),
            document_id=str(data.get("document_id", "")),
            file_type=str(data.get("file_type", "")),
            locator_status=status,
            page_number=data.get("page_number"),
            paragraph_index=data.get("paragraph_index"),
            table_index=data.get("table_index"),
            row_index=data.get("row_index"),
            column_index=data.get("column_index"),
            bbox=data.get("bbox"),
            matched_text=data.get("matched_text"),
            locator_confidence=float(data.get("locator_confidence", 0.0)),
            needs_manual_review=bool(needs_manual_review),
            failure_reason=data.get("failure_reason"),
            source_location=(
                SourceLocation.from_dict(location)
                if isinstance(location, dict)
                else None
            ),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AuditReport:
    """Audit report combining issues and annotation results."""

    report_id: str
    schema_version: str = SCHEMA_VERSION
    batch_id: str | None = None
    generated_at: str = field(default_factory=utc_now_iso)
    source_batch: str | None = None
    documents: list[dict[str, Any]] = field(default_factory=list)
    issues: list[AuditIssue] = field(default_factory=list)
    annotations: list[AnnotationResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.report_id, "report_id")
        _require_text(self.schema_version, "schema_version")

    def summary(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {severity: 0 for severity in SEVERITIES}
        for issue in self.issues:
            by_type[issue.issue_type] = by_type.get(issue.issue_type, 0) + 1
            by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        return {
            "issue_count": len(self.issues),
            "annotation_count": len(self.annotations),
            "needs_manual_review_count": sum(
                1 for issue in self.issues if issue.needs_manual_review
            ),
            "verified_calculation_count": sum(
                1 for issue in self.issues if issue.is_calculation_verified
            ),
            "by_severity": by_severity,
            "by_type": by_type,
            "annotations_by_status": {
                status: sum(
                    1 for annotation in self.annotations if annotation.status == status
                )
                for status in ANNOTATION_STATUSES
            },
        }

    def validate(self) -> None:
        issue_ids = [issue.issue_id for issue in self.issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("duplicate issue_id in audit report")
        annotation_ids = [annotation.annotation_id for annotation in self.annotations]
        if len(annotation_ids) != len(set(annotation_ids)):
            raise ValueError("duplicate annotation_id in audit report")
        known = set(issue_ids)
        for annotation in self.annotations:
            if annotation.issue_id not in known:
                raise ValueError(
                    f"annotation {annotation.annotation_id} references unknown issue "
                    f"{annotation.issue_id}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "batch_id": self.batch_id,
            "generated_at": self.generated_at,
            "source_batch": self.source_batch,
            "documents": [dict(document) for document in self.documents],
            "summary": self.summary(),
            "issues": [issue.to_dict() for issue in self.issues],
            "annotations": [
                annotation.to_dict() for annotation in self.annotations
            ],
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditReport":
        return cls(
            report_id=str(data.get("report_id", "")),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            batch_id=data.get("batch_id"),
            generated_at=str(data.get("generated_at") or utc_now_iso()),
            source_batch=data.get("source_batch"),
            documents=[dict(item) for item in data.get("documents", [])],
            issues=[AuditIssue.from_dict(item) for item in data.get("issues", [])],
            annotations=[
                AnnotationResult.from_dict(item)
                for item in data.get("annotations", [])
            ],
            warnings=list(data.get("warnings", [])),
            metadata=dict(data.get("metadata", {})),
        )
