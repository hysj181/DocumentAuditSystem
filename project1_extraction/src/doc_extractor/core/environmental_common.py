from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from doc_extractor.core.environmental_models import (
    ENV_MANAGEMENT,
    ENV_MONITORING,
    ENV_STATISTICS,
    FLAG_AMBIGUOUS_VALUE,
    FLAG_DETECTION_LIMIT,
    FLAG_ENTERPRISE_UNCLEAR,
    FLAG_ENTERPRISE_UNVERIFIED,
    FLAG_MISSING_POINT,
    FLAG_MISSING_TIME,
    FLAG_MISSING_UNIT,
    FLAG_MISSING_VALUE,
    FLAG_LOW_CONFIDENCE,
    FLAG_OCR_SOURCE,
    FLAG_TABLE_STRUCTURE_REVIEW,
    FLAG_UNRECOGNIZED,
    ENTERPRISE_NAME_MATCHED,
    ENTERPRISE_NAME_ONLY,
    ENTERPRISE_UNCLEAR,
    ENTERPRISE_VERIFIED,
    EnvironmentalRecord,
    EnterpriseGroup,
    status_from_flags,
)
from doc_extractor.core.models import (
    DocumentResult,
    Location,
)
from doc_extractor.core.patterns import extract_entities

TEXT_CONTENT_TYPES = {"heading", "paragraph", "page_text", "text_block", "ocr_text"}
LOW_CONFIDENCE_THRESHOLD = 0.75

COMMON_UNITS = (
    "mg/Nm³",
    "mg/Nm3",
    "mg/m³",
    "mg/m3",
    "mg/m",
    "μg/m³",
    "μg/m3",
    "ug/m³",
    "ug/m3",
    "mg/L",
    "μg/L",
    "ug/L",
    "g/L",
    "ppm",
    "ppb",
    "dB(A)",
    "dB（A）",
    "dB",
    "万m³",
    "万m3",
    "万立方米",
    "m³/h",
    "m3/h",
    "Nm³/h",
    "Nm3/h",
    "m³/d",
    "m3/d",
    "m³",
    "m3",
    "m",
    "立方米",
    "万t/a",
    "万吨/年",
    "t/a",
    "吨/年",
    "kg/a",
    "g/a",
    "t/d",
    "kg/d",
    "kg/h",
    "t/h",
    "万吨",
    "吨",
    "千克",
    "公斤",
    "kg",
    "g",
    "t",
    "万kWh",
    "万kwh",
    "万千瓦时",
    "kWh",
    "kwh",
    "千瓦时",
    "度",
    "吨标准煤",
    "tce",
    "标m³",
    "标m3",
    "%",
    "％",
    "无量纲",
    "次",
    "小时",
    "h",
    "天",
    "d",
    "台",
    "套",
    "张",
    "份",
    "个",
    "L",
    "mL",
)

UNIT_ALIASES = {
    "m3": "m³",
    "m": "m³",
    "立方米": "m³",
    "mg/m3": "mg/m³",
    "mg/m": "mg/m³",
    "mg/nm3": "mg/Nm³",
    "mg/nm": "mg/Nm³",
    "μg/m3": "μg/m³",
    "ug/m3": "μg/m³",
    "μg/m": "μg/m³",
    "ug/m": "μg/m³",
    "万m3": "万m³",
    "标m3": "标m³",
    "m3/h": "m³/h",
    "nm3/h": "Nm³/h",
    "m3/d": "m³/d",
    "kwh": "kWh",
    "db(a)": "dB(A)",
    "db（a）": "dB(A)",
    "db": "dB",
}


