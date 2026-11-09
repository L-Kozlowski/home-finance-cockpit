"""Raster derivatives of the shipped SVG logo and UI icons for headless PDF workers."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QByteArray, QRectF
from PyQt6.QtGui import QFontDatabase, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.identity import BRAND_ASSETS
from home_finance_cockpit.ui.components import PATHS


def build():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    target = BRAND_ASSETS / "reports"
    target.mkdir(exist_ok=True)
    sources = [("wordmark", str(BRAND_ASSETS / "wordmark-ui-dark.svg"), 1600, 380)]
    for key, path in PATHS.items():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            'stroke="#ffffff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
            + path
            + "</svg>"
        )
        sources.append((key, QByteArray(svg.encode()), 144, 144))
    for key, source, width, height in sources:
        renderer = QSvgRenderer(source)
        assert renderer.isValid()
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter, QRectF(0, 0, width, height))
        painter.end()
        assert image.save(str(target / f"{key}.png"))
    return app


if __name__ == "__main__":
    build()
