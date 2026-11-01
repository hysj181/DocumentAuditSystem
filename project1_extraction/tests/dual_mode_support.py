from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pymupdf

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from table_test_support import (  # noqa: E402
    COLUMN_TABLE_HTML,
    ENTERPRISE_CODE,
    ENTERPRISE_NAME,
    MONITORING_DATE,
    environment_table_parsed,
)


def cloud_pruned_payload() -> dict:
    table = environment_table_parsed()
    cell_boxes = [
        cell.bbox if cell.bbox is not None else [0, 0, 1, 1]
        for cell in table.cells
    ]
    ocr_texts = [
        f"企业名称：{ENTERPRISE_NAME}",
        f"统一社会信用代码：{ENTERPRISE_CODE}",
        f"监测日期：{MONITORING_DATE}",
    ]
    ocr_boxes = [
        [50, 20, 500, 50],
        [50, 60, 560, 90],
        [50, 100, 400, 130],
    ]
    ocr_scores = [0.99, 0.99, 0.99]
    for cell in table.cells:
        if cell.text and cell.bbox is not None:
            ocr_texts.append(cell.text)
            ocr_boxes.append(cell.bbox)
            ocr_scores.append(0.97)
    return {
        "width": 1240,
        "height": 1754,
        "parsing_res_list": [
            {
                "block_label": "table",
                "block_content": COLUMN_TABLE_HTML,
                "block_bbox": [80, 180, 1120, 580],
                "block_id": 0,
            }
        ],
        "layout_det_res": {
            "boxes": [
                {
                    "label": "table",
                    "score": 0.99,
                    "coordinate": [80, 180, 1120, 580],
                }
            ]
        },
        "overall_ocr_res": {
            "rec_texts": ocr_texts,
            "rec_boxes": ocr_boxes,
            "rec_scores": ocr_scores,
        },
        "table_res_list": [
            {
                "res": {
                    "cell_box_list": cell_boxes,
                    "pred_html": COLUMN_TABLE_HTML,
                    "table_ocr_pred": {
                        "rec_texts": ocr_texts[3:],
                        "rec_boxes": ocr_boxes[3:],
                        "rec_scores": ocr_scores[3:],
                    },
                }
            }
        ],
    }


def cloud_page(
    *,
    pruned_result: dict | None = None,
    markdown_text: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        pruned_result=pruned_result,
        markdown_text=markdown_text,
        exports={},
        raw={},
    )


class FakeCloudClient:
    def __init__(self, pages=None, *, job_id: str = "cloud-job-1") -> None:
        self._pages = pages if pages is not None else [cloud_page(pruned_result=cloud_pruned_payload())]
        self._job_id = job_id
        self.calls: list[dict] = []

    def parse_document(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(job_id=self._job_id, pages=self._pages, data_info={})


class FailingCloudClient:
    def __init__(self, message: str = "模拟网络断开") -> None:
        self.message = message
        self.calls: list[dict] = []

    def parse_document(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError(self.message)


def make_cloud_pdf(path: Path, *, pages: int = 1) -> Path:
    document = pymupdf.open()
    for _ in range(pages):
        document.new_page(width=595, height=842)
    document.save(path)
    document.close()
    return path


def make_markdown_cloud_page() -> SimpleNamespace:
    markdown = f"""# 企业环境监测报告

企业名称：{ENTERPRISE_NAME}
统一社会信用代码：{ENTERPRISE_CODE}
监测日期：{MONITORING_DATE}

| 监测点位 | 指标 | 数值 | 单位 |
| --- | --- | --- | --- |
| DW001 废水总排口 | COD | 45.2 | mg/L |
| DW001 废水总排口 | 氨氮 | 1.23 | mg/L |
"""
    return cloud_page(pruned_result=None, markdown_text=markdown)
