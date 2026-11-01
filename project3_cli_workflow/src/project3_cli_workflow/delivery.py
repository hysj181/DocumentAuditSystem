"""最终交付目录、审核报告汇总和交付清单。

本模块只读取已有阶段产物，不重新执行项目一或项目二。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from project3_cli_workflow.errors import AuditValidationError, ManifestError
from project3_cli_workflow.manifest import calculate_sha256, utc_now_iso
from project3_cli_workflow.models import (
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_PARTIAL,
    DELIVERY_STATUS_SUCCESS,
    OVERALL_STATUS_FAILED,
    OVERALL_STATUS_PARTIAL,
    OVERALL_STATUS_SUCCESS,
    RunManifest,
)
from project3_cli_workflow.project2 import AuditSummary

DELIVERY_DIR_NAME = "03_delivery"
STAGING_DIR_NAME = ".03_delivery_staging"
INPUT_MANIFEST_RELATIVE = Path("00_inputs") / "input_manifest.json"
AUDIT_COUNT_FIELDS = (
    "record_count",
    "verified_count",
    "unverified_count",
    "issue_count",
    "located_count",
    "annotation_applied_count",
    "annotation_failed_count",
    "annotation_manual_review_count",
    "issues_flagged_for_manual_review",
)
AUDIT_TYPO_COUNT_FIELDS = (
    "typo_issue_count",
    "typo_verified_count",
    "typo_manual_review_count",
    "typo_annotation_success_count",
    "typo_annotation_failed_count",
)

@dataclass(frozen=True)
class DeliveryArtifact:
    """一个已生成的交付文件。"""

    name: str
    path: str
    type: str
    exists: bool
    size: int | None
    sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "type": self.type,
            "exists": self.exists,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class MissingArtifact:
    """一个缺失或无法复制的交付项。"""

    name: str
    type: str
    source_path: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "source_path": self.source_path,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DeliveryResult:
    """最终交付阶段结果。"""

    status: str
    overall_status: str
    started_at: str
    finished_at: str
    directory: Path | None
    report_json: Path | None
    report_markdown: Path | None
    summary_markdown: Path
    delivery_manifest_json: Path
    artifacts: list[DeliveryArtifact] = field(default_factory=list)
    missing_artifacts: list[MissingArtifact] = field(
        default_factory=list
    )
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _relative_to_task(path: Path, task_dir: Path) -> str:
    """返回相对于任务目录的路径字符串。"""

    try:
        return str(path.resolve().relative_to(task_dir.resolve()))
    except ValueError:
        return str(path.resolve())


def _write_text(path: Path, content: str) -> None:
    """写入 UTF-8 文本，失败时转换为 ManifestError。"""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"无法写入交付文件：{path}；{exc}") from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """写入 UTF-8 JSON。"""

    _write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """原子写入 JSON。"""

    temp_path = path.with_name(f".{path.name}.tmp")
    _write_text(
        temp_path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    try:
        temp_path.replace(path)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise ManifestError(f"无法替换交付文件：{path}；{exc}") from exc


def _artifact_from_file(
    path: Path,
    task_dir: Path,
    artifact_type: str,
    *,
    final_path: Path | None = None,
) -> DeliveryArtifact:
    """从真实文件构建交付产物记录。"""

    target = final_path or path
    exists = path.is_file()
    size = path.stat().st_size if exists else None
    sha256 = calculate_sha256(path) if exists else None
    return DeliveryArtifact(
        name=target.name,
        path=_relative_to_task(target, task_dir),
        type=artifact_type,
        exists=exists,
        size=size,
        sha256=sha256,
    )


def _same_path(left: Path, right: Path) -> bool:
    """判断两个路径是否指向同一文件。"""

    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _unique_destination(directory: Path, file_name: str) -> Path:
    """为同名批注文件生成不覆盖的目标路径。"""

    candidate = directory / file_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _load_audit_payload(path: Path) -> dict[str, Any]:
    """读取审核报告原始 JSON。"""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditValidationError(
            f"无法读取审核报告：{path}；{exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AuditValidationError(f"审核报告顶层必须是对象：{path}")
    return payload


def _as_list(value: Any) -> list[str]:
    """把可选的 JSON 数组转换为字符串列表。"""

    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _parse_counts(value: Any, field_name: str) -> dict[str, int]:
    """校验并读取审核报告必填计数。"""

    if not isinstance(value, dict):
        raise AuditValidationError(f"{field_name} 必须是对象。")
    counts: dict[str, int] = {}
    for name in AUDIT_COUNT_FIELDS:
        item = value.get(name)
        if isinstance(item, bool) or not isinstance(item, int):
            raise AuditValidationError(
                f"{field_name}.{name} 必须是整数。"
            )
        counts[name] = item
    return counts


def _parse_optional_counts(value: Any) -> dict[str, int]:
    """读取可选错别字计数，缺失字段不伪造。"""

    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for name in AUDIT_TYPO_COUNT_FIELDS:
        item = value.get(name)
        if isinstance(item, int) and not isinstance(item, bool):
            counts[name] = item
    return counts


def _resolve_report_relative(
    value: str | None,
    report_path: Path,
) -> Path | None:
    """解析报告内或 manifest 中的相对路径。"""

    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = report_path.parent / path
    return path.resolve()


def _parse_audit_report(
    report_path: Path,
    manifest: RunManifest,
) -> tuple[AuditSummary, dict[str, Any]]:
    """从真实审核报告生成交付所需摘要，可选字段缺失时保持空值。"""

    raw_report = _load_audit_payload(report_path)
    if raw_report.get("schema_version") != "1.0":
        raise AuditValidationError("不支持的审核报告 schema_version。")
    batch_id = raw_report.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise AuditValidationError("审核报告 batch_id 缺失。")
    if manifest.batch_id and batch_id != manifest.batch_id:
        raise AuditValidationError(
            "审核报告 batch_id 与 manifest 不一致："
            f"{batch_id!r} != {manifest.batch_id!r}。"
        )

    metadata = raw_report.get("metadata")
    if not isinstance(metadata, dict):
        raise AuditValidationError("审核报告 metadata 必须是对象。")
    pipeline = metadata.get("pipeline")
    if not isinstance(pipeline, dict):
        raise AuditValidationError(
            "审核报告 metadata.pipeline 必须是对象。"
        )
    complete_success = pipeline.get("complete_success")
    if not isinstance(complete_success, bool):
        raise AuditValidationError(
            "审核报告 complete_success 必须是布尔值。"
        )
    counts = _parse_counts(
        pipeline.get("counts"),
        "metadata.pipeline.counts",
    )
    typo_counts = _parse_optional_counts(pipeline.get("typo_counts"))

    pipeline_warnings = pipeline.get("warnings")
    top_warnings = raw_report.get("warnings")
    warnings = list(
        dict.fromkeys(
            [
                *(_as_list(top_warnings) if isinstance(top_warnings, list) else []),
                *(
                    _as_list(pipeline_warnings)
                    if isinstance(pipeline_warnings, list)
                    else []
                ),
            ]
        )
    )

    stage_payload = pipeline.get("stage_reports")
    stage_reports = (
        stage_payload if isinstance(stage_payload, dict) else {}
    )
    audit_markdown_path = _resolve_report_relative(
        stage_reports.get("audit_markdown")
        if isinstance(stage_reports.get("audit_markdown"), str)
        else manifest.audit_report_markdown,
        report_path,
    )
    annotation_report_path = _resolve_report_relative(
        stage_reports.get("annotation_json")
        if isinstance(stage_reports.get("annotation_json"), str)
        else manifest.annotation_report,
        report_path,
    )
    math_validation_path = _resolve_report_relative(
        stage_reports.get("math_validation")
        if isinstance(stage_reports.get("math_validation"), str)
        else manifest.math_validation_report,
        report_path,
    )

    output_files: list[Path] = []
    output_payload = pipeline.get("output_files")
    if isinstance(output_payload, list):
        for item in output_payload:
            path = _resolve_report_relative(
                item if isinstance(item, str) else None,
                report_path,
            )
            if path is not None:
                output_files.append(path)

    summary = AuditSummary(
        batch_id=batch_id,
        complete_success=complete_success,
        counts=counts,
        typo_counts=typo_counts,
        warnings=warnings,
        stage_reports={
            str(key): str(value)
            for key, value in stage_reports.items()
        },
        output_files=output_files,
        audit_json_path=report_path,
        audit_markdown_path=audit_markdown_path,
        annotation_report_path=annotation_report_path,
        math_validation_path=math_validation_path,
    )
    return summary, raw_report


def _display(value: Any) -> str:
    """用于 Markdown 的 None 显示。"""

    return "无" if value is None else str(value)


def _generate_audit_report_json(
    manifest: RunManifest,
    summary: AuditSummary,
    raw_report: dict[str, Any],
    *,
    overall_status: str,
    annotated_files: list[str],
) -> dict[str, Any]:
    """生成审核报告汇总 JSON。"""

    pipeline = (raw_report.get("metadata") or {}).get("pipeline") or {}
    counts = summary.counts
    typo_counts = summary.typo_counts
    source_reports = {
        "project1_batch_json": manifest.batch_json_path,
        "project2_audit_report_json": manifest.audit_report_json,
        "project2_audit_report_markdown": manifest.audit_report_markdown,
        "project2_annotation_report_json": manifest.annotation_report,
        "project2_math_validation_json": manifest.math_validation_report,
    }
    return {
        "schema_version": "1.0",
        "job_id": manifest.job_id,
        "batch_id": manifest.batch_id,
        "report_id": raw_report.get("report_id"),
        "generated_at": raw_report.get("generated_at"),
        "overall_status": overall_status,
        "extraction_status": manifest.extraction_status,
        "audit_status": manifest.audit_status,
        "extraction_document_count": manifest.document_count,
        "extraction_successful_document_count": (
            manifest.successful_document_count
        ),
        "extraction_failed_document_count": (
            manifest.failed_document_count
        ),
        "audit_record_count": counts["record_count"],
        "verified_count": counts["verified_count"],
        "unverified_count": counts["unverified_count"],
        "issue_count": counts["issue_count"],
        "located_count": counts["located_count"],
        "annotation_applied_count": counts["annotation_applied_count"],
        "annotation_failed_count": counts["annotation_failed_count"],
        "annotation_manual_review_count": counts[
            "annotation_manual_review_count"
        ],
        "typo_issue_count": typo_counts.get("typo_issue_count"),
        "typo_verified_count": typo_counts.get("typo_verified_count"),
        "warnings": list(summary.warnings),
        "errors": _as_list(pipeline.get("errors")),
        "source_reports": source_reports,
        "annotated_files": annotated_files,
        "source_annotated_files": [
            str(path) for path in summary.output_files
        ],
        "complete_success": summary.complete_success,
        "data_source": {
            "extraction_statistics": "manifest.json / 项目一 batch.json",
            "audit_statistics": "项目二 audit_report_<batch_id>.json",
            "audit_counts_source": "metadata.pipeline.counts",
            "typo_counts_source": "metadata.pipeline.typo_counts",
        },
        "notes": [
            "complete_success=True 仅表示项目二审核流程完整，不代表数据合规。",
            "unverified 记录不属于 issue_count。",
            "manual_review 表示需要人工复核，不是已确认错误。",
        ],
    }


def _generate_audit_report_markdown(
    manifest: RunManifest,
    summary: AuditSummary,
    raw_report: dict[str, Any],
    *,
    overall_status: str,
    annotated_files: list[str],
) -> str:
    """生成审核报告汇总 Markdown。"""

    counts = summary.counts
    typo_counts = summary.typo_counts
    lines = [
        "# 审核报告汇总",
        "",
        "> 数据来源：项目二真实审核报告和项目一真实批次统计。",
        "> 本汇总不重新执行审核，不修改项目二原始报告。",
        "",
        "## 任务基本信息",
        "",
        "| 字段 | 值 |",
        "| --- | --- |",
        f"| 任务 ID | {_display(manifest.job_id)} |",
        f"| 批次 ID | {_display(manifest.batch_id)} |",
        f"| 审核报告 ID | {_display(raw_report.get('report_id'))} |",
        f"| 报告生成时间 | {_display(raw_report.get('generated_at'))} |",
        f"| 整体状态 | {overall_status} |",
        f"| 提取状态 | {manifest.extraction_status} |",
        f"| 审核状态 | {manifest.audit_status} |",
        f"| complete_success | {summary.complete_success} |",
        "",
        "## 输入文件",
        "",
    ]
    if manifest.inputs:
        for item in manifest.inputs:
            lines.append(
                f"- {item.file_name}：`{item.source_path}`"
            )
    else:
        lines.append("- 无有效输入文件。")
    if manifest.filtered_inputs:
        lines.extend(["", "### 过滤文件", ""])
        for item in manifest.filtered_inputs:
            lines.append(
                f"- {item.file_name}：{item.message}"
                f"（`{item.source_path}`）"
            )

    lines.extend(
        [
            "",
            "## 提取阶段结果",
            "",
            f"- 文档总数：{_display(manifest.document_count)}",
            f"- 成功文档：{_display(manifest.successful_document_count)}",
            f"- 失败文档：{_display(manifest.failed_document_count)}",
            f"- 提取警告数：{_display(manifest.warning_count)}",
            f"- 项目一 batch.json：`{_display(manifest.batch_json_path)}`",
            "",
            "## 审核阶段结果",
            "",
            f"- 审核记录数：{counts['record_count']}",
            f"- verified：{counts['verified_count']}",
            f"- unverified：{counts['unverified_count']}",
            f"- 已发现问题数：{counts['issue_count']}",
            f"- 定位成功数：{counts['located_count']}",
            f"- 批注成功数：{counts['annotation_applied_count']}",
            f"- 批注失败数：{counts['annotation_failed_count']}",
            f"- 批注人工核实数：{counts['annotation_manual_review_count']}",
            f"- 问题级人工核实标记数：{counts['issues_flagged_for_manual_review']}",
            "",
            "## 错别字检查统计",
            "",
            f"- 错别字问题数：{_display(typo_counts.get('typo_issue_count'))}",
            f"- 高置信度错别字问题数：{_display(typo_counts.get('typo_verified_count'))}",
            f"- 错别字人工核实数：{_display(typo_counts.get('typo_manual_review_count'))}",
            f"- 错别字批注成功数：{_display(typo_counts.get('typo_annotation_success_count'))}",
            f"- 错别字批注失败数：{_display(typo_counts.get('typo_annotation_failed_count'))}",
            "",
            "## 批注文件",
            "",
        ]
    )
    if annotated_files:
        lines.extend(f"- `{path}`" for path in annotated_files)
    else:
        lines.append("- 无自动批注文件。")

    lines.extend(["", "## 警告与错误", ""])
    messages = list(summary.warnings) + _as_list(
        ((raw_report.get("metadata") or {}).get("pipeline") or {}).get(
            "errors"
        )
    )
    if messages:
        lines.extend(f"- {item}" for item in dict.fromkeys(messages))
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 整体状态与注意事项",
            "",
            f"- 整体状态：{overall_status}",
            "- complete_success=True 仅表示项目二流程完整，不代表所有数据合规。",
            "- unverified 表示没有可验证的明确计算表达式，不能计入 issue_count。",
            "- manual_review 表示需要人工复核，不能直接视为已确认错误。",
            "- 审核问题数量均来自项目二报告，本汇总不重新计算。",
            "",
            "## 来源报告",
            "",
            f"- 项目一 batch.json：`{_display(manifest.batch_json_path)}`",
            f"- 审核报告 JSON：`{_display(manifest.audit_report_json)}`",
            f"- 审核报告 Markdown：`{_display(manifest.audit_report_markdown)}`",
            f"- 批注阶段报告：`{_display(manifest.annotation_report)}`",
            f"- 数学校验报告：`{_display(manifest.math_validation_report)}`",
            "",
        ]
    )
    return "\n".join(lines)


def _generate_run_summary(
    manifest: RunManifest,
    delivery_status: str,
    overall_status: str,
    task_dir: Path,
    missing: list[MissingArtifact],
    warnings: list[str],
) -> str:
    """生成运行摘要 Markdown。"""

    total_inputs = manifest.input_count + len(manifest.filtered_inputs)
    annotated_count = len(manifest.annotated_files)
    lines = [
        "# 运行摘要",
        "",
        "## 任务信息",
        "",
        f"- 任务 ID：{manifest.job_id}",
        f"- 创建时间：{manifest.created_at}",
        f"- 任务目录：`{task_dir}`",
        f"- 交付状态：{delivery_status}",
        f"- 最终状态：{overall_status}",
        "",
        "## 输入文件",
        "",
        f"- 输入文件数量：{total_inputs}",
        f"- 有效文件数量：{manifest.input_count}",
        f"- 过滤文件数量：{len(manifest.filtered_inputs)}",
        "",
        "## 提取结果",
        "",
        f"- 提取状态：{manifest.extraction_status}",
        f"- 提取文档总数：{_display(manifest.document_count)}",
        f"- 提取成功文档：{_display(manifest.successful_document_count)}",
        f"- 提取失败文档：{_display(manifest.failed_document_count)}",
        "",
        "## 审核结果",
        "",
        f"- 审核状态：{manifest.audit_status}",
        f"- 已发现问题数量：{_display(manifest.audit_issue_count)}",
        f"- 未核实记录数量：{_display(manifest.audit_unverified_count)}",
        f"- 人工复核数量：{_display(manifest.audit_manual_review_count)}",
        f"- 批注文件数量：{annotated_count}",
        "",
        "## 交付结果",
        "",
        f"- 输出目录：`{task_dir / DELIVERY_DIR_NAME}`",
        f"- 缺失交付项数量：{len(missing)}",
    ]
    if warnings:
        lines.extend(["", "## 交付警告", ""])
        lines.extend(f"- {item}" for item in warnings)
    if missing:
        lines.extend(["", "## 缺失交付项", ""])
        lines.extend(
            f"- {item.name}：{item.reason}" for item in missing
        )
    lines.append("")
    return "\n".join(lines)


def _check_source_artifact(
    name: str,
    path_text: str | None,
    artifact_type: str,
    missing: list[MissingArtifact],
) -> None:
    """检查报告声明的关键源文件是否存在。"""

    if not path_text:
        missing.append(
            MissingArtifact(
                name=name,
                type=artifact_type,
                source_path=None,
                reason="manifest 未记录该路径",
            )
        )
        return
    path = Path(path_text)
    if not path.is_file():
        missing.append(
            MissingArtifact(
                name=name,
                type=artifact_type,
                source_path=str(path),
                reason="文件不存在",
            )
        )


def _copy_annotated_files(
    manifest: RunManifest,
    summary: AuditSummary,
    staging_dir: Path,
    missing: list[MissingArtifact],
    warnings: list[str],
) -> list[str]:
    """复制真实批注文件并校验 SHA-256。"""

    target_dir = staging_dir / "批注文件"
    target_dir.mkdir(parents=True, exist_ok=True)
    original_inputs = [Path(item.source_path) for item in manifest.inputs]
    copied: list[str] = []

    for source in summary.output_files:
        if not source.is_file():
            missing.append(
                MissingArtifact(
                    name=source.name,
                    type="annotated_file",
                    source_path=str(source),
                    reason="批注文件不存在",
                )
            )
            continue
        if any(_same_path(source, item) for item in original_inputs):
            missing.append(
                MissingArtifact(
                    name=source.name,
                    type="annotated_file",
                    source_path=str(source),
                    reason="批注文件路径与原始输入相同，拒绝复制",
                )
            )
            continue

        destination = _unique_destination(target_dir, source.name)
        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            missing.append(
                MissingArtifact(
                    name=source.name,
                    type="annotated_file",
                    source_path=str(source),
                    reason=f"复制失败：{exc}",
                )
            )
            continue

        if (
            not destination.is_file()
            or destination.stat().st_size != source.stat().st_size
            or calculate_sha256(destination)
            != calculate_sha256(source)
        ):
            destination.unlink(missing_ok=True)
            missing.append(
                MissingArtifact(
                    name=source.name,
                    type="annotated_file",
                    source_path=str(source),
                    reason="复制后文件大小或 SHA-256 不一致",
                )
            )
            continue

        copied.append(
            str(
                Path(DELIVERY_DIR_NAME)
                / "批注文件"
                / destination.name
            )
        )

    if not summary.output_files:
        warnings.append(
            "项目二报告未记录批注文件，交付目录中的批注文件为空。"
        )
    return copied


def run_delivery(
    manifest: RunManifest,
    manifest_path: str | Path,
) -> DeliveryResult:
    """从现有 manifest 和真实阶段产物生成最终交付目录。"""

    manifest_file = Path(manifest_path).expanduser().resolve()
    task_dir = manifest_file.parent
    delivery_dir = task_dir / DELIVERY_DIR_NAME
    staging_dir = task_dir / STAGING_DIR_NAME
    started_at = utc_now_iso()

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)
    missing: list[MissingArtifact] = []
    warnings: list[str] = []

    input_manifest_path = task_dir / INPUT_MANIFEST_RELATIVE
    input_manifest_payload = {
        "schema_version": "1.0",
        "job_id": manifest.job_id,
        "created_at": manifest.created_at,
        "input_count": manifest.input_count,
        "inputs": [item.to_dict() for item in manifest.inputs],
        "filtered_inputs": [
            item.to_dict() for item in manifest.filtered_inputs
        ],
    }
    _write_json_atomic(input_manifest_path, input_manifest_payload)

    audit_path_text = manifest.audit_report_json
    audit_path = Path(audit_path_text) if audit_path_text else None
    summary: AuditSummary | None = None
    raw_report: dict[str, Any] | None = None
    delivery_error: str | None = None

    if audit_path is None or not audit_path.is_file():
        missing.append(
            MissingArtifact(
                name="audit_report_json",
                type="audit_report",
                source_path=str(audit_path) if audit_path else None,
                reason="项目二审核报告不存在",
            )
        )
        delivery_error = (
            "项目二审核报告不存在，无法生成审核报告汇总。"
        )
    else:
        try:
            summary, raw_report = _parse_audit_report(
                audit_path,
                manifest,
            )
        except AuditValidationError as exc:
            missing.append(
                MissingArtifact(
                    name="audit_report_json",
                    type="audit_report",
                    source_path=str(audit_path),
                    reason=exc.message,
                )
            )
            delivery_error = f"项目二审核报告无效：{exc.message}"

    _check_source_artifact(
        "project1_batch_json",
        manifest.batch_json_path,
        "batch_json",
        missing,
    )
    _check_source_artifact(
        "audit_report_markdown",
        manifest.audit_report_markdown,
        "audit_report_markdown",
        missing,
    )
    _check_source_artifact(
        "annotation_report_json",
        manifest.annotation_report,
        "annotation_report",
        missing,
    )
    _check_source_artifact(
        "math_validation_json",
        manifest.math_validation_report,
        "math_validation",
        missing,
    )

    annotated_files: list[str] = []
    if summary is not None:
        annotated_files = _copy_annotated_files(
            manifest,
            summary,
            staging_dir,
            missing,
            warnings,
        )

    if summary is None:
        delivery_status = DELIVERY_STATUS_FAILED
        overall_status = OVERALL_STATUS_FAILED
    else:
        delivery_status = (
            DELIVERY_STATUS_PARTIAL if missing else DELIVERY_STATUS_SUCCESS
        )
        overall_status = manifest.overall_status
        if delivery_status == DELIVERY_STATUS_FAILED:
            overall_status = OVERALL_STATUS_FAILED
        elif (
            delivery_status == DELIVERY_STATUS_PARTIAL
            and overall_status == OVERALL_STATUS_SUCCESS
        ):
            overall_status = OVERALL_STATUS_PARTIAL
        elif overall_status not in {
            OVERALL_STATUS_SUCCESS,
            OVERALL_STATUS_PARTIAL,
            OVERALL_STATUS_FAILED,
        }:
            overall_status = OVERALL_STATUS_FAILED

    report_json_path: Path | None = None
    report_markdown_path: Path | None = None
    if summary is not None and raw_report is not None:
        report_payload = _generate_audit_report_json(
            manifest,
            summary,
            raw_report,
            overall_status=overall_status,
            annotated_files=annotated_files,
        )
        report_markdown = _generate_audit_report_markdown(
            manifest,
            summary,
            raw_report,
            overall_status=overall_status,
            annotated_files=annotated_files,
        )
        report_json_path = staging_dir / "审核报告.json"
        report_markdown_path = staging_dir / "审核报告.md"
        _write_json(report_json_path, report_payload)
        _write_text(report_markdown_path, report_markdown)

    summary_path = staging_dir / "运行摘要.md"
    _write_text(
        summary_path,
        _generate_run_summary(
            manifest,
            delivery_status,
            overall_status,
            task_dir,
            missing,
            warnings,
        ),
    )

    artifacts: list[DeliveryArtifact] = []
    artifacts.append(
        _artifact_from_file(
            input_manifest_path,
            task_dir,
            "input_manifest",
        )
    )
    if report_json_path is not None:
        artifacts.append(
            _artifact_from_file(
                report_json_path,
                task_dir,
                "audit_report",
                final_path=delivery_dir / "审核报告.json",
            )
        )
    if report_markdown_path is not None:
        artifacts.append(
            _artifact_from_file(
                report_markdown_path,
                task_dir,
                "audit_report_markdown",
                final_path=delivery_dir / "审核报告.md",
            )
        )
    artifacts.append(
        _artifact_from_file(
            summary_path,
            task_dir,
            "run_summary",
            final_path=delivery_dir / "运行摘要.md",
        )
    )
    annotated_dir = staging_dir / "批注文件"
    if annotated_dir.is_dir():
        for source in sorted(annotated_dir.iterdir()):
            if not source.is_file():
                continue
            artifacts.append(
                _artifact_from_file(
                    source,
                    task_dir,
                    "annotated_file",
                    final_path=delivery_dir / "批注文件" / source.name,
                )
            )

    delivery_manifest_payload = {
        "schema_version": "1.0",
        "job_id": manifest.job_id,
        "created_at": utc_now_iso(),
        "overall_status": overall_status,
        "delivery_status": delivery_status,
        "artifacts": [item.to_dict() for item in artifacts],
        "missing_artifacts": [
            item.to_dict() for item in missing
        ],
        "warnings": list(warnings),
    }
    staging_manifest_path = staging_dir / "交付清单.json"
    _write_json(staging_manifest_path, delivery_manifest_payload)

    delivery_manifest_path = delivery_dir / "交付清单.json"
    try:
        if delivery_dir.exists():
            shutil.rmtree(delivery_dir)
        staging_dir.rename(delivery_dir)
    except OSError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise ManifestError(
            f"无法生成最终交付目录：{delivery_dir}；{exc}"
        ) from exc

    finished_at = utc_now_iso()
    final_report_json = (
        delivery_dir / "审核报告.json"
        if report_json_path is not None
        else None
    )
    final_report_markdown = (
        delivery_dir / "审核报告.md"
        if report_markdown_path is not None
        else None
    )
    return DeliveryResult(
        status=delivery_status,
        overall_status=overall_status,
        started_at=started_at,
        finished_at=finished_at,
        directory=delivery_dir,
        report_json=final_report_json,
        report_markdown=final_report_markdown,
        summary_markdown=delivery_dir / "运行摘要.md",
        delivery_manifest_json=delivery_manifest_path,
        artifacts=artifacts,
        missing_artifacts=missing,
        warnings=warnings,
        error=delivery_error,
    )
