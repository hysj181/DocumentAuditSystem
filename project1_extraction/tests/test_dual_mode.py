from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from doc_extractor.core import pdf_parser as pdf_parser_module
from doc_extractor.core.cloud_api_parser import cloud_api_status, token_configured
from doc_extractor.core.device_status import local_device_status
from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.exporters import export_excel, export_json
from doc_extractor.core.extractor import extract_document
from doc_extractor.core.pdf_parser import (
    PARSE_MODE_CLOUD,
    PARSE_MODE_LOCAL,
    parse_pdf,
)
from dual_mode_support import (
    FakeCloudClient,
    FailingCloudClient,
    cloud_page,
    cloud_pruned_payload,
    make_cloud_pdf,
    make_markdown_cloud_page,
)
from table_test_support import (
    make_mixed_scanned_pdf,
    make_mixed_scanned_structure_parser,
)


def test_local_mode_returns_local_gpu_metadata_and_environment_data(
    tmp_path: Path,
) -> None:
    path = make_mixed_scanned_pdf(tmp_path / "mixed_scanned.pdf")
    result = parse_pdf(
        path,
        mode=PARSE_MODE_LOCAL,
        structure_parser=make_mixed_scanned_structure_parser(),
    )
    environmental = extract_environmental_data([result])

    assert result.error is None
    assert result.metadata["extraction_mode"] == PARSE_MODE_LOCAL
    assert result.metadata["extraction_engine"] == "PaddleOCR"
    assert result.metadata["local_ocr_used"] is True
    assert result.metadata["cloud_api_used"] is False
    assert result.tables[0].metadata["extraction_mode"] == PARSE_MODE_LOCAL
    assert environmental.record_count == 10
    for record in environmental.records:
        assert record.extraction_engine == "PaddleOCR"
        assert record.extraction_mode == PARSE_MODE_LOCAL
        assert record.to_dict()["extraction_mode"] == PARSE_MODE_LOCAL


def test_cloud_mode_with_fake_client_returns_unified_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = make_cloud_pdf(tmp_path / "cloud.pdf")
    client = FakeCloudClient()

    def forbidden_local_parser():
        raise AssertionError("云端模式不应初始化本地 PaddleOCR 模型")

    monkeypatch.setattr(
        "doc_extractor.core.paddle_structure.get_paddle_structure_parser",
        forbidden_local_parser,
    )
    result = parse_pdf(path, mode=PARSE_MODE_CLOUD, cloud_client=client)
    environmental = extract_environmental_data([result])

    assert result.error is None
    assert result.metadata["extraction_mode"] == PARSE_MODE_CLOUD
    assert result.metadata["extraction_engine"] == "PaddleOCR"
    assert result.metadata["local_ocr_used"] is False
    assert result.metadata["cloud_api_used"] is True
    assert result.metadata["cloud_model"] == "PP-StructureV3"
    assert result.metadata["page_count"] == 1
    assert result.metadata["table_count"] == 1
    assert client.calls
    assert client.calls[0]["model"] == "PP-StructureV3"

    table = result.tables[0]
    assert table.extraction_engine == "PaddleOCR PP-StructureV3"
    assert table.metadata["extraction_mode"] == PARSE_MODE_CLOUD
    assert table.rows == 5
    assert table.columns == 8
    assert table.table_bbox is not None

    assert environmental.record_count == 10
    for record in environmental.records:
        assert record.extraction_engine == "PaddleOCR"
        assert record.extraction_mode == PARSE_MODE_CLOUD
        assert record.source_location["page_number"] == 1


def test_cloud_token_missing_returns_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PADDLEOCR_ACCESS_TOKEN", raising=False)
    path = make_cloud_pdf(tmp_path / "cloud.pdf")

    result = parse_pdf(path, mode=PARSE_MODE_CLOUD)

    assert result.error is not None
    assert "PADDLEOCR_ACCESS_TOKEN" in result.error
    assert result.records == []
    assert result.tables == []
    assert result.metadata["extraction_mode"] == PARSE_MODE_CLOUD
    assert any("不会自动切换" in warning for warning in result.warnings)


