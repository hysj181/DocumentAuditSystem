from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.paddle_structure import paddle_structure_available
from doc_extractor.core.pdf_parser import parse_pdf
from pdf_table_special.support import SPECIAL_STANDARD_ANSWERS

REAL_PADDLE_ENABLED = (
    os.environ.get("RUN_PADDLE_STRUCTURE_TESTS", "").strip() == "1"
)
SAMPLE = Path(__file__).resolve().parent / "samples" / "scanned_special_values.pdf"


@pytest.mark.skipif(
    not REAL_PADDLE_ENABLED
    or not paddle_structure_available()
    or not SAMPLE.exists(),
    reason="设置 RUN_PADDLE_STRUCTURE_TESTS=1 且安装 PaddleOCR 后运行真实模型测试",
)
def test_real_paddle_scanned_special_values_table() -> None:
    result = parse_pdf(SAMPLE, dpi=200)

    assert result.error is None
    assert result.metadata["table_count"] == 1
    assert result.metadata["structure_used"] is True
    table = result.tables[0]
    assert table.rows == len(SPECIAL_STANDARD_ANSWERS) + 1
    assert table.columns == 5
    assert table.header_row_count == 1
    assert table.page_number == 1
    assert table.table_bbox is not None
    assert table.needs_review is True

    environmental = extract_environmental_data([result])
    assert environmental.record_count == len(SPECIAL_STANDARD_ANSWERS)
    for expected in SPECIAL_STANDARD_ANSWERS:
        candidates = [
            record
            for record in environmental.records
            if record.indicator == expected["indicator"]
            and record.value == expected["value"]
            and (record.detection_limit or "") == (expected["detection_limit"] or "")
        ]
        assert candidates, f"缺少记录: {expected['indicator']} {expected['value']}"
        record = candidates[0]
        if expected["indicator"] != "噪声":
            assert record.unit == expected["unit"]
        else:
            assert record.unit in {"dB", "dB(A)"}
        assert expected["point"] in (record.point or "")
        assert record.time == expected["time"]
        assert record.source_location["row_index"] == expected["row_index"]
        assert record.source_location["column_index"] == 1
