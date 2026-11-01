from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from openpyxl import load_workbook
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from doc_extractor.core.environmental_pipeline import extract_batch
from doc_extractor.core.paddle_structure import StructurePageResult
from doc_extractor.ui.main_window import MainWindow
from doc_extractor.ui.worker import ExtractionWorker
from pdf_table_special.support import make_special_values_pdf
from table_test_support import (
    make_mixed_scanned_pdf,
    make_mixed_scanned_structure_parser,
)


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_ui_exports_json_and_excel_for_scanned_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _application()
    path = make_mixed_scanned_pdf(tmp_path / "mixed_scanned.pdf")
    fake_parser = make_mixed_scanned_structure_parser()
    batch = extract_batch([path], structure_parser=fake_parser)

    window = MainWindow()
    window.add_files([path])
    window._on_results_ready(batch)

    assert "页码：2" in window.table_meta_label.text()
    assert "PaddleOCR" in window.table_meta_label.text()
    assert "待人工核实：是" in window.table_meta_label.text()
    assert window.pdf_page_combo.count() == 2

    json_target = tmp_path / "ui_result.json"
    excel_target = tmp_path / "ui_result.xlsx"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(json_target), "JSON 文件 (*.json)")),
    )
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))
    window._export_json()
    assert json_target.exists()
    payload = json.loads(json_target.read_text(encoding="utf-8"))
    assert payload["table_count"] == 1
    assert payload["environmental"]["record_count"] == 10

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(
            lambda *args, **kwargs: (str(excel_target), "Excel 文件 (*.xlsx)")
        ),
    )
    window._export_excel()
    assert excel_target.exists()
    workbook = load_workbook(excel_target, read_only=True)
    assert "表格数据" in workbook.sheetnames
    assert "环境数据" in workbook.sheetnames
    env_rows = list(workbook["环境数据"].iter_rows(values_only=True))
    assert any(row[8] == "COD" and row[9] == 45.2 for row in env_rows[1:])
    workbook.close()

    window.close()
    assert app is not None


class SlowStructureParser:
    name = "SlowPaddleStub"

    def parse_page(self, image, **kwargs) -> StructurePageResult:
        time.sleep(1.0)
        return StructurePageResult(engine=self.name)


def test_ui_worker_keeps_event_loop_responsive_during_paddle_parse(
    tmp_path: Path,
) -> None:
    app = _application()
    native = make_special_values_pdf(tmp_path / "native.pdf")
    from pdf_table_special.support import render_pdf_page_to_image_only_pdf

    scanned = render_pdf_page_to_image_only_pdf(
        native, tmp_path / "scanned.pdf", dpi=200
    )

    window = MainWindow()
    window.add_files([scanned])
    ticks: list[int] = []
    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()

    worker = ExtractionWorker(
        [str(scanned)],
        structure_parser=SlowStructureParser(),
    )
    results = []
    failures = []
    loop = QEventLoop()
    worker.results_ready.connect(lambda value: (results.append(value), loop.quit()))
    worker.failed.connect(lambda message: (failures.append(message), loop.quit()))
    QTimer.singleShot(60_000, loop.quit)

    worker.start()
    loop.exec()
    worker.wait(10_000)
    timer.stop()

    assert not failures
    assert results
    assert ticks, "后台解析期间主事件循环未处理定时器事件"
    assert not worker.isRunning()
    window.close()
    assert app is not None
