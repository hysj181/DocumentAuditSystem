from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

ENTITY_TYPES = ("integer", "decimal", "amount", "percentage", "date")

FULLWIDTH_TRANSLATION = str.maketrans(
    {
        "０": "0",
        "１": "1",
        "２": "2",
        "３": "3",
        "４": "4",
        "５": "5",
        "６": "6",
        "７": "7",
        "８": "8",
        "９": "9",
        "．": ".",
        "－": "-",
        "＋": "+",
        "％": "%",
    }
)

DATE_RE = re.compile(
    r"(?<!\d)"
    r"(?P<year>(?:19|20)\d{2})\s*[-/.年]\s*"
    r"(?P<month>0?[1-9]|1[0-2])\s*[-/.月]\s*"
    r"(?P<day>0?[1-9]|[12]\d|3[01])\s*日?"
    r"(?!\d)"
)
PERCENTAGE_RE = re.compile(
    r"(?<![\d.])"
    r"(?P<num>[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*[%％]"
)
CURRENCY_PREFIX_RE = re.compile(
    r"[¥￥$€£]\s*"
    r"(?P<num>[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
)
CURRENCY_SUFFIX_RE = re.compile(
    r"(?<![\d.])"
    r"(?P<num>[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<unit>万元|亿元|元|美元|欧元|英镑|人民币|RMB|CNY|USD|EUR|GBP)",
    re.IGNORECASE,
)
DECIMAL_RE = re.compile(
    r"(?<![\d.])"
    r"(?P<num>[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d+)"
    r"(?![\d.])"
)
INTEGER_RE = re.compile(
    r"(?<![\d.,])"
    r"(?P<num>[-+]?(?:\d{1,3}(?:,\d{3})+|\d+))"
    r"(?![\d.,])"
)


@dataclass(frozen=True)
class Entity:
    type: str
    text: str
    start: int
    end: int
    value: int | float | str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "value": self.value,
        }


def _to_number(raw: str) -> int | float:
    normalized = raw.replace(",", "").replace("+", "")
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def _amount_value(match: re.Match[str]) -> int | float:
    value = _to_number(match.group("num"))
    unit = match.groupdict().get("unit") or ""
    if unit == "万元":
        return value * 10000
    if unit == "亿元":
        return value * 100000000
    return value


def _to_date_value(match: re.Match[str]) -> str:
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return match.group(0)


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < used_end and used_start < end for used_start, used_end in occupied)


def extract_entities(text: str) -> list[Entity]:
    if not text:
        return []

    search_text = text.translate(FULLWIDTH_TRANSLATION)
    entities: list[Entity] = []
    occupied: list[tuple[int, int]] = []

    def add(match: re.Match[str], entity_type: str, value: int | float | str | None) -> None:
        span = (match.start(), match.end())
        if _overlaps(span, occupied):
            return
        occupied.append(span)
        entities.append(
            Entity(
                type=entity_type,
                text=text[span[0] : span[1]],
                start=span[0],
                end=span[1],
                value=value,
            )
        )

    for match in DATE_RE.finditer(search_text):
        add(match, "date", _to_date_value(match))

    for match in PERCENTAGE_RE.finditer(search_text):
        add(match, "percentage", _to_number(match.group("num")))

    for match in CURRENCY_PREFIX_RE.finditer(search_text):
        add(match, "amount", _to_number(match.group("num")))

    for match in CURRENCY_SUFFIX_RE.finditer(search_text):
        add(match, "amount", _amount_value(match))

    for match in DECIMAL_RE.finditer(search_text):
        add(match, "decimal", _to_number(match.group("num")))

    for match in INTEGER_RE.finditer(search_text):
        add(match, "integer", _to_number(match.group("num")))

    entities.sort(key=lambda entity: (entity.start, entity.end))
    return entities


def entities_as_dicts(text: str) -> list[dict[str, Any]]:
    return [entity.to_dict() for entity in extract_entities(text)]
