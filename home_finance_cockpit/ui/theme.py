"""Shared desktop palette; stays lightweight for the database chooser."""

import atexit
import os
import re
from functools import partial
from pathlib import Path
from weakref import ref

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QToolTip

from home_finance_cockpit.domain import brand_palette as brand
from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.scaling import density, px, screen_density

BACKGROUND = brand.BACKGROUND.lower()
SURFACE = brand.SURFACE.lower()
TEXT = brand.TEXT.lower()
MUTED = brand.MUTED.lower()
ACCENT = brand.ACCENT.lower()
BLUE = brand.INFO.lower()
RED = brand.ERROR.lower()
from home_finance_cockpit.domain.brand_palette import BRAND_GRADIENT

SUCCESS = brand.SUCCESS.lower()
WARNING = brand.WARNING.lower()
DISABLED = brand.DISABLED.lower()
INK = brand.INK.lower()
CHART_COLORS = tuple(c.lower() for c in brand.CHART_COLORS)

BRAND_CONTROL_STYLES = f"""
QPushButton[role="primary"] {{ background: {BRAND_GRADIENT}; color: {INK}; border-color: #06B6D4; }}
QPushButton[role="primary"]:hover {{ background: #55E8FF; color: {INK}; border-color: #22D3EE; }}
QPushButton[role="primary"]:pressed {{ background: #06B6D4; color: {INK}; }}
QProgressBar::chunk {{ background: {BRAND_GRADIENT}; }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{ background: #22D3EE; border-color: #06B6D4; }}
"""

