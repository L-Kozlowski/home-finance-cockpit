"""Native icon packaging and usable light/dark brand variants."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import struct
import unittest

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.domain import brand_palette as brand
from home_finance_cockpit.identity import BRAND_ASSETS
from home_finance_cockpit.ui.branding import BrandLogo, application_icon
from home_finance_cockpit.ui.theme import apply_theme, configure_application


class BrandThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        apply_theme(self.app, "dark")
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_windows_icon_embeds_supplied_pngs_and_supports_high_dpi(self):
        data = (BRAND_ASSETS / "app-icon.ico").read_bytes()
        self.assertEqual(struct.unpack_from("<HHH", data), (0, 1, 5))
        for index, size in enumerate((16, 32, 64, 128, 256)):
            entry = struct.unpack_from("<BBBBHHII", data, 6 + index * 16)
            length, offset = entry[-2:]
            self.assertEqual(
                data[offset : offset + length], (BRAND_ASSETS / f"app-icon-{size}.png").read_bytes()
            )
        native = application_icon()
        self.assertFalse(native.isNull())
        self.assertTrue(
            {16, 32, 64, 128, 256, 512, 1024} <= {s.width() for s in native.availableSizes()}
        )

    def test_brand_wordmark_switches_to_real_light_variant(self):
        configure_application(self.app)
        logo = BrandLogo()
        logo.resize(300, 70)
        logo.show()
        self.app.processEvents()
        dark = logo.grab().toImage()
        apply_theme(self.app, "light")
        self.app.processEvents()
        light = logo.grab().toImage()
        self.assertTrue(logo.renderer.isValid())
        self.assertTrue(logo.light)
        self.assertNotEqual(light, dark)
        apply_theme(self.app, "dark")
        self.app.processEvents()
        self.assertFalse(logo.light)
        logo.close()
        logo.deleteLater()

    def test_primary_button_ink_is_legible_on_every_gradient_stop(self):
        def luminance(code):
            color = QColor(code)
            values = []
            for c in (color.redF(), color.greenF(), color.blueF()):
                values.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
            return sum(v * w for v, w in zip(values, (0.2126, 0.7152, 0.0722)))

        ink = luminance(brand.INK)
        for background in (brand.ACCENT_LIGHT, brand.ACCENT, brand.ACCENT_DARK):
            self.assertGreaterEqual((luminance(background) + 0.05) / (ink + 0.05), 4.5)
