from __future__ import annotations

import json

from doc_extractor.core.environmental_models import (
    ENV_MONITORING,
    FLAG_MISSING_UNIT,
    STATUS_PENDING_REVIEW,
    EnvironmentalExtractionResult,
    EnvironmentalRecord,
    EnterpriseGroup,
)


def _record() -> EnvironmentalRecord:
    return EnvironmentalRecord(
        record_id="rec-1",
        category=ENV_MONITORING,
        subcategory="wastewater",
        enterprise_id="ent-1",
        enterprise_name="测试企业有限公司",
        unified_social_credit_code="91310115MA1K4A2B3C",
        document_id="doc-1",
        source_file="C:/data/report.docx",
        file_type="word",
        indicator="COD",
        value=45.2,
        unit=None,
        time="2024-05-01",
        point="废水总排口",
        source_location={"paragraph_index": 3},
        source_content_type="paragraph",
        source_text="COD 45.2",
        raw_expression="COD 45.2",
        flags=[FLAG_MISSING_UNIT],
        status=STATUS_PENDING_REVIEW,
        confidence=0.8,
        metadata={"rule": "test"},
    )


def test_environmental_record_serialization_and_review_status() -> None:
    record = _record()
    payload = record.to_dict()

    assert payload["needs_review"] is True
    assert payload["status_label"] == "待人工核实"
    assert payload["flag_labels"] == ["缺少单位"]
    assert payload["category_label"] == "环境监测"
    assert json.dumps(payload, ensure_ascii=False)


def test_environmental_result_aggregation() -> None:
    enterprise = EnterpriseGroup(
        enterprise_id="ent-1",
        enterprise_name="测试企业有限公司",
        unified_social_credit_code="91310115MA1K4A2B3C",
        identity_status="verified",
        document_ids=["doc-1"],
        source_files=["C:/data/report.docx"],
    )
    result = EnvironmentalExtractionResult(
        enterprises=[enterprise],
        records=[_record()],
        warnings=["test warning"],
    )
    payload = result.to_dict()

    assert result.record_count == 1
    assert result.review_count == 1
    assert result.category_counts[ENV_MONITORING] == 1
    assert result.enterprise_for_document("doc-1") is enterprise
    assert payload["enterprise_count"] == 1
    assert payload["category_counts"]["环境监测"] == 1
    assert json.dumps(result.to_dict(), ensure_ascii=False)
