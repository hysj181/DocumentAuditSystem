from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doc_extractor.core.environmental_common import normalize_unit
from doc_extractor.core.environmental_models import (
    ENV_CATEGORY_LABELS,
    FLAG_DETECTION_LIMIT,
    FLAG_MISSING_VALUE,
    EnvironmentalRecord,
)
from doc_extractor.core.environmental_pipeline import extract_batch
from doc_extractor.core.extraction_batch import ExtractionBatch
from doc_extractor.core.models import Location, format_location

TEST_DATA_DIR = ROOT / "test_data"
DOCUMENT_SUFFIXES = {".docx", ".pdf"}

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "source_file": ("来源文件", "源文件", "文件", "文件名"),
    "enterprise_name": ("企业名称", "企业", "单位名称"),
    "category": ("数据类别", "类别", "数据分类"),
    "point": ("监测点位/范围", "监测点位", "点位", "范围"),
    "indicator": ("指标", "指标名称", "监测项目", "项目"),
    "raw_value": ("原始值", "数值", "值", "记录值"),
    "unit": ("单位",),
    "location_hint": ("预期位置提示", "位置提示", "预期位置", "位置"),
    "note": ("说明", "备注"),
}

ND_MARKERS = {"ND", "N.D.", "N.D", "未检出"}
MISSING_MARKERS = {"—", "–", "－", "-", "N/A", "NA"}
INDICATOR_ALIASES = {
    "治理设施运行时间": "设施运行时间",
}


@dataclass
class StandardAnswer:
    row_number: int
    source_file: str
    enterprise_name: str
    category: str
    point: str
    indicator: str
    raw_value: str
    unit: str
    location_hint: str
    note: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComparisonRow:
    standard: StandardAnswer | None
    actual: EnvironmentalRecord | None
    status: str
    notes: list[str] = field(default_factory=list)
    candidate_count: int = 0
    location_hint_ok: bool | None = None


@dataclass
class Evaluation:
    batch: ExtractionBatch
    document_files: list[Path]
    standard_file: Path
    standard_sheet: str
    standard_headers: list[str]
    standard_rows: list[StandardAnswer]
    comparisons: list[ComparisonRow]
    extras: list[EnvironmentalRecord]
    metrics: dict[str, Any]
    enterprise_warnings: list[str]

    @property
    def matched_comparisons(self) -> list[ComparisonRow]:
        return [row for row in self.comparisons if row.status == "正确匹配"]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", _text(value))
    return re.sub(r"\s+", "", normalized)


def normalize_point(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", _text(value))
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_label(value: Any) -> str:
    return unicodedata.normalize("NFKC", _text(value)).replace(" ", "")


def canonical_unit(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", _text(value))
    return normalize_unit(normalized) or ""


def normalize_indicator(value: Any) -> str:
    normalized = normalize_label(value)
    return INDICATOR_ALIASES.get(normalized, normalized)


def list_test_documents() -> list[Path]:
    if not TEST_DATA_DIR.is_dir():
        raise FileNotFoundError(f"测试数据目录不存在: {TEST_DATA_DIR}")
    return sorted(
        path
        for path in TEST_DATA_DIR.iterdir()
        if path.is_file() and path.suffix.casefold() in DOCUMENT_SUFFIXES
    )


def list_test_data_files() -> list[Path]:
    if not TEST_DATA_DIR.is_dir():
        return []
    return sorted(path for path in TEST_DATA_DIR.iterdir() if path.is_file())


def find_standard_workbook() -> Path:
    candidates = sorted(TEST_DATA_DIR.glob("*.xlsx"))
    if not candidates:
        raise FileNotFoundError("未找到标准答案 Excel 文件")
    for candidate in candidates:
        try:
            workbook = load_workbook(candidate, data_only=True, read_only=True)
        except Exception:
            continue
        try:
            for worksheet in workbook.worksheets:
                if _find_header_row(worksheet) is not None:
                    return candidate
        finally:
            workbook.close()
    raise ValueError("未找到包含标准答案字段的工作簿")


def _find_header_row(worksheet) -> tuple[int, list[str]] | None:
    max_row = worksheet.max_row or 8
    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=1, max_row=min(max_row, 8), values_only=True),
        start=1,
    ):
        headers = [_text(value) for value in row]
        if all(
            any(alias in headers for alias in aliases)
            for aliases in (
                HEADER_ALIASES["source_file"],
                HEADER_ALIASES["indicator"],
                HEADER_ALIASES["raw_value"],
                HEADER_ALIASES["unit"],
            )
        ):
            return row_index, headers
    return None


