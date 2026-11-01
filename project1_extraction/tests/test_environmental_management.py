from __future__ import annotations

from pathlib import Path

from docx import Document

from doc_extractor.core.environmental_models import (
    ENV_MANAGEMENT,
    FLAG_MISSING_TIME,
    FLAG_MISSING_UNIT,
)
from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.extractor import extract_document


def _environmental_result(path: Path):
    document = extract_document(path)
    assert document.error is None
    return extract_environmental_data([document])


def _find(records, indicator: str):
    matches = [record for record in records if record.indicator == indicator]
    assert matches, f"未找到指标 {indicator}"
    return matches[0]


def test_management_permit_and_facility_records(
    environmental_word_file: Path,
) -> None:
    result = _environmental_result(environmental_word_file)
    management = result.records_by_category(ENV_MANAGEMENT)
    assert management

    permit_number = _find(management, "排污许可证编号")
    assert permit_number.value == "91310115MA1K4A2B3C"
    assert permit_number.unit is None
    assert permit_number.flags == []
    assert permit_number.source_location["paragraph_index"] is not None

    validity = _find(management, "排污许可证有效期")
    assert validity.value == "2027-12-31"
    assert validity.time == "2027-12-31"
    assert validity.unit is None

    runtime = _find(management, "设施运行时间")
    assert runtime.value == 8
    assert runtime.unit == "h"
    assert FLAG_MISSING_TIME in runtime.flags

    dosage = _find(management, "药剂投加量")
    assert dosage.value == 12
    assert dosage.unit == "kg"
    assert dosage.subcategory == "ledger"


def test_management_missing_unit_is_not_auto_filled(tmp_path: Path) -> None:
    path = tmp_path / "management_missing.docx"
    document = Document()
    document.add_heading("测试企业有限公司 环保管理台账", level=1)
    document.add_paragraph("企业名称：测试企业有限公司")
    document.add_paragraph("统一社会信用代码：91310115MA1K4A2B3C")
    document.add_paragraph("治理设施运行时间 8")
    document.add_paragraph("药剂投加量 12")
    document.save(path)

    result = _environmental_result(path)
    management = result.records_by_category(ENV_MANAGEMENT)

    runtime = _find(management, "设施运行时间")
    assert runtime.value == 8
    assert runtime.unit is None
    assert FLAG_MISSING_UNIT in runtime.flags

    dosage = _find(management, "药剂投加量")
    assert dosage.value == 12
    assert dosage.unit is None
    assert FLAG_MISSING_UNIT in dosage.flags
