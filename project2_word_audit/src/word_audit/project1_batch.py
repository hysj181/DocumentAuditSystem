"""Read-only access to project one extraction batches.

This module only reads ``batch.json`` and the metadata already extracted by
project one. It never writes to the batch, Word or PDF files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSION = "1.0"


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class BatchRecord:
    document_id: str
    source_file: str
    file_type: str
    content_type: str
    text: str
    location: dict[str, Any]
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BatchRecord":
        return cls(
            document_id=str(data.get("document_id", "")),
            source_file=str(data.get("source_file", "")),
            file_type=str(data.get("file_type", "")),
            content_type=str(data.get("content_type", "")),
            text=str(data.get("text", "")),
            location=dict(data.get("location") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    @property
    def table_index(self) -> int | None:
        return _as_int(self.location.get("table_index"))

    @property
    def paragraph_index(self) -> int | None:
        return _as_int(self.location.get("paragraph_index"))

    @property
    def page_number(self) -> int | None:
        return _as_int(self.location.get("page_number"))

    @property
    def rows(self) -> list[list[str]]:
        rows = self.metadata.get("rows")
        if not isinstance(rows, list):
            return []
        return [list(row) for row in rows if isinstance(row, list)]

    @property
    def cells(self) -> list[dict[str, Any]]:
        cells = self.metadata.get("cells")
        if not isinstance(cells, list):
            return []
        return [dict(cell) for cell in cells if isinstance(cell, dict)]

    @property
    def headers(self) -> list[list[str | None]]:
        headers = self.metadata.get("headers")
        if not isinstance(headers, list):
            return []
        return [list(row) for row in headers if isinstance(row, list)]

    @property
    def header_row_count(self) -> int:
        return _as_int(self.metadata.get("header_row_count")) or 0


@dataclass(frozen=True)
class TableView:
    document_id: str
    source_file: str
    file_type: str
    table_index: int
    page_number: int | None
    rows: list[list[str]]
    cells: list[dict[str, Any]]
    headers: list[list[str | None]]
    header_row_count: int
    location: dict[str, Any]
    metadata: dict[str, Any]

    @classmethod
    def from_record(cls, record: BatchRecord) -> "TableView":
        table_index = record.table_index
        if table_index is None:
            table_index = _as_int(record.metadata.get("table_index"))
        if table_index is None:
            table_index = _as_int(record.metadata.get("page_table_index"))
        if table_index is None:
            raise ValueError("table record has no table_index")
        return cls(
            document_id=record.document_id,
            source_file=record.source_file,
            file_type=record.file_type,
            table_index=table_index,
            page_number=record.page_number,
            rows=record.rows,
            cells=record.cells,
            headers=record.headers,
            header_row_count=record.header_row_count,
            location=dict(record.location),
            metadata=dict(record.metadata),
        )

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return max((len(row) for row in self.rows), default=0)

    def cell_text(self, row_index: int, column_index: int) -> str | None:
        if row_index < 0 or row_index >= len(self.rows):
            return None
        row = self.rows[row_index]
        if column_index < 0 or column_index >= len(row):
            return None
        return str(row[column_index])


@dataclass(frozen=True)
class DocumentView:
    document_id: str
    source_name: str
    source_file: str
    file_type: str
    records: list[BatchRecord]
    metadata: dict[str, Any]
    tables: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentView":
        return cls(
            document_id=str(data.get("document_id", "")),
            source_name=str(data.get("source_name", "")),
            source_file=str(data.get("source_file", "")),
            file_type=str(data.get("file_type", "")),
            records=[
                BatchRecord.from_dict(item)
                for item in data.get("records", [])
                if isinstance(item, dict)
            ],
            metadata=dict(data.get("metadata") or {}),
            tables=[
                dict(item)
                for item in data.get("tables", [])
                if isinstance(item, dict)
            ],
        )

    def format_record(self, table_index: int) -> BatchRecord | None:
        for record in self.records:
            if record.content_type == "table" and record.table_index == table_index:
                return record
        return None

    def table(self, table_index: int) -> TableView | None:
        record = self.format_record(table_index)
        if record is None:
            return None
        return TableView.from_record(record)


@dataclass(frozen=True)
class EnvironmentalRecordView:
    record_id: str
    category: str
    subcategory: str | None
    document_id: str
    source_file: str
    file_type: str
    indicator: str | None
    value: Any
    unit: str | None
    time: str | None
    point: str | None
    detection_limit: str | None
    source_location: dict[str, Any]
    source_content_type: str
    source_text: str
    raw_expression: str
    flags: list[str]
    status: str
    confidence: float | None
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvironmentalRecordView":
        confidence = data.get("confidence")
        return cls(
            record_id=str(data.get("record_id", "")),
            category=str(data.get("category", "")),
            subcategory=data.get("subcategory"),
            document_id=str(data.get("document_id", "")),
            source_file=str(data.get("source_file", "")),
            file_type=str(data.get("file_type", "")),
            indicator=data.get("indicator"),
            value=data.get("value"),
            unit=data.get("unit"),
            time=data.get("time"),
            point=data.get("point"),
            detection_limit=data.get("detection_limit"),
            source_location=dict(data.get("source_location") or {}),
            source_content_type=str(data.get("source_content_type", "")),
            source_text=str(data.get("source_text", "")),
            raw_expression=str(data.get("raw_expression", "")),
            flags=list(data.get("flags", [])),
            status=str(data.get("status", "")),
            confidence=float(confidence) if confidence is not None else None,
            metadata=dict(data.get("metadata") or {}),
        )

    @property
    def table_index(self) -> int | None:
        return _as_int(self.source_location.get("table_index"))

    @property
    def row_index(self) -> int | None:
        return _as_int(self.source_location.get("row_index"))

    @property
    def column_index(self) -> int | None:
        return _as_int(self.source_location.get("column_index"))

    @property
    def page_number(self) -> int | None:
        return _as_int(self.source_location.get("page_number"))

    @property
    def bbox(self) -> list[float] | None:
        bbox = self.source_location.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            return None
        return [float(item) for item in bbox]


@dataclass(frozen=True)
class Project1Batch:
    batch_id: str
    schema_version: str
    extracted_at: str | None
    documents: list[DocumentView]
    environmental_records: list[EnvironmentalRecordView]
    environmental: dict[str, Any]
    path: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    environmental_present: bool = False

    @classmethod
    def load(cls, path: str | Path) -> "Project1Batch":
        source = Path(path).expanduser()
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"batch JSON must be an object: {source}")
        schema_version = str(payload.get("schema_version", ""))
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported batch schema_version: {schema_version!r}"
            )
        documents_data = payload.get("documents")
        if not isinstance(documents_data, list):
            raise ValueError("batch JSON must contain a 'documents' array")
        environmental_present = isinstance(payload.get("environmental"), dict)
        environmental = payload.get("environmental")
        if not isinstance(environmental, dict):
            environmental = {}
        records_data = environmental.get("records")
        if not isinstance(records_data, list):
            records_data = []
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return cls(
            batch_id=str(payload.get("batch_id", "")),
            schema_version=schema_version,
            extracted_at=payload.get("extracted_at"),
            documents=[
                DocumentView.from_dict(item)
                for item in documents_data
                if isinstance(item, dict)
            ],
            environmental_records=[
                EnvironmentalRecordView.from_dict(item)
                for item in records_data
                if isinstance(item, dict)
            ],
            environmental=dict(environmental),
            path=source.resolve(),
            metadata=dict(metadata),
            environmental_present=environmental_present,
        )

    def document(self, document_id: str) -> DocumentView | None:
        for document in self.documents:
            if document.document_id == document_id:
                return document
        return None

    def table(self, document_id: str, table_index: int) -> TableView | None:
        document = self.document(document_id)
        if document is None:
            return None
        return document.table(table_index)
