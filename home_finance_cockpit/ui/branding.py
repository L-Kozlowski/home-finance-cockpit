"""Supplied vector wordmark and native multi-resolution application icon."""

import sys

from PyQt6.QtCore import QRectF, QSize
from PyQt6.QtGui import QIcon, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QSizePolicy, QWidget

from home_finance_cockpit.identity import APP_NAME, BRAND_ASSETS, WINDOWS_APP_ID
from home_finance_cockpit.ui.scaling import px


def configure_windows_identity():
    """Give this Python process its own Windows taskbar identity before Qt starts."""
    if sys.platform == "win32":
        import ctypes

        set_identity = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_identity.argtypes = [ctypes.c_wchar_p]
        set_identity.restype = ctypes.c_long
        set_identity(WINDOWS_APP_ID)


def application_icon():
    result = QIcon(str(BRAND_ASSETS / "app-icon.ico"))
    for size in (16, 32, 64, 128, 256, 512, 1024):
        result.addFile(str(BRAND_ASSETS / f"app-icon-{size}.png"), QSize(size, size))
    return result


def configure_branding(app):
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(application_icon())


class BrandLogo(QWidget):
    """Draw the existing wordmark proportionally, including fractional monitor DPI."""

    def __init__(self, parent=None, *, height=56):
        super().__init__(parent)
        self.renderer = QSvgRenderer(str(BRAND_ASSETS / "wordmark-ui-dark.svg"), self)
        self.light = False
        self.setAccessibleName(APP_NAME)
        self.setToolTip(APP_NAME)
        self.setMinimumWidth(0)
        self.setFixedHeight(px(height))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        box = self.renderer.viewBoxF()
        return QSize(round(self.height() * box.width() / box.height()), self.height())

    def paintEvent(self, event):
        super().paintEvent(event)
        from home_finance_cockpit.ui.theme import is_light

        light = is_light()
        if light != self.light:
            self.renderer.load(
                str(BRAND_ASSETS / f"wordmark-ui-{'light' if light else 'dark'}.svg")
            )
            self.light = light
        box = self.renderer.viewBoxF()
        scale = min(self.width() / box.width(), self.height() / box.height())
        width, height = box.width() * scale, box.height() * scale
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.renderer.render(painter, QRectF(0, (self.height() - height) / 2, width, height))
        painter.end()
