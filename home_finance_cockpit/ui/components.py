"""Small desktop building blocks for the personal finance workspace."""

from html import escape

from PyQt6.QtCore import QByteArray, QRect, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QFrame, QVBoxLayout

from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.text_selection import DragSelectableLabel
from home_finance_cockpit.ui.theme import ACCENT, MUTED

PATHS = {
    "close": '<path d="m6 6 12 12M6 18 18 6"/>',
    "minus": '<path d="M4 12h16"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 10v7M12 6v1"/>',
    "check": '<path d="m4 12 5 5L20 6"/>',
    "chevron_down": '<path d="m5 9 7 7 7-7"/>',
    "folder": '<path d="M3 6h7l2 3h9v12H3zM3 6V3h7l2 3h9v3"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6m10-6v6M3 10h18M7 14h2m3 0h2m3 0h1M7 18h2m3 0h2"/>',
    "file": '<path d="M5 2h9l5 5v15H5zM14 2v6h5M8 12h8M8 16h8"/>',
    "upload": '<path d="M12 16V3m-4 4 4-4 4 4M4 15v6h16v-6"/>',
    "play": '<path d="m8 4 12 8-12 8z"/>',
    "clothes": '<path d="m8 3-6 5 4 4 2-2v11h8V10l2 2 4-4-6-5c-1 4-7 4-8 0z"/>',
    "phone": '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 18h4"/>',
    "internet": '<path d="M2 7c6-6 14-6 20 0M5 11c4-4 10-4 14 0M8 15c2-2 6-2 8 0"/><circle cx="12" cy="19" r="1"/>',
    "power": '<path d="M13 2 4 14h7l-1 8 10-13h-8z"/>',
    "water": '<path d="M12 2s-8 9-8 13a8 8 0 0 0 16 0c0-4-8-13-8-13zM8 15c0 3 2 4 4 4"/>',
    "tools": '<path d="m14 3-3 3 2 5 5 2 3-3c3 7-4 10-8 6L5 23l-4-4 8-8C5 7 8 0 14 3z"/>',
    "restaurant": '<path d="M4 3v6h6V3M7 3v18M18 3c-4 3-4 9 0 9V3v18"/>',
    "fuel": '<path d="M3 21V4h11v17M2 21h13M5 7h7v5H5zM14 9h3v8c0 4 4 4 4 0V7l-3-3"/>',
    "train": '<rect x="5" y="2" width="14" height="17" rx="3"/><path d="M5 11h14M12 2v9M7 22l2-3m8 3-2-3M8 15h1m6 0h1"/>',
    "bike": '<circle cx="5" cy="17" r="4"/><circle cx="19" cy="17" r="4"/><path d="m5 17 5-9 4 9H5m9 0 3-12h3M8 5h4"/>',
    "plane": '<path d="m2 14 8-4 3-8h2l-1 8 8 4v2l-9-2-3 7H8l1-7-7 2z"/>',
    "hotel": '<path d="M3 4v17M3 15h18v6M3 12h18v6M6 9h4v3H6zM12 12V7h6l3 5"/>',
    "laptop": '<path d="M4 3h16v13H4zM1 20l3-4h16l3 4z"/>',
    "camera": '<path d="M3 7h4l2-4h6l2 4h4v14H3z"/><circle cx="12" cy="13" r="4"/>',
    "book": '<path d="M12 5C8 2 4 2 2 3v16c4-1 7 0 10 2 3-2 6-3 10-2V3c-2-1-6-1-10 2v16"/>',
    "child": '<circle cx="12" cy="4" r="2"/><path d="M5 9h14M12 7v8m0 0-5 7m5-7 5 7"/>',
    "beauty": '<path d="M8 22V10h8v12zM9 10V4l6-2v8M7 15h10"/>',
    "garden": '<path d="M12 22V9M12 14C2 16 1 7 3 5c6 0 9 4 9 9M12 10C11 2 17 0 21 2c0 6-3 9-9 8"/>',
    "charity": '<path d="M3 16h4l3 3h7l4-4M3 21h4M12 12 6 6c-3-6 5-6 6-2 1-4 9-4 6 2z"/>',
    "tax": '<path d="M5 2h14v20l-3-2-4 2-4-2-3 2zM8 6h8M8 10h8M8 14h5"/>',
    "back": '<path d="m14 5-7 7 7 7M7 12h14"/>',
    "forward": '<path d="m10 5 7 7-7 7M17 12H3"/>',
    "food": '<path d="M5 3v7m3-7v7m-6-7v7h6M5 10v11M16 3v18m0-18c6 4 6 10 0 10"/>',
    "cart": '<path d="M2 3h3l3 13h12l2-9H6M9 20h1m8 0h1"/>',
    "coffee": '<path d="M4 7h13v9c0 6-13 6-13 0zM17 8h2c5 0 5 7-2 7M7 2v2m5-2v2"/>',
    "car": '<path d="m3 10 3-6h12l3 6v9H3zM3 10h18M6 14h2m8 0h2M6 19v2m12-2v2"/>',
    "health": '<path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6z"/>',
    "education": '<path d="m2 8 10-5 10 5-10 5zM6 10v7c4 4 8 4 12 0v-7M22 8v10"/>',
    "sport": '<path d="m7 5 12 12M4 8l4-4m8 16 4-4M2 6l4-4m12 20 4-4M5 11l6-6m2 14 6-6"/>',
    "music": '<path d="M9 17V5l12-2v12M9 9l12-2"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="18" cy="16" rx="3" ry="3"/>',
    "pet": '<ellipse cx="12" cy="16" rx="6" ry="5"/><circle cx="4" cy="10" r="2"/><circle cx="9" cy="5" r="2"/><circle cx="15" cy="5" r="2"/><circle cx="20" cy="10" r="2"/>',
    "trash": '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
    "keyboard": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M5 9h1m3 0h1m3 0h1m3 0h1M5 12h1m3 0h1m3 0h1m3 0h1M7 16h10"/>',
    "alert": '<path d="m12 3 10 18H2zM12 9v5M12 17v1"/>',
    "undo": '<path d="M9 4 3 10l6 6M3 10h11a7 7 0 0 1 7 7v3"/>',
    "report": '<path d="M5 3h10l4 4v14H5zM14 3v5h5M8 17v-3m4 3v-6m4 6v-4M8 10h2"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "edit": '<path d="m4 16 12-12 4 4L8 20H4zM13 7l4 4"/>',
    "search": '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
    "overview": '<path d="M3 13h7V3H3zM14 21h7V11h-7zM3 21h7v-4H3zM14 7h7V3h-7z"/>',
    "transactions": '<path d="M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4"/>',
    "wallet": '<rect x="3" y="6" width="18" height="15" rx="2"/><path d="m4 6 13-3v3M21 12h-6v4h6"/>',
    "chart": '<path d="M3 3v18h18M6 15l5-6 4 3 6-8"/>',
    "import": '<path d="M12 3v12m-4-4 4 4 4-4M4 15v6h16v-6"/>',
    "tag": '<path d="M3 3h8l10 10-8 8L3 11z"/><circle cx="7.5" cy="7.5" r="1"/>',
    "settings": '<path d="M10 3h4l.6 2.4 1.7 1 2.4-.7 2 3.5-1.8 1.7v2.2l1.8 1.7-2 3.5-2.4-.7-1.7 1L14 21h-4l-.6-2.4-1.7-1-2.4.7-2-3.5 1.8-1.7v-2.2L3.3 9.2l2-3.5 2.4.7 1.7-1z"/><circle cx="12" cy="12" r="3"/>',
    "plus": '<path d="M12 4v16M4 12h16"/>',
    "target": '<circle cx="11" cy="13" r="8"/><circle cx="11" cy="13" r="4"/><path d="m11 13 9-10m-4 0h4v4"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
    "refresh": '<path d="M20 7a9 9 0 1 0 1 9M20 3v5h-5"/>',
    "income": '<circle cx="12" cy="12" r="9"/><path d="M12 17V7m-4 4 4-4 4 4"/>',
    "expense": '<circle cx="12" cy="12" r="9"/><path d="M12 7v10m-4-4 4 4 4-4"/>',
    "filter": '<path d="M3 4h18l-7 8v7l-4 2V12z"/>',
    "bank": '<path d="m2 8 10-5 10 5zM3 21h18M5 10v8m7-8v8m7-8v8"/>',
    "card": '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="M2 9h20M6 15h5"/>',
    "cash": '<rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M5 8h1m12 8h1"/>',
    "savings": '<path d="M5 9h11l4 4-2 5h-2v3h-2v-3H8v3H6v-3l-3-4V9l3 2M10 6h4"/><circle cx="15" cy="12" r=".7"/>',
    "home": '<path d="m2 11 10-8 10 8M5 9v12h14V9M9 21v-7h6v7"/>',
    "travel": '<path d="m3 13 7-3 3-7 2 1-1 6 6 3v2l-7-1-3 6H8l1-7-6 2z"/>',
    "business": '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V3h8v4M3 12h18M10 12v3h4v-3"/>',
    "gift": '<path d="M3 10h18v4H3zM5 14v7h14v-7M12 10v11"/><path d="M12 10C2 10 4 1 9 4l3 6c10 0 8-9 3-6z"/>',
    "shield": '<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6z"/><path d="m8 12 3 3 5-6"/>',
}