def _header_map(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in headers:
                mapping[key] = alias
                break
    return mapping


def load_standard_answers(
    path: Path | None = None,
) -> tuple[Path, str, list[str], list[StandardAnswer]]:
    standard_path = path or find_standard_workbook()
    workbook = load_workbook(standard_path, data_only=True, read_only=True)
    try:
        for worksheet in workbook.worksheets:
            header_info = _find_header_row(worksheet)
            if header_info is None:
                continue
            header_row, headers = header_info
            mapping = _header_map(headers)
            rows: list[StandardAnswer] = []
            for row_number, values in enumerate(
                worksheet.iter_rows(min_row=header_row + 1, values_only=True),
                start=header_row + 1,
            ):
                raw = {
                    header: values[index] if index < len(values) else None
                    for index, header in enumerate(headers)
                }
                source_file = _text(values[headers.index(mapping["source_file"])])
                indicator = _text(values[headers.index(mapping["indicator"])])
                if not source_file and not indicator:
                    continue
                rows.append(
                    StandardAnswer(
                        row_number=row_number,
                        source_file=source_file,
                        enterprise_name=_text(
                            values[headers.index(mapping["enterprise_name"])]
                        )
                        if "enterprise_name" in mapping
                        else "",
                        category=_text(values[headers.index(mapping["category"])])
                        if "category" in mapping
                        else "",
                        point=_text(values[headers.index(mapping["point"])])
                        if "point" in mapping
                        else "",
                        indicator=indicator,
                        raw_value=_text(values[headers.index(mapping["raw_value"])]),
                        unit=_text(values[headers.index(mapping["unit"])]),
                        location_hint=_text(
                            values[headers.index(mapping["location_hint"])]
                        )
                        if "location_hint" in mapping
                        else "",
                        note=_text(values[headers.index(mapping["note"])])
                        if "note" in mapping
                        else "",
                        raw=raw,
                    )
                )
            return standard_path, worksheet.title, headers, rows
    finally:
        workbook.close()
    raise ValueError("标准答案工作簿没有可识别的数据表")


def _parse_number(value: Any) -> float | None:
    text = _text(value).replace(",", "").replace(" ", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _special_value_note(standard_value: str) -> str | None:
    upper = standard_value.upper()
    if upper in ND_MARKERS or standard_value in ND_MARKERS:
        return "检出限/未检出表达保留为空值，未转换为0"
    if standard_value in MISSING_MARKERS:
        return "缺失值保留为空值，未转换为0"
    if standard_value.startswith(("<", "≤")):
        return "低于检出限表达保留为空值，未转换为0"
    return None


def value_equivalent(standard_value: str, actual: EnvironmentalRecord, notes: list[str]) -> bool:
    standard_value = _text(standard_value)
    upper = standard_value.upper()
    raw_text = f"{actual.raw_expression}\n{actual.source_text}"
    detection_text = _text(actual.detection_limit)

    if upper in ND_MARKERS or standard_value in ND_MARKERS:
        note = _special_value_note(standard_value)
        if note:
            notes.append(note)
        return (
            actual.value is None
            and (
                detection_text.upper() in ND_MARKERS
                or any(marker in raw_text for marker in ND_MARKERS)
            )
        )

    if standard_value.startswith(("<", "≤")):
        note = _special_value_note(standard_value)
        if note:
            notes.append(note)
        compact_standard = standard_value.replace(" ", "")
        compact_detection = detection_text.replace(" ", "")
        return (
            actual.value is None
            and (
                compact_standard in compact_detection
                or compact_standard in raw_text.replace(" ", "")
            )
        )

    if standard_value in MISSING_MARKERS or standard_value == "":
        note = _special_value_note(standard_value)
        if note:
            notes.append(note)
        has_marker = any(marker in raw_text for marker in (standard_value, "—", "–", "－"))
        return actual.value is None and (
            has_marker
            or FLAG_MISSING_VALUE in actual.flags
            or FLAG_DETECTION_LIMIT in actual.flags
        )

    standard_number = _parse_number(standard_value)
    if standard_number is not None:
        actual_number = _parse_number(actual.value)
        return (
            actual.value is not None
            and actual_number is not None
            and abs(standard_number - actual_number) <= 1e-9
        )

    return normalize_label(standard_value) == normalize_label(actual.value)


def _enterprise_equivalent(
    standard_name: str,
    actual: EnvironmentalRecord,
    notes: list[str],
) -> bool:
    if not standard_name:
        return True
    normalized_standard = normalize_name(standard_name)
    normalized_actual = normalize_name(actual.enterprise_name)
    if normalized_standard != normalized_actual:
        return False
    if _text(standard_name) != _text(actual.enterprise_name):
        notes.append("企业名称全角/半角及空白规范化后一致")
    return True


def _point_equivalent(
    standard_point: str,
    actual: EnvironmentalRecord,
    notes: list[str],
) -> bool:
    normalized = normalize_point(standard_point)
    if not normalized or "见原文" in normalized or normalized in {"企业年度汇总"}:
        notes.append("标准点位为“见原文/企业年度汇总”，未作为具体点位硬性核对")
        return True
    actual_point = normalize_point(actual.point)
    return bool(actual_point) and actual_point == normalized


def _location_hint_match(
    hint: str,
    actual: EnvironmentalRecord,
) -> bool | None:
    text = normalize_point(hint)
    if not text:
        return None
    table_match = re.search(r"表格\s*(\d+).*?第\s*(\d+)\s*行", text)
    if table_match:
        expected_table = int(table_match.group(1)) - 1
        expected_row = int(table_match.group(2)) - 1
        return (
            actual.source_location.get("table_index") == expected_table
            and actual.source_location.get("row_index") == expected_row
        )
    page_match = re.search(r"第\s*(\d+)\s*页", text)
    if page_match:
        return actual.source_location.get("page_number") == int(page_match.group(1))
    return None


def _core_match(
    standard: StandardAnswer,
    actual: EnvironmentalRecord,
    notes: list[str],
) -> bool:
    if Path(actual.source_file).name != standard.source_file:
        return False
    if not _enterprise_equivalent(standard.enterprise_name, actual, notes):
        return False
    actual_category = ENV_CATEGORY_LABELS.get(actual.category, actual.category)
    if normalize_label(actual_category) != normalize_label(standard.category):
        return False
    if normalize_indicator(actual.indicator) != normalize_indicator(standard.indicator):
        return False
    if not value_equivalent(standard.raw_value, actual, notes):
        return False
    if canonical_unit(actual.unit) != canonical_unit(standard.unit):
        return False
    if not _point_equivalent(standard.point, actual, notes):
        return False
    return True


def _record_summary(record: EnvironmentalRecord) -> str:
    location = format_location(Location.from_dict(record.source_location))
    return (
        f"{record.record_id} | {Path(record.source_file).name} | "
        f"{record.indicator} | {record.value} | {record.unit} | "
        f"{record.time} | {record.point} | {location}"
    )


def compare_standard_answers(
    batch: ExtractionBatch,
    standard_rows: list[StandardAnswer],
) -> tuple[list[ComparisonRow], list[EnvironmentalRecord], dict[str, Any]]:
    actual_records = list(batch.environmental.records)
    available = list(range(len(actual_records)))
    used_actual: set[int] = set()
    comparisons: list[ComparisonRow] = []

    for standard in standard_rows:
        candidate_indices: list[int] = []
        candidate_notes: dict[int, list[str]] = {}
        for index, actual in enumerate(actual_records):
            notes: list[str] = []
            if _core_match(standard, actual, notes):
                candidate_indices.append(index)
                candidate_notes[index] = notes

        unused_candidates = [index for index in candidate_indices if index not in used_actual]
        location_matches = [
            index
            for index in unused_candidates
            if _location_hint_match(standard.location_hint, actual_records[index]) is True
        ]

        if len(candidate_indices) == 1 and unused_candidates:
            index = unused_candidates[0]
        elif len(candidate_indices) > 1 and len(location_matches) == 1:
            index = location_matches[0]
        elif len(candidate_indices) > 1 and unused_candidates:
            comparisons.append(
                ComparisonRow(
                    standard=standard,
                    actual=None,
                    status="无法可靠匹配（多个候选）",
                    notes=[
                        "存在多个候选提取记录，未强行判定",
                        *[
                            _record_summary(actual_records[index])
                            for index in unused_candidates
                        ],
                    ],
                    candidate_count=len(candidate_indices),
                )
            )
            continue
        elif candidate_indices and not unused_candidates:
            comparisons.append(
                ComparisonRow(
                    standard=standard,
                    actual=None,
                    status="重复匹配冲突",
                    notes=[
                        "所有候选记录已被其他标准记录占用，未强行判定",
                        *[
                            _record_summary(actual_records[index])
                            for index in candidate_indices
                        ],
                    ],
                    candidate_count=len(candidate_indices),
                )
            )
            continue
        else:
            comparisons.append(
                ComparisonRow(
                    standard=standard,
                    actual=None,
                    status="漏提取",
                    notes=["未找到同时满足来源文件、企业、类别、指标、值、单位及必要点位的记录"],
                )
            )
            continue

        used_actual.add(index)
        actual = actual_records[index]
        notes = list(candidate_notes.get(index, []))
        if len(candidate_indices) > 1:
            notes.append("存在多个候选，已按位置提示唯一确定")
        location_ok = _location_hint_match(standard.location_hint, actual)
        if location_ok is True:
            notes.append("预期位置提示与实际来源位置一致")
        elif location_ok is False:
            notes.append("预期位置提示与实际来源位置不一致，请人工核对")
        comparisons.append(
            ComparisonRow(
                standard=standard,
                actual=actual,
                status="正确匹配",
                notes=list(dict.fromkeys(notes)),
                candidate_count=len(candidate_indices),
                location_hint_ok=location_ok,
            )
        )

    extras = [actual_records[index] for index in available if index not in used_actual]
    for extra in extras:
        comparisons.append(
            ComparisonRow(
                standard=None,
                actual=extra,
                status="多余/未匹配提取",
                notes=["提取记录未匹配到任何标准答案记录"],
            )
        )

    matched = sum(1 for row in comparisons if row.status == "正确匹配")
    ambiguous = sum(
        1 for row in comparisons if row.status.startswith("无法可靠匹配")
    )
    missed = sum(1 for row in comparisons if row.status == "漏提取")
    conflicts = sum(1 for row in comparisons if row.status == "重复匹配冲突")
    standard_total = len(standard_rows)
    actual_total = len(actual_records)

    metrics = {
        "standard_total": standard_total,
        "actual_total": actual_total,
        "matched": matched,
        "ambiguous": ambiguous,
        "missed": missed,
        "conflicts": conflicts,
        "extra": len(extras),
        "recall": matched / standard_total if standard_total else 0.0,
        "precision": matched / actual_total if actual_total else 0.0,
        "location_hint_mismatches": sum(
            1 for row in comparisons if row.location_hint_ok is False
        ),
        "non_literal_point_rows": sum(
            1
            for row in comparisons
            if row.actual is not None
            and any("见原文/企业年度汇总" in note for note in row.notes)
        ),
    }
    return comparisons, extras, metrics


def run_evaluation() -> Evaluation:
    document_files = list_test_documents()
    if not document_files:
        raise FileNotFoundError("test_data 中没有 Word/PDF 测试文件")
    batch = extract_batch(document_files)
    standard_file, sheet_name, headers, standard_rows = load_standard_answers()
    comparisons, extras, metrics = compare_standard_answers(batch, standard_rows)
    return Evaluation(
        batch=batch,
        document_files=document_files,
        standard_file=standard_file,
        standard_sheet=sheet_name,
        standard_headers=headers,
        standard_rows=standard_rows,
        comparisons=comparisons,
        extras=extras,
        metrics=metrics,
        enterprise_warnings=batch.environmental.warnings,
    )


def _clean_excel(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    text = "".join(
        character for character in text if character in "\n\t" or ord(character) >= 32
    )
    if len(text) > 32767:
        text = text[:32764] + "..."
    return text


def _style_sheet(worksheet, widths: list[int]) -> None:
    fill = PatternFill("solid", fgColor="D9E2F3")
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
    worksheet.freeze_panes = "A2"
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width
    worksheet.auto_filter.ref = worksheet.dimensions


def write_comparison_excel(evaluation: Evaluation, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()

    summary = workbook.active
    summary.title = "测试汇总"
    summary.append(["项目", "值"])
    metrics = evaluation.metrics
    summary_rows = [
        ("标准答案文件", evaluation.standard_file.name),
        ("标准答案工作表", evaluation.standard_sheet),
        ("标准记录总数", metrics["standard_total"]),
        ("实际提取记录总数", metrics["actual_total"]),
        ("正确匹配数", metrics["matched"]),
        ("漏提取数", metrics["missed"]),
        ("无法可靠匹配数", metrics["ambiguous"]),
        ("重复匹配冲突数", metrics["conflicts"]),
        ("多余/未匹配提取数", metrics["extra"]),
        ("位置提示不一致数", metrics["location_hint_mismatches"]),
        ("非具体点位记录数", metrics["non_literal_point_rows"]),
        ("召回率", f"{metrics['recall'] * 100:.2f}%"),
        ("精确率", f"{metrics['precision'] * 100:.2f}%"),
    ]
    for item in summary_rows:
        summary.append(list(item))
    summary.append([])
    summary.append(["测试文件", "大小(字节)"])
    for document in evaluation.document_files:
        summary.append([document.name, document.stat().st_size])
    summary.append([evaluation.standard_file.name, evaluation.standard_file.stat().st_size])
    _style_sheet(summary, [30, 80])

    comparison_sheet = workbook.create_sheet("逐条对比")
    comparison_sheet.append(
        [
            "标准行号",
            "状态",
            "来源文件(标准)",
            "来源文件(实际)",
            "企业名称(标准)",
            "企业名称(实际)",
            "类别(标准)",
            "类别(实际)",
            "点位(标准)",
            "点位(实际)",
            "指标(标准)",
            "指标(实际)",
            "原始值(标准)",
            "原始值(实际)",
            "单位(标准)",
            "单位(实际)",
            "候选数",
            "位置提示核对",
            "说明",
            "匹配记录ID",
            "实际来源位置",
            "实际原始表达",
            "实际标记",
            "实际来源文本",
        ]
    )
    for comparison in evaluation.comparisons:
        standard = comparison.standard
        actual = comparison.actual
        comparison_sheet.append(
            [
                standard.row_number if standard else "",
                comparison.status,
                standard.source_file if standard else "",
                Path(actual.source_file).name if actual else "",
                standard.enterprise_name if standard else "",
                actual.enterprise_name if actual else "",
                standard.category if standard else "",
                ENV_CATEGORY_LABELS.get(actual.category, actual.category) if actual else "",
                standard.point if standard else "",
                actual.point if actual else "",
                standard.indicator if standard else "",
                actual.indicator if actual else "",
                standard.raw_value if standard else "",
                actual.value if actual else "",
                standard.unit if standard else "",
                actual.unit if actual else "",
                comparison.candidate_count,
                ""
                if comparison.location_hint_ok is None
                else ("一致" if comparison.location_hint_ok else "不一致"),
                _clean_excel("；".join(comparison.notes)),
                actual.record_id if actual else "",
                format_location(Location.from_dict(actual.source_location)) if actual else "",
                _clean_excel(actual.raw_expression) if actual else "",
                _clean_excel("；".join(actual.flags)) if actual else "",
                _clean_excel(actual.source_text) if actual else "",
            ]
        )
    _style_sheet(
        comparison_sheet,
        [8, 20, 30, 30, 30, 30, 12, 12, 24, 24, 16, 16, 14, 14, 12, 12, 8, 12, 60, 34, 36, 50, 30, 70],
    )

    details_sheet = workbook.create_sheet("提取记录明细")
    details_sheet.append(
        [
            "记录ID",
            "来源文件",
            "文件类型",
            "企业ID",
            "企业名称",
            "类别",
            "子类别",
            "指标",
            "数值",
            "单位",
            "时间",
            "点位",
            "检出限",
            "状态",
            "标记",
            "来源位置",
            "源内容类型",
            "原始表达",
            "来源文本",
        ]
    )
    for record in evaluation.batch.environmental.records:
        details_sheet.append(
            [
                record.record_id,
                _clean_excel(record.source_file),
                record.file_type,
                record.enterprise_id,
                _clean_excel(record.enterprise_name or ""),
                ENV_CATEGORY_LABELS.get(record.category, record.category),
                record.subcategory or "",
                record.indicator or "",
                record.value,
                record.unit or "",
                record.time or "",
                record.point or "",
                record.detection_limit or "",
                record.status,
                _clean_excel("；".join(record.flags)),
                format_location(Location.from_dict(record.source_location)),
                record.source_content_type,
                _clean_excel(record.raw_expression),
                _clean_excel(record.source_text),
            ]
        )
    _style_sheet(
        details_sheet,
        [34, 52, 8, 22, 30, 12, 14, 16, 14, 12, 12, 24, 12, 14, 34, 36, 12, 60, 80],
    )

    for sheet_name, predicate in (
        ("漏提取", lambda row: row.status == "漏提取"),
        (
            "无法可靠匹配",
            lambda row: row.status.startswith("无法可靠匹配")
            or row.status == "重复匹配冲突",
        ),
        ("多余提取", lambda row: row.status == "多余/未匹配提取"),
    ):
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(["标准行号", "状态", "标准指标", "标准原始值", "实际指标", "实际数值", "说明"])
        for comparison in evaluation.comparisons:
            if not predicate(comparison):
                continue
            sheet.append(
                [
                    comparison.standard.row_number if comparison.standard else "",
                    comparison.status,
                    comparison.standard.indicator if comparison.standard else "",
                    comparison.standard.raw_value if comparison.standard else "",
                    comparison.actual.indicator if comparison.actual else "",
                    comparison.actual.value if comparison.actual else "",
                    _clean_excel("；".join(comparison.notes)),
                ]
            )
        _style_sheet(sheet, [10, 26, 18, 16, 18, 16, 100])

    workbook.save(path)
    return path
