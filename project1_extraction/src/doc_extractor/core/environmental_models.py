from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ENV_MONITORING = "environmental_monitoring"
ENV_MANAGEMENT = "environmental_management"
ENV_STATISTICS = "environmental_statistics"

ENV_CATEGORIES = (ENV_MONITORING, ENV_MANAGEMENT, ENV_STATISTICS)

ENV_CATEGORY_LABELS: dict[str, str] = {
    ENV_MONITORING: "环境监测",
    ENV_MANAGEMENT: "环保管理",
    ENV_STATISTICS: "环境统计",
}

ENV_SUBCATEGORY_LABELS: dict[str, str] = {
    "wastewater": "废水",
    "waste_gas": "废气",
    "noise": "噪声",
    "permit": "排污许可",
    "ledger": "管理台账",
    "facility_operation": "治理设施运行",
    "water": "水资源",
    "energy": "能源",
    "pollutant": "污染物",
}

STATUS_COMPLETE = "complete"
STATUS_PENDING_REVIEW = "pending_review"

STATUS_LABELS = {
    STATUS_COMPLETE: "已提取",
    STATUS_PENDING_REVIEW: "待人工核实",
}

FLAG_MISSING_UNIT = "missing_unit"
FLAG_MISSING_VALUE = "missing_value"
FLAG_AMBIGUOUS_VALUE = "ambiguous_value"
FLAG_DETECTION_LIMIT = "detection_limit"
FLAG_MISSING_TIME = "missing_time"
FLAG_MISSING_POINT = "missing_point"
FLAG_ENTERPRISE_UNCLEAR = "enterprise_identity_unclear"
FLAG_ENTERPRISE_UNVERIFIED = "enterprise_identity_unverified"
FLAG_UNRECOGNIZED = "unrecognized"
FLAG_LOW_CONFIDENCE = "low_confidence"
FLAG_OCR_SOURCE = "ocr_source"
FLAG_TABLE_STRUCTURE_REVIEW = "table_structure_review"

FLAG_LABELS: dict[str, str] = {
    FLAG_MISSING_UNIT: "缺少单位",
    FLAG_MISSING_VALUE: "缺少数值",
    FLAG_AMBIGUOUS_VALUE: "数值存在歧义",
    FLAG_DETECTION_LIMIT: "检出限表达",
    FLAG_MISSING_TIME: "缺少时间",
    FLAG_MISSING_POINT: "缺少点位",
    FLAG_ENTERPRISE_UNCLEAR: "企业身份不明确",
    FLAG_ENTERPRISE_UNVERIFIED: "企业身份未完全核验",
    FLAG_UNRECOGNIZED: "无法识别",
    FLAG_LOW_CONFIDENCE: "低置信度",
    FLAG_OCR_SOURCE: "OCR 识别结果",
    FLAG_TABLE_STRUCTURE_REVIEW: "表格结构待核实",
}

ENTERPRISE_VERIFIED = "verified"
ENTERPRISE_NAME_ONLY = "name_only"
ENTERPRISE_NAME_MATCHED = "name_matched"
ENTERPRISE_UNCLEAR = "unclear"

ENTERPRISE_STATUS_LABELS: dict[str, str] = {
    ENTERPRISE_VERIFIED: "已核验统一社会信用代码",
    ENTERPRISE_NAME_ONLY: "仅按企业名称归并",
    ENTERPRISE_NAME_MATCHED: "名称匹配至已核验企业",
    ENTERPRISE_UNCLEAR: "企业身份不明确",
}


def status_from_flags(flags: list[str]) -> str:
    return STATUS_PENDING_REVIEW if flags else STATUS_COMPLETE


