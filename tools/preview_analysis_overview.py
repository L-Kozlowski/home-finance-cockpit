"""Generate three standalone design proposals; does not modify application UI."""

import math
import os
from html import escape
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QFontDatabase, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

OUT = Path(__file__).resolve().parents[1] / "docs/ui-concepts/analysis-overview"
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
COLORS = ["#22d3ee", "#78dfc1", "#b9a0fa", "#f5bb70", "#6ea7fb", "#e88caa"]
DATA = [
    ("Mieszkanie", 3200, 5),
    ("Żywność", 1850, 42),
    ("Transport", 980, 18),
    ("Zakupy", 860, 12),
    ("Zdrowie", 640, 7),
    ("Pozostałe", 920, 16),
]
parts = []


def rect(x, y, w, h, fill="#112233", radius=10, stroke=None):
    parts.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}"'
        + (f' stroke="{stroke}"' if stroke else "")
        + "/>"
    )


def text(x, y, value, size=14, color="#edf4ff", weight=400, anchor="start"):
    parts.append(
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>'
    )


def line(x, y, x2, y2, color="#24394d"):
    parts.append(f'<path d="M{x} {y} L{x2} {y2}" stroke="{color}" fill="none"/>')


def money(v):
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " zł"


def shell(number, subtitle):
    parts.clear()
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1000" viewBox="0 0 1440 1000"><g font-family="Segoe UI, sans-serif">'
    )
    rect(0, 0, 1440, 1000, "#0b1623", 0)
    rect(0, 0, 190, 1000, "#112233", 0)
    text(24, 43, "FINANS", 23, "#22d3ee", 700)
    text(24, 67, "Twoje finanse pod kontrolą", 10, "#a8bed5")
    for i, label in enumerate(
        [
            "Pulpit",
            "Transakcje",
            "Importy",
            "Analizy",
            "Kategorie i reguły",
            "Portfele",
            "Ustawienia",
        ]
    ):
        y = 126 + i * 52
        if i == 3:
            rect(12, y - 28, 166, 43, "#1e3347", 7)
            rect(12, y - 21, 3, 29, "#22d3ee", 1)
        text(28, y, label, 14, "#22d3ee" if i == 3 else "#a8bed5", 600 if i == 3 else 400)
    text(220, 46, "Analizy", 27, weight=600)
    text(1408, 42, f"KONCEPCJA 0{number}", 11, "#a8bed5", anchor="end")
    tabs = [
        ("Podsumowanie", 220),
        ("Kategorie", 355),
        ("W czasie", 465),
        ("Porównania", 565),
        ("Odbiorcy", 687),
        ("Kursy walut", 795),
    ]
    for label, x in tabs:
        text(x, 94, label, 14, "#22d3ee" if label == "Kategorie" else "#a8bed5", 600)
    line(220, 110, 1410, 110)
    rect(351, 107, 85, 3, "#22d3ee", 0)
    for x, w, label in [
        (220, 80, "Filtry"),
        (312, 184, "Wszystkie portfele"),
        (508, 74, "PLN"),
        (594, 121, "Miesiąc"),
    ]:
        rect(x, 128, w, 38, "#1a2b3d", 6, "#24394d")
        text(x + w / 2, 152, label, 13, anchor="middle")
    rect(727, 128, 38, 38, "#1a2b3d", 6)
    text(746, 153, "‹", 23, anchor="middle")
    rect(773, 128, 206, 38, "#1a2b3d", 6)
    text(876, 152, "październik 2026", 14, anchor="middle")
    rect(987, 128, 38, 38, "#1a2b3d", 6)
    text(1006, 153, "›", 23, anchor="middle")
    rect(1262, 128, 148, 38, "#1e3347", 6, "#426077")
    text(1336, 152, "Wyczyść filtry", 13, anchor="middle")
    rect(220, 187, 238, 42, "#112233", 8)
    rect(224, 191, 117, 34, "#1e3347", 6)
    text(282, 213, "Przegląd", 14, "#22d3ee", 600, "middle")
    text(398, 213, "Szczegóły", 14, "#a8bed5", 400, "middle")
    text(220, 264, "Na co wydajesz pieniądze?", 23, weight=600)
    text(220, 288, subtitle, 13, "#a8bed5")
    text(220, 979, "Dane przykładowe • sumy dotyczą wydatków w wybranym okresie", 11, "#7b8fa6")


