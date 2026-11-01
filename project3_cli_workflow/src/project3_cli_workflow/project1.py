"""项目一 extract 子进程适配与 batch.json 校验。

本模块只通过命令行调用项目一，不导入项目一内部模块。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from project3_cli_workflow.config import ProjectConfig
from project3_cli_workflow.errors import (
    BatchValidationError,
    InputError,
    ManifestError,
    Project1StageError,
)
from project3_cli_workflow.manifest import utc_now_iso
from project3_cli_workflow.models import (
    EXTRACTION_STATUS_FAILED,
    EXTRACTION_STATUS_PARTIAL,
    EXTRACTION_STATUS_SUCCESS,
)
from project3_cli_workflow.process import redact_text, run_process

BATCH_SCHEMA_VERSION = "1.0"
PARSE_MODES = ("local_gpu", "cloud_api")
SUPPORTED_DOCUMENT_TYPES = {"word", "pdf"}
STDERR_TAIL_LIMIT = 2000


@dataclass(frozen=True)
class BatchDocumentSummary:
    """batch.json 中单个文档的摘要。"""

    document_id: str
    source_file: str
    file_type: str
    succeeded: bool
    error: str | None
    record_count: int
    warning_count: int


@dataclass(frozen=True)
class BatchSummary:
    """项目一批次的校验结果摘要。"""

    batch_id: str
    schema_version: str
    document_count: int
    successful_document_count: int
    failed_document_count: int
    warning_count: int
    documents: list[BatchDocumentSummary] = field(default_factory=list)


@dataclass(frozen=True)
class Project1ExtractionResult:
    """项目一提取阶段的结果。"""

    status: str
    mode: str
    command: list[str]
    started_at: str
    finished_at: str
    duration_seconds: float
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_log_path: Path
    stderr_log_path: Path
    batch_path: Path | None = None
    batch: BatchSummary | None = None
    error: str | None = None


def _require_non_empty_string(
    value: Any,
    field_name: str,
    *,
    prefix: str = "",
) -> str:
    """校验非空字符串字段。"""

    if not isinstance(value, str) or not value.strip():
        raise BatchValidationError(f"{prefix}{field_name} 必须是非空字符串。")
    return value


def _require_list(value: Any, field_name: str, *, prefix: str = "") -> list[Any]:
    """校验列表字段。"""

    if not isinstance(value, list):
        raise BatchValidationError(f"{prefix}{field_name} 必须是数组。")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    """读取并解析 batch.json。"""

    if not path.is_file():
        raise BatchValidationError(f"batch.json 不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchValidationError(
            f"batch.json 无法解析：{path}；{exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise BatchValidationError(f"batch.json 顶层必须是对象：{path}")
    return payload


def load_batch_summary(path: str | Path) -> BatchSummary:
    """读取并校验项目一 batch.json，返回真实文档统计。"""

    batch_path = Path(path).expanduser()
    payload = _load_json(batch_path)

    schema_version = payload.get("schema_version")
    if schema_version != BATCH_SCHEMA_VERSION:
        raise BatchValidationError(
            "不支持的 batch schema_version："
            f"{schema_version!r}，当前仅支持 {BATCH_SCHEMA_VERSION!r}。"
        )

    batch_id = _require_non_empty_string(payload.get("batch_id"), "batch_id")
    documents_data = _require_list(payload.get("documents"), "documents")
    if not documents_data:
        raise BatchValidationError("batch.json 的 documents 为空。")

    document_count = payload.get("document_count")
    if isinstance(document_count, bool) or not isinstance(document_count, int):
        raise BatchValidationError("document_count 必须是整数。")
    if document_count != len(documents_data):
        raise BatchValidationError(
            "document_count 与 documents 数量不一致："
            f"{document_count} != {len(documents_data)}。"
        )

    environmental = payload.get("environmental")
    if not isinstance(environmental, dict):
        raise BatchValidationError("environmental 必须是对象。")
    environmental_warnings = _require_list(
        environmental.get("warnings", []),
        "environmental.warnings",
    )

    documents: list[BatchDocumentSummary] = []
    seen_document_ids: set[str] = set()
    warning_count = len(environmental_warnings)

    for index, item in enumerate(documents_data):
        prefix = f"documents[{index}]."
        if not isinstance(item, dict):
            raise BatchValidationError(f"{prefix}必须是对象。")
        document_id = _require_non_empty_string(
            item.get("document_id"),
            "document_id",
            prefix=prefix,
        )
        if document_id in seen_document_ids:
            raise BatchValidationError(f"{prefix}document_id 重复：{document_id}")
        seen_document_ids.add(document_id)

        source_file = _require_non_empty_string(
            item.get("source_file"),
            "source_file",
            prefix=prefix,
        )
        file_type = _require_non_empty_string(
            item.get("file_type"),
            "file_type",
            prefix=prefix,
        )
        if file_type not in SUPPORTED_DOCUMENT_TYPES:
            raise BatchValidationError(
                f"{prefix}file_type 无效：{file_type!r}。"
            )

        records = _require_list(
            item.get("records"),
            "records",
            prefix=prefix,
        )
        warnings = _require_list(
            item.get("warnings", []),
            "warnings",
            prefix=prefix,
        )
        error = item.get("error")
        if error is not None and not isinstance(error, str):
            raise BatchValidationError(f"{prefix}error 必须是字符串或 null。")

        warning_count += len(warnings)
        documents.append(
            BatchDocumentSummary(
                document_id=document_id,
                source_file=source_file,
                file_type=file_type,
                succeeded=error is None,
                error=error,
                record_count=len(records),
                warning_count=len(warnings),
            )
        )

    successful_count = sum(1 for item in documents if item.succeeded)
    failed_count = len(documents) - successful_count
    return BatchSummary(
        batch_id=batch_id,
        schema_version=schema_version,
        document_count=len(documents),
        successful_document_count=successful_count,
        failed_document_count=failed_count,
        warning_count=warning_count,
        documents=documents,
    )


def find_batch_json(extraction_root: str | Path) -> Path | None:
    """在项目一输出目录中查找 batch.json。"""

    batch_dir = Path(extraction_root).expanduser() / "batches"
    if not batch_dir.is_dir():
        return None
    candidates = list(batch_dir.glob("*/batch.json"))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (item.stat().st_mtime_ns, str(item)),
        reverse=True,
    )
    return candidates[0]


def build_extract_command(
    config: ProjectConfig,
    files: Iterable[str | Path],
    output_root: str | Path,
    mode: str,
) -> list[str]:
    """根据项目一真实 CLI 构造 extract 命令。"""

    if mode not in PARSE_MODES:
        raise InputError(f"不支持的项目一解析模式：{mode}")
    file_paths = [Path(path).expanduser().resolve() for path in files]
    if not file_paths:
        raise InputError("项目一提取至少需要一个输入文件。")

    command = [
        str(config.project1_python),
        str(config.project1_root / "main.py"),
        "extract",
    ]
    for path in file_paths:
        command.extend(["--input", str(path)])
    command.extend(
        [
            "--mode",
            mode,
            "--output-root",
            str(Path(output_root).expanduser().resolve()),
            "--save-format",
            "json",
            "--quiet",
        ]
    )
    return command


def _write_log(path: Path, content: str) -> Path:
    """写入 UTF-8 日志文件。"""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"无法写入提取日志：{path}；{exc}") from exc
    return path


def _stderr_tail(stderr: str) -> str:
    """截取 stderr 末尾内容，避免无限膨胀。"""

    text = stderr.strip()
    if len(text) <= STDERR_TAIL_LIMIT:
        return text
    return text[-STDERR_TAIL_LIMIT:]


def _failed_document_text(batch: BatchSummary) -> str:
    """汇总失败文档及错误原因。"""

    details = [
        f"{item.source_file}: {item.error}"
        for item in batch.documents
        if not item.succeeded
    ]
    return "；".join(details)


def _extraction_environment() -> dict[str, str]:
    """构造项目一子进程环境，不记录敏感环境变量。"""

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_project1_extraction(
    config: ProjectConfig,
    files: Sequence[str | Path],
    task_dir: str | Path,
    *,
    mode: str,
    timeout: float,
) -> Project1ExtractionResult:
    """调用项目一 extract，并读取、校验收到的 batch.json。"""

    if timeout <= 0:
        raise InputError("项目一提取超时时间必须大于 0 秒。")

    task_path = Path(task_dir).expanduser().resolve()
    extraction_root = task_path / "01_extraction"
    log_dir = task_path / "04_logs"
    main_script = config.project1_root / "main.py"
    if not main_script.is_file():
        raise Project1StageError(f"项目一入口不存在：{main_script}")

    command = build_extract_command(config, files, extraction_root, mode)
    started_at = utc_now_iso()
    process = run_process(
        command,
        cwd=config.project1_root,
        timeout=timeout,
        env=_extraction_environment(),
    )
    finished_at = utc_now_iso()

    token = os.environ.get("PADDLEOCR_ACCESS_TOKEN", "")
    secrets = (token,) if token else ()
    stdout = redact_text(process.stdout, secrets)
    stderr = redact_text(process.stderr, secrets)
    stdout_log = _write_log(log_dir / "project1_extract.stdout.log", stdout)
    stderr_log = _write_log(log_dir / "project1_extract.stderr.log", stderr)

    status = EXTRACTION_STATUS_FAILED
    error: str | None = None
    batch_path: Path | None = None
    batch: BatchSummary | None = None

    if process.start_failed:
        error = redact_text(process.error or "项目一进程启动失败。", secrets)
    elif process.timed_out:
        error = redact_text(process.error or "项目一提取超时。", secrets)
    else:
        batch_path = find_batch_json(extraction_root)
        if batch_path is None:
            tail = _stderr_tail(stderr)
            error = (
                f"项目一未生成 batch.json，退出码：{process.exit_code}。"
            )
            if tail:
                error = f"{error} stderr：{tail}"
        else:
            try:
                batch = load_batch_summary(batch_path)
            except BatchValidationError as exc:
                error = redact_text(exc.message, secrets)
            else:
                if batch.successful_document_count == 0:
                    status = EXTRACTION_STATUS_FAILED
                    error = "项目一未成功提取任何文档。"
                    failed_text = _failed_document_text(batch)
                    if failed_text:
                        error = f"{error} {failed_text}"
                elif (
                    batch.failed_document_count > 0
                    or process.exit_code != 0
                ):
                    status = EXTRACTION_STATUS_PARTIAL
                    parts: list[str] = []
                    if batch.failed_document_count > 0:
                        parts.append(
                            f"存在 {batch.failed_document_count} 个失败文档："
                            f"{_failed_document_text(batch)}"
                        )
                    if process.exit_code != 0:
                        parts.append(f"项目一退出码：{process.exit_code}")
                    error = "；".join(parts)
                else:
                    status = EXTRACTION_STATUS_SUCCESS
                error = redact_text(error, secrets) if error else None

    return Project1ExtractionResult(
        status=status,
        mode=mode,
        command=command,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=process.duration_seconds,
        exit_code=process.exit_code,
        stdout=stdout,
        stderr=stderr,
        stdout_log_path=stdout_log,
        stderr_log_path=stderr_log,
        batch_path=batch_path,
        batch=batch,
        error=error,
    )
