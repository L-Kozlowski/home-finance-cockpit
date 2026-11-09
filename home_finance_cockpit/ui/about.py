"""Release identity, authorship and locally available distribution notices."""

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget

from home_finance_cockpit.identity import (
    APP_AUTHOR,
    APP_COPYRIGHT,
    APP_LICENSE,
    APP_NAME,
    APP_RELEASE,
)
from home_finance_cockpit.localization import tr
from home_finance_cockpit.paths import RESOURCE_ROOT, data_directory
from home_finance_cockpit.ui.components import label


class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(label(APP_NAME, "section"))
        layout.addWidget(label(APP_RELEASE))
        layout.addWidget(label(tr("Autor: {name}", name=APP_AUTHOR)))
        layout.addWidget(label(APP_COPYRIGHT))
        layout.addWidget(label(tr("Licencja: {license}", license=APP_LICENSE)))
        note = label(
            tr(
                "Wersja beta do testów. Przed użyciem rzeczywistych danych wykonaj kopię bazy. "
                "Program można modyfikować i rozpowszechniać zgodnie z GPLv3. "
                "Nie udziela się gwarancji w zakresie dopuszczonym przez prawo."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        tabs = QTabWidget()
        for caption, filename in (
            ("Licencja", "LICENSE"),
            ("Biblioteki i materiały", "THIRD_PARTY_NOTICES.md"),
            ("Kod źródłowy", "SOURCE_CODE.md"),
        ):
            field = QPlainTextEdit()
            field.setReadOnly(True)
            path = RESOURCE_ROOT / filename
            field.setPlainText(
                path.read_text(encoding="utf-8")
                if path.is_file()
                else tr("Dokument jest dostępny w pakiecie wydania.")
            )
            tabs.addTab(field, tr(caption))
        layout.addWidget(tabs, 1)
        diagnostics = QPushButton(tr("Otwórz folder diagnostyczny"))
        diagnostics.clicked.connect(self.open_diagnostics)
        layout.addWidget(diagnostics)

    def open_diagnostics(self):
        folder = data_directory() / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
