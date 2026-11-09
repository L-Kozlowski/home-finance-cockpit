"""Branded A4 reports, matching the accepted Cockpit proposal without GUI dependencies."""

import calendar
import os
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from functools import lru_cache
from io import BytesIO
from math import nan
from pathlib import Path

from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from home_finance_cockpit.domain import brand_palette as B
from home_finance_cockpit.identity import APP_NAME, BRAND_ASSETS
from home_finance_cockpit.localization import language
from home_finance_cockpit.reports.data import category_comparison, previous_month
from home_finance_cockpit.reports.presentation import category_color

ASSETS = BRAND_ASSETS / "reports"


def wrap_lines(value, font, size, width):
    """Wrap long identifiers as well as ordinary words; never discard bank text."""
    result = []
    for line in simpleSplit(str(value), font, size, width) or [""]:
        while pdfmetrics.stringWidth(line, font, size) > width:
            low, high = 1, len(line)
            while low < high:
                middle = (low + high + 1) // 2
                if pdfmetrics.stringWidth(line[:middle], font, size) <= width:
                    low = middle
                else:
                    high = middle - 1
            result.append(line[:low])
            line = line[low:]
        result.append(line)
    return result


def register_fonts():
    for key, filename, weight in (
        ("Cockpit", "segoeui.ttf", "normal"),
        ("CockpitBold", "seguisb.ttf", "bold"),
    ):
        if key in pdfmetrics.getRegisteredFontNames():
            continue
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
        if not path.exists():
            path = font_manager.findfont(
                font_manager.FontProperties(family="DejaVu Sans", weight=weight)
            )
        pdfmetrics.registerFont(TTFont(key, str(path)))


@lru_cache(maxsize=256)
def report_icon(key, color):
    path = ASSETS / f"{key}.png"
    if not path.is_file():
        path = ASSETS / "tag.png"
    with Image.open(path) as source:
        result = Image.new("RGBA", source.size, color)
        result.putalpha(source.getchannel("A"))
    return ImageReader(result)


