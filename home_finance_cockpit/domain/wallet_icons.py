"""Stable wallet icon identifiers shared by storage and desktop UI."""

WALLET_ICONS = {
    "wallet": "Portfel",
    "bank": "Bank",
    "card": "Karta",
    "cash": "Gotówka",
    "savings": "Oszczędności",
    "home": "Dom",
    "travel": "Podróże",
    "business": "Praca",
    "gift": "Prezent",
    "shield": "Rezerwa",
}


def wallet_icon(value):
    if not isinstance(value, str) or value not in WALLET_ICONS:
        raise ValueError("Wybierz ikonę portfela z dostępnej listy.")
    return value
