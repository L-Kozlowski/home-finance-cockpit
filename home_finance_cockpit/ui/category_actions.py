"""Two-level category tree, keyword rules, JSON import and explicit classification."""

import sqlite3

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QWidget,
)

from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.categorization import apply_rules
from home_finance_cockpit.services.category_files import export_category_file, import_category_file
from home_finance_cockpit.ui.common import show_error
from home_finance_cockpit.ui.editors import CategoryDialog


class CategoryManagerBase(QWidget):
    changed = pyqtSignal()

    def notify_changed(self):
        self.refresh()
        self.changed.emit()

    def add_root(self):
        if CategoryDialog(self, self.db).exec():
            self.notify_changed()

    def add_child(self):
        selected = self.selected_category()
        if selected is None or selected["is_default"]:
            QMessageBox.information(
                self, tr("Podkategoria"), tr("Wybierz kategorię nadrzędną inną niż domyślna.")
            )
            return
        parent_id = selected["parent_id"] if selected["parent_id"] is not None else selected["id"]
        if CategoryDialog(self, self.db, parent_id=parent_id).exec():
            self.notify_changed()

    def edit_category(self):
        selected = self.selected_category()
        if selected is not None and CategoryDialog(self, self.db, selected).exec():
            self.notify_changed()

    def delete_category(self):
        selected = self.selected_category()
        if selected is None:
            return
        if selected["is_default"]:
            QMessageBox.information(
                self, tr("Kategoria"), tr("Nie można usunąć domyślnej kategorii.")
            )
            return
        if (
            QMessageBox.question(
                self,
                tr("Usuń kategorię"),
                tr(
                    "Usunąć {v0} wraz z podkategoriami i regułami? Powiązane transakcje zostaną przeniesione do kategorii Ogólne.",
                    v0=selected["display_name"],
                ),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.db.delete_category_tree(selected["id"])
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            return
        self.tree.clearSelection()
        self.notify_changed()

    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Eksportuj JSON"), "categories.json", tr("JSON (*.json)")
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            export_category_file(self.db, path)
        except (ValueError, OSError, sqlite3.Error) as exc:
            show_error(self, exc)
            return
        QMessageBox.information(
            self, tr("Eksportuj JSON"), tr("Zapisano kategorie i reguły do pliku JSON.")
        )

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Wczytaj kategorie i słowa kluczowe"), "", tr("JSON (*.json)")
        )
        if not path:
            return
        try:
            categories, rules, repeated = import_category_file(self.db, path)
        except (ValueError, OSError, sqlite3.Error) as exc:
            show_error(self, exc)
            return
        self.notify_changed()
        response = QMessageBox.question(
            self,
            tr("Kategorie wczytane"),
            tr(
                "Dodano kategorii: {v0}; reguł: {v1}; istniejących reguł: {v2}.\nIstniejące kategorie zostały zachowane i uzupełnione.\nCzy zastosować reguły do zapisanych transakcji?",
                v0=categories,
                v1=rules,
                v2=repeated,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            self.run_rules()

    def run_rules(self):
        if (
            self.include_manual.isChecked()
            and QMessageBox.question(
                self,
                tr("Ręczne kategorie"),
                tr("Zastąpić również ręczne kategorie pasującymi regułami?"),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            changed, conflicts = apply_rules(
                self.db,
                include_bank=self.include_bank.isChecked(),
                include_manual=self.include_manual.isChecked(),
            )
            self.notify_changed()
            QMessageBox.information(
                self,
                tr("Kategoryzacja"),
                tr(
                    "Zmieniono kategorii: {v0}. Konflikty do sprawdzenia: {v1}.",
                    v0=changed,
                    v1=conflicts,
                ),
            )
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
