"""项目三运行配置。

本模块只负责解析项目一、项目二路径和 Python 解释器，不调用外部项目。
优先级从高到低为：命令行参数、环境变量、默认值。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from project3_cli_workflow.errors import ConfigError

PROJECT3_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT3_ROOT.parent

DEFAULT_PROJECT1_ROOT = WORKSPACE_ROOT / "project1_extraction"
DEFAULT_PROJECT2_ROOT = WORKSPACE_ROOT / "project2_word_audit"

PROJECT1_ROOT_ENV = "PROJECT1_ROOT"
PROJECT1_PYTHON_ENV = "PROJECT1_PYTHON"
PROJECT2_ROOT_ENV = "PROJECT2_ROOT"
PROJECT2_PYTHON_ENV = "PROJECT2_PYTHON"


def default_python_path(project_root: Path) -> Path:
    """返回项目虚拟环境中 Python 解释器的默认路径。"""

    if sys.platform == "win32":
        return project_root / ".venv" / "Scripts" / "python.exe"
    return project_root / ".venv" / "bin" / "python"


def _environment_path(name: str) -> Path | None:
    """读取环境变量中的路径。"""

    value = os.environ.get(name, "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def _choose_path(
    explicit: Path | None,
    environment_name: str,
    default: Path,
) -> Path:
    """按命令行、环境变量、默认值的顺序选择路径。"""

    selected = explicit
    if selected is None:
        selected = _environment_path(environment_name)
    if selected is None:
        selected = default
    return selected.expanduser()


@dataclass(frozen=True)
class ProjectConfig:
    """项目一和项目二的运行配置。"""

    project1_root: Path
    project1_python: Path
    project2_root: Path
    project2_python: Path

    @classmethod
    def from_overrides(
        cls,
        *,
        project1_root: Path | None = None,
        project1_python: Path | None = None,
        project2_root: Path | None = None,
        project2_python: Path | None = None,
    ) -> ProjectConfig:
        """根据命令行覆盖值、环境变量和默认值构造配置。"""

        root1 = _choose_path(
            project1_root,
            PROJECT1_ROOT_ENV,
            DEFAULT_PROJECT1_ROOT,
        )
        root2 = _choose_path(
            project2_root,
            PROJECT2_ROOT_ENV,
            DEFAULT_PROJECT2_ROOT,
        )
        python1 = _choose_path(
            project1_python,
            PROJECT1_PYTHON_ENV,
            default_python_path(root1),
        )
        python2 = _choose_path(
            project2_python,
            PROJECT2_PYTHON_ENV,
            default_python_path(root2),
        )
        return cls(
            project1_root=root1.resolve(),
            project1_python=python1.resolve(),
            project2_root=root2.resolve(),
            project2_python=python2.resolve(),
        )

    def validate(self) -> None:
        """检查项目根目录和 Python 解释器是否存在。"""

        self._validate_directory("项目一", "根目录", self.project1_root)
        self._validate_file("项目一", "Python 解释器", self.project1_python)
        self._validate_directory("项目二", "根目录", self.project2_root)
        self._validate_file("项目二", "Python 解释器", self.project2_python)

    @staticmethod
    def _validate_directory(project: str, label: str, path: Path) -> None:
        if not path.exists():
            raise ConfigError(f"{project} {label}不存在：{path}")
        if not path.is_dir():
            raise ConfigError(f"{project} {label}不是目录：{path}")

    @staticmethod
    def _validate_file(project: str, label: str, path: Path) -> None:
        if not path.exists():
            raise ConfigError(f"{project} {label}不存在：{path}")
        if not path.is_file():
            raise ConfigError(f"{project} {label}不是文件：{path}")


def load_config(
    *,
    project1_root: Path | None = None,
    project1_python: Path | None = None,
    project2_root: Path | None = None,
    project2_python: Path | None = None,
) -> ProjectConfig:
    """构造并校验项目配置。"""

    config = ProjectConfig.from_overrides(
        project1_root=project1_root,
        project1_python=project1_python,
        project2_root=project2_root,
        project2_python=project2_python,
    )
    config.validate()
    return config