def _compact_unit_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _normalize_unit_spacing(text: str) -> str:
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\(\s*", "(", text)
    text = re.sub(r"\s*\)", ")", text)
    return text


def normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    stripped = _compact_unit_text(unit.strip())
    return UNIT_ALIASES.get(stripped, UNIT_ALIASES.get(stripped.casefold(), stripped))


def _flexible_unit_pattern(unit: str) -> str:
    escaped = re.escape(unit)
    escaped = escaped.replace(r"\(", r"\s*\(\s*")
    escaped = escaped.replace(r"\)", r"\s*\)")
    escaped = escaped.replace("/", r"\s*/\s*")
    return escaped


UNIT_PATTERN = "|".join(
    _flexible_unit_pattern(unit)
    for unit in sorted(set(COMMON_UNITS), key=len, reverse=True)
)
NUMBER_PATTERN = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
NUMBER_WITH_UNIT_RE = re.compile(
    rf"(?<![\d./\-])(?P<num>{NUMBER_PATTERN})\s*(?P<unit>{UNIT_PATTERN})",
    re.IGNORECASE,
)
NUMBER_ONLY_RE = re.compile(
    rf"(?<![\d./\-])(?P<num>{NUMBER_PATTERN})(?![\d./\-])"
)
UNIT_ONLY_RE = re.compile(
    rf"(?<![A-Za-z])(?:{UNIT_PATTERN})(?![A-Za-z])",
    re.IGNORECASE,
)
DETECTION_LIMIT_RE = re.compile(
    r"(?P<expr>未检出|低于检出限|低于方法检出限|(?<![A-Za-z])(?:ND|N\.D\.)(?![A-Za-z])|[<≤]\s*=?\s*\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
YEAR_ONLY_RE = re.compile(r"^(?:19|20)\d{2}$")
TIME_FALLBACK_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年(?:度)?")

POINT_LABEL_RE = re.compile(
    r"(?:监测点位|监测点|采样点位|采样点|排放口|点位|监测断面|设施名称)\s*[:：]\s*"
    r"(?P<point>[^，,；;。\t\n]{2,40})"
)
POINT_KNOWN_RE = re.compile(
    r"(?P<point>废水总排口|废气总排口|废水排放口|废气排放口|总排口|"
    r"厂界(?:东|南|西|北)?侧?|\d+#?废气排放口|"
    r"[一二三四五六七八九十]+#?废气排放口|监测断面)"
)

TEXT_VALUE_RE = re.compile(
    r"(?:为|是)?\s*[:：=]?\s*(?P<value>[A-Za-z0-9][A-Za-z0-9\-_/（）()]{3,60})"
)
CODE_SPAN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2,8}\d{2,}(?![A-Za-z0-9])")
SEPARATORS = "；;。\n"

CONTEXT_KEYWORDS: dict[str, tuple[str, ...]] = {
    ENV_MONITORING: ("监测日期", "采样日期", "检测日期", "监测时间"),
    ENV_MANAGEMENT: (
        "运行日期",
        "记录日期",
        "台账日期",
        "填报日期",
        "检查日期",
        "记录期间",
    ),
    ENV_STATISTICS: ("统计期间", "统计年度", "报告期", "数据年度", "核算年度"),
}


@dataclass
class SourceUnit:
    document_id: str
    source_file: str
    file_type: str
    text: str
    content_type: str
    location: Location
    cell_texts: list[str] | None = None
    column_index_override: int | None = None
    review_flags: tuple[str, ...] = ()

    def location_for_span(self, start: int, end: int) -> Location:
        location = Location.from_dict(self.location.to_dict())
        if self.column_index_override is not None:
            location.column_index = self.column_index_override
            return location
        if self.cell_texts:
            offset = 0
            for column_index, cell in enumerate(self.cell_texts):
                cell_end = offset + len(cell)
                if offset <= start <= cell_end or offset <= end <= cell_end:
                    location.column_index = column_index
                    break
                offset = cell_end + 1
        return location


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    aliases: tuple[str, ...]
    subcategory: str
    unit_required: bool = True
    time_required: bool = True
    value_kind: str = "number"
    exclude_suffixes: tuple[str, ...] = ()

    def all_aliases(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.name, *self.aliases)))


@dataclass(frozen=True)
class DocumentContext:
    time: str | None = None
    point: str | None = None


@dataclass(frozen=True)
class IndicatorMatch:
    spec: IndicatorSpec
    start: int
    end: int
    text: str


@dataclass
class ValueInfo:
    value: int | float | str | None
    unit: str | None
    detection_limit: str | None
    flags: list[str]
    time_value: str | None = None


@dataclass(frozen=True)
class _Candidate:
    start: int
    end: int
    raw: str
    value: int | float
    unit: str | None


