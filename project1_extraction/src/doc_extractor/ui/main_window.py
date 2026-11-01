from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

import pymupdf
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from doc_extractor import __version__
from doc_extractor.core.environmental_models import (
    ENTERPRISE_STATUS_LABELS,
    ENV_CATEGORIES,
    ENV_CATEGORY_LABELS,
    FLAG_LABELS,
    STATUS_LABELS,
    EnvironmentalExtractionResult,
    EnvironmentalRecord,
)
from doc_extractor.core.environmental_pipeline import extract_environmental_data
from doc_extractor.core.exporters import export_excel, export_json
from doc_extractor.core.extraction_batch import ExtractionBatch
from doc_extractor.core.extractor import detect_file_type
from doc_extractor.core.models import (
    CONTENT_TYPE_LABELS,
    ENTITY_TYPE_LABELS,
    DocumentResult,
    ExtractionRecord,
    FILE_TYPE_PDF,
    FILE_TYPE_WORD,
    Location,
    format_location,
)
from doc_extractor.core.device_status import local_device_status
from doc_extractor.core.paddle_structure import (
    ensure_paddle_cache_dir,
    paddle_structure_available,
    paddle_structure_parser_loaded,
)
from doc_extractor.core.pdf_parser import (
    ENGINE_PADDLE,
    PARSE_MODE_CLOUD,
    PARSE_MODE_LOCAL,
    cloud_api_status,
    token_configured,
)
from doc_extractor.ui.worker import ExtractionWorker


