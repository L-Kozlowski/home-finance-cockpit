"""Stable identifiers shared by category persistence and the icon picker."""

CATEGORY_ICONS = {
    "tag": "Kategoria",
    "food": "Żywność",
    "cart": "Zakupy",
    "coffee": "Kawiarnia",
    "home": "Dom",
    "car": "Samochód",
    "travel": "Podróże",
    "health": "Zdrowie",
    "education": "Edukacja",
    "gift": "Prezenty",
    "business": "Praca",
    "shield": "Ubezpieczenia",
    "savings": "Oszczędności",
    "sport": "Sport",
    "music": "Rozrywka",
    "pet": "Zwierzęta",
    "bank": "Bank",
    "cash": "Gotówka",
    "card": "Karta",
    "wallet": "Portfel",
    "clothes": "Odzież",
    "phone": "Telefon",
    "internet": "Internet",
    "power": "Energia",
    "water": "Woda",
    "tools": "Remont",
    "restaurant": "Restauracja",
    "fuel": "Paliwo",
    "train": "Transport publiczny",
    "bike": "Rower",
    "plane": "Loty",
    "hotel": "Noclegi",
    "laptop": "Elektronika",
    "camera": "Fotografia",
    "book": "Książki",
    "child": "Dzieci",
    "beauty": "Pielęgnacja",
    "garden": "Ogród",
    "charity": "Darowizny",
    "tax": "Podatki",
}


def category_icon(value):
    if value not in CATEGORY_ICONS:
        raise ValueError("Invalid category icon")
    return value
