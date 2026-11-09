"""Built-in fallback category invariants and bilingual icon discovery."""

import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from home_finance_cockpit.localization import language, set_language
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.category_workbench import CategoryManagerPage
from home_finance_cockpit.ui.editors import CategoryDialog
from home_finance_cockpit.ui.icon_picker import CategoryIconDialog, WalletIconDialog


class DefaultCategoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        previous = language()
        self.addCleanup(set_language, previous)
        set_language("pl")
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def test_default_exists_is_visible_and_protected_from_deletion(self):
        identifier = self.db.default_category_id()
        page = CategoryManagerPage(None, self.db)
        self.addCleanup(page.deleteLater)
        item = next(
            page.tree.topLevelItem(i)
            for i in range(page.tree.topLevelItemCount())
            if page.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == identifier
        )
        self.assertEqual(item.text(0), "Ogólne")
        page.tree.setCurrentItem(item)
        with (
            patch.object(QMessageBox, "question") as question,
            patch.object(QMessageBox, "information"),
        ):
            page.delete_category()
        question.assert_not_called()
        with self.assertRaises(ValueError):
            self.db.delete("categories", [identifier])
        with self.assertRaises(ValueError):
            self.db.delete_category_tree(identifier)
        self.assertEqual(self.db.default_category_id(), identifier)

    def test_default_translation_does_not_rename_user_categories_or_storage(self):
        identifier = self.db.default_category_id()
        user = self.db.save_category("Żywność")
        wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        self.db.save_transaction(
            wallet, "-10", identifier, "Unknown", "2026-01-01", source="unassigned"
        )
        for code, caption in (("en", "General"), ("pl", "Ogólne")):
            set_language(code)
            self.assertEqual(self.db.category(identifier)["display_name"], caption)
            self.assertEqual(self.db.category(user)["display_name"], "Żywność")
            self.assertEqual(self.db.transactions()[0]["category"], caption)
            page = CategoryManagerPage(None, self.db)
            self.addCleanup(page.deleteLater)
            captions = [
                page.tree.topLevelItem(i).text(0) for i in range(page.tree.topLevelItemCount())
            ]
            self.assertIn(caption, captions)
            self.assertIn("Żywność", captions)
        self.assertEqual(self.db.category(identifier)["name"], "Ogólne")

    def test_default_appearance_editable_but_name_and_parent_are_fixed(self):
        set_language("en")
        identifier = self.db.default_category_id()
        dialog = CategoryDialog(None, self.db, self.db.category(identifier))
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.name.text(), "General")
        self.assertTrue(dialog.name.isReadOnly())
        self.assertFalse(dialog.parent_category.isEnabled())
        self.assertFalse(dialog.icon_button.isHidden())
        self.assertFalse(dialog.color.isHidden())
        dialog.icon_name = "home"
        dialog.color.set_value("#22D3EE")
        dialog.persist()
        current = self.db.category(identifier)
        self.assertEqual(
            (current["name"], current["color"], current["icon_name"]), ("Ogólne", "#22D3EE", "home")
        )

    def test_icon_boxes_match_and_search_works_in_both_languages(self):
        for code in ("pl", "en"):
            set_language(code)
            dialog = CategoryIconDialog(None, "car", "#22D3EE")
            self.addCleanup(dialog.deleteLater)
            dialog.show()
            self.app.processEvents()
            self.assertEqual(len({b.width() for b in dialog.buttons.values()}), 1)
            for query, expected in (
                ("zywnosc", "food"),
                ("food", "food"),
                ("transport publiczny", "train"),
                ("public transport", "train"),
                ("shopping", "cart"),
            ):
                dialog.search.setText(query)
                self.assertFalse(dialog.buttons[expected].isHidden())
                self.assertTrue(dialog.buttons["home"].isHidden())
            self.assertEqual(dialog.selected_icon, "car")
            dialog.search.clear()
            self.assertTrue(all(not b.isHidden() for b in dialog.buttons.values()))
            dialog.close()
        wallet = WalletIconDialog(None)
        self.addCleanup(wallet.deleteLater)
        self.assertEqual(len({b.width() for b in wallet.buttons.values()}), 1)
