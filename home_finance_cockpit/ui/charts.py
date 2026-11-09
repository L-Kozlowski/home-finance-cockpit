"""Shared chart rendering and a separate, resizable interactive chart window."""

from copy import deepcopy
from datetime import date, timedelta

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.chart_dates import format_chart_dates
from home_finance_cockpit.ui.theme import ACCENT, RED, style_figure

CHART_TITLES = ("Struktura portfeli", "Kategorie wydatków", "Saldo portfeli w czasie")


class ExpandableCanvas(FigureCanvasQTAgg):
    enlarge_requested = pyqtSignal()

    def draw(self):
        from PyQt6 import sip

        if sip.isdeleted(self):
            return
        style_figure(self.figure)
        if getattr(self.figure, "_transparent_chart", False):
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAutoFillBackground(False)
            self.setStyleSheet("background: transparent;")
            self.figure.patch.set_alpha(0)
            for ax in self.figure.axes:
                ax.patch.set_alpha(0)
                ax.tick_params(axis="both", length=3, width=0.6)
        format_chart_dates(self.figure)
        try:
            super().draw()
        except RuntimeError:
            # Qt can delete a replaced workspace while Agg processes draw events.
            if not sip.isdeleted(self):
                raise

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.enlarge_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


def render_chart(figure, index, data, percentage=True):
    from home_finance_cockpit.domain.chart_palettes import chart_colors

    colors = chart_colors()
    figure.clear()
    ax = figure.add_subplot(111)
    ax.set_title(tr("{v0} ({v1})", v0=tr(CHART_TITLES[index]), v1=data["currency"]))
    if index == 0:
        if data["wallets"]:
            wallets = data["wallets"][::-1]
            bars = ax.barh(
                [w["name"] for w in wallets],
                [w["balance"] / 100 for w in wallets],
                color=[
                    colors[i % len(colors)] if w["balance"] >= 0 else RED
                    for i, w in enumerate(wallets)
                ],
                height=0.48,
            )
            positive = sum(max(0, w["balance"]) for w in wallets)
            signed = any(w["balance"] < 0 for w in wallets)
            labels = [
                f"{w['balance'] / positive:.0%}"
                if percentage and positive and not signed
                else amount_label(w["balance"])
                for w in wallets
            ]
            ax.bar_label(bars, labels=labels, padding=6, fontsize=9)
            ax.margins(x=0.30, y=0.25)
            ax.axvline(0, color="grey", linewidth=0.7)
            ax.set_xlabel((tr("Suma sald: ") + amount_label(data["balance"], data["currency"])))
        else:
            ax.text(0.5, 0.5, tr("Brak portfeli"), ha="center", transform=ax.transAxes)
    elif index == 1:
        if data["categories"]:
            values = [v for _, v in data["categories"]]
            total = sum(values)
            formatter = (
                "%1.1f%%" if percentage else lambda pct: amount_label(round(pct * total / 100))
            )
            from home_finance_cockpit.reports.presentation import category_color

            wedges, *_ = ax.pie(
                values,
                autopct=formatter,
                colors=[category_color(name) for name, _ in data["categories"]],
                wedgeprops=dict(width=0.5, edgecolor="#112233"),
            )
            ax.legend(
                wedges,
                [name for name, _ in data["categories"]],
                loc="center left",
                bbox_to_anchor=(1, 0.5),
                fontsize=8,
            )
        else:
            ax.text(0.5, 0.5, tr("Brak wydatków"), ha="center", transform=ax.transAxes)
    else:
        if data.get("balance_trend"):
            days = [date.fromisoformat(row[0]) for row in data["balance_trend"]]
            values = [row[1] / 100 for row in data["balance_trend"]]
            ax.plot(
                days,
                values,
                label=tr("Saldo z zapisów"),
                color=ACCENT,
                linewidth=2,
                marker="o",
                markersize=3,
            )
            ax.fill_between(days, values, color=ACCENT, alpha=0.10)
            if len(days) == 1:
                first = days[0] - timedelta(days=1) if days[0] > date.min else days[0]
                last = days[0] + timedelta(days=1) if days[0] < date.max else days[0]
                ax.set_xlim(first, last)
            locator = AutoDateLocator(minticks=3, maxticks=8)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(ConciseDateFormatter(locator))
            ax.legend(fontsize=8)
            ax.grid(alpha=0.2)
        else:
            ax.text(
                0.5, 0.5, tr("Brak zapisów salda w okresie"), ha="center", transform=ax.transAxes
            )
    return ax


class ChartDialog(QDialog):
    def __init__(
        self, parent, index, data, percentage=True, context="", *, renderer=None, title=None
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.setWindowTitle(
            tr("{v0} — {v1}", v0=tr(title or CHART_TITLES[index]), v1=data["currency"])
        )
        available = self.screen().availableGeometry()
        self.resize(min(1100, available.width() - 60), min(750, available.height() - 80))
        self.setMinimumSize(400, 300)
        layout = QVBoxLayout(self)
        hint = QLabel(
            tr(
                "Widok z chwili otwarcia. Użyj lupy do zaznaczenia zbliżenia, dłoni do przesuwania, a przycisku Home do przywrócenia widoku. Wykres można też zapisać z paska narzędzi."
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        if context:
            label = QLabel(context)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.canvas = ExpandableCanvas(Figure(figsize=(10, 6), layout="constrained"))
        self.toolbar = NavigationToolbar2QT(self.canvas, self, coordinates=False)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self.data = deepcopy(data)
        self.renderer, self.chart_index, self.percentage = (
            renderer or render_chart,
            index,
            percentage,
        )
        self.refresh_chart()

    def refresh_chart(self):
        self.renderer(self.canvas.figure, self.chart_index, self.data, self.percentage)
        self.canvas.draw_idle()