def kpis(y=312):
    for i, (label, value, detail) in enumerate(
        [
            ("Wydatki łącznie", "8 450,00 zł", "100 transakcji"),
            ("Największa kategoria", "Mieszkanie", "37,9% wydatków"),
            ("Średni wydatek", "84,50 zł", "na jedną transakcję"),
            ("Bez kategorii", "320,00 zł", "6 transakcji do przypisania"),
        ]
    ):
        x = 220 + i * 302
        rect(x, y, 284, 100)
        text(x + 18, y + 25, label, 12, "#a8bed5")
        text(x + 18, y + 57, value, 23, "#22d3ee" if i == 0 else "#edf4ff", 600)
        text(x + 18, y + 81, detail, 12, "#f5bb70" if i == 3 else "#a8bed5")


def donut(cx, cy, r=111):
    start = -90
    for i, (_, v, _) in enumerate(DATA):
        end = start + v / 8450 * 360
        a = math.radians(start + 1.2)
        b = math.radians(end - 1.2)
        parts.append(
            f'<path d="M{cx + r * math.cos(a)} {cy + r * math.sin(a)} A{r} {r} 0 {int(end - start > 180)} 1 {cx + r * math.cos(b)} {cy + r * math.sin(b)}" fill="none" stroke="{COLORS[i]}" stroke-width="30"/>'
        )
        start = end
    text(cx, cy - 8, "WYDATKI", 11, "#a8bed5", 600, "middle")
    text(cx, cy + 22, "8 450 zł", 26, weight=600, anchor="middle")
    text(cx, cy + 45, "100 transakcji", 12, "#a8bed5", anchor="middle")


def legend(x, y, w, row=34):
    for i, (name, v, _) in enumerate(DATA):
        rect(x, y + i * row - 10, 8, 8, COLORS[i], 3)
        text(x + 20, y + i * row, name, 13)
        text(x + w, y + i * row, money(v), 13, anchor="end")


ROWS = [
    ("Mieszkanie", 5, 3200, 0, 0),
    ("Czynsz", 1, 2500, 1, 0),
    ("Media", 4, 700, 1, 0),
    ("Żywność", 42, 1850, 0, 1),
    ("Spożywcze", 28, 1250, 1, 1),
    ("Restauracje", 14, 600, 1, 1),
    ("Transport", 18, 980, 0, 2),
    ("Zakupy", 12, 860, 0, 3),
    ("Zdrowie", 7, 640, 0, 4),
    ("Pozostałe", 16, 920, 0, 5),
    ("Bez kategorii", 6, 320, 1, 5),
]


def table(x, y, w, rows=ROWS, rh=37):
    rect(x, y, w, 42, "#1a2b3d", 6)
    text(x + 18, y + 26, "Kategoria / podkategoria", 12, "#a8bed5")
    text(x + w * 0.62, y + 26, "Transakcje", 12, "#a8bed5", anchor="end")
    text(x + w * 0.84, y + 26, "Suma wydatków", 12, "#a8bed5", anchor="end")
    text(x + w - 18, y + 26, "Udział", 12, "#a8bed5", anchor="end")
    for i, (name, count, v, child, c) in enumerate(rows):
        top = y + 43 + i * rh
        if child:
            rect(x, top, w, rh, "#0e1d2c", 0)
        line(x, top + rh, x + w, top + rh, "#203347")
        if not child:
            rect(x + 16, top + rh / 2 - 4, 8, 8, COLORS[c], 2)
        if child:
            line(x + 28, top + rh / 2 - 5, x + 28, top + rh / 2 + 1, "#57718a")
            line(x + 28, top + rh / 2 + 1, x + 35, top + rh / 2 + 1, "#57718a")
        text(
            x + (42 if child else 34),
            top + rh / 2 + 5,
            name,
            13,
            "#a8bed5" if child else "#edf4ff",
            400 if child else 600,
        )
        text(x + w * 0.62, top + rh / 2 + 5, count, 13, anchor="end")
        text(x + w * 0.84, top + rh / 2 + 5, money(v), 13, weight=600, anchor="end")
        text(
            x + w - 18,
            top + rh / 2 + 5,
            f"{v / 8450 * 100:.1f}%".replace(".", ","),
            12,
            "#a8bed5",
            anchor="end",
        )


