from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from doc_extractor.core.environmental_models import ENV_MANAGEMENT, ENV_MONITORING, ENV_STATISTICS
from doc_extractor.core.environmental_pipeline import extract_batch
from doc_extractor.core.extraction_batch import ExtractionBatch
from doc_extractor.core.extractor import extract_document
from doc_extractor.ui.main_window import MainWindow
from doc_extractor.ui.worker import ExtractionWorker


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_batch_import_deduplicates_files(word_file: Path, pdf_file: Path) -> None:
    app = _application()
    window = MainWindow()

    added = window.add_files([word_file, pdf_file, word_file])

    assert added == 2
    assert window.file_table.rowCount() == 2
    assert window.start_button.isEnabled()
    assert not window.export_json_button.isEnabled()

    window.close()
    assert app is not None


def test_extraction_worker_runs_without_blocking_ui(word_file: Path) -> None:
    app = _application()
    worker = ExtractionWorker([str(word_file)])
    results = []
    failures = []
    loop = QEventLoop()

    worker.results_ready.connect(lambda value: (results.append(value), loop.quit()))
    worker.failed.connect(lambda message: (failures.append(message), loop.quit()))
    QTimer.singleShot(15_000, loop.quit)

    worker.start()
    loop.exec()
    worker.wait(5_000)

    assert not failures
    assert len(results) == 1
    batch = results[0]
    assert isinstance(batch, ExtractionBatch)
    assert batch.document_count == 1
    assert batch.documents[0].record_count > 0
    assert not worker.isRunning()
    assert app is not None


def test_ui_displays_environmental_categories(
    environmental_word_file: Path,
) -> None:
    app = _application()
    window = MainWindow()
    window.add_files([environmental_word_file])

    batch = extract_batch([environmental_word_file])
    window._on_results_ready(batch)

    assert window.env_tabs.count() == 3
    assert window.env_enterprise_filter.count() == 2
    assert window.file_table.item(0, 2).text() == "华清化工有限公司"
    assert window._env_tables[ENV_MONITORING].rowCount() > 0
    assert window._env_tables[ENV_MANAGEMENT].rowCount() > 0
    assert window._env_tables[ENV_STATISTICS].rowCount() > 0
    assert "环境数据" in window.env_summary_label.text()

    window.env_tabs.setCurrentIndex(0)
    window._env_tables[ENV_MONITORING].selectRow(0)
    assert window.env_detail_view.toPlainText()
    assert window.export_json_button.isEnabled()

    window.close()
    assert app is not None


def test_ui_displays_extraction_results(word_file: Path) -> None:
    app = _application()
    window = MainWindow()
    window.add_files([word_file])

    result = extract_document(word_file)
    window._on_results_ready([result])

    assert "采购合同" in window.raw_view.toPlainText()
    assert window.structured_table.rowCount() == result.record_count
    assert window.entity_table.rowCount() >= 3
    assert window.table_combo.count() == 1
    assert window.table_view.rowCount() == 2
    assert window.export_json_button.isEnabled()
    assert window.export_excel_button.isEnabled()

    window.close()
    assert app is not None