class CockpitReport:
    def __init__(self, data, period, path, *, annual=False):
        register_fonts()
        self.data, self.options, self.period = data, data["options"], period
        self.annual, self.lang = annual, language()
        self.months = (
            [m for m in data["annual_months"] if m.startswith(period)] if annual else [period]
        )
        values = [data["summaries"][m] for m in self.months]
        self.s = dict(values[0])
        if annual:
            for key in (
                "inflows",
                "expenses",
                "gross_expenses",
                "net",
                "refunds",
                "expense_count",
                "uncategorized_minor",
                "conflicts",
                "user_excluded_count",
                "fee_count",
            ):
                self.s[key] = sum(s[key] for s in values)
            self.s["fees"] = (
                sum(s["fees"] for s in values if s["fees"] is not None)
                if any(s["fees"] is not None for s in values)
                else None
            )
            for key in ("categories", "subcategories", "daily"):
                totals = defaultdict(int)
                for s in values:
                    for k, v in s[key].items():
                        totals[k] += v
                self.s[key] = dict(totals)
            for key in ("rows", "raw", "uncategorized"):
                self.s[key] = [r for s in values for r in s[key]]
            self.s["change"], self.s["change_percent"] = None, None
        self.cats = sorted(
            self.s["categories"], key=lambda c: (-self.s["categories"][c], c.casefold())
        )
        self.colors = {c: category_color(c, data.get("category_colors")) for c in self.cats}
        self.expenses = [r for r in self.s["rows"] if r["amount_minor"] < 0]
        self.counts = Counter(r["category"] for r in self.expenses)
        self.currency = self.options.currency
        self.w, self.h = A4
        self.x, self.width, self.bottom = 34, self.w - 68, self.h - 48
        self.page, self.section, self.headings, self.tables = 0, 0, [], []
        self.title, self.subtitle = "", ""
        self.path = Path(path)
        self.canvas = Canvas(str(path), pagesize=A4, pageCompression=1)
        self.canvas.setAuthor(APP_NAME)
        self.canvas.setTitle(
            f"{APP_NAME} — {self.t('Raport roczny', 'Annual report') if annual else self.t('Raport miesięczny', 'Monthly report')}: {period}"
        )
        self.canvas.setSubject(
            self.t("Wydatki po zwrotach", "Costs after refunds")
            if self.options.after_refunds
            else self.t("Wydatki brutto", "Gross expenses")
        )
        self.cost_title = (
            self.t("Koszt po zwrotach", "Cost after refunds")
            if self.options.after_refunds
            else self.t("Wydatki brutto", "Gross expenses")
        )

    def t(self, pl, en):
        return pl if self.lang == "pl" else en

    def money(self, value, *, signed=False):
        if value is None:
            return "—"
        result = ("+" if signed and value > 0 else "") + f"{Decimal(value) / 100:,.2f}".replace(
            ",", " "
        )
        return result.replace(".", ",") if self.lang == "pl" else result

    def pct(self, value, *, signed=False):
        if value is None:
            return "—"
        result = ("+" if signed and value > 0 else "") + f"{value:.1f}%"
        return result.replace(".", ",") if self.lang == "pl" else result

    def subname(self, value):
        return (
            self.t("Bez podkategorii", "No subcategory")
            if value in ("", "No subcategory", None)
            else value
        )

    def month_name(self, month):
        names = (
            (
                "Styczeń",
                "Luty",
                "Marzec",
                "Kwiecień",
                "Maj",
                "Czerwiec",
                "Lipiec",
                "Sierpień",
                "Wrzesień",
                "Październik",
                "Listopad",
                "Grudzień",
            )
            if self.lang == "pl"
            else (
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            )
        )
        return f"{names[int(month[-2:]) - 1]} {month[:4]}"

    def date(self, value):
        return date.fromisoformat(value).strftime("%d.%m.%Y" if self.lang == "pl" else "%Y-%m-%d")

    def rect(self, x, y, w, h, fill=B.SURFACE, radius=8, stroke=None):
        c = self.canvas
        c.setFillColor(colors.HexColor(fill))
        if stroke:
            c.setStrokeColor(colors.HexColor(stroke))
            c.setLineWidth(0.6)
        c.roundRect(x, self.h - y - h, w, h, radius, fill=1, stroke=int(bool(stroke)))

    def text(self, x, y, value, size=9, color=B.TEXT, bold=False, align="left"):
        self.canvas.setFillColor(colors.HexColor(color))
        self.canvas.setFont("CockpitBold" if bold else "Cockpit", size)
        {
            "left": self.canvas.drawString,
            "right": self.canvas.drawRightString,
            "center": self.canvas.drawCentredString,
        }[align](x, self.h - y, str(value))

    def rule(self, x, y, w):
        self.canvas.setStrokeColor(colors.HexColor(B.BORDER))
        self.canvas.setLineWidth(0.6)
        self.canvas.line(x, self.h - y, x + w, self.h - y)

    def image(self, source, x, y, w, h):
        self.canvas.drawImage(
            str(source) if isinstance(source, Path) else source,
            x,
            self.h - y - h,
            w,
            h,
            mask="auto",
        )

    def glyph(self, key, x, y, size=16, color=B.ACCENT):
        self.image(report_icon(key, color), x, y, size, size)

    def new_page(self, section, title, subtitle="", *, continuation=False):
        if self.page:
            self.canvas.showPage()
        self.page += 1
        self.section = section
        self.title = title
        self.subtitle = subtitle
        self.rect(0, 0, self.w, self.h, B.BACKGROUND, 0)
        self.image(ASSETS / "wordmark.png", self.x, 23, 165, 39.2)
        self.text(
            self.w - self.x,
            37,
            self.t("RAPORT ROCZNY", "ANNUAL REPORT")
            if self.annual
            else self.t("RAPORT MIESIĘCZNY", "MONTHLY REPORT"),
            8,
            B.MUTED,
            True,
            "right",
        )
        self.text(
            self.w - self.x,
            55,
            f"{self.period if self.annual else self.month_name(self.period).upper()} / {self.currency}",
            9,
            align="right",
        )
        self.rule(self.x, 79, self.width)
        self.rect(self.x, 97, 29, 26, "#153b4d", 5)
        self.text(self.x + 14.5, 115, f"{section:02d}", 10, B.ACCENT, True, "center")
        heading = title + (self.t(" · cd.", " · continued") if continuation else "")
        title_lines = simpleSplit(heading, "CockpitBold", 22, self.width - 41)
        for i, line in enumerate(title_lines):
            self.text(self.x + 41, 117 + i * 26, line, 22, bold=True)
        sy = 139 + (len(title_lines) - 1) * 26
        sublines = wrap_lines(subtitle, "Cockpit", 8.5, self.width) if subtitle else []
        if len(sublines) > 2:
            sublines = [sublines[0], sublines[1][:-1] + "…"]
        for line in sublines:
            self.text(self.x, sy, line, 8.5, B.MUTED)
            sy += 12
        self.y = max(157, sy + 6)
        self.rule(self.x, self.h - 37, self.width)
        self.text(self.x, self.h - 23, APP_NAME, 7, B.MUTED)
        self.text(
            self.w - self.x,
            self.h - 23,
            f"{self.currency}  •  {self.page:02d}",
            7,
            B.MUTED,
            align="right",
        )
        self.headings.append((self.page, heading))
        key = f"section-{section}-{self.page}"
        self.canvas.bookmarkPage(key)
        if not continuation:
            self.canvas.addOutlineEntry(title, key, 0)

    def metric(self, x, y, w, h, title, value, detail, key, color=B.ACCENT):
        self.rect(x, y, w, h, B.SURFACE, 8, B.BORDER)
        self.glyph(key, x + 13, y + 13, 15, color)
        lines = simpleSplit(title, "Cockpit", 8.5, w - 45)
        for i, line in enumerate(lines):
            self.text(x + 36, y + 22 + i * 10, line, 8.5, B.MUTED)
        size = 17
        while pdfmetrics.stringWidth(value, "CockpitBold", size) > w - 26 and size > 9:
            size -= 0.5
        self.text(x + 13, y + 53, value, size, color, True)
        self.text(x + 13, y + h - 12, detail, 8, B.MUTED)

    def plot(self, kind, x, y, w, h, title, unit=None):
        self.rect(x, y, w, h, B.SURFACE, 8, B.BORDER)
        self.text(x + 14, y + 25, title, 11, bold=True)
        self.text(x + 14, y + 42, unit or self.currency, 8, B.MUTED)
        self.image(self.chart(kind, w - 20, h - 59), x + 10, y + 51, w - 20, h - 59)

    def chart(self, kind, w, h):
        figure = Figure(figsize=(w / 72, h / 72), dpi=160, layout="constrained")
        FigureCanvasAgg(figure)
        figure.patch.set_alpha(0)
        ax = figure.add_subplot(111)
        ax.set_facecolor("none")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(colors=B.MUTED, length=0, labelsize=8, pad=6)
        ax.set_axisbelow(True)
        formatter = FuncFormatter(lambda v, p: f"{v:,.0f}".replace(",", " "))
        if kind in ("daily", "cumulative"):
            year, month = map(int, self.period.split("-"))
            days = list(range(1, calendar.monthrange(year, month)[1] + 1))
            daily = [self.s["daily"].get(f"{self.period}-{d:02d}", 0) / 100 for d in days]
            if kind == "daily":
                ax.bar(days, daily, color=B.ACCENT, width=0.64, zorder=3)
            else:
                running = []
                total = 0
                for v in daily:
                    total += v
                    running.append(total)
                ax.plot(days, running, color=B.ACCENT, linewidth=2.2, zorder=3)
                ax.fill_between(days, running, color=B.ACCENT, alpha=0.1)
                ax.scatter([days[-1]], [running[-1]], color=B.ACCENT, s=18, zorder=4)
            ax.set_xticks(sorted({1, 10, 20, days[-1]}))
            ax.grid(axis="y", color=B.BORDER, linewidth=0.6)
        elif kind == "weekday":
            values = [0] * 7
            for r in self.s["rows"]:
                values[date.fromisoformat(r["date"]).weekday()] += r["cost_minor"]
            labels = (
                ("Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Ndz")
                if self.lang == "pl"
                else ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
            )
            ax.bar(
                labels,
                [v / 100 for v in values],
                color=[B.ACCENT if v == max(values) else B.INFO for v in values],
                width=0.55,
                zorder=3,
            )
            ax.grid(axis="y", color=B.BORDER, linewidth=0.6)
        elif kind in ("change", "merchants", "signed"):
            if kind == "change":
                pairs = [
                    (r[0], r[3])
                    for r in category_comparison(self.data, self.period)
                    if r[3] is not None
                ]
                pairs = sorted(pairs, key=lambda p: -abs(p[1]))[:8]
            elif kind == "merchants":
                values = defaultdict(int)
                for r in self.s["rows"]:
                    if r["cost_minor"]:
                        values[
                            r["from_to"].strip()
                            or r["description"].strip()
                            or self.t("Brak opisu", "No description")
                        ] += r["cost_minor"]
                pairs = sorted(values.items(), key=lambda p: -p[1])[:5]
            else:
                pairs = [(c, self.s["categories"][c]) for c in self.cats[:7]]
            pairs = list(reversed(pairs))
            labels = [v if len(v) <= 28 else v[:25] + "…" for v, _ in pairs]
            vals = [v / 100 for _, v in pairs]
            ax.barh(
                labels,
                vals,
                color=[B.ERROR if v > 0 else B.SUCCESS for v in vals]
                if kind == "change"
                else B.ACCENT,
                height=0.5,
                zorder=3,
            )
            ax.axvline(0, color=B.MUTED, linewidth=0.6)
            ax.grid(axis="x", color=B.BORDER, linewidth=0.6)
            ax.xaxis.set_major_formatter(formatter)
            if not pairs:
                ax.text(
                    0.5,
                    0.5,
                    self.t("Brak danych", "No data"),
                    color=B.MUTED,
                    ha="center",
                    transform=ax.transAxes,
                )
        elif kind in ("annual", "composition"):
            first, last = int(self.months[0][-2:]), int(self.months[-1][-2:])
            months = [f"{self.period}-{m:02d}" for m in range(first, last + 1)]
            positions = list(range(len(months)))
            if kind == "annual":
                for key, title, color in (
                    ("inflows", self.t("Wpływy", "Inflows"), B.SUCCESS),
                    ("expenses", self.cost_title, B.ERROR),
                    ("net", self.t("Przepływ netto", "Net flow"), B.INFO),
                ):
                    ax.plot(
                        positions,
                        [
                            self.data["summaries"][m][key] / 100 if m in self.months else nan
                            for m in months
                        ],
                        marker="o",
                        markersize=3,
                        linewidth=1.6,
                        color=color,
                        label=title,
                    )
            else:
                pos = [0.0] * len(months)
                neg = [0.0] * len(months)
                for cat in self.cats:
                    vals = [
                        self.data["summaries"][m]["categories"].get(cat, 0) / 100
                        if m in self.months
                        else nan
                        for m in months
                    ]
                    ax.bar(
                        positions,
                        vals,
                        bottom=[p if v >= 0 else n for p, n, v in zip(pos, neg, vals)],
                        color=self.colors[cat],
                        label=cat,
                        width=0.55,
                    )
                    pos = [a + max(0, b) for a, b in zip(pos, vals)]
                    neg = [a + min(0, b) for a, b in zip(neg, vals)]
            ax.set_xticks(positions, [m[-2:] for m in months])
            ax.grid(axis="y", color=B.BORDER, linewidth=0.6)
            ax.legend(
                frameon=False,
                labelcolor=B.MUTED,
                fontsize=7,
                ncols=min(3, len(self.cats)) or 1,
                loc="upper center",
                bbox_to_anchor=(0.5, 1.23),
            )
        if kind not in ("change", "merchants", "signed"):
            ax.yaxis.set_major_formatter(formatter)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
        stream = BytesIO()
        figure.savefig(stream, format="png", dpi=160, transparent=True)
        figure.clear()
        stream.seek(0)
        return ImageReader(stream)

    def ring_entries(self):
        """The ring and its legend always share exactly the same groups."""
        limit = 7 if len(self.cats) > 8 else 8
        entries = [(c, self.s["categories"][c], self.colors[c], c) for c in self.cats[:limit]]
        if len(self.cats) > 8:
            entries.append(
                (
                    self.t("Pozostałe", "Other"),
                    sum(self.s["categories"][c] for c in self.cats[7:]),
                    B.DISABLED,
                    None,
                )
            )
        return entries

    def ring_panel(self, y):
        self.rect(self.x, y, self.width, 292, B.SURFACE, 8, B.BORDER)
        self.text(
            self.x + 14, y + 25, self.t("Struktura wydatków", "Spending breakdown"), 11, bold=True
        )
        total = self.s["expenses"]
        entries = self.ring_entries()
        if any(v < 0 for v in self.s["categories"].values()):
            self.plot(
                "signed", self.x + 8, y + 41, 220, 236, self.t("Koszty ze znakiem", "Signed costs")
            )
        else:
            cx, cy, r = self.x + 116, y + 159, 83
            start = 90
            self.canvas.setStrokeColor(colors.HexColor(B.BORDER))
            self.canvas.setLineWidth(r * 0.25)
            self.canvas.circle(cx, self.h - cy, r, stroke=1, fill=0)
            for cat, value, color, original in entries:
                span = value / total * 360 if total else 0
                if not span:
                    continue
                gap = min(2, span * 0.2)
                self.canvas.setStrokeColor(colors.HexColor(color))
                self.canvas.setLineWidth(r * 0.25)
                self.canvas.arc(
                    cx - r,
                    self.h - cy - r,
                    cx + r,
                    self.h - cy + r,
                    startAng=start - gap / 2,
                    extent=-(span - gap),
                )
                start -= span
            self.text(
                cx,
                cy - 13,
                self.t("KOSZT", "COST")
                if self.options.after_refunds
                else self.t("WYDATKI", "EXPENSES"),
                8,
                B.MUTED,
                True,
                "center",
            )
            value = self.money(total)
            size = 20
            while pdfmetrics.stringWidth(value, "CockpitBold", size) > 155 and size > 9:
                size -= 0.5
            self.text(cx, cy + 11, value, size, bold=True, align="center")
            self.text(cx, cy + 31, self.currency, 8.5, B.MUTED, align="center")
        for i, (cat, amount, color, original) in enumerate(entries):
            yy = y + 62 + i * 28
            self.glyph(
                self.data.get("category_icons", {}).get(original, "tag"),
                self.x + 235,
                yy - 11,
                14,
                color,
            )
            label_lines = simpleSplit(cat, "Cockpit", 9, 155)
            for j, line in enumerate(label_lines[:2]):
                self.text(self.x + 257, yy + j * 10, line, 9)
            self.text(
                self.x + self.width - 18,
                yy,
                self.money(amount),
                9,
                bold=True,
                align="right",
            )
        if not self.cats:
            self.text(self.x + 235, y + 110, self.t("Brak wydatków", "No expenses"), 11, B.MUTED)
        if len(self.cats) > 8:
            self.text(
                self.x + 235,
                y + 280,
                self.t("Pełna lista w tabeli kategorii", "Full list in the category table"),
                8,
                B.MUTED,
            )

    def overview(self):
        scope = (
            self.t("Wszystkie portfele w wybranej walucie", "All wallets in the selected currency")
            if self.options.wallet_id is None
            else self.data["scope"]
        )
        self.new_page(
            1,
            self.t("Podsumowanie", "Overview"),
            f"{self.period if self.annual else self.month_name(self.period)} • {self.currency} • {scope}",
        )
        y = self.y
        w = (self.width - 20) / 3
        for i, (title, key, glyph, color) in enumerate(
            (
                (self.t("Wpływy", "Inflows"), "inflows", "income", B.SUCCESS),
                (self.cost_title, "expenses", "expense", B.ERROR),
                (self.t("Przepływ netto", "Net flow"), "net", "transactions", B.INFO),
            )
        ):
            self.metric(
                self.x + i * (w + 10),
                y,
                w,
                84,
                title,
                self.money(self.s[key]),
                self.currency,
                glyph,
                color,
            )
        y += 101
        self.ring_panel(y)
        y += 315
        stats = [
            (
                self.t("TRANSAKCJE WYDATKOWE", "EXPENSE TRANSACTIONS"),
                str(self.s["expense_count"]),
                self.t("wyłącznie kwoty ujemne", "negative amounts only"),
            ),
            (
                self.t("ŚREDNI WYDATEK", "AVERAGE EXPENSE"),
                self.money(Decimal(self.s["gross_expenses"]) / self.s["expense_count"])
                if self.s["expense_count"]
                else "—",
                self.currency,
            ),
            (
                self.t("ZMIANA M/M", "MONTHLY CHANGE"),
                self.money(self.s["change"], signed=True),
                self.pct(self.s["change_percent"], signed=True),
            ),
        ]
        if self.annual:
            stats[2] = (
                self.t("MIESIĄCE Z DANYMI", "MONTHS WITH DATA"),
                str(len(self.months)),
                self.t("z 12 miesięcy", "of 12 months"),
            )
        for i, (title, value, detail) in enumerate(stats):
            xx = self.x + i * 181
            self.text(xx, y, title, 8, B.MUTED)
            self.text(xx, y + 24, value, 17, B.ACCENT if i < 2 else B.ERROR, True)
            self.text(xx, y + 40, detail, 7.5, B.MUTED)
        if y + 208 <= self.bottom:
            self.plot(
                "annual" if self.annual else "cumulative",
                self.x,
                y + 57,
                self.width,
                151,
                self.t("Przepływy miesięczne", "Monthly activity")
                if self.annual
                else self.t("Wydatki narastająco", "Cumulative spending"),
            )

    def table(
        self,
        headers,
        rows,
        widths,
        *,
        right=(),
        category_col=None,
        font=9,
        row_height=27,
        changes=(),
        signed_col=None,
    ):
        """Repeat headers and split even a single very long bank description without losing text."""
        widths = [v * self.width / sum(widths) for v in widths]

        def header():
            lines = [
                simpleSplit(str(h), "CockpitBold", 8.3, w - 18) for h, w in zip(headers, widths)
            ]
            height = max(31, max(map(len, lines)) * 10 + 10)
            self.rect(self.x, self.y, self.width, height, B.INPUT, 5)
            xx = self.x
            for col, (wrapped, w) in enumerate(zip(lines, widths)):
                for j, line in enumerate(wrapped):
                    self.text(
                        xx + w - 9 if col in right else xx + 9,
                        self.y + 12 + j * 10,
                        line,
                        8.3,
                        B.MUTED,
                        True,
                        "right" if col in right else "left",
                    )
                xx += w
            self.y += height + 3

        if self.y + 70 > self.bottom:
            self.new_page(self.section, self.title, self.subtitle, continuation=True)
        header()
        for index, row in enumerate(rows):
            original = next(
                (c for c in self.cats if category_col is not None and c == row[category_col]), None
            )
            wrapped = [
                wrap_lines(
                    str(v) if v is not None else "—",
                    "Cockpit",
                    font,
                    w - 18 - (21 if col == category_col and original else 0),
                )
                or [""]
                for col, (v, w) in enumerate(zip(row, widths))
            ]
            position = 0
            length = max(map(len, wrapped))
            while position < length:
                lines_fit = int((self.bottom - self.y - 12) // (font + 3))
                if lines_fit < 1 or self.y + row_height > self.bottom:
                    self.new_page(self.section, self.title, self.subtitle, continuation=True)
                    header()
                    continue
                end = min(length, position + lines_fit)
                rh = max(row_height, (end - position) * (font + 3) + 12)
                if self.y + rh > self.bottom:
                    continue
                self.rect(
                    self.x, self.y, self.width, rh, B.PANEL if index % 2 == 0 else B.SURFACE, 0
                )
                xx = self.x
                for col, (lines, w) in enumerate(zip(wrapped, widths)):
                    offset = 0
                    if col == category_col and original:
                        self.glyph(
                            self.data.get("category_icons", {}).get(original, "tag"),
                            xx + 9,
                            self.y + (rh - 13) / 2,
                            13,
                            self.colors[original],
                        )
                        offset = 21
                    visible = lines[position:end]
                    color = B.TEXT
                    if col in changes:
                        color = (
                            B.ERROR
                            if str(row[col]).startswith("+")
                            else B.SUCCESS
                            if str(row[col]).startswith("-")
                            else B.MUTED
                        )
                    if col == signed_col:
                        color = B.ERROR if str(row[col]).startswith("-") else B.SUCCESS
                    for j, line in enumerate(visible):
                        yy = self.y + (rh - len(visible) * (font + 3)) / 2 + font + j * (font + 3)
                        self.text(
                            xx + w - 9 if col in right else xx + 9 + offset,
                            yy,
                            line,
                            font,
                            color,
                            False,
                            "right" if col in right else "left",
                        )
                    xx += w
                self.y += rh
                position = end
            self.tables.append((self.page, self.y))
        self.y += 15

    def categories(self):
        self.new_page(
            2,
            self.t("Kategorie wydatków", "Spending by category"),
            self.cost_title + " • " + self.currency,
        )
        shares = self.s["expenses"] > 0 and all(v >= 0 for v in self.s["categories"].values())
        self.table(
            [
                self.t("Kategoria", "Category"),
                self.t("Transakcje", "Transactions"),
                self.t("Kwota", "Amount") + " " + self.currency,
                self.t("Udział", "Share"),
            ],
            [
                (
                    c,
                    self.counts[c],
                    self.money(self.s["categories"][c]),
                    self.pct(Decimal(self.s["categories"][c]) * 100 / self.s["expenses"])
                    if shares
                    else "—",
                )
                for c in self.cats
            ],
            [2.5, 1, 1.3, 1],
            right=(1, 2, 3),
            category_col=0,
            row_height=31,
        )
        if self.y + 120 > self.bottom:
            self.new_page(2, self.title, self.subtitle, continuation=True)
        h = min(self.bottom - self.y - 3, 275)
        self.rect(self.x, self.y, self.width, h, B.SURFACE, 8, B.BORDER)
        self.text(
            self.x + 14,
            self.y + 25,
            self.t("Ranking wydatków · Top 8", "Spending ranking · Top 8"),
            11,
            bold=True,
        )
        self.text(self.x + 14, self.y + 42, self.currency, 8, B.MUTED)
        maximum = max([abs(v) for v in self.s["categories"].values()] or [1]) or 1
        for i, cat in enumerate(self.cats[:8]):
            yy = self.y + 66 + i * 24
            if yy + 10 > self.y + h:
                break
            short = cat if len(cat) < 21 else cat[:18] + "…"
            self.text(self.x + 15, yy, short, 9)
            bx = self.x + 130
            bw = self.width - 233
            self.rect(bx, yy - 9, bw, 9, B.BORDER, 2)
            self.rect(
                bx, yy - 9, bw * abs(self.s["categories"][cat]) / maximum, 9, self.colors[cat], 2
            )
            self.text(
                self.x + self.width - 14,
                yy,
                self.money(self.s["categories"][cat]),
                9,
                bold=True,
                align="right",
            )

    def comparison(self):
        self.new_page(
            3,
            self.t("Porównanie miesięcy", "Monthly comparison"),
            f"{self.period} − {previous_month(self.period)} • "
            + self.t("wzrost / spadek kosztów", "increase / decrease in costs"),
        )
        self.table(
            [
                self.t("Kategoria", "Category"),
                self.t("Poprzednio", "Previous") + " " + self.currency,
                self.t("Obecnie", "Current") + " " + self.currency,
                self.t("Zmiana", "Change") + " " + self.currency,
                self.t("Zmiana %", "Change %"),
            ],
            [
                (
                    c,
                    self.money(before),
                    self.money(now),
                    self.money(delta, signed=True),
                    self.pct(p, signed=True),
                )
                for c, before, now, delta, p in category_comparison(self.data, self.period)
            ],
            [2, 1.15, 1.25, 1.15, 0.95],
            right=(1, 2, 3, 4),
            category_col=0,
            row_height=31,
            font=8.7,
            changes=(3, 4),
        )
        if self.y + 160 > self.bottom:
            self.new_page(3, self.title, self.subtitle, continuation=True)
        self.plot(
            "change",
            self.x,
            self.y,
            self.width,
            min(295, self.bottom - self.y - 2),
            self.t("Zmiana wydatków kategorii · Top 8", "Category spending change · Top 8"),
            self.currency
            + " • "
            + self.t("czerwony: wzrost / zielony: spadek", "red: increase / green: decrease"),
        )

    def time(self):
        self.new_page(
            4,
            self.t("Wydatki w czasie", "Spending over time"),
            self.cost_title + " • " + self.t("data transakcji", "transaction date"),
        )
        y = self.y
        self.plot("daily", self.x, y, self.width, 199, self.t("Wydatki dzienne", "Daily spending"))
        y += 212
        w = (self.width - 12) / 2
        self.plot(
            "cumulative", self.x, y, w, 185, self.t("Wydatki narastająco", "Cumulative spending")
        )
        self.plot(
            "weekday", self.x + w + 12, y, w, 185, self.t("Dni tygodnia · suma", "Weekdays · total")
        )
        y += 198
        self.plot(
            "merchants",
            self.x,
            y,
            self.width,
            min(194, self.bottom - y - 1),
            self.t("Najwięksi odbiorcy · Top 5", "Top recipients · Top 5"),
        )

    def breakdown(self):
        self.new_page(
            5,
            self.t("Kategorie i podkategorie", "Categories and subcategories"),
            self.t(
                "Kwoty podkategorii składają się na sumę kategorii",
                "Subcategory amounts make up the category total",
            ),
        )
        counts = Counter(
            (r["category"], r["subcategory"] or "No subcategory") for r in self.expenses
        )
        rows = []
        for cat in self.cats:
            rows.append(
                (
                    cat,
                    self.t("SUMA KATEGORII", "CATEGORY TOTAL"),
                    self.counts[cat],
                    self.money(self.s["categories"][cat]),
                )
            )
            for (c, sub), value in sorted(self.s["subcategories"].items(), key=lambda p: -p[1]):
                if c == cat:
                    rows.append(("", self.subname(sub), counts[(c, sub)], self.money(value)))
        self.table(
            [
                self.t("Kategoria", "Category"),
                self.t("Podkategoria", "Subcategory"),
                self.t("Transakcje", "Transactions"),
                self.t("Kwota", "Amount") + " " + self.currency,
            ],
            rows,
            [1.8, 1.8, 1, 1.3],
            right=(2, 3),
            category_col=0,
            row_height=24,
            font=8.5,
        )

    def unassigned(self):
        self.new_page(
            6,
            self.t("Wydatki do przypisania", "Uncategorized expenses"),
            self.t(
                "Transakcje bez kategorii • dane uwzględnione w raporcie",
                "Uncategorized transactions • included in this report",
            ),
        )
        y = self.y
        w = (self.width - 20) / 3
        for i, (title, value, detail, key, color) in enumerate(
            (
                (
                    self.t("Bez kategorii", "Uncategorized"),
                    self.money(self.s["uncategorized_minor"]),
                    self.currency,
                    "tag",
                    B.WARNING,
                ),
                (
                    self.t("Transakcje", "Transactions"),
                    str(len(self.s["uncategorized"])),
                    self.t("do przypisania", "to categorize"),
                    "transactions",
                    B.WARNING,
                ),
                (
                    self.t("Zakres danych", "Data coverage"),
                    f"{len(self.s['rows'])} / {len(self.s['raw'])}",
                    self.t("uwzględnione / zapisane", "included / saved"),
                    "database",
                    B.ACCENT,
                ),
            )
        ):
            self.metric(self.x + i * (w + 10), y, w, 76, title, value, detail, key, color)
        self.y += 92
        if not self.s["uncategorized"]:
            self.text(
                self.x,
                self.y + 15,
                self.t(
                    "Wszystkie wydatki przypisane do kategorii",
                    "All expenses have been assigned to a category",
                ),
                10,
                B.MUTED,
            )
            self.y += 40
        else:
            self.table(
                [
                    self.t("Data", "Date"),
                    self.t("Opis / kontrahent", "Description / counterparty"),
                    self.t("Wydatek", "Expense") + " " + self.currency,
                ],
                [
                    (
                        self.date(r["date"]),
                        r["description"] or r["from_to"],
                        self.money(-r["amount_minor"]),
                    )
                    for r in sorted(self.s["uncategorized"], key=lambda r: (r["date"], r["id"]))
                ],
                [1.15, 3.9, 1.3],
                right=(2,),
                font=8.8,
                row_height=25,
            )

    def coverage(self):
        self.new_page(
            8, self.t("Zakres danych", "Data coverage"), self.period + " • " + self.currency
        )
        excluded = len(self.s["raw"]) - len(self.s["rows"])
        details = [
            (self.t("Portfele", "Wallets"), self.data["scope"]),
            (
                self.t("Uwzględnione / zapisane transakcje", "Included / saved transactions"),
                f"{len(self.s['rows'])} / {len(self.s['raw'])}",
            ),
            (self.t("Wyłączone transakcje", "Excluded transactions"), excluded),
            (
                self.t("Wyłączone przez użytkownika", "Excluded by user"),
                self.s["user_excluded_count"],
            ),
            (self.t("Konflikty kategorii", "Category conflicts"), self.s["conflicts"]),
            (
                self.t("Opłaty w dostępnych rekordach", "Fees in available records"),
                self.money(self.s["fees"]) + " " + self.currency,
            ),
            (
                self.t("Transakcje z polem opłaty", "Transactions with an available fee field"),
                self.s["fee_count"],
            ),
            (self.t("Tryb kosztów", "Cost mode"), self.cost_title),
            (
                self.t("Wydatki brutto", "Gross outflows"),
                self.money(self.s["gross_expenses"]) + " " + self.currency,
            ),
            (
                self.t("Oznaczone zwroty", "Marked refunds"),
                self.money(self.s["refunds"]) + " " + self.currency,
            ),
            (
                self.t("Przepływ netto", "Net flow"),
                self.t(
                    "Wpływy minus wydatki brutto; nie saldo portfela",
                    "Inflows minus gross outflows; not the wallet balance",
                ),
            ),
            (self.t("Przelewy własne", "Own transfers"), self.t("Wyłączone", "Excluded")),
            (
                self.t("Pomijanie pensji", "Omit salary"),
                self.t("Tak", "Yes") if self.options.omit_salary else self.t("Nie", "No"),
            ),
            (
                self.t("Wykluczanie rozpoznanych operacji", "Exclude recognized operations"),
                self.t("Tak", "Yes") if self.options.exclude_recognized else self.t("Nie", "No"),
            ),
        ]
        if self.annual:
            highest = max(self.months, key=lambda m: self.data["summaries"][m]["expenses"])
            lowest = min(self.months, key=lambda m: self.data["summaries"][m]["expenses"])
            details.extend(
                [
                    (
                        self.t(
                            "Średni koszt na miesiąc z danymi", "Average cost per available month"
                        ),
                        self.money(Decimal(self.s["expenses"]) / len(self.months))
                        + " "
                        + self.currency,
                    ),
                    (
                        self.t("Najwyższy koszt miesięczny", "Highest monthly cost"),
                        f"{highest} • {self.money(self.data['summaries'][highest]['expenses'])} {self.currency}",
                    ),
                    (
                        self.t("Najniższy koszt miesięczny", "Lowest monthly cost"),
                        f"{lowest} • {self.money(self.data['summaries'][lowest]['expenses'])} {self.currency}",
                    ),
                    (self.t("Miesiące z danymi", "Months included"), ", ".join(self.months)),
                    (
                        self.t("Miesiące bez danych", "Months without saved data"),
                        ", ".join(
                            f"{self.period}-{m:02d}"
                            for m in range(1, 13)
                            if f"{self.period}-{m:02d}" not in self.months
                        )
                        or "—",
                    ),
                ]
            )
        self.table(
            [self.t("Wskaźnik", "Metric"), self.t("Wartość", "Value")], details, [1.4, 2.2], font=9
        )

    def transactions(self):
        self.new_page(
            7,
            self.t("Szczegóły transakcji", "Monthly transaction detail"),
            self.t(
                "Uwzględnione operacje • wpływy dodatnie / wydatki ujemne",
                "Included operations • positive inflows / negative outflows",
            ),
        )
        self.table(
            [
                self.t("Data", "Date"),
                self.t("Opis / kontrahent", "Description / counterparty"),
                self.t("Kategoria", "Category"),
                self.t("Podkategoria", "Subcategory"),
                self.t("Kwota", "Amount") + " " + self.currency,
            ],
            [
                (
                    self.date(r["date"]),
                    r["description"] or r["from_to"],
                    r["category"],
                    self.subname(r["subcategory"]),
                    self.money(r["amount_minor"]),
                )
                for r in sorted(self.s["rows"], key=lambda r: (r["date"], r["id"]))
            ],
            [1.05, 2.8, 1.35, 1.4, 1.2],
            right=(4,),
            font=8.5,
            row_height=24,
            signed_col=4,
        )

    def annual_months(self):
        self.new_page(
            3,
            self.t("Porównanie miesięcy", "Monthly comparison"),
            self.t("Tylko miesiące z zapisanymi danymi", "Only months with saved data"),
        )
        self.table(
            [
                self.t("Miesiąc", "Month"),
                self.t("Wpływy", "Inflows"),
                self.cost_title,
                self.t("Przepływ netto", "Net flow"),
                self.t("Zmiana", "Change"),
                self.t("Zmiana %", "Change %"),
            ],
            [
                (
                    m,
                    self.money(self.data["summaries"][m]["inflows"]),
                    self.money(self.data["summaries"][m]["expenses"]),
                    self.money(self.data["summaries"][m]["net"]),
                    self.money(self.data["summaries"][m]["change"], signed=True),
                    self.pct(self.data["summaries"][m]["change_percent"], signed=True),
                )
                for m in self.months
            ],
            [1, 1.25, 1.25, 1.25, 1.1, 0.9],
            right=(1, 2, 3, 4, 5),
            font=8.5,
            changes=(4, 5),
        )
        if self.y + 250 > self.bottom:
            self.new_page(3, self.title, self.subtitle, continuation=True)
        self.plot(
            "annual",
            self.x,
            self.y,
            self.width,
            245,
            self.t("Przepływy miesięczne", "Monthly activity"),
        )
        self.new_page(
            4,
            self.t("Kategorie w czasie", "Categories over time"),
            self.cost_title + " • " + self.currency,
        )
        self.plot(
            "composition",
            self.x,
            self.y,
            self.width,
            290,
            self.t("Struktura wydatków miesięcznych", "Monthly spending composition"),
        )
        self.y += 310
        for offset in range(0, len(self.months), 4):
            block = self.months[offset : offset + 4]
            self.table(
                [self.t("Kategoria", "Category"), *block],
                [
                    (
                        c,
                        *[
                            self.money(self.data["summaries"][m]["categories"].get(c, 0))
                            for m in block
                        ],
                    )
                    for c in self.cats
                ],
                [2, *([1] * len(block))],
                right=tuple(range(1, len(block) + 1)),
                font=8.5,
                category_col=0,
            )

    def build(self):
        self.overview()
        self.categories()
        if self.annual:
            self.annual_months()
        else:
            if self.options.comparison:
                self.comparison()
            self.time()
        self.breakdown()
        if self.options.uncategorized:
            self.unassigned()
        if not self.annual and self.options.transactions:
            self.transactions()
        self.coverage()
        self.canvas.save()
        return {"pages": self.page, "headings": self.headings, "table_bottoms": self.tables}
