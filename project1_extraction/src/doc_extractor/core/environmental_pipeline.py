from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from doc_extractor.core.environmental_common import BaseEnvironmentalExtractor
from doc_extractor.core.environmental_enterprise import resolve_enterprises
from doc_extractor.core.environmental_management_extractor import (
    EnvironmentalManagementExtractor,
)
from doc_extractor.core.environmental_models import (
    EnvironmentalExtractionResult,
    EnvironmentalRecord,
)
from doc_extractor.core.environmental_monitoring_extractor import (
    EnvironmentalMonitoringExtractor,
)
from doc_extractor.core.environmental_statistics_extractor import (
    EnvironmentalStatisticsExtractor,
)
from doc_extractor.core.extraction_batch import ExtractionBatch
from doc_extractor.core.extractor import ProgressCallback, extract_documents
from doc_extractor.core.models import DocumentResult
from doc_extractor.core.paddle_structure import PageStructureParser
from doc_extractor.core.pdf_parser import PARSE_MODE_LOCAL
from doc_extractor.core.pdf_renderer import PdfRenderer


def default_extractors() -> list[BaseEnvironmentalExtractor]:
    return [
        EnvironmentalMonitoringExtractor(),
        EnvironmentalManagementExtractor(),
        EnvironmentalStatisticsExtractor(),
    ]


def _record_key(record: EnvironmentalRecord) -> tuple[object, ...]:
    return (
        record.document_id,
        record.category,
        record.indicator,
        record.value,
        record.unit,
        record.time,
        record.point,
        record.raw_expression,
        json.dumps(record.source_location, sort_keys=True, ensure_ascii=False),
    )


def extract_environmental_data(
    documents: Sequence[DocumentResult],
    *,
    extractors: Sequence[BaseEnvironmentalExtractor] | None = None,
) -> EnvironmentalExtractionResult:
    enterprises, group_for_document = resolve_enterprises(list(documents))
    extractor_instances = list(extractors) if extractors is not None else default_extractors()

    records: list[EnvironmentalRecord] = []
    warnings: list[str] = []

    for document in documents:
        if document.error:
            continue
        enterprise = group_for_document.get(document.document_id)
        if enterprise is None:
            continue
        for extractor in extractor_instances:
            try:
                extracted = extractor.extract(document, enterprise)
            except Exception as exc:
                warnings.append(
                    f"{Path(document.source_file).name} 的"
                    f"{extractor.category} 提取失败：{type(exc).__name__}: {exc}"
                )
                continue
            records.extend(extracted)

    unique_records: list[EnvironmentalRecord] = []
    seen: set[tuple[object, ...]] = set()
    for record in records:
        key = _record_key(record)
        if key in seen:
            continue
        seen.add(key)
        unique_records.append(record)

    enterprise_ids_with_records = {record.enterprise_id for record in unique_records}
    enterprises = [
        enterprise
        for enterprise in enterprises
        if enterprise.enterprise_id in enterprise_ids_with_records
    ]

    enterprise_warnings = [
        f"{enterprise.display_name}：{warning}"
        for enterprise in enterprises
        for warning in enterprise.warnings
    ]
    warnings = list(dict.fromkeys(warnings + enterprise_warnings))

    return EnvironmentalExtractionResult(
        enterprises=enterprises,
        records=unique_records,
        warnings=warnings,
    )


def extract_batch(
    paths: Iterable[str | Path],
    *,
    structure_parser: PageStructureParser | None = None,
    renderer: PdfRenderer | None = None,
    structure_dpi: int = 200,
    mode: str = PARSE_MODE_LOCAL,
    cloud_client=None,
    cloud_options=None,
    request_timeout: float = 300.0,
    poll_timeout: float = 600.0,
    progress_callback: ProgressCallback | None = None,
) -> ExtractionBatch:
    documents = extract_documents(
        paths,
        structure_parser=structure_parser,
        renderer=renderer,
        structure_dpi=structure_dpi,
        mode=mode,
        cloud_client=cloud_client,
        cloud_options=cloud_options,
        request_timeout=request_timeout,
        poll_timeout=poll_timeout,
        progress_callback=progress_callback,
    )
    if progress_callback is not None:
        progress_callback(
            len(documents),
            len(documents),
            "正在识别环境监测、环保管理、环境统计三类数据……",
        )
    try:
        environmental = extract_environmental_data(documents)
    except Exception as exc:
        environmental = EnvironmentalExtractionResult(
            warnings=[f"环境业务数据提取失败：{type(exc).__name__}: {exc}"]
        )
    return ExtractionBatch(documents=documents, environmental=environmental)
