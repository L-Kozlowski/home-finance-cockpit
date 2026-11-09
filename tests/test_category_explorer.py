import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest import TestCase
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication, QWidget

from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.category_explorer import CategoryExplorer, category_series


class ExplorerTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        self.food = self.db.save_category("Food")
        child = self.db.save_category("Grocery", parent_id=self.food)
        self.ids = []
        for month, amount in ((9, "-1400"), (10, "-1450"), (11, "-1500")):
            self.ids.append(
                self.db.save_transaction(self.wallet, amount, child, "Shop", f"2026-{month:02d}-01")
            )
        self.db.save_transaction(self.wallet, "-100", self.food, "Unassigned child", "2026-11-02")
        self.data = spending_snapshot(self.db, "PLN", after_refunds=False)
        self.owner = QWidget()
        self.owner.open_rows = Mock()
        self.owner.chart_windows = []
        self.view = CategoryExplorer(self.owner)
        self.addCleanup(self.owner.deleteLater)
        self.view.refresh(self.data)

    def test_tree_matrix_trends_and_share_use_same_scoped_totals(self):
        self.assertEqual(self.view.tree.topLevelItemCount(), 1)
        self.assertEqual(self.view.tree.topLevelItem(0).childCount(), 2)
        self.assertEqual(self.view.matrix.item(0, 1).text(), "1 400.00")
        self.assertEqual(self.view.matrix.item(0, 4).text(), "4 350.00")
        self.assertEqual(self.view.matrix.item(0, 5).text(), "1 450.00")
        self.assertEqual(len(self.view.trend_canvases), 2)
        self.view.display.setCurrentIndex(1)
        self.assertEqual(self.view.matrix.item(0, 1).text(), "100.00%")
        self.assertEqual(self.view.matrix.item(0, 3).text(), "93.75%")
        self.view.transactions.click()
        self.assertEqual(len(self.owner.open_rows.call_args.args[0]), 4)

    def test_child_selection_and_month_cell_open_exact_transactions(self):
        item = self.view.tree.topLevelItem(0).child(0)
        self.view.tree.setCurrentItem(item)
        self.assertEqual(self.view.matrix.rowCount(), 2)
        self.view.open_cell_transactions(0, 2)
        self.owner.open_rows.assert_called_with([self.ids[1]])
        self.view.refresh(self.data)
        self.assertEqual(self.view.selection, (self.food, "Grocery"))
        self.assertEqual(self.view.trends.rowCount(), 1)

    def test_filter_and_empty_refresh_clear_stale_selection(self):
        filtered = spending_snapshot(self.db, "PLN", month="2026-10", after_refunds=False)
        self.view.refresh(filtered)
        self.assertEqual(category_series(filtered, self.food)[0], ["2026-10"])
        self.assertEqual(self.view.matrix.item(0, 2).text(), "1 450.00")
        self.view.refresh(None)
        self.assertEqual(self.view.matrix.rowCount(), 0)
        self.assertEqual(self.view.trends.rowCount(), 0)
        self.assertFalse(self.view.transactions.isEnabled())

    def test_matrix_delegate_paints_cells_with_explicit_foreground(self):
        from PyQt6.QtCore import QRect, Qt
        from PyQt6.QtGui import QPainter, QPixmap
        from PyQt6.QtWidgets import QStyleOptionViewItem

        matrix = self.view.matrix
        index = matrix.model().index(0, 1)
        self.assertIsNotNone(index.data(Qt.ItemDataRole.ForegroundRole))
        image = QPixmap(180, 36)
        image.fill(Qt.GlobalColor.transparent)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 180, 36)
        option.widget = matrix
        painter = QPainter(image)
        try:
            matrix.itemDelegate().paint(painter, option, index)
        finally:
            painter.end()
        self.assertEqual(image.toImage().pixelColor(0, 0).alpha(), 255)

    def test_open_categories_from_main_navigation_renders_matrix(self):
        import tempfile
        from pathlib import Path

        from PyQt6.QtCore import QSettings, Qt
        from PyQt6.QtTest import QTest

        from home_finance_cockpit.ui.main_window import FinanceApp

        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            window = FinanceApp(self.db, settings=settings)
            try:
                window.resize(1400, 900)
                window.show()
                QTest.mouseClick(window.workspace.nav_buttons[4], Qt.MouseButton.LeftButton)
                tabs = window.analyses.tabs
                QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(1).center())
                self.app.processEvents()
                category_views = window.analyses.category_views
                self.assertTrue(category_views.overview.isVisible())
                self.assertEqual(category_views.overview.tree.topLevelItemCount(), 1)
                category_views.tabs.setCurrentIndex(1)
                self.app.processEvents()
                explorer = window.analyses.category_explorer
                self.assertTrue(explorer.isVisible())
                self.assertGreater(explorer.matrix.rowCount(), 0)
                self.assertFalse(explorer.matrix.viewport().grab().isNull())
                explorer.display.setCurrentIndex(1)
                self.app.processEvents()
                self.assertFalse(explorer.matrix.viewport().grab().isNull())
                self.assertIn("%", explorer.matrix.item(0, 1).text())
            finally:
                window.close()
                window.deleteLater()

    def test_category_icon_edit_preview_and_graphics(self):
        from home_finance_cockpit.ui.editors import CategoryDialog
        from home_finance_cockpit.ui.icon_picker import CategoryIconDialog

        self.db.save_category("Food", self.food, color="#22D3EE", icon_name="food")
        dialog = CategoryDialog(None, self.db, self.db.category(self.food))
        try:
            self.assertEqual(dialog.icon_name, "food")
            self.assertFalse(dialog.icon_button.icon().isNull())
            dialog.icon_name = "cart"
            dialog.persist()
            self.assertEqual(self.db.category(self.food)["icon_name"], "cart")
            self.db.save_category("Food renamed", self.food)
            self.assertEqual(self.db.category(self.food)["icon_name"], "cart")
            with self.assertRaises(ValueError):
                self.db.save_category("Invalid", icon_name="unknown")
            picker = CategoryIconDialog(None, "food", "#22D3EE")
            picker.select("health")
            self.assertEqual(picker.selected_icon, "health")
            self.assertFalse(picker.preview.icon().isNull())
            picker.deleteLater()
        finally:
            dialog.deleteLater()
        self.view.refresh(spending_snapshot(self.db, "PLN", after_refunds=False))
        self.assertFalse(self.view.tree.topLevelItem(0).icon(0).isNull())
        self.assertFalse(self.view.tree.topLevelItem(0).child(0).icon(0).isNull())
        self.assertFalse(self.view.trends.item(0, 0).icon().isNull())
        canvas = self.view.trend_canvases[0]
        canvas.draw()
        self.assertEqual(canvas.figure.patch.get_alpha(), 0)
        self.assertEqual(canvas.figure.axes[0].patch.get_alpha(), 0)

    def test_v10_category_icons_migrate_and_persist(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "icons.db"
            db = Database.create_new(path)
            category = db.save_category("Example", color="#22D3EE")
            with db.transaction():
                db.execute("ALTER TABLE categories DROP COLUMN icon_name")
                db.execute("DROP TABLE IF EXISTS currency_history_requests")
                db.execute("DROP TABLE IF EXISTS currency_rate_history")
                db.execute("PRAGMA user_version=10")
            db.close()
            db = Database.open_existing(path)
            try:
                self.assertEqual(db.category(category)["icon_name"], "tag")
                db.save_category("Example", category, icon_name="food")
            finally:
                db.close()
            db = Database.open_existing(path)
            try:
                self.assertEqual(db.category(category)["icon_name"], "food")
                self.assertEqual(db.category(category)["color"], "#22D3EE")
                self.assertTrue(list((path.parent / "backups").glob("before_v12_*.db")))
            finally:
                db.close()
