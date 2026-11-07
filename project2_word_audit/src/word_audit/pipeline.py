"""End-to-end audit pipeline.

This module only orchestrates the existing stages:

* project one batch loading
* mathematical validation
* location
* Word/PDF annotation
* JSON/Markdown reporting

It does not implement new audit rules. ``collect_audit_issues`` is the single
extension point for future rule modules.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from word_audit.annotation import AnnotationBatchResult, annotate_issues
from word_audit.annotation_common import unique_path, unique_report_paths
from word_audit.config import resolve_output_root
from word_audit.location import locate_issues, summarize_location_results
from word_audit.math_audit import (
    MathValidationResult,
    save_validation_result,
    validate_batch,
)
from word_audit.models import (
    LOCATION_LOCATED,
    AnnotationResult,
    AuditIssue,
    AuditReport,
    LocationResult,
    utc_now_iso,
)
from word_audit.project1_batch import Project1Batch
from word_audit.typo_audit import TypoAuditResult, scan_batch_typos


class PipelineInputError(ValueError):
    """Raised when the batch JSON cannot be used for an audit."""


@dataclass
class AuditPipelineResult:
    report: AuditReport
    batch: Project1Batch
    validation: MathValidationResult
    locations: list[LocationResult]
    annotation: AnnotationBatchResult
    audit_json_path: Path
    audit_markdown_path: Path
    math_validation_path: Path
    output_files: list[Path]
    started_at: str
    finished_at: str
    warnings: list[str] = field(default_factory=list)


def _load_batch(path: str | Path) -> Project1Batch:
    source = Path(path).expanduser()
    if not source.is_file():
        raise PipelineInputError(f"批次 JSON 不存在：{source}")
    try:
        return Project1Batch.load(source)
    except json.JSONDecodeError as exc:
        raise PipelineInputError(f"批次 JSON 格式无效：{exc}") from exc
    except ValueError as exc:
        raise PipelineInputError(f"批次数据结构无效：{exc}") from exc
    except OSError as exc:
        raise PipelineInputError(f"无法读取批次 JSON：{exc}") from exc


def validate_batch_input(batch: Project1Batch) -> None:
    """Validate the minimum structure needed for a full audit."""

    errors: list[str] = []
    if not batch.batch_id.strip():
        errors.append("缺少 batch_id")
    if not batch.environmental_present:
        errors.append("缺少 environmental 字段或该字段不是对象")
    if not batch.documents:
        errors.append("documents 为空或缺失")

    seen_ids: set[str] = set()
    for index, document in enumerate(batch.documents, start=1):
        prefix = f"documents[{index - 1}]"
        if not document.document_id.strip():
            errors.append(f"{prefix} 缺少 document_id")
        elif document.document_id in seen_ids:
            errors.append(f"{prefix} 的 document_id 重复：{document.document_id}")
        else:
            seen_ids.add(document.document_id)
        if not document.source_file.strip():
            errors.append(f"{prefix} 缺少 source_file")
        if document.file_type not in {"word", "pdf"}:
            errors.append(
                f"{prefix} 的 file_type 无效：{document.file_type!r}"
            )

    if errors:
        raise PipelineInputError("批次输入结构错误：" + "；".join(errors))


def collect_audit_issues(
    validation: MathValidationResult,
    typo_result: TypoAuditResult | None = None,
) -> list[AuditIssue]:
    """Collect issues from all currently enabled audit rules.

    Future unit, missing-data or external-AI rules can append their issues here
    without changing the pipeline flow.
    """

    issues = list(validation.issues)
    if typo_result is not None:
        issues.extend(typo_result.issues)
    return issues


def _missing_source_warnings(batch: Project1Batch) -> list[str]:
    warnings: list[str] = []
    for document in batch.documents:
        if not Path(document.source_file).is_file():
            warnings.append(
                f"项目一源文件不存在，定位和批注可能失败：{document.source_file}"
            )
    return warnings


def _annotation_counts(annotation: AnnotationBatchResult) -> dict[str, int]:
    task = annotation.report.metadata.get("annotation_task", {})
    counts = task.get("counts")
    if isinstance(counts, dict):
        return {
            "total": int(counts.get("total", 0)),
            "applied": int(counts.get("applied", 0)),
            "failed": int(counts.get("failed", 0)),
            "manual_review": int(counts.get("manual_review", 0)),
        }
    annotations = annotation.report.annotations
    return {
        "total": len(annotations),
        "applied": sum(1 for item in annotations if item.status == "applied"),
        "failed": sum(1 for item in annotations if item.status == "failed"),
        "manual_review": sum(1 for item in annotations if item.status == "skipped"),
    }


def _location_summary(locations: list[LocationResult]) -> dict[str, Any]:
    return summarize_location_results(locations)


def _build_counts(
    validation: MathValidationResult,
    issues: list[AuditIssue],
    locations: list[LocationResult],
    annotation_counts: dict[str, int],
) -> dict[str, int]:
    math_summary = validation.summary()
    location_summary = _location_summary(locations)
    return {
        "record_count": int(math_summary["record_count"]),
        "verified_count": int(math_summary["verified_count"]),
        "unverified_count": int(math_summary["unverified_count"]),
        "issue_count": len(issues),
        "located_count": int(location_summary["located"]),
        "annotation_applied_count": int(annotation_counts["applied"]),
        "annotation_failed_count": int(annotation_counts["failed"]),
        "annotation_manual_review_count": int(annotation_counts["manual_review"]),
        "issues_flagged_for_manual_review": sum(
            1 for issue in issues if issue.needs_manual_review
        ),
    }


def _is_typo_issue(issue: AuditIssue) -> bool:
    return issue.issue_type == "typo" or issue.metadata.get("audit_rule") == "typo"


def _typo_counts(
    issues: list[AuditIssue],
    annotations: list[AnnotationResult],
    typo_result: TypoAuditResult,
) -> dict[str, int]:
    typo_issue_ids = {
        issue.issue_id for issue in issues if _is_typo_issue(issue)
    }
    typo_annotations = [
        annotation
        for annotation in annotations
        if annotation.issue_id in typo_issue_ids
    ]
    return {
        "typo_issue_count": len(typo_issue_ids),
        "typo_verified_count": typo_result.verified_count,
        "typo_manual_review_count": sum(
            1 for annotation in typo_annotations if annotation.status == "skipped"
        ),
        "typo_annotation_success_count": sum(
            1 for annotation in typo_annotations if annotation.status == "applied"
        ),
        "typo_annotation_failed_count": sum(
            1 for annotation in typo_annotations if annotation.status == "failed"
        ),
    }


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _location_text(location: LocationResult | None) -> str:
    if location is None:
        return "-"
    parts: list[str] = []
    if location.page_number is not None:
        parts.append(f"第{location.page_number}页")
    if location.paragraph_index is not None:
        parts.append(f"段落[{location.paragraph_index}]")
    if location.table_index is not None:
        parts.append(f"表格[{location.table_index}]")
    if location.row_index is not None:
        parts.append(f"行[{location.row_index}]")
    if location.column_index is not None:
        parts.append(f"列[{location.column_index}]")
    if location.bbox:
        parts.append("bbox=(" + ", ".join(f"{value:.1f}" for value in location.bbox) + ")")
    return " ".join(parts) if parts else "-"


def _computed_text(issue: AuditIssue) -> str:
    calculation = issue.calculation
    if calculation is None:
        return "无"
    if not calculation.is_verified or calculation.computed_value is None:
        return "未验证"
    unit = f" {calculation.unit}" if calculation.unit else ""
    value = calculation.computed_value
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value}{unit}"


def _write_pipeline_markdown(
    report: AuditReport,
    locations: list[LocationResult],
    pipeline: dict[str, Any],
    path: Path,
) -> None:
    issue_by_id = {issue.issue_id: issue for issue in report.issues}
    location_by_id = {location.issue_id: location for location in locations}
    annotation_by_id = {
        item.issue_id: item for item in report.annotations
    }
    counts = pipeline["counts"]
    typo_counts = pipeline["typo_counts"]
    stages = pipeline["stages"]
    successful = [item for item in report.annotations if item.status == "applied"]
    failed = [item for item in report.annotations if item.status == "failed"]
    manual = [item for item in report.annotations if item.status == "skipped"]

    lines: list[str] = [
        "# 完整审核报告",
        "",
        f"- 报告编号：{report.report_id}",
        f"- 批次：{report.batch_id or '-'}",
        f"- 生成时间：{report.generated_at}",
        f"- 流程完成状态：{'完整完成' if pipeline['complete_success'] else '部分完成'}",
        f"- 合成测试数据：{'是' if pipeline['synthetic_data'] else '否'}",
        "",
        "## 数量统计",
        "",
        "| 项目 | 数量 |",
        "| --- | ---: |",
        f"| 读取记录数 | {counts['record_count']} |",
        f"| verified | {counts['verified_count']} |",
        f"| unverified | {counts['unverified_count']} |",
        f"| 审核问题数 | {counts['issue_count']} |",
        f"| 定位成功数 | {counts['located_count']} |",
        f"| 批注成功数 | {counts['annotation_applied_count']} |",
        f"| 批注失败数 | {counts['annotation_failed_count']} |",
        f"| 批注人工核实数 | {counts['annotation_manual_review_count']} |",
        f"| 问题级人工核实标记数 | {counts['issues_flagged_for_manual_review']} |",
        "",
        "## 错别字检查统计",
        "",
        "| 项目 | 数量 |",
        "| --- | ---: |",
        f"| 错别字问题数 | {typo_counts['typo_issue_count']} |",
        f"| 高置信度错别字问题数 | {typo_counts['typo_verified_count']} |",
        f"| 错别字人工核实数 | {typo_counts['typo_manual_review_count']} |",
        f"| 错别字批注成功数 | {typo_counts['typo_annotation_success_count']} |",
        f"| 错别字批注失败数 | {typo_counts['typo_annotation_failed_count']} |",
        "",
        "## 阶段状态",
        "",
        "| 阶段 | 状态 | 说明 |",
        "| --- | --- | --- |",
        f"| 读取与校验 | {stages['load']['status']} | 文档 {stages['load']['document_count']} 个，环境记录 {stages['load']['environmental_record_count']} 条 |",
        f"| 数学校验 | {stages['math_validation']['status']} | 问题 {stages['math_validation']['summary']['issue_count']} 条 |",
        f"| 错别字检查 | {stages['typo_audit']['status']} | 扫描单元 {stages['typo_audit']['scanned_unit_count']}，问题 {stages['typo_audit']['issue_count']}，高置信 {stages['typo_audit']['verified_count']}，低置信 {stages['typo_audit']['low_confidence_count']} |",
        f"| 定位 | {stages['location']['status']} | 成功 {stages['location']['located']}，歧义 {stages['location']['ambiguous']}，未找到 {stages['location']['not_found']}，无效 {stages['location']['invalid_location']}，人工 {stages['location']['manual_review']} |",
        f"| 批注 | {stages['annotation']['status']} | 成功 {stages['annotation']['applied']}，失败 {stages['annotation']['failed']}，人工 {stages['annotation']['manual_review']} |",
        "",
        "## 输入文件",
        "",
    ]
    for source in pipeline["input"]["source_files"]:
        lines.append(f"- `{source}`")
    if not pipeline["input"]["source_files"]:
        lines.append("- 无")
    lines.extend(["", "## 输出文件", ""])
    output_files = pipeline["output_files"]
    if output_files:
        lines.extend(f"- `{item}`" for item in output_files)
    else:
        lines.append("- 无")
    lines.extend(["", "## 阶段报告", ""])
    for stage_name, stage_path in pipeline["stage_reports"].items():
        lines.append(f"- {stage_name}：`{stage_path}`")

    lines.extend(
        [
            "",
            "## 审核问题",
            "",
            "| 问题编号 | 类型 | 描述 | 原文 | 原始计算值 | 正确计算值 | 定位状态 | 定位位置 | 批注状态 | 问题级人工核实 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for issue in report.issues:
        location = location_by_id.get(issue.issue_id)
        annotation_item = annotation_by_id.get(issue.issue_id)
        reported = issue.calculation.reported_value if issue.calculation else None
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    issue.issue_id,
                    issue.issue_type,
                    issue.description,
                    issue.original_text,
                    reported,
                    _computed_text(issue),
                    location.locator_status if location else "-",
                    _location_text(location),
                    annotation_item.status if annotation_item else "-",
                    "是" if issue.needs_manual_review else "否",
                )
            )
            + " |"
        )
    if not report.issues:
        lines.append("| - | - | 无审核问题 | - | - | - | - | - | - | - |")

    typo_issues = [issue for issue in report.issues if _is_typo_issue(issue)]
    lines.extend(
        [
            "",
            "## 错别字检查明细",
            "",
            "| 问题编号 | 错误原文 | 建议修改 | 错误类型 | 判断依据 | 规则编号 | 上下文 | 定位粒度 | 文件 | 位置 | 定位状态 | 批注状态 | 出现次数 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for issue in typo_issues:
        location = location_by_id.get(issue.issue_id)
        annotation_item = annotation_by_id.get(issue.issue_id)
        metadata = issue.metadata
        file_name = (
            Path(issue.location.source_file).name
            if issue.location is not None
            else "-"
        )
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    issue.issue_id,
                    metadata.get("error_text", issue.original_text),
                    metadata.get("suggested_text", issue.suggestion),
                    metadata.get("issue_type_label", "错别字"),
                    metadata.get("typo_reason", "-"),
                    metadata.get("typo_rule_id", "-"),
                    metadata.get("context", "-"),
                    metadata.get("location_granularity", "-"),
                    file_name,
                    _location_text(location),
                    location.locator_status if location else "-",
                    annotation_item.status if annotation_item else "-",
                    metadata.get("occurrence_count", 1),
                )
            )
            + " |"
        )
    if not typo_issues:
        lines.append(
            "| - | - | 无错别字问题 | - | - | - | - | - | - | - | - | - | - |"
        )

    lines.extend(
        [
            "",
            "## 批注成功清单",
            "",
            "| 问题编号 | 文档 | 位置 | 批注首行 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in successful:
        first_line = item.comment_text.splitlines()[0] if item.comment_text else ""
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    item.issue_id,
                    item.document_id,
                    _location_text(location_by_id.get(item.issue_id)),
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
    for item in failed:
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (item.issue_id, item.document_id, item.error or "-")
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
    for item in manual:
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    item.issue_id,
                    item.document_id,
                    item.metadata.get("locator_status", "-"),
                    item.error or item.metadata.get("failure_reason", "-"),
                )
            )
            + " |"
        )
    if not manual:
        lines.append("| - | - | - | 无 |")

    lines.extend(["", "## 警告与异常", ""])
    messages = list(pipeline.get("warnings", [])) + list(
        pipeline.get("errors", [])
    )
    if messages:
        lines.extend(f"- {_md_cell(message)}" for message in messages)
    else:
        lines.append("- 无")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def run_audit(
    batch_json: str | Path,
    output_dir: str | Path | None = None,
) -> AuditPipelineResult:
    """Run the complete audit flow for one project one batch JSON.

    ``output_dir`` defaults to the project ``output`` directory, not the
    current working directory.
    """

    started_at = utc_now_iso()
    started_monotonic = time.monotonic()
    batch = _load_batch(batch_json)
    validate_batch_input(batch)

    synthetic_data = batch.metadata.get("synthetic_data") is True
    validation = validate_batch(batch)
    typo_result = scan_batch_typos(batch)
    issues = collect_audit_issues(validation, typo_result)
    if synthetic_data:
        for issue in issues:
            issue.metadata["synthetic"] = True
            issue.metadata.setdefault(
                "synthetic_note",
                "合成测试数据，非项目一真实审核结果",
            )

    locations = locate_issues(batch, issues)
    output_root = resolve_output_root(output_dir)
    annotated_dir = output_root / "annotated"
    report_dir = output_root / "reports"

    math_validation_path = unique_path(
        report_dir,
        f"{batch.batch_id}_math_validation",
        ".json",
    )
    save_validation_result(validation, math_validation_path)

    annotation = annotate_issues(
        batch,
        issues,
        locations,
        output_dir=annotated_dir,
        report_dir=report_dir,
    )

    finished_at = utc_now_iso()
    duration_seconds = round(time.monotonic() - started_monotonic, 3)
    location_summary = _location_summary(locations)
    annotation_counts = _annotation_counts(annotation)
    counts = _build_counts(validation, issues, locations, annotation_counts)
    typo_counts = _typo_counts(issues, annotation.report.annotations, typo_result)

    missing_source_warnings = _missing_source_warnings(batch)
    warnings = list(dict.fromkeys(
        [
            *missing_source_warnings,
            *typo_result.warnings,
            *annotation.report.warnings,
        ]
    ))
    if synthetic_data:
        synthetic_warning = "本次审核使用合成测试数据，非项目一真实审核结果。"
        if synthetic_warning not in warnings:
            warnings.append(synthetic_warning)

    location_failed = any(
        location.locator_status != LOCATION_LOCATED for location in locations
    )
    complete_success = (
        not missing_source_warnings
        and not location_failed
        and annotation_counts["failed"] == 0
        and annotation_counts["manual_review"] == 0
    )

    audit_json_path, audit_markdown_path = unique_report_paths(
        report_dir,
        f"audit_report_{batch.batch_id}",
    )
    pipeline_metadata = {
        "synthetic_data": synthetic_data,
        "complete_success": complete_success,
        "input": {
            "batch_json": str(batch.path),
            "batch_id": batch.batch_id,
            "schema_version": batch.schema_version,
            "document_count": len(batch.documents),
            "environmental_record_count": len(batch.environmental_records),
            "source_files": [document.source_file for document in batch.documents],
        },
        "timing": {
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
        },
        "counts": counts,
        "typo_counts": typo_counts,
        "stages": {
            "load": {
                "status": "warning" if missing_source_warnings else "ok",
                "document_count": len(batch.documents),
                "environmental_record_count": len(batch.environmental_records),
                "warnings": missing_source_warnings,
            },
            "math_validation": {
                "status": "ok",
                "summary": validation.summary(),
                "report": str(math_validation_path),
            },
            "typo_audit": {
                "status": "ok",
                "scanned_unit_count": typo_result.scanned_unit_count,
                "issue_count": len(typo_result.issues),
                "verified_count": typo_result.verified_count,
                "low_confidence_count": typo_result.low_confidence_count,
                "warnings": typo_result.warnings,
            },
            "location": {
                "status": "ok" if not location_failed else "partial",
                **location_summary,
            },
            "annotation": {
                "status": (
                    "ok"
                    if annotation_counts["failed"] == 0
                    and annotation_counts["manual_review"] == 0
                    else "partial"
                ),
                **annotation_counts,
                "report": str(annotation.json_path),
                "markdown_report": str(annotation.markdown_path),
                "output_files": [str(path) for path in annotation.output_files],
            },
        },
        "output_files": [str(path) for path in annotation.output_files],
        "stage_reports": {
            "math_validation": str(math_validation_path),
            "annotation_json": str(annotation.json_path),
            "annotation_markdown": str(annotation.markdown_path),
            "audit_json": str(audit_json_path),
            "audit_markdown": str(audit_markdown_path),
        },
        "warnings": warnings,
        "errors": [],
    }

    report = AuditReport(
        report_id=f"audit-{uuid.uuid4().hex}",
        batch_id=batch.batch_id,
        generated_at=finished_at,
        source_batch=str(batch.path),
        documents=list(annotation.report.documents),
        issues=list(annotation.report.issues),
        annotations=list(annotation.report.annotations),
        warnings=warnings,
        metadata={
            "annotation_task": dict(
                annotation.report.metadata.get("annotation_task", {})
            ),
            "pipeline": pipeline_metadata,
        },
    )
    report.validate()

    audit_json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_pipeline_markdown(
        report,
        locations,
        pipeline_metadata,
        audit_markdown_path,
    )

    return AuditPipelineResult(
        report=report,
        batch=batch,
        validation=validation,
        locations=locations,
        annotation=annotation,
        audit_json_path=audit_json_path,
        audit_markdown_path=audit_markdown_path,
        math_validation_path=math_validation_path,
        output_files=list(annotation.output_files),
        started_at=started_at,
        finished_at=finished_at,
        warnings=warnings,
    )