def test_cloud_network_error_does_not_fallback_to_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = make_cloud_pdf(tmp_path / "cloud.pdf")
    client = FailingCloudClient("模拟断网")

    def forbidden_local_parser():
        raise AssertionError("云端失败时不应调用本地 PaddleOCR")

    monkeypatch.setattr(
        "doc_extractor.core.paddle_structure.get_paddle_structure_parser",
        forbidden_local_parser,
    )
    result = parse_pdf(path, mode=PARSE_MODE_CLOUD, cloud_client=client)

    assert result.error is not None
    assert "模拟断网" in result.error
    assert result.records == []
    assert result.tables == []
    assert any("未切换到本地 PaddleOCR" in warning for warning in result.warnings)


def test_cloud_token_is_not_written_to_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "unit-test-secret-token-should-not-appear"
    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", secret)
    path = make_cloud_pdf(tmp_path / "cloud.pdf")
    result = parse_pdf(
        path,
        mode=PARSE_MODE_CLOUD,
        cloud_client=FailingCloudClient("认证失败"),
    )
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)

    assert secret not in serialized
    assert secret not in (result.error or "")
    assert secret not in "\n".join(result.warnings)


def test_cloud_timeout_returns_clear_error(tmp_path: Path) -> None:
    class TimeoutClient:
        def parse_document(self, **kwargs):
            raise TimeoutError("模拟请求超时")

    path = make_cloud_pdf(tmp_path / "cloud.pdf")
    result = parse_pdf(
        path,
        mode=PARSE_MODE_CLOUD,
        cloud_client=TimeoutClient(),
        request_timeout=1,
        poll_timeout=2,
    )

    assert result.error is not None
    assert "超时" in result.error
    assert result.records == []
    assert result.tables == []


def test_official_cloud_client_can_be_created_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from doc_extractor.core.cloud_api_parser import create_cloud_client

    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", "dummy-token-for-client-creation")
    client = create_cloud_client(request_timeout=5, poll_timeout=10)
    client.close()


def test_cloud_mode_supports_multiple_pages(tmp_path: Path) -> None:
    path = make_cloud_pdf(tmp_path / "cloud_multi.pdf", pages=2)
    client = FakeCloudClient(
        pages=[
            cloud_page(pruned_result=cloud_pruned_payload()),
            cloud_page(markdown_text="第二页文字"),
        ]
    )
    result = parse_pdf(path, mode=PARSE_MODE_CLOUD, cloud_client=client)

    assert result.error is None
    assert result.metadata["page_count"] == 2
    page_numbers = {
        record.location.page_number
        for record in result.records
        if record.content_type == "ocr_page"
    }
    assert page_numbers == {1, 2}
    assert result.metadata["table_count"] == 1


def test_cloud_markdown_fallback_is_converted_to_table_data(tmp_path: Path) -> None:
    path = make_cloud_pdf(tmp_path / "cloud.pdf")
    client = FakeCloudClient(pages=[make_markdown_cloud_page()])

    result = parse_pdf(path, mode=PARSE_MODE_CLOUD, cloud_client=client)
    environmental = extract_environmental_data([result])

    assert result.error is None
    assert result.metadata["extraction_mode"] == PARSE_MODE_CLOUD
    assert result.metadata["table_count"] == 1
    table = result.tables[0]
    assert table.rows == 3
    assert table.columns == 4
    assert table.needs_review is True
    assert "cloud_markdown_table" in table.review_reasons
    assert environmental.record_count == 2
    indicators = {record.indicator for record in environmental.records}
    assert indicators == {"COD", "氨氮"}


