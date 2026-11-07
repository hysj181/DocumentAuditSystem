"""Project-level path configuration.

Defaults are derived from this file's location so that commands behave the
same regardless of the current working directory. Explicit arguments and
environment variables take precedence over the defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT_ROOT = PROJECT_ROOT / "test_data"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output"
DEFAULT_ANNOTATED_DIR = DEFAULT_OUTPUT_ROOT / "annotated"
DEFAULT_REPORTS_DIR = DEFAULT_OUTPUT_ROOT / "reports"
DEFAULT_CACHE_DIR = PROJECT_ROOT / ".cache"
DEFAULT_TEMP_DIR = PROJECT_ROOT / ".tmp"

INPUT_ROOT_ENV = "WORD_AUDIT_INPUT_DIR"
OUTPUT_ROOT_ENV = "WORD_AUDIT_OUTPUT_DIR"
TEMP_DIR_ENV = "WORD_AUDIT_TEMP_DIR"


def _environment_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def _resolve(
    value: str | Path | None,
    environment_name: str,
    default: Path,
) -> Path:
    if value is not None:
        return Path(value).expanduser().resolve()
    configured = _environment_path(environment_name)
    if configured is not None:
        return configured.resolve()
    return default.resolve()


def resolve_input_root(value: str | Path | None = None) -> Path:
    """Return the input root: explicit path, environment, then project default."""

    return _resolve(value, INPUT_ROOT_ENV, DEFAULT_INPUT_ROOT)


def resolve_output_root(value: str | Path | None = None) -> Path:
    """Return the output root: explicit path, environment, then project default."""

    return _resolve(value, OUTPUT_ROOT_ENV, DEFAULT_OUTPUT_ROOT)


def resolve_temp_dir(value: str | Path | None = None) -> Path:
    """Return the temporary directory: explicit path, environment, then default."""

    return _resolve(value, TEMP_DIR_ENV, DEFAULT_TEMP_DIR)
