"""Unified error-list JSON input and output.

The error list is the exchange format for audit findings produced by the
audit engine or by an external AI service. It can be converted to an
``AuditReport`` once annotation results exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from word_audit.models import (
    SCHEMA_VERSION,
    AnnotationResult,
    AuditIssue,
    AuditReport,
    utc_now_iso,
)


@dataclass
class ErrorList:
    """A collection of audit issues for one project one batch."""

    issues: list[AuditIssue] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    batch_id: str | None = None
    generated_at: str = field(default_factory=utc_now_iso)
    source: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.issues, list):
            raise ValueError("issues must be a list")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported error list schema_version: {self.schema_version!r}"
            )

    def validate(self) -> None:
        issue_ids = [issue.issue_id for issue in self.issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("duplicate issue_id in error list")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "generated_at": self.generated_at,
            "issue_count": len(self.issues),
            "source": dict(self.source),
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": dict(self.metadata),
        }

    def to_report(
        self,
        *,
        report_id: str,
        documents: list[dict[str, Any]] | None = None,
        source_batch: str | None = None,
        annotations: list[AnnotationResult] | None = None,
        warnings: list[str] | None = None,
    ) -> AuditReport:
        return AuditReport(
            report_id=report_id,
            batch_id=self.batch_id,
            source_batch=source_batch,
            documents=list(documents or []),
            issues=list(self.issues),
            annotations=list(annotations or []),
            warnings=list(warnings or []),
            metadata={
                "error_list_generated_at": self.generated_at,
                "error_list_source": dict(self.source),
            },
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ErrorList":
        if not isinstance(data, dict):
            raise ValueError("error list must be a JSON object")
        if "schema_version" not in data:
            raise ValueError("error list must contain a 'schema_version' field")
        raw_issues = data.get("issues")
        if not isinstance(raw_issues, list):
            raise ValueError("error list must contain an 'issues' array")
        for position, item in enumerate(raw_issues):
            if not isinstance(item, dict):
                raise ValueError(f"issues[{position}] must be a JSON object")
        return cls(
            issues=[AuditIssue.from_dict(item) for item in raw_issues],
            schema_version=str(data.get("schema_version")),
            batch_id=data.get("batch_id"),
            generated_at=str(data.get("generated_at") or utc_now_iso()),
            source=dict(data.get("source", {})),
            metadata=dict(data.get("metadata", {})),
        )


def load_error_list(path: str | Path) -> ErrorList:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    error_list = ErrorList.from_dict(payload)
    error_list.validate()
    return error_list


def save_error_list(error_list: ErrorList, path: str | Path) -> Path:
    error_list.validate()
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(error_list.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target
