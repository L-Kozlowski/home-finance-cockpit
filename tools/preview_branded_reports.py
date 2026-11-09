"""Three independent, branded PDF proposals. Production reports remain unchanged.

Sources: identity.py, brand_palette.py, the actual SVG wordmark and components.PATHS;
layout references: ui-concepts/analyses and implemented/cyan (see output README).
All calculations use the existing report snapshot of a disposable demo DB copy.
"""

import calendar
import json
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from io import BytesIO
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from pypdf import PdfReader
from PyQt6.QtCore import QByteArray, QRectF, QSize
from PyQt6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from home_finance_cockpit.domain import brand_palette as B
from home_finance_cockpit.identity import APP_NAME, BRAND_ASSETS
from home_finance_cockpit.reports.data import ReportOptions, category_comparison, snapshot
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.components import PATHS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/ui-concepts/report-pdfs-v2"
ASSETS = OUT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)
APP = QApplication.instance() or QApplication([])
for name, filename in (("UI", "segoeui.ttf"), ("UIBold", "seguisb.ttf")):
    path = Path("C:/Windows/Fonts") / filename
    pdfmetrics.registerFont(TTFont(name, str(path)))
    QFontDatabase.addApplicationFont(str(path))
font_manager.fontManager.addfont("C:/Windows/Fonts/segoeui.ttf")
matplotlib.rcParams.update({"font.family": "Segoe UI", "font.size": 9})

LABELS = {
    "Housing": "Mieszkanie",
    "Food": "Żywność",
    "Occasional": "Zakupy",
    "Medical": "Zdrowie",
    "Mandatory": "Opłaty stałe",
    "FreeTime": "Rozrywka",
    "AccountFunding": "Zasilenie konta",
    "TopUp": "Doładowanie",
    "Salary": "Wynagrodzenie",
    "Activities": "Aktywności",
    "BarAndFood": "Restauracje",
    "Car": "Samochód",
    "Catering": "Catering",
    "Cosmetics": "Kosmetyki",
    "Grocery": "Spożywcze",
    "Home": "Dom",
    "Insurance": "Ubezpieczenia",
    "Internet": "Internet",
    "No subcategory": "Bez podkategorii",
    "OnlineShopping": "Zakupy online",
    "Pharmacy": "Apteka",
    "Rail": "Kolej",
    "Rent": "Czynsz",
    "Subscriptions": "Subskrypcje",
    "Utilities": "Media",
}


def name(value):
    return LABELS.get(value, value) or "—"


def money(value, signed=False):
    if value is None:
        return "—"
    prefix = "+" if signed and value > 0 else ""
    return prefix + f"{value / 100:,.2f}".replace(",", " ").replace(".", ",")


def pct(value, signed=False):
    if value is None:
        return "—"
    return ("+" if signed and value > 0 else "") + f"{float(value):.1f}%".replace(".", ",")


def raster_svg(source, target, width=1600, height=380):
    renderer = QSvgRenderer(source)
    assert renderer.isValid()
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    assert image.save(str(target))


LOGO = ASSETS / "wordmark.png"
raster_svg(str(BRAND_ASSETS / "wordmark-ui-dark.svg"), LOGO)


def icon_asset(key, color=B.ACCENT):
    key = key if key in PATHS else "tag"
    target = ASSETS / f"{key}-{color.lstrip('#')}.png"
    if not target.exists():
        source = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="1.7" '
            'stroke-linecap="round" stroke-linejoin="round">' + PATHS[key] + "</svg>"
        )
        raster_svg(QByteArray(source.encode()), target, 144, 144)
    return target


with tempfile.TemporaryDirectory() as folder:
    copied = Path(folder) / "demo.db"
    shutil.copy2(ROOT / "example/database/home_finance_demo.db", copied)
    db = Database.open_existing(copied)
    DATA = snapshot(db, ReportOptions(currency="PLN", year=2026, months=("2026-10",), annual=False))
    CATEGORY_ICONS = {c["name"]: c["icon_name"] for c in db.categories()}
    db.close()

S = DATA["summaries"]["2026-10"]
PREV = DATA["summaries"]["2026-09"]
CATS = sorted(S["categories"], key=lambda c: -S["categories"][c])
COLORS = {
    c: DATA["category_colors"].get(c) or B.CHART_COLORS[i % len(B.CHART_COLORS)]
    for i, c in enumerate(CATS)
}
EXPENSES = [r for r in S["rows"] if r["amount_minor"] < 0]
COUNTS = Counter(r["category"] for r in EXPENSES)
DAILY = [
    sum(-r["amount_minor"] for r in EXPENSES if int(r["date"][-2:]) == d) for d in range(1, 32)
]
WEEKDAY = [
    sum(-r["amount_minor"] for r in EXPENSES if date.fromisoformat(r["date"]).weekday() == d)
    for d in range(7)
]
MERCHANTS = defaultdict(int)
for row in EXPENSES:
    MERCHANTS[row["from_to"].strip() or row["description"].strip() or "Brak opisu"] -= row[
        "amount_minor"
    ]
