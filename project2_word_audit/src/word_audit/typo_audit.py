"""Conservative Chinese typo detection over project one batch text.

This module does not modify source files. It scans text already present in the
project one JSON, protects known professional terms/enterprise names/standard
numbers, and converts high- or low-confidence findings into ``AuditIssue``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator

from word_audit.models import AuditIssue, SourceLocation
from word_audit.project1_batch import BatchRecord, Project1Batch
from word_audit.typo_rules import (
    DEFAULT_TYPO_ENTRIES,
    ORGANIZATION_RE,
    PROTECTED_TERMS,
    REPEAT_GUARD_TERMS,
    STANDARD_NUMBER_RE,
    TypoEntry,
)

_CONTEXT_RADIUS = 20


@dataclass(frozen=True)
class _TextUnit:
    document_id: str
    source_file: str
    source_name: str | None
    file_type: str
    text: str
    location: SourceLocation
    source_content_type: str
    unit_key: tuple[Any, ...]
    location_granularity: str


@dataclass(frozen=True)
class _Match:
    wrong: str
    correct: str
    reason: str
    confidence: str
    rule_id: str
    start: int
    end: int
    base_term: str | None = None


@dataclass
class TypoAuditResult:
    issues: list[AuditIssue]
    scanned_unit_count: int
    verified_count: int
    low_confidence_count: int
    warnings: list[str] = field(default_factory=list)


def _parse_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        bbox = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return bbox


def _batch_protected_terms(batch: Project1Batch) -> tuple[str, ...]:
    terms: set[str] = set(PROTECTED_TERMS)

    enterprises = batch.environmental.get("enterprises")
    if isinstance(enterprises, list):
        for enterprise in enterprises:
            if not isinstance(enterprise, dict):
                continue
            name = enterprise.get("enterprise_name")
            if isinstance(name, str) and name.strip():
                terms.add(name.strip())

    for record in batch.environmental_records:
        for value in (record.indicator, record.point, record.unit):
            if isinstance(value, str) and len(value.strip()) >= 2:
                terms.add(value.strip())

    return tuple(sorted(terms, key=len, reverse=True))


def _protected_spans(text: str, terms: tuple[str, ...]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for term in terms:
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                break
            spans.append((index, index + len(term)))
            start = index + 1
    for pattern in (STANDARD_NUMBER_RE, ORGANIZATION_RE):
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end()))
    return spans


def _is_protected(
    text: str,
    start: int,
    end: int,
    spans: list[tuple[int, int]],
) -> bool:
    if any(start >= span_start and end <= span_end for span_start, span_end in spans):
        return True
    left = text[start - 1] if start > 0 else ""
    right = text[end] if end < len(text) else ""
    if left and left.isascii() and left.isalnum():
        return True
    if right and right.isascii() and right.isalnum():
        return True
    return False


def _context(text: str, start: int, end: int) -> str:
    left = max(0, start - _CONTEXT_RADIUS)
    right = min(len(text), end + _CONTEXT_RADIUS)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def _find_matches(
    text: str,
    entries: tuple[TypoEntry, ...],
    protected_terms: tuple[str, ...],
) -> list[_Match]:
    spans = _protected_spans(text, protected_terms)
    raw_matches: list[_Match] = []

    for entry in entries:
        start = 0
        while True:
            index = text.find(entry.wrong, start)
            if index < 0:
                break
            end = index + len(entry.wrong)
            if not _is_protected(text, index, end, spans):
                raw_matches.append(
                    _Match(
                        wrong=entry.wrong,
                        correct=entry.correct,
                        reason=entry.reason,
                        confidence=entry.confidence,
                        rule_id=entry.rule_id,
                        start=index,
                        end=end,
                    )
                )
            start = index + 1

    for term in REPEAT_GUARD_TERMS:
        candidates = (
            (
                term + term[-1],
                f"“{term}”末字重复",
                "TYPO_REPEAT_LAST",
            ),
            (
                term[0] + term,
                f"“{term}”首字重复",
                "TYPO_REPEAT_FIRST",
            ),
        )
        for wrong, reason, rule_id in candidates:
            start = 0
            while True:
                index = text.find(wrong, start)
                if index < 0:
                    break
                end = index + len(wrong)
                if not _is_protected(text, index, end, spans):
                    raw_matches.append(
                        _Match(
                            wrong=wrong,
                            correct=term,
                            reason=reason,
                            confidence="high",
                            rule_id=rule_id,
                            start=index,
                            end=end,
                            base_term=term,
                        )
                    )
                start = index + 1

    unique: dict[tuple[int, int, str, str], _Match] = {}
    for match in raw_matches:
        unique[(match.start, match.end, match.wrong, match.rule_id)] = match

    ordered = sorted(
        unique.values(),
        key=lambda item: (
            item.start,
            -(item.end - item.start),
            0 if item.confidence == "high" else 1,
        ),
    )
    accepted: list[_Match] = []
    for match in ordered:
        if any(
            match.start < existing.end and existing.start < match.end
            for existing in accepted
        ):
            continue
        accepted.append(match)
    return sorted(accepted, key=lambda item: item.start)


def _word_cells(record: BatchRecord) -> Iterator[tuple[int, int, str]]:
    seen: set[tuple[int, int]] = set()
    for cell in record.cells:
        row = cell.get("row_index")
        column = cell.get("column_index")
        if isinstance(row, bool) or isinstance(column, bool):
            continue
        try:
            row_index = int(row)
            column_index = int(column)
        except (TypeError, ValueError):
            continue
        if (row_index, column_index) in seen:
            continue
        seen.add((row_index, column_index))
        text = cell.get("text")
        yield row_index, column_index, "" if text is None else str(text)

    if seen:
        return
    for row_index, row in enumerate(record.rows):
        for column_index, text in enumerate(row):
            yield row_index, column_index, str(text)


def _center_inside(bbox: list[float], container: list[float]) -> bool:
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return (
        container[0] <= center_x <= container[2]
        and container[1] <= center_y <= container[3]
    )


def _iter_text_units(
    batch: Project1Batch,
    warnings: list[str],
) -> Iterator[_TextUnit]:
    for document in batch.documents:
        if document.file_type == "word":
            for record in document.records:
                if record.content_type in {"paragraph", "heading"}:
                    if record.paragraph_index is None:
                        warnings.append(
                            f"Word 段落缺少 paragraph_index，已跳过：{document.source_file}"
                        )
                        continue
                    text = record.text.strip()
                    if not text:
                        continue
                    location = SourceLocation(
                        document_id=document.document_id,
                        source_file=document.source_file,
                        source_name=document.source_name,
                        file_type="word",
                        paragraph_index=record.paragraph_index,
                        source_content_type=record.content_type,
                        locator_method="exact_index",
                        locator_confidence=0.95,
                        notes=["typo_audit: word paragraph"],
                        metadata={"source_unit": "word_paragraph"},
                    )
                    yield _TextUnit(
                        document_id=document.document_id,
                        source_file=document.source_file,
                        source_name=document.source_name,
                        file_type="word",
                        text=text,
                        location=location,
                        source_content_type=record.content_type,
                        unit_key=("word_paragraph", record.paragraph_index),
                        location_granularity="word_paragraph",
                    )
                    continue

                if record.content_type == "table":
                    if record.table_index is None:
                        warnings.append(
                            f"Word 表格缺少 table_index，已跳过：{document.source_file}"
                        )
                        continue
                    for row_index, column_index, text in _word_cells(record):
                        text = text.strip()
                        if not text:
                            continue
                        location = SourceLocation(
                            document_id=document.document_id,
                            source_file=document.source_file,
                            source_name=document.source_name,
                            file_type="word",
                            table_index=record.table_index,
                            row_index=row_index,
                            column_index=column_index,
                            source_content_type="table",
                            locator_method="table_cell",
                            locator_confidence=0.95,
                            notes=["typo_audit: word table cell"],
                            metadata={"source_unit": "word_table_cell"},
                        )
                        yield _TextUnit(
                            document_id=document.document_id,
                            source_file=document.source_file,
                            source_name=document.source_name,
                            file_type="word",
                            text=text,
                            location=location,
                            source_content_type="table",
                            unit_key=(
                                "word_table_cell",
                                record.table_index,
                                row_index,
                                column_index,
                            ),
                            location_granularity="word_table_cell",
                        )
            continue

        if document.file_type != "pdf":
            continue

        table_records = [
            record for record in document.records if record.content_type == "table"
        ]
        table_boxes_by_page: dict[int, list[list[float]]] = {}
        for table_record in table_records:
            page_number = table_record.page_number
            table_bbox = _parse_bbox(table_record.location.get("bbox"))
            cells_with_bbox = [
                cell
                for cell in table_record.cells
                if _parse_bbox(cell.get("bbox"))
                and str(cell.get("text") or "").strip()
            ]
            if page_number is not None and table_bbox and cells_with_bbox:
                table_boxes_by_page.setdefault(page_number, []).append(table_bbox)

        text_records = [
            record
            for record in document.records
            if record.content_type in {"ocr_text", "text_block"}
        ]
        if not text_records:
            text_records = [
                record
                for record in document.records
                if record.content_type in {"ocr_page", "page_text"}
            ]

        for record in text_records:
            text = record.text.strip()
            if not text:
                continue
            page_number = record.page_number
            bbox = _parse_bbox(record.location.get("bbox"))
            if bbox and page_number is not None:
                containers = table_boxes_by_page.get(page_number, [])
                if any(_center_inside(bbox, container) for container in containers):
                    continue
            method = "text_match" if bbox is not None else "unknown"
            confidence = 0.9 if bbox is not None else 0.0
            granularity = "pdf_text_line" if bbox is not None else "pdf_unknown"
            location = SourceLocation(
                document_id=document.document_id,
                source_file=document.source_file,
                source_name=document.source_name,
                file_type="pdf",
                page_number=page_number,
                bbox=bbox,
                block_index=record.location.get("block_index"),
                reading_order=record.location.get("reading_order"),
                source_content_type=record.content_type,
                locator_method=method,
                locator_confidence=confidence,
                notes=[f"typo_audit: {granularity}"],
                metadata={"source_unit": "pdf_text"},
            )
            yield _TextUnit(
                document_id=document.document_id,
                source_file=document.source_file,
                source_name=document.source_name,
                file_type="pdf",
                text=text,
                location=location,
                source_content_type=record.content_type,
                unit_key=(
                    "pdf_text",
                    page_number,
                    tuple(round(value, 3) for value in bbox) if bbox else None,
                    record.location.get("reading_order"),
                    text,
                ),
                location_granularity=granularity,
            )

        for table_record in table_records:
            if table_record.table_index is None:
                warnings.append(
                    f"PDF 表格缺少 table_index，已跳过：{document.source_file}"
                )
                continue
            page_number = table_record.page_number
            for cell in table_record.cells:
                text = str(cell.get("text") or "").strip()
                if not text:
                    continue
                bbox = _parse_bbox(cell.get("bbox"))
                if bbox is None:
                    continue
                row = cell.get("row_index")
                column = cell.get("column_index")
                if isinstance(row, bool) or isinstance(column, bool):
                    continue
                try:
                    row_index = int(row)
                    column_index = int(column)
                except (TypeError, ValueError):
                    continue
                location = SourceLocation(
                    document_id=document.document_id,
                    source_file=document.source_file,
                    source_name=document.source_name,
                    file_type="pdf",
                    table_index=table_record.table_index,
                    row_index=row_index,
                    column_index=column_index,
                    page_number=page_number,
                    bbox=bbox,
                    source_content_type="table",
                    locator_method="table_cell",
                    locator_confidence=0.95 if page_number is not None else 0.7,
                    notes=["typo_audit: pdf table cell"],
                    metadata={"source_unit": "pdf_table_cell"},
                )
                yield _TextUnit(
                    document_id=document.document_id,
                    source_file=document.source_file,
                    source_name=document.source_name,
                    file_type="pdf",
                    text=text,
                    location=location,
                    source_content_type="table",
                    unit_key=(
                        "pdf_table_cell",
                        table_record.table_index,
                        row_index,
                        column_index,
                        page_number,
                    ),
                    location_granularity="pdf_table_cell",
                )


def _issues_for_unit(
    unit: _TextUnit,
    matches: list[_Match],
    *,
    synthetic_data: bool,
) -> list[AuditIssue]:
    grouped: dict[tuple[str, str, str, str | None], list[_Match]] = {}
    for match in matches:
        key = (match.wrong, match.correct, match.rule_id, match.base_term)
        grouped.setdefault(key, []).append(match)

    issues: list[AuditIssue] = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda item: item.start)
        first = ordered[0]
        occurrence_count = len(ordered)
        contexts = [
            _context(unit.text, item.start, item.end) for item in ordered
        ]
        if first.confidence == "high":
            description = (
                f"“{first.wrong}”疑似错别字，建议修改为“{first.correct}”。"
            )
        else:
            description = (
                f"“{first.wrong}”疑似文字错误，建议人工核实"
                f"（候选：{first.correct}）。"
            )
        if occurrence_count > 1:
            description += f"（本位置出现 {occurrence_count} 次）"

        metadata: dict[str, Any] = {
            "audit_rule": "typo",
            "issue_type_label": "错别字",
            "typo_confidence": first.confidence,
            "typo_rule_id": first.rule_id,
            "typo_reason": first.reason,
            "error_text": first.wrong,
            "suggested_text": first.correct,
            "context": contexts[0],
            "contexts": contexts,
            "occurrence_count": occurrence_count,
            "auto_annotate": first.confidence == "high",
            "location_granularity": unit.location_granularity,
            "source_unit": unit.unit_key[0],
        }
        if first.base_term is not None:
            metadata["base_term"] = first.base_term
        if synthetic_data:
            metadata["synthetic"] = True
            metadata["synthetic_note"] = "合成测试数据，非真实审核结果"

        issues.append(
            AuditIssue(
                issue_id=f"typo-{uuid.uuid4().hex}",
                issue_type="typo",
                severity="warning",
                description=description,
                original_text=first.wrong,
                location=unit.location,
                calculation=None,
                needs_manual_review=first.confidence != "high",
                suggestion=first.correct,
                metadata=metadata,
            )
        )
    return issues


def scan_batch_typos(
    batch: Project1Batch,
    *,
    entries: tuple[TypoEntry, ...] = DEFAULT_TYPO_ENTRIES,
    protected_terms: tuple[str, ...] | None = None,
) -> TypoAuditResult:
    """Scan batch text for conservative typo findings."""

    terms = _batch_protected_terms(batch)
    if protected_terms is not None:
        terms = tuple(
            sorted(set(terms) | set(protected_terms), key=len, reverse=True)
        )
    synthetic_data = batch.metadata.get("synthetic_data") is True
    warnings: list[str] = []
    issues: list[AuditIssue] = []
    scanned_unit_count = 0
    seen_units: set[tuple[Any, ...]] = set()

    for unit in _iter_text_units(batch, warnings):
        if unit.unit_key in seen_units:
            continue
        seen_units.add(unit.unit_key)
        scanned_unit_count += 1
        matches = _find_matches(unit.text, entries, terms)
        if matches:
            issues.extend(
                _issues_for_unit(
                    unit,
                    matches,
                    synthetic_data=synthetic_data,
                )
            )

    return TypoAuditResult(
        issues=issues,
        scanned_unit_count=scanned_unit_count,
        verified_count=sum(
            1
            for issue in issues
            if issue.metadata.get("typo_confidence") == "high"
        ),
        low_confidence_count=sum(
            1
            for issue in issues
            if issue.metadata.get("typo_confidence") == "low"
        ),
        warnings=warnings,
    )