def test_local_and_cloud_extraction_fields_are_consistent(tmp_path: Path) -> None:
    local_path = make_mixed_scanned_pdf(tmp_path / "local.pdf")
    local_result = parse_pdf(
        local_path,
        mode=PARSE_MODE_LOCAL,
        structure_parser=make_mixed_scanned_structure_parser(),
    )
    cloud_path = make_cloud_pdf(tmp_path / "cloud.pdf")
    cloud_result = parse_pdf(
        cloud_path,
        mode=PARSE_MODE_CLOUD,
        cloud_client=FakeCloudClient(),
    )

    local_env = extract_environmental_data([local_result])
    cloud_env = extract_environmental_data([cloud_result])

    def key(record):
        return (
            record.indicator,
            record.value,
            record.unit,
            record.point,
            record.time,
            record.detection_limit,
            record.extraction_engine,
        )

    assert {key(record) for record in local_env.records} == {
        key(record) for record in cloud_env.records
    }
    assert {record.extraction_mode for record in local_env.records} == {
        PARSE_MODE_LOCAL
    }
    assert {record.extraction_mode for record in cloud_env.records} == {
        PARSE_MODE_CLOUD
    }
    assert {record.extraction_engine for record in cloud_env.records} == {
        "PaddleOCR"
    }


def test_mode_dispatch_calls_requested_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def local_stub(*args, **kwargs):
        calls.append("local")
        return "local-result"

    def cloud_stub(*args, **kwargs):
        calls.append("cloud")
        return "cloud-result"

    monkeypatch.setattr(pdf_parser_module, "parse_pdf_local", local_stub)
    monkeypatch.setattr(pdf_parser_module, "parse_pdf_cloud", cloud_stub)

    assert pdf_parser_module.parse_pdf("dummy.pdf", mode=PARSE_MODE_LOCAL) == "local-result"
    assert pdf_parser_module.parse_pdf("dummy.pdf", mode=PARSE_MODE_CLOUD) == "cloud-result"
    assert calls == ["local", "cloud"]

    with pytest.raises(ValueError, match="不支持的 PDF 解析模式"):
        pdf_parser_module.parse_pdf("dummy.pdf", mode="auto")


def test_json_and_excel_export_include_extraction_mode(tmp_path: Path) -> None:
    path = make_cloud_pdf(tmp_path / "cloud.pdf")
    result = parse_pdf(
        path,
        mode=PARSE_MODE_CLOUD,
        cloud_client=FakeCloudClient(),
    )
    environmental = extract_environmental_data([result])

    json_path = export_json([result], tmp_path / "result.json", environmental)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["environmental"]["records"][0]["extraction_mode"] == PARSE_MODE_CLOUD
    assert payload["environmental"]["records"][0]["extraction_engine"] == "PaddleOCR"
    assert payload["tables"][0]["metadata"]["extraction_mode"] == PARSE_MODE_CLOUD

    excel_path = export_excel(
        [result], tmp_path / "result.xlsx", environmental
    )
    workbook = load_workbook(excel_path, read_only=True)
    table_rows = list(workbook["表格数据"].iter_rows(values_only=True))
    env_rows = list(workbook["环境数据"].iter_rows(values_only=True))
    assert table_rows[0][14] == "解析模式"
    assert any(row[14] == PARSE_MODE_CLOUD for row in table_rows[1:])
    assert env_rows[0][21] == "提取引擎"
    assert env_rows[0][22] == "解析模式"
    assert any(
        row[21] == "PaddleOCR" and row[22] == PARSE_MODE_CLOUD
        for row in env_rows[1:]
    )
    workbook.close()


def test_word_document_is_independent_of_pdf_mode(word_file: Path) -> None:
    result = extract_document(word_file, mode=PARSE_MODE_CLOUD)
    assert result.error is None
    assert result.records


def test_cloud_status_reports_token_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", "secret-token")
    status = cloud_api_status()
    serialized = json.dumps(status, ensure_ascii=False)
    assert status["token_configured"] is True
    assert "secret-token" not in serialized
    assert token_configured() is True


def test_gpu_status_is_reported_truthfully() -> None:
    status = local_device_status()
    assert "cuda" in status
    assert "gpu_count" in status
    assert "status" in status
    if not status["gpu_count"]:
        assert "不可用" in status["status"]


def test_official_cloud_client_supports_ppstructurev3() -> None:
    from paddleocr._api_client.client import PaddleOCRClient
    from paddleocr._api_client.models import Model, PPStructureV3Options

    assert Model.PP_STRUCTURE_V3.value == "PP-StructureV3"
    assert PaddleOCRClient is not None
    assert PPStructureV3Options is not None
