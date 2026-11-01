from __future__ import annotations

from doc_extractor.core.environmental_common import (
    BaseEnvironmentalExtractor,
    IndicatorSpec,
)
from doc_extractor.core.environmental_models import ENV_STATISTICS

STATISTICS_SPECS: tuple[IndicatorSpec, ...] = (
    IndicatorSpec("年度用水量", ("年度用水总量",), "water"),
    IndicatorSpec("年度用电量", ("年度耗电量",), "energy"),
    IndicatorSpec("新鲜用水量", ("新水用量",), "water"),
    IndicatorSpec("工业用水量", (), "water"),
    IndicatorSpec("生活用水量", (), "water"),
    IndicatorSpec("总用水量", (), "water"),
    IndicatorSpec("用水量", (), "water"),
    IndicatorSpec("废水排放量", (), "water"),
    IndicatorSpec("废水产生量", (), "water"),
    IndicatorSpec(
        "用电量",
        ("耗电量", "电力消耗量"),
        "energy",
    ),
    IndicatorSpec(
        "综合能耗",
        ("综合能源消费量",),
        "energy",
    ),
    IndicatorSpec(
        "天然气用量",
        ("天然气消耗量", "天然气使用量"),
        "energy",
    ),
    IndicatorSpec(
        "燃煤量",
        ("煤炭消耗量", "原煤消耗量"),
        "energy",
    ),
    IndicatorSpec(
        "蒸汽用量",
        ("蒸汽消耗量",),
        "energy",
    ),
    IndicatorSpec("能源消耗量", (), "energy"),
    IndicatorSpec("COD产生量", ("C0D产生量",), "pollutant"),
    IndicatorSpec("COD排放量", ("C0D排放量",), "pollutant"),
    IndicatorSpec("氨氮产生量", (), "pollutant"),
    IndicatorSpec("氨氮排放量", (), "pollutant"),
    IndicatorSpec("总磷排放量", (), "pollutant"),
    IndicatorSpec("总氮排放量", (), "pollutant"),
    IndicatorSpec("二氧化硫排放量", (), "pollutant"),
    IndicatorSpec("氮氧化物排放量", (), "pollutant"),
    IndicatorSpec("颗粒物排放量", (), "pollutant"),
    IndicatorSpec("一般工业固体废物产生量", (), "pollutant"),
    IndicatorSpec("危险废物产生量", (), "pollutant"),
    IndicatorSpec("污染物产生量", (), "pollutant"),
    IndicatorSpec("污染物排放量", (), "pollutant"),
)


class EnvironmentalStatisticsExtractor(BaseEnvironmentalExtractor):
    category = ENV_STATISTICS
    specs = STATISTICS_SPECS
    point_required = False
    category_keywords = (
        "用水",
        "用电",
        "能源",
        "天然气",
        "燃煤",
        "蒸汽",
        "排放量",
        "产生量",
        "统计",
        "消耗量",
    )


def extract(
    document,
    enterprise,
):
    return EnvironmentalStatisticsExtractor().extract(document, enterprise)
