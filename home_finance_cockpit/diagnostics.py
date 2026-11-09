"""Local failure diagnostics without exception messages, locals or transaction data."""

import faulthandler
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from home_finance_cockpit.identity import APP_RELEASE
from home_finance_cockpit.paths import ensure_data_directory

_native_log = None


def install_diagnostics():
    global _native_log
    folder = ensure_data_directory() / "logs"
    folder.mkdir(exist_ok=True)
    logger = logging.getLogger("home_finance_cockpit")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            folder / "application.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.info("Starting release %s; Python %s", APP_RELEASE, sys.version.split()[0])
    native_path = folder / "native-crash.log"
    if native_path.exists() and native_path.stat().st_size > 1_000_000:
        native_path.replace(folder / "native-crash.previous.log")
    _native_log = native_path.open("a", encoding="utf-8")
    faulthandler.enable(_native_log)

    def report_exception(error_type, error, traceback):
        frames = []
        while traceback is not None:
            code = traceback.tb_frame.f_code
            frames.append(f"{Path(code.co_filename).name}:{traceback.tb_lineno}:{code.co_name}")
            traceback = traceback.tb_next
        logger.error("Unhandled %s; frames=%s", error_type.__name__, " > ".join(frames))
        from PyQt6.QtCore import QCoreApplication
        from PyQt6.QtWidgets import QApplication, QMessageBox

        from home_finance_cockpit.localization import tr

        if isinstance(QApplication.instance(), QApplication):
            QMessageBox.critical(
                None,
                tr("Błąd aplikacji"),
                tr(
                    "Wystąpił nieoczekiwany błąd. Aplikacja zostanie zamknięta. "
                    "Informacje diagnostyczne zapisano w folderze: {folder}",
                    folder=str(folder),
                ),
            )
            QCoreApplication.exit(1)

    sys.excepthook = report_exception
    return folder
