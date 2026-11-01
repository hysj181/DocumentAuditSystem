"""输入路径解析、文件夹扫描和文件过滤。

只接受项目一实际支持的 ``.docx`` 和 ``.pdf``，扩展名统一按小写处理。
本模块不读取文件内容，也不修改原始文件。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from project3_cli_workflow.errors import InputError
from project3_cli_workflow.models import (
    FILTER_REASON_DUPLICATE,
    FILTER_REASON_UNSUPPORTED,
    FilteredInput,
)

SUPPORTED_SUFFIXES: dict[str, str] = {
    ".docx": "docx",
    ".pdf": "pdf",
}


@dataclass
class InputScanResult:
    """输入扫描结果。"""

    files: list[Path] = field(default_factory=list)
    filtered: list[FilteredInput] = field(default_factory=list)


def _path_key(path: Path) -> str:
    """返回用于去重和稳定排序的规范路径键。"""

    return os.path.normcase(str(path.resolve()))


def _file_type(path: Path) -> str:
    """返回小写扩展名，不含点；无扩展名时返回 unknown。"""

    suffix = path.suffix.casefold().lstrip(".")
    return suffix or "unknown"


def _filtered(path: Path, reason: str, message: str) -> FilteredInput:
    """构造过滤记录。"""

    return FilteredInput(
        source_path=str(path.resolve()),
        file_name=path.name,
        file_type=_file_type(path),
        reason=reason,
        message=message,
    )


def _add_file(
    path: Path,
    *,
    files: list[Path],
    filtered: list[FilteredInput],
    seen: set[str],
) -> None:
    """过滤单个文件；支持的类型加入有效列表。"""

    resolved = path.resolve()
    key = _path_key(resolved)

    if resolved.suffix.casefold() not in SUPPORTED_SUFFIXES:
        filtered.append(
            _filtered(
                resolved,
                FILTER_REASON_UNSUPPORTED,
                "不支持的文件类型；项目一仅支持 .docx 和 .pdf",
            )
        )
        return

    if key in seen:
        filtered.append(
            _filtered(
                resolved,
                FILTER_REASON_DUPLICATE,
                "重复输入文件，已跳过",
            )
        )
        return

    seen.add(key)
    files.append(resolved)


def _scan_directory(path: Path, recursive: bool) -> list[Path]:
    """扫描文件夹中的文件，并按规范路径稳定排序。"""

    if recursive:
        candidates = path.rglob("*")
    else:
        candidates = path.glob("*")
    files = [candidate for candidate in candidates if candidate.is_file()]
    return sorted(files, key=_path_key)


def collect_inputs(
    paths: Iterable[str | Path],
    *,
    recursive: bool = False,
) -> InputScanResult:
    """解析用户输入并返回有效文件与过滤记录。

    字符串路径按用户给定顺序处理；文件夹内部按规范路径稳定排序。
    """

    raw_paths = list(paths)
    if not raw_paths:
        raise InputError("未提供输入文件或文件夹。")

    result = InputScanResult()
    seen: set[str] = set()

    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise InputError(f"输入路径不存在：{path}")
        if path.is_file():
            _add_file(
                path,
                files=result.files,
                filtered=result.filtered,
                seen=seen,
            )
            continue
        if path.is_dir():
            for candidate in _scan_directory(path, recursive):
                _add_file(
                    candidate,
                    files=result.files,
                    filtered=result.filtered,
                    seen=seen,
                )
            continue
        raise InputError(f"输入路径既不是文件也不是文件夹：{path}")

    if not result.files:
        detail = (
            f"已过滤 {len(result.filtered)} 个文件。"
            if result.filtered
            else ""
        )
        raise InputError(
            "未找到可处理的 .docx 或 .pdf 文件；请检查输入文件或文件夹。"
            f"{detail}"
        )

    return result
