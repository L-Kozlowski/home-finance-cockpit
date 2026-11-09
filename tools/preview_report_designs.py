"""Build three complete PDF design proposals from the synthetic demo database."""

import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib

matplotlib.use("Agg")
from matplotlib import font_manager
from matplotlib import pyplot as plt
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from home_finance_cockpit.reports.data import ReportOptions, category_comparison, snapshot
from home_finance_cockpit.storage import Database

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


def category_label(value):
    return LABELS.get(value, value)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/ui-concepts/report-pdfs"
OUT.mkdir(parents=True, exist_ok=True)
for name, weight in [("Report", "normal"), ("ReportBold", "bold")]:
    pdfmetrics.registerFont(
        TTFont(
            name,
            font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans", weight=weight)),
        )
    )
pdfmetrics.registerFontFamily("Report", normal="Report", bold="ReportBold")

with tempfile.TemporaryDirectory() as temporary:
    copied = Path(temporary) / "demo.db"
    shutil.copy2(ROOT / "example/database/home_finance_demo.db", copied)
    db = Database.open_existing(copied)
    data = snapshot(db, ReportOptions(currency="PLN", year=2026, months=("2026-10",), annual=False))
    db.close()
S = data["summaries"]["2026-10"]
PALETTE = ["#22b8cf", "#778bfa", "#45b59b", "#d9a451", "#b48ce1", "#e47a91", "#5298cd"]
CATS = sorted(S["categories"], key=lambda k: -S["categories"][k])
CAT_COLORS = {
    cat: data["category_colors"].get(cat) or PALETTE[i % len(PALETTE)] for i, cat in enumerate(CATS)
}


def money(v):
    if v is None:
        return "—"
    return f"{v / 100:,.2f}".replace(",", " ").replace(".", ",")


def percent(v):
    return "—" if v is None else f"{float(v):.1f}%".replace(".", ",")


