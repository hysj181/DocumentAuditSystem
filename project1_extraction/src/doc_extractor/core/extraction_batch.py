from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from doc_extractor.core.environmental_models import EnvironmentalExtractionResult
from doc_extractor.core.models import DocumentResult


def new_batch_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}_{uuid.uuid4().hex[:8]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExtractionBatch:
    documents: list[DocumentResult] = field(default_factory=list)
    environmental: EnvironmentalExtractionResult = field(
        default_factory=EnvironmentalExtractionResult
    )
    batch_id: str = field(default_factory=new_batch_id)
    extracted_at: str = field(default_factory=utc_now_iso)

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def record_count(self) -> int:
        return sum(document.record_count for document in self.documents)

    @property
    def source_files(self) -> list[str]:
        return [document.source_file for document in self.documents]

    def to_dict(self) -> dict[str, Any]:
        from doc_extractor.core.exporters import build_export_payload

        return build_export_payload(
            self.documents,
            self.environmental,
            batch_id=self.batch_id,
            extracted_at=self.extracted_at,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractionBatch":
        environmental_data = data.get("environmental")
        environmental = (
            EnvironmentalExtractionResult.from_dict(environmental_data)
            if isinstance(environmental_data, dict)
            else EnvironmentalExtractionResult()
        )
        return cls(
            documents=[
                DocumentResult.from_dict(item) for item in data.get("documents", [])
            ],
            environmental=environmental,
            batch_id=str(data.get("batch_id") or new_batch_id()),
            extracted_at=str(
                data.get("extracted_at")
                or data.get("exported_at")
                or utc_now_iso()
            ),
        )
