"""输入文件、过滤记录和运行清单的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MANIFEST_SCHEMA_VERSION = "1.0"
MANIFEST_STATUS_INITIALIZED = "initialized"
INPUT_STATUS_PENDING = "pending"
FILTERED_STATUS = "filtered"
FILTER_REASON_UNSUPPORTED = "unsupported_extension"
FILTER_REASON_DUPLICATE = "duplicate_input"

EXTRACTION_STATUS_PENDING = "pending"
EXTRACTION_STATUS_RUNNING = "extraction_running"
EXTRACTION_STATUS_SUCCESS = "extraction_success"
EXTRACTION_STATUS_PARTIAL = "extraction_partial"
EXTRACTION_STATUS_FAILED = "extraction_failed"

AUDIT_STATUS_PENDING = "pending"
AUDIT_STATUS_RUNNING = "audit_running"
AUDIT_STATUS_SUCCESS = "audit_success"
AUDIT_STATUS_PARTIAL = "audit_partial"
AUDIT_STATUS_FAILED = "audit_failed"
AUDIT_STATUS_SKIPPED = "audit_skipped"

OVERALL_STATUS_PENDING = "pending"
OVERALL_STATUS_RUNNING = "running"
OVERALL_STATUS_SUCCESS = "success"
OVERALL_STATUS_PARTIAL = "partial"
OVERALL_STATUS_FAILED = "failed"

DELIVERY_STATUS_PENDING = "pending"
DELIVERY_STATUS_RUNNING = "delivery_running"
DELIVERY_STATUS_SUCCESS = "delivery_success"
DELIVERY_STATUS_PARTIAL = "delivery_partial"
DELIVERY_STATUS_FAILED = "delivery_failed"


def _optional_int(value: Any) -> int | None:
    """把 JSON 值转换为可选整数。"""

    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    """把 JSON 值转换为可选浮点数。"""

    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    """把 JSON 值转换为可选布尔值。"""

    return value if isinstance(value, bool) else None


def _string_list(value: Any) -> list[str]:
    """把 JSON 数组转换为字符串列表。"""

    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _int_dict(value: Any) -> dict[str, int] | None:
    """把 JSON 对象转换为整数计数字典。"""

    if not isinstance(value, dict):
        return None
    result: dict[str, int] = {}
    for key, item in value.items():
        number = _optional_int(item)
        if number is not None:
            result[str(key)] = number
    return result


def _dict_list(value: Any) -> list[dict[str, Any]]:
    """把 JSON 数组转换为字典列表。"""

    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


@dataclass(frozen=True)
class InputFile:
    """一个通过过滤、等待后续处理的输入文件。"""

    input_id: str
    source_path: str
    file_name: str
    file_type: str
    file_size: int
    modified_at: str
    sha256: str
    status: str = INPUT_STATUS_PENDING
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 manifest 的字典。"""

        return {
            "input_id": self.input_id,
            "source_path": self.source_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "modified_at": self.modified_at,
            "sha256": self.sha256,
            "status": self.status,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InputFile:
        """从 manifest 字典恢复输入文件记录。"""

        return cls(
            input_id=str(data.get("input_id", "")),
            source_path=str(data.get("source_path", "")),
            file_name=str(data.get("file_name", "")),
            file_type=str(data.get("file_type", "")),
            file_size=int(data.get("file_size", 0) or 0),
            modified_at=str(data.get("modified_at", "")),
            sha256=str(data.get("sha256", "")),
            status=str(data.get("status", INPUT_STATUS_PENDING)),
            error=data.get("error"),
        )


@dataclass(frozen=True)
class FilteredInput:
    """被过滤的输入文件及其原因。"""

    source_path: str
    file_name: str
    file_type: str
    reason: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 manifest 的过滤记录。"""

        return {
            "source_path": self.source_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "status": FILTERED_STATUS,
            "reason": self.reason,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilteredInput:
        """从 manifest 字典恢复过滤记录。"""

        return cls(
            source_path=str(data.get("source_path", "")),
            file_name=str(data.get("file_name", "")),
            file_type=str(data.get("file_type", "")),
            reason=str(data.get("reason", "")),
            message=str(data.get("message", "")),
        )


@dataclass
class RunManifest:
    """一次任务的运行清单。"""

    job_id: str
    created_at: str
    inputs: list[InputFile] = field(default_factory=list)
    filtered_inputs: list[FilteredInput] = field(default_factory=list)
    schema_version: str = MANIFEST_SCHEMA_VERSION
    status: str = MANIFEST_STATUS_INITIALIZED

    extraction_status: str = EXTRACTION_STATUS_PENDING
    extraction_started_at: str | None = None
    extraction_finished_at: str | None = None
    extraction_mode: str | None = None
    extraction_timeout_seconds: float | None = None
    extraction_exit_code: int | None = None
    extraction_command: list[str] | None = None
    extraction_stdout_log: str | None = None
    extraction_stderr_log: str | None = None
    batch_id: str | None = None
    batch_json_path: str | None = None
    document_count: int | None = None
    successful_document_count: int | None = None
    failed_document_count: int | None = None
    warning_count: int | None = None
    extraction_error: str | None = None

    overall_status: str = OVERALL_STATUS_PENDING
    audit_status: str = AUDIT_STATUS_PENDING
    audit_started_at: str | None = None
    audit_finished_at: str | None = None
    audit_timeout_seconds: float | None = None
    audit_exit_code: int | None = None
    audit_command: list[str] | None = None
    audit_stdout_log: str | None = None
    audit_stderr_log: str | None = None
    audit_report_json: str | None = None
    audit_report_markdown: str | None = None
    annotation_report: str | None = None
    math_validation_report: str | None = None
    annotated_files: list[str] = field(default_factory=list)
    audit_complete_success: bool | None = None
    audit_issue_count: int | None = None
    audit_unverified_count: int | None = None
    audit_manual_review_count: int | None = None
    audit_issues_flagged_for_manual_review_count: int | None = None
    audit_warning_count: int | None = None
    audit_typo_counts: dict[str, int] | None = None
    audit_error: str | None = None

    delivery_status: str = DELIVERY_STATUS_PENDING
    delivery_started_at: str | None = None
    delivery_finished_at: str | None = None
    delivery_directory: str | None = None
    delivery_report_json: str | None = None
    delivery_report_markdown: str | None = None
    delivery_summary_markdown: str | None = None
    delivery_manifest_json: str | None = None
    delivery_artifact_count: int | None = None
    delivery_missing_artifact_count: int | None = None
    delivery_error: str | None = None

    task_fingerprint: str | None = None
    fingerprint_components: dict[str, Any] | None = None
    workflow_version: str | None = None
    project1_version: str | None = None
    project2_version: str | None = None
    project1_root: str | None = None
    project2_root: str | None = None
    batch_json_sha256: str | None = None
    audit_report_sha256: str | None = None
    extraction_reused: bool = False
    audit_reused: bool = False
    delivery_reused: bool = False
    stage_history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def input_count(self) -> int:
        """有效输入文件数量。"""

        return len(self.inputs)

    def to_dict(self) -> dict[str, Any]:
        """转换为 manifest JSON 结构。"""

        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "created_at": self.created_at,
            "status": self.status,
            "input_count": self.input_count,
            "inputs": [item.to_dict() for item in self.inputs],
            "filtered_inputs": [
                item.to_dict() for item in self.filtered_inputs
            ],
            "extraction_status": self.extraction_status,
            "extraction_started_at": self.extraction_started_at,
            "extraction_finished_at": self.extraction_finished_at,
            "extraction_mode": self.extraction_mode,
            "extraction_timeout_seconds": self.extraction_timeout_seconds,
            "extraction_exit_code": self.extraction_exit_code,
            "extraction_command": (
                list(self.extraction_command)
                if self.extraction_command is not None
                else None
            ),
            "extraction_stdout_log": self.extraction_stdout_log,
            "extraction_stderr_log": self.extraction_stderr_log,
            "batch_id": self.batch_id,
            "batch_json_path": self.batch_json_path,
            "document_count": self.document_count,
            "successful_document_count": self.successful_document_count,
            "failed_document_count": self.failed_document_count,
            "warning_count": self.warning_count,
            "extraction_error": self.extraction_error,
            "overall_status": self.overall_status,
            "audit_status": self.audit_status,
            "audit_started_at": self.audit_started_at,
            "audit_finished_at": self.audit_finished_at,
            "audit_timeout_seconds": self.audit_timeout_seconds,
            "audit_exit_code": self.audit_exit_code,
            "audit_command": (
                list(self.audit_command)
                if self.audit_command is not None
                else None
            ),
            "audit_stdout_log": self.audit_stdout_log,
            "audit_stderr_log": self.audit_stderr_log,
            "audit_report_json": self.audit_report_json,
            "audit_report_markdown": self.audit_report_markdown,
            "annotation_report": self.annotation_report,
            "math_validation_report": self.math_validation_report,
            "annotated_files": list(self.annotated_files),
            "audit_complete_success": self.audit_complete_success,
            "audit_issue_count": self.audit_issue_count,
            "audit_unverified_count": self.audit_unverified_count,
            "audit_manual_review_count": self.audit_manual_review_count,
            "audit_issues_flagged_for_manual_review_count": (
                self.audit_issues_flagged_for_manual_review_count
            ),
            "audit_warning_count": self.audit_warning_count,
            "audit_typo_counts": (
                dict(self.audit_typo_counts)
                if self.audit_typo_counts is not None
                else None
            ),
            "audit_error": self.audit_error,
            "delivery_status": self.delivery_status,
            "delivery_started_at": self.delivery_started_at,
            "delivery_finished_at": self.delivery_finished_at,
            "delivery_directory": self.delivery_directory,
            "delivery_report_json": self.delivery_report_json,
            "delivery_report_markdown": self.delivery_report_markdown,
            "delivery_summary_markdown": self.delivery_summary_markdown,
            "delivery_manifest_json": self.delivery_manifest_json,
            "delivery_artifact_count": self.delivery_artifact_count,
            "delivery_missing_artifact_count": (
                self.delivery_missing_artifact_count
            ),
            "delivery_error": self.delivery_error,
            "task_fingerprint": self.task_fingerprint,
            "fingerprint_components": (
                dict(self.fingerprint_components)
                if self.fingerprint_components is not None
                else None
            ),
            "workflow_version": self.workflow_version,
            "project1_version": self.project1_version,
            "project2_version": self.project2_version,
            "project1_root": self.project1_root,
            "project2_root": self.project2_root,
            "batch_json_sha256": self.batch_json_sha256,
            "audit_report_sha256": self.audit_report_sha256,
            "extraction_reused": self.extraction_reused,
            "audit_reused": self.audit_reused,
            "delivery_reused": self.delivery_reused,
            "stage_history": [dict(item) for item in self.stage_history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunManifest:
        """从 manifest.json 恢复运行清单。"""

        inputs_data = data.get("inputs")
        filtered_data = data.get("filtered_inputs")
        return cls(
            job_id=str(data.get("job_id", "")),
            created_at=str(data.get("created_at", "")),
            inputs=[
                InputFile.from_dict(item)
                for item in inputs_data or []
                if isinstance(item, dict)
            ],
            filtered_inputs=[
                FilteredInput.from_dict(item)
                for item in filtered_data or []
                if isinstance(item, dict)
            ],
            schema_version=str(
                data.get("schema_version", MANIFEST_SCHEMA_VERSION)
            ),
            status=str(data.get("status", MANIFEST_STATUS_INITIALIZED)),
            extraction_status=str(
                data.get("extraction_status", EXTRACTION_STATUS_PENDING)
            ),
            extraction_started_at=data.get("extraction_started_at"),
            extraction_finished_at=data.get("extraction_finished_at"),
            extraction_mode=data.get("extraction_mode"),
            extraction_timeout_seconds=_optional_float(
                data.get("extraction_timeout_seconds")
            ),
            extraction_exit_code=_optional_int(
                data.get("extraction_exit_code")
            ),
            extraction_command=_string_list(
                data.get("extraction_command")
            )
            or None,
            extraction_stdout_log=data.get("extraction_stdout_log"),
            extraction_stderr_log=data.get("extraction_stderr_log"),
            batch_id=data.get("batch_id"),
            batch_json_path=data.get("batch_json_path"),
            document_count=_optional_int(data.get("document_count")),
            successful_document_count=_optional_int(
                data.get("successful_document_count")
            ),
            failed_document_count=_optional_int(
                data.get("failed_document_count")
            ),
            warning_count=_optional_int(data.get("warning_count")),
            extraction_error=data.get("extraction_error"),
            overall_status=str(
                data.get("overall_status", OVERALL_STATUS_PENDING)
            ),
            audit_status=str(data.get("audit_status", AUDIT_STATUS_PENDING)),
            audit_started_at=data.get("audit_started_at"),
            audit_finished_at=data.get("audit_finished_at"),
            audit_timeout_seconds=_optional_float(
                data.get("audit_timeout_seconds")
            ),
            audit_exit_code=_optional_int(data.get("audit_exit_code")),
            audit_command=_string_list(data.get("audit_command")) or None,
            audit_stdout_log=data.get("audit_stdout_log"),
            audit_stderr_log=data.get("audit_stderr_log"),
            audit_report_json=data.get("audit_report_json"),
            audit_report_markdown=data.get("audit_report_markdown"),
            annotation_report=data.get("annotation_report"),
            math_validation_report=data.get("math_validation_report"),
            annotated_files=_string_list(data.get("annotated_files")),
            audit_complete_success=_optional_bool(
                data.get("audit_complete_success")
            ),
            audit_issue_count=_optional_int(data.get("audit_issue_count")),
            audit_unverified_count=_optional_int(
                data.get("audit_unverified_count")
            ),
            audit_manual_review_count=_optional_int(
                data.get("audit_manual_review_count")
            ),
            audit_issues_flagged_for_manual_review_count=_optional_int(
                data.get(
                    "audit_issues_flagged_for_manual_review_count"
                )
            ),
            audit_warning_count=_optional_int(
                data.get("audit_warning_count")
            ),
            audit_typo_counts=_int_dict(data.get("audit_typo_counts")),
            audit_error=data.get("audit_error"),
            delivery_status=str(
                data.get("delivery_status", DELIVERY_STATUS_PENDING)
            ),
            delivery_started_at=data.get("delivery_started_at"),
            delivery_finished_at=data.get("delivery_finished_at"),
            delivery_directory=data.get("delivery_directory"),
            delivery_report_json=data.get("delivery_report_json"),
            delivery_report_markdown=data.get("delivery_report_markdown"),
            delivery_summary_markdown=data.get("delivery_summary_markdown"),
            delivery_manifest_json=data.get("delivery_manifest_json"),
            delivery_artifact_count=_optional_int(
                data.get("delivery_artifact_count")
            ),
            delivery_missing_artifact_count=_optional_int(
                data.get("delivery_missing_artifact_count")
            ),
            delivery_error=data.get("delivery_error"),
            task_fingerprint=data.get("task_fingerprint"),
            fingerprint_components=(
                dict(data.get("fingerprint_components"))
                if isinstance(data.get("fingerprint_components"), dict)
                else None
            ),
            workflow_version=data.get("workflow_version"),
            project1_version=data.get("project1_version"),
            project2_version=data.get("project2_version"),
            project1_root=data.get("project1_root"),
            project2_root=data.get("project2_root"),
            batch_json_sha256=data.get("batch_json_sha256"),
            audit_report_sha256=data.get("audit_report_sha256"),
            extraction_reused=bool(data.get("extraction_reused", False)),
            audit_reused=bool(data.get("audit_reused", False)),
            delivery_reused=bool(data.get("delivery_reused", False)),
            stage_history=_dict_list(data.get("stage_history")),
        )
