"""最终交付目录、审核报告汇总和交付清单测试。"""

from __future__ import annotations

import json
from pathlib import Path

from project3_cli_workflow.delivery import run_delivery
from project3_cli_workflow.manifest import (
    calculate_sha256,
    write_manifest,
)
from project3_cli_workflow.models import (
    AUDIT_STATUS_SKIPPED,
    AUDIT_STATUS_SUCCESS,
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_PARTIAL,
    DELIVERY_STATUS_SUCCESS,
    EXTRACTION_STATUS_FAILED,
    EXTRACTION_STATUS_PARTIAL,
    EXTRACTION_STATUS_SUCCESS,
    OVERALL_STATUS_FAILED,
    OVERALL_STATUS_PARTIAL,
    OVERALL_STATUS_SUCCESS,
    InputFile,
    RunManifest,
)


def _base_counts() -> dict[str, int]:
    """返回真实项目二 counts 字段。"""

    return {
        "record_count": 5,
        "verified_count": 0,
        "unverified_count": 5,
        "issue_count": 2,
        "located_count": 2,
        "annotation_applied_count": 1,
        "annotation_failed_count": 0,
        "annotation_manual_review_count": 1,
        "issues_flagged_for_manual_review": 2,
    }


def _base_typo_counts() -> dict[str, int]:
    """返回真实项目二 typo_counts 字段。"""

    return {
        "typo_issue_count": 1,
        "typo_verified_count": 1,
        "typo_manual_review_count": 0,
        "typo_annotation_success_count": 1,
        "typo_annotation_failed_count": 0,
    }


def _write_audit_report(
    audit_root: Path,
    *,
    batch_id: str = "batch-test",
    complete_success: bool = True,
    output_files: list[Path] | None = None,
    omit_optional_fields: bool = False,
    missing_markdown: bool = False,
) -> dict[str, Path]:
    """写入模拟项目二审核报告及关键报告文件。"""

    reports = audit_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / f"audit_report_{batch_id}.json"
    markdown_path = reports / f"audit_report_{batch_id}.md"
    if not missing_markdown:
        markdown_path.write_text("# 审核报告\n", encoding="utf-8")
    annotation_path = reports / f"annotation_report_{batch_id}.json"
    annotation_path.write_text("{}", encoding="utf-8")
    annotation_md_path = reports / f"annotation_report_{batch_id}.md"
    annotation_md_path.write_text("# 批注报告\n", encoding="utf-8")
    math_path = reports / f"{batch_id}_math_validation.json"
    math_path.write_text("{}", encoding="utf-8")

    output_paths = [str(path) for path in (output_files or [])]
    pipeline: dict[str, object] = {
        "complete_success": complete_success,
        "counts": _base_counts(),
    }
    if not omit_optional_fields:
        pipeline.update(
            {
                "typo_counts": _base_typo_counts(),
                "warnings": ["项目二警告"],
                "errors": [],
                "stage_reports": {
                    "audit_json": str(json_path),
                    "audit_markdown": str(markdown_path),
                    "annotation_json": str(annotation_path),
                    "annotation_markdown": str(annotation_md_path),
                    "math_validation": str(math_path),
                },
                "output_files": output_paths,
            }
        )

    payload = {
        "schema_version": "1.0",
        "report_id": "audit-report-test",
        "batch_id": batch_id,
        "generated_at": "2026-11-01T00:00:00+00:00",
        "source_batch": str(
            audit_root.parent
            / "01_extraction"
            / "batches"
            / batch_id
            / "batch.json"
        ),
        "documents": [],
        "summary": {},
        "issues": [],
        "annotations": [],
        "warnings": ["项目二警告"] if not omit_optional_fields else [],
        "metadata": {"pipeline": pipeline},
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "json": json_path,
        "markdown": markdown_path,
        "annotation": annotation_path,
        "annotation_markdown": annotation_md_path,
        "math": math_path,
    }


