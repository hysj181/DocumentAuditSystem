"""阶段结果有效性和任务查找。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from project3_cli_workflow.errors import (
    AuditValidationError,
    BatchValidationError,
    ManifestError,
)
from project3_cli_workflow.fingerprint import Fingerprint
from project3_cli_workflow.manifest import calculate_sha256, load_manifest
from project3_cli_workflow.models import (
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_SUCCESS,
    DELIVERY_STATUS_SUCCESS,
    EXTRACTION_STATUS_PARTIAL,
    EXTRACTION_STATUS_SUCCESS,
    InputFile,
    RunManifest,
)
from project3_cli_workflow.project1 import load_batch_summary
from project3_cli_workflow.project2 import load_audit_report


@dataclass(frozen=True)
class StageValidation:
    """阶段复用判断结果。"""

    valid: bool
    reasons: list[str] = field(default_factory=list)


def _is_within(path: Path, parent: Path) -> bool:
    """判断路径是否位于任务目录内。"""

    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _path_key(path: str | Path) -> str:
    """路径比较键。"""

    return os.path.normcase(str(Path(path).expanduser().resolve()))


def inputs_match(
    manifest_inputs: list[InputFile],
    current_inputs: list[InputFile],
) -> bool:
    """比较 manifest 输入与当前输入的数量、路径和 SHA-256。"""

    if len(manifest_inputs) != len(current_inputs):
        return False
    expected = {
        _path_key(item.source_path): item.sha256 for item in current_inputs
    }
    actual = {
        _path_key(item.source_path): item.sha256
        for item in manifest_inputs
    }
    return expected == actual


def validate_extraction(
    manifest: RunManifest,
    task_dir: Path,
    current_inputs: list[InputFile],
    *,
    mode: str,
) -> StageValidation:
    """检查项目一提取结果是否可安全复用。"""

    reasons: list[str] = []
    if manifest.extraction_status not in {
        EXTRACTION_STATUS_SUCCESS,
        EXTRACTION_STATUS_PARTIAL,
    }:
        reasons.append(
            f"提取状态不可复用：{manifest.extraction_status}"
        )
    if not manifest.batch_json_path:
        reasons.append("manifest 缺少 batch_json_path")
    else:
        batch_path = Path(manifest.batch_json_path)
        if not batch_path.is_file():
            reasons.append(f"batch.json 不存在：{batch_path}")
        elif not _is_within(batch_path, task_dir):
            reasons.append("batch.json 不属于当前任务目录")
        else:
            try:
                summary = load_batch_summary(batch_path)
            except BatchValidationError as exc:
                reasons.append(f"batch.json 无效：{exc.message}")
            else:
                if manifest.batch_id and summary.batch_id != (
                    manifest.batch_id
                ):
                    reasons.append(
                        "batch_id 与 manifest 不一致："
                        f"{summary.batch_id!r} != {manifest.batch_id!r}"
                    )
                if manifest.document_count is not None and (
                    summary.document_count != manifest.document_count
                ):
                    reasons.append(
                        "文档数量与 manifest 不一致："
                        f"{summary.document_count} != "
                        f"{manifest.document_count}"
                    )
            if not manifest.batch_json_sha256:
                reasons.append("manifest 缺少 batch_json_sha256")
            else:
                try:
                    actual_hash = calculate_sha256(batch_path)
                except Exception as exc:  # noqa: BLE001
                    reasons.append(f"无法计算 batch.json SHA-256：{exc}")
                else:
                    if actual_hash != manifest.batch_json_sha256:
                        reasons.append("batch.json SHA-256 已变化")
    if not manifest.extraction_mode:
        reasons.append("manifest 缺少 extraction_mode")
    elif manifest.extraction_mode != mode:
        reasons.append(
            "提取模式不一致："
            f"{manifest.extraction_mode!r} != {mode!r}"
        )
    if not inputs_match(manifest.inputs, current_inputs):
        reasons.append("输入文件数量、路径或 SHA-256 已变化")
    return StageValidation(valid=not reasons, reasons=reasons)


def _load_raw_json(path: Path) -> dict[str, Any]:
    """读取审核报告原始 JSON。"""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditValidationError(
            f"审核报告无法解析：{path}；{exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AuditValidationError(f"审核报告顶层必须是对象：{path}")
    return payload


def validate_audit(
    manifest: RunManifest,
    task_dir: Path,
) -> StageValidation:
    """检查项目二审核结果是否可安全复用。"""

    reasons: list[str] = []
    if manifest.audit_status not in {
        AUDIT_STATUS_SUCCESS,
        AUDIT_STATUS_PARTIAL,
    }:
        reasons.append(f"审核状态不可复用：{manifest.audit_status}")
    if not manifest.batch_id:
        reasons.append("manifest 缺少 batch_id")

    report_path_text = manifest.audit_report_json
    if not report_path_text:
        reasons.append("manifest 缺少 audit_report_json")
    else:
        report_path = Path(report_path_text)
        if not report_path.is_file():
            reasons.append(f"审核报告不存在：{report_path}")
        elif not _is_within(report_path, task_dir):
            reasons.append("审核报告不属于当前任务目录")
        elif not manifest.audit_report_sha256:
            reasons.append("manifest 缺少 audit_report_sha256")
        else:
            try:
                actual_hash = calculate_sha256(report_path)
            except Exception as exc:  # noqa: BLE001
                reasons.append(f"无法计算审核报告 SHA-256：{exc}")
            else:
                if actual_hash != manifest.audit_report_sha256:
                    reasons.append("审核报告 SHA-256 已变化")
            try:
                raw_report = _load_raw_json(report_path)
                report_id = raw_report.get("report_id")
                if not isinstance(report_id, str) or not report_id.strip():
                    reasons.append("审核报告 report_id 缺失")
                summary = load_audit_report(
                    report_path,
                    manifest.batch_id or "",
                )
            except AuditValidationError as exc:
                reasons.append(f"审核报告无效：{exc.message}")
            else:
                if (
                    manifest.audit_status == AUDIT_STATUS_SUCCESS
                    and not summary.complete_success
                ):
                    reasons.append(
                        "audit_status 为 success，但 complete_success 为 false"
                    )
                if (
                    summary.audit_markdown_path is None
                    or not summary.audit_markdown_path.is_file()
                ):
                    reasons.append("审核 Markdown 报告不存在")
                if (
                    summary.annotation_report_path is None
                    or not summary.annotation_report_path.is_file()
                ):
                    reasons.append("批注阶段报告不存在")
                if (
                    summary.math_validation_path is None
                    or not summary.math_validation_path.is_file()
                ):
                    reasons.append("数学校验报告不存在")
                missing_annotated = [
                    str(path)
                    for path in summary.output_files
                    if not path.is_file()
                ]
                if missing_annotated:
                    reasons.append(
                        "批注文件缺失：" + "；".join(missing_annotated)
                    )
                if manifest.batch_json_path and (
                    manifest.batch_json_sha256
                ):
                    batch_path = Path(manifest.batch_json_path)
                    if not batch_path.is_file():
                        reasons.append("审核依赖的 batch.json 不存在")
                    elif (
                        calculate_sha256(batch_path)
                        != manifest.batch_json_sha256
                    ):
                        reasons.append(
                            "审核依赖的 batch.json SHA-256 已变化"
                        )
    return StageValidation(valid=not reasons, reasons=reasons)


def validate_delivery(
    manifest: RunManifest,
    task_dir: Path,
) -> StageValidation:
    """检查最终交付目录是否可安全复用。"""

    reasons: list[str] = []
    if manifest.delivery_status != DELIVERY_STATUS_SUCCESS:
        reasons.append(f"交付状态不可复用：{manifest.delivery_status}")
    manifest_path_text = manifest.delivery_manifest_json
    if not manifest_path_text:
        reasons.append("manifest 缺少 delivery_manifest_json")
        return StageValidation(valid=False, reasons=reasons)
    delivery_manifest_path = Path(manifest_path_text)
    if not delivery_manifest_path.is_file():
        reasons.append(f"交付清单不存在：{delivery_manifest_path}")
        return StageValidation(valid=False, reasons=reasons)
    if not _is_within(delivery_manifest_path, task_dir):
        reasons.append("交付清单不属于当前任务目录")
    try:
        payload = json.loads(
            delivery_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        reasons.append(f"交付清单无法解析：{exc}")
        return StageValidation(valid=False, reasons=reasons)
    if not isinstance(payload, dict):
        reasons.append("交付清单顶层必须是对象")
        return StageValidation(valid=False, reasons=reasons)
    if payload.get("job_id") != manifest.job_id:
        reasons.append("交付清单 job_id 不匹配")
    if payload.get("overall_status") != manifest.overall_status:
        reasons.append("交付清单 overall_status 与 manifest 不一致")
    if payload.get("delivery_status") != manifest.delivery_status:
        reasons.append("交付清单 delivery_status 与 manifest 不一致")
    if payload.get("missing_artifacts"):
        reasons.append("交付清单记录有缺失交付项")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        reasons.append("交付清单 artifacts 必须是数组")
        artifacts = []
    for item in artifacts:
        if not isinstance(item, dict):
            reasons.append("交付清单存在无效 artifact")
            continue
        path_text = item.get("path")
        if not isinstance(path_text, str):
            reasons.append("交付 artifact 缺少 path")
            continue
        path = Path(path_text)
        if not path.is_absolute():
            path = task_dir / path
        if not _is_within(path, task_dir):
            reasons.append(f"交付 artifact 超出任务目录：{path_text}")
            continue
        if not path.is_file():
            reasons.append(f"交付文件缺失：{path_text}")
            continue
        if item.get("exists") is not True:
            reasons.append(f"交付文件 exists 不为 true：{path_text}")
        if item.get("size") != path.stat().st_size:
            reasons.append(f"交付文件大小不一致：{path_text}")
        if item.get("sha256") != calculate_sha256(path):
            reasons.append(f"交付文件 SHA-256 不一致：{path_text}")

    report_json_text = manifest.delivery_report_json
    audit_json_text = manifest.audit_report_json
    if not report_json_text or not Path(report_json_text).is_file():
        reasons.append("交付审核报告 JSON 不存在")
    elif not audit_json_text or not Path(audit_json_text).is_file():
        reasons.append("原始审核报告 JSON 不存在")
    else:
        try:
            delivery_report = json.loads(
                Path(report_json_text).read_text(encoding="utf-8")
            )
            audit_report = json.loads(
                Path(audit_json_text).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            reasons.append(f"交付报告无法解析：{exc}")
        else:
            if delivery_report.get("batch_id") != manifest.batch_id:
                reasons.append("交付报告 batch_id 不匹配")
            if delivery_report.get("report_id") != audit_report.get(
                "report_id"
            ):
                reasons.append("交付报告 report_id 不匹配")
            if delivery_report.get("overall_status") != (
                manifest.overall_status
            ):
                reasons.append("交付报告 overall_status 不匹配")
    return StageValidation(valid=not reasons, reasons=reasons)


def find_manifest_by_fingerprint(
    output_root: str | Path,
    fingerprint: Fingerprint,
) -> Path | None:
    """在输出根目录下查找指纹匹配的最近任务。"""

    if not fingerprint.safe:
        return None
    root = Path(output_root).expanduser()
    if not root.is_dir():
        return None
    candidates = sorted(
        root.glob("*/manifest.json"),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    for candidate in candidates:
        try:
            manifest = load_manifest(candidate)
        except ManifestError:
            manifest = None
        if manifest is not None and (
            manifest.task_fingerprint == fingerprint.value
        ):
            return candidate
    return None


def find_manifest_by_job_id(
    output_root: str | Path,
    job_id: str,
) -> Path | None:
    """根据 job_id 查找 manifest。"""

    root = Path(output_root).expanduser()
    direct = root / job_id / "manifest.json"
    if direct.is_file():
        return direct
    if not root.is_dir():
        return None
    for candidate in root.glob("*/manifest.json"):
        try:
            manifest = load_manifest(candidate)
        except ManifestError:
            manifest = None
        if manifest is not None and manifest.job_id == job_id:
            return candidate
    return None
