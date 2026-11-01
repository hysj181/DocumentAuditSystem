"""独立子进程调用和输出安全处理。"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    """一次子进程调用的结果。"""

    command: tuple[str, ...]
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    start_failed: bool = False
    error: str | None = None
    duration_seconds: float = 0.0


def _as_text(value: str | bytes | None) -> str:
    """将子进程输出统一转换为字符串。"""

    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def redact_text(text: str, secrets: Sequence[str] = ()) -> str:
    """从文本中移除敏感值。"""

    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "***")
    return result


def run_process(
    command: Sequence[str],
    *,
    cwd: str | Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    """运行子进程并捕获输出，不因超时或启动失败抛出异常。"""

    command_list = [str(item) for item in command]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command_list,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=dict(env) if env is not None else None,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr)
        return ProcessResult(
            command=tuple(command_list),
            cwd=str(cwd),
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            error=f"子进程超时：超过 {timeout} 秒。",
            duration_seconds=round(time.monotonic() - started, 3),
        )
    except FileNotFoundError as exc:
        return ProcessResult(
            command=tuple(command_list),
            cwd=str(cwd),
            exit_code=None,
            stdout="",
            stderr="",
            start_failed=True,
            error=f"无法启动项目一进程：{exc}",
            duration_seconds=round(time.monotonic() - started, 3),
        )
    except OSError as exc:
        return ProcessResult(
            command=tuple(command_list),
            cwd=str(cwd),
            exit_code=None,
            stdout="",
            stderr="",
            start_failed=True,
            error=f"项目一进程启动或执行失败：{exc}",
            duration_seconds=round(time.monotonic() - started, 3),
        )

    return ProcessResult(
        command=tuple(command_list),
        cwd=str(cwd),
        exit_code=completed.returncode,
        stdout=_as_text(completed.stdout),
        stderr=_as_text(completed.stderr),
        duration_seconds=round(time.monotonic() - started, 3),
    )
