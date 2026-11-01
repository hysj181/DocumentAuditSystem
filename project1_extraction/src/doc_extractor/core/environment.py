from __future__ import annotations

import importlib
import importlib.metadata
import platform
import sys
from dataclasses import dataclass

DEPENDENCIES: dict[str, str] = {
    "PySide6": "PySide6",
    "python-docx": "docx",
    "PyMuPDF": "pymupdf",
    "openpyxl": "openpyxl",
    "pytest": "pytest",
}


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    version: str
    available: bool
    error: str | None = None


def check_dependency(name: str, module_name: str) -> DependencyStatus:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - defensive branch
        return DependencyStatus(
            name=name,
            version="not installed",
            available=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    version = getattr(module, "__version__", None)
    if version is None:
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"

    return DependencyStatus(name=name, version=str(version), available=True)


def collect_environment_info() -> list[DependencyStatus]:
    return [check_dependency(name, module) for name, module in DEPENDENCIES.items()]


def format_environment_info() -> str:
    lines = [
        f"Python      : {platform.python_version()} ({platform.architecture()[0]})",
        f"Executable  : {sys.executable}",
        f"Platform    : {platform.platform()}",
        "",
        "Dependencies:",
    ]

    for status in collect_environment_info():
        if status.available:
            lines.append(f"  {status.name:<12}: {status.version}")
        else:
            lines.append(f"  {status.name:<12}: MISSING ({status.error})")

    return "\n".join(lines)
