"""阶段结果复用判断测试。"""

from __future__ import annotations

import json
from pathlib import Path

from project3_cli_workflow.delivery import run_delivery
from project3_cli_workflow.manifest import (
    build_manifest,
    calculate_sha256,
    write_manifest,
)
from project3_cli_workflow.models import (
    AUDIT_STATUS_SUCCESS,
    EXTRACTION_STATUS_SUCCESS,
    OVERALL_STATUS_SUCCESS,
    RunManifest,
)
from project3_cli_workflow.reuse import (
    validate_audit,
    validate_delivery,
    validate_extraction,
)


def _counts() -> dict[str, int]:
    """返回项目二真实 counts。"""

    return {
        "record_count": 2,
        "verified_count": 0,
        "unverified_count": 2,
        "issue_count": 1,
        "located_count": 1,
        "annotation_applied_count": 1,
        "annotation_failed_count": 0,
        "annotation_manual_review_count": 0,
        "issues_flagged_for_manual_review": 1,
    }


def _typo_counts() -> dict[str, int]:
    """返回项目二真实 typo_counts。"""

    return {
        "typo_issue_count": 0,
        "typo_verified_count": 0,
        "typo_manual_review_count": 0,
        "typo_annotation_success_count": 0,
        "typo_annotation_failed_count": 0,
    }


