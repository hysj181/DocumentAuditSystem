"""Command-line entry point for the Word document audit tool."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from word_audit import __version__
from word_audit.config import resolve_output_root
from word_audit.math_audit import save_validation_result, validate_batch
from word_audit.pipeline import PipelineInputError, run_audit
from word_audit.project1_batch import Project1Batch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="word-audit",
        description="Word document mathematical audit and annotation tool.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser(
        "validate-batch",
        help="Validate calculation content in a project one batch JSON.",
    )
    validate_parser.add_argument(
        "--batch-json",
        required=True,
        help="Path to project one output/batches/<batch_id>/batch.json.",
    )
    validate_parser.add_argument(
        "--output",
        default=None,
        help=(
            "Validation report path. Defaults to "
            "output/reports/<batch_id>_math_validation.json."
        ),
    )

    audit_parser = subparsers.add_parser(
        "audit",
        help="Run the complete audit pipeline for one project one batch JSON.",
        description=(
            "Run the complete read-only audit flow: load a project one batch "
            "JSON, validate calculations, locate issues, write Word comments "
            "or PDF markers to copies, and export JSON/Markdown reports."
        ),
        epilog=(
            "Example:\n"
            "  uv run python main.py audit "
            "--batch-json \"output\\\\batches\\\\<batch_id>\\\\batch.json\" "
            "--output-dir \"output\""
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    audit_parser.add_argument(
        "--batch-json",
        required=True,
        help="Path to project one output/batches/<batch_id>/batch.json.",
    )
    audit_parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Output root directory. Reports go to <output-dir>/reports and "
            "annotated files to <output-dir>/annotated. Default: the "
            "project's output directory."
        ),
    )
    return parser


def run_audit_command(args: argparse.Namespace) -> int:
    try:
        result = run_audit(args.batch_json, args.output_dir)
    except PipelineInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"file/output error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"audit pipeline failed: {exc}", file=sys.stderr)
        return 1

    pipeline = result.report.metadata.get("pipeline", {})
    counts = pipeline.get("counts", {})
    print(f"batch_id: {result.report.batch_id}")
    print(f"complete_success: {pipeline.get('complete_success')}")
    print(f"synthetic_data: {pipeline.get('synthetic_data')}")
    print(f"records: {counts.get('record_count', 0)}")
    print(f"verified: {counts.get('verified_count', 0)}")
    print(f"unverified: {counts.get('unverified_count', 0)}")
    print(f"issues: {counts.get('issue_count', 0)}")
    print(f"located: {counts.get('located_count', 0)}")
    print(f"annotations_applied: {counts.get('annotation_applied_count', 0)}")
    print(f"annotations_failed: {counts.get('annotation_failed_count', 0)}")
    print(
        "annotations_manual_review: "
        f"{counts.get('annotation_manual_review_count', 0)}"
    )
    print(
        "issues_flagged_for_manual_review: "
        f"{counts.get('issues_flagged_for_manual_review', 0)}"
    )
    typo_counts = pipeline.get("typo_counts", {})
    print(f"typo_issues: {typo_counts.get('typo_issue_count', 0)}")
    print(f"typo_verified: {typo_counts.get('typo_verified_count', 0)}")
    print(
        "typo_manual_review: "
        f"{typo_counts.get('typo_manual_review_count', 0)}"
    )
    print(
        "typo_annotations_applied: "
        f"{typo_counts.get('typo_annotation_success_count', 0)}"
    )
    print(
        "typo_annotations_failed: "
        f"{typo_counts.get('typo_annotation_failed_count', 0)}"
    )
    print(f"audit_report_json: {result.audit_json_path}")
    print(f"audit_report_markdown: {result.audit_markdown_path}")
    print(f"math_validation_report: {result.math_validation_path}")
    for path in result.output_files:
        print(f"annotated_file: {path}")
    for warning in pipeline.get("warnings", []):
        print(f"warning: {warning}")
    return 0


def run_validate_batch(args: argparse.Namespace) -> int:
    batch = Project1Batch.load(args.batch_json)
    result = validate_batch(batch)
    output = (
        Path(args.output)
        if args.output
        else resolve_output_root()
        / "reports"
        / f"{batch.batch_id}_math_validation.json"
    )
    saved = save_validation_result(result, output)
    summary = result.summary()
    print(f"batch_id: {result.batch_id}")
    print(f"records: {summary['record_count']}")
    print(f"verified: {summary['verified_count']}")
    print(f"unverified: {summary['unverified_count']}")
    print(f"errors: {summary['error_count']}")
    print(f"issues: {summary['issue_count']}")
    print(f"value cells mapped: {summary['value_cell_mapped_count']}")
    print(f"expressions detected: {summary['expression_count']}")
    print(f"report: {saved}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "audit":
        return run_audit_command(args)
    if args.command == "validate-batch":
        return run_validate_batch(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