def _spans_overlap(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def _inside_table_bbox(
    record_location: Location,
    table_boxes: list[tuple[int | None, list[float]]],
) -> bool:
    bbox = record_location.bbox
    if not bbox or len(bbox) != 4:
        return False
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    for page_number, table_bbox in table_boxes:
        if page_number != record_location.page_number:
            continue
        if (
            table_bbox[0] <= center_x <= table_bbox[2]
            and table_bbox[1] <= center_y <= table_bbox[3]
        ):
            return True
    return False


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _header_columns(
    headers: list[list[Any]],
    column_count: int,
) -> list[list[str]]:
    columns: list[list[str]] = []
    for column_index in range(column_count):
        parts: list[str] = []
        for header_row in headers:
            if column_index < len(header_row):
                value = _cell_text(header_row[column_index])
                value = " ".join(value.split())
                if value:
                    parts.append(value)
        columns.append(list(dict.fromkeys(parts)))
    return columns


def _find_column(columns: list[list[str]], keywords: tuple[str, ...]) -> int | None:
    for column_index, parts in enumerate(columns):
        text = " ".join(parts)
        if any(keyword in text for keyword in keywords):
            return column_index
    return None


def _unit_from_header(parts: list[str]) -> str | None:
    for text in reversed(parts):
        match = UNIT_ONLY_RE.search(_normalize_unit_spacing(text))
        if match:
            return normalize_unit(match.group(0))
    return None


def _table_column_units(
    record: Any,
    specs: tuple[IndicatorSpec, ...],
) -> list[SourceUnit] | None:
    rows = record.metadata.get("rows") or []
    headers = record.metadata.get("headers") or []
    header_row_count = int(
        record.metadata.get("header_row_count") or len(headers)
    )
    if not rows or not headers or header_row_count <= 0:
        return None

    column_count = max((len(row) for row in rows), default=0)
    if column_count <= 0:
        return None
    header_columns = _header_columns(headers, column_count)
    value_columns: list[tuple[int, str]] = []
    for column_index, parts in enumerate(header_columns):
        header_text = " ".join(parts)
        if header_text and match_indicator_specs(header_text, specs):
            value_columns.append((column_index, header_text))
    if not value_columns:
        return None

    unit_column = _find_column(header_columns, ("单位",))
    point_column = _find_column(
        header_columns,
        ("点位", "排放口", "排口", "监测点", "采样点", "断面"),
    )
    date_column = _find_column(
        header_columns,
        ("日期", "时间", "期间", "年度", "年份"),
    )
    label_column = _find_column(
        header_columns,
        ("指标", "项目", "监测项目", "统计指标", "参数", "因子"),
    )

    base_review_flags: list[str] = []
    if record.metadata.get("needs_review"):
        base_review_flags.append(FLAG_TABLE_STRUCTURE_REVIEW)

    cells_by_row: dict[int, dict[int, dict[str, Any]]] = {}
    for cell in record.metadata.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        row_index = int(cell.get("row_index", -1))
        column_index = int(cell.get("column_index", -1))
        if row_index < 0 or column_index < 0:
            continue
        cells_by_row.setdefault(row_index, {})[column_index] = cell

    units: list[SourceUnit] = []
    for row_index in range(header_row_count, len(rows)):
        row = rows[row_index]

        def value_at(column_index: int | None) -> str:
            if column_index is None or column_index >= len(row):
                return ""
            return _cell_text(row[column_index])

        point = " ".join(value_at(point_column).split())
        date = " ".join(value_at(date_column).split())
        label = " ".join(value_at(label_column).split())
        unit_text = _compact_unit_text(value_at(unit_column))
        if unit_text in {"—", "–", "－", "-", "/", "N/A"}:
            unit_text = ""
        if not point and not label and row:
            label = " ".join(_cell_text(row[0]).split())

        anchor_cells = cells_by_row.get(row_index, {})
        for column_index, header_text in value_columns:
            anchor = anchor_cells.get(column_index)
            if anchor is not None:
                cell_value = _cell_text(anchor.get("text"))
            else:
                cell_value = value_at(column_index)
            cell_value = " ".join(cell_value.split())
            if not cell_value:
                continue

            cell_unit = unit_text or _unit_from_header(
                header_columns[column_index]
            )
            parts: list[str] = []
            if point:
                parts.append(f"监测点位 {point}")
            if date:
                parts.append(f"监测日期 {date}")
            if label and label not in {point, date}:
                parts.append(f"项目 {label}")
            parts.append(f"{header_text}: {cell_value}")
            if cell_unit:
                parts.append(cell_unit)

            review_flags = list(base_review_flags)
            confidence = anchor.get("confidence") if anchor else None
            if confidence is not None:
                try:
                    if float(confidence) < LOW_CONFIDENCE_THRESHOLD:
                        review_flags.append(FLAG_LOW_CONFIDENCE)
                except (TypeError, ValueError):
                    pass

            location = Location.from_dict(record.location.to_dict())
            location.row_index = row_index
            location.column_index = column_index
            units.append(
                SourceUnit(
                    document_id=record.document_id,
                    source_file=record.source_file,
                    file_type=record.file_type,
                    text=" ".join(parts),
                    content_type=record.content_type,
                    location=location,
                    column_index_override=column_index,
                    review_flags=tuple(dict.fromkeys(review_flags)),
                )
            )
    return units or None


def build_source_units(
    document: DocumentResult,
    specs: tuple[IndicatorSpec, ...] | None = None,
) -> list[SourceUnit]:
    has_text_blocks = any(
        record.content_type == "text_block" for record in document.records
    )
    has_ocr_text = any(record.content_type == "ocr_text" for record in document.records)
    table_boxes: list[tuple[int | None, list[float]]] = []
    for record in document.records:
        if record.content_type != "table":
            continue
        bbox = record.location.bbox
        if not bbox:
            continue
        cell_boxes = [
            cell.get("bbox")
            for cell in record.metadata.get("cells") or []
            if cell.get("bbox") and len(cell.get("bbox")) == 4
        ]
        if cell_boxes:
            bbox = [
                min([bbox[0], *[box[0] for box in cell_boxes]]),
                min([bbox[1], *[box[1] for box in cell_boxes]]),
                max([bbox[2], *[box[2] for box in cell_boxes]]),
                max([bbox[3], *[box[3] for box in cell_boxes]]),
            ]
        table_boxes.append((record.location.page_number, bbox))

    units: list[SourceUnit] = []
    for record in document.records:
        if record.content_type == "table":
            if specs:
                column_units = _table_column_units(record, specs)
                if column_units is not None:
                    units.extend(column_units)
                    continue
            rows = record.metadata.get("rows", [])
            table_review_flags = (
                (FLAG_TABLE_STRUCTURE_REVIEW,)
                if record.metadata.get("needs_review")
                else ()
            )
            for row_index, row in enumerate(rows):
                cells = [str(cell).strip() for cell in row]
                text = "\t".join(cells).strip()
                if not text:
                    continue
                location = Location.from_dict(record.location.to_dict())
                location.row_index = row_index
                location.column_index = None
                units.append(
                    SourceUnit(
                        document_id=record.document_id,
                        source_file=record.source_file,
                        file_type=record.file_type,
                        text=text,
                        content_type=record.content_type,
                        location=location,
                        cell_texts=cells,
                        review_flags=table_review_flags,
                    )
                )
            continue

        if record.content_type == "page_text" and has_text_blocks:
            continue
        if record.content_type == "ocr_page" and has_ocr_text:
            continue
        if record.content_type not in TEXT_CONTENT_TYPES:
            continue
        if _inside_table_bbox(record.location, table_boxes):
            continue
        text = record.text.strip()
        if not text:
            continue
        review_flags: list[str] = []
        if record.content_type in {"ocr_text", "ocr_page"}:
            review_flags.append(FLAG_OCR_SOURCE)
            confidence = record.metadata.get("confidence")
            if confidence is not None:
                try:
                    if float(confidence) < LOW_CONFIDENCE_THRESHOLD:
                        review_flags.append(FLAG_LOW_CONFIDENCE)
                except (TypeError, ValueError):
                    pass
        units.append(
            SourceUnit(
                document_id=record.document_id,
                source_file=record.source_file,
                file_type=record.file_type,
                text=text,
                content_type=record.content_type,
                location=Location.from_dict(record.location.to_dict()),
                review_flags=tuple(dict.fromkeys(review_flags)),
            )
        )
    return units


@lru_cache(maxsize=None)
def _alias_regex(alias: str) -> re.Pattern[str]:
    prefix = (
        r"(?<![A-Za-z0-9])"
        if alias and alias[0].isascii() and alias[0].isalnum()
        else ""
    )
    # OCR 常把指标和数值粘在一起，如 COD45.2、pH7.3。
    # 指标以字母结尾时阻止后接字母（避免 CODcr 被当成 COD），但允许后接数字。
    suffix = (
        r"(?![A-Za-z])"
        if alias and alias[-1].isascii() and alias[-1].isalpha()
        else ""
    )
    return re.compile(prefix + re.escape(alias) + suffix, re.IGNORECASE)


def match_indicator_specs(text: str, specs: tuple[IndicatorSpec, ...]) -> list[IndicatorMatch]:
    raw_matches: list[IndicatorMatch] = []
    for spec in specs:
        for alias in spec.all_aliases():
            for match in _alias_regex(alias).finditer(text):
                tail = text[match.end() : match.end() + 12].lstrip()
                if any(tail.startswith(suffix) for suffix in spec.exclude_suffixes):
                    continue
                raw_matches.append(
                    IndicatorMatch(
                        spec=spec,
                        start=match.start(),
                        end=match.end(),
                        text=match.group(0),
                    )
                )

    raw_matches.sort(key=lambda item: (item.start, -(item.end - item.start)))
    accepted: list[IndicatorMatch] = []
    occupied: list[tuple[int, int]] = []
    seen_specs: set[str] = set()

    for match in raw_matches:
        if match.spec.name in seen_specs:
            continue
        if _spans_overlap(match.start, match.end, occupied):
            continue
        accepted.append(match)
        occupied.append((match.start, match.end))
        seen_specs.add(match.spec.name)

    accepted.sort(key=lambda item: item.start)
    return accepted


def _is_separator(text: str, index: int) -> bool:
    character = text[index]
    if character in SEPARATORS:
        return True
    if character in "，,":
        previous_digit = index > 0 and text[index - 1].isdigit()
        next_digit = index + 1 < len(text) and text[index + 1].isdigit()
        return not (previous_digit and next_digit)
    return False


def _window_after(text: str, start: int, limit: int) -> tuple[int, int]:
    end = min(len(text), start + 120, limit)
    for index in range(start, end):
        if _is_separator(text, index):
            return start, index
    return start, end


def _window_before(text: str, start: int, previous_end: int) -> tuple[int, int]:
    window_start = max(previous_end, start - 60, 0)
    last_separator = window_start
    for index in range(window_start, start):
        if _is_separator(text, index):
            last_separator = index + 1
    return last_separator, start


def _to_number(raw: str) -> int | float:
    normalized = raw.replace(",", "").replace("+", "")
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def _collect_candidates(
    text: str,
    start: int,
    end: int,
    blocked_spans: list[tuple[int, int]],
) -> tuple[list[_Candidate], list[_Candidate]]:
    with_unit: list[_Candidate] = []
    without_unit: list[_Candidate] = []
    unit_spans: list[tuple[int, int]] = []

    for match in NUMBER_WITH_UNIT_RE.finditer(text):
        if match.start() < start or match.end() > end:
            continue
        if _spans_overlap(match.start(), match.end(), blocked_spans):
            continue
        unit = normalize_unit(match.group("unit"))
        with_unit.append(
            _Candidate(
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
                value=_to_number(match.group("num")),
                unit=unit,
            )
        )
        unit_spans.append((match.start(), match.end()))

    for match in NUMBER_ONLY_RE.finditer(text):
        if match.start() < start or match.end() > end:
            continue
        if _spans_overlap(match.start(), match.end(), blocked_spans):
            continue
        if _spans_overlap(match.start(), match.end(), unit_spans):
            continue
        raw = match.group("num")
        if YEAR_ONLY_RE.fullmatch(raw):
            continue
        without_unit.append(
            _Candidate(
                start=match.start(),
                end=match.end(),
                raw=raw,
                value=_to_number(raw),
                unit=None,
            )
        )

    with_unit.sort(key=lambda item: item.start)
    without_unit.sort(key=lambda item: item.start)
    return with_unit, without_unit


def _unit_in_window(text: str, start: int, end: int) -> str | None:
    match = UNIT_ONLY_RE.search(_normalize_unit_spacing(text[start:end]))
    return normalize_unit(match.group(0)) if match else None


def _distinct_values(candidates: list[_Candidate]) -> set[int | float]:
    return {candidate.value for candidate in candidates}


def extract_number_value(
    *,
    text: str,
    match: IndicatorMatch,
    next_start: int,
    previous_end: int,
    date_spans: list[tuple[int, int]],
    indicator_spans: list[tuple[int, int]],
    point_spans: list[tuple[int, int]] | None = None,
) -> ValueInfo:
    after_start, after_end = _window_after(text, match.end, next_start)
    before_start, before_end = _window_before(text, match.start, previous_end)
    blocked = date_spans + indicator_spans + (point_spans or [])

    after_with_unit, after_without_unit = _collect_candidates(
        text, after_start, after_end, blocked
    )
    before_with_unit, before_without_unit = _collect_candidates(
        text, before_start, before_end, blocked
    )

    windows = (
        (after_start, after_end, after_with_unit, False),
        (before_start, before_end, before_with_unit, True),
    )
    for window_start, window_end, window_candidates, from_before in windows:
        detection = DETECTION_LIMIT_RE.search(text[window_start:window_end])
        if detection:
            if window_candidates:
                unit = window_candidates[-1].unit if from_before else window_candidates[0].unit
            else:
                unit = _unit_in_window(text, window_start, window_end)
            return ValueInfo(
                value=None,
                unit=unit,
                detection_limit=detection.group("expr"),
                flags=[FLAG_DETECTION_LIMIT],
            )

    flags: list[str] = []
    if after_with_unit:
        candidates = after_with_unit
    elif after_without_unit:
        candidates = after_without_unit
    elif before_with_unit:
        candidates = list(reversed(before_with_unit))
    else:
        candidates = list(reversed(before_without_unit))

    if not candidates:
        unit = _unit_in_window(text, after_start, after_end) or _unit_in_window(
            text, before_start, before_end
        )
        return ValueInfo(
            value=None,
            unit=unit,
            detection_limit=None,
            flags=[FLAG_MISSING_VALUE],
        )

    if len(_distinct_values(candidates)) > 1:
        flags.append(FLAG_AMBIGUOUS_VALUE)

    selected = candidates[0]
    return ValueInfo(
        value=selected.value,
        unit=selected.unit,
        detection_limit=None,
        flags=flags,
    )


def extract_text_value(
    *,
    text: str,
    match: IndicatorMatch,
    next_start: int,
) -> ValueInfo:
    window_start, window_end = _window_after(text, match.end, next_start)
    window = text[window_start:window_end]
    value_match = TEXT_VALUE_RE.search(window)
    if not value_match:
        return ValueInfo(
            value=None,
            unit=None,
            detection_limit=None,
            flags=[FLAG_MISSING_VALUE],
        )
    return ValueInfo(
        value=value_match.group("value"),
        unit=None,
        detection_limit=None,
        flags=[],
    )


def extract_date_value(
    *,
    text: str,
    match: IndicatorMatch,
    next_start: int,
) -> ValueInfo:
    window_start, window_end = _window_after(text, match.end, next_start)
    dates = [
        entity
        for entity in extract_entities(text[window_start:window_end])
        if entity.type == "date"
    ]
    if not dates:
        return ValueInfo(
            value=None,
            unit=None,
            detection_limit=None,
            flags=[FLAG_MISSING_VALUE],
        )
    value = str(dates[0].value)
    return ValueInfo(
        value=value,
        unit=None,
        detection_limit=None,
        flags=[],
        time_value=value,
    )


def find_time(text: str) -> str | None:
    dates = [entity for entity in extract_entities(text) if entity.type == "date"]
    if dates:
        return str(dates[0].value)
    fallback = TIME_FALLBACK_RE.search(text)
    if fallback:
        return f"{fallback.group(1)}年"
    return None


def _format_point_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return re.sub(
        r"^([A-Za-z]{1,8}\d{2,})\s*(?=[\u4e00-\u9fff])",
        r"\1 ",
        normalized,
    )


def find_point(text: str) -> str | None:
    labelled = POINT_LABEL_RE.search(text)
    if labelled:
        return _format_point_text(labelled.group("point"))
    known = POINT_KNOWN_RE.search(text)
    if known:
        return _format_point_text(known.group("point"))
    return None


def _non_value_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in (POINT_LABEL_RE, POINT_KNOWN_RE, CODE_SPAN_RE):
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end()))
    return spans


