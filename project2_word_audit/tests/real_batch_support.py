"""Build a reproducible real project-one batch from the tracked test data.

The fixture is created once per pytest session by ``tests/conftest.py``.
Tests call :func:`real_batch_path` from ``setUpClass``; if the session fixture
has not run, the helper raises a clear error instead of skipping.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT1_TEST_DATA = REPO_ROOT / "project1_extraction" / "test_data"
REAL_BATCH_ID = "20261101T053459830362Z_0e022780"
INPUT_FILES = (
    PROJECT1_TEST_DATA / "01_企业废水监测报告.docx",
    PROJECT1_TEST_DATA / "02_企业废气监测报告.pdf",
)

_batch_path: Path | None = None

EXPECTED_INDICATORS = [
    "COD",
    "氨氮",
    "总磷",
    "总氮",
    "pH",
    "颗粒物",
    "二氧化硫",
    "氮氧化物",
    "排放速率",
]


def _validate_batch(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("batch_id") != REAL_BATCH_ID:
        raise RuntimeError(
            f"real batch fixture has unexpected batch_id: {payload.get('batch_id')!r}"
        )
    documents = payload.get("documents")
    if not isinstance(documents, list) or len(documents) != 2:
        raise RuntimeError(
            f"real batch fixture must contain 2 documents, got {documents!r}"
        )
    records = (payload.get("environmental") or {}).get("records")
    if not isinstance(records, list) or len(records) != 9:
        raise RuntimeError(
            f"real batch fixture must contain 9 environmental records, got {records!r}"
        )
    indicators = [record.get("indicator") for record in records]
    if indicators != EXPECTED_INDICATORS:
        raise RuntimeError(
            f"real batch fixture indicators changed: {indicators!r}"
        )
    word = next(
        (document for document in documents if document.get("file_type") == "word"),
        None,
    )
    pdf = next(
        (document for document in documents if document.get("file_type") == "pdf"),
        None,
    )
    if word is None or pdf is None:
        raise RuntimeError("real batch fixture must contain one Word and one PDF")
    table_records = [
        record
        for record in word.get("records", [])
        if record.get("content_type") == "table"
    ]
    if not table_records:
        raise RuntimeError("real batch fixture Word document has no table")
    rows = (table_records[0].get("metadata") or {}).get("rows") or []
    if len(rows) != 6 or any(len(row) != 4 for row in rows):
        raise RuntimeError(
            f"real batch fixture Word table must be 6x4, got {len(rows)} rows"
        )
    if rows[1][1] != "85" or rows[2][1] != "12.5":
        raise RuntimeError("real batch fixture Word table values changed")


def initialize_real_batch(root: str | Path) -> Path:
    """Extract the tracked test data once and return the generated batch.json."""

    global _batch_path
    if _batch_path is not None and _batch_path.is_file():
        return _batch_path

    from doc_extractor.api import extract_files, save_batch
    from doc_extractor.core.paddle_structure import ensure_paddle_cache_dir

    ensure_paddle_cache_dir()
    missing = [str(path) for path in INPUT_FILES if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "real batch fixture input files are missing: " + ", ".join(missing)
        )

    batch = extract_files(INPUT_FILES, mode="local_gpu")
    if batch.batch_id != REAL_BATCH_ID:
        batch.batch_id = REAL_BATCH_ID
    outputs = save_batch(batch, root, formats=("json",))
    path = Path(outputs["batch"])
    _validate_batch(path)
    _batch_path = path
    return path


def real_batch_path() -> Path:
    """Return the session fixture batch path; fail loudly if not initialized."""

    if _batch_path is None or not _batch_path.is_file():
        raise RuntimeError(
            "real batch fixture is not initialized; run project two tests "
            "through pytest so tests/conftest.py can create it"
        )
    return _batch_path
