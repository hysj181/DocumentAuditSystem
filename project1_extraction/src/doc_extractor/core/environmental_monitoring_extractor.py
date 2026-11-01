from __future__ import annotations

from doc_extractor.core.environmental_common import (
    BaseEnvironmentalExtractor,
    IndicatorSpec,
)
from doc_extractor.core.environmental_models import ENV_MONITORING

EXCLUDE_LOAD_SUFFIXES = (
    "排放量",
    "产生量",
    "削减量",
    "去除量",
    "处理量",
    "用量",
    "消耗量",
)

MONITORING_SPECS: tuple[IndicatorSpec, ...] = (
    IndicatorSpec(
        "COD",
        ("化学需氧量", "C0D"),
        "wastewater",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec(
        "CODcr",
        ("C0Dcr",),
        "wastewater",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec("氨氮", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("总磷", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("总氮", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec(
        "悬浮物",
        ("SS",),
        "wastewater",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec(
        "pH",
        ("PH",),
        "wastewater",
        unit_required=False,
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec(
        "BOD5",
        ("五日生化需氧量",),
        "wastewater",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec("石油类", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec(
        "动植物油", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES
    ),
    IndicatorSpec("挥发酚", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("氰化物", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("六价铬", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("总铬", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("总砷", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("总铅", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("总汞", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("总镉", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec("色度", (), "wastewater", exclude_suffixes=EXCLUDE_LOAD_SUFFIXES),
    IndicatorSpec(
        "二氧化硫",
        ("SO2", "S02"),
        "waste_gas",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec(
        "氮氧化物",
        ("NOx", "N0x"),
        "waste_gas",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec(
        "颗粒物",
        ("烟尘", "粉尘"),
        "waste_gas",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec(
        "排放速率",
        (),
        "waste_gas",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec(
        "非甲烷总烃",
        ("NMHC",),
        "waste_gas",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec(
        "臭气浓度",
        (),
        "waste_gas",
        unit_required=False,
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
    IndicatorSpec(
        "噪声",
        ("厂界噪声", "Leq", "等效声级"),
        "noise",
        exclude_suffixes=EXCLUDE_LOAD_SUFFIXES,
    ),
)


class EnvironmentalMonitoringExtractor(BaseEnvironmentalExtractor):
    category = ENV_MONITORING
    specs = MONITORING_SPECS
    point_required = True
    category_keywords = ("废水", "废气", "噪声", "监测", "排放口", "排口")


def extract(
    document,
    enterprise,
):
    return EnvironmentalMonitoringExtractor().extract(document, enterprise)
