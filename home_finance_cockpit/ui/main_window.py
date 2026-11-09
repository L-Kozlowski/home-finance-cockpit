"""Application composition and navigation."""

import sqlite3
from datetime import datetime

from PyQt6.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFileDialog,
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.identity import APP_NAME
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.analysis import group_wallet_balances
from home_finance_cockpit.services.backups import BackupService
from home_finance_cockpit.services.preferences import Preferences
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.analyses import AnalysesTab
from home_finance_cockpit.ui.branding import application_icon
from home_finance_cockpit.ui.category_workbench import CategoryManagerPage
from home_finance_cockpit.ui.common import fill_table, selected_ids, show_error
from home_finance_cockpit.ui.components import icon
from home_finance_cockpit.ui.dashboard import Dashboard
from home_finance_cockpit.ui.editors import TransactionDialog, WalletDialog
from home_finance_cockpit.ui.import_dialog import ImportDialog
from home_finance_cockpit.ui.navigation import WorkspaceShell
from home_finance_cockpit.ui.reports import ReportGeneratorPage
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.transactions_page import TransactionsPage
from home_finance_cockpit.ui.wallets_page import WalletsPage


class FinanceApp(QMainWindow):
    open_database_requested = pyqtSignal()
    new_database_requested = pyqtSignal()
    language_changed = pyqtSignal(str)

    def __init__(self, db=None, *, settings=None):
        super().__init__()
        self.db = db if db is not None else Database()
        self.report_generator = None
        self.preferences = Preferences(self.db.path, settings)
        from PyQt6.QtWidgets import QApplication

        from home_finance_cockpit.localization import install_qt_language, set_language

        set_language(self.preferences.language())
        install_qt_language(QApplication.instance())
        from home_finance_cockpit.ui.chart_dates import set_date_format

        set_date_format(self.preferences.date_format())
        from PyQt6.QtWidgets import QApplication

        from home_finance_cockpit.domain.chart_palettes import set_palette
        from home_finance_cockpit.ui.theme import apply_font_size

        set_palette(self.preferences.chart_palette())
        apply_font_size(QApplication.instance(), self.preferences.font_size())
        self.backups = BackupService(self.db, self.preferences, self)
        from home_finance_cockpit.services.exchange_rates import ExchangeRateService

        self.exchange_rates = ExchangeRateService(self.db, self)
        self.exchange_rates.changed.connect(self.refresh_rate_visualizations)
        self.backups.failed.connect(
            lambda message: show_error(
                self, tr("Nie udało się wykonać automatycznej kopii: {message}", message=message)
            )
        )
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(application_icon())
        self.setAcceptDrops(True)
        available = self.screen().availableGeometry()
        self.resize(min(px(1500), available.width() - 30), min(px(950), available.height() - 50))
        self.setMinimumSize(px(900), px(580))
        self.build_workspace()
        self.backups.start()
        self.exchange_rates.start()

    def build_workspace(self):
        from PyQt6.QtWidgets import QApplication

        self.build_menu()
        self.menuBar().hide()
        self.tabs = QTabWidget()
        self.dashboard = Dashboard(self.db)
        self.tabs.addTab(self.dashboard, tr("Przegląd"))
        self.transaction_page = TransactionsPage(self.db, self)
        self.transaction_filters = self.transaction_page.filters
        self.wallet_filter = self.transaction_filters.wallet
        self.transaction_search = self.transaction_page.search
        self.transaction_count = self.transaction_page.count
        self.transaction_wallet_summary = self.transaction_page.filter_summary
        self.transaction_filter_button = self.transaction_page.filter_button
        self.tx_table = self.transaction_page.table
        self.tabs.addTab(self.transaction_page, tr("Transakcje"))
        self.wallet_page = WalletsPage(self.db, self)
        self.wallet_table = self.wallet_page.table
        self.tabs.addTab(self.wallet_page, tr("Portfele"))
        from home_finance_cockpit.ui.import_history import ImportHistoryPage

        self.history_page = ImportHistoryPage(self.db, self)
        self.history_table = self.history_page.table
        self.tabs.addTab(self.history_page, tr("Historia importów"))
        self.analyses = AnalysesTab(self.db)
        self.tabs.addTab(self.analyses, tr("Analizy"))
        self.category_page = CategoryManagerPage(None, self.db)
        self.category_page.changed.connect(self.refresh_ui)
        self.tabs.addTab(self.category_page, tr("Kategorie i reguły"))
        self.report_generator = ReportGeneratorPage(self, self.db)
        self.report_generator.panel.busy_changed.connect(self.set_report_busy)
        self.tabs.addTab(self.report_generator, tr("Generuj raport"))
        from home_finance_cockpit.ui.goal_workspace import SavingsGoalsPage

        self.goals_page = SavingsGoalsPage(self.db)
        self.goals_page.changed.connect(self.refresh_ui)
        self.tabs.addTab(self.goals_page, tr("Cele oszczędnościowe"))
        self.summary_mode = self.dashboard.summary_mode
        self.summary_table = self.dashboard.summary_table
        self.summary_mode.currentIndexChanged.connect(self.refresh_summary)
        self.summary_table.setToolTip(
            tr(
                "Saldo początkowe + wszystkie zapisane transakcje. Niezależne od filtrów dashboardu."
            )
        )
        self.workspace = WorkspaceShell(
            self.tabs,
            self.db.path,
            import_csv=self.import_csv,
            add_transaction=self.add_transaction,
            add_wallet=self.add_wallet,
            add_goal=self.goals_page.add,
            settings=self.show_settings,
            report=self.show_report_generator,
            database_menu=self.database_menu,
            undo=self.undo_deletion,
        )
        self.setCentralWidget(self.workspace)
        self.workspace.set_category_actions(self.category_page)
        self.workspace.set_analysis_actions(self.analyses)
        from home_finance_cockpit.ui.theme import apply_theme

        apply_theme(QApplication.instance(), self.preferences.theme())
        for index in range(self.tabs.count()):
            self.tabs.widget(index).setObjectName("page")
        self.tabs.currentChanged.connect(self.guard_navigation)
        self.refresh_ui()
        self.tabs.setCurrentIndex(self.preferences.start_page())
        from home_finance_cockpit.ui.navigation_history import NavigationHistory

        self.navigation_history = NavigationHistory(self)
        self.apply_shortcuts()

    def guard_navigation(self, index):
        if index != 5 and not self.category_page.guard_pending():
            self.tabs.setCurrentIndex(5)
            return
        if index != 7 and not self.goals_page.guard_pending():
            self.tabs.setCurrentIndex(7)
            return
        if index != 1 and not self.transaction_page.inspector.guard_pending():
            self.tabs.setCurrentIndex(1)

    def change_language(self, value):
        from PyQt6.QtWidgets import QApplication, QComboBox, QDateEdit

        from home_finance_cockpit.localization import install_qt_language, language, set_language

        if language() == value:
            return True
        if (
            self.report_generator.panel.is_running
            or not self.transaction_page.inspector.guard_pending()
            or not self.goals_page.guard_pending()
            or not self.category_page.guard_pending()
        ):
            return False
        current_page = self.tabs.currentIndex()
        sources = [self.dashboard, self.transaction_filters, self.analyses]
        snapshots = []
        fields = (
            "currency",
            "wallet",
            "preset",
            "start",
            "end",
            "year",
            "month",
            "mode",
            "exclude",
            "omit_salary",
            "percentage",
            "top_n",
        )
        for owner in sources:
            state = {}
            for field in fields:
                widget = getattr(owner, field, None)
                if isinstance(widget, QComboBox):
                    state[field] = ("combo", widget.currentData())
                elif isinstance(widget, QDateEdit):
                    state[field] = ("date", widget.date())
                elif hasattr(widget, "isChecked"):
                    state[field] = ("check", widget.isChecked())
                elif hasattr(widget, "value"):
                    state[field] = ("value", widget.value())
            snapshots.append((state, set(getattr(owner, "selected_category_ids", set()))))
        search, mode = self.transaction_search.text(), self.transaction_page.mode
        group = self.analyses.tabs.currentIndex()
        summary = self.summary_mode.currentData()
        geometry = self.saveGeometry()
        for page in (self.dashboard, self.analyses, self.wallet_page):
            page.close_chart_windows()
        old = self.takeCentralWidget()
        old.hide()
        self.menuBar().clear()
        set_language(value)
        install_qt_language(QApplication.instance())
        self.build_workspace()
        for owner, (state, categories) in zip(
            (self.dashboard, self.transaction_filters, self.analyses), snapshots
        ):
            owner.selected_category_ids = categories
            for field, (kind, item) in state.items():
                widget = getattr(owner, field)
                if kind == "combo":
                    widget.setCurrentIndex(max(0, widget.findData(item)))
                elif kind == "date":
                    widget.setDate(item)
                elif kind == "check":
                    widget.setChecked(item)
                else:
                    widget.setValue(item)
        self.transaction_search.setText(search)
        self.transaction_page.set_mode(mode)
        self.analyses.tabs.setCurrentIndex(group)
        self.summary_mode.setCurrentIndex(max(0, self.summary_mode.findData(summary)))
        self.tabs.setCurrentIndex(current_page)
        self.restoreGeometry(geometry)
        self.refresh_ui()
        old.deleteLater()
        self.language_changed.emit(value)
        return True

    def focus_transaction_search(self):
        self.tabs.setCurrentIndex(1)
        self.transaction_search.setFocus()
        self.transaction_search.selectAll()

    def apply_shortcuts(self):
        from home_finance_cockpit.services.shortcuts import load

        for shortcut in getattr(self, "shortcuts", {}).values():
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        callbacks = {
            key: (lambda index=index: self.tabs.setCurrentIndex(index))
            for index, key in enumerate(
                (
                    "overview",
                    "transactions",
                    "wallets",
                    "imports",
                    "analytics",
                    "categories",
                    "reports",
                    "goals",
                )
            )
        }
        callbacks.update(
            settings=self.show_settings,
            currencies=lambda: self.manage("currencies"),
            add_goal=self.goals_page.add,
            add_transaction=self.add_transaction,
            add_wallet=self.add_wallet,
            import_=self.import_csv,
            open_database=self.open_database_requested.emit,
            new_database=self.new_database_requested.emit,
            backup=self.backup,
            search=self.focus_transaction_search,
            refresh=self.refresh_ui,
            undo=self.undo_from_shortcut,
        )
        callbacks.update(
            navigate_back=self.navigation_history.back,
            navigate_forward=self.navigation_history.forward,
        )
        callbacks["import"] = callbacks.pop("import_")
        self.shortcuts = {}
        for key, binding in load(self.preferences.settings).items():
            shortcut = QShortcut(QKeySequence(binding), self)
            shortcut.activated.connect(callbacks[key])
            shortcut.setEnabled(bool(binding) and not self.report_generator.panel.is_running)
            self.shortcuts[key] = shortcut
        self.search_shortcut = self.shortcuts["search"]
        self.import_shortcut = self.shortcuts["import"]
        self.undo_shortcut = self.shortcuts["undo"]

    def show_settings(self):
        from home_finance_cockpit.ui.settings import SettingsDialog

        dialog = SettingsDialog(self)
        dialog.exec()
        dialog.deleteLater()

    @staticmethod
    def add_button(layout, label, callback):
        button = QPushButton(tr(label))
        if label.startswith("Usuń"):
            button.setProperty("role", "danger")
        button.clicked.connect(callback)
        layout.addWidget(button)

    def build_menu(self):
        menu = self.menuBar().addMenu(tr("Plik"))
        self.database_menu = menu
        menu.addAction(tr("Otwórz bazę danych…"), lambda: self.open_database_requested.emit())
        menu.addAction(tr("Utwórz nową bazę danych…"), lambda: self.new_database_requested.emit())
        menu.addSeparator()
        menu.addAction(tr("Kopia zapasowa bazy…"), self.backup)
        menu.addAction(tr("Zamknij"), self.close)
        manage = self.menuBar().addMenu(tr("Zarządzaj"))
        for label, kind in (("Kategorie i reguły", "categories"), ("Waluty", "currencies")):
            manage.addAction(tr(label), lambda checked=False, k=kind: self.manage(k))
        self.menuBar().addAction(tr("Import CSV"), self.import_csv)
        self.menuBar().addAction(tr("Generuj raporty…"), self.show_report_generator)
        self.menuBar().addAction(tr("Odśwież"), self.refresh_ui)

    def refresh_ui(self):
        self.goals_page.refresh()
        self.dashboard.goals_summary.refresh()
        self.refresh_valuation()
        self.workspace.undo_button.setEnabled(self.db.can_undo_delete())
        self.category_page.refresh()
        self.transaction_filters.refresh_choices()
        self.refresh_transactions()
        self.balance_snapshot = list(self.db.wallet_balances())
        self.refresh_summary()
        self.wallet_page.refresh()
        self.history_page.refresh()
        self.history_records = self.history_page.records
        self.dashboard.refresh_filters()
        self.analyses.refresh_filters()
        if self.report_generator is not None:
            self.report_generator.panel.refresh_filters()
        self.setWindowTitle(APP_NAME)

    def undo_from_shortcut(self):
        from PyQt6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit

        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit)):
            focus.undo()
        else:
            self.undo_deletion()

    def undo_deletion(self):
        if not self.db.can_undo_delete() or not self.transaction_page.inspector.guard_pending():
            return
        try:
            self.db.undo_delete()
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            return
        self.refresh_ui()

    def refresh_summary(self, *_):
        with QSignalBlocker(self.summary_table):
            self._refresh_summary()

    def _refresh_summary(self):
        wallets = getattr(self, "balance_snapshot", [])
        if self.summary_mode.currentData() == "currency":
            self.summary_table.setColumnCount(2)
            self.summary_table.setHorizontalHeaderLabels([tr("Waluta"), tr("Suma sald portfeli")])
            data = group_wallet_balances(wallets)
            fill_table(
                self.summary_table,
                [[code, amount_label(group["balance"])] for code, group in data.items()],
            )
        else:
            self.summary_table.setColumnCount(4)
            self.summary_table.setHorizontalHeaderLabels(
                [tr("Portfel"), tr("Saldo"), tr("Waluta"), tr("Na wykresie")]
            )
            fill_table(
                self.summary_table,
                [[w["name"], amount_label(w["balance"]), w["currency"], ""] for w in wallets],
                [w["id"] for w in wallets],
            )
            for row, wallet in enumerate(wallets):
                self.summary_table.item(row, 0).setIcon(icon(wallet["icon_name"]))
                check = self.summary_table.item(row, 3)
                check.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                check.setCheckState(
                    Qt.CheckState.Unchecked
                    if wallet["id"] in self.dashboard.excluded_chart_wallet_ids
                    else Qt.CheckState.Checked
                )
            self.summary_table.resizeColumnToContents(0)
        header = self.summary_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, self.summary_table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

    @property
    def transactions(self):
        return self.transaction_page.records

    def refresh_transactions(self, *_):
        self.transaction_page.refresh()

    def show_report_generator(self):
        self.report_generator.panel.refresh_filters()
        self.tabs.setCurrentIndex(6)

    def add_wallet(self):
        if WalletDialog(self, self.db).exec():
            self.refresh_ui()

    def edit_wallet(self):
        ids = selected_ids(self.wallet_table)
        if len(ids) != 1:
            QMessageBox.information(self, tr("Edycja"), tr("Wybierz jeden portfel."))
            return
        if WalletDialog(self, self.db, self.db.wallet(ids[0])).exec():
            self.refresh_ui()

    def add_transaction(self):
        if not self.db.wallets():
            QMessageBox.information(
                self, tr("Brak portfeli"), tr("Najpierw dodaj portfel w zakładce Portfele.")
            )
            return
        if TransactionDialog(self, self.db).exec():
            self.refresh_ui()

    def edit_transaction(self):
        ids = selected_ids(self.tx_table)
        if len(ids) != 1:
            QMessageBox.information(self, tr("Edycja"), tr("Wybierz jedną transakcję."))
            return
        if not self.transaction_page.inspector.guard_pending():
            return
        record = self.db.transactions(transaction_id=ids[0])[0]
        if TransactionDialog(self, self.db, record).exec():
            self.refresh_ui()

    def delete_records(self, kind, widget):
        ids = selected_ids(widget)
        if not ids:
            QMessageBox.information(self, tr("Usuwanie"), tr("Zaznacz rekordy do usunięcia."))
            return
        if kind == "transactions" and not self.transaction_page.inspector.guard_pending():
            return
        if (
            QMessageBox.question(
                self, tr("Usuwanie"), tr("Usunąć {v0} zaznaczonych rekordów?", v0=len(ids))
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.db.delete(kind, ids)
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
        self.refresh_ui()

    def delete_import_transactions(self, import_id):
        try:
            record = next((r for r in self.db.import_history() if r["id"] == import_id), None)
            if record is None:
                raise ValueError(tr("Wybrany import już nie istnieje."))
            count = record["current_count"]
            question = tr(
                "Usunąć {v0} transakcji powiązanych z importem pliku „{v1}” do portfela „{v2}”?\n\nDotyczy to również transakcji edytowanych po imporcie. Wpis w historii zostanie usunięty. Ponowny import CSV może przywrócić usunięte operacje.",
                v0=count,
                v1=record["file_name"],
                v2=record["wallet"],
            )
            if (
                QMessageBox.question(
                    self,
                    tr("Usuń transakcje importu"),
                    tr(question),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
            deleted = self.db.delete_import_transactions(import_id, expected_count=count)
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            self.refresh_ui()
            return
        self.refresh_ui()
        QMessageBox.information(
            self, tr("Transakcje usunięte"), tr("Usunięto transakcji: {v0}.", v0=deleted)
        )

    def manage(self, kind):
        if kind in ("categories", "rules"):
            self.category_page.refresh()
            self.tabs.setCurrentIndex(5)
            return
        if kind == "currencies":
            from home_finance_cockpit.ui.settings import SettingsDialog

            dialog = SettingsDialog(self, section=2)
            dialog.exec()
            dialog.deleteLater()
            return
        raise ValueError(tr("Nieobsługiwany rodzaj ustawień."))

    def dragEnterEvent(self, event):
        if ImportDialog.dropped_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = ImportDialog.dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.import_csv(paths)
        else:
            event.ignore()

    def import_csv(self, paths=None):
        existing = getattr(self, "import_dialog", None)
        if existing is not None:
            if isinstance(paths, (list, tuple)) and paths:
                existing.load_paths(
                    [*existing.paths, *paths], preserve_mapping=bool(existing.files)
                )
            existing.showNormal()
            existing.raise_()
            existing.activateWindow()
            return
        if not self.db.wallets():
            QMessageBox.information(
                self, tr("Brak portfeli"), tr("Najpierw dodaj portfel w zakładce Portfele.")
            )
            return
        dialog = ImportDialog(self, self.db)
        self.import_dialog = dialog
        if self.tabs.currentIndex() == 2:
            wallet = self.wallet_page.selected_wallet()
            if wallet is not None:
                dialog.wallet.setCurrentIndex(dialog.wallet.findData(wallet["id"]))
        if isinstance(paths, (list, tuple)) and paths:
            dialog.load_paths(paths)

        def finish(result):
            self.import_dialog = None
            if result:
                self.refresh_ui()
            dialog.deleteLater()

        dialog.finished.connect(finish)
        dialog.show()

    def backup(self):
        name = "finans_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
        path, _ = QFileDialog.getSaveFileName(self, tr("Kopia zapasowa"), name, tr("SQLite (*.db)"))
        if not path:
            return
        try:
            self.db.backup(path)
        except (ValueError, sqlite3.Error, OSError) as exc:
            show_error(self, exc)
        else:
            QMessageBox.information(self, tr("Kopia zapasowa"), tr("Zapisano kopię bazy."))

    def closeEvent(self, event):
        if not self.category_page.guard_pending():
            event.ignore()
            return
        if not self.goals_page.guard_pending():
            event.ignore()
            return
        if self.report_generator is not None and self.report_generator.panel.is_running:
            event.ignore()
            self.tabs.setCurrentIndex(6)
            self.report_generator.panel.status.setText(
                tr("Przed zamknięciem aplikacji poczekaj na raporty lub anuluj generowanie.")
            )
            return
        if not self.transaction_page.inspector.guard_pending():
            event.ignore()
            return
        self.backups.stop()
        if getattr(self, "import_dialog", None) is not None:
            self.import_dialog.reject()
        self.exchange_rates.stop()
        self.dashboard.close_chart_windows()
        self.analyses.close_chart_windows()
        self.wallet_page.close_chart_windows()
        if self.report_generator is not None:
            self.report_generator.close()
        self.db.close()
        event.accept()

    def refresh_rate_visualizations(self):
        self.refresh_valuation()
        self.dashboard.refresh()
        self.analyses.refresh()

    def refresh_valuation(self):
        from decimal import ROUND_HALF_UP, Decimal

        balances = list(self.db.wallet_balances())
        missing = set()
        sources = set()
        total = Decimal(0)
        for wallet in balances:
            if not wallet["balance"]:
                continue
            rate, source = self.db.effective_rate(wallet["currency"])
            if rate is None:
                missing.add(wallet["currency"])
            else:
                total += wallet["balance"] * rate
            sources.add(source)
        if missing:
            self.dashboard.valuation.setText(
                tr("Brak kursów: {codes}", codes=", ".join(sorted(missing)))
            )
        else:
            text = tr(
                "Wartość wszystkich portfeli: {amount}",
                amount=amount_label(
                    int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)), "PLN"
                ),
            )
            if "cached" in sources:
                text += " · " + tr("Ostatni zapisany kurs NBP")
            if "fallback" in sources:
                text += " · " + tr("Ręczny kurs zastępczy")
            self.dashboard.valuation.setText(text)

    def set_report_busy(self, busy):
        self.menuBar().setEnabled(not busy)
        self.workspace.sidebar.setEnabled(not busy)
        self.workspace.import_button.setEnabled(not busy)
        self.workspace.add_button.setEnabled(not busy)
        for index in range(self.tabs.count()):
            if index != 6:
                self.tabs.widget(index).setEnabled(not busy)
        for shortcut in self.shortcuts.values():
            shortcut.setEnabled(not busy and not shortcut.key().isEmpty())
