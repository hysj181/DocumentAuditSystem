from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from doc_extractor import __version__
from doc_extractor.config import resolve_log_dir
from doc_extractor.core.paddle_structure import ensure_paddle_cache_dir
from doc_extractor.ui.main_window import MainWindow


def _setup_logging() -> Path:
    log_dir = resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "doc_extractor.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(
        isinstance(existing, RotatingFileHandler)
        and getattr(existing, "baseFilename", "") == str(log_path)
        for existing in root.handlers
    ):
        root.addHandler(handler)
    return log_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doc-extractor")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Start the window, process events briefly, then exit.",
    )
    parser.add_argument(
        "--smoke-test-timeout",
        type=int,
        default=1000,
        metavar="MS",
        help="Auto-close delay for --smoke-test (default: 1000 ms).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_paddle_cache_dir()
    log_path = _setup_logging()
    logging.getLogger(__name__).info(
        "启动 doc_extractor %s，日志文件：%s", __version__, log_path
    )

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Document Extractor")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("DocumentAuditSystem")

    window = MainWindow()
    window.show()

    if args.smoke_test:
        QTimer.singleShot(max(args.smoke_test_timeout, 0), app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
