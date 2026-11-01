from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from docx import Document


@pytest.fixture
def word_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.docx"
    document = Document()
    document.add_heading("采购合同", level=1)
    document.add_paragraph("合同金额：￥12,345.67，折扣 12.5%。")
    document.add_paragraph("签署日期：2024-05-01。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "服务费"
    table.cell(1, 1).text = "8,800.00"
    document.save(path)
    return path


@pytest.fixture
def blank_word_file(tmp_path: Path) -> Path:
    path = tmp_path / "blank.docx"
    Document().save(path)
    return path


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.pdf"
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((50, 60), "采购合同", fontname="china-s", fontsize=18)
    page.insert_text((50, 100), "Contract HT-2024-001", fontsize=11)
    page.insert_text((50, 130), "Amount: ￥8,800.00", fontname="china-s", fontsize=11)
    page.insert_text((50, 160), "Rate: 15.5%", fontsize=11)
    page.insert_text((50, 190), "Date: 2024-06-30", fontsize=11)

    for x in (50, 220, 450):
        page.draw_line((x, 250), (x, 330), color=(0, 0, 0), width=1)
    for y in (250, 290, 330):
        page.draw_line((50, y), (450, y), color=(0, 0, 0), width=1)
    page.insert_text((60, 278), "Item", fontsize=11)
    page.insert_text((230, 278), "Price", fontsize=11)
    page.insert_text((60, 318), "Service", fontsize=11)
    page.insert_text((230, 318), "1200.50", fontsize=11)

    second_page = document.new_page(width=595, height=842)
    second_page.insert_text((50, 70), "Page two 42 45.5%", fontsize=11)
    document.save(path)
    document.close()
    return path


@pytest.fixture
def blank_pdf_file(tmp_path: Path) -> Path:
    path = tmp_path / "blank.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()
    return path


@pytest.fixture
def scanned_pdf_file(tmp_path: Path) -> Path:
    source = pymupdf.open()
    page = source.new_page(width=600, height=300)
    page.insert_text(
        (50, 110),
        "合同金额 12345.67 元",
        fontname="china-s",
        fontsize=30,
    )
    page.insert_text(
        (50, 190),
        "日期 2024-05-01 Amount 88.50",
        fontname="china-s",
        fontsize=30,
    )
    pixmap = page.get_pixmap(dpi=200, alpha=False)
    source.close()

    path = tmp_path / "scanned.pdf"
    scanned = pymupdf.open()
    scanned_page = scanned.new_page(width=600, height=300)
    scanned_page.insert_image(scanned_page.rect, stream=pixmap.tobytes("png"))
    scanned.save(path)
    scanned.close()
    return path


@pytest.fixture
def corrupt_docx(tmp_path: Path) -> Path:
    path = tmp_path / "corrupt.docx"
    path.write_bytes(b"this is not a valid docx file")
    return path


@pytest.fixture
def corrupt_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"this is not a valid pdf file")
    return path


def _add_environment_table(document: Document) -> None:
    rows = [
        ["指标", "数值", "单位"],
        ["新鲜用水量", "1200", "m3"],
        ["用电量", "8500", "kWh"],
        ["天然气用量", "1.2", "万m3"],
        ["COD排放量", "0.85", "吨"],
        ["氨氮排放量", "0.12", "t/a"],
        ["废水排放量", "未检出", "t/a"],
    ]
    table = document.add_table(rows=len(rows), cols=3)
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            table.cell(row_index, column_index).text = value


@pytest.fixture
def environmental_word_file(tmp_path: Path) -> Path:
    path = tmp_path / "environmental.docx"
    document = Document()
    document.add_heading("华清化工有限公司 2024年度环境报告", level=1)
    document.add_paragraph("企业名称：华清化工有限公司")
    document.add_paragraph("统一社会信用代码：91310115MA1K4A2B3C")
    document.add_paragraph("监测日期：2024-05-01")
    document.add_paragraph("废水总排口：COD 45.2 mg/L，氨氮 1.23 mg/L，pH 7.2")
    document.add_paragraph("总磷 <0.01 mg/L，总氮 未检出 mg/L，悬浮物 18.5 mg/L")
    document.add_paragraph("二氧化硫 12.5 mg/m3，氮氧化物 20.1 mg/m3，厂界噪声 55.6 dB(A)")
    document.add_paragraph("补充监测：总磷 0.5")
    document.add_paragraph("平行样：COD 45.2 mg/L 48.6 mg/L")
    document.add_paragraph("排污许可证编号：91310115MA1K4A2B3C，排污许可证有效期至2027-12-31。")
    document.add_paragraph("治理设施运行时间 8 h，药剂投加量 12 kg，维护次数 3 次。")
    document.add_paragraph("统计期间：2024年度")
    _add_environment_table(document)
    document.save(path)
    return path


@pytest.fixture
def environmental_word_file_same_uscc(tmp_path: Path) -> Path:
    path = tmp_path / "environmental_same_uscc.docx"
    document = Document()
    document.add_heading("华清化工有限公司 2024年度用水统计", level=1)
    document.add_paragraph("企业名称：华清化工有限公司")
    document.add_paragraph("统一社会信用代码：91310115MA1K4A2B3C")
    document.add_paragraph("统计期间：2024年度")
    document.add_paragraph("新鲜用水量 900 m3，用电量 6200 kWh")
    document.save(path)
    return path


@pytest.fixture
def environmental_word_file_same_name(tmp_path: Path) -> Path:
    path = tmp_path / "environmental_same_name.docx"
    document = Document()
    document.add_heading("华清化工有限公司 环保管理记录", level=1)
    document.add_paragraph("企业名称：华清化工有限公司")
    document.add_paragraph("统计期间：2024年度")
    document.add_paragraph("治理设施运行时间 6 h，药剂投加量 8 kg")
    document.save(path)
    return path


@pytest.fixture
def environmental_word_file_other_enterprise(tmp_path: Path) -> Path:
    path = tmp_path / "environmental_other.docx"
    document = Document()
    document.add_heading("清源环保科技有限公司 监测报告", level=1)
    document.add_paragraph("企业名称：清源环保科技有限公司")
    document.add_paragraph("监测日期：2024-06-01")
    document.add_paragraph("废水总排口：COD 30.0 mg/L")
    document.save(path)
    return path


@pytest.fixture
def environmental_word_no_identity(tmp_path: Path) -> Path:
    path = tmp_path / "environmental_no_identity.docx"
    document = Document()
    document.add_heading("环境统计报表", level=1)
    document.add_paragraph("统计期间：2024年度")
    document.add_paragraph("用水量 500 m3")
    document.save(path)
    return path


@pytest.fixture
def environmental_pdf_file(tmp_path: Path) -> Path:
    path = tmp_path / "environmental.pdf"
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text(
        (50, 60),
        "华清化工有限公司 监测报告",
        fontname="china-s",
        fontsize=18,
    )
    page.insert_text(
        (50, 100),
        "企业名称：华清化工有限公司",
        fontname="china-s",
        fontsize=11,
    )
    page.insert_text(
        (50, 130),
        "统一社会信用代码：91310115MA1K4A2B3C",
        fontname="china-s",
        fontsize=11,
    )
    page.insert_text(
        (50, 160),
        "监测日期：2024-05-01",
        fontname="china-s",
        fontsize=11,
    )
    page.insert_text(
        (50, 190),
        "废水总排口：COD 45.2 mg/L，氨氮 1.23 mg/L",
        fontname="china-s",
        fontsize=11,
    )
    document.save(path)
    document.close()
    return path
