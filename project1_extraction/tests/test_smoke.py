from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from doc_extractor.ui.main_window import MainWindow


def test_main_window_can_be_created() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.windowTitle() == "综合环境数据提取系统"
    assert window.centralWidget() is not None
    assert window.statusBar() is not None

    window.show()
    app.processEvents()
    window.close()