def _make_task(
    tmp_path: Path,
    *,
    extraction_status: str = EXTRACTION_STATUS_SUCCESS,
    audit_status: str = AUDIT_STATUS_SUCCESS,
    overall_status: str = OVERALL_STATUS_SUCCESS,
    complete_success: bool = True,
    with_annotated: bool = False,
    annotated_exists: bool = True,
    audit_report_exists: bool = True,
    missing_markdown: bool = False,
    omit_optional_fields: bool = False,
) -> tuple[Path, RunManifest, dict[str, Path]]:
    """创建带真实结构报告的任务目录。"""

    task_dir = tmp_path / "任务目录"
    input_path = tmp_path / "企业资料" / "监测报告.docx"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes("原始输入内容".encode())
    batch_path = (
        task_dir
        / "01_extraction"
        / "batches"
        / "batch-test"
        / "batch.json"
    )
    batch_path.parent.mkdir(parents=True)
    batch_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "batch_id": "batch-test",
                "document_count": 1,
                "documents": [],
                "environmental": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    annotated_path = (
        task_dir
        / "02_audit"
        / "annotated"
        / "监测报告_annotated.docx"
    )
    annotated_paths: list[Path] = []
    if with_annotated:
        annotated_paths.append(annotated_path)
        if annotated_exists:
            annotated_path.parent.mkdir(parents=True, exist_ok=True)
            annotated_path.write_bytes("批注后的内容".encode())

    report_paths = _write_audit_report(
        task_dir / "02_audit",
        complete_success=complete_success,
        output_files=annotated_paths,
        missing_markdown=missing_markdown,
        omit_optional_fields=omit_optional_fields,
    )
    if not audit_report_exists:
        report_paths["json"].unlink()

    manifest = RunManifest(
        job_id="job-delivery-test",
        created_at="2026-11-01T00:00:00+00:00",
        inputs=[
            InputFile(
                input_id="input-1",
                source_path=str(input_path.resolve()),
                file_name=input_path.name,
                file_type="docx",
                file_size=input_path.stat().st_size,
                modified_at="2026-11-01T00:00:00+00:00",
                sha256=calculate_sha256(input_path),
            )
        ],
    )
    manifest.extraction_status = extraction_status
    manifest.audit_status = audit_status
    manifest.overall_status = overall_status
    manifest.batch_id = "batch-test"
    manifest.batch_json_path = str(batch_path.resolve())
    manifest.document_count = 1
    manifest.successful_document_count = 1
    manifest.failed_document_count = 0
    manifest.audit_report_json = str(report_paths["json"].resolve())
    manifest.audit_report_markdown = str(
        report_paths["markdown"].resolve()
    )
    manifest.annotation_report = str(
        report_paths["annotation"].resolve()
    )
    manifest.math_validation_report = str(
        report_paths["math"].resolve()
    )
    manifest.annotated_files = [
        str(path.resolve()) for path in annotated_paths
    ]
    manifest.audit_complete_success = complete_success
    manifest.audit_issue_count = 2
    manifest.audit_unverified_count = 5
    manifest.audit_manual_review_count = 1
    manifest.audit_warning_count = 1
    manifest_path = task_dir / "manifest.json"
    write_manifest(manifest, manifest_path)
    return task_dir, manifest, report_paths


def _load_json(path: Path) -> dict[str, object]:
    """读取 JSON 文件。"""

    return json.loads(path.read_text(encoding="utf-8"))


def test_delivery_success_and_report_summary(tmp_path: Path) -> None:
    """正常任务应生成完整交付目录和真实计数报告。"""

    task_dir, manifest, _ = _make_task(tmp_path, with_annotated=True)

    result = run_delivery(manifest, task_dir / "manifest.json")

    assert result.status == DELIVERY_STATUS_SUCCESS
    assert result.overall_status == OVERALL_STATUS_SUCCESS
    assert result.directory == task_dir / "03_delivery"
    assert result.report_json is not None
    assert result.report_json.is_file()
    assert result.report_markdown is not None
    assert result.report_markdown.is_file()
    assert result.summary_markdown.is_file()
    assert result.delivery_manifest_json.is_file()

    report = _load_json(result.report_json)
    assert report["job_id"] == "job-delivery-test"
    assert report["batch_id"] == "batch-test"
    assert report["report_id"] == "audit-report-test"
    assert report["extraction_document_count"] == 1
    assert report["extraction_successful_document_count"] == 1
    assert report["audit_record_count"] == 5
    assert report["verified_count"] == 0
    assert report["unverified_count"] == 5
    assert report["issue_count"] == 2
    assert report["annotation_manual_review_count"] == 1
    assert report["typo_issue_count"] == 1
    assert report["annotated_files"] == [
        str(Path("03_delivery") / "批注文件" / "监测报告_annotated.docx")
    ]
    assert report["data_source"]

    markdown = result.report_markdown.read_text(encoding="utf-8")
    assert "# 审核报告汇总" in markdown
    assert "unverified" in markdown
    assert "不代表所有数据合规" in markdown
    assert "manual_review" in markdown


