from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from doc_extractor.core.pdf_parser import PARSE_MODE_CLOUD, PARSE_MODE_LOCAL
from doc_extractor.ui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_mode_switch_is_user_driven_and_cloud_upload_is_confirmed(
    pdf_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _application()
    monkeypatch.delenv("PADDLEOCR_ACCESS_TOKEN", raising=False)
    window = MainWindow()
    window.add_files([pdf_file])

    assert window.local_mode_radio.isChecked()
    assert not window.cloud_mode_radio.isChecked()
    assert window._parse_mode == PARSE_MODE_LOCAL
    assert "当前模式：本地 GPU" in window.mode_status_label.text()

    window.cloud_mode_radio.setChecked(True)
    assert window.cloud_mode_radio.isChecked()
    assert window._parse_mode == PARSE_MODE_CLOUD
    assert "当前模式：云端 API" in window.mode_status_label.text()
    assert "上传" in window.warning_label.text()
    assert "Token 未配置" in window.api_status_label.text()

    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: next(answers)),
    )
    assert window._confirm_cloud_upload() is False
    assert window._confirm_cloud_upload() is True

    window.close()
    assert app is not None


def test_cloud_mode_without_token_does_not_start_worker(
    pdf_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _application()
    monkeypatch.delenv("PADDLEOCR_ACCESS_TOKEN", raising=False)
    window = MainWindow()
    window.add_files([pdf_file])
    window.cloud_mode_radio.setChecked(True)

    window.start_extraction()

    assert window._worker is None
    assert "PADDLEOCR_ACCESS_TOKEN" in window.warning_label.text()
    assert "不会自动切换" in window.warning_label.text()
    window.close()
    assert app is not None


def test_cloud_mode_confirmation_no_does_not_start_worker(
    pdf_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _application()
    monkeypatch.setenv("PADDLEOCR_ACCESS_TOKEN", "configured-for-test")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )
    window = MainWindow()
    window.add_files([pdf_file])
    window.cloud_mode_radio.setChecked(True)

    window.start_extraction()

    assert window._worker is None
    assert "已取消" in window.warning_label.text()
    window.close()
    assert app is not None


def test_gpu_unavailable_is_displayed_without_auto_switching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _application()
    monkeypatch.delenv("PADDLEOCR_ACCESS_TOKEN", raising=False)
    window = MainWindow()
    window._refresh_service_status()

    assert window.local_mode_radio.isChecked()
    assert not window.cloud_mode_radio.isChecked()
    assert window._parse_mode == PARSE_MODE_LOCAL
    if not window._device_status.get("gpu_count"):
        assert "不可用" in window.gpu_status_label.text()
    window.close()
    assert app is not None
