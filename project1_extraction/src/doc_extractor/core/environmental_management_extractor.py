from __future__ import annotations

from doc_extractor.core.environmental_common import (
    BaseEnvironmentalExtractor,
    IndicatorSpec,
)
from doc_extractor.core.environmental_models import ENV_MANAGEMENT

MANAGEMENT_SPECS: tuple[IndicatorSpec, ...] = (
    IndicatorSpec(
        "排污许可证编号",
        ("许可证编号", "排污许可证证书编号"),
        "permit",
        unit_required=False,
        time_required=False,
        value_kind="text",
    ),
    IndicatorSpec(
        "排污许可证有效期",
        ("许可证有效期", "有效期至", "有效期限"),
        "permit",
        unit_required=False,
        value_kind="date",
    ),
    IndicatorSpec(
        "设施运行时间",
        ("治理设施运行时间", "运行时长", "运行时间"),
        "facility_operation",
    ),
    IndicatorSpec(
        "设施运行率",
        ("治理设施运行率", "同步运行率", "运行率"),
        "facility_operation",
    ),
    IndicatorSpec(
        "药剂投加量",
        ("药剂用量", "加药量"),
        "ledger",
    ),
    IndicatorSpec(
        "维护次数",
        ("检修次数",),
        "facility_operation",
    ),
    IndicatorSpec(
        "停机时长",
        ("停机时间",),
        "facility_operation",
    ),
    IndicatorSpec(
        "污泥转移量",
        ("污泥转移",),
        "ledger",
    ),
    IndicatorSpec(
        "废水处理量",
        (),
        "facility_operation",
    ),
    IndicatorSpec(
        "废气处理量",
        (),
        "facility_operation",
    ),
)


class EnvironmentalManagementExtractor(BaseEnvironmentalExtractor):
    category = ENV_MANAGEMENT
    specs = MANAGEMENT_SPECS
    point_required = False
    category_keywords = (
        "排污许可",
        "许可证",
        "台账",
        "治理设施",
        "运行记录",
        "加药",
        "维护",
        "环保设施",
    )


def extract(
    document,
    enterprise,
):
    return EnvironmentalManagementExtractor().extract(document, enterprise)
