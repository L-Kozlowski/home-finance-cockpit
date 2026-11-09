"""Editable, localized starter configuration for newly created user databases."""

from datetime import date

from home_finance_cockpit.localization import translate

STARTER_CATEGORIES = (
    (
        "food",
        "Żywność",
        "#10B981",
        "food",
        (
            ("groceries", "Zakupy spożywcze"),
            ("restaurants", "Restauracje"),
            ("coffee", "Kawiarnie"),
        ),
    ),
    (
        "housing",
        "Mieszkanie",
        "#A78BFA",
        "home",
        (
            ("rent", "Opłaty mieszkaniowe"),
            ("utilities", "Media"),
            ("internet", "Internet"),
            ("furniture", "Meble i wyposażenie"),
        ),
    ),
    (
        "transport",
        "Transport",
        "#3B82F6",
        "car",
        (
            ("fuel", "Paliwo"),
            ("public_transport", "Transport publiczny"),
            ("car_purchase", "Zakup samochodu"),
            ("car_service", "Serwis samochodu"),
            ("car_insurance", "Ubezpieczenie samochodu"),
            ("parking", "Parkowanie"),
        ),
    ),
    (
        "health",
        "Zdrowie",
        "#F472B6",
        "health",
        (("medicine", "Leki"), ("medical_visits", "Wizyty lekarskie")),
    ),
    (
        "shopping",
        "Zakupy",
        "#F59E0B",
        "cart",
        (("clothes", "Odzież"), ("electronics", "Elektronika")),
    ),
    ("leisure", "Rozrywka", "#8B5CF6", "music", (("culture", "Kultura"), ("sport", "Sport"))),
    (
        "income",
        "Przychody",
        "#06B6D4",
        "business",
        (
            ("salary", "Wynagrodzenie"),
            ("other_income", "Pozostałe wpływy"),
            ("interest", "Odsetki"),
            ("dividends", "Dywidendy"),
        ),
    ),
    (
        "subscriptions",
        "Subskrypcje",
        "#818CF8",
        "card",
        (("streaming", "Filmy i muzyka"), ("software", "Oprogramowanie")),
    ),
    (
        "travel",
        "Podróże",
        "#22D3EE",
        "travel",
        (
            ("flights", "Loty"),
            ("hotels", "Hotele"),
            ("car_rental", "Wynajem samochodu"),
            ("activities", "Atrakcje turystyczne"),
        ),
    ),
    (
        "investments",
        "Inwestycje",
        "#F2CC82",
        "savings",
        (
            ("brokerage_fees", "Opłaty maklerskie"),
            ("gold_fees", "Koszty złota"),
            ("bond_fees", "Koszty obligacji"),
        ),
    ),
    (
        "phone_transaction",
        "Przelewy na telefon",
        "#FB923C",
        "phone",
        (("phone_sent", "Znajomi i rodzina"), ("phone_received", "Rozliczenia ze znajomymi")),
    ),
    (
        "internal_transfers",
        "Przelewy wewnętrzne",
        "#94A3B8",
        "bank",
        (("between_accounts", "Między własnymi kontami"), ("currency_exchange", "Wymiana walut")),
    ),
)

