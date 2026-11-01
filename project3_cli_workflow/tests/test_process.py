"""子进程调用、超时和输出安全测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from project3_cli_workflow.process import redact_text, run_process


def test_run_process_captures_output_and_arguments(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """子进程参数、cwd、超时、stdout 和 stderr 应被记录。"""

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="标准输出",
            stderr="标准错误",
        )

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_process(
        ["python.exe", "main.py", "extract"],
        cwd=tmp_path,
        timeout=12.5,
        env={"PYTHONUTF8": "1"},
    )

    assert result.exit_code == 0
    assert result.stdout == "标准输出"
    assert result.stderr == "标准错误"
    assert result.timed_out is False
    assert result.start_failed is False
    assert captured["cwd"] == str(tmp_path)
    assert captured["timeout"] == 12.5
    assert captured["shell"] is False
    assert captured["env"] == {"PYTHONUTF8": "1"}


def test_run_process_start_failure(monkeypatch) -> None:
    """解释器或入口不存在时应返回启动失败。"""

    def fake_run(command, **kwargs):
        raise FileNotFoundError("python.exe")

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_process(["missing-python", "main.py"], cwd=".", timeout=5)

    assert result.start_failed is True
    assert result.timed_out is False
    assert result.exit_code is None
    assert "无法启动项目一进程" in (result.error or "")


def test_run_process_timeout(monkeypatch) -> None:
    """超时应保留已有 stdout/stderr 并返回超时状态。"""

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command,
            kwargs["timeout"],
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    monkeypatch.setattr(
        "project3_cli_workflow.process.subprocess.run",
        fake_run,
    )

    result = run_process(["python.exe", "main.py"], cwd=".", timeout=3)

    assert result.timed_out is True
    assert result.exit_code is None
    assert result.stdout == "partial stdout"
    assert result.stderr == "partial stderr"
    assert "超时" in (result.error or "")


def test_redact_text_removes_secret() -> None:
    """敏感值必须从日志文本中移除。"""

    text = "token=secret-value，其他内容不变"
    assert redact_text(text, ("secret-value",)) == "token=***，其他内容不变"