def _normalized_path(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _file_type_label(path: str | Path) -> str:
    file_type = detect_file_type(path)
    if file_type == FILE_TYPE_WORD:
        return "Word"
    if file_type == FILE_TYPE_PDF:
        return "PDF"
    return "未知"


def _record_source(record: ExtractionRecord) -> str:
    if "ocr" in record.content_type:
        return "PaddleOCR"
    source = str(record.metadata.get("source", ""))
    if source == FILE_TYPE_WORD:
        return "Word"
    if source in {FILE_TYPE_PDF, "paddle_structure"}:
        return "PaddleOCR"
    return source or "-"


def _entity_source(record: ExtractionRecord) -> str:
    if "ocr" in record.content_type:
        return "PaddleOCR"
    if record.content_type == "table":
        return "表格"
    return "正文"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # 必须在任何 PaddleOCR/PaddleX 导入之前修正缓存路径。
        ensure_paddle_cache_dir()
        self._file_paths: list[str] = []
        self._results: list[DocumentResult] = []
        self._results_by_path: dict[str, DocumentResult] = {}
        self._table_records: list[ExtractionRecord] = []
        self._environmental: EnvironmentalExtractionResult | None = None
        self._env_visible_records: dict[str, list[EnvironmentalRecord]] = {
            category: [] for category in ENV_CATEGORIES
        }
        self._env_tables: dict[str, QTableWidget] = {}
        self._worker: ExtractionWorker | None = None
        self._parse_mode = PARSE_MODE_LOCAL
        self._api_last_status = "未调用"
        self._local_last_status = "未调用"
        self._device_status: dict = {}
        self._cloud_status: dict = {}

        self.setWindowTitle("综合环境数据提取系统")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)
        self._build_ui()
        self._update_actions()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("综合环境数据提取", central)
        title_font = QFont(title.font())
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        version_label = QLabel(f"v{__version__}", central)
        version_label.setStyleSheet("color: #777777;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(version_label)

        subtitle = QLabel(
            "面向企业环境监测、环保管理、环境统计数据，支持 Word/PDF 与扫描件 OCR，"
            "提取结果按企业归并并保留完整来源位置。",
            central,
        )
        subtitle.setStyleSheet("color: #555555;")

        self.import_word_button = QPushButton("导入 Word", central)
        self.import_pdf_button = QPushButton("导入 PDF", central)
        self.import_batch_button = QPushButton("批量导入", central)
        self.start_button = QPushButton("开始提取", central)
        self.export_json_button = QPushButton("导出 JSON", central)
        self.export_excel_button = QPushButton("导出 Excel", central)
        self.remove_button = QPushButton("移除选中", central)
        self.clear_button = QPushButton("清空", central)
        self.start_button.setStyleSheet("font-weight: bold;")

        self.engine_label = QLabel(
            f"PDF 解析引擎：{ENGINE_PADDLE}（单引擎）",
            central,
        )
        self.engine_label.setStyleSheet("color: #2e7d32; font-weight: bold;")
        self.engine_label.setToolTip(
            "PDF 文字、表格、版面均统一使用 PaddleOCR PP-StructureV3。"
            "PyMuPDF 仅用于页面图像渲染，不参与内容解析。"
        )

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for button in (
            self.import_word_button,
            self.import_pdf_button,
            self.import_batch_button,
            self.start_button,
            self.export_json_button,
            self.export_excel_button,
            self.clear_button,
        ):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.engine_label)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("解析模式：", central))
        self.local_mode_radio = QRadioButton(
            "本地 GPU（PaddleOCR）", central
        )
        self.cloud_mode_radio = QRadioButton(
            "云端 API（PaddleOCR）", central
        )
        self.local_mode_radio.setChecked(True)
        self.local_mode_radio.setToolTip(
            "本地 PaddleOCR PP-StructureV3。若 GPU 不可用，界面会明确提示；"
            "不会自动切换到云端。"
        )
        self.cloud_mode_radio.setToolTip(
            "调用 PaddleOCR 官方云端 API（PP-StructureV3）。"
            "PDF 会上传到远程服务，提取前需要确认。"
        )
        mode_row.addWidget(self.local_mode_radio)
        mode_row.addWidget(self.cloud_mode_radio)
        mode_row.addStretch(1)
        self.mode_status_label = QLabel("当前模式：本地 GPU", central)
        self.gpu_status_label = QLabel("GPU：检测中", central)
        self.api_status_label = QLabel("API：检测中", central)
        self.model_status_label = QLabel("模型：检测中", central)
        for label in (
            self.mode_status_label,
            self.gpu_status_label,
            self.api_status_label,
            self.model_status_label,
        ):
            label.setStyleSheet("color: #555555;")
        status_row = QHBoxLayout()
        status_row.setSpacing(16)
        for label in (
            self.mode_status_label,
            self.gpu_status_label,
            self.api_status_label,
            self.model_status_label,
        ):
            status_row.addWidget(label)
        status_row.addStretch(1)

        self.warning_label = QLabel("请导入 Word 或 PDF 文件。", central)
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #666666;")

        splitter = QSplitter(Qt.Orientation.Horizontal, central)

        left_panel = QWidget(splitter)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        files_title = QLabel("文件列表", left_panel)
        files_font = QFont(files_title.font())
        files_font.setBold(True)
        files_title.setFont(files_font)

        self.file_table = QTableWidget(0, 5, left_panel)
        self.file_table.setHorizontalHeaderLabels(
            ["文件名", "类型", "企业", "状态", "记录数"]
        )
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_table.setAlternatingRowColors(True)
        header = self.file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        left_layout.addWidget(files_title)
        left_layout.addWidget(self.file_table, 1)
        left_layout.addWidget(self.remove_button)

        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget(right_panel)
        self.raw_view = QPlainTextEdit(right_panel)
        self.raw_view.setReadOnly(True)
        self.raw_view.setFont(QFont("Consolas", 10))
        self.raw_view.setPlaceholderText("提取的原始文字将显示在这里。")

        structured_tab = QWidget(right_panel)
        structured_layout = QVBoxLayout(structured_tab)
        structured_layout.setContentsMargins(0, 0, 0, 0)
        structured_splitter = QSplitter(Qt.Orientation.Vertical, structured_tab)
        self.structured_table = QTableWidget(0, 5, structured_splitter)
        self.structured_table.setHorizontalHeaderLabels(["#", "类型", "位置", "文本", "来源"])
        self.structured_table.verticalHeader().setVisible(False)
        self.structured_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.structured_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.structured_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        structured_header = self.structured_table.horizontalHeader()
        structured_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        structured_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        structured_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        structured_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        structured_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.detail_view = QPlainTextEdit(structured_splitter)
        self.detail_view.setReadOnly(True)
        self.detail_view.setFont(QFont("Consolas", 9))
        self.detail_view.setPlaceholderText("选择一条结构化记录以查看完整元数据。")
        structured_splitter.addWidget(self.structured_table)
        structured_splitter.addWidget(self.detail_view)
        structured_splitter.setStretchFactor(0, 3)
        structured_splitter.setStretchFactor(1, 2)
        structured_layout.addWidget(structured_splitter)

        tables_tab = QWidget(right_panel)
        tables_layout = QVBoxLayout(tables_tab)
        tables_layout.setContentsMargins(0, 0, 0, 0)
        self.table_combo = QComboBox(tables_tab)
        self.table_view = QTableWidget(tables_tab)
        self.table_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_view.setAlternatingRowColors(True)
        self.table_meta_label = QLabel("尚未识别表格。", tables_tab)
        self.table_meta_label.setWordWrap(True)
        self.table_meta_label.setStyleSheet("color: #555555;")
        tables_layout.addWidget(self.table_combo)
        tables_layout.addWidget(self.table_meta_label)
        tables_layout.addWidget(self.table_view, 1)

        pdf_tab = QWidget(right_panel)
        pdf_layout = QVBoxLayout(pdf_tab)
        pdf_layout.setContentsMargins(0, 0, 0, 0)
        pdf_page_row = QHBoxLayout()
        pdf_page_row.addWidget(QLabel("PDF 页码：", pdf_tab))
        self.pdf_page_combo = QComboBox(pdf_tab)
        self.pdf_page_combo.setEnabled(False)
        pdf_page_row.addWidget(self.pdf_page_combo)
        pdf_page_row.addStretch(1)
        self.pdf_preview_hint = QLabel("选择 PDF 文件查看原始页面与表格区域。", pdf_tab)
        self.pdf_preview_hint.setStyleSheet("color: #777777;")
        pdf_page_row.addWidget(self.pdf_preview_hint)
        self.pdf_preview_label = QLabel("尚未选择 PDF。", pdf_tab)
        self.pdf_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_preview_label.setStyleSheet(
            "background: #f7f7f7; border: 1px solid #dddddd; color: #666666;"
        )
        self.pdf_preview_label.setMinimumSize(600, 500)
        pdf_scroll = QScrollArea(pdf_tab)
        pdf_scroll.setWidgetResizable(True)
        pdf_scroll.setWidget(self.pdf_preview_label)
        pdf_layout.addLayout(pdf_page_row)
        pdf_layout.addWidget(pdf_scroll, 1)

        self.entity_table = QTableWidget(0, 5, right_panel)
        self.entity_table.setHorizontalHeaderLabels(["类型", "文本", "值", "位置", "来源"])
        self.entity_table.verticalHeader().setVisible(False)
        self.entity_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.entity_table.setAlternatingRowColors(True)
        entity_header = self.entity_table.horizontalHeader()
        entity_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        entity_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        entity_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        entity_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        entity_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        env_tab = QWidget(right_panel)
        env_layout = QVBoxLayout(env_tab)
        env_layout.setContentsMargins(0, 0, 0, 0)
        env_layout.setSpacing(6)
        env_filter_row = QHBoxLayout()
        env_filter_row.addWidget(QLabel("企业筛选：", env_tab))
        self.env_enterprise_filter = QComboBox(env_tab)
        self.env_enterprise_filter.addItem("全部企业", None)
        self.env_enterprise_filter.setEnabled(False)
        env_filter_row.addWidget(self.env_enterprise_filter)
        env_filter_row.addStretch(1)
        self.env_summary_label = QLabel("尚未提取环境数据。", env_tab)
        self.env_summary_label.setWordWrap(True)
        self.env_summary_label.setStyleSheet("color: #555555;")
        self.env_tabs = QTabWidget(env_tab)
        for category in ENV_CATEGORIES:
            table = QTableWidget(0, 9, self.env_tabs)
            table.setHorizontalHeaderLabels(
                ["企业", "指标", "数值", "单位", "时间", "点位", "检出限", "来源", "状态"]
            )
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table_header = table.horizontalHeader()
            for column in range(8):
                table_header.setSectionResizeMode(
                    column, QHeaderView.ResizeMode.ResizeToContents
                )
            table_header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
            table.itemSelectionChanged.connect(self._show_env_detail)
            self._env_tables[category] = table
            self.env_tabs.addTab(table, ENV_CATEGORY_LABELS[category])
        self.env_detail_view = QPlainTextEdit(env_tab)
        self.env_detail_view.setReadOnly(True)
        self.env_detail_view.setFont(QFont("Consolas", 9))
        self.env_detail_view.setPlaceholderText("选择一条环境数据记录以查看完整来源与标记信息。")
        env_splitter = QSplitter(Qt.Orientation.Vertical, env_tab)
        env_splitter.addWidget(self.env_tabs)
        env_splitter.addWidget(self.env_detail_view)
        env_splitter.setStretchFactor(0, 3)
        env_splitter.setStretchFactor(1, 1)
        env_layout.addLayout(env_filter_row)
        env_layout.addWidget(self.env_summary_label)
        env_layout.addWidget(env_splitter, 1)

        self.tabs.addTab(self.raw_view, "原始文字")
        self.tabs.addTab(structured_tab, "结构化信息")
        self.tabs.addTab(tables_tab, "表格数据")
        self.tabs.addTab(pdf_tab, "PDF 原页")
        self.tabs.addTab(self.entity_table, "实体识别")
        self.tabs.addTab(env_tab, "环境数据")
        right_layout.addWidget(self.tabs)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 800])

        bottom_row = QHBoxLayout()
        self.status_label = QLabel("就绪", central)
        self.status_label.setStyleSheet("color: #444444;")
        self.progress_bar = QProgressBar(central)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedWidth(260)
        bottom_row.addWidget(self.status_label, 1)
        bottom_row.addWidget(self.progress_bar)

        layout.addLayout(title_row)
        layout.addWidget(subtitle)
        layout.addLayout(toolbar)
        layout.addLayout(mode_row)
        layout.addLayout(status_row)
        layout.addWidget(self.warning_label)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom_row)

        self.setCentralWidget(central)
        paddle_status = "可用" if paddle_structure_available() else "未安装"
        self.statusBar().showMessage(
            f"v{__version__} | PDF 解析：{ENGINE_PADDLE}（{paddle_status}）"
        )

        self.import_word_button.clicked.connect(self._import_word)
        self.import_pdf_button.clicked.connect(self._import_pdf)
        self.import_batch_button.clicked.connect(self._import_batch)
        self.start_button.clicked.connect(self.start_extraction)
        self.export_json_button.clicked.connect(self._export_json)
        self.export_excel_button.clicked.connect(self._export_excel)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_all)
        self.file_table.itemSelectionChanged.connect(self._display_current_document)
        self.structured_table.itemSelectionChanged.connect(self._show_record_detail)
        self.table_combo.currentIndexChanged.connect(self._show_table)
        self.env_enterprise_filter.currentIndexChanged.connect(self._refresh_env_tables)
        self.env_tabs.currentChanged.connect(self._show_env_detail)
        self.pdf_page_combo.currentIndexChanged.connect(self._render_current_pdf_page)
        self.local_mode_radio.toggled.connect(self._on_mode_changed)
        self.cloud_mode_radio.toggled.connect(self._on_mode_changed)
        self._refresh_service_status()
        if not paddle_structure_available():
            self._set_warning(
                "未检测到可用的 PaddleOCR/PaddlePaddle。PDF 解析不会回退到其他引擎，"
                "请安装 PaddleOCR 3.x 后重试。",
                "warning",
            )

    def _on_mode_changed(self, *_args) -> None:
        if self.cloud_mode_radio.isChecked():
            self._parse_mode = PARSE_MODE_CLOUD
        else:
            self._parse_mode = PARSE_MODE_LOCAL
        self._refresh_service_status()

        if self._parse_mode == PARSE_MODE_CLOUD:
            if token_configured():
                self._set_warning(
                    "云端 API 模式：PDF 将上传到 PaddleOCR 官方远程服务，"
                    "开始提取前会再次确认。",
                    "warning",
                )
            else:
                self._set_warning(
                    "云端 API 模式：PDF 将上传到 PaddleOCR 官方远程服务。"
                    "当前未配置 PADDLEOCR_ACCESS_TOKEN，请通过系统环境变量安全配置后重启软件；"
                    "程序不会显示或记录 Token。",
                    "error",
                )
        else:
            if self._device_status.get("gpu_count"):
                self._set_warning("本地模式：使用本地 PaddleOCR GPU 推理。", "info")
            else:
                self._set_warning(
                    "本地模式：GPU 不可用，当前将使用 CPU 推理；不会自动切换云端。",
                    "warning",
                )

    def _refresh_service_status(self) -> None:
        self._device_status = local_device_status()
        self._cloud_status = cloud_api_status()
        mode_text = "云端 API" if self._parse_mode == PARSE_MODE_CLOUD else "本地 GPU"
        self.mode_status_label.setText(f"当前模式：{mode_text}")

        gpu_text = self._device_status.get("status", "GPU 状态未知")
        self.gpu_status_label.setText(f"GPU：{gpu_text}")
        self.gpu_status_label.setStyleSheet(
            "color: #2e7d32;"
            if self._device_status.get("gpu_count")
            else "color: #9a6700;"
        )

        self.api_status_label.setText(
            f"API：{self._cloud_status.get('status', '未知')} | "
            f"最近调用：{self._api_last_status}"
        )
        self.api_status_label.setStyleSheet(
            "color: #2e7d32;"
            if self._cloud_status.get("token_configured")
            else "color: #9a6700;"
        )

        if self._parse_mode == PARSE_MODE_CLOUD:
            model_text = "云端 API（不加载本地模型）"
        elif not paddle_structure_available():
            model_text = "本地模型不可用"
        elif paddle_structure_parser_loaded():
            model_text = "本地模型已加载"
        else:
            model_text = "本地模型未加载（首次解析时加载）"
        self.model_status_label.setText(
            f"模型：{model_text} | 最近本地调用：{self._local_last_status}"
        )

    def _confirm_cloud_upload(self) -> bool:
        answer = QMessageBox.question(
            self,
            "云端 API 上传确认",
            "当前选择云端 API 模式。\n\n"
            "所选 PDF 将上传到 PaddleOCR 官方远程服务进行解析。\n"
            "请确认文件内容允许上传到远程服务。\n\n"
            "是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _set_warning(self, text: str, level: str = "info") -> None:
        colors = {
            "info": "#666666",
            "success": "#2e7d32",
            "warning": "#9a6700",
            "error": "#b00020",
        }
        self.warning_label.setStyleSheet(f"color: {colors.get(level, '#666666')};")
        self.warning_label.setText(text)

    def _update_actions(self) -> None:
        busy = self._worker is not None
        has_files = bool(self._file_paths)
        all_extracted = bool(self._results) and all(
            _normalized_path(path) in self._results_by_path for path in self._file_paths
        )
        self.import_word_button.setEnabled(not busy)
        self.import_pdf_button.setEnabled(not busy)
        self.import_batch_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy and has_files)
        self.clear_button.setEnabled(not busy)
        self.start_button.setEnabled(not busy and has_files)
        self.export_json_button.setEnabled(not busy and all_extracted)
        self.export_excel_button.setEnabled(not busy and all_extracted)
        self.local_mode_radio.setEnabled(not busy)
        self.cloud_mode_radio.setEnabled(not busy)

    def add_files(self, paths: Sequence[str | Path]) -> int:
        existing = {_normalized_path(path) for path in self._file_paths}
        added = 0
        skipped = 0

        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()
            if not path.is_file() or detect_file_type(path) is None:
                skipped += 1
                continue
            key = _normalized_path(path)
            if key in existing:
                skipped += 1
                continue

            existing.add(key)
            self._file_paths.append(str(path))
            row = self.file_table.rowCount()
            self.file_table.insertRow(row)
            name_item = QTableWidgetItem(path.name)
            name_item.setToolTip(str(path))
            type_item = QTableWidgetItem(_file_type_label(path))
            enterprise_item = QTableWidgetItem("-")
            status_item = QTableWidgetItem("待提取")
            count_item = QTableWidgetItem("-")
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.file_table.setItem(row, 0, name_item)
            self.file_table.setItem(row, 1, type_item)
            self.file_table.setItem(row, 2, enterprise_item)
            self.file_table.setItem(row, 3, status_item)
            self.file_table.setItem(row, 4, count_item)
            added += 1

        if added:
            if self._results:
                self._environmental = None
                self._clear_environmental_views()
            self.status_label.setText(f"已添加 {added} 个文件。")
            if self.file_table.currentRow() < 0:
                self.file_table.selectRow(0)
        if skipped:
            self._set_warning(f"已跳过 {skipped} 个重复、不存在或不支持的文件。", "warning")
        self._update_actions()
        return added

    def _import_word(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "导入 Word 文档",
            "",
            "Word 文档 (*.docx)",
        )
        if paths:
            self.add_files(paths)

    def _import_pdf(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "导入 PDF 文档",
            "",
            "PDF 文档 (*.pdf)",
        )
        if paths:
            self.add_files(paths)

    def _import_batch(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "批量导入文档",
            "",
            "支持的文档 (*.docx *.pdf);;Word 文档 (*.docx);;PDF 文档 (*.pdf);;所有文件 (*)",
        )
        if paths:
            self.add_files(paths)

    def _remove_selected(self) -> None:
        row = self.file_table.currentRow()
        if row < 0 or row >= len(self._file_paths):
            return
        path = self._file_paths.pop(row)
        self.file_table.removeRow(row)
        key = _normalized_path(path)
        self._results = [
            result for result in self._results if _normalized_path(result.source_file) != key
        ]
        self._results_by_path.pop(key, None)
        if self._results:
            self._environmental = extract_environmental_data(self._results)
            self._populate_environmental()
        else:
            self._environmental = None
            self._clear_environmental_views()
        self._display_current_document()
        self._update_actions()

    def _clear_all(self) -> None:
        if self._worker is not None:
            return
        self._file_paths.clear()
        self._results.clear()
        self._results_by_path.clear()
        self._table_records.clear()
        self._environmental = None
        self.file_table.setRowCount(0)
        self._clear_views()
        self._clear_environmental_views()
        self._api_last_status = "未调用"
        self._local_last_status = "未调用"
        self._set_warning("请导入 Word 或 PDF 文件。", "info")
        self.status_label.setText("就绪")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self._refresh_service_status()
        self._update_actions()

    def start_extraction(self) -> None:
        if self._worker is not None or not self._file_paths:
            return

        if self._parse_mode == PARSE_MODE_CLOUD:
            if not token_configured():
                self._set_warning(
                    "未配置 PADDLEOCR_ACCESS_TOKEN，无法使用云端 API。"
                    "请通过系统环境变量配置后重启软件；不会自动切换本地模式。",
                    "error",
                )
                self.status_label.setText("云端 API Token 未配置")
                self._refresh_service_status()
                return
            if not self._confirm_cloud_upload():
                self._set_warning("已取消云端上传与解析。", "info")
                self.status_label.setText("已取消")
                return
            self._api_last_status = "上传/解析中"
        else:
            self._local_last_status = "解析中"
        self._refresh_service_status()

        for row in range(self.file_table.rowCount()):
            self.file_table.item(row, 2).setText("-")
            self.file_table.item(row, 3).setText("等待中")
            self.file_table.item(row, 3).setForeground(QBrush(QColor("#444444")))
            self.file_table.item(row, 4).setText("-")

        self._results = []
        self._results_by_path.clear()
        self._table_records.clear()
        self._environmental = None
        self._clear_views()
        self._clear_environmental_views()
        self._set_warning("正在提取，请稍候……", "info")
        self.progress_bar.setRange(0, max(len(self._file_paths), 1))
        self.progress_bar.setValue(0)
        self.status_label.setText("准备提取……")

        worker = ExtractionWorker(
            list(self._file_paths),
            self,
            mode=self._parse_mode,
        )
        worker.progress.connect(self._on_progress)
        worker.results_ready.connect(self._on_results_ready)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._update_actions()
        worker.start()

    def _on_progress(self, current: int, total: int, message: str) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(current)
        self.status_label.setText(message)

    def _on_results_ready(self, results: object) -> None:
        if isinstance(results, ExtractionBatch):
            document_results = list(results.documents)
            self._environmental = results.environmental
        else:
            document_results = list(results) if results else []
            self._environmental = (
                extract_environmental_data(document_results) if document_results else None
            )

        self._results = document_results
        self._results_by_path = {
            _normalized_path(result.source_file): result for result in document_results
        }
        env = self._environmental
        enterprise_by_document = {}
        documents_with_env_data: set[str] = set()
        if env is not None:
            documents_with_env_data = {record.document_id for record in env.records}
            for enterprise in env.enterprises:
                for document_id in enterprise.document_ids:
                    enterprise_by_document[document_id] = enterprise

        success_count = 0
        error_count = 0
        total_records = 0
        for row, path in enumerate(self._file_paths):
            result = self._results_by_path.get(_normalized_path(path))
            if result is None:
                continue
            enterprise_item = self.file_table.item(row, 2)
            status_item = self.file_table.item(row, 3)
            count_item = self.file_table.item(row, 4)
            if result.error:
                status_item.setText("失败")
                status_item.setForeground(QBrush(QColor("#b00020")))
                error_count += 1
            else:
                status_item.setText("成功")
                status_item.setForeground(QBrush(QColor("#2e7d32")))
                success_count += 1
            count_item.setText(str(result.record_count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            total_records += result.record_count

            enterprise = enterprise_by_document.get(result.document_id)
            if (
                enterprise is None
                or result.error
                or result.document_id not in documents_with_env_data
            ):
                enterprise_item.setText("-")
                enterprise_item.setToolTip("")
            else:
                enterprise_item.setText(enterprise.display_name)
                tooltip_lines = [
                    ENTERPRISE_STATUS_LABELS.get(
                        enterprise.identity_status, enterprise.identity_status
                    )
                ]
                tooltip_lines.extend(enterprise.warnings)
                enterprise_item.setToolTip("\n".join(tooltip_lines))

        self.progress_bar.setValue(self.progress_bar.maximum())
        env_text = ""
        if env is not None:
            env_text = (
                f" 环境数据 {env.record_count} 条"
                f"（待核实 {env.review_count} 条，企业 {len(env.enterprises)} 家）。"
            )
        self.status_label.setText(
            f"提取完成：成功 {success_count} 个，失败 {error_count} 个，"
            f"通用记录 {total_records} 条。{env_text}"
        )
        self._populate_environmental()
        self._set_warning("提取完成，请选择文件查看结果。", "success")
        result_status = "成功" if error_count == 0 else "部分失败"
        if self._parse_mode == PARSE_MODE_CLOUD:
            self._api_last_status = result_status
        else:
            self._local_last_status = result_status
        self._refresh_service_status()
        if self._file_paths:
            self.file_table.selectRow(0)
            self._display_current_document()
        self._update_actions()

    def _on_worker_failed(self, message: str) -> None:
        self._set_warning(f"提取任务失败：{message}", "error")
        self.status_label.setText("提取任务失败")
        if self._parse_mode == PARSE_MODE_CLOUD:
            self._api_last_status = "失败"
        else:
            self._local_last_status = "失败"
        self._refresh_service_status()
        QMessageBox.critical(self, "提取失败", message)

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._refresh_service_status()
        self._update_actions()

    def _current_result(self) -> DocumentResult | None:
        row = self.file_table.currentRow()
        if row < 0 or row >= len(self._file_paths):
            return None
        return self._results_by_path.get(_normalized_path(self._file_paths[row]))

    def _display_current_document(self) -> None:
        result = self._current_result()
        if result is None:
            self._clear_views()
            if self.file_table.currentRow() >= 0:
                self._set_warning("该文件尚未提取。", "info")
            return

        self.raw_view.setPlainText(result.raw_text() or "（无文本内容）")

        if result.error:
            self._set_warning(f"错误：{result.error}", "error")
        elif result.warnings:
            shown = result.warnings[:6]
            suffix = ""
            if len(result.warnings) > len(shown):
                suffix = f"\n……另有 {len(result.warnings) - len(shown)} 条提示"
            self._set_warning("提示：\n" + "\n".join(shown) + suffix, "warning")
        else:
            self._set_warning("提取完成，未发现提示信息。", "success")

        self._populate_structured(result)
        self._populate_tables(result)
        self._populate_pdf_preview(result)
        self._populate_entities(result)

    def _populate_structured(self, result: DocumentResult) -> None:
        records = result.records
        self.structured_table.setRowCount(len(records))
        for row, record in enumerate(records):
            index_item = QTableWidgetItem(str(row))
            index_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item = QTableWidgetItem(
                CONTENT_TYPE_LABELS.get(record.content_type, record.content_type)
            )
            location_text = format_location(record.location)
            location_item = QTableWidgetItem(location_text)
            text_preview = record.text.replace("\n", " ")
            if len(text_preview) > 160:
                text_preview = text_preview[:157] + "..."
            text_item = QTableWidgetItem(text_preview)
            text_item.setToolTip(record.text)
            source_item = QTableWidgetItem(_record_source(record))
            self.structured_table.setItem(row, 0, index_item)
            self.structured_table.setItem(row, 1, type_item)
            self.structured_table.setItem(row, 2, location_item)
            self.structured_table.setItem(row, 3, text_item)
            self.structured_table.setItem(row, 4, source_item)
        if records:
            self.structured_table.selectRow(0)
            self._show_record_detail()
        else:
            self.detail_view.clear()

    def _show_record_detail(self) -> None:
        row = self.structured_table.currentRow()
        result = self._current_result()
        if result is None or row < 0 or row >= len(result.records):
            self.detail_view.clear()
            return
        record = result.records[row]
        self.detail_view.setPlainText(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
        )

    def _populate_tables(self, result: DocumentResult) -> None:
        self._table_records = [
            record for record in result.records if record.content_type == "table"
        ]
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        if not self._table_records:
            self.table_combo.addItem("该文档未识别到表格")
            self.table_combo.setEnabled(False)
            self.table_combo.blockSignals(False)
            self.table_meta_label.setText("该文档未识别到表格。")
            self.table_view.clear()
            self.table_view.setRowCount(0)
            self.table_view.setColumnCount(0)
            return

        self.table_combo.setEnabled(True)
        for index, record in enumerate(self._table_records):
            parts: list[str] = []
            if record.location.page_number is not None:
                parts.append(f"第{record.location.page_number}页")
            parts.append(f"表格[{record.location.table_index}]")
            rows = record.metadata.get("row_count", 0)
            columns = record.metadata.get("column_count", 0)
            parts.append(f"({rows}×{columns})")
            engine = record.metadata.get("extraction_engine", "")
            if engine:
                parts.append(f"| {engine}")
            if record.metadata.get("needs_review"):
                parts.append("| 待核实")
            self.table_combo.addItem(" ".join(parts), index)
        self.table_combo.blockSignals(False)
        self.table_combo.setCurrentIndex(0)
        self._show_table(0)

    def _show_table(self, index: int) -> None:
        if index < 0 or index >= len(self._table_records):
            self.table_view.setRowCount(0)
            self.table_meta_label.setText("尚未选择表格。")
            return
        record = self._table_records[index]
        table_id = record.metadata.get("table_id", "-")
        engine = record.metadata.get("extraction_engine", "-")
        needs_review = record.metadata.get("needs_review", False)
        reasons = "；".join(record.metadata.get("review_reasons", [])) or "无"
        bbox = record.location.bbox
        bbox_text = (
            ", ".join(f"{value:.1f}" for value in bbox) if bbox else "-"
        )
        self.table_meta_label.setText(
            f"表格ID：{table_id} | 页码：{record.location.page_number or '-'} | "
            f"引擎：{engine} | 待人工核实：{'是' if needs_review else '否'} | "
            f"原因：{reasons} | bbox=({bbox_text})"
        )
        rows = record.metadata.get("rows", [])
        column_count = max((len(row) for row in rows), default=0)
        self.table_view.clear()
        self.table_view.setRowCount(len(rows))
        self.table_view.setColumnCount(column_count)
        if column_count:
            self.table_view.setHorizontalHeaderLabels(
                [f"列{column + 1}" for column in range(column_count)]
            )
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table_view.setItem(row_index, column_index, item)
        self.table_view.resizeColumnsToContents()

    def _populate_pdf_preview(self, result: DocumentResult) -> None:
        self.pdf_page_combo.blockSignals(True)
        self.pdf_page_combo.clear()
        self.pdf_preview_label.clear()

        if result.file_type != FILE_TYPE_PDF:
            self.pdf_page_combo.setEnabled(False)
            self.pdf_preview_hint.setText("当前文件不是 PDF。")
            self.pdf_preview_label.setText("仅 PDF 支持原始页面预览。")
            self.pdf_page_combo.blockSignals(False)
            return
        if result.error:
            self.pdf_page_combo.setEnabled(False)
            self.pdf_preview_hint.setText("PDF 解析失败。")
            self.pdf_preview_label.setText(f"无法预览：{result.error}")
            self.pdf_page_combo.blockSignals(False)
            return

        page_count = int(result.metadata.get("page_count", 0) or 0)
        for page_number in range(1, page_count + 1):
            self.pdf_page_combo.addItem(f"第{page_number}页", page_number)
        self.pdf_page_combo.setEnabled(page_count > 0)
        self.pdf_preview_hint.setText(
            f"共 {page_count} 页；红框为识别到的表格区域。"
        )
        self.pdf_page_combo.blockSignals(False)
        if page_count:
            self.pdf_page_combo.setCurrentIndex(0)
            self._render_current_pdf_page()
        else:
            self.pdf_preview_label.setText("该 PDF 没有可预览页面。")

    def _render_current_pdf_page(self, *_args) -> None:
        result = self._current_result()
        page_number = self.pdf_page_combo.currentData()
        if (
            result is None
            or result.file_type != FILE_TYPE_PDF
            or not page_number
        ):
            return
        try:
            with pymupdf.open(result.source_file) as document:
                page = document[int(page_number) - 1]
                pixmap = page.get_pixmap(dpi=120, alpha=False)
                page_width = page.rect.width
                page_height = page.rect.height
        except Exception as exc:
            self.pdf_preview_label.setText(
                f"页面渲染失败：{type(exc).__name__}: {exc}"
            )
            return

        image = QPixmap()
        if not image.loadFromData(pixmap.tobytes("png")):
            self.pdf_preview_label.setText("页面图像加载失败。")
            return

        scale_x = image.width() / page_width if page_width else 1.0
        scale_y = image.height() / page_height if page_height else 1.0
        painter = QPainter(image)
        try:
            pen = QPen(QColor("#d32f2f"))
            pen.setWidth(3)
            painter.setPen(pen)
            for table in result.tables:
                if table.page_number != int(page_number) or not table.table_bbox:
                    continue
                x0, y0, x1, y1 = table.table_bbox
                painter.drawRect(
                    QRectF(
                        x0 * scale_x,
                        y0 * scale_y,
                        max(1.0, (x1 - x0) * scale_x),
                        max(1.0, (y1 - y0) * scale_y),
                    )
                )
        finally:
            painter.end()

        self.pdf_preview_label.setPixmap(image)
        self.pdf_preview_label.resize(image.size())

    def _populate_entities(self, result: DocumentResult) -> None:
        entities = list(result.iter_entities())
        self.entity_table.setRowCount(len(entities))
        for row, (record, entity, location) in enumerate(entities):
            type_item = QTableWidgetItem(
                ENTITY_TYPE_LABELS.get(entity.get("type", ""), entity.get("type", ""))
            )
            text_item = QTableWidgetItem(str(entity.get("text", "")))
            text_item.setToolTip(str(entity.get("text", "")))
            value = entity.get("value")
            value_item = QTableWidgetItem("" if value is None else str(value))
            value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            location_item = QTableWidgetItem(format_location(location))
            source_item = QTableWidgetItem(_entity_source(record))
            self.entity_table.setItem(row, 0, type_item)
            self.entity_table.setItem(row, 1, text_item)
            self.entity_table.setItem(row, 2, value_item)
            self.entity_table.setItem(row, 3, location_item)
            self.entity_table.setItem(row, 4, source_item)

    def _clear_env_tables(self) -> None:
        for category, table in self._env_tables.items():
            table.clearContents()
            table.setRowCount(0)
            self._env_visible_records[category] = []
        self.env_detail_view.clear()

    def _clear_environmental_views(self) -> None:
        self._environmental = None
        self.env_enterprise_filter.blockSignals(True)
        self.env_enterprise_filter.clear()
        self.env_enterprise_filter.addItem("全部企业", None)
        self.env_enterprise_filter.setEnabled(False)
        self.env_enterprise_filter.blockSignals(False)
        self.env_summary_label.setText("尚未提取环境数据。")
        self.env_summary_label.setToolTip("")
        self._clear_env_tables()

    def _populate_environmental(self) -> None:
        env = self._environmental
        self.env_enterprise_filter.blockSignals(True)
        self.env_enterprise_filter.clear()
        self.env_enterprise_filter.addItem("全部企业", None)

        if env is None:
            self.env_enterprise_filter.setEnabled(False)
            self.env_enterprise_filter.blockSignals(False)
            self.env_summary_label.setText("尚未提取环境数据。")
            self.env_summary_label.setToolTip("")
            self._clear_env_tables()
            return

        for enterprise in env.enterprises:
            self.env_enterprise_filter.addItem(
                f"{enterprise.display_name}（{enterprise.document_count} 个文件）",
                enterprise.enterprise_id,
            )
        self.env_enterprise_filter.setEnabled(bool(env.enterprises))
        self.env_enterprise_filter.setCurrentIndex(0)
        self.env_enterprise_filter.blockSignals(False)

        counts = env.category_counts
        summary = (
            f"共 {env.record_count} 条环境数据，待人工核实 {env.review_count} 条，"
            f"企业 {len(env.enterprises)} 家；监测 {counts[ENV_CATEGORIES[0]]} / "
            f"管理 {counts[ENV_CATEGORIES[1]]} / 统计 {counts[ENV_CATEGORIES[2]]}。"
        )
        if env.warnings:
            summary += f" 另有 {len(env.warnings)} 条提示。"
        self.env_summary_label.setText(summary)
        self.env_summary_label.setToolTip("\n".join(env.warnings))
        self._refresh_env_tables()

    def _refresh_env_tables(self, *_args) -> None:
        env = self._environmental
        if env is None:
            self._clear_env_tables()
            return

        selected_enterprise = self.env_enterprise_filter.currentData()
        enterprise_names = {
            enterprise.enterprise_id: enterprise.display_name
            for enterprise in env.enterprises
        }

        for category, table in self._env_tables.items():
            records = [
                record
                for record in env.records_by_category(category)
                if selected_enterprise is None
                or record.enterprise_id == selected_enterprise
            ]
            self._env_visible_records[category] = records
            table.clearContents()
            table.setRowCount(len(records))
            for row, record in enumerate(records):
                enterprise_name = record.enterprise_name or enterprise_names.get(
                    record.enterprise_id, ""
                )
                enterprise_item = QTableWidgetItem(enterprise_name)
                enterprise_item.setToolTip(record.enterprise_id)
                indicator_item = QTableWidgetItem(record.indicator or "")
                value_item = QTableWidgetItem(
                    "" if record.value is None else str(record.value)
                )
                value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                unit_item = QTableWidgetItem(record.unit or "")
                time_item = QTableWidgetItem(record.time or "")
                point_item = QTableWidgetItem(record.point or "")
                limit_item = QTableWidgetItem(record.detection_limit or "")
                location = Location.from_dict(record.source_location)
                source_item = QTableWidgetItem(
                    f"{Path(record.source_file).name} | {format_location(location)}"
                )
                source_item.setToolTip(
                    f"{record.source_file}\n{format_location(location)}\n"
                    f"原始表达：{record.raw_expression}"
                )
                status_item = QTableWidgetItem(
                    STATUS_LABELS.get(record.status, record.status)
                )
                flag_text = "；".join(
                    FLAG_LABELS.get(flag, flag) for flag in record.flags
                )
                status_item.setToolTip(flag_text or "无")
                if record.needs_review:
                    status_item.setForeground(QBrush(QColor("#9a6700")))
                else:
                    status_item.setForeground(QBrush(QColor("#2e7d32")))

                for column, item in enumerate(
                    (
                        enterprise_item,
                        indicator_item,
                        value_item,
                        unit_item,
                        time_item,
                        point_item,
                        limit_item,
                        source_item,
                        status_item,
                    )
                ):
                    table.setItem(row, column, item)

        current_category = ENV_CATEGORIES[self.env_tabs.currentIndex()]
        current_table = self._env_tables[current_category]
        if current_table.rowCount() > 0:
            if current_table.currentRow() < 0:
                current_table.selectRow(0)
        else:
            self.env_detail_view.clear()

    def _show_env_detail(self, *_args) -> None:
        if self._environmental is None:
            self.env_detail_view.clear()
            return
        category = ENV_CATEGORIES[self.env_tabs.currentIndex()]
        table = self._env_tables[category]
        row = table.currentRow()
        records = self._env_visible_records.get(category, [])
        if row < 0 and records:
            table.selectRow(0)
            row = table.currentRow()
        if row < 0 or row >= len(records):
            self.env_detail_view.clear()
            return
        self.env_detail_view.setPlainText(
            json.dumps(records[row].to_dict(), ensure_ascii=False, indent=2)
        )

    def _clear_views(self) -> None:
        self.raw_view.clear()
        self.structured_table.clearContents()
        self.structured_table.setRowCount(0)
        self.detail_view.clear()
        self._table_records.clear()
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        self.table_combo.addItem("（无表格）")
        self.table_combo.setEnabled(False)
        self.table_combo.blockSignals(False)
        self.table_view.clear()
        self.table_view.setRowCount(0)
        self.table_view.setColumnCount(0)
        self.table_meta_label.setText("尚未识别表格。")
        self.pdf_page_combo.blockSignals(True)
        self.pdf_page_combo.clear()
        self.pdf_page_combo.setEnabled(False)
        self.pdf_page_combo.blockSignals(False)
        self.pdf_preview_label.clear()
        self.pdf_preview_label.setText("尚未选择 PDF。")
        self.pdf_preview_hint.setText("选择 PDF 文件查看原始页面与表格区域。")
        self.entity_table.clearContents()
        self.entity_table.setRowCount(0)

    def _default_export_name(self, suffix: str) -> str:
        if self._results:
            stem = Path(self._results[0].source_file).stem
        else:
            stem = "提取结果"
        return str(Path.home() / f"{stem}_提取结果{suffix}")

    def _export_json(self) -> None:
        if not self._results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 JSON",
            self._default_export_name(".json"),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        try:
            output = export_json(self._results, path, self._environmental)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", f"{type(exc).__name__}: {exc}")
            return
        self.status_label.setText(f"JSON 已导出：{output}")
        QMessageBox.information(self, "导出成功", f"JSON 已保存到：\n{output}")

    def _export_excel(self) -> None:
        if not self._results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Excel",
            self._default_export_name(".xlsx"),
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            output = export_excel(self._results, path, self._environmental)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", f"{type(exc).__name__}: {exc}")
            return
        self.status_label.setText(f"Excel 已导出：{output}")
        QMessageBox.information(self, "导出成功", f"Excel 已保存到：\n{output}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._worker is not None:
            QMessageBox.warning(self, "正在提取", "请等待提取任务完成后再关闭窗口。")
            event.ignore()
            return
        super().closeEvent(event)
