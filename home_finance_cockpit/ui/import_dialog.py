"""Import preview, validation details and explicit duplicate review."""

import csv
import sqlite3
from html import escape
from pathlib import Path

from PyQt6.QtCore import QEvent, QSignalBlocker, QSize, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMessageBox,
    QTableWidgetItem,
    QToolTip,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.import_files import (
    SUPPORTED_FILES,
    commit_import_batch,
    prepare_import_batch,
    read_import_file,
)
from home_finance_cockpit.services.importing import (
    suggested_mapping,
)
from home_finance_cockpit.ui.branding import application_icon
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.common import fill_table
from home_finance_cockpit.ui.components import icon
from home_finance_cockpit.ui.editors import select_data
from home_finance_cockpit.ui.import_workspace import (
    ImportFileCard,
    apply_workspace_style,
    build_workspace,
    step_marker,
)
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import MUTED, RED, SUCCESS, WARNING, display_color


class ImportDialog(QDialog):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.db, self.file, self.plan = db, None, None
        self.files, self.plans, self.paths = [], [], []
        self.loaded_paths, self.file_cards = [], []
        self.excluded_rows, self.load_errors = {}, []
        self.raw_offset, self._loading, self._validating = 0, False, False
        self.current_step = 0
        self.source_accepted = self.mapping_accepted = False
        self.raw_column_widths, self.mapped_column_widths = {}, {}
        self.setAcceptDrops(True)
        self.setWindowTitle(tr("Import transakcji CSV / Excel"))
        self.setWindowIcon(application_icon())
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(420, 300)
        screen = parent.screen() if parent else self.screen()
        available = screen.availableGeometry()
        self.resize(min(px(1450), available.width() - 40), min(px(960), available.height() - 50))
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(350)
        self.preview_timer.timeout.connect(lambda: self.validate())
        self.column_fit_timer = QTimer(self)
        self.column_fit_timer.setSingleShot(True)
        self.column_fit_timer.timeout.connect(lambda: self.fit_preview_columns(self.preview))
        build_workspace(self, db)
        self.raw_preview.horizontalHeader().sectionResized.connect(
            lambda column, old, width: self.remember_column_width(column, width, self.raw_preview)
        )
        self.mapping_source_preview.horizontalHeader().sectionResized.connect(
            lambda column, old, width: self.remember_column_width(
                column, width, self.mapping_source_preview
            )
        )
        self.preview.horizontalHeader().sectionResized.connect(
            lambda column, old, width: self.remember_column_width(column, width, self.preview)
        )
        self.details.textChanged.connect(self.update_notices)
        self.wallet.currentIndexChanged.connect(self.invalidate)
        self.encoding.currentIndexChanged.connect(self.options_changed)
        self.delimiter.currentIndexChanged.connect(self.options_changed)
        self.header_row.valueChanged.connect(self.header_row_changed)
        self.header_mode.currentIndexChanged.connect(self.header_mode_changed)
        self.sheet_name.editingFinished.connect(self.options_changed)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)
        for viewport in (
            self.content_scroll.viewport(),
            self.preview.viewport(),
            self.raw_preview.viewport(),
            self.details.viewport(),
            self.file_scroll.viewport(),
            self.source_scroll.viewport(),
            self.mapping_source_preview.viewport(),
        ):
            viewport.setAcceptDrops(True)
        self.update_summary()
        self.set_step(0)

    def invalidate(self, *_):
        self.preview_timer.stop()
        if not self._validating:
            self.mapping_accepted = False
            if self.current_step == 0:
                self.source_accepted = False
            with QSignalBlocker(self.review_confirmation):
                self.review_confirmation.setChecked(False)
            if self.current_step == 2:
                self.set_step(1)
        self.plan = None
        self.plans = []
        self.save_button.setEnabled(False)
        if hasattr(self, "preview"):
            self.preview.setRowCount(0)
            self.update_summary()
        if self.files and self.current_step == 1 and not self._loading and not self._validating:
            self.preview_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "source_layout"):
            self.update_import_density()

    def update_import_density(self):
        compact = self.height() < px(850)
        if self.property("compactImport") == compact:
            return
        self.setProperty("compactImport", compact)
        self.source_layout.setSpacing(px(3 if compact else 7))
        self.drop_button.setMinimumHeight(px(44 if compact else 74))
        self.file_scroll.setFixedHeight(px(94))
        apply_workspace_style(self)

    def set_step(self, step):
        self.current_step = step
        self.pages.setCurrentIndex(step)
        for index, button in enumerate(self.step_buttons):
            button.setIcon(step_marker(index + 1, active=index == step, complete=index < step))
            button.setProperty("active", index == step)
            button.setEnabled(
                index == 0
                or (index == 1 and self.source_accepted)
                or (index == 2 and self.mapping_accepted)
            )
            button.style().unpolish(button)
            button.style().polish(button)
        self.update_navigation()

    def go_to_step(self, step):
        if step == 1 and not self.source_accepted:
            return
        if step == 2 and not self.mapping_accepted:
            return
        self.set_step(step)
        if step == 0:
            self.drop_button.setFocus()
            self.content_scroll.ensureWidgetVisible(self.drop_button)
        self.update_summary()

    def advance_step(self):
        if self.current_step == 0 and self.files:
            self.source_accepted = True
            self.set_step(1)
            self.validate()
        elif self.current_step == 1:
            self.validate()
            if self.plans:
                self.mapping_accepted = True
                self.review_confirmation.setChecked(False)
                self.set_step(2)

    def update_navigation(self, *_):
        ready = sum(len(plan.rows) - len(plan.duplicates) for plan in self.plans)
        self.back_button.setEnabled(self.current_step > 0)
        self.next_button.setVisible(self.current_step < 2)
        self.next_button.setEnabled(
            bool(self.files) if self.current_step == 0 else bool(self.plans)
        )
        self.next_button.setText(
            tr("Zaakceptuj źródło i przejdź dalej")
            if self.current_step == 0
            else tr("Zaakceptuj mapowanie i sprawdź błędy")
        )
        self.save_button.setVisible(self.current_step == 2)
        self.save_button.setEnabled(
            self.current_step == 2
            and self.source_accepted
            and self.mapping_accepted
            and self.review_confirmation.isChecked()
            and ready > 0
        )

    def header_mode_changed(self):
        self.sync_header_row()
        self.options_changed()

    def header_row_changed(self):
        if self.header_mode.currentData() == "manual":
            self.options_changed()

    def sync_header_row(self):
        automatic = self.header_mode.currentData() == "auto"
        self.header_row_label.setText(tr("Wykryty wiersz") if automatic else tr("Numer wiersza"))
        self.header_row.setEnabled(not automatic)
        with QSignalBlocker(self.header_row):
            self.header_row.setMinimum(0 if automatic else 1)
            if automatic:
                index = self.raw_file.currentIndex()
                self.header_row.setValue(
                    self.files[index].header_row if 0 <= index < len(self.files) else 0
                )
            else:
                self.header_row.setValue(max(1, self.header_row.value()))

    def update_summary(self):
        if self.current_step == 0:
            self.summary.setText(
                tr(
                    "Pliki: {count} · Wiersze: {rows}",
                    count=len(self.files),
                    rows=sum(len(file.rows) for file in self.files),
                )
            )
            self.update_navigation()
            return
        if not self.plans:
            self.summary.setText(
                tr("Sprawdź mapowanie przed importem.")
                if self.files
                else tr("Wybierz pliki do importu.")
            )
            self.save_button.setText(tr("Importuj transakcje"))
            self.update_navigation()
            return
        duplicates = sum(len(plan.duplicates) for plan in self.plans)
        ready = sum(len(plan.rows) for plan in self.plans) - duplicates
        excluded = sum(
            len(set(plan.skipped_rows) & self.excluded_rows.get(plan.file.digest, set()))
            for plan in self.plans
        )
        invalid = sum(len(plan.skipped_rows) for plan in self.plans) - excluded
        self.summary.setText(
            tr(
                "{ready} gotowych · {invalid} błędnych · {excluded} wykluczonych · {duplicates} duplikatów",
                ready=ready,
                invalid=invalid,
                excluded=excluded,
                duplicates=duplicates,
            )
        )
        self.save_button.setText(tr("Importuj transakcje ({count})", count=ready))
        self.update_navigation()

    def update_notices(self):
        invalid = sum(
            len(plan.skipped_rows)
            - len(set(plan.skipped_rows) & self.excluded_rows.get(plan.file.digest, set()))
            for plan in self.plans
        )
        text = tr("Błędne wiersze zostaną pominięte: {count}.", count=invalid)
        self.notice_labels[0].setText(text)
        self.notice_icons[0].setPixmap(
            icon("alert" if invalid else "check", WARNING if invalid else SUCCESS).pixmap(
                QSize(px(24), px(24))
            )
        )
        rows = []
        for message in self.load_errors:
            filename, separator, reason = message.partition(": ")
            rows.append((filename if separator else "", None, reason if separator else message))
        for file in self.files:
            rows.extend((file.name, None, warning) for warning in file.header_warnings)
        for plan in self.plans:
            rows.extend(
                (plan.file.name, line, reason) for line, reason in sorted(plan.skipped_rows.items())
            )
            rows.extend(
                (
                    plan.file.name,
                    line,
                    tr("Duplikat: rekord jest już zapisany i zostanie pominięty."),
                )
                for line in plan.duplicates
            )
            rows.extend(
                (plan.file.name, row["source_line"], row["conflict_explanation"])
                for row in plan.rows
                if row.get("conflict_explanation")
            )
        opening_plan = min(
            (plan for plan in self.plans if plan.opening_date),
            key=lambda plan: plan.opening_date,
            default=None,
        )
        if opening_plan:
            rows.append(
                (
                    opening_plan.file.name,
                    None,
                    tr(
                        "Data startu portfela zostanie zmieniona na {date}. Saldo początkowe pozostanie takie samo.",
                        date=format_date(opening_plan.opening_date),
                    ),
                )
            )
        if not rows and self.plans:
            rows.append(("", None, tr("Brak błędów. Poprawne rekordy są gotowe do importu.")))
        self.issues_model.set_rows(rows)
        self.source_status.setText(
            "\n".join(self.load_errors)
            if self.load_errors
            else tr(
                "Rozszerzaj kolumny, przeciągając krawędzie nagłówków. Zaznacz wiersze do pominięcia i zaakceptuj źródło."
            )
        )

    def refresh_file_cards(self):
        while self.file_cards_layout.count():
            item = self.file_cards_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.file_cards = []
        for index, file in enumerate(self.files):
            path = self.loaded_paths[index]
            size = Path(path).stat().st_size if Path(path).exists() else 0
            subtitle = tr(
                "{size} KB · {count} wierszy", size=max(1, round(size / 1024)), count=len(file.rows)
            )
            card = ImportFileCard(
                file.name,
                subtitle,
                lambda index=index: self.raw_file.setCurrentIndex(index),
                lambda checked=False, index=index: self.remove_file(index),
            )
            card.setFixedWidth(px(300))
            self.file_cards_layout.addWidget(card)
            self.file_cards.append(card)
        self.file_scroll.setVisible(bool(self.files))
        self.file_scroll.setFixedHeight(px(94))

    def remove_file(self, index):
        if index >= len(self.loaded_paths):
            return
        removed = self.loaded_paths[index]
        remaining = [path for path in self.paths if path != removed]
        if remaining:
            self.load_paths(remaining, preserve_mapping=True)
            return
        self.invalidate()
        self.paths, self.files, self.loaded_paths = [], [], []
        self.file = None
        self.load_errors = []
        self.excluded_rows = {}
        self.raw_file.clear()
        self.refresh_file_cards()
        self.details.clear()
        self.sync_header_row()
        self.preview_timer.stop()
        self.update_summary()
        self.set_step(0)

    def options_changed(self):
        if self.paths:
            self.load_paths(self.paths, preserve_mapping=bool(self.files))
        else:
            self.invalidate()

    def raw_file_changed(self, *_):
        self.raw_offset = 0
        self.render_raw()
        index = self.raw_file.currentIndex()
        if hasattr(self, "mapping_file"):
            with QSignalBlocker(self.mapping_file):
                self.mapping_file.setCurrentIndex(index)
        self.sync_header_row()
        for number, card in enumerate(self.file_cards):
            card.setProperty("selected", number == index)
            card.style().unpolish(card)
            card.style().polish(card)
        if self.current_step == 1 and not self._loading and not self._validating:
            self.preview_timer.start()

    def change_raw_page(self, direction):
        self.raw_offset = max(0, self.raw_offset + direction * 500)
        self.render_raw()
        if self.current_step == 1:
            self.preview_timer.start()

    def render_raw(self):
        index = self.raw_file.currentIndex()
        if index < 0 or index >= len(self.files):
            with QSignalBlocker(self.raw_preview):
                self.raw_preview.setRowCount(0)
                self.raw_preview.setColumnCount(2)
                self.raw_preview.setHorizontalHeaderLabels([tr("Pomiń"), tr("Wiersz")])
            self.raw_position.setText(tr("Wiersze: 0"))
            self.raw_previous.setEnabled(False)
            self.raw_next.setEnabled(False)
            self.mapping_position.setText(tr("Wiersze: 0"))
            self.mapping_previous.setEnabled(False)
            self.mapping_next.setEnabled(False)
            return
        file = self.files[index]
        rows = file.source_rows or [
            (line, [raw.get(h, "") for h in file.headers]) for line, raw in file.rows
        ]
        visible = rows[self.raw_offset : self.raw_offset + 500]
        width = max([len(file.headers), *(len(values) for _, values in visible)])
        headers = [
            *file.headers,
            *[
                tr("Dodatkowe pole {number}", number=i + 1)
                for i in range(width - len(file.headers))
            ],
        ]
        with QSignalBlocker(self.raw_preview):
            self.raw_preview.setColumnCount(width + 2)
            self.raw_preview.setHorizontalHeaderLabels([tr("Pomiń"), tr("Wiersz"), *headers])
            fill_table(
                self.raw_preview,
                [["", line, *values, *[""] * (width - len(values))] for line, values in visible],
                resize_columns=False,
            )
            for row, (line, _) in enumerate(visible):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setData(Qt.ItemDataRole.UserRole, (file.digest, line))
                item.setCheckState(
                    Qt.CheckState.Checked
                    if line in self.excluded_rows.get(file.digest, set())
                    else Qt.CheckState.Unchecked
                )
                if line in file.row_errors:
                    item.setToolTip(file.row_errors[line])
                self.raw_preview.setItem(row, 0, item)
        self.raw_position.setText(
            tr(
                "Wiersze {first}–{last} z {total}",
                first=self.raw_offset + 1 if rows else 0,
                last=min(self.raw_offset + 500, len(rows)),
                total=len(rows),
            )
        )
        self.raw_previous.setEnabled(self.raw_offset > 0)
        self.raw_next.setEnabled(self.raw_offset + 500 < len(rows))
        self.mapping_position.setText(self.raw_position.text())
        self.mapping_previous.setEnabled(self.raw_previous.isEnabled())
        self.mapping_next.setEnabled(self.raw_next.isEnabled())
        self.style_source_rows()

    def style_source_rows(self):
        index = self.raw_file.currentIndex()
        if index < 0 or index >= len(self.files):
            return
        file = self.files[index]
        plan = next((plan for plan in self.plans if plan.file.digest == file.digest), None)
        errors = dict(file.row_errors)
        if plan:
            errors.update(plan.skipped_rows)
        for row in range(self.raw_preview.rowCount()):
            marker = self.raw_preview.item(row, 0)
            if not marker or marker.data(Qt.ItemDataRole.UserRole) is None:
                continue
            _, line = marker.data(Qt.ItemDataRole.UserRole)
            excluded = line in self.excluded_rows.get(file.digest, set())
            reason = errors.get(line, "")
            tooltip = (
                self.raw_row_tooltip(
                    file,
                    line,
                    reason,
                    [
                        self.raw_preview.item(row, col).text()
                        for col in range(2, self.raw_preview.columnCount())
                    ],
                )
                if reason
                else None
            )
            with QSignalBlocker(self.raw_preview):
                marker.setToolTip(tooltip or "")
            for col in range(1, self.raw_preview.columnCount()):
                item = self.raw_preview.item(row, col)
                if not item:
                    continue
                item.setToolTip(tooltip or item.text())
                color = MUTED if excluded else WARNING if reason else "#EDF4FF"
                item.setForeground(QColor(display_color(color)))
                item.setBackground(
                    QColor(display_color("#1A2B3D" if reason and not excluded else "#112233"))
                )
        self.raw_preview.verticalHeader().setDefaultSectionSize(px(40))
        self.fit_preview_columns(self.raw_preview)

    @staticmethod
    def raw_row_tooltip(file, line, reason, values=None):
        if values is None:
            values = next((values for number, values in file.source_rows if number == line), None)
        if values is None:
            values = next(
                (
                    [raw.get(h, "") for h in file.headers]
                    for number, raw in file.rows
                    if number == line
                ),
                [],
            )
        cells = "".join(
            f"<tr><td><b>{escape(file.headers[i] if i < len(file.headers) else str(i + 1))}</b></td>"
            f"<td>{escape(str(value)) or '—'}</td></tr>"
            for i, value in enumerate(values)
        )
        return f"<b>{escape(str(reason))}</b><br><table cellspacing='4'>{cells}</table>"

    def fit_preview_columns(self, widget):
        from PyQt6.QtWidgets import QHeaderView

        header = widget.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(widget.columnCount()):
            if not widget.isColumnHidden(column):
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        for column in range(widget.columnCount()):
            item = widget.horizontalHeaderItem(column)
            if item:
                item.setToolTip(item.text())
        source_header = self.mapping_source_preview.horizontalHeader()
        source_header.setStretchLastSection(False)
        source_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        widths = self.raw_column_widths if widget is self.raw_preview else self.mapped_column_widths
        visible = [
            column for column in range(widget.columnCount()) if not widget.isColumnHidden(column)
        ]
        available = widget.viewport().width()
        minimums = {
            column: max(
                header.minimumSectionSize(),
                widget.fontMetrics().horizontalAdvance(widget.horizontalHeaderItem(column).text())
                + px(32),
            )
            for column in visible
        }
        # Keep identifiers compact and give descriptions the remaining space.
        mapped_minimums = {0: 65, 1: 105, 2: 100, 3: 150, 4: 140, 5: 130, 7: 115}
        weights = {0: 0, 1: 0, 2: 0, 3: 3, 4: 2, 5: 1, 7: 1}
        if widget is self.preview:
            minimums = {
                c: max(size, px(mapped_minimums.get(c, 120))) for c, size in minimums.items()
            }
        extra = max(0, available - sum(minimums.values()))
        total_weight = sum(weights.get(c, 1) for c in visible) or 1
        shares = {c: int(extra * weights.get(c, 1) / total_weight) for c in visible}
        if visible and widget is self.preview:
            shares[visible[-1]] += extra - sum(shares.values())
        self._fitting_columns = True
        try:
            for column in visible:
                title = widget.horizontalHeaderItem(column).text()
                default = (
                    max(px(65), minimums.get(column, px(65)))
                    if column == 0 or (column == 1 and widget is self.raw_preview)
                    else min(
                        px(280),
                        max(px(120), widget.fontMetrics().horizontalAdvance(title) + px(30)),
                    )
                )
                if widget is self.preview and not widths and column in visible:
                    widget.setColumnWidth(column, minimums[column] + shares[column])
                else:
                    widget.setColumnWidth(
                        column, max(minimums.get(column, 0), widths.get(title, default))
                    )
                if widget is self.raw_preview:
                    source_header.resizeSection(column, widget.columnWidth(column))
            # Refresh Qt's offsets for hidden sections after resizing; otherwise
            # their old widths can leave gaps before the Import column.
            for column in range(widget.columnCount()):
                if widget.isColumnHidden(column):
                    header.showSection(column)
                    header.hideSection(column)
        finally:
            self._fitting_columns = False

    def remember_column_width(self, column, width, widget):
        if self._loading or self._validating or getattr(self, "_fitting_columns", False):
            return
        if widget is self.preview and (not self.plans or not self.preview.rowCount()):
            return
        original = self.preview if widget is self.preview else self.raw_preview
        item = original.horizontalHeaderItem(column)
        if item is None:
            return
        widths = self.mapped_column_widths if original is self.preview else self.raw_column_widths
        widths[item.text()] = width
        if original is self.raw_preview:
            other = self.mapping_source_preview if widget is self.raw_preview else self.raw_preview
            with QSignalBlocker(other.horizontalHeader()):
                other.setColumnWidth(column, width)

    def exclude_row(self, item):
        if item.column() != 0 or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        digest, line = item.data(Qt.ItemDataRole.UserRole)
        excluded = self.excluded_rows.setdefault(digest, set())
        if item.checkState() == Qt.CheckState.Checked:
            excluded.add(line)
        else:
            excluded.discard(line)
        self.invalidate()
        self.details.setPlainText(tr("Zmieniono pomijane wiersze. Sprawdź podgląd przed zapisem."))
        self.style_source_rows()

    def choose_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Wybierz pliki transakcji"), "", tr("CSV i Excel (*.csv *.xlsx *.xlsm)")
        )
        if paths:
            self.load_paths([*self.paths, *paths], preserve_mapping=bool(self.files))

    def load_paths(self, paths, *, preserve_mapping=False):
        self._loading = True
        self.loaded_paths = []
        try:
            self._load_paths(paths, preserve_mapping=preserve_mapping)
        finally:
            self._loading = False
            self.refresh_file_cards()
            self.raw_file_changed()
            self.update_summary()
            self.source_accepted = self.mapping_accepted = False
            self.set_step(0)
            with QSignalBlocker(self.mapping_file):
                self.mapping_file.clear()
                self.mapping_file.addItems([file.name for file in self.files])

    def _load_paths(self, paths, *, preserve_mapping=False):
        self.invalidate()
        self.load_errors = []
        if not preserve_mapping:
            self.excluded_rows = {}
        previous = {key: combo.currentData() for key, combo in self.fields.items()}
        self.file, self.files = None, []
        with QSignalBlocker(self.raw_file):
            self.raw_file.clear()
        self.raw_file_changed()
        try:
            paths = list(dict.fromkeys(str(Path(path).resolve()) for path in paths))
            if not paths or len(paths) > 50:
                raise ValueError(tr("Wybierz od 1 do 50 plików."))
            if sum(Path(path).stat().st_size for path in paths) > 100 * 1024 * 1024:
                raise ValueError(
                    tr("Paczka przekracza 100 MB. Podziel ją na mniejsze grupy plików.")
                )
            files = []
            for path in paths:
                try:
                    files.append(
                        read_import_file(
                            path,
                            self.encoding.currentData(),
                            self.delimiter.currentData(),
                            self.sheet_name.text().strip() or None,
                            header_row=self.header_row.value()
                            if self.header_mode.currentData() == "manual"
                            else None,
                        )
                    )
                    self.loaded_paths.append(path)
                except (ValueError, OSError, csv.Error) as exc:
                    self.load_errors.append(tr("{v0}: {v1}", v0=Path(path).name, v1=exc))
                if sum(len(file.rows) for file in files) > 200000:
                    raise ValueError(
                        tr("Paczka przekracza 200 000 wierszy. Podziel ją na mniejsze grupy.")
                    )
        except (ValueError, OSError, csv.Error) as exc:
            self.paths = []
            self.filename.setText(tr("Nie wczytano plików"))
            self.details.setPlainText(str(exc))
            return
        self.paths, self.files, self.file = paths, files, files[0] if files else None
        self.filename.setText("\n".join(file.name for file in files) or tr("Nie wczytano plików"))
        self.filename.setToolTip(
            "\n".join(f"{file.name}: {file.encoding or 'Excel'}" for file in files)
        )
        # Only columns present in every file can be shared by the batch.
        headers = (
            [header for header in files[0].headers if all(header in file.headers for file in files)]
            if files
            else []
        )
        defaults = previous if preserve_mapping else suggested_mapping(headers)
        for key, combo in self.fields.items():
            combo.clear()
            glyph = icon(combo.property("mappingIcon"), MUTED)
            combo.addItem(glyph, tr("— brak —"), None)
            for header in headers:
                combo.addItem(glyph, header, header)
            select_data(combo, defaults.get(key))
        with QSignalBlocker(self.raw_file):
            self.raw_file.clear()
            self.raw_file.addItems([file.name for file in files])
        self.raw_file_changed()
        self.details.setPlainText(
            "\n".join(self.load_errors)
            + "\n"
            + "\n".join(
                tr(
                    "{file}: nagłówki w wierszu {row}; dane poniżej tego wiersza.",
                    file=file.name,
                    row=file.header_row,
                )
                for file in files
            )
            + "\n"
            + "\n".join(
                f"{file.name}: {warning}" for file in files for warning in file.header_warnings
            )
            + "\n"
            + tr(
                "Pliki: {v0}. Wiersze: {v1}. Podgląd surowy: {v2}. Wybierz wspólne mapowanie i sprawdź całą paczkę.",
                v0=len(files),
                v1=sum(len(file.rows) for file in files),
                v2=files[0].name if files else "—",
            )
        )

    @staticmethod
    def dropped_paths(event):
        if not event.mimeData().hasUrls():
            return []
        urls = event.mimeData().urls()
        if not urls or any(not url.isLocalFile() for url in urls):
            return []
        paths = [url.toLocalFile() for url in urls]
        return (
            paths
            if all(
                Path(path).is_file() and Path(path).suffix.lower() in SUPPORTED_FILES
                for path in paths
            )
            else []
        )

    def dragEnterEvent(self, event):
        if self.dropped_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = self.dropped_paths(event)
        if paths:
            self.load_paths([*self.paths, *paths], preserve_mapping=bool(self.files))
            event.acceptProposedAction()
        else:
            event.ignore()

    def eventFilter(self, watched, event):
        if watched is self.issues_table.viewport() and event.type() == QEvent.Type.ToolTip:
            index = self.issues_table.indexAt(event.pos())
            if index.isValid():
                name, line, reason = self.issues_model.rows[index.row()]
                file = next((file for file in self.files if file.name == name), None)
                if file is not None and line is not None:
                    QToolTip.showText(
                        event.globalPos(),
                        self.raw_row_tooltip(file, line, reason),
                        self.issues_table,
                    )
                    return True
        if (
            event.type() == QEvent.Type.Resize
            and watched is self.preview.viewport()
            and event.size().width() != event.oldSize().width()
            and not self.mapped_column_widths
        ):
            self.column_fit_timer.start(0)
        if event.type() in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ) and self.dropped_paths(event):
            if event.type() == QEvent.Type.Drop:
                self.dropEvent(event)
            else:
                self.dragEnterEvent(event)
            return True
        return super().eventFilter(watched, event)

    def validate(self):
        if self._loading or self._validating:
            return
        self._validating = True
        self.preview_timer.stop()
        try:
            self._validate()
        finally:
            self._validating = False
            self.update_summary()

    def _validate(self):
        self.invalidate()
        try:
            files = self.files or ([self.file] if self.file is not None else [])
            if not files:
                raise ValueError(tr("Najpierw wczytaj pliki CSV lub Excel."))
            mapping = {
                key: combo.currentData() for key, combo in self.fields.items() if combo.isEnabled()
            }
            mapping["amount_mode"] = "signed"
            plans = prepare_import_batch(
                self.db, files, self.wallet.currentData(), mapping, excluded_rows=self.excluded_rows
            )
            self.plans, self.plan = plans, plans[0]
            self.preview.setColumnCount(10)
            self.preview.setHorizontalHeaderLabels(
                [
                    tr("Wiersz"),
                    tr("Data"),
                    tr("Kwota"),
                    tr("Opis"),
                    tr("Kontrahent"),
                    tr("Kategoria"),
                    tr("Podkategoria"),
                    tr("Import"),
                    tr("Konflikt / wyjaśnienie"),
                    tr("Plik"),
                ]
            )
            from itertools import islice

            selected_index = self.raw_file.currentIndex()
            selected_digest = (
                self.files[selected_index].digest if 0 <= selected_index < len(self.files) else None
            )
            visible_lines = {
                self.raw_preview.item(row, 0).data(Qt.ItemDataRole.UserRole)[1]
                for row in range(self.raw_preview.rowCount())
            }
            preview_rows = list(
                islice(
                    (
                        (plan, row)
                        for plan in plans
                        if selected_digest is None or plan.file.digest == selected_digest
                        for row in plan.rows
                        if not visible_lines or row["source_line"] in visible_lines
                    ),
                    1000,
                )
            )
            fill_table(
                self.preview,
                [
                    [
                        r["source_line"],
                        format_date(r["date"]),
                        amount_label(r["amount_minor"]),
                        r["description"],
                        r["from_to"],
                        r["category_name"],
                        r["subcategory_name"],
                        (tr("Pomiń — już zapisana") if r["duplicate"] else tr("Nowa")),
                        r["conflict_explanation"],
                        plan.file.name,
                    ]
                    for plan, r in preview_rows
                ],
                resize_columns=False,
            )
            for column in (6, 8, 9):
                self.preview.setColumnHidden(column, True)
            self.preview.verticalHeader().setDefaultSectionSize(px(40))
            self.fit_preview_columns(self.preview)
            categories = {c["name"]: c for c in self.db.categories() if c["parent_id"] is None}
            for row in range(self.preview.rowCount()):
                self.preview.item(row, 8).setToolTip(self.preview.item(row, 8).text())
                plan, transaction = preview_rows[row]
                category = categories.get(transaction["category_name"])
                if transaction["is_uncategorized"]:
                    category = self.db.category(self.db.default_category_id())
                    self.preview.item(row, 5).setText(category["display_name"])
                if category:
                    from home_finance_cockpit.reports.presentation import category_color

                    self.preview.item(row, 5).setIcon(
                        icon(
                            category["icon_name"],
                            category_color(category["name"], {category["name"]: category["color"]}),
                        )
                    )
                self.preview.item(row, 5).setToolTip(
                    transaction["subcategory_name"] or self.preview.item(row, 5).text()
                )
                self.preview.item(row, 2).setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.preview.item(row, 2).setForeground(
                    QColor(display_color(RED if transaction["amount_minor"] < 0 else SUCCESS))
                )
                result = self.preview.item(row, 7)
                result.setForeground(
                    QColor(display_color(MUTED if transaction["duplicate"] else SUCCESS))
                )
                result.setIcon(
                    icon(
                        "undo" if transaction["duplicate"] else "check",
                        MUTED if transaction["duplicate"] else SUCCESS,
                    )
                )
                for column in (0, 1, 3, 4, 7):
                    self.preview.item(row, column).setToolTip(
                        transaction["conflict_explanation"] or self.preview.item(row, column).text()
                    )
            messages = list(self.load_errors)
            if sum(len(plan.rows) for plan in plans) > 1000:
                messages.append(
                    tr(
                        "Podgląd pokazuje pierwsze 1000 operacji. Walidacja i zapis obejmują całą paczkę."
                    )
                )
            for plan in plans:
                messages.extend(
                    f"{plan.file.name}: {warning}" for warning in plan.file.header_warnings
                )
                messages.append(
                    tr(
                        "{file}: nagłówki w wierszu {row}; dane poniżej tego wiersza.",
                        file=plan.file.name,
                        row=plan.file.header_row,
                    )
                )
                messages.append(
                    tr(
                        "{v0}: nowe {v1}, duplikaty {v2}, pominięte wiersze {v3}.",
                        v0=plan.file.name,
                        v1=len(plan.rows) - len(plan.duplicates),
                        v2=len(plan.duplicates),
                        v3=len(plan.skipped_rows),
                    )
                )
                messages.extend(
                    tr(
                        "{file}, wiersz {line}: {reason}",
                        file=plan.file.name,
                        line=line,
                        reason=reason,
                    )
                    for line, reason in plan.skipped_rows.items()
                )
            opening = min((plan.opening_date for plan in plans if plan.opening_date), default=None)
            if opening:
                messages.append(
                    tr(
                        "Data startu portfela zostanie zmieniona na {date}. Saldo początkowe pozostanie takie samo.",
                        date=format_date(opening),
                    )
                )
            self.details.setPlainText("\n".join(messages))
            self.style_source_rows()
            fallback_count = 0
            for plan in plans:
                primary, fallback = plan.mapping.get("amount"), plan.mapping.get("amount_fallback")
                valid_lines = {row["source_line"] for row in plan.rows}
                fallback_count += sum(
                    1
                    for line, raw in plan.file.rows
                    if line in valid_lines
                    and not raw.get(primary, "").strip()
                    and fallback
                    and raw.get(fallback, "").strip()
                )
            self.fallback_note.setText(
                tr("Użyto kwoty zapasowej w {count} wierszach.", count=fallback_count)
                if fallback_count
                else tr("Kwota zapasowa jest używana tylko przy pustej kwocie głównej.")
            )
        except (ValueError, sqlite3.Error) as exc:
            self.details.setPlainText("\n".join([*self.load_errors, str(exc)]))
            self.fallback_note.setText(str(exc))

    def save(self):
        if (
            not self.plans
            or self.current_step != 2
            or not self.source_accepted
            or not self.mapping_accepted
            or not self.review_confirmation.isChecked()
        ):
            return
        if not any(len(plan.rows) > len(plan.duplicates) for plan in self.plans):
            return
        try:
            fresh = prepare_import_batch(
                self.db,
                [plan.file for plan in self.plans],
                self.wallet.currentData(),
                self.plan.mapping,
                excluded_rows=self.excluded_rows,
            )
            if self.review_signature(fresh) != self.review_signature(self.plans):
                self.mapping_accepted = False
                self.review_confirmation.setChecked(False)
                self.set_step(1)
                self.validate()
                self.fallback_note.setText(
                    tr(
                        "Dane zmieniły się od podglądu. Ponownie zaakceptuj mapowanie i sprawdź podsumowanie."
                    )
                )
                return
            counts = commit_import_batch(self.db, self.plans)
        except (ValueError, sqlite3.Error) as exc:
            self.invalidate()
            self.details.setPlainText(str(exc))
            self.fallback_note.setText(str(exc))
            return
        QMessageBox.information(
            self,
            tr("Import zakończony"),
            tr(
                "Dodano transakcji: {added}. Pominięto wierszy: {skipped}. Pliki: {files}.",
                added=sum(counts),
                skipped=sum(len(plan.skipped_rows) + len(plan.duplicates) for plan in self.plans),
                files=len(counts),
            ),
        )
        self.accept()

    @staticmethod
    def review_signature(plans):
        return tuple(
            (
                plan.file.digest,
                plan.opening_date,
                tuple(sorted(plan.skipped_rows.items())),
                tuple(plan.errors),
                tuple(
                    (
                        row["source_line"],
                        row["date"],
                        row["amount_minor"],
                        row["duplicate"],
                        row["category_name"],
                        row["subcategory_name"],
                        row["category_conflict"],
                    )
                    for row in plan.rows
                ),
            )
            for plan in plans
        )

    def done(self, result):
        self.preview_timer.stop()
        self.column_fit_timer.stop()
        super().done(result)
