"""Maintainable Chinese typo dictionary and protection rules.

The seed dictionary is intentionally conservative. It only contains exact,
human-reviewed wrong forms. There is no pinyin auto-correction and no
edit-distance guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TypoEntry:
    wrong: str
    correct: str
    reason: str
    confidence: str
    rule_id: str

    def __post_init__(self) -> None:
        if not self.wrong or not self.correct:
            raise ValueError("typo entry text must not be empty")
        if self.wrong == self.correct:
            raise ValueError("typo entry wrong and correct must differ")
        if self.confidence not in {"high", "low"}:
            raise ValueError(
                f"typo confidence must be 'high' or 'low': {self.confidence!r}"
            )


# High-confidence entries are exact known errors. Low-confidence entries are
# still reported, but metadata.auto_annotate is false and they require human
# review.
DEFAULT_TYPO_ENTRIES: tuple[TypoEntry, ...] = (
    TypoEntry("数剧", "数据", "同音字/常见错别字", "high", "TYPO_001"),
    TypoEntry("数具", "数据", "同音字/常见错别字", "high", "TYPO_002"),
    TypoEntry("监则", "监测", "同音字/常见错别字", "high", "TYPO_003"),
    TypoEntry("监侧", "监测", "形近字/常见错别字", "high", "TYPO_004"),
    TypoEntry("检侧", "检测", "形近字/常见错别字", "high", "TYPO_005"),
    TypoEntry("检则", "检测", "同音字/常见错别字", "high", "TYPO_006"),
    TypoEntry("浓渡", "浓度", "同音字/形近字", "high", "TYPO_007"),
    TypoEntry("污梁", "污染", "同音字/形近字", "high", "TYPO_008"),
    TypoEntry("污柒", "污染", "形近字/常见错别字", "high", "TYPO_009"),
    TypoEntry("排汚", "排放", "日文异体字/错字", "high", "TYPO_010"),
    TypoEntry("采祥", "采样", "同音字/形近字", "high", "TYPO_011"),
    TypoEntry("废汽", "废气", "同音字/常见错别字", "high", "TYPO_012"),
    TypoEntry("废谁", "废水", "同音字/常见错别字", "high", "TYPO_013"),
    TypoEntry("报高", "报告", "同音字/形近字", "high", "TYPO_014"),
    TypoEntry("结杲", "结果", "形近字/常见错别字", "high", "TYPO_015"),
    TypoEntry("记绿", "记录", "同音字/常见错别字", "high", "TYPO_016"),
    TypoEntry("运形", "运行", "同音字/形近字", "high", "TYPO_017"),
    TypoEntry("设拖", "设施", "同音字/形近字", "high", "TYPO_018"),
    TypoEntry("标淮", "标准", "形近字/常见错别字", "high", "TYPO_019"),
    TypoEntry("方发", "方法", "同音字/常见错别字", "high", "TYPO_020"),
    TypoEntry("环竟", "环境", "同音字/形近字", "high", "TYPO_021"),
    TypoEntry("保沪", "保护", "同音字/形近字", "high", "TYPO_022"),
    TypoEntry("企也", "企业", "同音字/形近字", "high", "TYPO_023"),
    TypoEntry("模似", "模拟", "同音字/形近字", "high", "TYPO_024"),
    TypoEntry("总鳞", "总磷", "同音字/污染物名称错字", "high", "TYPO_025"),
    TypoEntry("总淡", "总氮", "同音字/污染物名称错字", "high", "TYPO_026"),
    TypoEntry("氨淡", "氨氮", "同音字/污染物名称错字", "high", "TYPO_027"),
    TypoEntry("颗料物", "颗粒物", "形近字/污染物名称错字", "high", "TYPO_028"),
    TypoEntry("二氧化流", "二氧化硫", "同音字/污染物名称错字", "high", "TYPO_029"),
    TypoEntry(
        "排污许可正",
        "排污许可证",
        "同音字/专业术语候选",
        "high",
        "TYPO_030",
    ),
    # Low-confidence example: reported, but never auto-annotated.
    TypoEntry(
        "临测",
        "监测",
        "同音/形近候选，需结合上下文人工确认",
        "low",
        "TYPO_LOW_001",
    ),
)


# Built-in professional terms. Terms from the project one batch are added at
# scan time, including enterprise names, indicators and monitoring points.
PROTECTED_TERMS: tuple[str, ...] = (
    "化学需氧量",
    "五日生化需氧量",
    "高锰酸盐指数",
    "氨氮",
    "总磷",
    "总氮",
    "悬浮物",
    "二氧化硫",
    "氮氧化物",
    "颗粒物",
    "挥发性有机物",
    "非甲烷总烃",
    "排污许可证",
    "排污许可",
    "环境监测",
    "检测方法",
    "监测方法",
    "治理设施",
    "污染防治设施",
    "排放浓度",
    "排放速率",
    "监测点位",
    "采样点位",
    "监测断面",
    "企业名称",
    "统一社会信用代码",
    "监测报告",
    "检测报告",
    "环境统计",
    "环保管理",
    "环境影响评价",
    "重铬酸钾法",
    "纳氏试剂分光光度法",
    "紫外分光光度法",
    "气相色谱法",
    "高效液相色谱法",
    "原子吸收分光光度法",
    "电感耦合等离子体质谱法",
    "离子色谱法",
    "重量法",
    "稀释倍数法",
)


# Known correct words used only for conservative repeated-character checks.
# We never flag arbitrary repeated characters, to avoid legitimate
# reduplication such as "年年", "常常", "一一".
REPEAT_GUARD_TERMS: tuple[str, ...] = (
    "企业",
    "数据",
    "监测",
    "检测",
    "报告",
    "浓度",
    "废水",
    "废气",
    "记录",
    "运行",
    "处理",
    "方法",
    "结果",
    "项目",
    "单位",
    "采样",
    "排放",
    "污染",
    "环境",
    "保护",
    "设施",
    "标准",
    "分析",
    "设备",
    "治理",
    "排放量",
    "监测点",
    "采样点",
)


STANDARD_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:GB|HJ|DB)(?:\d+)?(?:/[TZ])?\s*\d+(?:[.\-—/]\d+)*"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)

ORGANIZATION_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9（）()]{2,40}"
    r"(?:股份有限公司|有限责任公司|有限公司|集团|研究院|检测中心|监测站|"
    r"生态环境局|环保局|环境保护局)"
)