# These are editable example rules, never financial data or automatic transfer reconciliation.
MERCHANT_RULES = {
    "groceries": ("LIDL", "ALDI", "CARREFOUR", "TESCO", "COSTCO"),
    "restaurants": ("MCDONALD'S", "BURGER KING", "DOMINO'S", "UBER EATS"),
    "coffee": ("STARBUCKS", "COSTA COFFEE"),
    "rent": ("GREYSTAR",),
    "utilities": ("ENGIE", "EDF"),
    "internet": ("VODAFONE",),
    "furniture": ("IKEA",),
    "fuel": ("SHELL", "BP", "ESSO", "TOTALENERGIES"),
    "public_transport": ("UBER", "BOLT", "FLIXBUS"),
    "car_purchase": ("TOYOTA",),
    "car_service": ("BOSCH CAR SERVICE", "MICHELIN"),
    "car_insurance": ("ALLIANZ",),
    "parking": ("Q-PARK",),
    "medicine": ("BOOTS", "WALGREENS"),
    "medical_visits": ("BUPA",),
    "clothes": ("ZARA", "H&M", "UNIQLO", "NIKE", "ADIDAS"),
    "electronics": ("AMAZON", "APPLE", "SAMSUNG"),
    "culture": ("CINEWORLD", "TICKETMASTER", "STEAM", "PLAYSTATION"),
    "sport": ("DECATHLON", "BASIC-FIT"),
    "streaming": ("NETFLIX", "SPOTIFY", "DISNEY+"),
    "software": ("ADOBE", "MICROSOFT 365"),
    "flights": ("LUFTHANSA", "RYANAIR", "EASYJET"),
    "hotels": ("MARRIOTT", "HILTON", "BOOKING.COM"),
    "car_rental": ("HERTZ", "SIXT"),
    "activities": ("GETYOURGUIDE",),
}
DESCRIPTION_RULES = {
    "salary": ("PAYROLL", "Annual bonus"),
    "interest": ("Interest", "Bond distribution"),
    "dividends": ("Dividend",),
    "brokerage_fees": ("Brokerage fee",),
    "gold_fees": ("Gold custody fee",),
    "bond_fees": ("Bond custody fee",),
    "phone_sent": ("Phone transfer to",),
    "phone_received": ("Phone repayment from",),
    "between_accounts": ("Internal transfer",),
    "currency_exchange": ("FX transfer",),
}
CHILD_ICONS = {
    "groceries": "cart",
    "restaurants": "restaurant",
    "coffee": "coffee",
    "rent": "home",
    "utilities": "power",
    "internet": "internet",
    "furniture": "home",
    "fuel": "fuel",
    "public_transport": "train",
    "car_purchase": "car",
    "car_service": "tools",
    "car_insurance": "shield",
    "parking": "car",
    "medicine": "health",
    "medical_visits": "health",
    "clothes": "clothes",
    "electronics": "laptop",
    "culture": "music",
    "sport": "sport",
    "salary": "business",
    "other_income": "cash",
    "interest": "bank",
    "dividends": "savings",
    "streaming": "music",
    "software": "laptop",
    "flights": "plane",
    "hotels": "hotel",
    "car_rental": "car",
    "activities": "camera",
    "brokerage_fees": "business",
    "gold_fees": "savings",
    "bond_fees": "bank",
    "phone_sent": "phone",
    "phone_received": "phone",
    "between_accounts": "bank",
    "currency_exchange": "cash",
}


def populate_starter_categories(db, language_code):
    """Shared hierarchy and rules for a pristine user database and the showcase dataset."""
    if language_code not in ("pl", "en"):
        raise ValueError("Unsupported starter data language")
    targets = {}
    with db.transaction():
        for key, title, color, glyph, children in STARTER_CATEGORIES:
            root = db.save_category(translate(title, language_code), color=color, icon_name=glyph)
            targets[key] = root
            for child_key, child_title in children:
                targets[child_key] = db.save_category(
                    translate(child_title, language_code),
                    parent_id=root,
                    icon_name=CHILD_ICONS.get(child_key, glyph),
                )
        db.save_category("Ogólne", db.default_category_id(), color="#94A3B8", icon_name="tag")
        for target, merchants in MERCHANT_RULES.items():
            for merchant in merchants:
                db.save_rule(
                    targets[target],
                    "from_to",
                    merchant,
                    "literal" if target == "groceries" else "exact",
                )
        for target, patterns in DESCRIPTION_RULES.items():
            for pattern in patterns:
                db.save_rule(targets[target], "description", pattern, "starts_with")
        db.save_rule(
            targets["fuel"],
            "from_to",
            "MOL",
            conditions=[
                dict(
                    column_name="description",
                    mode="not_contains",
                    pattern=translate("parówka", language_code),
                )
            ],
        )
        # Keep a localized payroll example alongside international bank labels.
        if language_code == "pl":
            db.save_rule(targets["salary"], "description", "wynagrodzenie")
    return targets


def populate_starter_data(db, language_code):
    """Populate only a pristine database, atomically and without invented money."""
    if language_code not in ("pl", "en"):
        raise ValueError("Unsupported starter data language")
    with db.transaction():
        if any(not category["is_default"] for category in db.categories()) or any(
            db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            for table in ("wallets", "transactions", "rules", "savings_goals", "imports")
        ):
            return False

        def names(value):
            return translate(value, language_code)

        populate_starter_categories(db, language_code)
        wallet = db.save_wallet(
            names("Portfel główny"), "0", "PLN", date.today().isoformat(), icon_name="wallet"
        )
        db.save_savings_goal(
            names("Poduszka finansowa (przykład)"), wallet, "10000", "0", calculation_mode="wallet"
        )
    return True
