"""Deterministic English showcase: January–October 2026, entirely fictional money."""

import csv
import json
import math
import random
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from home_finance_cockpit.services.category_files import export_category_file
from home_finance_cockpit.services.starter_data import populate_starter_categories
from home_finance_cockpit.storage import Database
from tools.xlsx_examples import write_xlsx

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "example"
MONTHS = tuple(f"2026-{m:02d}" for m in range(1, 11))
RATES = {"PLN": Decimal("1"), "EUR": Decimal("4.30"), "USD": Decimal("4.00")}
APP_OWNER = "James Wilson"
WALLETS = [
    dict(key="main_account", name="Main account", currency="PLN", opening="24000.00", icon="bank"),
    dict(
        key="emergency_savings",
        name="Emergency savings",
        currency="PLN",
        opening="24000.00",
        icon="savings",
    ),
    dict(
        key="revolut_travel", name="Revolut Travel", currency="EUR", opening="800.00", icon="travel"
    ),
    dict(
        key="investment_usd", name="Investments", currency="USD", opening="5000.00", icon="business"
    ),
    dict(key="gold_usd", name="Gold reserve", currency="USD", opening="1500.00", icon="shield"),
    dict(key="bonds", name="Bond portfolio", currency="PLN", opening="12000.00", icon="bank"),
    dict(key="cash", name="Cash wallet", currency="PLN", opening="600.00", icon="cash"),
]
for wallet in WALLETS:
    wallet["opening_date"] = "2026-01-01"


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build():
    rng = random.Random(20261031)
    wallets = {w["key"]: w for w in WALLETS}
    ledger = {key: [] for key in wallets}
    metadata, transfers = {}, []
    sequence = 0

    def add(key, day, amount, merchant, description, *, kind="standard", included=True):
        nonlocal sequence
        sequence += 1
        external_id = f"HFC-{day.replace('-', '')}-{sequence:05d}"
        record = dict(
            date=day,
            amount=Decimal(str(amount)).quantize(Decimal(".01")),
            merchant=merchant,
            description=description,
            external_id=external_id,
            currency=wallets[key]["currency"],
        )
        ledger[key].append(record)
        if kind != "standard" or not included:
            metadata[external_id] = dict(analysis_kind=kind, include_in_reports=included)
        return external_id

    def transfer(source, target, day, received, label):
        received = Decimal(str(received))
        paid = (
            received * RATES[wallets[target]["currency"]] / RATES[wallets[source]["currency"]]
        ).quantize(Decimal(".01"))
        prefix = (
            "Internal transfer"
            if wallets[source]["currency"] == wallets[target]["currency"]
            else "FX transfer"
        )
        description = f"{prefix} | {label} | {wallets[source]['name']} to {wallets[target]['name']}"
        counterparty = APP_OWNER + (
            " | Own accounts" if prefix == "Internal transfer" else " | Currency exchange"
        )
        debit = add(source, day, -paid, counterparty, description, kind="transfer")
        credit = add(target, day, received, counterparty, description, kind="transfer")
        transfers.append(
            dict(
                debit=debit,
                credit=credit,
                source=source,
                target=target,
                paid=str(paid),
                received=str(received),
                date=day,
            )
        )

    variation = [0.90, 1.05, 0.96, 1.16, 0.88, 1.22, 1.08, 0.95, 1.13, 1.04]
    for m in range(1, 11):
        month = f"2026-{m:02d}"

        def day(d):
            return f"{month}-{d:02d}"

        pay = Decimal("18500") + (Decimal("750") if m >= 7 else 0)
        add(
            "main_account",
            day(1),
            pay,
            "MICROSOFT PAYROLL",
            "PAYROLL | Monthly salary",
            kind="salary",
        )
        if m in (3, 9):
            add(
                "main_account",
                day(1),
                4200 if m == 3 else 2600,
                "MICROSOFT PAYROLL",
                "Annual bonus | Performance award",
                kind="salary",
            )
        transfer("main_account", "emergency_savings", day(2), 2300, "Emergency fund contribution")
        transfer("main_account", "investment_usd", day(3), 400, "Monthly investment contribution")
        transfer("main_account", "gold_usd", day(3), 150, "Gold reserve contribution")
        transfer("main_account", "bonds", day(4), 900, "Monthly bond contribution")
        transfer("main_account", "revolut_travel", day(4), 200, "Holiday fund contribution")
        transfer("main_account", "cash", day(5), 300, "Cash withdrawal")
        add("main_account", day(2), -3300, "GREYSTAR", "Apartment rent | Monthly payment")
        add(
            "main_account",
            day(8),
            -(245 + (11 - m) * 9 + rng.randint(-35, 35)),
            "ENGIE",
            "Electricity and heating",
        )
        add("main_account", day(9), -(95 + rng.randint(-12, 18)), "EDF", "Home energy account")
        add("main_account", day(10), -119, "VODAFONE", "Home internet and mobile plan")
        for d, merchant, amount in (
            (6, "NETFLIX", 49),
            (7, "SPOTIFY", 24),
            (13, "MICROSOFT 365", 43),
            (14, "BASIC-FIT", 109),
        ):
            add(
                "main_account",
                day(d),
                -amount,
                merchant,
                "Monthly membership" if merchant == "BASIC-FIT" else "Monthly subscription",
            )
        if m % 2 == 0:
            add("main_account", day(15), -39, "DISNEY+", "Streaming subscription")
        if m in (2, 5, 8):
            add("main_account", day(16), -135, "ADOBE", "Creative Cloud subscription")
        for j, d in enumerate((3, 6, 10, 13, 17, 20, 24, 27)):
            merchant = ("LIDL", "CARREFOUR", "ALDI", "TESCO")[j % 4]
            amount = Decimal(rng.randint(9000, 23000)) * Decimal(str(variation[m - 1])) / 100
            add(
                "main_account",
                day(d),
                -amount,
                merchant,
                "Weekly groceries" if j % 2 == 0 else "Fresh food and household essentials",
            )
        for d in (4, 11, 18, 25):
            add("main_account", day(d), -rng.randint(25, 49), "STARBUCKS", "Coffee and breakfast")
        for d, merchant in (
            (7, "MCDONALD'S"),
            (12, "UBER EATS"),
            (19, "DOMINO'S"),
            (26, "BURGER KING"),
        ):
            add(
                "main_account",
                day(d),
                -rng.randint(48, 135),
                merchant,
                "Dinner with friends" if d == 19 else "Lunch and takeaway",
            )
        for d, merchant in ((8, "SHELL"), (22, "BP")):
            add("main_account", day(d), -rng.randint(210, 360), merchant, "Vehicle fuel | Petrol")
        for d in (5, 15, 23):
            add("main_account", day(d), -rng.randint(12, 36), "Q-PARK", "City parking")
        for d in (9, 21):
            add("main_account", day(d), -rng.randint(22, 64), "UBER", "City ride")
        add("main_account", day(18), -rng.randint(45, 155), "BOOTS", "Pharmacy and personal care")
        if m in (2, 6, 9):
            add(
                "main_account",
                day(17),
                -rng.randint(190, 440),
                "BUPA",
                "Dental and health check-up",
            )
        clothing = ("UNIQLO", "H&M", "NIKE", "ZARA", "ADIDAS")[m % 5]
        if m not in (1, 5, 8):
            add("main_account", day(16), -rng.randint(180, 610), clothing, "Seasonal clothing")
        add("main_account", day(28), -rng.randint(55, 125), "CINEWORLD", "Cinema evening")
        if m % 2:
            add("main_account", day(12), -rng.randint(85, 240), "DECATHLON", "Sports equipment")
        if m in (3, 8):
            add(
                "main_account",
                day(23),
                -rng.randint(220, 550),
                "TICKETMASTER",
                "Live concert tickets",
            )
        if m in (1, 6, 10):
            add("main_account", day(20), -rng.randint(65, 195), "STEAM", "Game purchase")
        for d, person in ((11, "John Smith"), (24, "Emma Johnson")):
            add(
                "main_account",
                day(d),
                -rng.randint(55, 210),
                person,
                f"Phone transfer to {person} | Shared dinner",
            )
        if m % 2 == 0:
            add(
                "main_account",
                day(25),
                rng.randint(45, 120),
                "Michael Brown",
                "Phone repayment from Michael Brown | Shared expenses",
                kind="reimbursement",
            )
        for d, merchant in ((10, "STARBUCKS"), (19, "MCDONALD'S"), (26, "DOMINO'S")):
            add("cash", day(d), -rng.randint(25, 65), merchant, "Cash payment | Food and coffee")
        add(
            "emergency_savings",
            day(28),
            Decimal("46.25") + m * Decimal("2.15"),
            "HSBC",
            "Interest | Savings account",
        )
        add(
            "bonds",
            day(28),
            Decimal("38.50") + m * Decimal("1.80"),
            "VANGUARD | Bond distributions",
            "Bond distribution | Monthly income",
        )
        add(
            "investment_usd",
            day(28),
            Decimal("11.75") + m * Decimal(".65"),
            "VANGUARD | Dividends",
            "Dividend | Portfolio distribution",
        )
        add(
            "investment_usd",
            day(28),
            Decimal("-2.50"),
            "VANGUARD | Brokerage",
            "Brokerage fee | Monthly account fee",
        )
        add("gold_usd", day(28), Decimal("-1.50"), "ISHARES", "Gold custody fee | Monthly charge")
        add(
            "bonds",
            day(28),
            Decimal("-3.50"),
            "VANGUARD | Bond custody",
            "Bond custody fee | Monthly charge",
        )
        add(
            "revolut_travel",
            day(12),
            -rng.randint(7, 16),
            "SPOTIFY",
            "Travel account | Subscription",
        )

    def event(key, month, day, amount, merchant, description, **kwargs):
        return add(key, f"2026-{month:02d}-{day:02d}", amount, merchant, description, **kwargs)

    event("main_account", 1, 21, -899, "IKEA", 'Home office | "BILLY" bookcase and desk lamp')
    event("main_account", 2, 18, -2850, "SAMSUNG", "Electronics order | Home monitor upgrade")
    transfer(
        "emergency_savings", "main_account", "2026-04-17", 22000, "Car purchase reserve release"
    )
    event("main_account", 4, 18, -52000, "TOYOTA", "Vehicle purchase | Pre-owned Toyota Corolla")
    event("main_account", 4, 19, -2180, "ALLIANZ", "Annual car insurance")
    event("main_account", 5, 18, -1390, "MICHELIN", "New tyres | Seasonal replacement")
    event(
        "main_account",
        6,
        15,
        -680,
        "BOSCH CAR SERVICE",
        "Vehicle service | Inspection and oil change",
    )
    event("main_account", 10, 18, -510, "BOSCH CAR SERVICE", "Vehicle service | Autumn maintenance")
    event("main_account", 3, 16, -460, "NIKE", "Clothing order | Running shoes")
    event(
        "main_account",
        3,
        27,
        460,
        "NIKE",
        "Clothing refund | Returned running shoes",
        kind="refund",
    )
    event("main_account", 5, 20, -1299, "AMAZON", "Electronics order | Headphones")
    event(
        "main_account",
        6,
        5,
        1299,
        "AMAZON",
        "Electronics refund | Returned headphones",
        kind="refund",
    )
    event("main_account", 8, 21, -3499, "APPLE", "Electronics order | Laptop replacement")
    event("main_account", 9, 19, -1580, "IKEA", "Home improvements | Storage and lighting")
    transfer("main_account", "revolut_travel", "2026-06-28", 900, "Summer holiday top-up")
    event("revolut_travel", 7, 3, -460, "LUFTHANSA", "Summer holiday | Return flights")
    event("revolut_travel", 7, 5, -1050, "MARRIOTT", "Summer holiday | Seven-night hotel stay")
    event("revolut_travel", 7, 5, -245, "HERTZ", "Summer holiday | Car rental")
    event(
        "revolut_travel", 7, 6, -145, "GETYOURGUIDE", "Summer holiday | City tours and experiences"
    )
    for d in range(5, 13):
        event(
            "revolut_travel",
            7,
            d,
            -rng.randint(15, 38),
            "CARREFOUR",
            "Summer holiday | Food and essentials",
        )
        event(
            "revolut_travel",
            7,
            d,
            -rng.randint(14, 29),
            "STARBUCKS",
            "Summer holiday | Coffee and lunch",
        )
    event("revolut_travel", 7, 10, -61, "SHELL", "Summer holiday | Rental car fuel")
    event("revolut_travel", 9, 10, -95, "RYANAIR", "Autumn city break | Return flights")
    event("revolut_travel", 9, 13, -225, "HILTON", "Autumn city break | Two-night stay")
    event("revolut_travel", 9, 14, -48, "GETYOURGUIDE", "Autumn city break | Museum and city tour")
    for m in (2, 9):
        event(
            "main_account",
            m,
            20,
            -189,
            "UBER",
            "Business trip | Reimbursed separately",
            included=False,
        )
        event(
            "main_account",
            m,
            26,
            189,
            "MICROSOFT PAYROLL",
            "PAYROLL | Travel expense reimbursement",
            kind="reimbursement",
            included=False,
        )
    # Three older Amazon records illustrate a genuinely different reviewed purchase.
    reviewed = event("main_account", 2, 24, "-129.90", "AMAZON", "Home accessory | Desk organizer")
    metadata[reviewed] = dict(
        analysis_kind="standard",
        include_in_reports=True,
        category_path=["Housing", "Furniture and home"],
    )
    for month, day_number, amount, merchant, description in (
        (5, 7, "-89.90", "ETSY", "Home accessory | Handmade print"),
        (6, 19, "-145.00", "EBAY", "Online purchase | Item details pending"),
        (7, 16, "-75.00", "EXPEDIA", "Travel booking | Service charge"),
        (8, 11, "-64.50", "PAYPAL", "Online payment | Merchant details pending"),
        (9, 22, "-49.00", "DROPBOX", "Cloud storage subscription"),
        (10, 29, "-69.00", "ZOOM", "Online meeting subscription"),
    ):
        event("main_account", month, day_number, amount, merchant, description)

    for key, records in ledger.items():
        balance = Decimal(wallets[key]["opening"])
        for record in sorted(records, key=lambda r: (r["date"], r["external_id"])):
            balance += record["amount"]
            if balance < 0:
                raise ValueError(f"Negative showcase balance: {key}, {record['date']}, {balance}")

    EXAMPLE.mkdir(exist_ok=True)
    db = Database(":memory:")
    try:
        populate_starter_categories(db, "en")
        export_category_file(db, EXAMPLE / "config/categories_demo.json")
        save_json(
            EXAMPLE / "config/category_colors.json",
            {
                c["name"]: c["color"]
                for c in db.categories()
                if c["parent_id"] is None and not c["is_default"]
            },
        )
    finally:
        db.close()
    imports = []
    standard = [
        "Date",
        "Amount",
        "Description",
        "Counterparty",
        "Currency",
        "Status",
        "Transaction ID",
        "Balance",
    ]
    main_headers = [
        "Date",
        "Debit",
        "Credit",
        "Description",
        "Counterparty",
        "Currency",
        "Status",
        "Transaction ID",
        "Balance",
    ]
    for key, records in ledger.items():
        balance = Decimal(wallets[key]["opening"])
        for month in MONTHS:
            selected = sorted(
                [r for r in records if r["date"].startswith(month)],
                key=lambda r: (r["date"], r["external_id"]),
            )
            rows = []
            for r in selected:
                balance += r["amount"]
                values = [
                    r["date"],
                    f"{r['amount']:.2f}",
                    r["description"],
                    r["merchant"],
                    r["currency"],
                    "COMPLETED",
                    r["external_id"],
                    f"{balance:.2f}",
                ]
                if key == "main_account":
                    values = [
                        values[0],
                        f"{-r['amount']:.2f}" if r["amount"] < 0 else "",
                        f"{r['amount']:.2f}" if r["amount"] > 0 else "",
                        *values[2:],
                    ]
                rows.append(values)
            relative = f"transactions/{key}/{key}_{month}.csv"
            headers = main_headers if key == "main_account" else standard
            delimiter = ";" if key == "main_account" else ","
            write_csv_and_xlsx(EXAMPLE / relative, headers, rows, wallets[key]["name"], delimiter)
            mapping = dict(
                date="Date",
                description="Description",
                from_to="Counterparty",
                currency="Currency",
                status="Status",
                external_id="Transaction ID",
            )
            if key == "main_account":
                mapping.update(amount_mode="split", debit="Debit", credit="Credit")
            else:
                mapping["amount"] = "Amount"
            imports.append(dict(wallet=key, file=relative, mapping=mapping, delimiter=delimiter))
    selected = sorted(
        [r for r in ledger["cash"] if r["date"].startswith("2026-10")], key=lambda r: r["date"]
    )[:2]
    overlap = [
        [
            r["date"],
            f"{r['amount']:.2f}",
            r["description"],
            r["merchant"],
            "PLN",
            "COMPLETED",
            r["external_id"],
            "",
        ]
        for r in selected
    ]
    overlap += [
        [
            "2026-10-29",
            "-45.10",
            "Additional groceries",
            "LIDL",
            "PLN",
            "COMPLETED",
            "HFC-OVERLAP-001",
            "",
        ],
        [
            "2026-10-30",
            "-17.90",
            "Additional coffee",
            "STARBUCKS",
            "PLN",
            "COMPLETED",
            "HFC-OVERLAP-002",
            "",
        ],
    ]
    write_csv_and_xlsx(
        EXAMPLE / "transactions/scenarios/cash_overlap_2026-10.csv",
        standard,
        overlap,
        "Cash wallet",
        ",",
    )
    validation = [overlap[0], *[list(row) for row in overlap[2:]]]
    validation.append(
        [
            "2026-02-30",
            "not-an-amount",
            "Invalid row for preview only",
            "AMAZON",
            "PLN",
            "COMPLETED",
            "HFC-INVALID",
            "",
        ]
    )
    write_csv_and_xlsx(
        EXAMPLE / "transactions/scenarios/import_validation.csv",
        standard,
        validation,
        "Cash wallet",
        ",",
    )
    quotes = []
    current = date(2026, 1, 1)
    while current <= date(2026, 10, 31):
        if current.weekday() < 5:
            i = (current - date(2026, 1, 1)).days
            quotes.append(
                dict(
                    date=current.isoformat(),
                    EUR=f"{4.3 + 0.075 * math.sin(i / 23):.4f}",
                    USD=f"{4 + 0.11 * math.sin(i / 31) + 0.025 * math.cos(i / 9):.4f}",
                )
            )
        current += timedelta(days=1)
    setup = dict(
        version=2,
        language="en",
        year=2026,
        months=MONTHS,
        person=APP_OWNER,
        wallets=WALLETS,
        imports=imports,
        exchange_rates={"EUR": "4.30", "USD": "4.00"},
        transactions=metadata,
        transfers=transfers,
        rate_history=quotes,
        report_excluded_external_ids=[
            key for key, value in metadata.items() if not value["include_in_reports"]
        ],
        goals=[
            dict(
                name="Emergency fund",
                wallet="emergency_savings",
                target="50000",
                allocated="0",
                mode="wallet",
                deadline="2027-06-30",
            ),
            dict(
                name="Next summer holiday",
                wallet="revolut_travel",
                target="6000",
                allocated="0",
                mode="wallet",
                deadline="2027-07-01",
            ),
            dict(
                name="Investment milestone",
                wallet="investment_usd",
                target="12000",
                allocated="0",
                mode="wallet",
                deadline="2027-12-31",
            ),
            dict(
                name="Home renovation",
                currency="PLN",
                target="30000",
                allocated="8500",
                mode="manual",
                deadline="2027-09-30",
            ),
        ],
    )
    save_json(EXAMPLE / "config/demo_setup.json", setup)
    write_xlsx(
        EXAMPLE / "demo_setup.xlsx",
        [
            (
                "Wallets",
                [["Wallet", "Currency", "Opening balance", "Start date"]]
                + [
                    [w["name"], w["currency"], Decimal(w["opening"]), w["opening_date"]]
                    for w in WALLETS
                ],
                [28, 12, 22, 18],
            ),
            (
                "Imports",
                [["Wallet key", "CSV file"]] + [[i["wallet"], i["file"]] for i in imports],
                [25, 78],
            ),
        ],
    )
    print(
        f"Built {sum(map(len, ledger.values()))} transactions, {len(imports)} monthly imports, 7 wallets and 10 months."
    )
    return setup


def write_csv_and_xlsx(path, headers, rows, wallet, delimiter):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(headers)
        writer.writerows(rows)
    numeric = {i for i, h in enumerate(headers) if h in ("Amount", "Debit", "Credit", "Balance")}
    converted = []
    for row in rows:
        values = []
        for i, value in enumerate(row):
            try:
                values.append(Decimal(value) if i in numeric and str(value).strip() else value)
            except InvalidOperation:
                values.append(value)
        converted.append(values)
    write_xlsx(
        path.with_suffix(".xlsx"),
        [
            (
                "Instructions",
                [
                    ["Field", "Value"],
                    ["Wallet", wallet],
                    ["Import format", "CSV UTF-8; the workbook is for viewing and editing"],
                    ["Data", "Fictional showcase data; not real customer records"],
                ],
                [25, 90],
            ),
            (
                "Transactions",
                [headers, *converted],
                [48 if h in ("Description", "Counterparty") else 20 for h in headers],
            ),
        ],
    )
