"""Lightweight first window; importing this module never loads charts."""

from PyQt6.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.identity import APP_NAME
from home_finance_cockpit.localization import language, tr
from home_finance_cockpit.ui.branding import BrandLogo, application_icon


class StartupWindow(QWidget):
    open_last_requested = pyqtSignal()
    open_database_requested = pyqtSignal()
    new_database_requested = pyqtSignal()
    language_selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._busy = False
        self.setWindowTitle(tr("{v0} — wybierz bazę danych", v0=APP_NAME))
        self.setWindowIcon(application_icon())
        self.resize(520, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        title = BrandLogo(height=82)
        layout.addWidget(title)
        language_row = QHBoxLayout()
        self.language_label = QLabel(tr("Język"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("Polski", "pl")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(self.language_combo.findData(language()))
        self.language_combo.currentIndexChanged.connect(
            lambda: self.language_selected.emit(self.language_combo.currentData())
        )
        language_row.addWidget(self.language_label)
        language_row.addWidget(self.language_combo, 1)
        layout.addLayout(language_row)
        self.intro = QLabel(tr("Wybierz bazę danych, z którą chcesz pracować."))
        layout.addWidget(self.intro)
        self.last_button = QPushButton(tr("Otwórz ostatnio otwartą bazę danych"))
        self.last_button.clicked.connect(lambda: self.open_last_requested.emit())
        self.last_path = QLabel()
        self.last_path.setWordWrap(False)
        self.last_path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.last_path.setMinimumWidth(0)
        self.open_button = QPushButton(tr("Wybierz bazę danych do otwarcia…"))
        self.open_button.clicked.connect(lambda: self.open_database_requested.emit())
        self.new_button = QPushButton(tr("Utwórz nową bazę danych…"))
        self.new_button.clicked.connect(lambda: self.new_database_requested.emit())
        for widget in (self.last_button, self.last_path, self.open_button, self.new_button):
            layout.addWidget(widget)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        layout.addStretch()
        self.set_last_path(None)

    def set_last_path(self, path):
        self._last_path = path
        self._has_last = path is not None
        self.last_button.setEnabled(self._has_last)
        self.last_path.setToolTip(str(path) if path else "")
        self.update_path_label()

    def update_path_label(self):
        text = str(self._last_path) if self._last_path else tr("Nie otwarto jeszcze żadnej bazy.")
        self.last_path.setText(
            self.last_path.fontMetrics().elidedText(
                text, Qt.TextElideMode.ElideMiddle, max(40, self.width() - 56)
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_last_path"):
            self.update_path_label()

    def retranslate(self):
        self.language_label.setText(tr("Język"))
        with QSignalBlocker(self.language_combo):
            self.language_combo.setCurrentIndex(self.language_combo.findData(language()))
        self.setWindowTitle(tr("{v0} — wybierz bazę danych", v0=APP_NAME))
        self.intro.setText(tr("Wybierz bazę danych, z którą chcesz pracować."))
        self.last_button.setText(tr("Otwórz ostatnio otwartą bazę danych"))
        self.open_button.setText(tr("Wybierz bazę danych do otwarcia…"))
        self.new_button.setText(tr("Utwórz nową bazę danych…"))
        self.set_last_path(self._last_path)
        self.set_busy(self._busy)

    def set_busy(self, busy):
        self._busy = busy
        self.language_combo.setEnabled(not busy)
        self.last_button.setEnabled(not busy and self._has_last)
        self.open_button.setEnabled(not busy)
        self.new_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.status.setText((tr("Otwieranie bazy i ładowanie widoku…") if busy else ""))

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            event.accept()
