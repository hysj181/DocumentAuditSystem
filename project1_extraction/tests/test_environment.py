from __future__ import annotations

import sys

from doc_extractor.core.environment import (
    collect_environment_info,
    format_environment_info,
)


def test_python_version_is_supported() -> None:
    assert sys.version_info >= (3, 12)


def test_required_dependencies_are_available() -> None:
    statuses = collect_environment_info()
    missing = [status.name for status in statuses if not status.available]

    assert not missing, f"Missing dependencies: {', '.join(missing)}"
    assert all(status.version != "unknown" for status in statuses)


def test_environment_info_is_formatted() -> None:
    text = format_environment_info()

    assert "Python" in text
    assert "Dependencies:" in text
    for name in ("PySide6", "python-docx", "PyMuPDF", "openpyxl", "pytest"):
        assert name in text
