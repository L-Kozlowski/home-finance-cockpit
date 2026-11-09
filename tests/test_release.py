"""Installed releases keep mutable files separate and expose authorship in both languages."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QLabel

from home_finance_cockpit.identity import APP_AUTHOR, APP_RELEASE
from home_finance_cockpit.localization import set_language
from home_finance_cockpit.paths import data_directory, reports_directory
from home_finance_cockpit.ui.about import AboutPage


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("pl")

    def test_frozen_paths_are_per_user_and_outside_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": folder}, clear=True),
                patch("sys.frozen", True, create=True),
                patch("sys.platform", "win32"),
            ):
                self.assertEqual(data_directory(), Path(folder) / "HomeFinanceCockpit")
                self.assertEqual(reports_directory(), data_directory() / "reports")

    def test_staging_archives_obsolete_packages_without_changing_current_source(self):
        import sys

        with patch.object(
            sys, "path", [str(Path(__file__).resolve().parents[1] / "tools"), *sys.path]
        ):
            from tools import stage_release
        with tempfile.TemporaryDirectory() as folder:
            release = Path(folder)
            source = release / "source"
            for package in ("home_finance_cockpit", "previous_package"):
                path = source / package
                path.mkdir(parents=True)
                (path / "__init__.py").write_text("# English source comment\n", encoding="utf-8")
            with (
                patch.object(stage_release, "SOURCE", source),
                patch.object(stage_release, "RELEASE", release),
            ):
                archived = stage_release.archive_unlisted_packages()
            self.assertEqual(len(archived), 1)
            self.assertFalse((source / "previous_package").exists())
            self.assertTrue((source / "home_finance_cockpit/__init__.py").is_file())
            self.assertEqual(
                (archived[0] / "__init__.py").read_text(encoding="utf-8"),
                "# English source comment\n",
            )

    def test_profile_override_is_explicit_and_does_not_use_current_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"HFC_DATA_DIR": folder}):
                self.assertEqual(data_directory(), Path(folder).resolve())

    def test_about_shows_release_author_and_localized_labels(self):
        for code, prefix in (("pl", "Autor: "), ("en", "Author: ")):
            set_language(code)
            page = AboutPage()
            try:
                captions = [widget.text() for widget in page.findChildren(QLabel)]
                self.assertIn(prefix + APP_AUTHOR, captions)
                self.assertIn(APP_RELEASE, captions)
                self.assertTrue(any("GPL-3.0-only" in text for text in captions))
            finally:
                page.deleteLater()

    def test_staging_ignores_private_example_materials_and_keeps_demo(self):
        import sys

        with patch.object(
            sys, "path", [str(Path(__file__).resolve().parents[1] / "tools"), *sys.path]
        ):
            from tools import stage_release
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(stage_release, "ROOT", root):
                ignored = stage_release.ignored(
                    str(root / "example"),
                    ["source", "backups", "logs", "settings.ini", "demo_setup.xlsx"],
                )
                self.assertEqual(ignored, {"source", "backups", "logs", "settings.ini"})
                ignored = stage_release.ignored(
                    str(root / "example/database"),
                    ["home_finance_demo.db", "private.db", "private.db-wal"],
                )
                self.assertEqual(ignored, {"private.db", "private.db-wal"})
