"""Annotation orchestration and JSON/Markdown reporting."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from word_audit.annotation_common import (
    anchor_for,
    build_comment_text,
    is_synthetic_issue,
    unique_report_paths,
)
from word_audit.models import (
    LOCATION_LOCATED,
    AnnotationResult,
    AuditIssue,
    AuditReport,
    LocationResult,
    SourceLocation,
)
from word_audit.pdf_annotator import annotate_pdf_document
from word_audit.project1_batch import DocumentView, Project1Batch
from word_audit.word_annotator import annotate_word_document


@dataclass
class AnnotationBatchResult:
    report: AuditReport
    json_path: Path
    markdown_path: Path
    output_files: list[Path]


def _fallback_anchor(issue: AuditIssue) -> SourceLocation:
    if issue.location is not None:
        return issue.location
    return SourceLocation(
        document_id="unknown",
        source_file="unknown",
        file_type="unknown",
        locator_method="unknown",
        locator_confidence=0.0,
    )


def _skipped_annotation(
    issue: AuditIssue,
    result: LocationResult | None,
    document: DocumentView | None,
    reason: str,
) -> AnnotationResult:
    anchor = (
        anchor_for(result, document)
        if result is not None
        else _fallback_anchor(issue)
    )
    metadata = {
        "locator_status": result.locator_status if result else "missing",
        "locator_confidence": result.locator_confidence if result else 0.0,
        "synthetic": is_synthetic_issue(issue),
        "manual_review": True,
        "failure_reason": reason,
    }
    return AnnotationResult(
        annotation_id=uuid.uuid4().hex,
        issue_id=issue.issue_id,
        document_id=(
            result.document_id
            if result is not None
            else (issue.location.document_id if issue.location else "unknown")
        ),
        comment_text=build_comment_text(issue),
        anchor=anchor,
        status="skipped",
        error=reason,
        metadata=metadata,
    )


def _document_dicts(
    batch: Project1Batch,
    output_by_document: dict[str, Path],
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for document in batch.documents:
        output = output_by_document.get(document.document_id)
        documents.append(
            {
                "document_id": document.document_id,
                "source_name": document.source_name,
                "source_file": document.source_file,
                "file_type": document.file_type,
                "annotated_file": str(output) if output else None,
            }
        )
    return documents


def _counts(annotations: list[AnnotationResult]) -> dict[str, int]:
    return {
        "total": len(annotations),
        "applied": sum(1 for item in annotations if item.status == "applied"),
        "failed": sum(1 for item in annotations if item.status == "failed"),
        "manual_review": sum(1 for item in annotations if item.status == "skipped"),
    }


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _location_summary(annotation: AnnotationResult) -> str:
    anchor = annotation.anchor
    parts: list[str] = []
    if anchor.page_number is not None:
        parts.append(f"第{anchor.page_number}页")
    if anchor.paragraph_index is not None:
        parts.append(f"段落[{anchor.paragraph_index}]")
    if anchor.table_index is not None:
        parts.append(f"表格[{anchor.table_index}]")
    if anchor.row_index is not None:
        parts.append(f"行[{anchor.row_index}]")
    if anchor.column_index is not None:
        parts.append(f"列[{anchor.column_index}]")
    if anchor.bbox:
        parts.append("bbox=(" + ", ".join(f"{value:.1f}" for value in anchor.bbox) + ")")
    return " ".join(parts) if parts else "-"


def _write_markdown(report: AuditReport, path: Path) -> None:
    task = report.metadata.get("annotation_task", {})
    counts = task.get("counts", {})
    issue_by_id = {issue.issue_id: issue for issue in report.issues}
    successful = [item for item in report.annotations if item.status == "applied"]
    failed = [item for item in report.annotations if item.status == "failed"]
    manual = [item for item in report.annotations if item.status == "skipped"]

    lines: list[str] = [
        "# 批注任务报告",
        "",
        f"- 报告编号：{report.report_id}",
        f"- 批次：{report.batch_id or '-'}",
        f"- 生成时间：{report.generated_at}",
        f"- 合成测试数据：{'是' if task.get('synthetic_data') else '否'}",
        "",
        "## 数量统计",
        "",
        "| 项目 | 数量 |",
        "| --- | ---: |",
        f"| 总问题数 | {counts.get('total', 0)} |",
        f"| 批注成功 | {counts.get('applied', 0)} |",
        f"| 批注失败 | {counts.get('failed', 0)} |",
        f"| 人工核实 | {counts.get('manual_review', 0)} |",
        "",
        "## 原始文件",
        "",
    ]
    original_files = task.get("original_files", [])
    if original_files:
        lines.extend(f"- `{item}`" for item in original_files)
    else:
        lines.append("- 无")
    lines.extend(["", "## 输出文件", ""])
    output_files = task.get("output_files", [])
    if output_files:
        lines.extend(f"- `{item}`" for item in output_files)
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 批注成功清单",
            "",
            "| 问题编号 | 文档 | 位置 | 批注首行 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for annotation in successful:
        issue = issue_by_id.get(annotation.issue_id)
        first_line = annotation.comment_text.splitlines()[0] if annotation.comment_text else ""
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    annotation.issue_id,
                    annotation.document_id,
                    _location_summary(annotation),
                    first_line,
                )
            )
            + " |"
        )
    if not successful:
        lines.append("| - | - | - | 无 |")

    lines.extend(
        [
            "",
            "## 批注失败清单",
            "",
            "| 问题编号 | 文档 | 失败原因 |",
            "| --- | --- | --- |",
        ]
    )
    for annotation in failed:
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    annotation.issue_id,
                    annotation.document_id,
                    annotation.error or "-",
                )
            )
            + " |"
        )
    if not failed:
        lines.append("| - | - | 无 |")

    lines.extend(
        [
            "",
            "## 人工核实清单",
            "",
            "| 问题编号 | 文档 | 定位状态 | 原因 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for annotation in manual:
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    annotation.issue_id,
                    annotation.document_id,
                    annotation.metadata.get("locator_status", "-"),
                    annotation.error or annotation.metadata.get("failure_reason", "-"),
                )
            )
            + " |"
        )
    if not manual:
        lines.append("| - | - | - | 无 |")

    lines.extend(["", "## 问题说明", ""])
    for issue in report.issues:
        synthetic = "（合成测试数据）" if is_synthetic_issue(issue) else ""
        lines.append(
            f"- {issue.issue_id}{synthetic}：[{issue.issue_type}] {issue.description}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def annotate_issues(
    batch: Project1Batch,
    issues: list[AuditIssue],
    locations: list[LocationResult],
    *,
    output_dir: str | Path = "output/annotated",
    report_dir: str | Path = "output/reports",
) -> AnnotationBatchResult:
    """Apply annotations to copies and write JSON/Markdown reports."""

    issue_ids = [issue.issue_id for issue in issues]
    if len(issue_ids) != len(set(issue_ids)):
        raise ValueError("duplicate issue_id in annotation input")

    location_by_issue: dict[str, LocationResult] = {}
    warnings: list[str] = []
    for location in locations:
        if location.issue_id in location_by_issue:
            raise ValueError(
                f"duplicate location result for issue {location.issue_id}"
            )
        location_by_issue[location.issue_id] = location
    known_issue_ids = set(issue_ids)
    for location in locations:
        if location.issue_id not in known_issue_ids:
            warnings.append(
                f"定位结果引用了未知问题：{location.issue_id}"
            )

    annotations_by_issue: dict[str, AnnotationResult] = {}
    eligible: dict[str, list[tuple[AuditIssue, LocationResult]]] = {}
    document_by_id = {document.document_id: document for document in batch.documents}

    for issue in issues:
        location = location_by_issue.get(issue.issue_id)
        if location is None:
            annotations_by_issue[issue.issue_id] = _skipped_annotation(
                issue, None, None, "location_result_missing"
            )
            continue
        document = document_by_id.get(location.document_id)
        if document is None:
            annotations_by_issue[issue.issue_id] = _skipped_annotation(
                issue, location, None, "document_not_found_in_batch"
            )
            continue
        if location.locator_status != LOCATION_LOCATED:
            annotations_by_issue[issue.issue_id] = _skipped_annotation(
                issue,
                location,
                document,
                location.failure_reason or location.locator_status,
            )
            continue
        if issue.metadata.get("auto_annotate", True) is False:
            annotations_by_issue[issue.issue_id] = _skipped_annotation(
                issue,
                location,
                document,
                "issue_requires_manual_review",
            )
            continue
        eligible.setdefault(document.document_id, []).append((issue, location))

    output_by_document: dict[str, Path] = {}
    for document in batch.documents:
        items = eligible.get(document.document_id, [])
        if not items:
            continue
        if document.file_type == "word":
            document_annotations, output_path = annotate_word_document(
                document, items, output_dir
            )
        elif document.file_type == "pdf":
            document_annotations, output_path = annotate_pdf_document(
                document, items, output_dir
            )
        else:
            document_annotations = [
                _skipped_annotation(
                    issue, location, document, "unsupported_file_type"
                )
                for issue, location in items
            ]
            output_path = None
        for annotation in document_annotations:
            annotations_by_issue[annotation.issue_id] = annotation
        if output_path is not None:
            output_by_document[document.document_id] = output_path

    for issue in issues:
        if issue.issue_id in annotations_by_issue:
            continue
        location = location_by_issue.get(issue.issue_id)
        document = (
            document_by_id.get(location.document_id) if location is not None else None
        )
        annotations_by_issue[issue.issue_id] = _skipped_annotation(
            issue, location, document, "annotation_not_generated"
        )

    annotations = [annotations_by_issue[issue.issue_id] for issue in issues]
    synthetic = any(is_synthetic_issue(issue) for issue in issues)
    counts = _counts(annotations)
    output_files = list(output_by_document.values())
    report_stem = f"annotation_report_{batch.batch_id}"
    json_path, markdown_path = unique_report_paths(report_dir, report_stem)

    task_metadata = {
        "synthetic_data": synthetic,
        "source_batch": str(batch.path),
        "original_files": [document.source_file for document in batch.documents],
        "output_files": [str(path) for path in output_files],
        "success": [
            {
                "annotation_id": annotation.annotation_id,
                "issue_id": annotation.issue_id,
                "output_file": annotation.metadata.get("output_file"),
            }
            for annotation in annotations
            if annotation.status == "applied"
        ],
        "failed": [
            {
                "annotation_id": annotation.annotation_id,
                "issue_id": annotation.issue_id,
                "error": annotation.error,
            }
            for annotation in annotations
            if annotation.status == "failed"
        ],
        "manual_review": [
            {
                "annotation_id": annotation.annotation_id,
                "issue_id": annotation.issue_id,
                "locator_status": annotation.metadata.get("locator_status"),
                "failure_reason": annotation.error
                or annotation.metadata.get("failure_reason"),
            }
            for annotation in annotations
            if annotation.status == "skipped"
        ],
        "counts": counts,
        "report_files": {
            "json": str(json_path),
            "markdown": str(markdown_path),
        },
    }
    if synthetic:
        warnings.append("本次批注使用合成测试问题数据，非项目一真实计算错误。")
    if counts["manual_review"]:
        warnings.append(f"{counts['manual_review']} 个问题进入人工核实清单。")
    if counts["failed"]:
        warnings.append(f"{counts['failed']} 个问题批注失败。")

    report = AuditReport(
        report_id=f"annotation-{uuid.uuid4().hex}",
        batch_id=batch.batch_id,
        source_batch=str(batch.path),
        documents=_document_dicts(batch, output_by_document),
        issues=list(issues),
        annotations=annotations,
        warnings=warnings,
        metadata={"annotation_task": task_metadata},
    )
    report.validate()

    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_markdown(report, markdown_path)
    return AnnotationBatchResult(
        report=report,
        json_path=json_path,
        markdown_path=markdown_path,
        output_files=output_files,
    )