STYLESHEET = """
QWidget { color: #edf4ff; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog, QWidget#appShell, QWidget#page, QTabWidget::pane { background: #0b1623; }
QTabWidget::pane { border: 0; }
QWidget#sidebar { background: #0b1623; border-right: 1px solid #24394d; }
QFrame#card, QLabel#metricCard { background: #1a2b3d; border: 1px solid #24394d; border-radius: 10px; }
QFrame#card QLabel { background: transparent; border: 0; }
QLabel[role="muted"] { color: #a8bed5; }
QLabel[role="section"] { font-size: 16px; font-weight: 600; }
QLabel#pageTitle { font-size: 28px; font-weight: 700; }
QLabel#brand { font-size: 23px; font-weight: 700; }
QLabel#badge { color: #22d3ee; background: #153b4d; padding: 5px 9px; border-radius: 5px; }
QPushButton, QToolButton { background: #1a2b3d; border: 1px solid #24394d; border-radius: 6px; padding: 7px 12px; min-height: 18px; }
QPushButton:hover, QToolButton:hover { background: #1e3347; border-color: #06b6d4; }
QPushButton::menu-indicator, QToolButton::menu-indicator { image:none; width:0; height:0; }
QPushButton:pressed { background: #1e3347; }
QPushButton:checked, QToolButton:checked { background: #153b4d; border-color: #22d3ee; color: #55e8ff; }
QPushButton[role="primary"] { background: #22d3ee; color: #062536; border-color: #22d3ee; font-weight: 600; }
QPushButton[role="primary"]:hover { background: #55e8ff; }
QPushButton[role="danger"] { color: #ef4444; }
QPushButton[role="nav"] { text-align: left; background: transparent; border: 1px solid transparent; padding: 10px 14px; font-size: 14px; }
QPushButton[role="nav"]:hover { background: #1a2b3d; }
QPushButton[role="nav"]:checked { background: #15475b; color: #55e8ff; border-color: #25435b; }
QPushButton:disabled, QToolButton:disabled { background: #112233; color: #7b8fa6; border-color: #24394d; }
QPushButton[role="primary"]:disabled { background: #112233; color: #7b8fa6; border-color: #24394d; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
    background: #1e3347; border: 1px solid #24394d; border-radius: 6px; padding: 6px 9px; selection-background-color: #16465b; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QPushButton:focus, QToolButton:focus { border: 1px solid #22d3ee; }
/* Embedded line-edit buttons use Qt's own centered geometry. */
QLineEdit QToolButton, QLineEdit QToolButton:hover, QLineEdit QToolButton:pressed,
QLineEdit QToolButton:focus, QLineEdit QToolButton:disabled {
    padding: 0; min-height: 0; border: 0; border-radius: 0; background: transparent;
}
QComboBox::drop-down, QDateEdit::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { background: #1a2b3d; color: #edf4ff; selection-background-color: #16465b; }
QAbstractItemView { background: #112233; alternate-background-color: #1a2b3d; color: #edf4ff; border: 1px solid #24394d;
    border-radius: 6px; selection-background-color: #16465b; selection-color: #ffffff; outline: 0; }
QTableView { gridline-color: #23394c; }
QTableView::item { padding: 5px 8px; border: 0; }
QHeaderView::section { background: #1e3347; color: #a8bed5; border: 0; border-bottom: 1px solid #24394d; padding: 6px 8px; font-weight: 600; }
QTableCornerButton::section { background: #1e3347; border: 0; }
QScrollArea { border: 0; background: transparent; }
QScrollArea > QWidget > QWidget { background: #0b1623; }
QScrollBar:vertical { background: #0b1623; width: 11px; margin: 0; }
QScrollBar:horizontal { background: #0b1623; height: 11px; margin: 0; }
QScrollBar::handle { background: #3d5b74; border-radius: 5px; min-height: 28px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: #1e3347; }
QSplitter::handle:hover { background: #06b6d4; }
QMenuBar { background: #0b1623; padding: 3px 8px; border-bottom: 1px solid #24394d; }
QMenuBar::item { padding: 5px 9px; }
QMenuBar::item:selected, QMenu::item:selected { background: #16465b; }
QMenu { background: #112233; border: 1px solid #24394d; padding: 5px; }
QMenu::item { padding: 7px 20px; }
QStatusBar { background: #0b1623; color: #a8bed5; border-top: 1px solid #24394d; }
QToolTip { background: #1a2b3d; color: #edf4ff; border: 1px solid #24394d; padding: 6px; }
QProgressBar { background: #1e3347; border: 1px solid #24394d; border-radius: 5px; text-align: center; min-height: 16px; }
QProgressBar::chunk { background: #06b6d4; border-radius: 4px; }
QGroupBox { border: 1px solid #24394d; border-radius: 6px; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; }
QCheckBox, QRadioButton { spacing: 7px; padding: 3px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCalendarWidget QWidget { background: #1a2b3d; }
QCalendarWidget QTableView::item { padding: 0; border: 0; }
QCalendarWidget QToolButton { padding: 3px 6px; min-height: 18px; }
"""


