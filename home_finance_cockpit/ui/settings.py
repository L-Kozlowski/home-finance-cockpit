"""Settings window with database, currency and general sections."""

import sqlite3
from pathlib import Path

from PyQt6.QtCore import QSize, QTime, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.identity import APP_NAME
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.preferences import INTERVALS, START_PAGES
from home_finance_cockpit.ui.common import show_error
from home_finance_cockpit.ui.components import icon, label
from home_finance_cockpit.ui.currency_manager import CurrencyManagerPage
from home_finance_cockpit.ui.scaling import px


class SettingsDialog(QDialog):
    def __init__(self, host, section=0):
        super().__init__(host)
        self.host, self.preferences, self.backups = host, host.preferences, host.backups
        self.build_controls(section)

    def build_controls(self, section=0):
        host = self.host
        self.setWindowTitle((tr("Ustawienia — ") + APP_NAME))
        self.setSizeGripEnabled(True)
        available = self.screen().availableGeometry()
        self.resize(min(px(1080), available.width() - 40), min(px(780), available.height() - 60))
        root = QVBoxLayout(self)
        root.addWidget(label(tr("Ustawienia"), "section"))
        main = QHBoxLayout()
        self.sections = QListWidget()
        for caption, glyph in (
            ("Ogólne", "settings"),
            ("Baza danych i kopie", "database"),
            ("Waluty", "cash"),
            ("Skróty klawiszowe", "keyboard"),
            ("O aplikacji", "file"),
        ):
            item = QListWidgetItem(icon(glyph), tr(caption))
            item.setSizeHint(QSize(px(180), px(42)))
            self.sections.addItem(item)
        self.sections.setSpacing(px(3))
        self.sections.setFixedWidth(px(195))
        main.addWidget(self.sections)
        self.pages = QStackedWidget()
        main.addWidget(self.pages, 1)
        root.addLayout(main, 1)
        database = QWidget()
        form = QFormLayout(database)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.database_path = self.readonly(
            str(Path(host.db.path).resolve())
            if host.db.path != ":memory:"
            else "Baza w pamięci — niezapisana w pliku"
        )
        form.addRow(tr("Aktywna baza:"), self.database_path)
        self.encryption_status = label("")
        form.addRow(tr("Ochrona bazy:"), self.encryption_status)
        password_buttons = QHBoxLayout()
        self.password_button = QPushButton()
        self.password_button.clicked.connect(lambda: self.manage_password())
        self.remove_password_button = QPushButton(tr("Usuń hasło"))
        self.remove_password_button.clicked.connect(lambda: self.manage_password(remove=True))
        password_buttons.addWidget(self.password_button)
        password_buttons.addWidget(self.remove_password_button)
        form.addRow(password_buttons)
        self.refresh_encryption_status()
        form.addRow(
            label(
                tr(
                    "Nowe kopie zachowują szyfrowanie i hasło z chwili ich utworzenia. Wcześniejsze kopie nie zmieniają się automatycznie."
                )
            )
        )
        self.backup_enabled = QCheckBox(tr("Włącz automatyczne kopie tej bazy"))
        self.backup_enabled.setEnabled(host.db.path != ":memory:")
        self.frequency = QComboBox()
        for seconds, caption in INTERVALS:
            self.frequency.addItem(tr(caption), seconds)
        self.backup_folder = QLineEdit()
        browse = QPushButton(tr("Wybierz folder…"))
        browse.clicked.connect(self.browse_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.backup_folder, 1)
        folder_row.addWidget(browse)
        enabled, interval, folder = self.preferences.backup_config()
        self.backup_enabled.setChecked(enabled and host.db.path != ":memory:")
        self.frequency.setCurrentIndex(self.frequency.findData(interval))
        self.backup_folder.setText(folder)
        self.backup_folder.setCursorPosition(0)
        self.backup_folder.setToolTip(folder)
        self.backup_folder.textChanged.connect(self.backup_folder.setToolTip)
        form.addRow(self.backup_enabled)
        form.addRow(tr("Częstotliwość:"), self.frequency)
        form.addRow(tr("Folder kopii:"), folder_row)
        form.addRow(
            label(
                tr(
                    "Harmonogram działa podczas pracy aplikacji. Zaległa kopia zostanie wykonana po jej ponownym uruchomieniu. Kopie nie są automatycznie usuwane."
                )
            )
        )
        self.last_time, self.last_path, self.next_time = label(""), self.readonly(""), label("")
        self.backup_status = label("")
        form.addRow(tr("Ostatnia udana kopia:"), self.last_time)
        form.addRow(tr("Plik ostatniej kopii:"), self.last_path)
        form.addRow(tr("Następna kopia:"), self.next_time)
        form.addRow(self.backup_status)
        self.backup_now = QPushButton(tr("Wykonaj kopię teraz"))
        self.backup_now.clicked.connect(self.create_backup)
        form.addRow(self.backup_now)
        form.addRow(
            label(
                tr(
                    "Folder i częstotliwość dotyczą tej bazy. Ustawienia ogólne dotyczą całej aplikacji. Zmiany harmonogramu zatwierdź przyciskiem Zapisz ustawienia."
                )
            )
        )
        self.add_scroll_page(database)
        self.currencies = CurrencyManagerPage(None, host.db, service=host.exchange_rates)
        self.currencies.changed.connect(host.refresh_ui)
        currency_page = QWidget()
        currency_layout = QVBoxLayout(currency_page)
        currency_layout.addWidget(self.currencies, 1)
        self.pages.addWidget(currency_page)
        general = QWidget()
        general_form = QFormLayout(general)
        general_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.language_combo = QComboBox()
        self.language_combo.addItem("Polski", "pl")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(
            self.language_combo.findData(self.preferences.language())
        )
        general_form.addRow(tr("Język:"), self.language_combo)
        self.start_page = QComboBox()
        for index, caption in START_PAGES:
            self.start_page.addItem(tr(caption), index)
        self.start_page.setCurrentIndex(self.start_page.findData(self.preferences.start_page()))
        general_form.addRow(tr("Po otwarciu bazy pokaż:"), self.start_page)
        from home_finance_cockpit.ui.chart_dates import DATE_FORMATS

        self.date_format = QComboBox()
        self.date_format.addItems(DATE_FORMATS)
        self.date_format.setCurrentText(self.preferences.date_format())
        general_form.addRow(tr("Format dat:"), self.date_format)
        from home_finance_cockpit.services.preferences import FONT_POINTS

        self.font_size = QComboBox()
        for points in FONT_POINTS:
            self.font_size.addItem(str(points), points)
        self.font_size.setCurrentIndex(self.font_size.findData(self.preferences.font_points()))
        general_form.addRow(tr("Rozmiar czcionki (pt):"), self.font_size)
        from home_finance_cockpit.domain.chart_palettes import PALETTES

        self.chart_palette = QComboBox()
        for key, (caption, colors) in PALETTES.items():
            self.chart_palette.addItem(tr(caption), key)
        self.chart_palette.setCurrentIndex(
            self.chart_palette.findData(self.preferences.chart_palette())
        )
        general_form.addRow(tr("Paleta wykresów i kategorii:"), self.chart_palette)
        self.palette_preview = QWidget()
        self.palette_preview_layout = QHBoxLayout(self.palette_preview)
        self.palette_preview_layout.setContentsMargins(0, 0, 0, 0)
        general_form.addRow(tr("Podgląd palety:"), self.palette_preview)
        self.chart_palette.setToolTip(
            tr("Kategorie z własnym kolorem zachowują go. Pozostałe korzystają z wybranej palety.")
        )
        self.chart_palette.currentIndexChanged.connect(self.update_palette_preview)
        self.update_palette_preview()
        general_form.addRow(
            tr("Plik ustawień:"), self.readonly(self.preferences.settings.fileName())
        )
        self.theme = QComboBox()
        self.theme.addItem(tr("Ciemny"), "dark")
        self.theme.addItem(tr("Jasny"), "light")
        self.theme.setCurrentIndex(self.theme.findData(self.preferences.theme()))
        general_form.addRow(tr("Motyw:"), self.theme)
        self.add_scroll_page(general)
        general_page = self.pages.widget(2)
        self.pages.removeWidget(general_page)
        self.pages.insertWidget(0, general_page)
        from home_finance_cockpit.ui.shortcut_settings import ShortcutSettings

        self.shortcut_page = ShortcutSettings(self.preferences.settings)
        self.add_scroll_page(self.shortcut_page)
        from home_finance_cockpit.ui.about import AboutPage

        self.pages.addWidget(AboutPage())
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sections.setCurrentRow(section)
        buttons = QHBoxLayout()
        self.message = label("")
        buttons.addWidget(self.message, 1)
        close = QPushButton(tr("Zamknij"))
        close.clicked.connect(self.reject)
        self.save_button = QPushButton(tr("Zapisz"))
        self.save_button.setProperty("role", "primary")
        self.save_button.clicked.connect(self.save)
        self.save_feedback = QTimer(self)
        self.save_feedback.setSingleShot(True)
        self.save_feedback.timeout.connect(lambda: self.save_button.setText(tr("Zapisz")))
        buttons.addWidget(close)
        buttons.addWidget(self.save_button)
        self.save_close_button = QPushButton(tr("Zapisz i zamknij"))
        self.save_close_button.clicked.connect(self.save_and_close)
        buttons.addWidget(self.save_close_button)
        root.addLayout(buttons)
        self.backups.changed.connect(self.refresh_status)
        self.finished.connect(self.disconnect_status)
        self.refresh_status()

    @staticmethod
    def readonly(value):
        field = QLineEdit(value)
        field.setReadOnly(True)
        field.setCursorPosition(0)
        field.setToolTip(value)
        return field

    def refresh_encryption_status(self):
        encrypted = self.host.db.is_encrypted
        self.encryption_status.setText(
            tr(
                "Szyfrowanie SQLCipher włączone"
                if encrypted
                else "Baza bez hasła — plik nie jest szyfrowany"
            )
        )
        self.password_button.setText(tr("Zmień hasło" if encrypted else "Ustaw hasło"))
        self.password_button.setEnabled(self.host.db.path != ":memory:")
        self.remove_password_button.setVisible(encrypted)

    def manage_password(self, *, remove=False):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication

        from home_finance_cockpit.ui.database_password import DatabasePasswordDialog

        if self.host.report_generator.panel.is_running:
            show_error(self, ValueError(tr("Poczekaj na zakończenie generowania raportów.")))
            return
        dialog = DatabasePasswordDialog(self, encrypted=self.host.db.is_encrypted, remove=remove)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.host.db.change_password(
                    None if remove else dialog.new.text(), dialog.current.text()
                )
            finally:
                QApplication.restoreOverrideCursor()
            self.refresh_encryption_status()
            self.message.setText(
                tr(
                    "Usunięto hasło i wyłączono szyfrowanie."
                    if remove
                    else "Zapisano hasło. Plik bazy jest szyfrowany."
                )
            )
        except (ValueError, OSError, sqlite3.Error) as exc:
            show_error(self, exc)
        finally:
            dialog.clear_passwords()
            dialog.deleteLater()

    def update_palette_preview(self):
        from home_finance_cockpit.domain.chart_palettes import PALETTES

        while self.palette_preview_layout.count():
            item = self.palette_preview_layout.takeAt(0)
            item.widget().deleteLater()
        for color in PALETTES[self.chart_palette.currentData()][1]:
            swatch = label("")
            swatch.setProperty("preserveColors", True)
            swatch.setMinimumHeight(px(24))
            swatch.setToolTip(color)
            swatch.setStyleSheet(f"background:{color}; border-radius:4px;")
            self.palette_preview_layout.addWidget(swatch)

    def add_scroll_page(self, page):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)

    def disconnect_status(self):
        try:
            self.backups.changed.disconnect(self.refresh_status)
        except TypeError:
            pass

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, tr("Folder kopii zapasowych"), self.backup_folder.text()
        )
        if folder:
            self.backup_folder.setText(folder)

    def refresh_status(self):
        last = self.backups.last_backup()
        self.last_time.setText(
            (
                last.astimezone().strftime("%d.%m.%Y %H:%M:%S")
                if last
                else tr("Brak dostępnej kopii")
            )
        )
        path = str(self.preferences.get("last_backup_path"))
        self.last_path.setText(path)
        self.last_path.setToolTip(path)
        next_time = self.backups.next_backup()
        self.next_time.setText(
            (
                next_time.astimezone().strftime("%d.%m.%Y %H:%M:%S")
                if next_time
                else tr("Automatyczne kopie wyłączone")
            )
        )
        self.backup_status.setText(
            ((tr("Ostatni błąd: ") + self.backups.last_error) if self.backups.last_error else "")
        )

    def save(self):
        from home_finance_cockpit.localization import language

        selected_language = self.language_combo.currentData()
        language_changed = language() != selected_language
        if language_changed and self.host.report_generator.panel.is_running:
            show_error(
                self,
                ValueError(tr("Poczekaj na zakończenie generowania raportów przed zmianą języka.")),
            )
            return False
        if language_changed and not self.host.transaction_page.inspector.guard_pending():
            return False
        try:
            bindings = self.shortcut_page.bindings()
            self.currencies.exchange_settings.save()
            self.preferences.save(
                self.backup_enabled.isChecked(),
                self.frequency.currentData(),
                self.backup_folder.text(),
                self.start_page.currentData(),
            )
            from home_finance_cockpit.ui.chart_dates import set_date_format

            self.preferences.settings.setValue(
                "general/date_format", self.date_format.currentText()
            )
            self.preferences.settings.setValue("general/font_points", self.font_size.currentData())
            self.preferences.settings.setValue("general/theme", self.theme.currentData())
            self.preferences.settings.setValue(
                "general/chart_palette", self.chart_palette.currentData()
            )
            self.preferences.settings.setValue("general/language", selected_language)
            import json

            self.preferences.settings.setValue("general/shortcuts", json.dumps(bindings))
            self.preferences.sync()
            set_date_format(self.date_format.currentText())
            from PyQt6.QtWidgets import QApplication

            from home_finance_cockpit.domain.chart_palettes import set_palette
            from home_finance_cockpit.ui.theme import apply_font_size, apply_theme

            set_palette(self.chart_palette.currentData())
            apply_theme(QApplication.instance(), self.theme.currentData())
            apply_font_size(QApplication.instance(), self.font_size.currentData() * 10)
            self.host.workspace.sidebar.setFixedWidth(
                px(round(205 * max(1.0, self.font_size.currentData() / 10)))
            )
            from home_finance_cockpit.ui.charts import ChartDialog

            for dialog in self.host.findChildren(ChartDialog):
                dialog.refresh_chart()
            from home_finance_cockpit.ui.charts import ExpandableCanvas

            for canvas in self.host.findChildren(ExpandableCanvas):
                canvas.draw_idle()
        except (ValueError, OSError, sqlite3.Error) as exc:
            show_error(self, exc)
            return False
        self.backup_folder.setText(self.preferences.backup_config()[2])
        self.backups.start()
        self.refresh_status()
        if language_changed:
            self.host.change_language(selected_language)
            self.rebuild_controls()
        else:
            self.host.apply_shortcuts()
        self.host.refresh_ui()
        apply_theme(QApplication.instance(), self.theme.currentData())
        self.message.setText(
            (tr("Zapisano ustawienia · ") + QTime.currentTime().toString("HH:mm:ss"))
        )
        self.save_button.setText(tr("Zapisano"))
        self.save_feedback.start(1800)
        return True

    def rebuild_controls(self):
        section = self.sections.currentRow()
        geometry = self.saveGeometry()
        self.save_feedback.stop()
        self.save_feedback.deleteLater()
        self.disconnect_status()
        try:
            self.finished.disconnect(self.disconnect_status)
        except TypeError:
            pass
        holder = QWidget()
        holder.setLayout(self.layout())
        self.build_controls(section)
        self.restoreGeometry(geometry)
        holder.deleteLater()

    def save_and_close(self):
        if self.save():
            self.accept()
            self.host.refresh_ui()

    def create_backup(self):
        try:
            path = self.backups.create_backup(folder=self.backup_folder.text())
        except (ValueError, OSError, sqlite3.Error) as exc:
            show_error(self, exc)
            return
        self.message.setText((tr("Zapisano kopię: ") + path.name))