def _date_in_window(text: str, start: int, end: int) -> str | None:
    dates = [
        entity
        for entity in extract_entities(text[start:end])
        if entity.type == "date"
    ]
    return str(dates[0].value) if dates else None


def find_time_near_indicator(
    *,
    text: str,
    match: IndicatorMatch,
    next_start: int,
    previous_end: int,
) -> str | None:
    after_start, after_end = _window_after(text, match.end, next_start)
    value = _date_in_window(text, after_start, after_end)
    if value:
        return value
    before_start, before_end = _window_before(text, match.start, previous_end)
    return _date_in_window(text, before_start, before_end)


def find_point_near_indicator(
    *,
    text: str,
    match: IndicatorMatch,
    next_start: int,
    previous_end: int,
) -> str | None:
    inside_indicator = find_point(match.text)
    if inside_indicator:
        return inside_indicator
    after_start, after_end = _window_after(text, match.end, next_start)
    after_point = find_point(text[after_start:after_end])
    if after_point:
        return after_point
    before_start, before_end = _window_before(text, match.start, previous_end)
    return find_point(text[before_start:before_end])


def build_document_context(
    units: list[SourceUnit],
    category: str,
) -> DocumentContext:
    time_candidates: list[str] = []
    point_candidates: list[str] = []
    keywords = CONTEXT_KEYWORDS.get(category, ())

    for unit in units:
        if any(keyword in unit.text for keyword in keywords):
            time_value = find_time(unit.text)
            if time_value:
                time_candidates.append(time_value)
        point = find_point(unit.text)
        if point:
            point_candidates.append(point)

    unique_times = list(dict.fromkeys(time_candidates))
    unique_points = list(dict.fromkeys(point_candidates))
    return DocumentContext(
        time=unique_times[0] if len(unique_times) == 1 else None,
        point=unique_points[0] if len(unique_points) == 1 else None,
    )


