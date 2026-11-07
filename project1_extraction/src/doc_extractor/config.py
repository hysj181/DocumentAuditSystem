"""Project-level path configuration.

All default directories are derived from this file's location, so the
application behaves the same no matter which working directory it is started
from. Explicit user paths and environment variables still take precedence.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT_ROOT = PROJECT_ROOT / "test_data"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_CACHE_DIR = PROJECT_ROOT / ".paddlex_cache"
DEFAULT_TEMP_DIR = PROJECT_ROOT / ".tmp"

INPUT_ROOT_ENV = "DOC_EXTRACTOR_INPUT_DIR"
OUTPUT_ROOT_ENV = "DOC_EXTRACTOR_OUTPUT_DIR"
LOG_DIR_ENV = "DOC_EXTRACTOR_LOG_DIR"
TEMP_DIR_ENV = "DOC_EXTRACTOR_TEMP_DIR"


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


def resolve_log_dir(value: str | Path | None = None) -> Path:
    """Return the log directory: explicit path, environment, then project default."""

    return _resolve(value, LOG_DIR_ENV, DEFAULT_LOG_DIR)


def resolve_temp_dir(value: str | Path | None = None) -> Path:
    """Return the temporary directory: explicit path, environment, then default."""

    return _resolve(value, TEMP_DIR_ENV, DEFAULT_TEMP_DIR)