assert sum(DAILY) == sum(WEEKDAY) == sum(S["categories"].values()) == S["gross_expenses"]
assert S["net"] == S["inflows"] - S["gross_expenses"]


def chart_image(kind, width, height):
    """Render real snapshot data in the actual application's palette."""
    fig = Figure(figsize=(width / 72, height / 72), dpi=170, layout="constrained")
    FigureCanvasAgg(fig)
    fig.patch.set_alpha(0)
    ax = fig.add_subplot(111)
    ax.set_facecolor("none")
    ax.tick_params(colors=B.MUTED, length=0, labelsize=8, pad=7)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)
    if kind == "daily":
        ax.bar(range(1, 32), [v / 100 for v in DAILY], color=B.ACCENT, width=0.64, zorder=3)
        ax.set_xticks([1, 5, 10, 15, 20, 25, 31])
        ax.grid(axis="y", color=B.BORDER, linewidth=0.6)
    elif kind == "cumulative":
        values = []
        total = 0
        for v in DAILY:
            total += v
            values.append(total / 100)
        ax.plot(range(1, 32), values, color=B.ACCENT, linewidth=2.2, zorder=3)
        ax.fill_between(range(1, 32), values, color=B.ACCENT, alpha=0.1)
        ax.set_xticks([1, 10, 20, 31])
        ax.grid(color=B.BORDER, linewidth=0.6)
        ax.scatter([31], [values[-1]], color=B.ACCENT, s=18, zorder=4)
    elif kind == "weekday":
        ax.bar(
            ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Ndz"],
            [v / 100 for v in WEEKDAY],
            color=[B.ACCENT if v == max(WEEKDAY) else B.INFO for v in WEEKDAY],
            width=0.55,
            zorder=3,
        )
        ax.grid(axis="y", color=B.BORDER, linewidth=0.6)
    elif kind == "change":
        comparison = list(reversed(category_comparison(DATA, "2026-10")))
        values = [r[3] / 100 for r in comparison]
        ax.barh(
            [name(r[0]) for r in comparison],
            values,
            color=[B.ERROR if v > 0 else B.SUCCESS if v < 0 else B.DISABLED for v in values],
            height=0.5,
            zorder=3,
        )
        ax.axvline(0, color=B.MUTED, linewidth=0.7)
        ax.grid(axis="x", color=B.BORDER, linewidth=0.6)
    elif kind == "merchants":
        pairs = list(reversed(sorted(MERCHANTS.items(), key=lambda p: -p[1])[:5]))
        labels = [(key if len(key) < 31 else key[:28] + "…") for key, v in pairs]
        ax.barh(labels, [v / 100 for key, v in pairs], color=B.ACCENT, height=0.48, zorder=3)
        ax.grid(axis="x", color=B.BORDER, linewidth=0.6)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, p: f"{v:,.0f}".replace(",", " "))
    ) if kind not in ("change", "merchants") else None
    ax.xaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, p: f"{v:,.0f}".replace(",", " "))
    ) if kind in ("change", "merchants") else None
    stream = BytesIO()
    fig.savefig(stream, format="png", dpi=170, transparent=True)
    stream.seek(0)
    return ImageReader(stream)


