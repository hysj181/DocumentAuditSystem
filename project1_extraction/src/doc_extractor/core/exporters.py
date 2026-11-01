from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from doc_extractor.core.environmental_models import (
    ENTERPRISE_STATUS_LABELS,
    ENV_CATEGORY_LABELS,
    ENV_SUBCATEGORY_LABELS,
    STATUS_LABELS,
    EnvironmentalExtractionResult,
)
from doc_extractor.core.models import DocumentResult, Location, format_location

SCHEMA_VERSION = "1.0"
EXCEL_MAX_CELL_LENGTH = 32767


def _output_path(path: str | Path, default_suffix: str) -> Path:
    output = Path(path).expanduser()
    if output.suffix == "":
        output = output.with_suffix(default_suffix)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _guard_original_files(output: Path, documents: Sequence[DocumentResult]) -> None:
    normalized_output = str(output).casefold()
    for document in documents:
        if str(Path(document.source_file).resolve()).casefold() == normalized_output:
            raise ValueError("导出路径不能与原始文件相同，请选择其他文件名。")


def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    if len(text) > EXCEL_MAX_CELL_LENGTH:
        text = text[: EXCEL_MAX_CELL_LENGTH - 3] + "..."
    return text


def _clean_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return _clean_text(value)


def build_export_payload(
    documents: Sequence[DocumentResult],
    environmental: EnvironmentalExtractionResult | None = None,
    *,
    batch_id: str | None = None,
    extracted_at: str | None = None,
) -> dict[str, Any]:
    tables = [table for document in documents for table in document.tables]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(documents),
        "table_count": len(tables),
        "documents": [document.to_dict() for document in documents],
        "tables": [table.to_dict() for table in tables],
    }
    if batch_id is not None:
        payload["batch_id"] = batch_id
    if extracted_at is not None:
        payload["extracted_at"] = extracted_at
    if environmental is not None:
        payload["environmental"] = environmental.to_dict()
    return payload


def export_json(
    documents: Sequence[DocumentResult],
    path: str | Path,
    environmental: EnvironmentalExtractionResult | None = None,
    *,
    batch_id: str | None = None,
    extracted_at: str | None = None,
) -> Path:
    output = _output_path(path, ".json")
    _guard_original_files(output, documents)
    payload = build_export_payload(
        documents,
        environmental,
        batch_id=batch_id,
        extracted_at=extracted_at,
    )
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def _md_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("|", "\\|").replace("\n", "<br>")


def _md_value(value: Any) -> str:
    if value is None:
        return ""
    return _md_text(value)


def _table_rows_from_record(record: Any) -> list[list[str]]:
    rows = record.metadata.get("rows")
    if rows:
        return [[str(value) if value is not None else "" for value in row] for row in rows]
    unified = record.metadata.get("unified_table")
    if isinstance(unified, dict) and unified.get("cells"):
        from doc_extractor.core.table_models import TableData

        return TableData.from_dict(unified).grid()
    return []


