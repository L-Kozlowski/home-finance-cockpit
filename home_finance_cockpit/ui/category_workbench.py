"""Three-column category navigation and compound-rule editing workspace."""

import sqlite3

from PyQt6.QtCore import QRect, QSignalBlocker, QSize, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionComboBox,
    QStylePainter,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.categories import (
    RULE_MODES,
    category_name,
    column_label,
    describe_rule,
    rule_conditions,
)
from home_finance_cockpit.localization import quote_text, tr
from home_finance_cockpit.reports.presentation import category_color
from home_finance_cockpit.services.search import normalize
from home_finance_cockpit.ui.category_actions import CategoryManagerBase
from home_finance_cockpit.ui.category_explorer import CategoryTree, dot
from home_finance_cockpit.ui.common import show_error
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.editors import CategoryDialog
from home_finance_cockpit.ui.theme import INK, display_color


class AssignmentDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(58, size.height()))
        return size


class AssignmentCombo(QComboBox):
    """Keep the parent icon and hierarchy visible even when the popup is closed."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(72)
        self.setItemDelegate(AssignmentDelegate(self))
        self.setIconSize(QSize(28, 28))

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        option.currentIcon = icon("tag")
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        area = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, self
        )
        self.itemIcon(self.currentIndex()).paint(
            painter, QRect(area.left() + 10, area.center().y() - 14, 28, 28)
        )
        text_area = area.adjusted(50, 0, -8, 0)
        parts = self.currentText().split("\n", 1)
        painter.setPen(self.palette().text().color())
        if len(parts) == 1:
            painter.drawText(text_area, Qt.AlignmentFlag.AlignVCenter, parts[0])
        else:
            upper = QRect(
                text_area.left(),
                text_area.top() + 8,
                text_area.width(),
                text_area.height() // 2 - 4,
            )
            painter.drawText(upper, Qt.AlignmentFlag.AlignVCenter, parts[0])
            painter.setPen(QColor(display_color("#A8BED5")))
            painter.drawText(
                text_area.adjusted(0, text_area.height() // 2, 0, -6),
                Qt.AlignmentFlag.AlignVCenter,
                parts[1],
            )


class RuleEditor(QWidget):
    def __init__(self, db, parent=None, record=None, category_id=None):
        super().__init__(parent)
        self.db = db
        self.record = record
        self.conditions = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label(tr("Przypisz do"), "section"))
        self.category = AssignmentCombo()
        self.category.setMinimumContentsLength(12)
        self.category.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        categories = {c["id"]: c for c in db.categories()}
        for c in categories.values():
            if c["is_default"]:
                continue
            root = categories.get(c["parent_id"], c)
            tint = category_color(root["name"], {root["name"]: root["color"]})
            caption = root["name"] + "\n" + c["name"] if c["parent_id"] else c["name"]
            self.category.addItem(icon(root["icon_name"], tint), caption, c["id"])
        identifier = record["category_id"] if record else category_id
        self.category.setCurrentIndex(max(0, self.category.findData(identifier)))
        self.category.currentIndexChanged.connect(self.update_preview)
        layout.addWidget(self.category)
        layout.addWidget(label(tr("Warunki"), "section"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.content = QWidget()
        self.condition_layout = QVBoxLayout(self.content)
        self.condition_layout.setContentsMargins(0, 0, 0, 0)
        self.condition_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll)
        self.add_button = QPushButton(tr("Dodaj warunek"))
        self.add_button.setIcon(icon("plus"))
        self.add_button.clicked.connect(lambda: self.add_condition())
        layout.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(label(tr("Podgląd warunku"), "section"))
        self.preview = label("")
        self.preview.setWordWrap(True)
        preview_panel, box = panel()
        box.addWidget(self.preview)
        layout.addWidget(preview_panel)
        layout.addStretch(1)
        self.note = label("")
        layout.addWidget(self.note)
        for condition in (
            rule_conditions(record)
            if record
            else [dict(column_name="description", mode="literal", pattern="")]
        ):
            self.add_condition(condition)
        self.baseline = self.state()
        self.update_preview()
        background = display_color("#0B1623")
        border = display_color("#24394D")
        self.setStyleSheet(
            "QLineEdit,QComboBox {background:"
            + background
            + "; border:1px solid "
            + border
            + "; border-radius:5px; padding:7px;} QScrollArea,QScrollArea > QWidget > QWidget {background:transparent;}"
        )

    def add_condition(self, condition=None):
        if len(self.conditions) >= 12:
            return
        condition = condition or dict(column_name="description", mode="not_contains", pattern="")
        card, box = panel()
        grid = QGridLayout()
        box.addLayout(grid)
        column = QComboBox()
        operator = QComboBox()
        pattern = QLineEdit(condition["pattern"])
        pattern.setClearButtonEnabled(True)
        for key in self.db.rule_columns():
            column.addItem(column_label(key), key)
        if column.findData(condition["column_name"]) < 0:
            column.setPlaceholderText(tr("Wybierz pole aplikacji"))
        for key, caption in RULE_MODES.items():
            operator.addItem(tr(caption), key)
        column.setCurrentIndex(column.findData(condition["column_name"]))
        operator.setCurrentIndex(operator.findData(condition["mode"]))
        for widget in (column, operator):
            widget.setMinimumContentsLength(6)
            widget.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
        for col, (caption, field) in enumerate(
            ((tr("Pole"), column), (tr("Dopasowanie"), operator), (tr("Słowo kluczowe"), pattern))
        ):
            grid.addWidget(label(caption), 0, col)
            grid.addWidget(field, 1, col)
            grid.setColumnStretch(col, 1)
        remove = QPushButton()
        remove.setIcon(icon("trash"))
        remove.setFixedWidth(28)
        grid.addWidget(remove, 1, 3)
        join = label(tr("ORAZ"))
        join.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.condition_layout.addWidget(join)
        self.condition_layout.addWidget(card)
        entry = (card, column, operator, pattern, join, remove)
        self.conditions.append(entry)
        remove.clicked.connect(lambda: self.remove_condition(entry))
        column.currentIndexChanged.connect(self.update_preview)
        operator.currentIndexChanged.connect(self.update_preview)
        pattern.textChanged.connect(self.update_preview)
        self.update_preview()
        QTimer.singleShot(0, self.update_preview)

    def remove_condition(self, entry):
        if len(self.conditions) <= 1:
            return
        self.conditions.remove(entry)
        for widget in (entry[0], entry[4]):
            self.condition_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self.update_preview()

    def state(self):
        return self.category.currentData(), [
            (c.currentData(), m.currentData(), p.text()) for _, c, m, p, _, _ in self.conditions
        ]

    def dirty(self):
        return self.state() != self.baseline

    def update_preview(self, *_):
        if not hasattr(self, "preview"):
            return
        texts = []
        for index, (_, column, operator, pattern, join, remove) in enumerate(self.conditions):
            join.setVisible(index > 0)
            remove.setEnabled(len(self.conditions) > 1)
            texts.append(
                f"{column_label(column.currentData())} {tr(RULE_MODES[operator.currentData()]).lower()} {quote_text(pattern.text())}"
            )
        self.preview.setText((" " + tr("ORAZ") + " ").join(texts))
        self.add_button.setEnabled(len(self.conditions) < 12)
        height = sum(
            card.sizeHint().height() + (join.sizeHint().height() + 12 if index else 0) + 12
            for index, (card, _, _, _, join, _) in enumerate(self.conditions)
        )
        self.scroll.setFixedHeight(min(520, max(120, height)))

    def persist(self):
        identifier, conditions = self.state()
        if identifier is None:
            raise ValueError(tr("Najpierw dodaj kategorię inną niż domyślna."))
        first = conditions[0]
        return self.db.save_rule(
            identifier,
            first[0],
            first[2],
            first[1],
            self.record["id"] if self.record else None,
            conditions=[dict(column_name=c, mode=m, pattern=p) for c, m, p in conditions[1:]],
        )


class CategoryManagerPage(CategoryManagerBase):
    def __init__(self, parent, db):
        QWidget.__init__(self, parent)
        self.db = db
        self.editor = None
        self.selected_rule_id = None
        self.new_rule_pending = False
        self.require_rule_selection = False
        self.loading = False
        self._category_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar = QHBoxLayout()
        self.toolbar.addStretch()
        self.import_button = QPushButton(tr("Importuj JSON"))
        self.import_button.setIcon(icon("import"))
        self.import_button.clicked.connect(self.import_json)
        self.apply_button = QPushButton(tr("Zastosuj reguły"))
        self.apply_button.setIcon(icon("play", INK))
        self.apply_button.setProperty("themeIcon", "play")
        self.apply_button.setProperty("role", "primary")
        self.apply_button.clicked.connect(self.show_apply_options)
        self.export_button = QPushButton(tr("Eksportuj JSON"))
        self.export_button.setIcon(icon("upload"))
        self.export_button.clicked.connect(self.export_json)
        self.toolbar.addWidget(self.export_button)
        self.toolbar.addWidget(self.import_button)
        self.toolbar.addWidget(self.apply_button)
        layout.addLayout(self.toolbar)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        left, box = panel()
        head = QHBoxLayout()
        head.addWidget(label(tr("Kategorie"), "section"), 1)
        add = QPushButton()
        add.setIcon(icon("plus"))
        add.setFixedWidth(32)
        add.clicked.connect(self.category_add_menu)
        head.addWidget(add)
        box.addLayout(head)
        self.category_search = QLineEdit()
        self.category_search.setPlaceholderText(tr("Szukaj kategorii…"))
        self.category_search.setClearButtonEnabled(True)
        self.category_search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.category_search.textChanged.connect(self.filter_categories)
        box.addWidget(self.category_search)
        self.tree = CategoryTree()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.edit_controls = True
        self.tree.edit_requested.connect(self.edit_tree_category)
        self.tree.add_requested.connect(self.add_tree_child)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 125)
        self.tree.itemSelectionChanged.connect(self.category_changed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.category_menu)
        box.addWidget(self.tree, 1)
        all_rules = QPushButton(tr("Pokaż wszystkie reguły"))
        all_rules.clicked.connect(self.clear_category)
        box.addWidget(all_rules)
        self.splitter.addWidget(left)
        middle, box = panel()
        head = QHBoxLayout()
        self.rules_title = label(tr("Reguły"), "section")
        head.addWidget(self.rules_title, 1)
        add_rule = QPushButton(tr("Nowa reguła"))
        add_rule.setIcon(icon("plus", INK))
        add_rule.setProperty("themeIcon", "plus")
        add_rule.setProperty("role", "primary")
        add_rule.setStyleSheet("QPushButton {padding:8px 14px;}")
        add_rule.clicked.connect(self.add_rule)
        head.addWidget(add_rule)
        box.addLayout(head)
        self.assignment_chip = QWidget()
        chip = QHBoxLayout(self.assignment_chip)
        chip.setContentsMargins(12, 7, 12, 7)
        chip.setSpacing(10)
        self.assignment_icon = label("")
        self.assignment = label("")
        self.assignment.setWordWrap(False)
        chip.addWidget(self.assignment_icon)
        chip.addWidget(self.assignment)
        self.clear_category_button = QPushButton()
        self.clear_category_button.setIcon(icon("close"))
        self.clear_category_button.setFixedSize(24, 24)
        self.clear_category_button.setStyleSheet(
            "QPushButton {padding:0;min-width:0;min-height:0;}"
        )
        self.clear_category_button.setToolTip(tr("Pokaż wszystkie reguły"))
        self.clear_category_button.clicked.connect(self.clear_category)
        chip.addWidget(self.clear_category_button)
        self.assignment_chip.setStyleSheet(
            "background:" + display_color("#1E3347") + "; border-radius:12px;"
        )
        box.addWidget(self.assignment_chip, 0, Qt.AlignmentFlag.AlignLeft)
        self.rule_search = QLineEdit()
        self.rule_search.setPlaceholderText(tr("Szukaj reguł…"))
        self.rule_search.setClearButtonEnabled(True)
        self.rule_search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.rule_search.textChanged.connect(self.refresh_rules)
        box.addWidget(self.rule_search)
        self.rule_list = QListWidget()
        self.rule_list.setSpacing(5)
        self.rule_list.setStyleSheet(
            "QListWidget {background:transparent; border:0;} QListWidget::item {border:1px solid #24394D; border-radius:6px;} QListWidget::item:selected {background:#153B4D; border-color:#22D3EE;}"
        )
        self.rule_list.currentItemChanged.connect(self.rule_selected)
        box.addWidget(self.rule_list, 1)
        self.splitter.addWidget(middle)
        right, box = panel()
        self.editor_title = label(tr("Edytuj regułę"), "section")
        box.addWidget(self.editor_title)
        self.editor_host = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_host)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.editor_host, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(tr("Anuluj"))
        cancel.clicked.connect(self.cancel_rule)
        save = QPushButton(tr("Zapisz regułę"))
        save.setProperty("role", "primary")
        save.clicked.connect(self.save_rule)
        self.save_rule_button, self.cancel_rule_button = save, cancel
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        box.addLayout(buttons)
        self.splitter.addWidget(right)
        self.splitter.setSizes([280, 390, 480])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        self.status = label("")
        self.status.hide()
        self.apply_dialog = QDialog(self, Qt.WindowType.Popup)
        self.apply_dialog.setWindowTitle(tr("Zastosuj reguły"))
        popup = QVBoxLayout(self.apply_dialog)
        popup.addWidget(label(tr("Przypisz kategorie do transakcji"), "section"))
        self.include_bank = QCheckBox(tr("Zastępuj kategorie z CSV, gdy pasuje reguła"))
        self.include_bank.setChecked(True)
        self.include_manual = QCheckBox(tr("Zastępuj ręczne kategorie (po potwierdzeniu)"))
        popup.addWidget(self.include_bank)
        popup.addWidget(self.include_manual)
        actions = QHBoxLayout()
        dismiss = QPushButton(tr("Anuluj"))
        dismiss.clicked.connect(self.apply_dialog.hide)
        apply = QPushButton(tr("Zastosuj reguły"))
        apply.setProperty("role", "primary")
        apply.clicked.connect(self.apply_from_popup)
        actions.addWidget(dismiss)
        actions.addWidget(apply)
        popup.addLayout(actions)
        self.refresh()

    def guard_pending(self):
        if self.editor is None or not self.editor.dirty():
            return True
        result = QMessageBox.question(
            self,
            tr("Niezapisane zmiany"),
            tr("Zapisać zmiany reguły przed przejściem dalej?"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            return self.save_rule()
        self.cancel_rule()
        return True

    def refresh(self):
        selected = self.selected_category() if self.tree.selectedItems() else None
        identifier = selected["id"] if selected else None
        categories = self.db.categories()
        rules = self.db.rules()
        counts = {c["id"]: sum(r["category_id"] == c["id"] for r in rules) for c in categories}
        expanded = {
            self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(self.tree.topLevelItemCount())
            if self.tree.topLevelItem(i).isExpanded()
        }
        with QSignalBlocker(self.tree):
            self.tree.clear()
            nodes = {}
            for c in categories:
                root = next((r for r in categories if r["id"] == c["parent_id"]), c)
                tint = category_color(root["name"], {root["name"]: root["color"]})
                count = counts[c["id"]] + sum(
                    counts[x["id"]] for x in categories if x["parent_id"] == c["id"]
                )
                item = QTreeWidgetItem([category_name(c), str(count)])
                item.setData(0, Qt.ItemDataRole.UserRole, c["id"])
                item.setData(0, Qt.ItemDataRole.UserRole + 1, bool(c["is_default"]))
                item.setSizeHint(0, QSize(0, 42 if c["parent_id"] is None else 34))
                item.setIcon(
                    0, dot(tint) if c["parent_id"] is not None else icon(c["icon_name"], tint)
                )
                nodes[c["id"]] = item
            for c in categories:
                item = nodes[c["id"]]
                if c["parent_id"] is None:
                    self.tree.addTopLevelItem(item)
                    item.setExpanded(c["id"] in expanded or not expanded)
                else:
                    nodes[c["parent_id"]].addChild(item)
            if identifier in nodes:
                self.tree.setCurrentItem(nodes[identifier])
        self.filter_categories()
        self.refresh_rules()

    def filter_categories(self, *_):
        terms = normalize(self.category_search.text()).split()
        for index in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(index)
            matches_root = all(t in normalize(root.text(0)) for t in terms)
            visible = matches_root
            for child in [root.child(i) for i in range(root.childCount())]:
                child_match = matches_root or all(t in normalize(child.text(0)) for t in terms)
                child.setHidden(not child_match)
                visible |= child_match
            root.setHidden(not visible)
            if terms and visible:
                root.setExpanded(True)

    def category_changed(self):
        if self.loading:
            return
        if not self.guard_pending():
            identifier = self._category_id
            with QSignalBlocker(self.tree):
                self.tree.clearSelection()
                iterator = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
                for root in iterator:
                    for item in [root] + [root.child(i) for i in range(root.childCount())]:
                        if item.data(0, Qt.ItemDataRole.UserRole) == identifier:
                            self.tree.setCurrentItem(item)
            return
        selected = self.selected_category()
        self._category_id = selected["id"] if selected else None
        self.new_rule_pending = False
        self.selected_rule_id = None
        self.load_rule(None)
        self.refresh_rules()

    def selected_category(self):
        selection = self.tree.selectedItems()
        if not selection:
            return None
        try:
            return self.db.category(selection[0].data(0, Qt.ItemDataRole.UserRole))
        except ValueError:
            return None

    def edit_tree_category(self, item):
        if not self.guard_pending():
            return
        self.tree.setCurrentItem(item)
        self.edit_category()

    def add_tree_child(self, item):
        if not self.guard_pending():
            return
        category = self.db.category(item.data(0, Qt.ItemDataRole.UserRole))
        if (
            not category["is_default"]
            and CategoryDialog(self, self.db, parent_id=category["id"]).exec()
        ):
            self.notify_changed()

    def refresh_rules(self, *_):
        selected = self.selected_category()
        allowed = (
            None
            if selected is None
            else {selected["id"]}
            | {c["id"] for c in self.db.categories() if c["parent_id"] == selected["id"]}
        )
        terms = normalize(self.rule_search.text()).split()
        self.records = [
            r
            for r in reversed(self.db.rules())
            if (allowed is None or r["category_id"] in allowed)
            and all(t in normalize(describe_rule(r)) for t in terms)
        ]
        self.rules_title.setText(
            (category_name(selected) + " · " if selected else "") + tr("Reguły")
        )
        self.assignment.setText(selected["display_name"] if selected else tr("Wszystkie kategorie"))
        self.clear_category_button.setVisible(selected is not None)
        root = (
            self.db.category(selected["parent_id"])
            if selected and selected["parent_id"]
            else selected
        )
        tint = (
            category_color(root["name"], {root["name"]: root["color"]})
            if root
            else display_color("#22D3EE")
        )
        self.assignment_icon.setPixmap(
            icon(root["icon_name"] if root else "tag", tint).pixmap(24, 24)
        )
        with QSignalBlocker(self.rule_list):
            self.rule_list.clear()
            selection = None
            if self.new_rule_pending:
                draft = QListWidgetItem(tr("Nowa reguła"))
                draft.setData(Qt.ItemDataRole.UserRole, None)
                draft.setSizeHint(QSize(200, 48))
                self.rule_list.addItem(draft)
                draft_card = QWidget()
                draft_layout = QHBoxLayout(draft_card)
                draft_layout.setContentsMargins(12, 8, 12, 8)
                draft_layout.addWidget(label(tr("Nowa reguła")))
                draft.setText("")
                self.rule_list.setItemWidget(draft, draft_card)
                selection = draft
            usage = {
                row[0]: row[1]
                for row in self.db.execute(
                    "SELECT matched_rule_id,COUNT(*) FROM transactions WHERE matched_rule_id IS NOT NULL AND category_source='rule' GROUP BY matched_rule_id"
                )
            }
            for rule in self.records:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, rule["id"])
                item.setSizeHint(QSize(200, max(48, 22 + 20 * len(rule_conditions(rule)))))
                self.rule_list.addItem(item)
                card = QWidget()
                content = QHBoxLayout(card)
                content.setContentsMargins(10, 4, 8, 4)
                content.setSpacing(5)
                description = label(
                    ("\n" + tr("ORAZ") + " ").join(
                        f"{column_label(c['column_name'])} {tr(RULE_MODES[c['mode']]).lower()} {quote_text(c['pattern'])}"
                        for c in rule_conditions(rule)
                    )
                )
                content.addWidget(description, 1)
                description.clicked.connect(
                    lambda identifier=rule["id"]: self.choose_rule(identifier)
                )
                count = usage.get(rule["id"], 0)
                counter = label("+999" if count > 1000 else str(count))
                counter.setObjectName("ruleUsageCount")
                counter.clicked.connect(lambda identifier=rule["id"]: self.choose_rule(identifier))
                counter.setToolTip(
                    tr("Transakcje przypisane przez tę regułę: {count}", count=count)
                )
                content.addWidget(counter)
                edit = QPushButton()
                edit.setIcon(icon("edit"))
                edit.setFixedWidth(28)
                edit.setIconSize(QSize(16, 16))
                edit.setStyleSheet("QPushButton {padding:2px;min-width:0;}")
                edit.clicked.connect(
                    lambda checked=False, identifier=rule["id"]: self.choose_rule(identifier)
                )
                content.addWidget(edit)
                remove = QPushButton()
                remove.setIcon(icon("trash"))
                remove.setFixedWidth(26)
                remove.setIconSize(QSize(16, 16))
                remove.setStyleSheet("QPushButton {padding:2px;min-width:0;}")
                remove.setToolTip(tr("Usuń regułę"))
                remove.clicked.connect(
                    lambda checked=False, identifier=rule["id"]: self.delete_rule_by_id(identifier)
                )
                content.addWidget(remove)
                self.rule_list.setItemWidget(item, card)
                if rule["id"] == self.selected_rule_id:
                    selection = item
            if selection:
                self.rule_list.setCurrentItem(selection)
        if not self.new_rule_pending and (self.editor is None or not self.editor.dirty()):
            record = next((r for r in self.records if r["id"] == self.selected_rule_id), None)
            if record is None and self.records and not self.require_rule_selection:
                record = self.records[0]
                self.selected_rule_id = record["id"]
            if record is None and self.require_rule_selection:
                self.selected_rule_id = None
                self.show_empty_rule_editor()
            else:
                self.load_rule(record)
            if record:
                with QSignalBlocker(self.rule_list):
                    for i in range(self.rule_list.count()):
                        if self.rule_list.item(i).data(Qt.ItemDataRole.UserRole) == record["id"]:
                            self.rule_list.setCurrentRow(i)

    def load_rule(self, record):
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        selected = self.selected_category()
        self.editor = RuleEditor(
            self.db,
            self.editor_host,
            record,
            selected["id"] if selected and not selected["is_default"] else None,
        )
        self.editor_layout.addWidget(self.editor)
        self.save_rule_button.setEnabled(True)
        self.cancel_rule_button.setEnabled(True)
        self.editor_title.setText(tr("Edytuj regułę") if record else tr("Nowa reguła"))

    def show_empty_rule_editor(self):
        while self.editor_layout.count():
            widget = self.editor_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        self.editor = None
        self.editor_title.setText(tr("Wybierz regułę z listy"))
        self.save_rule_button.setEnabled(False)
        self.cancel_rule_button.setEnabled(False)

    def rule_selected(self, item, previous):
        if item:
            self.choose_rule(item.data(Qt.ItemDataRole.UserRole), previous)

    def choose_rule(self, identifier, previous=None):
        if identifier == self.selected_rule_id:
            return
        if not self.guard_pending():
            with QSignalBlocker(self.rule_list):
                for i in range(self.rule_list.count()):
                    if (
                        self.rule_list.item(i).data(Qt.ItemDataRole.UserRole)
                        == self.selected_rule_id
                    ):
                        self.rule_list.setCurrentRow(i)
            return
        self.selected_rule_id = identifier
        if self.new_rule_pending:
            self.new_rule_pending = False
            if (
                self.rule_list.count()
                and self.rule_list.item(0).data(Qt.ItemDataRole.UserRole) is None
            ):
                with QSignalBlocker(self.rule_list):
                    self.rule_list.takeItem(0)
        record = next((r for r in self.db.rules() if r["id"] == identifier), None)
        self.load_rule(record)
        with QSignalBlocker(self.rule_list):
            for i in range(self.rule_list.count()):
                if self.rule_list.item(i).data(Qt.ItemDataRole.UserRole) == identifier:
                    self.rule_list.setCurrentRow(i)

    def add_rule(self):
        if not self.guard_pending():
            return
        self.selected_rule_id = None
        self.new_rule_pending = True
        with QSignalBlocker(self.rule_search):
            self.rule_search.clear()
        with QSignalBlocker(self.rule_list):
            self.rule_list.clearSelection()
        self.load_rule(None)
        self.refresh_rules()
        self.rule_list.scrollToTop()

    def save_rule(self):
        if self.editor is None:
            return False
        was_new = self.new_rule_pending
        try:
            self.selected_rule_id = self.editor.persist()
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            return False
        self.editor.baseline = self.editor.state()
        self.new_rule_pending = False
        if was_new:
            selected = self.selected_category()
            target = self.db.category(self.editor.category.currentData())
            if selected and selected["id"] not in (target["id"], target["parent_id"]):
                with QSignalBlocker(self.tree):
                    self.tree.clearSelection()
                self._category_id = None
        self.notify_changed()
        return True

    def cancel_rule(self):
        pending = self.new_rule_pending
        self.new_rule_pending = False
        record = next((r for r in self.db.rules() if r["id"] == self.selected_rule_id), None)
        self.load_rule(record)
        if pending:
            self.refresh_rules()

    def clear_category(self):
        if not self.guard_pending():
            return
        self.require_rule_selection = True
        self.new_rule_pending = False
        self.selected_rule_id = None
        self._category_id = None
        with QSignalBlocker(self.tree):
            self.tree.clearSelection()
            self.tree.setCurrentItem(None)
        self.refresh_rules()

    def category_add_menu(self):
        menu = QMenu(self)
        menu.addAction(tr("+ Kategoria"), self.add_root)
        menu.addAction(tr("+ Podkategoria"), self.add_child)
        button = self.sender()
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def category_menu(self, point):
        item = self.tree.itemAt(point)
        if not item:
            return
        self.open_category_menu(item, self.tree.viewport().mapToGlobal(point))

    def open_category_menu(self, item, position):
        self.tree.setCurrentItem(item)
        selected = self.selected_category()
        if not selected or selected["id"] != item.data(0, Qt.ItemDataRole.UserRole):
            return
        menu = QMenu(self)
        menu.addAction(tr("+ Podkategoria"), self.add_child)
        menu.addAction(tr("Edytuj kategorię"), self.edit_category)
        menu.addSeparator()
        menu.addAction(tr("Usuń kategorię"), self.delete_category).setEnabled(
            not selected["is_default"]
        )
        menu.exec(position)

    def delete_rule_by_id(self, identifier):
        if not self.guard_pending():
            return
        if (
            QMessageBox.question(self, tr("Usuń reguły"), tr("Usunąć {v0} reguł?", v0=1))
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.db.delete("rules", [identifier])
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            return
        self.selected_rule_id = None
        self.notify_changed()

    def show_apply_options(self):
        if not self.guard_pending():
            return
        self.apply_dialog.adjustSize()
        position = self.apply_button.mapToGlobal(self.apply_button.rect().bottomRight())
        position.setX(position.x() - self.apply_dialog.width())
        self.apply_dialog.move(position)
        self.apply_dialog.show()

    def apply_from_popup(self):
        self.apply_dialog.hide()
        self.run_rules()

    def run_rules(self):
        if self.guard_pending():
            super().run_rules()