def _make_task(
    tmp_path: Path,
    *,
    with_annotated: bool = False,
) -> tuple[Path, RunManifest, Path, list]:
    """创建可复用的完整任务。"""

    task_dir = tmp_path / "task"
    input_path = tmp_path / "input" / "监测报告.docx"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes("原始输入".encode())
    inputs_manifest = build_manifest([input_path])
    inputs = inputs_manifest.inputs

    batch_path = (
        task_dir
        / "01_extraction"
        / "batches"
        / "batch-test"
        / "batch.json"
    )
    batch_path.parent.mkdir(parents=True)
    batch_payload = {
        "schema_version": "1.0",
        "batch_id": "batch-test",
        "document_count": 1,
        "documents": [
            {
                "document_id": "doc-1",
                "source_name": input_path.name,
                "source_file": str(input_path.resolve()),
                "file_type": "word",
                "record_count": 1,
                "records": [],
                "tables": [],
                "warnings": [],
                "error": None,
                "metadata": {},
            }
        ],
        "environmental": {"records": [], "warnings": []},
    }
    batch_path.write_text(
        json.dumps(batch_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    reports = task_dir / "02_audit" / "reports"
    reports.mkdir(parents=True)
    audit_json = reports / "audit_report_batch-test.json"
    audit_markdown = reports / "audit_report_batch-test.md"
    annotation_json = reports / "annotation_report_batch-test.json"
    annotation_markdown = reports / "annotation_report_batch-test.md"
    math_json = reports / "batch-test_math_validation.json"
    audit_markdown.write_text("# audit\n", encoding="utf-8")
    annotation_json.write_text("{}", encoding="utf-8")
    annotation_markdown.write_text("# annotation\n", encoding="utf-8")
    math_json.write_text("{}", encoding="utf-8")

    annotated: list[Path] = []
    if with_annotated:
        annotated_path = (
            task_dir / "02_audit" / "annotated" / "监测报告_annotated.docx"
        )
        annotated_path.parent.mkdir(parents=True)
        annotated_path.write_bytes("批注副本".encode())
        annotated.append(annotated_path)

    audit_payload = {
        "schema_version": "1.0",
        "report_id": "report-1",
        "batch_id": "batch-test",
        "generated_at": "2026-11-01T00:00:00+00:00",
        "warnings": [],
        "metadata": {
            "pipeline": {
                "complete_success": True,
                "counts": _counts(),
                "typo_counts": _typo_counts(),
                "warnings": [],
                "errors": [],
                "stage_reports": {
                    "audit_json": str(audit_json),
                    "audit_markdown": str(audit_markdown),
                    "annotation_json": str(annotation_json),
                    "annotation_markdown": str(annotation_markdown),
                    "math_validation": str(math_json),
                },
                "output_files": [str(path) for path in annotated],
            }
        },
    }
    audit_json.write_text(
        json.dumps(audit_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manifest = RunManifest(
        job_id="job-reuse-test",
        created_at="2026-11-01T00:00:00+00:00",
        inputs=inputs,
    )
    manifest.extraction_status = EXTRACTION_STATUS_SUCCESS
    manifest.audit_status = AUDIT_STATUS_SUCCESS
    manifest.overall_status = OVERALL_STATUS_SUCCESS
    manifest.extraction_mode = "local_gpu"
    manifest.batch_id = "batch-test"
    manifest.batch_json_path = str(batch_path.resolve())
    manifest.batch_json_sha256 = calculate_sha256(batch_path)
    manifest.document_count = 1
    manifest.successful_document_count = 1
    manifest.failed_document_count = 0
    manifest.audit_report_json = str(audit_json.resolve())
    manifest.audit_report_sha256 = calculate_sha256(audit_json)
    manifest.audit_report_markdown = str(audit_markdown.resolve())
    manifest.annotation_report = str(annotation_json.resolve())
    manifest.math_validation_report = str(math_json.resolve())
    manifest.annotated_files = [str(path) for path in annotated]
    manifest_path = task_dir / "manifest.json"
    write_manifest(manifest, manifest_path)

    delivery = run_delivery(manifest, manifest_path)
    manifest.delivery_status = delivery.status
    manifest.delivery_started_at = delivery.started_at
    manifest.delivery_finished_at = delivery.finished_at
    manifest.delivery_directory = str(delivery.directory)
    manifest.delivery_report_json = str(delivery.report_json)
    manifest.delivery_report_markdown = str(delivery.report_markdown)
    manifest.delivery_summary_markdown = str(delivery.summary_markdown)
    manifest.delivery_manifest_json = str(delivery.delivery_manifest_json)
    manifest.delivery_artifact_count = len(delivery.artifacts)
    manifest.delivery_missing_artifact_count = len(
        delivery.missing_artifacts
    )
    manifest.delivery_error = delivery.error
    manifest.overall_status = delivery.overall_status
    write_manifest(manifest, manifest_path)
    return task_dir, manifest, manifest_path, inputs


def test_valid_extraction_audit_and_delivery(tmp_path: Path) -> None:
    """完整有效任务三个阶段都应可复用。"""

    task_dir, manifest, _, inputs = _make_task(tmp_path)

    assert validate_extraction(
        manifest,
        task_dir,
        inputs,
        mode="local_gpu",
    ).valid
    assert validate_audit(manifest, task_dir).valid
    assert validate_delivery(manifest, task_dir).valid


def test_missing_batch_disables_extraction_reuse(tmp_path: Path) -> None:
    """batch.json 缺失时提取不可复用。"""

    task_dir, manifest, _, inputs = _make_task(tmp_path)
    Path(str(manifest.batch_json_path)).unlink()

    result = validate_extraction(
        manifest,
        task_dir,
        inputs,
        mode="local_gpu",
    )

    assert result.valid is False
    assert any("不存在" in item for item in result.reasons)


def test_corrupt_batch_disables_extraction_reuse(tmp_path: Path) -> None:
    """batch.json 损坏时提取不可复用。"""

    task_dir, manifest, _, inputs = _make_task(tmp_path)
    Path(str(manifest.batch_json_path)).write_text(
        "{broken",
        encoding="utf-8",
    )

    result = validate_extraction(
        manifest,
        task_dir,
        inputs,
        mode="local_gpu",
    )

    assert result.valid is False
    assert any("batch.json 无效" in item for item in result.reasons)


def test_batch_id_mismatch_disables_extraction_reuse(
    tmp_path: Path,
) -> None:
    """batch_id 不匹配时提取不可复用。"""

    task_dir, manifest, _, inputs = _make_task(tmp_path)
    batch_path = Path(str(manifest.batch_json_path))
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    payload["batch_id"] = "other-batch"
    batch_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_extraction(
        manifest,
        task_dir,
        inputs,
        mode="local_gpu",
    )

    assert result.valid is False
    assert any("batch_id" in item for item in result.reasons)


def test_input_sha_change_disables_extraction_reuse(
    tmp_path: Path,
) -> None:
    """输入 SHA-256 变化时提取不可复用。"""

    task_dir, manifest, _, inputs = _make_task(tmp_path)
    input_path = Path(inputs[0].source_path)
    input_path.write_text("changed", encoding="utf-8")
    changed_inputs = build_manifest([input_path]).inputs

    result = validate_extraction(
        manifest,
        task_dir,
        changed_inputs,
        mode="local_gpu",
    )

    assert result.valid is False
    assert any("SHA-256 已变化" in item for item in result.reasons)


def test_missing_audit_report_disables_reuse(tmp_path: Path) -> None:
    """审核报告缺失时审核不可复用。"""

    task_dir, manifest, _, _ = _make_task(tmp_path)
    Path(str(manifest.audit_report_json)).unlink()

    result = validate_audit(manifest, task_dir)

    assert result.valid is False
    assert any("审核报告不存在" in item for item in result.reasons)


def test_corrupt_audit_report_disables_reuse(tmp_path: Path) -> None:
    """审核报告损坏时审核不可复用。"""

    task_dir, manifest, _, _ = _make_task(tmp_path)
    Path(str(manifest.audit_report_json)).write_text(
        "{broken",
        encoding="utf-8",
    )

    result = validate_audit(manifest, task_dir)

    assert result.valid is False
    assert any("无法解析" in item for item in result.reasons)


def test_audit_batch_id_mismatch_disables_reuse(tmp_path: Path) -> None:
    """审核报告 batch_id 不匹配时不可以复用。"""

    task_dir, manifest, _, _ = _make_task(tmp_path)
    report_path = Path(str(manifest.audit_report_json))
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["batch_id"] = "other-batch"
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest.audit_report_sha256 = calculate_sha256(report_path)

    result = validate_audit(manifest, task_dir)

    assert result.valid is False
    assert any("batch_id" in item for item in result.reasons)


def test_missing_report_id_disables_reuse(tmp_path: Path) -> None:
    """report_id 缺失时审核不可复用。"""

    task_dir, manifest, _, _ = _make_task(tmp_path)
    report_path = Path(str(manifest.audit_report_json))
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["report_id"] = ""
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest.audit_report_sha256 = calculate_sha256(report_path)

    result = validate_audit(manifest, task_dir)

    assert result.valid is False
    assert any("report_id" in item for item in result.reasons)


def test_missing_audit_markdown_disables_reuse(tmp_path: Path) -> None:
    """审核 Markdown 缺失时审核不可复用。"""

    task_dir, manifest, _, _ = _make_task(tmp_path)
    Path(str(manifest.audit_report_markdown)).unlink()

    result = validate_audit(manifest, task_dir)

    assert result.valid is False
    assert any("Markdown" in item for item in result.reasons)


def test_missing_annotated_file_disables_audit_reuse(
    tmp_path: Path,
) -> None:
    """批注文件缺失时审核不可复用。"""

    task_dir, manifest, _, _ = _make_task(tmp_path, with_annotated=True)
    Path(manifest.annotated_files[0]).unlink()

    result = validate_audit(manifest, task_dir)

    assert result.valid is False
    assert any("批注文件缺失" in item for item in result.reasons)


def test_delivery_sha_change_disables_reuse(tmp_path: Path) -> None:
    """交付文件 SHA-256 变化时交付不可复用。"""

    task_dir, manifest, _, _ = _make_task(tmp_path)
    artifact_path = Path(str(manifest.delivery_report_markdown))
    artifact_path.write_text("changed", encoding="utf-8")

    result = validate_delivery(manifest, task_dir)

    assert result.valid is False
    assert any("SHA-256" in item for item in result.reasons)


def test_missing_delivery_file_disables_reuse(tmp_path: Path) -> None:
    """交付文件缺失时交付不可复用。"""

    task_dir, manifest, _, _ = _make_task(tmp_path)
    Path(str(manifest.delivery_report_markdown)).unlink()

    result = validate_delivery(manifest, task_dir)

    assert result.valid is False
    assert any("缺失" in item for item in result.reasons)
