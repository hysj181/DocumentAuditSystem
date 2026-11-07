"""Extraction and audit orchestration for uploaded documents."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from doc_extractor.api import extract_files, save_batch
from word_audit.pipeline import run_audit

from project3_web.task_store import (
    TaskStore,
    relative_path,
    sha256_file,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

DEFAULT_EXTRACTION_MODE = "local_gpu"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_ERRORS = "completed_with_errors"
STATUS_FAILED = "failed"
STATUS_QUEUED = "queued"
STATUS_EXTRACTING = "extracting"
STATUS_AUDITING = "auditing"

PROCESSING_STATUSES = {STATUS_QUEUED, STATUS_EXTRACTING, STATUS_AUDITING}
STATUS_LABELS = {
    STATUS_QUEUED: "排队中",
    STATUS_EXTRACTING: "正在提取",
    STATUS_AUDITING: "正在审核",
    STATUS_COMPLETED: "已完成",
    STATUS_COMPLETED_WITH_ERRORS: "完成但有错误",
    STATUS_FAILED: "失败",
}


def extraction_mode() -> str:
    return os.environ.get(
        "DOCUMENT_AUDIT_EXTRACTION_MODE",
        DEFAULT_EXTRACTION_MODE,
    )


def _set_status(
    task: dict[str, Any],
    store: TaskStore,
    status: str,
    message: str,
) -> None:
    task["status"] = status
    task["status_message"] = message
    store.save(task)


def _document_summaries(batch: Any) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for document in batch.documents:
        summaries.append(
            {
                "document_id": document.document_id,
                "source_name": Path(document.source_file).name,
                "source_file": document.source_file,
                "file_type": document.file_type,
                "record_count": document.record_count,
                "table_count": document.table_count,
                "warnings": list(document.warnings),
                "error": document.error,
                "succeeded": document.error is None,
            }
        )
    return summaries


def _issue_summary(issue: Any) -> dict[str, Any]:
    location = None
    if issue.location is not None:
        location = issue.location.to_dict()
    return {
        "issue_id": issue.issue_id,
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "description": issue.description,
        "original_text": issue.original_text,
        "needs_manual_review": issue.needs_manual_review,
        "review_reasons": list(issue.review_reasons),
        "suggestion": issue.suggestion,
        "status": issue.status,
        "location": location,
    }


def _annotation_summary(annotation: Any) -> dict[str, Any]:
    metadata = dict(annotation.metadata or {})
    return {
        "annotation_id": annotation.annotation_id,
        "issue_id": annotation.issue_id,
        "document_id": annotation.document_id,
        "status": annotation.status,
        "comment_text": annotation.comment_text,
        "error": annotation.error,
        "word_anchor": (
            dict(annotation.word_anchor) if annotation.word_anchor else None
        ),
        "annotation_kind": metadata.get("annotation_kind"),
        "comment_id": metadata.get("comment_id"),
        "anchor_text": metadata.get("anchor_text"),
        "output_file": metadata.get("output_file"),
    }


def _add_artifact(
    artifacts: dict[str, dict[str, Any]],
    artifact_id: str,
    path: Path,
    task_dir: Path,
    *,
    label: str,
    kind: str,
) -> None:
    if not path.is_file():
        return
    try:
        relative = relative_path(path, task_dir)
    except ValueError:
        logger.warning("artifact is outside task directory: %s", path)
        return
    artifacts[artifact_id] = {
        "label": label,
        "kind": kind,
        "path": relative,
        "filename": path.name,
    }


def _collect_audit_artifacts(
    audit_result: Any,
    task_dir: Path,
) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for index, output in enumerate(audit_result.output_files, start=1):
        suffix = output.suffix.casefold()
        if suffix == ".docx":
            _add_artifact(
                artifacts,
                f"word_{index}",
                output,
                task_dir,
                label="标注后 Word 文件",
                kind="word",
            )
        elif suffix == ".pdf":
            _add_artifact(
                artifacts,
                f"pdf_{index}",
                output,
                task_dir,
                label="标注后 PDF 文件",
                kind="pdf",
            )
    _add_artifact(
        artifacts,
        "audit_json",
        audit_result.audit_json_path,
        task_dir,
        label="完整审核 JSON",
        kind="json",
    )
    _add_artifact(
        artifacts,
        "audit_markdown",
        audit_result.audit_markdown_path,
        task_dir,
        label="完整审核 Markdown",
        kind="markdown",
    )
    _add_artifact(
        artifacts,
        "annotation_json",
        audit_result.annotation.json_path,
        task_dir,
        label="批注明细 JSON",
        kind="json",
    )
    _add_artifact(
        artifacts,
        "annotation_markdown",
        audit_result.annotation.markdown_path,
        task_dir,
        label="批注明细 Markdown",
        kind="markdown",
    )
    _add_artifact(
        artifacts,
        "math_validation",
        audit_result.math_validation_path,
        task_dir,
        label="数学校验 JSON",
        kind="json",
    )
    return artifacts


def process_task(
    store: TaskStore,
    task_id: str,
    *,
    mode: str | None = None,
) -> None:
    """Run extraction and audit for one task, persisting every stage."""

    task = store.load(task_id)
    if task is None:
        logger.error("task not found: %s", task_id)
        return
    task_dir = store.task_dir(task_id)
    if task_dir is None:
        logger.error("invalid task id: %s", task_id)
        return

    local_mode = mode or extraction_mode()
    try:
        _set_status(task, store, STATUS_EXTRACTING, "正在调用项目一提取文档内容")
        uploads = [
            item
            for item in task.get("uploads", [])
            if isinstance(item, dict) and item.get("stored_name")
        ]
        input_paths = [task_dir / "uploads" / item["stored_name"] for item in uploads]
        missing = [str(path) for path in input_paths if not path.is_file()]
        if missing:
            raise FileNotFoundError("上传文件缺失：" + ", ".join(missing))

        batch = extract_files(input_paths, mode=local_mode)
        documents = _document_summaries(batch)
        task["documents"] = documents

        extraction_dir = task_dir / "extraction"
        outputs = save_batch(batch, extraction_dir, formats=("json",))
        batch_json = Path(outputs["batch"])
        extraction_records = sum(
            int(document.get("record_count", 0)) for document in documents
        )
        task["extraction"] = {
            "batch_id": batch.batch_id,
            "batch_json": relative_path(batch_json, task_dir),
            "document_count": len(documents),
            "record_count": extraction_records,
            "environmental_record_count": len(batch.environmental.records),
            "documents": documents,
            "warnings": list(batch.environmental.warnings),
        }
        task["warnings"] = list(dict.fromkeys(
            [
                *task.get("warnings", []),
                *batch.environmental.warnings,
                *[
                    f"{document['source_name']}：{document['error']}"
                    for document in documents
                    if document.get("error")
                ],
                *[
                    f"{document['source_name']}：{warning}"
                    for document in documents
                    for warning in document.get("warnings", [])
                ],
            ]
        ))

        artifacts: dict[str, dict[str, Any]] = {}
        _add_artifact(
            artifacts,
            "batch_json",
            batch_json,
            task_dir,
            label="项目一提取批次 JSON",
            kind="json",
        )
        task["artifacts"] = artifacts

        succeeded = [document for document in documents if document.get("succeeded")]
        if not succeeded:
            task["error"] = "所有文档提取失败"
            task["status"] = STATUS_FAILED
            task["status_message"] = "文档提取失败"
            task["completed_at"] = utc_now_iso()
            store.save(task)
            return

        _set_status(task, store, STATUS_AUDITING, "正在调用项目二执行审核与批注")
        audit_result = run_audit(
            batch_json,
            output_dir=task_dir / "audit",
        )
        pipeline = audit_result.report.metadata.get("pipeline", {})
        annotation_task = audit_result.report.metadata.get("annotation_task", {})
        artifacts.update(_collect_audit_artifacts(audit_result, task_dir))
        task["artifacts"] = artifacts
        task["audit"] = {
            "complete_success": bool(pipeline.get("complete_success", False)),
            "synthetic_data": bool(pipeline.get("synthetic_data", False)),
            "counts": dict(pipeline.get("counts", {})),
            "typo_counts": dict(pipeline.get("typo_counts", {})),
            "warnings": list(audit_result.report.warnings),
            "errors": list(pipeline.get("errors", [])),
            "documents": list(audit_result.report.documents),
            "issues": [
                _issue_summary(issue) for issue in audit_result.report.issues
            ],
            "annotations": [
                _annotation_summary(annotation)
                for annotation in audit_result.report.annotations
            ],
            "annotation_counts": dict(annotation_task.get("counts", {})),
        }

        has_document_errors = any(
            not document.get("succeeded") for document in documents
        )
        task["status"] = (
            STATUS_COMPLETED_WITH_ERRORS if has_document_errors else STATUS_COMPLETED
        )
        task["status_message"] = (
            "审核完成，但部分文档提取失败"
            if has_document_errors
            else "审核完成"
        )
        task["error"] = None
        task["completed_at"] = utc_now_iso()

        for upload in uploads:
            path = task_dir / "uploads" / upload["stored_name"]
            if not path.is_file() or sha256_file(path) != upload.get("sha256"):
                raise RuntimeError("上传文件 SHA256 发生变化，拒绝标记任务成功")

        store.save(task)
    except Exception as exc:
        logger.exception("task failed: %s", task_id)
        task["status"] = STATUS_FAILED
        task["status_message"] = "任务处理失败"
        task["error"] = f"{type(exc).__name__}: {exc}"
        task["completed_at"] = utc_now_iso()
        store.save(task)