def expression_around(text: str, start: int, end: int) -> str:
    left = 0
    for index in range(start - 1, -1, -1):
        if _is_separator(text, index):
            left = index + 1
            break
    right = len(text)
    for index in range(end, len(text)):
        if _is_separator(text, index):
            right = index
            break
    expression = text[left:right].strip(" \t\r\n，,；;。")
    return expression or text.strip()


def build_environmental_record(
    *,
    document: DocumentResult,
    unit: SourceUnit,
    match: IndicatorMatch,
    enterprise: EnterpriseGroup,
    value_info: ValueInfo,
    time_value: str | None,
    point_value: str | None,
    point_required: bool,
    time_from_context: bool = False,
    point_from_context: bool = False,
) -> EnvironmentalRecord:
    flags = list(dict.fromkeys([*value_info.flags, *unit.review_flags]))
    if match.spec.unit_required and not value_info.unit:
        flags.append(FLAG_MISSING_UNIT)
    if value_info.value is None and not value_info.detection_limit:
        flags.append(FLAG_MISSING_VALUE)
    if match.spec.time_required and not time_value:
        flags.append(FLAG_MISSING_TIME)
    if point_required and not point_value:
        flags.append(FLAG_MISSING_POINT)

    if enterprise.identity_status == ENTERPRISE_UNCLEAR:
        flags.append(FLAG_ENTERPRISE_UNCLEAR)
    elif enterprise.identity_status in {ENTERPRISE_NAME_ONLY, ENTERPRISE_NAME_MATCHED}:
        flags.append(FLAG_ENTERPRISE_UNVERIFIED)

    flags = list(dict.fromkeys(flags))
    location = unit.location_for_span(match.start, match.end)
    confidence = 0.9 if not flags else max(0.35, 0.9 - 0.1 * len(flags))

    return EnvironmentalRecord(
        record_id=uuid.uuid4().hex,
        category="",
        subcategory=match.spec.subcategory,
        enterprise_id=enterprise.enterprise_id,
        enterprise_name=enterprise.enterprise_name,
        unified_social_credit_code=enterprise.unified_social_credit_code,
        document_id=document.document_id,
        source_file=document.source_file,
        file_type=document.file_type,
        indicator=match.spec.name,
        value=value_info.value,
        unit=value_info.unit,
        time=time_value,
        point=point_value,
        source_location=location.to_dict(),
        source_content_type=unit.content_type,
        source_text=unit.text,
        raw_expression=expression_around(unit.text, match.start, match.end),
        extraction_engine=document.metadata.get("extraction_engine", "PaddleOCR"),
        extraction_mode=document.metadata.get("extraction_mode"),
        detection_limit=value_info.detection_limit,
        flags=flags,
        status=status_from_flags(flags),
        confidence=round(confidence, 2),
        metadata={
            "indicator_alias": match.text,
            "enterprise_identity_status": enterprise.identity_status,
            "source_unit_type": unit.content_type,
            "extraction_engine": document.metadata.get(
                "extraction_engine", "PaddleOCR"
            ),
            "extraction_mode": document.metadata.get("extraction_mode"),
            "table_index": location.table_index,
            "row_index": location.row_index,
            "column_index": location.column_index,
            "time_from_document_context": time_from_context,
            "point_from_document_context": point_from_context,
        },
    )


