"""任务锁和并发保护测试。"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from project3_cli_workflow.errors import TaskLockError
from project3_cli_workflow.lock import LOCK_FILE_NAME, TaskLock


def _lock_payload(
    *,
    pid: int,
    created_at: datetime,
    lock_id: str = "lock-1",
) -> dict[str, object]:
    """构造锁文件内容。"""

    return {
        "job_id": "job-1",
        "lock_id": lock_id,
        "pid": pid,
        "host": "test-host",
        "created_at": created_at.isoformat(),
    }


def test_acquire_and_release_lock(tmp_path: Path) -> None:
    """正常获取和释放锁。"""

    lock = TaskLock(tmp_path, "job-1")
    with lock:
        assert lock.lock_path.is_file()

    assert not lock.lock_path.exists()


def test_active_lock_rejects_second_holder(tmp_path: Path) -> None:
    """活跃进程持有的锁不得被第二个进程抢占。"""

    lock_path = tmp_path / LOCK_FILE_NAME
    lock_path.write_text(
        json.dumps(
            _lock_payload(
                pid=os.getpid(),
                created_at=datetime.now(UTC),
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(TaskLockError, match="已被其他进程锁定"):
        TaskLock(tmp_path, "job-1").acquire()

    assert lock_path.is_file()


def test_stale_lock_is_replaced(tmp_path: Path) -> None:
    """过期锁可以被安全替换。"""

    lock_path = tmp_path / LOCK_FILE_NAME
    lock_path.write_text(
        json.dumps(
            _lock_payload(
                pid=999999,
                created_at=datetime.now(UTC) - timedelta(days=2),
            )
        ),
        encoding="utf-8",
    )

    lock = TaskLock(tmp_path, "job-1")
    with lock:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["pid"] == os.getpid()

    assert not lock_path.exists()


def test_malformed_recent_lock_is_not_deleted(tmp_path: Path) -> None:
    """无法解析的新锁不得直接删除。"""

    lock_path = tmp_path / LOCK_FILE_NAME
    lock_path.write_text("not json", encoding="utf-8")

    with pytest.raises(TaskLockError):
        TaskLock(tmp_path, "job-1").acquire()

    assert lock_path.read_text(encoding="utf-8") == "not json"


def test_release_does_not_remove_other_holder(tmp_path: Path) -> None:
    """释放逻辑不能删除其他进程的锁。"""

    lock_path = tmp_path / LOCK_FILE_NAME
    lock_path.write_text(
        json.dumps(
            _lock_payload(
                pid=os.getpid(),
                created_at=datetime.now(UTC),
                lock_id="other-lock",
            )
        ),
        encoding="utf-8",
    )
    lock = TaskLock(tmp_path, "job-1")
    lock.lock_id = "my-lock"

    lock.release()

    assert lock_path.is_file()


def test_lock_file_contains_no_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """锁文件不得包含 API Token。"""

    secret = "secret-token-value"
    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", secret)
    lock = TaskLock(tmp_path, "job-1")
    with lock:
        content = lock.lock_path.read_text(encoding="utf-8")
    assert secret not in content