def icon(name, color=ACCENT, size=24):
    from home_finance_cockpit.ui.theme import display_color

    color = display_color(color)
    from home_finance_cockpit.domain.brand_palette import ACCENT_DARK, ACCENT_LIGHT

    stroke = "url(#accent)" if color.lower() == ACCENT.lower() else color
    gradient = f'<defs><linearGradient id="accent" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ACCENT_LIGHT}"/><stop offset="0.5" stop-color="{ACCENT}"/><stop offset="1" stop-color="{ACCENT_DARK}"/></linearGradient></defs>'
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{stroke}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        + gradient
        + PATHS[name]
        + "</svg>"
    )
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def label(text, role="muted"):
    widget = DragSelectableLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setProperty("role", role)
    widget.setWordWrap(True)
    return widget


def panel(title=None):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(px(16), px(12), px(16), px(12))
    layout.setSpacing(px(8))
    if title:
        layout.addWidget(label(tr(title), "section"))
    return frame, layout


class MetricCard(DragSelectableLabel):
    def __init__(self, color=ACCENT, glyph=None):
        super().__init__()
        self.color = color
        self.glyph_name = glyph
        self.glyph = icon(glyph, color) if glyph else None
        if self.glyph is not None:
            self.setContentsMargins(px(34), 0, 0, 0)
        self.setObjectName("metricCard")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setMargin(px(12))
        self.setMinimumHeight(px(80))
        self.setWordWrap(True)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.glyph is not None:
            painter = QPainter(self)
            icon(self.glyph_name, self.color).paint(
                painter, QRect(px(12), (self.height() - px(26)) // 2, px(26), px(26))
            )
            painter.end()

    def setText(self, text):
        from home_finance_cockpit.ui.theme import display_color, font_scale

        parts = text.split("\n", 1)
        if len(parts) == 1:
            return super().setText(escape(text))
        title, value = map(escape, parts)
        super().setText(
            tr(
                '<span style="color:{v0};font-size:{v1}px">{v2}</span><br><span style="color:{v3};font-size:{v4}px;font-weight:600">{v5}</span>',
                v0=display_color(MUTED),
                v1=round(px(12) * font_scale()),
                v2=tr(title),
                v3=display_color(self.color),
                v4=round(px(24) * font_scale()),
                v5=value,
            )
        )
