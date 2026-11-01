"""任务指纹和版本检测测试。"""

from __future__ import annotations

import json
from pathlib import Path

from project3_cli_workflow.config import ProjectConfig
from project3_cli_workflow.fingerprint import (
    apply_fingerprint,
    build_task_fingerprint,
    read_project_version,
)
from project3_cli_workflow.manifest import build_manifest
from project3_cli_workflow.models import RunManifest


def _create_project(
    root: Path,
    version: str,
    *,
    with_pyproject: bool = True,
) -> tuple[Path, Path]:
    """创建带版本文件的模拟项目。"""

    root.mkdir(parents=True, exist_ok=True)
    python = root / "python.exe"
    python.write_text("", encoding="utf-8")
    if with_pyproject:
        (root / "pyproject.toml").write_text(
            f'[project]\nname = "fake"\nversion = "{version}"\n',
            encoding="utf-8",
        )
    return root, python


def _config(
    tmp_path: Path,
    *,
    p1_version: str = "0.6.0",
    p2_version: str = "0.1.0",
    p1_pyproject: bool = True,
    p2_pyproject: bool = True,
) -> ProjectConfig:
    """创建测试配置。"""

    p1_root, p1_python = _create_project(
        tmp_path / "p1",
        p1_version,
        with_pyproject=p1_pyproject,
    )
    p2_root, p2_python = _create_project(
        tmp_path / "p2",
        p2_version,
        with_pyproject=p2_pyproject,
    )
    return ProjectConfig.from_overrides(
        project1_root=p1_root,
        project1_python=p1_python,
        project2_root=p2_root,
        project2_python=p2_python,
    )


def _inputs(tmp_path: Path, name: str = "a.docx") -> list:
    """构建输入文件清单。"""

    path = tmp_path / name
    path.write_text("input", encoding="utf-8")
    return build_manifest([path]).inputs


def test_read_project_version(tmp_path: Path) -> None:
    """应从 pyproject.toml 读取版本。"""

    root, _ = _create_project(tmp_path / "project", "1.2.3")
    assert read_project_version(root) == "1.2.3"


def test_same_input_same_fingerprint(tmp_path: Path) -> None:
    """相同输入和配置必须得到相同指纹。"""

    config = _config(tmp_path)
    inputs = _inputs(tmp_path)

    first = build_task_fingerprint(inputs, "local_gpu", config)
    second = build_task_fingerprint(inputs, "local_gpu", config)

    assert first.value == second.value
    assert first.safe is True


def test_input_content_change_changes_fingerprint(tmp_path: Path) -> None:
    """输入 SHA-256 变化必须改变指纹。"""

    config = _config(tmp_path)
    path = tmp_path / "a.docx"
    path.write_text("input", encoding="utf-8")
    first_inputs = build_manifest([path]).inputs
    first = build_task_fingerprint(first_inputs, "local_gpu", config)
    path.write_text("changed", encoding="utf-8")
    second_inputs = build_manifest([path]).inputs
    second = build_task_fingerprint(second_inputs, "local_gpu", config)

    assert first.value != second.value


def test_input_path_change_changes_fingerprint(tmp_path: Path) -> None:
    """输入绝对路径变化必须改变指纹。"""

    config = _config(tmp_path)
    first_inputs = _inputs(tmp_path, "a.docx")
    second_inputs = _inputs(tmp_path, "b.docx")

    first = build_task_fingerprint(first_inputs, "local_gpu", config)
    second = build_task_fingerprint(second_inputs, "local_gpu", config)

    assert first.value != second.value


def test_mode_change_changes_fingerprint(tmp_path: Path) -> None:
    """local_gpu 与 cloud_api 不得互相复用。"""

    config = _config(tmp_path)
    inputs = _inputs(tmp_path)

    local = build_task_fingerprint(inputs, "local_gpu", config)
    cloud = build_task_fingerprint(inputs, "cloud_api", config)

    assert local.value != cloud.value


def test_project_version_change_changes_fingerprint(
    tmp_path: Path,
) -> None:
    """项目一或项目二版本变化必须改变指纹。"""

    first_config = _config(tmp_path, p1_version="0.6.0", p2_version="0.1.0")
    inputs = _inputs(tmp_path)
    first = build_task_fingerprint(inputs, "local_gpu", first_config)

    second_config = _config(tmp_path, p1_version="0.6.1", p2_version="0.1.0")
    second = build_task_fingerprint(inputs, "local_gpu", second_config)
    assert first.value != second.value

    third_config = _config(tmp_path, p1_version="0.6.0", p2_version="0.2.0")
    third = build_task_fingerprint(inputs, "local_gpu", third_config)
    assert first.value != third.value


def test_missing_version_disables_reuse(tmp_path: Path) -> None:
    """无法确定版本时不得标记为可安全复用。"""

    config = _config(tmp_path, p1_pyproject=False)
    fingerprint = build_task_fingerprint(
        _inputs(tmp_path),
        "local_gpu",
        config,
    )

    assert fingerprint.safe is False


def test_token_not_in_fingerprint(tmp_path: Path, monkeypatch) -> None:
    """API Token 不得进入指纹组件。"""

    secret = "secret-token-value"
    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", secret)
    config = _config(tmp_path)
    fingerprint = build_task_fingerprint(
        _inputs(tmp_path),
        "cloud_api",
        config,
    )

    serialized = json.dumps(
        fingerprint.components,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert secret not in serialized
    assert "access_token" not in serialized.casefold()
    assert "paddleocr_access_token" not in serialized.casefold()


def test_apply_fingerprint_writes_safe_components(tmp_path: Path) -> None:
    """指纹应写入 manifest 的版本和非敏感配置字段。"""

    config = _config(tmp_path)
    fingerprint = build_task_fingerprint(
        _inputs(tmp_path),
        "local_gpu",
        config,
    )
    manifest = RunManifest(job_id="job-1", created_at="now")

    apply_fingerprint(manifest, fingerprint)

    assert manifest.task_fingerprint == fingerprint.value
    assert manifest.project1_version == "0.6.0"
    assert manifest.project2_version == "0.1.0"
    assert manifest.project1_root == str(config.project1_root.resolve())
    assert manifest.workflow_version
    assert manifest.fingerprint_components == fingerprint.components