class BaseEnvironmentalExtractor:
    category = ""
    specs: tuple[IndicatorSpec, ...] = ()
    point_required = False
    category_keywords: tuple[str, ...] = ()

    def extract(
        self,
        document: DocumentResult,
        enterprise: EnterpriseGroup,
    ) -> list[EnvironmentalRecord]:
        if document.error:
            return []

        records: list[EnvironmentalRecord] = []
        units = build_source_units(document, self.specs)
        context = build_document_context(units, self.category)
        for unit in units:
            matches = match_indicator_specs(unit.text, self.specs)
            if not matches:
                unrecognized = self._build_unrecognized_record(
                    document=document,
                    enterprise=enterprise,
                    unit=unit,
                    context=context,
                )
                if unrecognized is not None:
                    records.append(unrecognized)
                continue

            date_spans = [
                (entity.start, entity.end)
                for entity in extract_entities(unit.text)
                if entity.type == "date"
            ]
            indicator_spans = [(match.start, match.end) for match in matches]
            point_spans = _non_value_spans(unit.text)
            leading_point = find_point(unit.text[: matches[0].start])

            for index, match in enumerate(matches):
                next_start = (
                    matches[index + 1].start if index + 1 < len(matches) else len(unit.text)
                )
                previous_end = matches[index - 1].end if index > 0 else 0

                if match.spec.value_kind == "text":
                    value_info = extract_text_value(
                        text=unit.text,
                        match=match,
                        next_start=next_start,
                    )
                elif match.spec.value_kind == "date":
                    value_info = extract_date_value(
                        text=unit.text,
                        match=match,
                        next_start=next_start,
                    )
                else:
                    value_info = extract_number_value(
                        text=unit.text,
                        match=match,
                        next_start=next_start,
                        previous_end=previous_end,
                        date_spans=date_spans,
                        indicator_spans=indicator_spans,
                        point_spans=point_spans,
                    )

                near_time = find_time_near_indicator(
                    text=unit.text,
                    match=match,
                    next_start=next_start,
                    previous_end=previous_end,
                )
                near_point = find_point_near_indicator(
                    text=unit.text,
                    match=match,
                    next_start=next_start,
                    previous_end=previous_end,
                )

                if match.spec.time_required:
                    record_time = value_info.time_value or near_time or context.time
                    time_from_context = (
                        value_info.time_value is None
                        and near_time is None
                        and context.time is not None
                    )
                else:
                    record_time = value_info.time_value
                    time_from_context = False

                record_point = near_point or leading_point
                point_from_context = False
                if record_point is None and context.point is not None:
                    record_point = context.point
                    point_from_context = True

                record = build_environmental_record(
                    document=document,
                    unit=unit,
                    match=match,
                    enterprise=enterprise,
                    value_info=value_info,
                    time_value=record_time,
                    point_value=record_point,
                    point_required=self.point_required,
                    time_from_context=time_from_context,
                    point_from_context=point_from_context,
                )
                record.category = self.category
                records.append(record)

        return records

    def _build_unrecognized_record(
        self,
        *,
        document: DocumentResult,
        enterprise: EnterpriseGroup,
        unit: SourceUnit,
        context: DocumentContext,
    ) -> EnvironmentalRecord | None:
        if not any(keyword in unit.text for keyword in self.category_keywords):
            return None

        date_spans = [
            (entity.start, entity.end)
            for entity in extract_entities(unit.text)
            if entity.type == "date"
        ]
        with_unit, _without_unit = _collect_candidates(
            unit.text,
            0,
            len(unit.text),
            date_spans + _non_value_spans(unit.text),
        )
        candidate = with_unit[0] if with_unit else None
        if candidate is None:
            return None

        detection = DETECTION_LIMIT_RE.search(unit.text)
        unit_text = candidate.unit
        flags = [FLAG_UNRECOGNIZED, *unit.review_flags]
        if unit_text is None:
            flags.append(FLAG_MISSING_UNIT)

        time_value = find_time(unit.text) or context.time
        point_value = find_point(unit.text)
        if point_value is None and self.point_required:
            point_value = context.point
        if not time_value:
            flags.append(FLAG_MISSING_TIME)
        if self.point_required and not point_value:
            flags.append(FLAG_MISSING_POINT)

        if enterprise.identity_status == ENTERPRISE_UNCLEAR:
            flags.append(FLAG_ENTERPRISE_UNCLEAR)
        elif enterprise.identity_status in {ENTERPRISE_NAME_ONLY, ENTERPRISE_NAME_MATCHED}:
            flags.append(FLAG_ENTERPRISE_UNVERIFIED)

        flags = list(dict.fromkeys(flags))
        location = unit.location_for_span(candidate.start, candidate.end)
        matched_keywords = [
            keyword for keyword in self.category_keywords if keyword in unit.text
        ]

        return EnvironmentalRecord(
            record_id=uuid.uuid4().hex,
            category=self.category,
            subcategory=None,
            enterprise_id=enterprise.enterprise_id,
            enterprise_name=enterprise.enterprise_name,
            unified_social_credit_code=enterprise.unified_social_credit_code,
            document_id=document.document_id,
            source_file=document.source_file,
            file_type=document.file_type,
            indicator=None,
            value=None if detection else candidate.value,
            unit=unit_text,
            time=time_value,
            point=point_value,
            source_location=location.to_dict(),
            source_content_type=unit.content_type,
            source_text=unit.text,
            raw_expression=expression_around(unit.text, candidate.start, candidate.end),
            extraction_engine=document.metadata.get("extraction_engine", "PaddleOCR"),
            extraction_mode=document.metadata.get("extraction_mode"),
            detection_limit=detection.group("expr") if detection else None,
            flags=flags,
            status=status_from_flags(flags),
            confidence=0.35,
            metadata={
                "unrecognized": True,
                "enterprise_identity_status": enterprise.identity_status,
                "source_unit_type": unit.content_type,
                "table_index": location.table_index,
                "row_index": location.row_index,
                "column_index": location.column_index,
                "matched_category_keywords": matched_keywords,
            },
        )