def test_delivery_missing_optional_report_fields(tmp_path: Path) -> None:
    """缺少可选报告字段时使用空值或空数组，不伪造计数。"""

    task_dir, manifest, _ = _make_task(
        tmp_path,
        omit_optional_fields=True,
    )

    result = run_delivery(manifest, task_dir / "manifest.json")

    assert result.status == DELIVERY_STATUS_SUCCESS
    assert result.report_json is not None
    report = _load_json(result.report_json)
    assert report["typo_issue_count"] is None
    assert report["typo_verified_count"] is None
    assert report["warnings"] == []
    assert report["errors"] == []
    assert report["annotated_files"] == []


def test_delivery_missing_audit_report_does_not_fake_summary(
    tmp_path: Path,
) -> None:
    """审核报告缺失时交付失败，不生成伪造审核报告。"""

    task_dir, manifest, _ = _make_task(
        tmp_path,
        audit_report_exists=False,
        overall_status=OVERALL_STATUS_FAILED,
        audit_status=AUDIT_STATUS_SKIPPED,
    )

    result = run_delivery(manifest, task_dir / "manifest.json")

    assert result.status == DELIVERY_STATUS_FAILED
    assert result.overall_status == OVERALL_STATUS_FAILED
    assert result.report_json is None
    assert result.report_markdown is None
    assert result.summary_markdown.is_file()
    assert result.delivery_manifest_json.is_file()
    assert not (result.directory / "审核报告.json").exists()
    assert result.error


def test_delivery_missing_markdown_marks_partial(tmp_path: Path) -> None:
    """审核 Markdown 缺失时交付不完整。"""

    task_dir, manifest, _ = _make_task(tmp_path, missing_markdown=True)

    result = run_delivery(manifest, task_dir / "manifest.json")

    assert result.status == DELIVERY_STATUS_PARTIAL
    assert result.overall_status == OVERALL_STATUS_PARTIAL
    assert any("markdown" in item.name for item in result.missing_artifacts)


def test_delivery_copies_annotated_and_checks_sha(tmp_path: Path) -> None:
    """批注文件应复制成功，源文件保留且 SHA-256 一致。"""

    task_dir, manifest, _ = _make_task(tmp_path, with_annotated=True)
    source = Path(manifest.annotated_files[0])
    source_before = source.read_bytes()
    source_sha = calculate_sha256(source)

    result = run_delivery(manifest, task_dir / "manifest.json")

    destination = task_dir / "03_delivery" / "批注文件" / source.name
    assert destination.is_file()
    assert calculate_sha256(destination) == source_sha
    assert source.read_bytes() == source_before
    assert source.is_file()

    delivery_manifest = _load_json(result.delivery_manifest_json)
    artifact = next(
        item
        for item in delivery_manifest["artifacts"]
        if item["type"] == "annotated_file"
    )
    assert artifact["sha256"] == source_sha
    assert artifact["size"] == source.stat().st_size


def test_delivery_missing_annotated_marks_partial(tmp_path: Path) -> None:
    """报告声明但实际缺失的批注文件应记录，不静默忽略。"""

    task_dir, manifest, _ = _make_task(
        tmp_path,
        with_annotated=True,
        annotated_exists=False,
    )

    result = run_delivery(manifest, task_dir / "manifest.json")

    assert result.status == DELIVERY_STATUS_PARTIAL
    assert len(result.missing_artifacts) == 1
    assert result.missing_artifacts[0].type == "annotated_file"
    assert "不存在" in result.missing_artifacts[0].reason
    delivery_manifest = _load_json(result.delivery_manifest_json)
    assert delivery_manifest["missing_artifacts"]


def test_delivery_no_annotated_files_records_empty_directory(
    tmp_path: Path,
) -> None:
    """没有批注文件时目录为空并在清单中明确记录。"""

    task_dir, manifest, _ = _make_task(tmp_path)

    result = run_delivery(manifest, task_dir / "manifest.json")

    assert result.status == DELIVERY_STATUS_SUCCESS
    annotated_dir = result.directory / "批注文件"
    assert annotated_dir.is_dir()
    assert list(annotated_dir.iterdir()) == []
    assert any("批注文件为空" in item for item in result.warnings)


