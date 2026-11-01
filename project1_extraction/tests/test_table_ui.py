from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from doc_extractor.core.environmental_pipeline import extract_batch
from doc_extractor.ui.main_window import MainWindow
from table_test_support import (
    make_mixed_scanned_pdf,
    make_mixed_scanned_structure_parser,
)


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_pdf_engine_is_fixed_to_paddleocr() -> None:
    app = _application()
    window = MainWindow()

    assert "PaddleOCR PP-StructureV3" in window.engine_label.text()
    assert not hasattr(window, "engine_combo")
    assert not hasattr(window, "ocr_checkbox")

    window.close()
    assert app is not None


def test_pdf_page_preview_and_table_review_metadata(tmp_path: Path) -> None:
    app = _application()
    path = make_mixed_scanned_pdf(tmp_path / "mixed_scanned.pdf")
    fake_parser = make_mixed_scanned_structure_parser()
    batch = extract_batch([path], structure_parser=fake_parser)

    window = MainWindow()
    window.add_files([path])
    window._on_results_ready(batch)

    assert window.pdf_page_combo.count() == 2
    assert window.pdf_page_combo.isEnabled()
    assert window.pdf_preview_label.pixmap() is not None
    assert window.table_combo.count() == 1
    assert "PaddleOCR" in window.table_combo.itemText(0)

    window.pdf_page_combo.setCurrentIndex(1)
    assert window.pdf_page_combo.currentData() == 2
    assert window.pdf_preview_label.pixmap() is not None

    meta_text = window.table_meta_label.text()
    assert "PaddleOCR PP-StructureV3" in meta_text
    assert "待人工核实：是" in meta_text
    assert "merged_cells_detected" in meta_text
    assert window.table_view.rowCount() == 5
    assert window.export_json_button.isEnabled()
    assert window.export_excel_button.isEnabled()

    window.close()
    assert app is not None
