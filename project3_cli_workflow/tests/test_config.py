"""项目路径和 Python 解释器配置测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from project3_cli_workflow.config import ProjectConfig, load_config
from project3_cli_workflow.errors import ConfigError


def _create_project(root: Path, name: str = "python.exe") -> tuple[Path, Path]:
    """创建模拟项目目录和 Python 解释器文件。"""

    root.mkdir(parents=True)
    python = root / name
    python.write_text("", encoding="utf-8")
    return root, python


def test_defaults_point_to_sibling_projects() -> None:
    """未覆盖时默认定位到项目一和项目二同级目录。"""

    config = ProjectConfig.from_overrides()

    assert config.project1_root.name == "project1_extraction"
    assert config.project2_root.name == "project2_word_audit"
    assert config.project1_python.name in {"python.exe", "python"}
    assert config.project2_python.name in {"python.exe", "python"}


def test_command_line_overrides_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命令行参数优先于环境变量。"""

    env_root, _ = _create_project(tmp_path / "env_project1")
    explicit_root, explicit_python = _create_project(tmp_path / "cli_project1")
    project2_root, project2_python = _create_project(tmp_path / "project2")

    monkeypatch.setenv("PROJECT1_ROOT", str(env_root))
    monkeypatch.setenv("PROJECT1_PYTHON", str(env_root / "python.exe"))

    config = ProjectConfig.from_overrides(
        project1_root=explicit_root,
        project1_python=explicit_python,
        project2_root=project2_root,
        project2_python=project2_python,
    )

    assert config.project1_root == explicit_root.resolve()
    assert config.project1_python == explicit_python.resolve()


def test_environment_overrides_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未传命令行参数时使用环境变量。"""

    project1_root, project1_python = _create_project(tmp_path / "project1")
    project2_root, project2_python = _create_project(tmp_path / "project2")

    monkeypatch.setenv("PROJECT1_ROOT", str(project1_root))
    monkeypatch.setenv("PROJECT1_PYTHON", str(project1_python))
    monkeypatch.setenv("PROJECT2_ROOT", str(project2_root))
    monkeypatch.setenv("PROJECT2_PYTHON", str(project2_python))

    config = ProjectConfig.from_overrides()

    assert config.project1_root == project1_root.resolve()
    assert config.project1_python == project1_python.resolve()
    assert config.project2_root == project2_root.resolve()
    assert config.project2_python == project2_python.resolve()


def test_load_config_validates_existing_paths(tmp_path: Path) -> None:
    """有效目录和解释器可以通过校验。"""

    project1_root, project1_python = _create_project(tmp_path / "project1")
    project2_root, project2_python = _create_project(tmp_path / "project2")

    config = load_config(
        project1_root=project1_root,
        project1_python=project1_python,
        project2_root=project2_root,
        project2_python=project2_python,
    )

    assert config.project1_root == project1_root.resolve()


def test_missing_project_root_raises_config_error(tmp_path: Path) -> None:
    """项目根目录不存在时抛出 ConfigError。"""

    _project1_root, project1_python = _create_project(tmp_path / "project1")
    project2_root, project2_python = _create_project(tmp_path / "project2")

    with pytest.raises(ConfigError, match="项目一 根目录不存在"):
        load_config(
            project1_root=tmp_path / "missing_project1",
            project1_python=project1_python,
            project2_root=project2_root,
            project2_python=project2_python,
        )


def test_missing_python_raises_config_error(tmp_path: Path) -> None:
    """Python 解释器不存在时抛出 ConfigError。"""

    project1_root, _ = _create_project(tmp_path / "project1")
    project2_root, project2_python = _create_project(tmp_path / "project2")

    with pytest.raises(ConfigError, match="项目一 Python 解释器不存在"):
        load_config(
            project1_root=project1_root,
            project1_python=tmp_path / "missing_python.exe",
            project2_root=project2_root,
            project2_python=project2_python,
        )


def test_project_root_as_file_raises_config_error(tmp_path: Path) -> None:
    """项目根路径是文件时抛出 ConfigError。"""

    root_file = tmp_path / "not_a_directory"
    root_file.write_text("", encoding="utf-8")
    project1_root, project1_python = _create_project(tmp_path / "project1")
    _project2_root, project2_python = _create_project(tmp_path / "project2")

    with pytest.raises(ConfigError, match="项目二 根目录不是目录"):
        load_config(
            project1_root=project1_root,
            project1_python=project1_python,
            project2_root=root_file,
            project2_python=project2_python,
        )
