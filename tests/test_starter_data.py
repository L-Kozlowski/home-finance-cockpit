"""Localized starter profiles, atomic initialization and startup language choice."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.application import ApplicationController
from home_finance_cockpit.localization import language, set_language
from home_finance_cockpit.services.categorization import classify
from home_finance_cockpit.services.starter_data import (
    DESCRIPTION_RULES,
    MERCHANT_RULES,
    STARTER_CATEGORIES,
    populate_starter_data,
)
from home_finance_cockpit.storage import Database
from tests.test_startup import StubWindow


class StarterDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        previous = language()
        self.addCleanup(set_language, previous)

    def test_profiles_include_appearance_rules_wallet_and_goal_in_each_language(self):
        for code, food_name, wallet_name, goal_name in (
            ("pl", "Żywność", "Portfel główny", "Poduszka finansowa (przykład)"),
            ("en", "Food", "Main wallet", "Emergency fund (example)"),
        ):
            set_language("en" if code == "pl" else "pl")
            db = Database.create_new(self.root / f"{code}.db", starter_language=code)
            try:
                food = db.find_category(food_name)
                self.assertEqual((food["color"], food["icon_name"]), ("#10B981", "food"))
                roots = [
                    c for c in db.categories() if c["parent_id"] is None and not c["is_default"]
                ]
                self.assertEqual(len(roots), len(STARTER_CATEGORIES))
                self.assertTrue(all(root["color"] and root["icon_name"] != "tag" for root in roots))
                self.assertTrue(
                    all(c["color"] is None for c in db.categories() if c["parent_id"] is not None)
                )
                expected_rules = (
                    sum(map(len, MERCHANT_RULES.values()))
                    + sum(map(len, DESCRIPTION_RULES.values()))
                    + 1
                    + (code == "pl")
                )
                self.assertEqual(len(db.rules()), expected_rules)
                self.assertEqual(len(db.wallets()), 1)
                self.assertEqual(
                    (db.wallets()[0]["name"], db.wallets()[0]["opening_minor"]), (wallet_name, 0)
                )
                self.assertEqual(len(db.savings_goals()), 1)
                goal = db.savings_goals()[0]
                self.assertEqual(goal["name"], goal_name)
                self.assertEqual(goal["target_minor"], 1000000)
                self.assertEqual(goal["wallet_id"], db.wallets()[0]["id"])
                self.assertEqual(goal["calculation_mode"], "wallet")
                self.assertFalse(db.transactions())
                self.assertFalse(db.import_history())
            finally:
                db.close()

    def test_rules_demonstrate_counterparty_matching_and_description_exclusion(self):
        for code, excluded in (("pl", "parówka"), ("en", "hot dog")):
            db = Database(":memory:")
            try:
                populate_starter_data(db, code)
                matched, conflict = classify(dict(from_to="MOL", description="Fuel"), db.rules())
                self.assertIsNotNone(matched)
                self.assertFalse(conflict)
                self.assertIsNone(
                    classify(dict(from_to="MOL", description=excluded), db.rules())[0]
                )
                grocery = classify(
                    dict(from_to="LIDL store", description="Card payment"), db.rules()
                )[0]
                self.assertIsNotNone(grocery)
                self.assertNotEqual(grocery["category_id"], matched["category_id"])
            finally:
                db.close()

    def test_reopening_and_reseeding_do_not_duplicate_or_rename_user_data(self):
        path = self.root / "profile.db"
        db = Database.create_new(path, starter_language="en")
        identifier = db.find_category("Food")["id"]
        db.save_category("My groceries", identifier)
        before = [dict(c) for c in db.categories()]
        self.assertFalse(populate_starter_data(db, "pl"))
        self.assertEqual([dict(c) for c in db.categories()], before)
        db.close()
        set_language("pl")
        reopened = Database.open_existing(path)
        try:
            self.assertIsNotNone(reopened.find_category("My groceries"))
            self.assertEqual(len(reopened.wallets()), 1)
            self.assertEqual(len(reopened.savings_goals()), 1)
        finally:
            reopened.close()

    def test_existing_empty_database_is_not_backfilled_and_failed_seed_rolls_back(self):
        path = self.root / "empty.db"
        Database.create_new(path).close()
        db = Database.open_existing(path)
        try:
            self.assertFalse(db.wallets())
            self.assertEqual(len(db.categories()), 1)
            with patch.object(db, "save_rule", side_effect=RuntimeError("Simulated failure")):
                with self.assertRaises(RuntimeError):
                    populate_starter_data(db, "en")
            self.assertEqual(len(db.categories()), 1)
            self.assertFalse(db.rules())
            self.assertFalse(db.savings_goals())
            self.assertFalse(db.wallets())
        finally:
            db.close()
        broken = self.root / "failed.db"
        with patch(
            "home_finance_cockpit.services.starter_data.populate_starter_data",
            side_effect=RuntimeError("Failed"),
        ):
            with self.assertRaises(RuntimeError):
                Database.create_new(broken, starter_language="en")
        self.assertFalse(broken.exists())


class StarterLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_launcher_switches_immediately_persists_and_seeds_selected_language(self):
        previous = language()
        self.addCleanup(set_language, previous)
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            controller = ApplicationController(
                self.app, settings=settings, window_factory=StubWindow
            )
            try:
                controller.launcher.language_combo.setCurrentIndex(1)
                self.assertEqual(language(), "en")
                self.assertEqual(controller.launcher.language_label.text(), "Language")
                self.assertIn("Create", controller.launcher.new_button.text())
                self.assertEqual(settings.value("general/language"), "en")
                controller._finish_open(Path(folder) / "new.db", create=True)
                self.assertIsNotNone(controller.window.db.find_category("Food"))
                self.assertEqual(controller.window.db.wallets()[0]["name"], "Main wallet")
                controller.launcher.set_busy(True)
                self.assertFalse(controller.launcher.language_combo.isEnabled())
                controller.launcher.set_busy(False)
                self.assertTrue(controller.launcher.language_combo.isEnabled())
                another = ApplicationController(
                    self.app, settings=settings, window_factory=StubWindow
                )
                try:
                    self.assertEqual(another.launcher.language_combo.currentData(), "en")
                finally:
                    another.launcher.close()
                    another.launcher.deleteLater()
            finally:
                if controller.window:
                    controller.window.close()
                    controller.window.deleteLater()
                controller.launcher.close()
                controller.launcher.deleteLater()

    def test_real_window_opens_new_profile_and_displays_categories_and_goal(self):
        previous = language()
        self.addCleanup(set_language, previous)
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("general/language", "en")
            controller = ApplicationController(self.app, settings=settings)
            try:
                with patch("home_finance_cockpit.application.QMessageBox.warning") as warning:
                    controller._finish_open(Path(folder) / "starter.db", create=True)
                warning.assert_not_called()
                self.assertIsNotNone(controller.window)
                for page in (0, 5, 7):
                    controller.window.tabs.setCurrentIndex(page)
                    self.app.processEvents()
                self.assertEqual(len(controller.window.db.wallets()), 1)
                self.assertEqual(len(controller.window.db.savings_goals()), 1)
                self.assertEqual(
                    len(controller.window.db.categories()),
                    1 + sum(1 + len(c[4]) for c in STARTER_CATEGORIES),
                )
                self.assertFalse(controller.window.db.transactions())
            finally:
                if controller.window:
                    controller.window.close()
                    controller.window.deleteLater()
                controller.launcher.close()
                controller.launcher.deleteLater()