def _markdown_table(rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["（空表格）", ""]
    column_count = max(len(row) for row in rows)
    normalized = [
        [*row, *["" for _ in range(column_count - len(row))]]
        for row in rows
    ]
    lines = [
        "| " + " | ".join(_md_text(cell) for cell in normalized[0]) + " |",
        "| " + " | ".join("---" for _ in range(column_count)) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(_md_text(cell) for cell in row) + " |")
    return lines


def _visible_records(document: DocumentResult) -> list[Any]:
    has_text_blocks = any(
        record.content_type == "text_block" for record in document.records
    )
    has_ocr_text = any(
        record.content_type == "ocr_text" for record in document.records
    )
    visible = []
    for record in document.records:
        if record.content_type == "page_text" and has_text_blocks:
            continue
        if record.content_type == "ocr_page" and has_ocr_text:
            continue
        visible.append(record)
    return visible


def build_markdown(
    documents: Sequence[DocumentResult],
    environmental: EnvironmentalExtractionResult | None = None,
    *,
    batch_id: str | None = None,
    extracted_at: str | None = None,
) -> str:
    lines: list[str] = ["# 综合环境数据提取结果", ""]
    if batch_id:
        lines.append(f"- 批次 ID：`{batch_id}`")
    if extracted_at:
        lines.append(f"- 提取时间：{extracted_at}")
    lines.append(f"- 文档数量：{len(documents)}")
    lines.append(
        f"- 表格数量：{sum(document.table_count for document in documents)}"
    )
    if environmental is not None:
        lines.append(f"- 环境记录数：{environmental.record_count}")
    lines.extend(["", "---", ""])

    for document in documents:
        lines.extend(
            [
                f"## 文件：{_md_text(document.source_name)}",
                "",
                f"- 文件路径：`{_md_text(document.source_file)}`",
                f"- 文件类型：{document.file_type}",
                f"- 记录数：{document.record_count}",
                f"- 表格数：{document.table_count}",
            ]
        )
        if document.error:
            lines.append(f"- 解析错误：{_md_text(document.error)}")
        if document.warnings:
            lines.append("- 提示信息：")
            lines.extend(f"  - {_md_text(warning)}" for warning in document.warnings)
        lines.append("")

        for record in _visible_records(document):
            location = format_location(record.location)
            if record.content_type == "table":
                lines.extend(
                    [
                        f"### 表格 {record.location.table_index}",
                        "",
                        f"来源：{_md_text(location)}",
                        "",
                    ]
                )
                rows = _table_rows_from_record(record)
                lines.extend(_markdown_table(rows))
                lines.append("")
                continue

            text = record.text.strip()
            if not text:
                continue
            if record.content_type == "heading":
                lines.extend(
                    [
                        f"### {_md_text(text)}",
                        "",
                        f"来源：{_md_text(location)}",
                        "",
                    ]
                )
            elif record.content_type in {"page_text", "ocr_page"}:
                lines.extend(
                    [
                        f"#### 页面文字（{_md_text(location)}）",
                        "",
                        _md_text(text),
                        "",
                    ]
                )
            elif record.content_type in {"text_block", "ocr_text"}:
                lines.append(f"- {_md_text(text)}（来源：{_md_text(location)}）")
            else:
                lines.extend(
                    [
                        _md_text(text),
                        "",
                        f"来源：{_md_text(location)}",
                        "",
                    ]
                )
        if document.records and document.records[-1].content_type in {
            "text_block",
            "ocr_text",
        }:
            lines.append("")
        lines.extend(["---", ""])

    if environmental is not None:
        lines.extend(["## 企业汇总", ""])
        if environmental.enterprises:
            lines.extend(
                [
                    "| 企业 ID | 企业名称 | 统一社会信用代码 | 身份状态 | 文档数 |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for enterprise in environmental.enterprises:
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            _md_text(enterprise.enterprise_id),
                            _md_text(enterprise.display_name),
                            _md_text(enterprise.unified_social_credit_code),
                            _md_text(
                                ENTERPRISE_STATUS_LABELS.get(
                                    enterprise.identity_status,
                                    enterprise.identity_status,
                                )
                            ),
                            str(enterprise.document_count),
                        ]
                    )
                    + " |"
                )
        else:
            lines.append("（无企业数据）")
        lines.extend(["", "## 环境数据记录", ""])
        if environmental.records:
            lines.extend(
                [
                    "| 企业 | 类别 | 子类别 | 指标 | 数值 | 单位 | 时间 | 点位 | 检出限 | 状态 | 来源 | 原始表达 |",
                    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for record in environmental.records:
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            _md_text(record.enterprise_name or record.enterprise_id),
                            _md_text(
                                ENV_CATEGORY_LABELS.get(
                                    record.category, record.category
                                )
                            ),
                            _md_text(
                                ENV_SUBCATEGORY_LABELS.get(
                                    record.subcategory or "",
                                    record.subcategory or "",
                                )
                            ),
                            _md_text(record.indicator),
                            _md_value(record.value),
                            _md_text(record.unit),
                            _md_text(record.time),
                            _md_text(record.point),
                            _md_text(record.detection_limit),
                            _md_text(
                                STATUS_LABELS.get(record.status, record.status)
                            ),
                            _md_text(
                                format_location(
                                    Location.from_dict(record.source_location)
                                )
                            ),
                            _md_text(record.raw_expression),
                        ]
                    )
                    + " |"
                )
        else:
            lines.append("（无环境数据记录）")
        if environmental.warnings:
            lines.extend(["", "## 环境数据提示", ""])
            lines.extend(
                f"- {_md_text(warning)}" for warning in environmental.warnings
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def export_markdown(
    documents: Sequence[DocumentResult],
    path: str | Path,
    environmental: EnvironmentalExtractionResult | None = None,
    *,
    batch_id: str | None = None,
    extracted_at: str | None = None,
) -> Path:
    output = _output_path(path, ".md")
    _guard_original_files(output, documents)
    content = build_markdown(
        documents,
        environmental,
        batch_id=batch_id,
        extracted_at=extracted_at,
    )
    output.write_text(content, encoding="utf-8")
    return output


def _style_header(worksheet: Worksheet) -> None:
    fill = PatternFill("solid", fgColor="D9E2F3")
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
    worksheet.freeze_panes = "A2"


def _set_widths(worksheet: Worksheet, widths: Sequence[int]) -> None:
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width


def export_excel(
    documents: Sequence[DocumentResult],
    path: str | Path,
    environmental: EnvironmentalExtractionResult | None = None,
) -> Path:
    output = _output_path(path, ".xlsx")
    _guard_original_files(output, documents)

    workbook = Workbook()
    summary = workbook.active
    summary.title = "文件汇总"
    summary.append(["文档ID", "源文件", "文件类型", "记录数", "状态", "错误信息", "提示信息"])

    records_sheet = workbook.create_sheet("记录")
    records_sheet.append(["文档ID", "源文件", "文件类型", "内容类型", "文本", "位置", "元数据"])

    tables_sheet = workbook.create_sheet("表格数据")
    tables_sheet.append(
        [
            "文档ID",
            "源文件",
            "页码",
            "表格索引",
            "行索引",
            "列索引",
            "单元格文本",
            "表格ID",
            "提取引擎",
            "行跨度",
            "列跨度",
            "置信度",
            "待核实",
            "核实原因",
            "解析模式",
        ]
    )

    entities_sheet = workbook.create_sheet("实体信息")
    entities_sheet.append(["文档ID", "源文件", "实体类型", "实体文本", "实体值", "位置", "来源"])

    environmental_sheet = None
    enterprise_sheet = None
    if environmental is not None:
        environmental_sheet = workbook.create_sheet("环境数据")
        environmental_sheet.append(
            [
                "记录ID",
                "企业ID",
                "企业名称",
                "类别",
                "子类别",
                "文档ID",
                "源文件",
                "文件类型",
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
                "源文本",
                "元数据",
                "提取引擎",
                "解析模式",
            ]
        )
        enterprise_sheet = workbook.create_sheet("企业汇总")
        enterprise_sheet.append(
            [
                "企业ID",
                "企业名称",
                "统一社会信用代码",
                "身份状态",
                "文档数",
                "文档ID",
                "源文件",
                "提示信息",
            ]
        )

    for document in documents:
        summary.append(
            [
                document.document_id,
                _clean_text(document.source_file),
                document.file_type,
                document.record_count,
                "失败" if document.error else "成功",
                _clean_text(document.error or ""),
                _clean_text("\n".join(document.warnings)),
            ]
        )

        for record in document.records:
            records_sheet.append(
                [
                    document.document_id,
                    _clean_text(document.source_file),
                    record.file_type,
                    record.content_type,
                    _clean_text(record.text),
                    _clean_text(format_location(record.location)),
                    _clean_text(
                        json.dumps(record.metadata, ensure_ascii=False, default=str)
                    ),
                ]
            )

            if record.content_type != "table":
                continue

            table_id = record.metadata.get("table_id", "")
            extraction_engine = record.metadata.get("extraction_engine", "")
            extraction_mode = record.metadata.get("extraction_mode", "")
            needs_review = record.metadata.get("needs_review", False)
            review_reasons = "；".join(record.metadata.get("review_reasons", []))
            cells = record.metadata.get("cells") or []
            if cells:
                for cell in cells:
                    tables_sheet.append(
                        [
                            document.document_id,
                            _clean_text(document.source_file),
                            record.location.page_number,
                            record.location.table_index,
                            cell.get("row_index"),
                            cell.get("column_index"),
                            _clean_text(cell.get("text", "")),
                            table_id,
                            extraction_engine,
                            cell.get("row_span", 1),
                            cell.get("column_span", 1),
                            cell.get("confidence"),
                            "是" if needs_review else "否",
                            _clean_text(review_reasons),
                            extraction_mode,
                        ]
                    )
            else:
                rows = record.metadata.get("rows", [])
                for row_index, row in enumerate(rows):
                    for column_index, cell_text in enumerate(row):
                        tables_sheet.append(
                            [
                                document.document_id,
                                _clean_text(document.source_file),
                                record.location.page_number,
                                record.location.table_index,
                                row_index,
                                column_index,
                                _clean_text(cell_text),
                                table_id,
                                extraction_engine,
                                1,
                                1,
                                None,
                                "是" if needs_review else "否",
                                _clean_text(review_reasons),
                                extraction_mode,
                            ]
                        )

        for record, entity, location in document.iter_entities():
            if "ocr" in record.content_type:
                source = "OCR"
            elif record.content_type == "table":
                source = "表格"
            else:
                source = "正文"
            entities_sheet.append(
                [
                    document.document_id,
                    _clean_text(document.source_file),
                    entity.get("type", ""),
                    _clean_text(entity.get("text", "")),
                    _clean_value(entity.get("value")),
                    _clean_text(format_location(location)),
                    source,
                ]
            )

    if environmental is not None and environmental_sheet is not None:
        enterprise_names = {
            enterprise.enterprise_id: enterprise.display_name
            for enterprise in environmental.enterprises
        }
        for record in environmental.records:
            enterprise_name = record.enterprise_name or enterprise_names.get(
                record.enterprise_id, ""
            )
            environmental_sheet.append(
                [
                    record.record_id,
                    record.enterprise_id,
                    _clean_text(enterprise_name),
                    ENV_CATEGORY_LABELS.get(record.category, record.category),
                    ENV_SUBCATEGORY_LABELS.get(
                        record.subcategory or "", record.subcategory or ""
                    ),
                    record.document_id,
                    _clean_text(record.source_file),
                    record.file_type,
                    _clean_text(record.indicator or ""),
                    None if record.value is None else _clean_value(record.value),
                    _clean_text(record.unit or ""),
                    _clean_text(record.time or ""),
                    _clean_text(record.point or ""),
                    _clean_text(record.detection_limit or ""),
                    STATUS_LABELS.get(record.status, record.status),
                    _clean_text("；".join(record.flags)),
                    _clean_text(format_location(Location.from_dict(record.source_location))),
                    record.source_content_type,
                    _clean_text(record.raw_expression),
                    _clean_text(record.source_text),
                    _clean_text(
                        json.dumps(record.metadata, ensure_ascii=False, default=str)
                    ),
                    record.extraction_engine,
                    _clean_text(record.extraction_mode or ""),
                ]
            )

        if enterprise_sheet is not None:
            for enterprise in environmental.enterprises:
                enterprise_sheet.append(
                    [
                        enterprise.enterprise_id,
                        _clean_text(enterprise.enterprise_name or ""),
                        _clean_text(enterprise.unified_social_credit_code or ""),
                        enterprise.identity_status,
                        enterprise.document_count,
                        _clean_text("\n".join(enterprise.document_ids)),
                        _clean_text("\n".join(enterprise.source_files)),
                        _clean_text("\n".join(enterprise.warnings)),
                    ]
                )

    worksheet_settings = [
        (summary, [34, 52, 10, 10, 10, 40, 60]),
        (records_sheet, [34, 52, 10, 12, 80, 36, 80]),
        (tables_sheet, [34, 52, 8, 10, 8, 8, 40, 16, 26, 8, 8, 10, 8, 30, 14]),
        (entities_sheet, [34, 52, 12, 32, 18, 36, 8]),
    ]
    if environmental_sheet is not None:
        worksheet_settings.append(
            (
                environmental_sheet,
                [34, 22, 30, 12, 12, 34, 52, 8, 20, 14, 10, 12, 20, 12, 14, 30, 36, 12, 60, 80, 80, 14, 14],
            )
        )
    if enterprise_sheet is not None:
        worksheet_settings.append(
            (enterprise_sheet, [28, 34, 30, 22, 8, 60, 80, 80])
        )

    for worksheet, widths in worksheet_settings:
        _style_header(worksheet)
        _set_widths(worksheet, widths)
        worksheet.auto_filter.ref = worksheet.dimensions

    workbook.save(str(output))
    return output
