from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from doc_extractor.core.table_models import TableData

FILE_TYPE_WORD = "word"
FILE_TYPE_PDF = "pdf"

CONTENT_TYPE_LABELS: dict[str, str] = {
    "heading": "标题",
    "paragraph": "段落",
    "table": "表格",
    "page_text": "页面文字",
    "text_block": "文本块",
    "ocr_page": "OCR 页面",
    "ocr_text": "OCR 文本",
}

ENTITY_TYPE_LABELS: dict[str, str] = {
    "integer": "整数",
    "decimal": "小数",
    "amount": "金额",
    "percentage": "百分比",
    "date": "日期",
}


@dataclass
class Location:
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    page_number: int | None = None
    bbox: list[float] | None = None
    block_index: int | None = None
    reading_order: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "paragraph_index": self.paragraph_index,
            "table_index": self.table_index,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "page_number": self.page_number,
            "bbox": self.bbox,
            "block_index": self.block_index,
            "reading_order": self.reading_order,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Location:
        allowed = {
            "paragraph_index",
            "table_index",
            "row_index",
            "column_index",
            "page_number",
            "bbox",
            "block_index",
            "reading_order",
        }
        return cls(**{key: value for key, value in data.items() if key in allowed})


def format_location(location: Location) -> str:
    parts: list[str] = []
    if location.page_number is not None:
        parts.append(f"第{location.page_number}页")
    if location.paragraph_index is not None:
        parts.append(f"段落[{location.paragraph_index}]")
    if location.table_index is not None:
        parts.append(f"表格[{location.table_index}]")
    if location.row_index is not None:
        parts.append(f"行[{location.row_index}]")
    if location.column_index is not None:
        parts.append(f"列[{location.column_index}]")
    if location.block_index is not None:
        parts.append(f"文本块[{location.block_index}]")
    if location.bbox:
        bbox_text = ", ".join(f"{value:.1f}" for value in location.bbox)
        parts.append(f"bbox=({bbox_text})")
    return " ".join(parts) if parts else "-"


@dataclass
class ExtractionRecord:
    document_id: str
    source_file: str
    file_type: str
    content_type: str
    text: str
    location: Location = field(default_factory=Location)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_file": self.source_file,
            "file_type": self.file_type,
            "content_type": self.content_type,
            "text": self.text,
            "location": self.location.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtractionRecord:
        return cls(
            document_id=data["document_id"],
            source_file=data["source_file"],
            file_type=data["file_type"],
            content_type=data["content_type"],
            text=data.get("text", ""),
            location=Location.from_dict(data.get("location", {})),
            metadata=data.get("metadata", {}),
        )

    def iter_entities(self) -> Iterator[tuple[dict[str, Any], Location]]:
        if self.content_type == "table":
            for cell in self.metadata.get("cells", []):
                cell_location = Location(
                    paragraph_index=self.location.paragraph_index,
                    table_index=self.location.table_index,
                    row_index=cell.get("row_index"),
                    column_index=cell.get("column_index"),
                    page_number=self.location.page_number,
                    bbox=cell.get("bbox", self.location.bbox),
                    block_index=self.location.block_index,
                )
                for entity in cell.get("entities", []):
                    yield entity, cell_location
            return

        for entity in self.metadata.get("entities", []):
            yield entity, self.location


@dataclass
class DocumentResult:
    document_id: str
    source_file: str
    file_type: str
    records: list[ExtractionRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tables: list[TableData] = field(default_factory=list)

    @property
    def source_name(self) -> str:
        return Path(self.source_file).name

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def succeeded(self) -> bool:
        return self.error is None

    def raw_text(self) -> str:
        page_records = [
            record
            for record in self.records
            if record.content_type in {"page_text", "ocr_page"} and record.text.strip()
        ]
        if page_records:
            return "\n\n".join(record.text.strip() for record in page_records)

        if self.file_type == FILE_TYPE_PDF:
            source_records = [
                record
                for record in self.records
                if record.content_type in {"text_block", "ocr_text", "table"}
            ]
        else:
            source_records = self.records

        return "\n".join(record.text.strip() for record in source_records if record.text.strip())

    def iter_entities(self) -> Iterator[tuple[ExtractionRecord, dict[str, Any], Location]]:
        for record in self.records:
            for entity, location in record.iter_entities():
                yield record, entity, location

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_name": self.source_name,
            "source_file": self.source_file,
            "file_type": self.file_type,
            "record_count": self.record_count,
            "table_count": self.table_count,
            "records": [record.to_dict() for record in self.records],
            "tables": [table.to_dict() for table in self.tables],
            "warnings": self.warnings,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentResult:
        return cls(
            document_id=data["document_id"],
            source_file=data["source_file"],
            file_type=data["file_type"],
            records=[ExtractionRecord.from_dict(item) for item in data.get("records", [])],
            warnings=data.get("warnings", []),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
            tables=[TableData.from_dict(item) for item in data.get("tables", [])],
        )


@dataclass
class BatchResult:
    documents: list[DocumentResult] = field(default_factory=list)

    @property
    def successes(self) -> list[DocumentResult]:
        return [document for document in self.documents if document.succeeded]

    @property
    def failures(self) -> list[DocumentResult]:
        return [document for document in self.documents if not document.succeeded]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_count": len(self.documents),
            "success_count": len(self.successes),
            "failure_count": len(self.failures),
            "documents": [document.to_dict() for document in self.documents],
        }
