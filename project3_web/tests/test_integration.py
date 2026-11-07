from __future__ import annotations

import hashlib
from pathlib import Path

from doc_extractor.api import extract_files, save_batch
from fastapi.testclient import TestClient
from project3_web.app import create_app
from word_audit.pipeline import run_audit

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DATA = REPO_ROOT / "project1_extraction" / "test_data"
INPUT_FILES = (
    TEST_DATA / "01_企业废水监测报告.docx",
    TEST_DATA / "02_企业废气监测报告.pdf",
)
BATCH_ID = "20261101T053459830362Z_0e022780"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mixed_word_pdf_end_to_end(tmp_path: Path) -> None:
    before = {str(path): _sha256(path) for path in INPUT_FILES}

    batch = extract_files(INPUT_FILES, mode="local_gpu")
    batch.batch_id = BATCH_ID
    outputs = save_batch(batch, tmp_path / "01_extraction", formats=("json",))
    batch_json = Path(outputs["batch"])
    assert batch_json.is_file()

    result = run_audit(batch_json, tmp_path / "02_audit")
    counts = result.report.metadata["pipeline"]["counts"]
    assert counts["record_count"] == 9
    assert counts["unverified_count"] == 9
    assert counts["issue_count"] == 0
    assert result.report.metadata["pipeline"]["complete_success"] is True
    assert result.output_files == []
    assert len(result.batch.documents) == 2
    assert len(result.batch.environmental_records) == 9

    for path in (
        result.audit_json_path,
        result.audit_markdown_path,
        result.math_validation_path,
        result.annotation.json_path,
        result.annotation.markdown_path,
    ):
        assert path.is_file(), path

    after = {str(path): _sha256(path) for path in INPUT_FILES}
    assert before == after
