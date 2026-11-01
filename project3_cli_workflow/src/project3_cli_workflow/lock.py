"""任务级文件锁，避免两个进程同时修改同一 manifest。"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from project3_cli_workflow.errors import TaskLockError

LOCK_FILE_NAME = ".task.lock"
STALE_SECONDS = 24 * 60 * 60


def _now_iso() -> str:
    """返回当前 UTC 时间。"""

    return datetime.now(UTC).isoformat()


def _pid_alive(pid: int) -> bool:
    """检查 PID 是否仍然存活。"""

    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        error_invalid_parameter = 87
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return ctypes.windll.kernel32.GetLastError() != (
            error_invalid_parameter
        )
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_created_at(value: Any) -> datetime | None:
    """解析锁创建时间。"""

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _lock_is_stale(payload: dict[str, Any], lock_path: Path) -> bool:
    """判断锁是否已过期。"""

    created = _parse_created_at(payload.get("created_at"))
    if created is not None:
        age = (datetime.now(UTC) - created).total_seconds()
        if age > STALE_SECONDS:
            return True
    pid = payload.get("pid")
    if isinstance(pid, int) and not isinstance(pid, bool):
        return not _pid_alive(pid)
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return True
    return age > STALE_SECONDS


def _read_lock(lock_path: Path) -> dict[str, Any] | None:
    """读取锁内容。"""

    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@dataclass
class TaskLock:
    """任务锁上下文管理器。"""

    task_dir: Path
    job_id: str
    lock_id: str | None = None

    @property
    def lock_path(self) -> Path:
        """锁文件路径。"""

        return self.task_dir / LOCK_FILE_NAME

    def acquire(self) -> None:
        """获取任务锁。"""

        self.task_dir.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            lock_id = uuid.uuid4().hex
            payload = {
                "job_id": self.job_id,
                "lock_id": lock_id,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "created_at": _now_iso(),
            }
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                existing = _read_lock(self.lock_path)
                if existing is not None and _lock_is_stale(
                    existing,
                    self.lock_path,
                ):
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass
                    continue
                pid = (
                    existing.get("pid")
                    if isinstance(existing, dict)
                    else None
                )
                raise TaskLockError(
                    "任务已被其他进程锁定："
                    f"{self.job_id}，PID={pid}"
                )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                self.lock_id = lock_id
            except OSError as exc:
                self.lock_path.unlink(missing_ok=True)
                raise TaskLockError(
                    f"无法写入任务锁：{self.lock_path}；{exc}"
                ) from exc
            return
        raise TaskLockError(f"无法获取任务锁：{self.job_id}")

    def release(self) -> None:
        """释放当前进程持有的锁。"""

        if self.lock_id is None:
            return
        existing = _read_lock(self.lock_path)
        if existing is not None and existing.get("lock_id") == self.lock_id:
            try:
                self.lock_path.unlink()
            except OSError:
                pass
        self.lock_id = None

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
