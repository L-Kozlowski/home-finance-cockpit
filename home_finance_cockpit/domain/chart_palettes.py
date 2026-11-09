"""Curated categorical palettes shared by the UI and report renderer."""

from hashlib import sha256

from home_finance_cockpit.domain.brand_palette import CHART_COLORS as BRAND_COLORS

PALETTES = {
    "vivid": (
        "Vivid — intensywna",
        ("#00B8D9", "#FFAB00", "#FF5630", "#7C4DFF", "#00C853", "#F500A0"),
    ),
    "jewel": (
        "Jewel — szlachetna",
        ("#26A69A", "#7E57C2", "#EC407A", "#FFA726", "#42A5F5", "#9CCC65"),
    ),
    "sunset": (
        "Sunset — ciepła",
        ("#F07167", "#F6BD60", "#D45D9E", "#A280D5", "#F89F6E", "#6CB4B8"),
    ),
    "botanical": (
        "Botanical — naturalna",
        ("#43AA8B", "#90BE6D", "#F9C74F", "#F8961E", "#577590", "#B56576"),
    ),
    "spectrum": (
        "Spectrum — wielobarwna",
        (
            "#4E79A7",
            "#F28E2B",
            "#E15759",
            "#76B7B2",
            "#59A14F",
            "#EDC949",
            "#AF7AA1",
            "#FF9DA7",
            "#9C755F",
            "#BAB0AC",
        ),
    ),
    "electric": (
        "Electric — wyrazista",
        ("#00C2FF", "#FF5DA2", "#B6E53C", "#FF9E00", "#9B6DFF", "#00D5A4", "#FF6262", "#E5D0FF"),
    ),
    "cockpit": ("Cockpit — klasyczna", BRAND_COLORS),
    "business": (
        "Business — zrównoważona",
        ("#76A9DC", "#F0B775", "#86BC86", "#D99BA8", "#A998CF", "#81BDBD"),
    ),
    "ocean": (
        "Ocean — chłodna",
        ("#67B7DC", "#74D3BE", "#8E9FE3", "#B2A1D8", "#B5D5DE", "#5E9EBA"),
    ),
    "accessible": (
        "Kontrast — zróżnicowana",
        ("#56B4E9", "#E69F00", "#65C9A4", "#EAA8CD", "#EEDB70", "#E28B60"),
    ),
}
_active = "cockpit"


def set_palette(value):
    global _active
    if value not in PALETTES:
        raise ValueError("Wybierz poprawną paletę kolorów.")
    _active = value


def chart_colors():
    return PALETTES[_active][1]


def automatic_category_color(name):
    known = {
        "Food": 0,
        "Transport": 1,
        "Mandatory": 2,
        "Home": 3,
        "Housing": 3,
        "Medical": 4,
        "FreeTime": 5,
        "Occasional": 2,
        "Revolut": 1,
        "AccountFunding": 5,
    }
    index = known.get(name)
    if index is None:
        index = int.from_bytes(sha256(name.encode("utf-8")).digest()[:4], "big")
    colors = chart_colors()
    return colors[index % len(colors)]
