"""Local JSON-backed task persistence and safe artifact lookup."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_task_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_filename(filename: str, fallback: str = "upload") -> str:
    name = Path(filename or "").name
    name = _UNSAFE_FILENAME_RE.sub("_", name).strip(" .")
    if not name:
        name = fallback
    suffix = Path(name).suffix
    stem = Path(name).stem[:100] or fallback
    return f"{stem}{suffix}"[:140]


def unique_filename(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
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


def relative_path(path: Path, task_dir: Path) -> str:
    return path.resolve().relative_to(task_dir.resolve()).as_posix()


class TaskStore:
    """One local directory per task, with atomic JSON status updates."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def task_dir(self, task_id: str) -> Path | None:
        if not TASK_ID_RE.fullmatch(task_id or ""):
            return None
        return self.root / task_id

    def create_task(
        self,
        *,
        task_id: str,
        uploads: list[dict[str, Any]],
        status: str = "queued",
    ) -> dict[str, Any]:
        task_dir = self.task_dir(task_id)
        if task_dir is None:
            raise ValueError("invalid task id")
        task_dir.mkdir(parents=True, exist_ok=True)
        now = utc_now_iso()
        task: dict[str, Any] = {
            "task_id": task_id,
            "status": status,
            "status_message": "任务已创建，等待处理",
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "error": None,
            "warnings": [],
            "uploads": uploads,
            "extraction": None,
            "audit": None,
            "artifacts": {},
        }
        self.save(task)
        return task

    def task_path(self, task_id: str) -> Path | None:
        task_dir = self.task_dir(task_id)
        if task_dir is None:
            return None
        return task_dir / "task.json"

    def save(self, task: dict[str, Any]) -> None:
        task_id = str(task.get("task_id", ""))
        task_path = self.task_path(task_id)
        if task_path is None:
            raise ValueError("invalid task id")
        task_path.parent.mkdir(parents=True, exist_ok=True)
        task["updated_at"] = utc_now_iso()
        payload = json.dumps(task, ensure_ascii=False, indent=2)
        with self._lock:
            for attempt in range(8):
                temporary = task_path.with_name(
                    f"{task_path.name}.{uuid.uuid4().hex}.tmp"
                )
                try:
                    temporary.write_text(payload, encoding="utf-8")
                    os.replace(temporary, task_path)
                    return
                except PermissionError:
                    temporary.unlink(missing_ok=True)
                    if attempt == 7:
                        task_path.write_text(payload, encoding="utf-8")
                        return
                    time.sleep(0.03 * (attempt + 1))

    def load(self, task_id: str) -> dict[str, Any] | None:
        task_path = self.task_path(task_id)
        if task_path is None or not task_path.is_file():
            return None
        try:
            payload = json.loads(task_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def list_tasks(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for task_file in self.root.glob("*/task.json"):
            task_id = task_file.parent.name
            task = self.load(task_id)
            if task is not None:
                tasks.append(task)
        tasks.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return tasks

    def artifact_path(
        self,
        task: dict[str, Any],
        artifact_id: str,
    ) -> Path | None:
        artifacts = task.get("artifacts")
        if not isinstance(artifacts, dict):
            return None
        artifact = artifacts.get(artifact_id)
        if not isinstance(artifact, dict):
            return None
        raw_path = artifact.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            return None
        task_dir = self.task_dir(str(task.get("task_id", "")))
        if task_dir is None:
            return None
        candidate = (task_dir / raw_path).resolve()
        try:
            candidate.relative_to(task_dir.resolve())
        except ValueError:
            return None
        if not candidate.is_file():
            return None
        return candidate

    def artifact_filename(
        self,
        task: dict[str, Any],
        artifact_id: str,
    ) -> str:
        artifact = (task.get("artifacts") or {}).get(artifact_id) or {}
        filename = artifact.get("filename")
        if isinstance(filename, str) and filename:
            return safe_filename(filename)
        return safe_filename(artifact_id)


def list_artifacts_for_display(
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    artifacts = task.get("artifacts")
    if not isinstance(artifacts, dict):
        return []
    result: list[dict[str, Any]] = []
    for artifact_id, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            continue
        result.append(
            {
                "id": artifact_id,
                "label": artifact.get("label") or artifact_id,
                "kind": artifact.get("kind") or "file",
                "filename": artifact.get("filename") or artifact_id,
            }
        )
    return result


def upload_entries(uploads: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in uploads if isinstance(item, dict)]