def save(name):
    parts.append("</g></svg>")
    svg = "".join(parts)
    path = OUT / f"{name}.svg"
    path.write_text(svg, encoding="utf-8")
    renderer = QSvgRenderer(bytes(svg, "utf-8"))
    assert renderer.isValid(), name
    img = QImage(1440, 1000, QImage.Format.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    renderer.render(painter, QRectF(0, 0, 1440, 1000))
    painter.end()
    assert img.save(str(OUT / f"{name}.png"))


shell(1, "Wykres i szczegóły kategorii obok siebie — wszystko w jednym widoku.")
kpis()
rect(220, 430, 366, 520)
text(242, 461, "Struktura wydatków", 17, weight=600)
donut(403, 615, 107)
legend(242, 773, 320, 29)
rect(604, 430, 806, 520)
text(626, 461, "Kategorie i podkategorie", 17, weight=600)
text(1388, 460, "Rozwiń wszystkie", 12, "#22d3ee", anchor="end")
table(620, 481, 774, rh=37)
save("01-wykres-obok-tabeli")

shell(2, "Najwięcej miejsca na kategorie i podkategorie, z podsumowaniem zawsze pod ręką.")
rect(220, 314, 826, 636)
text(242, 348, "Wydatki według kategorii", 18, weight=600)
rect(242, 368, 782, 36, "#1e3347", 6)
text(257, 391, "Szukaj kategorii lub podkategorii…", 13, "#a8bed5")
table(238, 421, 790, rh=40)
rect(1064, 314, 346, 479)
text(1086, 348, "Struktura wydatków", 17, weight=600)
donut(1237, 496, 99)
legend(1086, 654, 302, 24)
rect(1064, 811, 346, 139)
text(1086, 839, "Do uzupełnienia", 14, "#f5bb70", 600)
text(1086, 873, "6 transakcji bez kategorii", 16, weight=600)
text(1086, 900, "320,00 zł • 3,8% wydatków", 13, "#a8bed5")
text(1086, 929, "Pokaż transakcje", 13, "#22d3ee", 600)
save("02-tabela-na-pierwszym-planie")

shell(3, "Szybki obraz miesiąca na górze, szczegółowe zestawienie poniżej.")
rect(220, 312, 1190, 300)
text(242, 345, "Struktura wydatków", 17, weight=600)
donut(392, 478, 94)
legend(558, 387, 350, 35)
line(943, 343, 943, 581)
text(974, 370, "WYDATKI ŁĄCZNIE", 11, "#a8bed5", 600)
text(974, 412, "8 450,00 zł", 30, "#22d3ee", 600)
text(974, 441, "100 transakcji • 6 kategorii", 13, "#a8bed5")
text(974, 490, "Mieszkanie + Żywność", 16, weight=600)
text(974, 516, "to 59,8% wszystkich wydatków.", 13, "#a8bed5")
rect(972, 540, 412, 45, "#1e3347", 6)
text(988, 568, "Bez kategorii: 6 transakcji / 320,00 zł", 13, "#f5bb70")
rect(220, 630, 1190, 320)
text(242, 663, "Kategorie i podkategorie", 18, weight=600)
text(1388, 663, "Rozwiń wszystkie", 12, "#22d3ee", anchor="end")
table(238, 683, 1154, ROWS[:6], rh=31)
text(242, 936, "Widoczne 2 z 6 kategorii • przewiń, aby zobaczyć pozostałe", 11, "#7b8fa6")
save("03-szeroki-przeglad")
print(f"Generated 3 SVG and 3 PNG previews in {OUT}")
