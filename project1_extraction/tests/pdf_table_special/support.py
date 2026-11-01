from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from table_test_support import make_native_table_pdf  # noqa: E402

ENTERPRISE_NAME = "专项测试环境科技有限公司"
ENTERPRISE_CODE = "91310115MA1K4A2B3C"

SPECIAL_ROWS = [
    ["监测点位", "指标", "数值", "单位", "监测日期"],
    ["DW001 废水总排口", "COD", "45.2", "mg/L", "2024-07-01"],
    ["DW001 废水总排口", "总磷", "<0.01", "mg/L", "2024-07-01"],
    ["DW001 废水总排口", "悬浮物", "—", "mg/L", "2024-07-01"],
    ["DW001 废水总排口", "pH", "7.3", "无量纲", "2024-07-01"],
    ["DA001 废气排放口", "二氧化硫", "ND", "mg/m3", "2024-07-02"],
    ["DA001 废气排放口", "氮氧化物", "35.2", "mg/m3", "2024-07-02"],
    ["DA001 废气排放口", "颗粒物", "8.6", "mg/m3", "2024-07-02"],
    ["厂界东侧", "噪声", "55.6", "dB(A)", "2024-07-02"],
]

SPECIAL_STANDARD_ANSWERS = [
    {
        "indicator": "COD",
        "value": 45.2,
        "unit": "mg/L",
        "point": "废水总排口",
        "time": "2024-07-01",
        "detection_limit": None,
        "row_index": 1,
        "column_index": 1,
    },
    {
        "indicator": "总磷",
        "value": None,
        "unit": "mg/L",
        "point": "废水总排口",
        "time": "2024-07-01",
        "detection_limit": "<0.01",
        "row_index": 2,
        "column_index": 1,
    },
    {
        "indicator": "悬浮物",
        "value": None,
        "unit": "mg/L",
        "point": "废水总排口",
        "time": "2024-07-01",
        "detection_limit": None,
        "row_index": 3,
        "column_index": 1,
    },
    {
        "indicator": "pH",
        "value": 7.3,
        "unit": "无量纲",
        "point": "废水总排口",
        "time": "2024-07-01",
        "detection_limit": None,
        "row_index": 4,
        "column_index": 1,
    },
    {
        "indicator": "二氧化硫",
        "value": None,
        "unit": "mg/m³",
        "point": "废气排放口",
        "time": "2024-07-02",
        "detection_limit": "ND",
        "row_index": 5,
        "column_index": 1,
    },
    {
        "indicator": "氮氧化物",
        "value": 35.2,
        "unit": "mg/m³",
        "point": "废气排放口",
        "time": "2024-07-02",
        "detection_limit": None,
        "row_index": 6,
        "column_index": 1,
    },
    {
        "indicator": "颗粒物",
        "value": 8.6,
        "unit": "mg/m³",
        "point": "废气排放口",
        "time": "2024-07-02",
        "detection_limit": None,
        "row_index": 7,
        "column_index": 1,
    },
    {
        "indicator": "噪声",
        "value": 55.6,
        "unit": "dB(A)",
        "point": "厂界东侧",
        "time": "2024-07-02",
        "detection_limit": None,
        "row_index": 8,
        "column_index": 1,
    },
]

BORDERLESS_ROWS = [
    ["监测点位", "COD(mg/L)", "氨氮(mg/L)", "总磷(mg/L)", "pH", "监测日期"],
    ["DW001 废水总排口", "45.2", "1.23", "<0.01", "7.3", "2024-05-01"],
    ["DA001 废气排放口", "", "", "", "", "2024-05-01"],
]


def make_special_values_pdf(path: Path) -> Path:
    return make_native_table_pdf(
        path,
        SPECIAL_ROWS,
        title_lines=(
            f"企业名称：{ENTERPRISE_NAME}",
            f"统一社会信用代码：{ENTERPRISE_CODE}",
            "监测日期：2024-07-01",
        ),
        column_widths=[150.0, 100.0, 90.0, 100.0, 120.0],
    )


def make_borderless_native_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=842, height=595)
    page.insert_text(
        (40, 40),
        f"企业名称：{ENTERPRISE_NAME}",
        fontname="china-s",
        fontsize=12,
    )
    page.insert_text(
        (40, 62),
        f"统一社会信用代码：{ENTERPRISE_CODE}",
        fontname="china-s",
        fontsize=12,
    )
    page.insert_text(
        (40, 84),
        "监测日期：2024-05-01",
        fontname="china-s",
        fontsize=12,
    )
    x0, y0 = 40.0, 120.0
    widths = [150.0, 120.0, 120.0, 120.0, 70.0, 130.0]
    row_height = 30.0
    for row_index, row in enumerate(BORDERLESS_ROWS):
        x = x0
        for column_index, text in enumerate(row):
            if text:
                page.insert_text(
                    (x + 4, y0 + row_index * row_height + 20),
                    text,
                    fontname="china-s",
                    fontsize=10,
                )
            x += widths[column_index]
    document.save(path)
    document.close()
    return path


def render_pdf_page_to_image_only_pdf(source: Path, target: Path, dpi: int = 200) -> Path:
    with pymupdf.open(source) as document:
        page = document[0]
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        width = page.rect.width
        height = page.rect.height
    scanned = pymupdf.open()
    scanned_page = scanned.new_page(width=width, height=height)
    scanned_page.insert_image(scanned_page.rect, stream=pixmap.tobytes("png"))
    scanned.save(target)
    scanned.close()
    return target
