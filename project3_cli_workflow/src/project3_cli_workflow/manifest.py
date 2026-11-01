"""SHA-256 计算和 manifest.json 生成。

本模块只读取输入文件，不修改其内容。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from project3_cli_workflow.errors import InputError, ManifestError
from project3_cli_workflow.models import (
    FilteredInput,
    InputFile,
    RunManifest,
)

SHA256_CHUNK_SIZE = 1024 * 1024


def utc_now_iso() -> str:
    """返回 UTC ISO 8601 时间。"""

    return datetime.now(UTC).isoformat()


def new_job_id() -> str:
    """生成任务唯一 ID。"""

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}_{uuid.uuid4().hex[:8]}"


def calculate_sha256(
    path: str | Path,
    *,
    chunk_size: int = SHA256_CHUNK_SIZE,
) -> str:
    """分块计算文件 SHA-256，避免一次性读入大文件。"""

    digest = hashlib.sha256()
    source = Path(path).expanduser()
    try:
        with source.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise InputError(f"无法读取输入文件：{source}；{exc}") from exc
    return digest.hexdigest()


def _build_input_file(path: Path) -> InputFile:
    """读取文件元数据并计算 SHA-256。"""

    resolved = path.resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise InputError(f"无法读取文件信息：{resolved}；{exc}") from exc

    return InputFile(
        input_id=uuid.uuid4().hex,
        source_path=str(resolved),
        file_name=resolved.name,
        file_type=resolved.suffix.casefold().lstrip("."),
        file_size=stat.st_size,
        modified_at=datetime.fromtimestamp(
            stat.st_mtime,
            tz=UTC,
        ).isoformat(),
        sha256=calculate_sha256(resolved),
    )


def build_manifest(
    files: Iterable[str | Path],
    filtered_inputs: Iterable[FilteredInput] = (),
    *,
    job_id: str | None = None,
    created_at: str | None = None,
) -> RunManifest:
    """为有效输入构建运行清单。"""

    manifest = RunManifest(
        job_id=job_id or new_job_id(),
        created_at=created_at or utc_now_iso(),
        inputs=[_build_input_file(Path(path)) for path in files],
        filtered_inputs=list(filtered_inputs),
    )
    return manifest


def load_manifest(manifest_path: str | Path) -> RunManifest:
    """读取现有 manifest.json，供交付阶段复用。"""

    path = Path(manifest_path).expanduser()
    if not path.is_file():
        raise ManifestError(f"manifest.json 不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(
            f"manifest.json 无法解析：{path}；{exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ManifestError(f"manifest.json 顶层必须是对象：{path}")
    return RunManifest.from_dict(payload)


def write_manifest(manifest: RunManifest, manifest_path: str | Path) -> Path:
    """原子写入 manifest.json，避免中途写入导致 JSON 损坏。"""

    path = Path(manifest_path).expanduser()
    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise ManifestError(
            f"无法写入 manifest.json：{path}；{exc}"
        ) from exc
    return path


def save_manifest(
    manifest: RunManifest,
    output_root: str | Path,
) -> Path:
    """在输出根目录下创建任务目录并写入 UTF-8 manifest.json。"""

    root = Path(output_root).expanduser()
    try:
        root = root.resolve()
    except OSError as exc:
        raise InputError(f"输出根目录无效：{output_root}；{exc}") from exc

    if root.exists() and not root.is_dir():
        raise InputError(f"输出根目录不是目录：{root}")

    task_dir = root / manifest.job_id
    try:
        task_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ManifestError(f"任务目录已存在：{task_dir}") from exc
    except OSError as exc:
        raise ManifestError(f"无法创建任务目录：{task_dir}；{exc}") from exc

    return write_manifest(manifest, task_dir / "manifest.json")
