"""Content density in Qt logical pixels, on top of native monitor DPI scaling."""

from PyQt6.QtGui import QGuiApplication


def screen_density(width, height):
    """Keep the desktop composition usable on a full-HD screen at 125–150% DPI."""
    return max(0.75, min(1.0, width / 1600, height / 1000))


def density():
    app = QGuiApplication.instance()
    return float(app.property("contentDensity") or 1.0) if app else 1.0


def px(value):
    return round(value * density())
