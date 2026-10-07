from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("공공언어 검사기")
    app.setOrganizationName("PublicLanguageChecker")
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())