@dataclass
class EnterpriseGroup:
    enterprise_id: str
    enterprise_name: str | None
    unified_social_credit_code: str | None
    identity_status: str
    document_ids: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def document_count(self) -> int:
        return len(self.document_ids)

    @property
    def display_name(self) -> str:
        if self.enterprise_name:
            return self.enterprise_name
        return f"未识别企业（{self.enterprise_id[-6:]}）"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enterprise_id": self.enterprise_id,
            "enterprise_name": self.enterprise_name,
            "display_name": self.display_name,
            "unified_social_credit_code": self.unified_social_credit_code,
            "identity_status": self.identity_status,
            "document_count": self.document_count,
            "document_ids": self.document_ids,
            "source_files": self.source_files,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnterpriseGroup":
        return cls(
            enterprise_id=str(data.get("enterprise_id", "")),
            enterprise_name=data.get("enterprise_name"),
            unified_social_credit_code=data.get("unified_social_credit_code"),
            identity_status=str(data.get("identity_status", ENTERPRISE_UNCLEAR)),
            document_ids=list(data.get("document_ids", [])),
            source_files=list(data.get("source_files", [])),
            warnings=list(data.get("warnings", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class EnvironmentalRecord:
    record_id: str
    category: str
    subcategory: str | None
    enterprise_id: str
    enterprise_name: str | None
    unified_social_credit_code: str | None
    document_id: str
    source_file: str
    file_type: str
    indicator: str | None
    value: int | float | str | None
    unit: str | None
    time: str | None
    point: str | None
    source_location: dict[str, Any]
    source_content_type: str
    source_text: str
    raw_expression: str
    extraction_engine: str = "PaddleOCR"
    extraction_mode: str | None = None
    detection_limit: str | None = None
    flags: list[str] = field(default_factory=list)
    status: str = STATUS_PENDING_REVIEW
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def needs_review(self) -> bool:
        return self.status == STATUS_PENDING_REVIEW

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "category": self.category,
            "category_label": ENV_CATEGORY_LABELS.get(self.category, self.category),
            "subcategory": self.subcategory,
            "subcategory_label": ENV_SUBCATEGORY_LABELS.get(
                self.subcategory or "", self.subcategory
            ),
            "enterprise_id": self.enterprise_id,
            "enterprise_name": self.enterprise_name,
            "unified_social_credit_code": self.unified_social_credit_code,
            "document_id": self.document_id,
            "source_file": self.source_file,
            "file_type": self.file_type,
            "indicator": self.indicator,
            "value": self.value,
            "unit": self.unit,
            "time": self.time,
            "point": self.point,
            "detection_limit": self.detection_limit,
            "source_location": self.source_location,
            "source_content_type": self.source_content_type,
            "source_text": self.source_text,
            "raw_expression": self.raw_expression,
            "extraction_engine": self.extraction_engine,
            "extraction_mode": self.extraction_mode,
            "flags": self.flags,
            "flag_labels": [FLAG_LABELS.get(flag, flag) for flag in self.flags],
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "needs_review": self.needs_review,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvironmentalRecord":
        confidence = data.get("confidence", 0.5)
        if confidence is None:
            confidence = 0.5
        return cls(
            record_id=str(data.get("record_id", "")),
            category=str(data.get("category", "")),
            subcategory=data.get("subcategory"),
            enterprise_id=str(data.get("enterprise_id", "")),
            enterprise_name=data.get("enterprise_name"),
            unified_social_credit_code=data.get("unified_social_credit_code"),
            document_id=str(data.get("document_id", "")),
            source_file=str(data.get("source_file", "")),
            file_type=str(data.get("file_type", "")),
            indicator=data.get("indicator"),
            value=data.get("value"),
            unit=data.get("unit"),
            time=data.get("time"),
            point=data.get("point"),
            source_location=dict(data.get("source_location") or {}),
            source_content_type=str(data.get("source_content_type", "")),
            source_text=str(data.get("source_text", "")),
            raw_expression=str(data.get("raw_expression", "")),
            extraction_engine=str(data.get("extraction_engine", "PaddleOCR")),
            extraction_mode=data.get("extraction_mode"),
            detection_limit=data.get("detection_limit"),
            flags=list(data.get("flags", [])),
            status=str(data.get("status", STATUS_PENDING_REVIEW)),
            confidence=float(confidence),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class EnvironmentalExtractionResult:
    enterprises: list[EnterpriseGroup] = field(default_factory=list)
    records: list[EnvironmentalRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def review_count(self) -> int:
        return sum(1 for record in self.records if record.needs_review)

    @property
    def category_counts(self) -> dict[str, int]:
        return {
            category: sum(1 for record in self.records if record.category == category)
            for category in ENV_CATEGORIES
        }

    def records_by_category(self, category: str) -> list[EnvironmentalRecord]:
        return [record for record in self.records if record.category == category]

    def enterprise_for_document(self, document_id: str) -> EnterpriseGroup | None:
        for enterprise in self.enterprises:
            if document_id in enterprise.document_ids:
                return enterprise
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_count": self.record_count,
            "review_count": self.review_count,
            "enterprise_count": len(self.enterprises),
            "category_counts": {
                ENV_CATEGORY_LABELS[category]: count
                for category, count in self.category_counts.items()
            },
            "enterprises": [enterprise.to_dict() for enterprise in self.enterprises],
            "records": [record.to_dict() for record in self.records],
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvironmentalExtractionResult":
        return cls(
            enterprises=[
                EnterpriseGroup.from_dict(item)
                for item in data.get("enterprises", [])
            ],
            records=[
                EnvironmentalRecord.from_dict(item)
                for item in data.get("records", [])
            ],
            warnings=list(data.get("warnings", [])),
        )