def test_delivery_extraction_partial_stays_partial(tmp_path: Path) -> None:
    """extraction_partial 时整体状态不能变成 success。"""

    task_dir, manifest, _ = _make_task(
        tmp_path,
        extraction_status=EXTRACTION_STATUS_PARTIAL,
        overall_status=OVERALL_STATUS_PARTIAL,
    )

    result = run_delivery(manifest, task_dir / "manifest.json")

    assert result.status == DELIVERY_STATUS_SUCCESS
    assert result.overall_status == OVERALL_STATUS_PARTIAL
    summary = result.summary_markdown.read_text(encoding="utf-8")
    assert "extraction_partial" in summary


def test_delivery_audit_partial_stays_partial(tmp_path: Path) -> None:
    """audit_partial 时整体状态不能变成 success。"""

    task_dir, manifest, _ = _make_task(
        tmp_path,
        audit_status="audit_partial",
        overall_status=OVERALL_STATUS_PARTIAL,
        complete_success=False,
    )

    result = run_delivery(manifest, task_dir / "manifest.json")

    assert result.status == DELIVERY_STATUS_SUCCESS
    assert result.overall_status == OVERALL_STATUS_PARTIAL


def test_delivery_extraction_failed_creates_no_audit_report(
    tmp_path: Path,
) -> None:
    """提取失败任务不得伪造审核报告。"""

    task_dir, manifest, _ = _make_task(
        tmp_path,
        extraction_status=EXTRACTION_STATUS_FAILED,
        audit_status=AUDIT_STATUS_SKIPPED,
        overall_status=OVERALL_STATUS_FAILED,
        audit_report_exists=False,
    )

    result = run_delivery(manifest, task_dir / "manifest.json")

    assert result.status == DELIVERY_STATUS_FAILED
    assert result.report_json is None
    assert not (result.directory / "审核报告.md").exists()
    assert not (result.directory / "审核报告.json").exists()
    delivery_manifest = _load_json(result.delivery_manifest_json)
    assert any(
        item["type"] == "audit_report"
        for item in delivery_manifest["missing_artifacts"]
    )


def test_delivery_manifest_fields_and_sha(tmp_path: Path) -> None:
    """交付清单应记录相对路径、类型、大小、SHA-256 和缺失项。"""

    task_dir, manifest, _ = _make_task(tmp_path, with_annotated=True)

    result = run_delivery(manifest, task_dir / "manifest.json")
    delivery_manifest = _load_json(result.delivery_manifest_json)

    assert delivery_manifest["schema_version"] == "1.0"
    assert delivery_manifest["job_id"] == "job-delivery-test"
    assert delivery_manifest["overall_status"] == "success"
    assert delivery_manifest["delivery_status"] == "delivery_success"
    assert delivery_manifest["missing_artifacts"] == []
    assert delivery_manifest["artifacts"]
    for artifact in delivery_manifest["artifacts"]:
        path = task_dir / artifact["path"]
        assert path.is_file()
        assert artifact["exists"] is True
        assert artifact["size"] == path.stat().st_size
        assert artifact["sha256"] == calculate_sha256(path)


def test_delivery_does_not_modify_original_inputs(tmp_path: Path) -> None:
    """交付整理不得修改原始输入文件。"""

    task_dir, manifest, _ = _make_task(tmp_path)
    input_path = Path(manifest.inputs[0].source_path)
    before = input_path.read_bytes()

    run_delivery(manifest, task_dir / "manifest.json")

    assert input_path.read_bytes() == before


def test_delivery_repeated_generation_keeps_intermediate_outputs(
    tmp_path: Path,
) -> None:
    """重复生成交付文件不得破坏项目一、项目二中间产物。"""

    task_dir, manifest, _ = _make_task(tmp_path, with_annotated=True)
    batch_path = Path(str(manifest.batch_json_path))
    audit_path = Path(str(manifest.audit_report_json))
    batch_sha = calculate_sha256(batch_path)
    audit_sha = calculate_sha256(audit_path)

    first = run_delivery(manifest, task_dir / "manifest.json")
    second = run_delivery(manifest, task_dir / "manifest.json")

    assert first.status == DELIVERY_STATUS_SUCCESS
    assert second.status == DELIVERY_STATUS_SUCCESS
    assert batch_path.is_file()
    assert audit_path.is_file()
    assert calculate_sha256(batch_path) == batch_sha
    assert calculate_sha256(audit_path) == audit_sha
    assert not (task_dir / ".03_delivery_staging").exists()
