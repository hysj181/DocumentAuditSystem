from __future__ import annotations

import uuid
from pathlib import Path

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from doc_extractor.core.models import (
    FILE_TYPE_WORD,
    DocumentResult,
    ExtractionRecord,
    Location,
)
from doc_extractor.core.patterns import entities_as_dicts


def _is_heading(style_name: str) -> bool:
    normalized = style_name.strip().casefold()
    if not normalized:
        return False
    return (
        normalized.startswith("heading")
        or normalized.startswith("title")
        or normalized.startswith("标题")
        or normalized in {"title", "subtitle", "副标题"}
    )


def _paragraph_record(
    paragraph: Paragraph,
    *,
    document_id: str,
    source_file: str,
    paragraph_index: int,
    document_order: int,
) -> ExtractionRecord | None:
    text = paragraph.text.strip()
    if not text:
        return None

    try:
        style_name = paragraph.style.name if paragraph.style is not None else ""
    except (AttributeError, KeyError):
        style_name = ""

    content_type = "heading" if _is_heading(style_name) else "paragraph"
    return ExtractionRecord(
        document_id=document_id,
        source_file=source_file,
        file_type=FILE_TYPE_WORD,
        content_type=content_type,
        text=text,
        location=Location(paragraph_index=paragraph_index),
        metadata={
            "style_name": style_name,
            "document_order": document_order,
            "source": "word",
            "entities": entities_as_dicts(text),
        },
    )


def _table_record(
    table: Table,
    *,
    document_id: str,
    source_file: str,
    table_index: int,
    document_order: int,
) -> ExtractionRecord:
    rows: list[list[str]] = []
    cells: list[dict[str, object]] = []

    for row_index, row in enumerate(table.rows):
        row_values: list[str] = []
        for column_index, cell in enumerate(row.cells):
            cell_text = cell.text.strip()
            row_values.append(cell_text)
            cells.append(
                {
                    "row_index": row_index,
                    "column_index": column_index,
                    "text": cell_text,
                    "entities": entities_as_dicts(cell_text),
                }
            )
        rows.append(row_values)

    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    table_text = "\n".join("\t".join(row) for row in rows)

    return ExtractionRecord(
        document_id=document_id,
        source_file=source_file,
        file_type=FILE_TYPE_WORD,
        content_type="table",
        text=table_text,
        location=Location(table_index=table_index),
        metadata={
            "document_order": document_order,
            "row_count": row_count,
            "column_count": column_count,
            "rows": rows,
            "cells": cells,
            "source": "word",
            "entities": entities_as_dicts(table_text),
        },
    )


def parse_word(path: str | Path, document_id: str | None = None) -> DocumentResult:
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Word 文件不存在: {source_path}")

    document_id = document_id or uuid.uuid4().hex
    source_file = str(source_path)
    document = Document(str(source_path))

    records: list[ExtractionRecord] = []
    paragraph_count = 0
    table_count = 0
    document_order = 0

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            record = _paragraph_record(
                paragraph,
                document_id=document_id,
                source_file=source_file,
                paragraph_index=paragraph_count,
                document_order=document_order,
            )
            paragraph_count += 1
            if record is not None:
                records.append(record)
            document_order += 1
        elif isinstance(child, CT_Tbl):
            table = Table(child, document)
            records.append(
                _table_record(
                    table,
                    document_id=document_id,
                    source_file=source_file,
                    table_index=table_count,
                    document_order=document_order,
                )
            )
            table_count += 1
            document_order += 1

    return DocumentResult(
        document_id=document_id,
        source_file=source_file,
        file_type=FILE_TYPE_WORD,
        records=records,
        metadata={
            "paragraph_count": paragraph_count,
            "table_count": table_count,
            "content_block_count": document_order,
        },
    )
