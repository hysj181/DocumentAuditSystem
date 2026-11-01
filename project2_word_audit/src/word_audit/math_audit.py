"""Mathematical validation of project one environmental records.

The module is deliberately conservative:

* Only explicit arithmetic expressions are evaluated.
* A plain monitoring value is never treated as a calculation error.
* When there is no calculation basis the record is marked ``unverified`` and
  ``computed_value`` stays ``None``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from word_audit.models import (
    ISSUE_TYPE_CALCULATION,
    SEVERITY_ERROR,
    VERIFICATION_NOT_ATTEMPTED,
    VERIFICATION_VERIFIED,
    AuditIssue,
    CalculationInfo,
    SourceLocation,
    utc_now_iso,
)
from word_audit.project1_batch import (
    EnvironmentalRecordView,
    Project1Batch,
    TableView,
)

VALIDATION_VERIFIED = "verified"
VALIDATION_UNVERIFIED = "unverified"
VALIDATION_ERROR = "error"

VALIDATION_STATUSES = (
    VALIDATION_VERIFIED,
    VALIDATION_UNVERIFIED,
    VALIDATION_ERROR,
)

_FULLWIDTH_TRANSLATION = str.maketrans(
    {
        "×": "*",
        "÷": "/",
        "（": "(",
        "）": ")",
        "％": "%",
        "－": "-",
        "＋": "+",
        "＝": "=",
        "，": ",",
        "。": ".",
        "　": " ",
    }
)

_DATE_RE = re.compile(
    r"(?:19|20)\d{2}\s*[-/.年]\s*\d{1,2}(?:\s*[-/.月]\s*\d{1,2})?\s*日?"
)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ARITHMETIC_RE = re.compile(r"\d\s*[+\-*/]\s*\(?\s*\d")
_ALLOWED_EXPRESSION_CHARS_RE = re.compile(r"^[0-9.\s+\-*/()]+$")

_CALCULATION_KEYWORDS = (
    "去除率",
    "去除效率",
    "排放量",
    "产生量",
    "合计",
    "总计",
    "核算",
    "折算",
    "计算",
)

_VALUE_COLUMN_KEYWORDS = (
    "监测结果",
    "检测结果",
    "监测值",
    "结果",
    "数值",
    "浓度",
    "排放浓度",
    "实测值",
    "测定值",
)

_HEADER_KEYWORDS = (
    "监测结果",
    "检测结果",
    "监测值",
    "结果",
    "数值",
    "浓度",
    "排放浓度",
    "实测值",
    "测定值",
    "单位",
    "备注",
    "监测项目",
    "指标",
    "项目",
)


def _normalize_expression(text: str) -> str:
    return text.translate(_FULLWIDTH_TRANSLATION)


def _numbers_in_text(text: str) -> list[float]:
    values: list[float] = []
    for match in _NUMBER_RE.finditer(text):
        try:
            values.append(float(match.group(0)))
        except ValueError:
            continue
    return values


def _is_arithmetic(expression: str) -> bool:
    cleaned = _DATE_RE.sub(" ", _normalize_expression(expression))
    cleaned = cleaned.replace(",", "")
    if len(_NUMBER_RE.findall(cleaned)) < 2:
        return False
    return bool(_ARITHMETIC_RE.search(cleaned))


def _extract_arithmetic_part(text: str) -> tuple[str, int] | None:
    cleaned = _DATE_RE.sub(" ", _normalize_expression(text))
    for match in re.finditer(r"[0-9+\-*/().\s]+", cleaned):
        part = match.group(0).strip()
        if _is_arithmetic(part):
            return part, match.start()
    return None


@dataclass(frozen=True)
class ExpressionCandidate:
    text: str
    lhs: str
    rhs: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "lhs": self.lhs,
            "rhs": self.rhs,
        }


def detect_calculation_expressions(text: str) -> list[ExpressionCandidate]:
    """Return explicit arithmetic expressions only.

    Unit strings such as ``mg/L``, dates and single monitoring values are
    ignored.
    """

    if not text:
        return []
    normalized = _normalize_expression(text)
    candidates: list[ExpressionCandidate] = []
    seen: set[str] = set()

    def add(lhs: str, rhs: str | None, whole: str) -> None:
        key = (rhs or whole).strip()
        if not key or key in seen:
            return
        seen.add(key)
        candidates.append(
            ExpressionCandidate(
                text=whole.strip(),
                lhs=lhs.strip(" :：,，"),
                rhs=rhs.strip(" :：,，") if rhs is not None else None,
            )
        )

    for segment in re.split(r"[。；;\n]", normalized):
        segment = segment.strip()
        if not segment:
            continue
        if "=" in segment:
            lhs, rhs = segment.split("=", 1)
            rhs = rhs.strip(" :：,，")
            if _is_arithmetic(rhs):
                add(lhs, rhs, segment)
            continue
        for keyword in _CALCULATION_KEYWORDS:
            if keyword not in segment:
                continue
            extracted = _extract_arithmetic_part(segment)
            if extracted is not None:
                rhs, _ = extracted
                add(keyword, rhs, segment)
                break

    return candidates


class _ExpressionEvaluator:
    def __init__(self) -> None:
        self._allowed_binops = {
            ast.Add: lambda left, right: left + right,
            ast.Sub: lambda left, right: left - right,
            ast.Mult: lambda left, right: left * right,
            ast.Div: self._divide,
        }

    @staticmethod
    def _divide(left: Decimal, right: Decimal) -> Decimal:
        if right == 0:
            raise ZeroDivisionError("division by zero")
        return left / right

    def evaluate(self, node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return self.evaluate(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)
            ):
                raise ValueError("only numeric constants are allowed")
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp):
            operand = self.evaluate(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return operand
            raise ValueError("unsupported unary operator")
        if isinstance(node, ast.BinOp):
            operation = self._allowed_binops.get(type(node.op))
            if operation is None:
                raise ValueError("unsupported binary operator")
            return operation(self.evaluate(node.left), self.evaluate(node.right))
        raise ValueError(f"unsupported expression node: {type(node).__name__}")


_EVALUATOR = _ExpressionEvaluator()


def evaluate_expression(expression: str) -> tuple[float | None, str | None]:
    """Evaluate a pure arithmetic expression.

    Returns ``(value, None)`` on success or ``(None, reason)`` when the
    expression is not safe or not pure arithmetic.
    """

    candidate = _normalize_expression(expression).strip().replace(",", "")
    if not candidate:
        return None, "empty_expression"
    if "%" in candidate:
        return None, "percentage_not_supported"
    if not _ALLOWED_EXPRESSION_CHARS_RE.match(candidate):
        return None, "expression_contains_non_numeric_tokens"
    if not _is_arithmetic(candidate):
        return None, "not_an_arithmetic_expression"
    try:
        tree = ast.parse(candidate, mode="eval")
        value = _EVALUATOR.evaluate(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, InvalidOperation) as exc:
        return None, f"evaluation_failed: {exc}"
    return float(value), None


def _combine_header_rows(rows: list[list[str]], column_count: int) -> list[str]:
    headers: list[str] = []
    for column_index in range(column_count):
        parts: list[str] = []
        for row in rows:
            if column_index >= len(row):
                continue
            text = " ".join(str(row[column_index]).split())
            if text and text not in parts:
                parts.append(text)
        headers.append(" ".join(parts))
    return headers


def infer_headers(table: TableView) -> tuple[int, list[str]]:
    """Infer the header rows and per-column header text.

    PDF tables usually carry ``headers`` / ``header_row_count``. Word tables
    do not, so the first rows are inspected for header keywords.
    """

    if table.headers and table.header_row_count > 0:
        count = min(table.header_row_count, len(table.rows))
        return count, _combine_header_rows(table.headers[:count], table.column_count)

    for row_index in range(min(3, len(table.rows))):
        row = table.rows[row_index]
        if any(
            keyword in str(cell)
            for cell in row
            for keyword in _HEADER_KEYWORDS
        ):
            return row_index + 1, _combine_header_rows(
                table.rows[: row_index + 1], table.column_count
            )
    return 0, []


def find_value_column(header_texts: list[str]) -> int | None:
    for keyword in _VALUE_COLUMN_KEYWORDS:
        for column_index, text in enumerate(header_texts):
            if keyword in text:
                return column_index
    return None


@dataclass(frozen=True)
class ValueCellMapping:
    found: bool
    row_index: int | None = None
    column_index: int | None = None
    text: str | None = None
    header_text: str | None = None
    confidence: float = 0.0
    basis: str = ""
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "text": self.text,
            "header_text": self.header_text,
            "confidence": self.confidence,
            "basis": self.basis,
            "reason": self.reason,
        }


def _matches_expected_value(
    record: EnvironmentalRecordView,
    cell_text: str,
    parsed_value: float | None,
) -> bool:
    normalized_cell = cell_text.strip()
    if record.detection_limit:
        return record.detection_limit.strip().casefold() in normalized_cell.casefold()
    if parsed_value is not None:
        tolerance = max(1e-9, abs(parsed_value) * 1e-9)
        return any(
            abs(number - parsed_value) <= tolerance
            for number in _numbers_in_text(normalized_cell)
        )
    if isinstance(record.value, str) and record.value.strip():
        return record.value.strip() in normalized_cell
    return False


def map_value_cell(
    record: EnvironmentalRecordView,
    table: TableView,
    parsed_value: float | None,
) -> ValueCellMapping:
    row_index = record.row_index
    anchor_column = record.column_index
    if row_index is None:
        return ValueCellMapping(found=False, reason="row_index_missing")
    if row_index < 0 or row_index >= table.row_count:
        return ValueCellMapping(found=False, reason="row_index_out_of_range")

    _, header_texts = infer_headers(table)
    value_column = find_value_column(header_texts)
    if value_column is None:
        return ValueCellMapping(found=False, reason="value_column_not_found")
    if value_column >= table.column_count:
        return ValueCellMapping(found=False, reason="value_column_out_of_range")

    cell_text = table.cell_text(row_index, value_column)
    if cell_text is None:
        return ValueCellMapping(found=False, reason="value_cell_missing")
    if not _matches_expected_value(record, cell_text, parsed_value):
        return ValueCellMapping(
            found=False,
            row_index=row_index,
            column_index=value_column,
            text=cell_text,
            header_text=header_texts[value_column] if value_column < len(header_texts) else None,
            confidence=0.0,
            basis="header_mapping",
            reason="value_cell_text_mismatch",
        )

    confidence = 0.95
    basis = "header_mapping"
    if anchor_column is not None and anchor_column == value_column:
        confidence = 0.7
        basis = "anchor_and_value_same_column"
    return ValueCellMapping(
        found=True,
        row_index=row_index,
        column_index=value_column,
        text=cell_text,
        header_text=header_texts[value_column] if value_column < len(header_texts) else None,
        confidence=confidence,
        basis=basis,
    )


def _parse_numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _build_location(
    record: EnvironmentalRecordView,
    batch: Project1Batch,
    mapping: ValueCellMapping,
    table_found: bool,
) -> SourceLocation:
    document = batch.document(record.document_id)
    source_name = document.source_name if document else None
    notes: list[str] = []
    if mapping.found:
        notes.append(f"数值单元格由表头映射: {mapping.basis}")
    elif mapping.reason:
        notes.append(f"数值单元格未确认: {mapping.reason}")

    if mapping.found:
        method = "table_cell"
        confidence = mapping.confidence
    elif table_found:
        method = "exact_index"
        confidence = 0.8
    else:
        method = "unknown"
        confidence = 0.0

    return SourceLocation(
        document_id=record.document_id,
        source_file=record.source_file,
        source_name=source_name,
        file_type=record.file_type,
        paragraph_index=record.source_location.get("paragraph_index"),
        table_index=record.table_index,
        row_index=record.row_index,
        column_index=record.column_index,
        value_row_index=mapping.row_index if mapping.found else None,
        value_column_index=mapping.column_index if mapping.found else None,
        page_number=record.page_number,
        bbox=record.bbox,
        block_index=record.source_location.get("block_index"),
        reading_order=record.source_location.get("reading_order"),
        source_content_type=record.source_content_type,
        locator_method=method,
        locator_confidence=confidence,
        notes=notes,
        metadata={
            "project1_record_id": record.record_id,
            "project1_status": record.status,
            "project1_flags": list(record.flags),
        },
    )


def _values_equal(reported: float, computed: float) -> bool:
    tolerance = max(1e-9, abs(reported) * 1e-9)
    return abs(reported - computed) <= tolerance


@dataclass
class RecordValidation:
    record_id: str
    document_id: str
    file_type: str
    indicator: str | None
    raw_value: Any
    parsed_value: float | None
    unit: str | None
    raw_expression: str
    source_text: str
    detection_limit: str | None
    anchor_location: SourceLocation
    value_cell: ValueCellMapping
    expressions: list[ExpressionCandidate] = field(default_factory=list)
    calculation: CalculationInfo | None = None
    validation_status: str = VALIDATION_UNVERIFIED
    review_reasons: list[str] = field(default_factory=list)
    issues: list[AuditIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "document_id": self.document_id,
            "file_type": self.file_type,
            "indicator": self.indicator,
            "input": {
                "value": self.raw_value,
                "parsed_value": self.parsed_value,
                "unit": self.unit,
                "raw_expression": self.raw_expression,
                "source_text": self.source_text,
                "detection_limit": self.detection_limit,
            },
            "anchor_location": self.anchor_location.to_dict(),
            "value_cell": self.value_cell.to_dict(),
            "expressions": [item.to_dict() for item in self.expressions],
            "calculation": self.calculation.to_dict() if self.calculation else None,
            "validation_status": self.validation_status,
            "review_reasons": list(self.review_reasons),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class MathValidationResult:
    batch_id: str
    batch_path: str
    generated_at: str
    records: list[RecordValidation]
    issues: list[AuditIssue] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        status_counts = {status: 0 for status in VALIDATION_STATUSES}
        for record in self.records:
            status_counts[record.validation_status] = (
                status_counts.get(record.validation_status, 0) + 1
            )
        return {
            "record_count": len(self.records),
            "verified_count": status_counts[VALIDATION_VERIFIED],
            "unverified_count": status_counts[VALIDATION_UNVERIFIED],
            "error_count": status_counts[VALIDATION_ERROR],
            "issue_count": len(self.issues),
            "value_cell_mapped_count": sum(
                1 for record in self.records if record.value_cell.found
            ),
            "anchor_value_distinct_count": sum(
                1
                for record in self.records
                if record.value_cell.found
                and record.value_cell.row_index is not None
                and record.value_cell.column_index is not None
                and (
                    record.value_cell.row_index != record.anchor_location.row_index
                    or record.value_cell.column_index
                    != record.anchor_location.column_index
                )
            ),
            "expression_count": sum(
                len(record.expressions) for record in self.records
            ),
            "no_calculation_expression_count": sum(
                1
                for record in self.records
                if "no_calculation_expression" in record.review_reasons
            ),
            "validation_status_counts": status_counts,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "batch_id": self.batch_id,
            "batch_path": self.batch_path,
            "generated_at": self.generated_at,
            "summary": self.summary(),
            "records": [record.to_dict() for record in self.records],
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _validate_record(
    record: EnvironmentalRecordView,
    batch: Project1Batch,
) -> RecordValidation:
    table: TableView | None = None
    if record.table_index is not None:
        table = batch.table(record.document_id, record.table_index)

    parsed_value = _parse_numeric(record.value)
    if table is None:
        mapping = ValueCellMapping(found=False, reason="table_not_found")
    else:
        mapping = map_value_cell(record, table, parsed_value)

    location = _build_location(record, batch, mapping, table is not None)

    expressions: list[ExpressionCandidate] = []
    seen: set[str] = set()
    for text in (record.raw_expression, record.source_text):
        for candidate in detect_calculation_expressions(text):
            key = (candidate.rhs or candidate.text).strip()
            if key in seen:
                continue
            seen.add(key)
            expressions.append(candidate)

    review_reasons: list[str] = []
    if table is None:
        review_reasons.append("table_not_found")
    elif not mapping.found:
        review_reasons.append(mapping.reason or "value_cell_not_verified")
    if parsed_value is None:
        if record.detection_limit:
            review_reasons.append("detection_limit_no_numeric_value")
        else:
            review_reasons.append("missing_numeric_value")

    issues: list[AuditIssue] = []
    validation_status = VALIDATION_UNVERIFIED
    calculation: CalculationInfo | None = None

    if not expressions:
        review_reasons.append("no_calculation_expression")
        calculation = CalculationInfo(
            reported_value=parsed_value,
            unit=record.unit,
            verification_status=VERIFICATION_NOT_ATTEMPTED,
            notes=["no_calculation_expression"],
            metadata={
                "raw_value": record.value,
                "detection_limit": record.detection_limit,
            },
        )
    else:
        verified_any = False
        evaluable_any = False
        mismatch_found = False
        for expression_index, expression in enumerate(expressions):
            target = expression.rhs or expression.text
            computed, error = evaluate_expression(target)
            if computed is None:
                review_reasons.append("expression_not_evaluable")
                if calculation is None:
                    calculation = CalculationInfo(
                        formula=expression.text,
                        substituted_formula=expression.rhs,
                        reported_value=parsed_value,
                        unit=record.unit,
                        verification_status=VERIFICATION_NOT_ATTEMPTED,
                        verification_method=None,
                        verification_detail=error,
                        notes=[f"expression_not_evaluable: {error}"],
                    )
                continue

            evaluable_any = True
            verification_detail = f"{target} = {computed}"
            calculation = CalculationInfo(
                formula=expression.text,
                substituted_formula=expression.rhs,
                reported_value=parsed_value,
                computed_value=computed,
                unit=record.unit,
                verification_status=VERIFICATION_VERIFIED,
                verification_method="ast_decimal",
                verification_detail=verification_detail,
            )

            if parsed_value is None:
                review_reasons.append("reported_value_missing")
                continue
            if _values_equal(parsed_value, computed):
                verified_any = True
                continue

            calculation = CalculationInfo(
                formula=expression.text,
                substituted_formula=expression.rhs,
                reported_value=parsed_value,
                computed_value=computed,
                unit=record.unit,
                verification_status=VERIFICATION_VERIFIED,
                verification_method="ast_decimal",
                verification_detail=verification_detail,
            )
            issue = AuditIssue(
                issue_id=f"calc-{record.record_id}-{expression_index}",
                issue_type=ISSUE_TYPE_CALCULATION,
                severity=SEVERITY_ERROR,
                description=(
                    f"{record.indicator or '指标'} 的计算结果与报告值不一致："
                    f"报告值 {parsed_value}，计算结果 {computed}。"
                ),
                original_text=record.raw_expression,
                location=location,
                calculation=calculation,
                needs_manual_review=True,
                review_reasons=["calculation_mismatch"],
                suggestion="请核对计算表达式和报告值。",
            )
            issues.append(issue)
            mismatch_found = True
            break

        if mismatch_found:
            validation_status = VALIDATION_ERROR
        elif verified_any:
            validation_status = VALIDATION_VERIFIED
        else:
            validation_status = VALIDATION_UNVERIFIED
        if not evaluable_any and not review_reasons:
            review_reasons.append("no_evaluable_expression")

    review_reasons = list(dict.fromkeys(review_reasons))
    return RecordValidation(
        record_id=record.record_id,
        document_id=record.document_id,
        file_type=record.file_type,
        indicator=record.indicator,
        raw_value=record.value,
        parsed_value=parsed_value,
        unit=record.unit,
        raw_expression=record.raw_expression,
        source_text=record.source_text,
        detection_limit=record.detection_limit,
        anchor_location=location,
        value_cell=mapping,
        expressions=expressions,
        calculation=calculation,
        validation_status=validation_status,
        review_reasons=review_reasons,
        issues=issues,
    )


def validate_batch(batch: Project1Batch) -> MathValidationResult:
    records = [
        _validate_record(record, batch)
        for record in batch.environmental_records
    ]
    issues = [issue for record in records for issue in record.issues]
    return MathValidationResult(
        batch_id=batch.batch_id,
        batch_path=str(batch.path),
        generated_at=utc_now_iso(),
        records=records,
        issues=issues,
    )


def save_validation_result(
    result: MathValidationResult,
    path: str | Path,
) -> Path:
    import json

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target