class Report:
    def __init__(self, variant):
        self.variant = variant
        self.w, self.h = landscape(A4) if variant == 2 else A4
        self.x = 170 if variant == 2 else 34 if variant == 1 else 44
        self.width = self.w - self.x - (30 if variant == 2 else self.x)
        self.bottom = self.h - 48
        self.page = 0
        self.section = 0
        self.audit = []
        self.filename = {
            1: "01-home-finance-cockpit.pdf",
            2: "02-home-finance-panorama.pdf",
            3: "03-home-finance-focus.pdf",
        }[variant]
        self.canvas = Canvas(str(OUT / self.filename), pagesize=(self.w, self.h), pageCompression=1)
        self.canvas.setTitle(f"{APP_NAME} — Raport miesięczny — październik 2026")
        self.canvas.setAuthor(APP_NAME)
        self.canvas.setSubject(
            "Wizualizacja raportu • syntetyczne dane demo • wydatki brutto • PLN"
        )

    def rect(self, x, y, w, h, fill=B.SURFACE, radius=8, stroke=None):
        c = self.canvas
        c.setFillColor(colors.HexColor(fill))
        if stroke:
            c.setStrokeColor(colors.HexColor(stroke))
            c.setLineWidth(0.6)
        c.roundRect(x, self.h - y - h, w, h, radius, fill=1, stroke=int(bool(stroke)))

    def text(self, x, y, text, size=9, color=B.TEXT, bold=False, align="left"):
        c = self.canvas
        c.setFillColor(colors.HexColor(color))
        c.setFont("UIBold" if bold else "UI", size)
        {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align](
            x, self.h - y, str(text)
        )

    def rule(self, x, y, w, color=B.BORDER):
        self.canvas.setStrokeColor(colors.HexColor(color))
        self.canvas.setLineWidth(0.6)
        self.canvas.line(x, self.h - y, x + w, self.h - y)

    def image(self, path, x, y, w, h):
        self.canvas.drawImage(
            str(path) if isinstance(path, Path) else path, x, self.h - y - h, w, h, mask="auto"
        )

    def glyph(self, key, x, y, size=16, color=B.ACCENT):
        self.image(icon_asset(key, color), x, y, size, size)

    def new_page(self, section, title, subtitle=None, continuation=False):
        if self.page:
            self.canvas.showPage()
        self.page += 1
        self.section = section
        bg = B.PANEL if self.variant == 3 else B.BACKGROUND
        self.rect(0, 0, self.w, self.h, bg, 0)
        if self.variant == 2:
            self.rect(0, 0, 148, self.h, B.PANEL, 0)
            self.image(LOGO, 18, 23, 115, 27.3)
            self.rule(18, 72, 112)
            self.text(18, 98, "RAPORT MIESIĘCZNY", 8, B.MUTED, True)
            self.text(18, 120, "Październik 2026", 12, bold=True)
            self.text(18, 141, "PLN • wszystkie portfele", 7.5, B.MUTED)
            sections = [
                "Podsumowanie",
                "Kategorie",
                "Porównanie",
                "W czasie",
                "Podkategorie",
                "Do przypisania",
                "Transakcje",
            ]
            for i, label in enumerate(sections, 1):
                y = 183 + (i - 1) * 39
                self.canvas.linkRect(
                    "Przejdź do sekcji: " + label,
                    f"section-start-{i}",
                    (10, self.h - y - 12, 138, self.h - y + 19),
                    relative=0,
                    thickness=0,
                )
                if i == section:
                    self.rect(10, y - 19, 128, 31, "#153b4d", 5)
                    self.rect(10, y - 16, 2, 25, B.ACCENT, 1)
                self.glyph(
                    ["overview", "tag", "chart", "chart", "tag", "alert", "transactions"][i - 1],
                    19,
                    y - 12,
                    13,
                    B.ACCENT if i == section else B.DISABLED,
                )
                self.text(40, y, label, 9, B.TEXT if i == section else B.MUTED, bold=i == section)
            self.text(18, self.h - 47, "Dane demonstracyjne", 7, B.MUTED)
            self.text(18, self.h - 31, "Wydatki brutto", 7, B.MUTED)
            self.text(self.x, 36, f"{section:02d} / 07", 9, B.ACCENT, True)
            self.text(self.w - 30, 36, "01–31.10.2026  •  PLN", 8, B.MUTED, align="right")
            self.text(self.x, 69, title + (" · cd." if continuation else ""), 23, bold=True)
            if subtitle:
                self.text(self.x, 89, subtitle, 8.5, B.MUTED)
            self.y = 106
        else:
            self.image(LOGO, self.x, 23, 165, 39.2)
            self.text(self.w - self.x, 37, "RAPORT MIESIĘCZNY", 8, B.MUTED, True, "right")
            self.text(self.w - self.x, 55, "PAŹDZIERNIK 2026 / PLN", 9, B.TEXT, False, "right")
            self.rule(self.x, 79, self.width)
            if self.variant == 1:
                self.rect(self.x, 97, 29, 26, "#153b4d", 5)
                self.text(self.x + 14.5, 115, f"{section:02d}", 10, B.ACCENT, True, "center")
                self.text(
                    self.x + 41, 117, title + (" · cd." if continuation else ""), 22, bold=True
                )
            else:
                self.rect(self.x, 98, 3, 31, B.ACCENT, 1)
                self.text(self.x + 14, 108, f"{section:02d} / RAPORT MIESIĘCZNY", 8, B.ACCENT, True)
                self.text(
                    self.x + 14, 133, title + (" · cd." if continuation else ""), 23, bold=True
                )
            sy = 139 if self.variant == 1 else 155
            if subtitle:
                self.text(self.x, sy, subtitle, 8.5, B.MUTED)
            self.y = 157 if self.variant == 1 else 173
        self.rule(self.x, self.h - 37, self.width)
        self.text(self.x, self.h - 23, APP_NAME, 7, B.MUTED)
        self.text(
            self.w - (30 if self.variant == 2 else self.x),
            self.h - 23,
            f"Dane demo  •  {self.page:02d}",
            7,
            B.MUTED,
            align="right",
        )
        self.audit.append({"page": self.page, "section": section, "title": title})
        self.canvas.bookmarkPage(f"section-{section}-{self.page}")
        if not continuation:
            self.canvas.bookmarkPage(f"section-start-{section}")
            self.canvas.addOutlineEntry(title, f"section-{section}-{self.page}", 0)

    def metric(self, x, y, w, h, title, value, detail, key, color=B.ACCENT, flat=False):
        if not flat:
            self.rect(x, y, w, h, B.SURFACE, 8, B.BORDER)
        self.glyph(key, x + 13, y + 13, 15, color)
        self.text(x + 36, y + 24, title, 8.5, B.MUTED)
        size = 20 if w > 180 else 17
        self.text(x + 13, y + 52, value, size, color, True)
        self.text(x + 13, y + h - 12, detail, 8, B.MUTED)

    def metrics(self, y):
        gap = 10
        w = (self.width - 2 * gap) / 3
        for i, (title, value, key, color) in enumerate(
            [
                ("Wpływy", S["inflows"], "income", B.SUCCESS),
                ("Wydatki brutto", S["gross_expenses"], "expense", B.ERROR),
                ("Przepływ netto", S["net"], "transactions", B.INFO),
            ]
        ):
            self.metric(
                self.x + i * (w + gap),
                y,
                w,
                84,
                title,
                money(value),
                "PLN",
                key,
                color,
                flat=self.variant == 3,
            )

    def panel_heading(self, x, y, title, unit=None):
        self.text(x + 14, y + 25, title, 11, bold=True)
        if unit:
            self.text(x + 14, y + 42, unit, 8, B.MUTED)

    def plot(self, kind, x, y, w, h, title, unit="PLN"):
        self.rect(
            x,
            y,
            w,
            h,
            B.SURFACE if self.variant != 3 else B.BACKGROUND,
            8,
            B.BORDER if self.variant != 3 else None,
        )
        self.panel_heading(x, y, title, unit)
        self.image(chart_image(kind, w - 20, h - 59), x + 10, y + 51, w - 20, h - 59)

    def ring(self, cx, cy, r):
        c = self.canvas
        start = 90
        for cat in CATS:
            span = S["categories"][cat] / S["expenses"] * 360
            c.setStrokeColor(colors.HexColor(COLORS[cat]))
            c.setLineWidth(r * 0.25)
            c.arc(
                cx - r,
                self.h - cy - r,
                cx + r,
                self.h - cy + r,
                startAng=start - 1,
                extent=-max(0, span - 2),
            )
            start -= span
        self.text(cx, cy - 13, "WYDATKI", 8, B.MUTED, True, "center")
        self.text(cx, cy + 11, money(S["expenses"]), 20 if r > 70 else 15, B.TEXT, True, "center")
        self.text(cx, cy + 31, "PLN", 8.5, B.MUTED, False, "center")

    def ranking(self, x, y, w, row_h=27, bars=False, counts=False):
        for i, cat in enumerate(CATS):
            yy = y + i * row_h
            self.glyph(CATEGORY_ICONS.get(cat, "tag"), x, yy - 11, 14, COLORS[cat])
            self.text(x + 22, yy, name(cat), 9)
            self.text(x + w, yy, money(S["categories"][cat]), 9, bold=True, align="right")
            if bars:
                self.rect(x + 22, yy + 5, w - 22, 3, B.BORDER, 1)
                self.rect(
                    x + 22,
                    yy + 5,
                    (w - 22) * S["categories"][cat] / max(S["categories"].values()),
                    3,
                    COLORS[cat],
                    1,
                )
            elif counts:
                self.text(
                    x + 22,
                    yy + 13,
                    f"{COUNTS[cat]} trans.  /  {pct(S['categories'][cat] * 100 / S['expenses'])}",
                    7.5,
                    B.MUTED,
                )

    def small_stat(self, x, y, w, title, value, detail=None, color=B.ACCENT):
        self.text(x, y, title, 8, B.MUTED)
        self.text(x, y + 24, value, 17, color, True)
        if detail:
            self.text(x, y + 40, detail, 7.5, B.MUTED)

    def overview(self):
        self.new_page(1, "Podsumowanie", "Wszystkie portfele PLN • 01–31 października 2026")
        y = self.y
        if self.variant == 1:
            self.metrics(y)
            cy = y + 101
            height = 292
            self.rect(self.x, cy, self.width, height, B.SURFACE, 8, B.BORDER)
            self.panel_heading(self.x, cy, "Struktura wydatków")
            self.ring(self.x + 116, cy + 159, 83)
            self.ranking(self.x + 235, cy + 62, self.width - 253, row_h=28)
            cy += height + 23
            self.small_stat(
                self.x,
                cy,
                160,
                "TRANSAKCJE WYDATKOWE",
                str(S["expense_count"]),
                "wyłącznie kwoty ujemne",
            )
            self.small_stat(
                self.x + 181,
                cy,
                160,
                "ŚREDNI WYDATEK",
                money(S["gross_expenses"] / S["expense_count"]) + " PLN",
            )
            self.small_stat(
                self.x + 363,
                cy,
                160,
                "ZMIANA M/M",
                money(S["change"], True) + " PLN",
                pct(S["change_percent"], True),
                B.ERROR,
            )
            self.plot("cumulative", self.x, cy + 57, self.width, 151, "Wydatki narastająco")
        elif self.variant == 2:
            self.metrics(y)
            cy = y + 101
            h = self.bottom - cy - 4
            self.rect(self.x, cy, 239, h, B.SURFACE, 8, B.BORDER)
            self.panel_heading(self.x, cy, "Struktura wydatków")
            self.ring(self.x + 119.5, cy + 134, 73)
            self.rule(self.x + 17, cy + 231, 205)
            self.text(
                self.x + 17, cy + 254, f"{S['expense_count']} transakcji wydatkowych", 10, bold=True
            )
            self.text(
                self.x + 17,
                cy + 275,
                "Średnia: " + money(S["gross_expenses"] / S["expense_count"]) + " PLN",
                9,
                B.MUTED,
            )
            self.text(
                self.x + 17, cy + 298, "Zmiana m/m: " + pct(S["change_percent"], True), 9, B.ERROR
            )
            rx = self.x + 254
            rw = self.width - 254
            self.rect(rx, cy, rw, h, B.SURFACE, 8, B.BORDER)
            self.panel_heading(rx, cy, "Kategorie · kwoty i udziały")
            self.ranking(rx + 16, cy + 65, rw - 32, row_h=31, counts=True)
        else:
            self.rect(self.x, y, self.width, 118, B.BACKGROUND, 8)
            self.glyph("expense", self.x + 17, y + 18, 21, B.ACCENT)
            self.text(self.x + 49, y + 32, "WYDATKI BRUTTO", 9, B.MUTED, True)
            self.text(self.x + 17, y + 74, money(S["expenses"]) + " PLN", 32, B.ACCENT, True)
            self.text(
                self.x + 17, y + 99, f"{S['expense_count']} transakcji wydatkowych", 9, B.MUTED
            )
            self.small_stat(
                self.x + 325,
                y + 25,
                150,
                "ZMIANA WZGLĘDEM WRZEŚNIA",
                pct(S["change_percent"], True),
                money(S["change"], True) + " PLN",
                B.ERROR,
            )
            y += 145
            self.small_stat(self.x, y, 240, "WPŁYWY", money(S["inflows"]) + " PLN", color=B.SUCCESS)
            self.small_stat(
                self.x + 270, y, 240, "PRZEPŁYW NETTO", money(S["net"]) + " PLN", color=B.INFO
            )
            y += 75
            self.text(self.x, y, "Kategorie wydatków", 14, bold=True)
            self.rule(self.x, y + 13, self.width)
            self.ranking(self.x, y + 43, 285, row_h=27)
            self.ring(self.x + 402, y + 118, 68)
            self.plot("cumulative", self.x, y + 257, self.width, 145, "Wydatki narastająco")

    def table(
        self,
        headers,
        rows,
        widths,
        title,
        section,
        align_right=(),
        category_column=None,
        font=9,
        base_h=27,
    ):
        widths = [v * self.width / sum(widths) for v in widths]

        def head():
            self.rect(self.x, self.y, self.width, 31, B.INPUT, 5)
            xx = self.x
            for col, (h, w) in enumerate(zip(headers, widths)):
                lines = simpleSplit(h, "UIBold", 8.3, w - 18)
                for j, t in enumerate(lines):
                    self.text(
                        xx + w - 9 if col in align_right else xx + 9,
                        self.y + 12 + j * 10,
                        t,
                        8.3,
                        B.MUTED,
                        True,
                        "right" if col in align_right else "left",
                    )
                xx += w
            self.y += 34

        head()
        for index, row in enumerate(rows):
            wrapped = []
            for col, (v, w) in enumerate(zip(row, widths)):
                inset = 22 if col == category_column else 0
                wrapped.append(simpleSplit(str(v), "UI", font, w - 18 - inset) or ["—"])
            rh = max(base_h, max(len(lines) for lines in wrapped) * (font + 3) + 12)
            if self.y + rh > self.bottom:
                self.new_page(section, title, continuation=True)
                head()
            self.rect(self.x, self.y, self.width, rh, B.PANEL if index % 2 == 0 else B.SURFACE, 0)
            xx = self.x
            for col, (lines, w) in enumerate(zip(wrapped, widths)):
                offset = 0
                if col == category_column:
                    original = next((c for c in CATS if name(c) == row[col]), None)
                    if original is not None:
                        self.glyph(
                            CATEGORY_ICONS.get(original, "tag"),
                            xx + 9,
                            self.y + (rh - 13) / 2,
                            13,
                            COLORS[original],
                        )
                        offset = 21
                color = B.TEXT
                if section == 3 and col in (3, 4):
                    raw = str(row[col])
                    color = (
                        B.ERROR
                        if raw.startswith("+")
                        else B.SUCCESS
                        if raw.startswith("-")
                        else B.MUTED
                    )
                if section == 7 and col == len(row) - 1:
                    color = B.ERROR if str(row[col]).startswith("-") else B.SUCCESS
                for j, t in enumerate(lines):
                    yy = self.y + (rh - len(lines) * (font + 3)) / 2 + font + j * (font + 3)
                    self.text(
                        xx + w - 9 if col in align_right else xx + 9 + offset,
                        yy,
                        t,
                        font,
                        color,
                        False,
                        "right" if col in align_right else "left",
                    )
                xx += w
            self.y += rh
            assert self.y <= self.bottom + 0.1
        self.y += 15

    def categories(self):
        self.new_page(
            2, "Kategorie wydatków", "Wydatki brutto • liczba transakcji • udział w sumie"
        )
        rows = [
            (
                name(c),
                COUNTS[c],
                money(S["categories"][c]),
                pct(S["categories"][c] * 100 / S["expenses"]),
            )
            for c in CATS
        ]
        self.table(
            ["Kategoria", "Transakcje", "Kwota PLN", "Udział"],
            rows,
            [2.5, 1, 1.3, 1],
            "Kategorie wydatków",
            2,
            (1, 2, 3),
            0,
            base_h=31,
        )
        remaining = self.bottom - self.y
        if self.variant == 2:
            self.rect(self.x, self.y, self.width, remaining - 4, B.SURFACE, 8)
            self.text(self.x + 15, self.y + 25, "Największa kategoria", 10, B.MUTED)
            self.text(self.x + 15, self.y + 55, name(CATS[0]), 22, bold=True)
            self.text(
                self.x + 325,
                self.y + 55,
                pct(S["categories"][CATS[0]] * 100 / S["expenses"]),
                28,
                B.ACCENT,
                True,
            )
        else:
            h = min(remaining - 6, 275)
            self.rect(
                self.x, self.y, self.width, h, B.SURFACE if self.variant == 1 else B.BACKGROUND, 8
            )
            self.panel_heading(self.x, self.y, "Ranking wydatków", "PLN")
            maxval = max(S["categories"].values())
            for i, c in enumerate(CATS):
                yy = self.y + 66 + i * 24
                self.text(self.x + 15, yy, name(c), 9)
                bx = self.x + 130
                bw = self.width - 233
                self.rect(bx, yy - 9, bw, 9, B.BORDER, 2)
                self.rect(bx, yy - 9, bw * S["categories"][c] / maxval, 9, COLORS[c], 2)
                self.text(
                    self.x + self.width - 14,
                    yy,
                    money(S["categories"][c]),
                    9,
                    bold=True,
                    align="right",
                )

    def comparison(self):
        self.new_page(
            3, "Porównanie miesięcy", "Październik − wrzesień 2026 • wzrost / spadek wydatków"
        )
        rows = [
            (name(c), money(before), money(now), money(delta, True), pct(p, True))
            for c, before, now, delta, p in category_comparison(DATA, "2026-10")
        ]
        self.table(
            ["Kategoria", "Wrzesień PLN", "Październik PLN", "Zmiana PLN", "Zmiana %"],
            rows,
            [2, 1.15, 1.25, 1.15, 0.95],
            "Porównanie miesięcy",
            3,
            (1, 2, 3, 4),
            0,
            base_h=31,
            font=8.7,
        )
        self.plot(
            "change",
            self.x,
            self.y,
            self.width,
            min(self.bottom - self.y - 2, 295),
            "Zmiana wydatków kategorii",
            "PLN • czerwony: wzrost / zielony: spadek",
        )

    def time(self):
        self.new_page(4, "Wydatki w czasie", "Wydatki brutto • data transakcji • PLN")
        y = self.y
        if self.variant == 2:
            gap = 12
            w = (self.width - gap) / 2
            h = (self.bottom - y - 13) / 2
            self.plot("daily", self.x, y, w, h, "Wydatki dzienne")
            self.calendar(self.x + w + gap, y, w, h)
            self.plot("cumulative", self.x, y + h + gap, w, h, "Wydatki narastająco")
            self.plot("weekday", self.x + w + gap, y + h + gap, w, h, "Dni tygodnia · suma")
        else:
            self.plot("daily", self.x, y, self.width, 199, "Wydatki dzienne")
            y += 212
            w = (self.width - 12) / 2
            self.plot("cumulative", self.x, y, w, 185, "Wydatki narastająco")
            self.plot("weekday", self.x + w + 12, y, w, 185, "Dni tygodnia · suma")
            y += 198
            self.plot(
                "merchants",
                self.x,
                y,
                self.width,
                min(194, self.bottom - y - 1),
                "Najwięksi odbiorcy · Top 5",
            )

    def calendar(self, x, y, w, h):
        self.rect(x, y, w, h, B.SURFACE, 8, B.BORDER)
        self.panel_heading(x, y, "Kalendarz wydatków", "Październik 2026 • PLN")
        size = min((w - 28) / 7, (h - 74) / 6)
        left = x + (w - size * 7) / 2
        top = y + 61
        for j, d in enumerate(["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]):
            self.text(left + j * size + size / 2, top, d, 7, B.MUTED, align="center")
        for i, week in enumerate(calendar.monthcalendar(2026, 10)):
            for j, day in enumerate(week):
                if not day:
                    continue
                intensity = DAILY[day - 1] / max(DAILY)
                # Actual UI panel/cyan tones, with day numbers always visible.
                base = colors.HexColor(B.PANEL)
                accent = colors.HexColor(B.ACCENT_DARK)
                mix = [
                    a * (1 - intensity * 0.8) + b * intensity * 0.8
                    for a, b in zip(base.rgb(), accent.rgb())
                ]
                fill = colors.Color(*mix).hexval().replace("0x", "#")
                self.rect(left + j * size, top + 8 + i * size, size - 3, size - 3, fill, 3)
                self.text(
                    left + j * size + (size - 3) / 2,
                    top + 8 + i * size + (size - 3) * 0.66,
                    day,
                    8,
                    B.TEXT,
                    align="center",
                )

    def breakdown(self):
        self.new_page(
            5, "Kategorie i podkategorie", "Kwoty podkategorii składają się na sumę kategorii"
        )
        counts = Counter((r["category"], r["subcategory"]) for r in EXPENSES)
        rows = []
        for cat in CATS:
            rows.append((name(cat), "SUMA KATEGORII", COUNTS[cat], money(S["categories"][cat])))
            for (c, sub), value in sorted(S["subcategories"].items(), key=lambda p: -p[1]):
                if c == cat:
                    rows.append(("", name(sub), counts[(c, sub)], money(value)))
        self.table(
            ["Kategoria", "Podkategoria", "Transakcje", "Kwota PLN"],
            rows,
            [1.8, 1.8, 1, 1.3],
            "Kategorie i podkategorie",
            5,
            (2, 3),
            0,
            base_h=24,
            font=8.5,
        )

    def unassigned(self):
        self.new_page(
            6, "Wydatki do przypisania", "Transakcje bez kategorii • dane uwzględnione w raporcie"
        )
        y = self.y
        gap = 10
        w = (self.width - 2 * gap) / 3
        self.metric(
            self.x,
            y,
            w,
            76,
            "Bez kategorii",
            money(S["uncategorized_minor"]),
            "PLN",
            "tag",
            B.WARNING,
        )
        self.metric(
            self.x + w + gap,
            y,
            w,
            76,
            "Transakcje",
            str(len(S["uncategorized"])),
            "do przypisania",
            "transactions",
            B.WARNING,
        )
        self.metric(
            self.x + 2 * (w + gap),
            y,
            w,
            76,
            "Zakres danych",
            f"{len(S['rows'])} / {len(S['raw'])}",
            "uwzględnione / zapisane",
            "database",
            B.ACCENT,
        )
        self.y += 92
        rows = [
            (
                r["date"].replace("2026-10-", "") + ".10.2026",
                r["description"] or r["from_to"],
                money(-r["amount_minor"]),
            )
            for r in sorted(S["uncategorized"], key=lambda r: r["date"])
        ]
        self.table(
            ["Data", "Opis / kontrahent", "Wydatek PLN"],
            rows,
            [1.15, 3.9, 1.3],
            "Wydatki do przypisania",
            6,
            (2,),
            font=8.8,
            base_h=25,
        )
        if self.y + 25 < self.bottom:
            self.text(
                self.x,
                self.y + 10,
                f"Wyłączone transakcje: {len(S['raw']) - len(S['rows'])}   •   Konflikty kategorii: {S['conflicts']}   •   Opłaty: {money(S['fees'])} PLN",
                8,
                B.MUTED,
            )

    def transactions(self):
        self.new_page(
            7, "Szczegóły transakcji", "Uwzględnione operacje • wpływy dodatnie / wydatki ujemne"
        )
        rows = [
            (
                r["date"][8:] + "." + r["date"][5:7] + ".2026",
                r["description"] or r["from_to"],
                name(r["category"]),
                name(r["subcategory"]),
                money(r["amount_minor"]),
            )
            for r in sorted(S["rows"], key=lambda r: (r["date"], r["id"]))
        ]
        self.table(
            ["Data", "Opis / kontrahent", "Kategoria", "Podkategoria", "Kwota PLN"],
            rows,
            [1.05, 2.8, 1.35, 1.4, 1.2],
            "Szczegóły transakcji",
            7,
            (4,),
            font=8.5 if self.variant != 2 else 9,
            base_h=24,
        )

    def build(self):
        self.overview()
        self.categories()
        self.comparison()
        self.time()
        self.breakdown()
        self.unassigned()
        self.transactions()
        self.canvas.save()
        reader = PdfReader(OUT / self.filename)
        text = "\n".join(p.extract_text() for p in reader.pages)
        assert APP_NAME in text and "FINANS" not in text
        assert money(S["expenses"]) in text and money(S["net"]) in text
        assert len(reader.pages) == self.page
        # Both Segoe UI faces are embedded; the logo is an actual image asset.
        resources = reader.pages[0]["/Resources"]
        fonts = [font.get_object() for font in resources["/Font"].values()]
        assert sum("/FontFile2" in f.get("/FontDescriptor", {}) for f in fonts) == 2
        assert any(
            obj.get_object().get("/Subtype") == "/Image" for obj in resources["/XObject"].values()
        )
        print(f"{self.filename}: {self.page} pages")
        return {"file": self.filename, "pages": self.page, "layout": self.audit}


def render_previews(filename):
    doc = QPdfDocument(None)
    doc.load(str(OUT / filename))
    count = doc.pageCount()
    cols = 3
    page_size = doc.pagePointSize(0)
    thumb_w = 300
    thumb_h = round(thumb_w * page_size.height() / page_size.width())
    sheet = QImage(
        cols * (thumb_w + 12),
        ((count + cols - 1) // cols) * (thumb_h + 12),
        QImage.Format.Format_RGB32,
    )
    sheet.fill(QColor("#52677b"))
    painter = QPainter(sheet)
    for i in range(count):
        img = doc.render(i, QSize(thumb_w, thumb_h))
        painter.drawImage((i % cols) * (thumb_w + 12) + 6, (i // cols) * (thumb_h + 12) + 6, img)
        if i in (0, 1, 3, 5):
            width = 1100
            doc.render(i, QSize(width, round(width * page_size.height() / page_size.width()))).save(
                str(OUT / f"{Path(filename).stem}-p{i + 1}.png")
            )
    painter.end()
    sheet.save(str(OUT / f"{Path(filename).stem}-all.png"))
    doc.close()


if __name__ == "__main__":
    manifest = {
        "brand": APP_NAME,
        "period": "2026-10",
        "currency": "PLN",
        "source": "example/database/home_finance_demo.db (synthetic)",
        "expenses_minor": S["expenses"],
        "inflows_minor": S["inflows"],
        "net_minor": S["net"],
        "reports": [],
    }
    for variant in (1, 2, 3):
        report = Report(variant)
        manifest["reports"].append(report.build())
        render_previews(report.filename)
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
