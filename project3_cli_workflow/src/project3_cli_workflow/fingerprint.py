"""任务指纹计算。

指纹只包含非敏感配置和输入文件摘要，不包含任何 API Token。
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project3_cli_workflow.config import ProjectConfig
from project3_cli_workflow.models import (
    MANIFEST_SCHEMA_VERSION,
    InputFile,
    RunManifest,
)

WORKFLOW_VERSION = "0.1.0"
FINGERPRINT_VERSION = "1.0"


@dataclass(frozen=True)
class Fingerprint:
    """任务指纹及其安全组件。"""

    value: str
    components: dict[str, Any]
    safe: bool


def read_project_version(project_root: str | Path) -> str | None:
    """从项目 pyproject.toml 读取版本，不执行外部项目。"""

    pyproject = Path(project_root).expanduser() / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        with pyproject.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = payload.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        return None
    return version.strip()


def _resolved(path: str | Path) -> str:
    """返回规范绝对路径字符串。"""

    return str(Path(path).expanduser().resolve())


def _input_components(inputs: list[InputFile]) -> list[dict[str, Any]]:
    """生成稳定排序的输入摘要组件。"""

    items = [
        {
            "source_path": _resolved(item.source_path),
            "sha256": item.sha256,
            "file_size": item.file_size,
        }
        for item in inputs
    ]
    items.sort(key=lambda item: os.path.normcase(item["source_path"]))
    return items


def build_task_fingerprint(
    inputs: list[InputFile],
    mode: str,
    config: ProjectConfig,
    *,
    project1_version: str | None = None,
    project2_version: str | None = None,
) -> Fingerprint:
    """根据输入和当前配置计算任务指纹。"""

    version1 = (
        project1_version
        if project1_version is not None
        else read_project_version(config.project1_root)
    )
    version2 = (
        project2_version
        if project2_version is not None
        else read_project_version(config.project2_root)
    )
    components: dict[str, Any] = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "workflow_version": WORKFLOW_VERSION,
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "input_count": len(inputs),
        "inputs": _input_components(inputs),
        "mode": mode,
        "project1_root": _resolved(config.project1_root),
        "project1_python": _resolved(config.project1_python),
        "project1_version": version1,
        "project2_root": _resolved(config.project2_root),
        "project2_python": _resolved(config.project2_python),
        "project2_version": version2,
    }
    canonical = json.dumps(
        components,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    value = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Fingerprint(
        value=value,
        components=components,
        safe=version1 is not None and version2 is not None,
    )


def _component_text(
    components: dict[str, Any],
    key: str,
) -> str | None:
    """读取字符串组件。"""

    value = components.get(key)
    return value if isinstance(value, str) else None


def apply_fingerprint(manifest: RunManifest, fingerprint: Fingerprint) -> None:
    """把指纹写入 manifest，不修改输入和阶段结果。"""

    manifest.task_fingerprint = fingerprint.value
    manifest.fingerprint_components = dict(fingerprint.components)
    manifest.workflow_version = WORKFLOW_VERSION
    manifest.project1_version = _component_text(
        fingerprint.components,
        "project1_version",
    )
    manifest.project2_version = _component_text(
        fingerprint.components,
        "project2_version",
    )
    manifest.project1_root = _component_text(
        fingerprint.components,
        "project1_root",
    )
    manifest.project2_root = _component_text(
        fingerprint.components,
        "project2_root",
    )