class Design:
    def __init__(self, mode):
        self.mode = mode
        self.dark = mode == 1
        self.bg = "#0b1623" if self.dark else "#f4f7fa"
        self.card = "#14283a" if self.dark else "#ffffff"
        self.text = "#edf4ff" if self.dark else "#14283a"
        self.muted = "#a8bed5" if self.dark else "#52677b"
        self.line = "#294154" if self.dark else "#dbe4eb"
        self.accent = "#22d3ee" if self.dark else "#087c93"
        self.story = []
        self.styles = {
            "body": ParagraphStyle(
                "body",
                fontName="Report",
                fontSize=8,
                leading=12,
                textColor=colors.HexColor(self.text),
            ),
            "muted": ParagraphStyle(
                "muted",
                fontName="Report",
                fontSize=8,
                leading=12,
                textColor=colors.HexColor(self.muted),
            ),
            "h1": ParagraphStyle(
                "h1",
                fontName="ReportBold",
                fontSize=19,
                leading=25,
                spaceAfter=12,
                textColor=colors.HexColor(self.text),
                keepWithNext=True,
            ),
            "h2": ParagraphStyle(
                "h2",
                fontName="ReportBold",
                fontSize=11,
                leading=16,
                spaceBefore=12,
                spaceAfter=8,
                textColor=colors.HexColor(self.text),
                keepWithNext=True,
            ),
            "value": ParagraphStyle(
                "value",
                fontName="ReportBold",
                fontSize=16,
                leading=23,
                textColor=colors.HexColor(self.accent),
            ),
        }

    def p(self, text, style="body"):
        return Paragraph(escape(str(text)), self.styles[style])

    def title(self, n, title, new=True):
        if new:
            self.story.append(PageBreak())
        self.story.append(self.p(f"{n:02d}  {title}", "h1"))

    def heading(self, title):
        self.story.append(self.p(title, "h2"))

    def table(self, headers, rows, widths, numeric=(), small=False):
        cells = [[self.p(v) for v in headers]]
        for row in rows:
            cells.append([self.p(v) for v in row])
        table = Table(
            cells, colWidths=[523 * w / sum(widths) for w in widths], repeatRows=1, hAlign="LEFT"
        )
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3347" if self.dark else "#e4edf3")),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [
                    colors.HexColor(self.card),
                    colors.HexColor("#102132" if self.dark else "#edf3f7"),
                ],
            ),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6 if small else 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6 if small else 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(self.accent)),
        ]
        table.setStyle(TableStyle(commands))
        self.story.append(table)

    def chart(self, kind, height=200):
        plt.rcParams.update(
            {
                "font.family": "DejaVu Sans",
                "font.size": 8,
                "text.color": self.text,
                "axes.labelcolor": self.muted,
                "xtick.color": self.muted,
                "ytick.color": self.muted,
            }
        )
        fig, ax = plt.subplots(figsize=(8, height / 65), layout="constrained")
        fig.patch.set_facecolor(self.card)
        ax.set_facecolor(self.card)
        if kind == "donut":
            vals = [S["categories"][c] for c in CATS]
            wedges, _ = ax.pie(
                vals,
                colors=[CAT_COLORS[c] for c in CATS],
                startangle=90,
                counterclock=False,
                wedgeprops={"width": 0.25, "edgecolor": self.card, "linewidth": 2},
            )
            ax.text(
                0,
                0.08,
                money(S["expenses"]),
                ha="center",
                fontsize=16,
                weight="bold",
                color=self.text,
            )
            ax.text(0, -0.18, "Wydatki · PLN", ha="center", fontsize=9, color=self.muted)
            ax.legend(
                wedges,
                [category_label(c) for c in CATS],
                loc="center left",
                bbox_to_anchor=(1, 0.5),
                frameon=False,
                labelcolor=self.text,
                fontsize=8,
            )
            ax.set_xlim(-1.3, 1.6)
        elif kind == "categories":
            names = list(reversed(CATS))
            ax.barh(
                [category_label(c) for c in names],
                [S["categories"][c] / 100 for c in names],
                color=[CAT_COLORS[c] for c in names],
                height=0.57,
            )
            ax.set_xlabel("PLN")
            ax.grid(axis="x", alpha=0.13)
            ax.set_axisbelow(True)
        elif kind == "comparison":
            previous = data["summaries"]["2026-09"]["categories"]
            names = list(reversed(CATS))
            positions = list(range(len(names)))
            ax.barh(
                [p + 0.17 for p in positions],
                [previous.get(c, 0) / 100 for c in names],
                height=0.3,
                color="#758aa3",
                label="Wrzesień",
            )
            ax.barh(
                [p - 0.17 for p in positions],
                [S["categories"][c] / 100 for c in names],
                height=0.3,
                color="#22b8cf",
                label="Październik",
            )
            ax.set_yticks(positions, [category_label(c) for c in names])
            ax.set_xlabel("PLN")
            ax.grid(axis="x", alpha=0.13)
            ax.set_axisbelow(True)
            ax.legend(frameon=False, labelcolor=self.text, loc="lower right")
        elif kind == "daily":
            daily = defaultdict(int)
            for r in S["rows"]:
                if r["amount_minor"] < 0:
                    daily[int(r["date"][-2:])] -= r["amount_minor"]
            ax.bar(
                range(1, 32), [daily[d] / 100 for d in range(1, 32)], color="#22b8cf", width=0.68
            )
            ax.set_xlabel("Dzień miesiąca")
            ax.set_ylabel("PLN")
            ax.grid(axis="y", alpha=0.13)
            ax.set_xticks([1, 5, 10, 15, 20, 25, 31])
        elif kind == "cumulative":
            daily = Counter()
            for r in S["rows"]:
                if r["amount_minor"] < 0:
                    daily[int(r["date"][-2:])] -= r["amount_minor"]
            values = []
            total = 0
            for d in range(1, 32):
                total += daily[d]
                values.append(total / 100)
            ax.plot(range(1, 32), values, color="#22b8cf", linewidth=2)
            ax.fill_between(range(1, 32), values, color="#22b8cf", alpha=0.14)
            ax.set_xlabel("Dzień miesiąca")
            ax.set_ylabel("PLN")
            ax.grid(alpha=0.13)
            ax.set_xticks([1, 5, 10, 15, 20, 25, 31])
        elif kind == "weekday":
            values = [0] * 7
            for r in S["rows"]:
                if r["amount_minor"] < 0:
                    values[date.fromisoformat(r["date"]).weekday()] -= r["amount_minor"]
            ax.bar(
                ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Ndz"],
                [v / 100 for v in values],
                color=PALETTE,
            )
            ax.set_ylabel("PLN")
            ax.grid(axis="y", alpha=0.13)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(length=0)
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=180, facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        self.story.append(Image(buf, width=523, height=height))

    def footer(self, canvas, doc):
        w, h = A4
        canvas.setFillColor(colors.HexColor(self.bg))
        canvas.rect(0, 0, w, h, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#22d3ee" if self.dark else "#087c93"))
        canvas.rect(0, h - 5, w, 5, fill=1, stroke=0)
        canvas.setFont("ReportBold", 10)
        canvas.drawString(36, h - 30, "FINANS")
        canvas.setFillColor(colors.HexColor(self.muted))
        canvas.setFont("Report", 8)
        canvas.drawRightString(w - 36, h - 30, "PAŹDZIERNIK 2026  /  PLN")
        canvas.setStrokeColor(colors.HexColor(self.line))
        canvas.line(36, 35, w - 36, 35)
        canvas.setFont("Report", 7)
        canvas.drawString(36, 23, "Dane demonstracyjne • wszystkie portfele PLN • wydatki brutto")
        canvas.drawRightString(w - 36, 23, f"{doc.page}")
        if self.mode == 3:
            canvas.setFillColor(colors.HexColor("#112233"))
            canvas.rect(0, h - 48, w, 48, fill=1, stroke=0)
            canvas.setFillColor(colors.HexColor("#22d3ee"))
            canvas.setFont("ReportBold", 11)
            canvas.drawString(36, h - 30, "FINANS")
            canvas.setFillColor(colors.HexColor("#edf4ff"))
            canvas.setFont("Report", 8)
            canvas.drawRightString(w - 36, h - 30, "RAPORT MIESIĘCZNY • PAŹDZIERNIK 2026")

    def build(self):
        self.title(1, "Raport miesięczny", new=False)
        self.story.append(self.p("Październik 2026 · wszystkie portfele PLN", "muted"))
        self.story.append(Spacer(1, 16))
        cards = []
        for title, value in [
            ("Wpływy", S["inflows"]),
            ("Wydatki", S["expenses"]),
            ("Przepływ netto", S["net"]),
        ]:
            cards.append(
                [self.p(title, "muted"), self.p(money(value), "value"), self.p("PLN", "muted")]
            )
        tiles = Table(
            [[Table([[v] for v in c], colWidths=[150]) for c in cards]], colWidths=[174, 174, 175]
        )
        tiles.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(self.card)),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(self.line)),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        self.story.append(tiles)
        self.heading("Aktywność w miesiącu")
        self.table(
            ["Transakcje wydatkowe", "Zmiana m/m", "Średni wydatek"],
            [
                [
                    str(S["expense_count"]),
                    money(S["change"]) + " PLN / " + percent(S["change_percent"]),
                    money(S["gross_expenses"] / S["expense_count"]) + " PLN",
                ]
            ],
            [1, 1.5, 1],
        )
        self.heading("Struktura wydatków")
        self.chart("donut", 250)
        self.heading("Dane raportu")
        self.table(
            ["Zakres", "Wartość"],
            [
                ("Okres", "01–31.10.2026"),
                ("Portfele", "Wszystkie portfele w PLN"),
                ("Wydatki", "Brutto, bez pomniejszania o zwroty"),
                ("Przelewy własne", "Wyłączone"),
                (
                    "Opłaty w dostępnych rekordach",
                    money(S["fees"]) + " PLN" if S["fees"] is not None else "Brak danych",
                ),
            ],
            [1, 2],
            small=True,
        )
        self.title(2, "Wydatki według kategorii")
        self.table(
            ["Kategoria", "Wydatki PLN", "Udział"],
            [
                (
                    category_label(c),
                    money(S["categories"][c]),
                    percent(S["categories"][c] * 100 / S["expenses"]),
                )
                for c in CATS
            ],
            [2.5, 1, 0.7],
            small=True,
        )
        self.heading("Ranking kategorii")
        self.chart("categories", 230)
        self.title(3, "Porównanie z wrześniem")
        self.story.append(self.p("Zmiana = październik − wrzesień", "muted"))
        self.story.append(Spacer(1, 12))
        self.table(
            ["Kategoria", "Wrzesień PLN", "Październik PLN", "Zmiana PLN", "Zmiana %"],
            [
                (category_label(c), money(before), money(now), money(delta), percent(pct))
                for c, before, now, delta, pct in category_comparison(data, "2026-10")
            ],
            [2.1, 1.1, 1.2, 1.1, 0.9],
            small=True,
        )
        self.heading("Wydatki kategorii · dwa miesiące")
        self.chart("comparison", 265)
        self.title(4, "Wydatki w czasie")
        self.heading("Wydatki dzienne")
        self.chart("daily", 175)
        self.heading("Wydatki narastająco")
        self.chart("cumulative", 175)
        self.heading("Wydatki według dnia tygodnia")
        self.chart("weekday", 160)
        self.title(5, "Kategorie i podkategorie")
        counts = Counter(
            (r["category"], r["subcategory"]) for r in S["rows"] if r["amount_minor"] < 0
        )
        rows = []
        for c in CATS:
            children = sorted(
                ((sub, value) for (cat, sub), value in S["subcategories"].items() if cat == c),
                key=lambda v: -v[1],
            )
            for sub, value in children:
                rows.append(
                    (
                        category_label(c),
                        category_label(sub) if sub else "Bez podkategorii",
                        str(counts[(c, sub)]),
                        money(value),
                    )
                )
            rows.append(
                (
                    category_label(c),
                    "SUMA KATEGORII",
                    str(sum(n for (cat, sub), n in counts.items() if cat == c)),
                    money(S["categories"][c]),
                )
            )
        self.table(
            ["Kategoria", "Podkategoria", "Transakcje", "Wydatki PLN"],
            rows,
            [1.7, 1.8, 0.8, 1.1],
            small=True,
        )
        self.title(6, "Transakcje bez kategorii")
        missing = S["uncategorized"]
        self.heading("Zakres danych")
        self.table(
            ["Zakres danych", "Wartość"],
            [
                ("Transakcje: uwzględnione / zapisane", f"{len(S['rows'])} / {len(S['raw'])}"),
                (
                    "Transakcje: wyłączone / konflikty kategorii",
                    f"{len(S['raw']) - len(S['rows'])} / {S['conflicts']}",
                ),
                (
                    "Bez kategorii: transakcje / kwota",
                    f"{len(missing)} / {money(S['uncategorized_minor'])} PLN",
                ),
            ],
            [3, 1.4],
            small=True,
        )
        self.heading("Wydatki do przypisania")
        self.table(
            ["Data", "Opis", "Wydatek PLN"],
            [
                (r["date"], r["description"] or r["from_to"], money(-r["amount_minor"]))
                for r in missing
            ]
            or [("—", "Wszystkie wydatki przypisane", "—")],
            [1, 3.6, 1.2],
            small=True,
        )
        self.title(7, "Szczegóły transakcji")
        self.table(
            ["Data", "Opis / kontrahent", "Kategoria", "Podkategoria", "Kwota PLN"],
            [
                (
                    r["date"],
                    r["description"] or r["from_to"],
                    category_label(r["category"]),
                    category_label(r["subcategory"]) if r["subcategory"] else "—",
                    money(r["amount_minor"]),
                )
                for r in sorted(S["rows"], key=lambda r: (r["date"], r["id"]))
            ],
            [1, 2.6, 1.5, 1.5, 1.1],
            small=True,
        )
        names = {1: "01-raport-ciemny.pdf", 2: "02-raport-jasny.pdf", 3: "03-raport-mieszany.pdf"}
        path = OUT / names[self.mode]
        document = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            rightMargin=36,
            leftMargin=36,
            topMargin=64,
            bottomMargin=48,
            title="Raport miesięczny — październik 2026",
            author="FINANS • koncepcja wizualna",
        )
        document.build(self.story, onFirstPage=self.footer, onLaterPages=self.footer)
        reader = PdfReader(path)
        assert all(page.extract_text().strip() for page in reader.pages)
        print(f"{path.name}: {len(reader.pages)} pages, {path.stat().st_size:,} bytes")


for mode in (1, 2, 3):
    Design(mode).build()

# Raster previews allow checking every page without changing the application.
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
for pdf in OUT.glob("*.pdf"):
    document = QPdfDocument(None)
    document.load(str(pdf))
    count = document.pageCount()
    sheet = QImage(900, ((count + 2) // 3) * 440, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#6d7a86"))
    painter = QPainter(sheet)
    for page in range(count):
        rendered = document.render(page, QSize(292, 413))
        painter.drawImage((page % 3) * 300 + 4, (page // 3) * 440 + 4, rendered)
        if page == 0:
            document.render(page, QSize(900, 1273)).save(str(OUT / f"{pdf.stem}-preview.png"))
    painter.end()
    sheet.save(str(OUT / f"{pdf.stem}-pages.png"))
    document.close()
print("Categories:", CATS)
print("Subcategories:", sorted({sub for cat, sub in S["subcategories"]}))
