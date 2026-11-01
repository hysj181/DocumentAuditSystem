"""Shared helpers for Word and PDF annotation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from word_audit.models import AuditIssue, LocationResult, SourceLocation
from word_audit.project1_batch import DocumentView


def is_synthetic_issue(issue: AuditIssue) -> bool:
    return bool(issue.metadata.get("synthetic")) or (
        str(issue.metadata.get("data_source", "")).lower() == "synthetic"
    )


def _format_value(value: float | int | str | None) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def build_comment_text(issue: AuditIssue) -> str:
    synthetic = is_synthetic_issue(issue)
    prefix = "[合成测试数据] " if synthetic else ""
    type_label = issue.metadata.get("issue_type_label") or issue.issue_type
    lines = [f"# {prefix}[{type_label}] {issue.description}"]
    if issue.original_text.strip():
        lines.append(f"原文：{issue.original_text.strip()}")

    calculation = issue.calculation
    if (
        calculation is not None
        and calculation.is_verified
        and calculation.computed_value is not None
    ):
        unit = f" {calculation.unit}" if calculation.unit else ""
        suggestion = f"经计算为 {_format_value(calculation.computed_value)}{unit}。"
    elif issue.suggestion and issue.suggestion.strip():
        suggestion = issue.suggestion.strip()
    else:
        suggestion = "请人工核实。"
    lines.append(f"建议核实：{suggestion}")
    return "\n".join(lines)


def anchor_for(
    result: LocationResult,
    document: DocumentView | None,
) -> SourceLocation:
    location = result.source_location
    data: dict[str, Any]
    if location is not None:
        data = location.to_dict()
    else:
        data = {
            "document_id": result.document_id,
            "source_file": (
                document.source_file if document is not None else "unknown"
            ),
            "file_type": result.file_type,
            "locator_method": "unknown",
            "locator_confidence": 0.0,
        }

    data["document_id"] = result.document_id or data.get("document_id") or "unknown"
    if not data.get("source_file"):
        data["source_file"] = (
            document.source_file if document is not None else "unknown"
        )
    data["file_type"] = result.file_type or (
        document.file_type if document is not None else "unknown"
    )

    for field_name in (
        "page_number",
        "paragraph_index",
        "table_index",
        "row_index",
        "column_index",
        "bbox",
    ):
        value = getattr(result, field_name)
        if value is not None:
            data[field_name] = value

    method = str(data.get("locator_method") or "unknown")
    if method == "unknown":
        if result.table_index is not None:
            method = "table_cell"
        elif result.paragraph_index is not None:
            method = "exact_index"
        elif result.page_number is not None:
            method = "text_match"
        data["locator_method"] = method
    data["locator_confidence"] = float(result.locator_confidence)
    if not data.get("notes"):
        data["notes"] = []
    return SourceLocation.from_dict(data)


def unique_path(directory: str | Path, stem: str, suffix: str) -> Path:
    target_dir = Path(directory).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    candidate = target_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    index = 1
    while True:
        candidate = target_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def unique_report_paths(
    directory: str | Path,
    stem: str,
) -> tuple[Path, Path]:
    target_dir = Path(directory).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    index = 0
    while True:
        name = stem if index == 0 else f"{stem}_{index}"
        json_path = target_dir / f"{name}.json"
        markdown_path = target_dir / f"{name}.md"
        if not json_path.exists() and not markdown_path.exists():
            return json_path, markdown_path
        index += 1
