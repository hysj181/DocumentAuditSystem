from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

from doc_extractor.core.exporters import export_excel, export_json, export_markdown
from doc_extractor.core.extraction_batch import ExtractionBatch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output"
OUTPUT_ENV_VAR = "DOC_EXTRACTOR_OUTPUT_DIR"
OUTPUT_SUBDIRS = ("json", "excel", "markdown", "batches")
EXPORT_FORMATS = ("json", "excel", "markdown")


def resolve_output_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root).expanduser().resolve()
    configured = os.environ.get(OUTPUT_ENV_VAR, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_OUTPUT_ROOT.resolve()


def ensure_output_layout(root: str | Path | None = None) -> dict[str, Path]:
    output_root = resolve_output_root(root)
    layout = {"root": output_root}
    for name in OUTPUT_SUBDIRS:
        directory = output_root / name
        directory.mkdir(parents=True, exist_ok=True)
        layout[name] = directory
    return layout


def _safe_batch_name(batch_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(batch_id)).strip("._")
    return (safe or "batch")[:120]


def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    index = 1
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _unique_directory(parent: Path, name: str) -> Path:
    candidate = parent / name
    if not candidate.exists():
        return candidate
    index = 1
    while True:
        candidate = parent / f"{name}_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def save_batch(
    batch: ExtractionBatch,
    root: str | Path | None = None,
    formats: Iterable[str] = EXPORT_FORMATS,
) -> dict[str, Path]:
    layout = ensure_output_layout(root)
    if isinstance(formats, str):
        formats = (formats,)
    normalized_formats = tuple(dict.fromkeys(str(item).lower() for item in formats))
    unknown = [item for item in normalized_formats if item not in EXPORT_FORMATS]
    if unknown:
        raise ValueError(f"不支持的导出格式：{', '.join(unknown)}")

    outputs: dict[str, Path] = {}
    batch_name = _safe_batch_name(batch.batch_id)

    batch_directory = _unique_directory(layout["batches"], batch_name)
    batch_directory.mkdir(parents=True, exist_ok=False)
    batch_path = batch_directory / "batch.json"
    outputs["batch"] = export_json(
        batch.documents,
        batch_path,
        batch.environmental,
        batch_id=batch.batch_id,
        extracted_at=batch.extracted_at,
    )

    if "json" in normalized_formats:
        json_path = _unique_path(layout["json"], batch_name, ".json")
        outputs["json"] = export_json(
            batch.documents,
            json_path,
            batch.environmental,
            batch_id=batch.batch_id,
            extracted_at=batch.extracted_at,
        )

    if "excel" in normalized_formats:
        excel_path = _unique_path(layout["excel"], batch_name, ".xlsx")
        outputs["excel"] = export_excel(
            batch.documents,
            excel_path,
            batch.environmental,
        )

    if "markdown" in normalized_formats:
        markdown_path = _unique_path(layout["markdown"], batch_name, ".md")
        outputs["markdown"] = export_markdown(
            batch.documents,
            markdown_path,
            batch.environmental,
            batch_id=batch.batch_id,
            extracted_at=batch.extracted_at,
        )

    return outputs


def export_batch(
    batch: ExtractionBatch,
    output_format: str,
    root: str | Path | None = None,
    path: str | Path | None = None,
) -> Path:
    output_format = str(output_format).lower()
    if output_format not in EXPORT_FORMATS:
        raise ValueError(f"不支持的导出格式：{output_format}")

    layout = ensure_output_layout(root)
    if path is not None:
        target = Path(path).expanduser()
        if target.suffix == "":
            target = target.with_suffix(f".{output_format}")
        if target.exists():
            target = _unique_path(
                target.parent.resolve(), target.stem, target.suffix
            )
    else:
        suffix = {"json": ".json", "excel": ".xlsx", "markdown": ".md"}[
            output_format
        ]
        target = _unique_path(
            layout[output_format],
            _safe_batch_name(batch.batch_id),
            suffix,
        )

    if output_format == "json":
        return export_json(
            batch.documents,
            target,
            batch.environmental,
            batch_id=batch.batch_id,
            extracted_at=batch.extracted_at,
        )
    if output_format == "excel":
        return export_excel(batch.documents, target, batch.environmental)
    return export_markdown(
        batch.documents,
        target,
        batch.environmental,
        batch_id=batch.batch_id,
        extracted_at=batch.extracted_at,
    )


def load_batch(path: str | Path) -> ExtractionBatch:
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
        raise ValueError(f"不是有效的批次 JSON 文件：{source}")
    return ExtractionBatch.from_dict(payload)


def restore_batch(path: str | Path) -> ExtractionBatch:
    return load_batch(path)


def list_batch_files(root: str | Path | None = None) -> list[Path]:
    layout = ensure_output_layout(root)
    files = list(layout["batches"].glob("*/batch.json"))
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files


def find_batch_file(
    batch_id: str,
    root: str | Path | None = None,
) -> Path | None:
    layout = ensure_output_layout(root)
    direct = layout["batches"] / _safe_batch_name(batch_id) / "batch.json"
    if direct.is_file():
        return direct
    for candidate in layout["batches"].glob("*/batch.json"):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("batch_id", "")) == batch_id:
            return candidate
    return None


def load_batch_by_id(
    batch_id: str,
    root: str | Path | None = None,
) -> ExtractionBatch:
    path = find_batch_file(batch_id, root)
    if path is None:
        raise FileNotFoundError(f"未找到批次：{batch_id}")
    return load_batch(path)


def load_latest_batch(root: str | Path | None = None) -> ExtractionBatch:
    files = list_batch_files(root)
    if not files:
        raise FileNotFoundError("没有可用的批次，请先执行 extract。")
    return load_batch(files[0])