class TooltipBlocker(QObject):
    """Suppress hover help, including item views and Qt's built-in controls."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip:
            return True
        return super().eventFilter(watched, event)


def remove_tooltip_filter(application):
    app = application()
    if (
        app is not None
        and not sip.isdeleted(app)
        and getattr(app, "_tooltip_blocker_installed", False)
    ):
        app.removeEventFilter(app._tooltip_blocker)
        app._tooltip_blocker_installed = False


def disable_tooltips(app):
    if not hasattr(app, "_tooltip_blocker"):
        app._tooltip_blocker = TooltipBlocker(app)
        cleanup = partial(remove_tooltip_filter, ref(app))
        app.aboutToQuit.connect(cleanup)
        # Offscreen tools can finish without entering QApplication.exec().
        # Remove Python event filters before Qt destroys windows at interpreter exit.
        atexit.register(cleanup)
    if not getattr(app, "_tooltip_blocker_installed", False):
        app.installEventFilter(app._tooltip_blocker)
        app._tooltip_blocker_installed = True
    QToolTip.hideText()


def configure_application(app, *, content_density=None):
    disable_tooltips(app)
    from home_finance_cockpit.ui.branding import configure_branding

    configure_branding(app)
    screen = app.primaryScreen().availableGeometry()
    factor = (
        screen_density(screen.width(), screen.height())
        if content_density is None
        else content_density
    )
    app.setProperty("contentDensity", max(0.75, min(1.0, float(factor))))
    app.setStyle("Fusion")
    app.setProperty("uiTheme", "dark")
    font_file = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
    family = "Segoe UI"
    if font_file.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            family = families[0]
    app.setFont(QFont(family, 10))
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, BACKGROUND),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, "#112233"),
        (QPalette.ColorRole.AlternateBase, "#1a2b3d"),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.Button, "#1a2b3d"),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.Highlight, "#16465b"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
        (QPalette.ColorRole.ToolTipBase, SURFACE),
        (QPalette.ColorRole.ToolTipText, TEXT),
        (QPalette.ColorRole.Link, ACCENT),
        (QPalette.ColorRole.PlaceholderText, "#7b8fa6"),
    ):
        palette.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#7b8fa6"))
    app.setPalette(palette)
    assets = Path(__file__).resolve().parent / "assets"
    stylesheet = (
        STYLESHEET
        + f"""
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{(assets / "chevron-down.svg").as_posix()}"); width: 14px; height: 14px; }}
    QCheckBox::indicator, QAbstractItemView::indicator {{ width: 16px; height: 16px; background: #1e3347; border: 1px solid #7b8fa6; border-radius: 3px; }}
    QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{ background: #22d3ee; border-color: #22d3ee; image: url("{(assets / "check.svg").as_posix()}"); }}
    QComboBox:disabled, QDateEdit:disabled, QLineEdit:disabled {{ color: #7b8fa6; background: #112233; border-color: #24394d; }}
    """
    )
    stylesheet += BRAND_CONTROL_STYLES
    app.setProperty(
        "baseStylesheet",
        re.sub(r"(\d+)px", lambda match: f"{max(1, px(int(match[1])))}px", stylesheet),
    )
    app.setProperty("darkStylesheet", app.property("baseStylesheet"))
    apply_font_size(app, round(font_scale() * 100))


def font_scale():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    return float(app.property("fontScale") or 1.0) if app else 1.0


def apply_font_size(app, percent):
    if not 80 <= percent <= 240:
        raise ValueError(tr("Rozmiar czcionki musi mieścić się w zakresie 8–24 pt."))
    if not app.property("baseStylesheet"):
        configure_application(app)
    base = app.property("baseStylesheet")
    if (
        app.property("appliedFontPercent") == percent
        and app.property("appliedFontBase") == base
        and abs(app.font().pointSizeF() - percent / 10) < 0.01
    ):
        return
    app.setProperty("fontScale", percent / 100)
    app.setStyleSheet(
        re.sub(
            r"font-size:\s*(\d+)px",
            lambda m: f"font-size: {max(1, round(int(m[1]) * percent / 100))}px",
            base,
        )
    )
    font = app.font()
    font.setPointSizeF(10 * percent / 100)
    app.setFont(font)
    app.setProperty("appliedFontPercent", percent)
    app.setProperty("appliedFontBase", base)


LIGHT_COLORS = {
    "#0b1623": "#f4f7fb",
    "#112233": "#ffffff",
    "#1a2b3d": "#ffffff",
    "#1e3347": "#edf2f8",
    "#24394d": "#bdcbdc",
    "#15475b": "#d8f2f7",
    "#153b4d": "#dff5f8",
    "#16465b": "#ccecf3",
    "#edf4ff": "#092235",
    "#a8bed5": "#50647a",
    "#7b8fa6": "#61758b",
    "#55e8ff": "#087f96",
    "#22d3ee": "#078fa8",
    "#06b6d4": "#087f96",
    "#3b82f6": "#1d4ed8",
    "#10b981": "#047857",
    "#ef4444": "#b91c1c",
    "#f59e0b": "#a65c00",
    "#3d5b74": "#a9c1d4",
    "#062536": "#062536",
}


def is_light():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    return bool(app and app.property("uiTheme") == "light")


def display_color(color):
    return LIGHT_COLORS.get(color.lower(), color) if is_light() else color


def apply_theme(app, name):
    if name not in ("dark", "light"):
        raise ValueError(tr("Wybierz poprawny motyw."))
    if not app.property("baseStylesheet"):
        configure_application(app)
    if name == "dark" and app.property("uiTheme") == "dark":
        return
    dark = app.property("darkStylesheet") or app.property("baseStylesheet")
    app.setProperty("darkStylesheet", dark)
    app.setProperty("uiTheme", name)

    def translate(style):
        translated = re.sub(r"#[0-9a-fA-F]{6}", lambda match: display_color(match[0]), style)
        return (
            translated.replace("selection-color: #ffffff", "selection-color: #092235").replace(
                "/chevron-down.svg", "/chevron-down-light.svg"
            )
            if name == "light"
            else translated
        )

    extra = BRAND_CONTROL_STYLES
    app.setProperty("baseStylesheet", translate(dark) + extra)
    palette = app.palette()
    for role, color in (
        (QPalette.ColorRole.Window, BACKGROUND),
        (QPalette.ColorRole.Base, "#112233"),
        (QPalette.ColorRole.AlternateBase, "#1a2b3d"),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Button, "#1a2b3d"),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.Highlight, "#16465b"),
        (QPalette.ColorRole.HighlightedText, TEXT),
    ):
        palette.setColor(role, QColor(display_color(color)))
    app.setPalette(palette)
    for widget in app.allWidgets():
        if widget.property("preserveColors"):
            continue
        current = widget.styleSheet()
        if current != widget.property("lastThemeStyle"):
            widget.setProperty("rawThemeStyle", current)
        raw = widget.property("rawThemeStyle") or ""
        rendered = translate(raw)
        if current != rendered:
            widget.setStyleSheet(rendered)
        widget.setProperty("lastThemeStyle", rendered)
        if widget.property("navGlyph"):
            from home_finance_cockpit.ui.components import icon

            widget.setIcon(icon(widget.property("navGlyph"), ACCENT))
        elif widget.property("themeIcon"):
            from home_finance_cockpit.ui.components import icon

            widget.setIcon(
                icon(
                    widget.property("themeIcon"),
                    INK
                    if widget.property("role") == "primary"
                    else RED
                    if widget.property("role") == "danger"
                    else ACCENT,
                )
            )
        widget.update()
    apply_font_size(app, round(font_scale() * 100))


def style_figure(figure):
    """Style UI figures locally, without altering the PDF renderer's settings."""
    figure.set_facecolor(display_color(SURFACE))
    for ax in figure.axes:
        ax.set_facecolor(display_color(SURFACE))
        ax.tick_params(
            colors=display_color(MUTED),
            labelsize=9 * density() * font_scale(),
            length=0,
            pad=5 * density(),
        )
        ax.xaxis.label.set_color(display_color(MUTED))
        ax.yaxis.label.set_color(display_color(MUTED))
        ax.xaxis.get_offset_text().set_color(display_color(MUTED))
        ax.yaxis.get_offset_text().set_color(display_color(MUTED))
        ax.title.set_color(display_color(TEXT))
        ax.title.set_fontsize(max(11, 13 * density()) * font_scale())
        ax.xaxis.label.set_fontsize(9 * density() * font_scale())
        ax.yaxis.label.set_fontsize(9 * density() * font_scale())
        ax.title.set_fontweight("semibold")
        for title in (ax._left_title, ax._right_title):
            title.set_color(display_color(TEXT))
            title.set_fontsize(max(11, 13 * density()) * font_scale())
            title.set_fontweight("semibold")
        for spine in ax.spines.values():
            spine.set_color("#24394d")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for line in ax.get_xgridlines() + ax.get_ygridlines():
            line.set_color("#24394d")
            line.set_alpha(0.3)
        for text in ax.texts:
            text.set_color(display_color(getattr(text, "_semantic_color", TEXT)))
            text.set_fontsize(9 * density() * font_scale())
        legend = ax.get_legend()
        if legend is not None:
            legend.get_frame().set_facecolor(display_color(SURFACE))
            legend.get_frame().set_edgecolor("#24394d")
            for text in legend.get_texts():
                text.set_color(display_color(MUTED))
                text.set_fontsize(8 * density() * font_scale())
