"""Strict parsing at every entry point; money is stored as integer minor units."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from home_finance_cockpit.localization import tr

MAX_MINOR = 10**15


def text(value, label="Wartość", *, required=True, limit=500):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(tr("{v0}: oczekiwano tekstu.", v0=tr(label)))
    value = value.strip()
    if required and not value:
        raise ValueError(tr("{v0}: pole jest wymagane.", v0=tr(label)))
    if len(value) > limit or "\x00" in value:
        raise ValueError(
            tr(
                "{v0}: nieprawidłowy tekst lub przekroczono limit {v1} znaków.",
                v0=tr(label),
                v1=limit,
            )
        )
    return value


def currency_code(value):
    value = text(value, "Kod waluty").upper()
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError(tr("Kod waluty musi składać się z 3 liter A–Z."))
    return value


def money_minor(value):
    """Accept a decimal comma or dot, and correctly grouped thousands.

    Supported wallets use currencies with two decimal places. Ambiguous values
    with three decimals are rejected rather than silently rounded.
    """
    raw = str(value).strip().replace("\u2212", "-")
    raw = raw.replace("\u00a0", " ").replace("\u202f", " ")
    if " " in raw:
        if not re.fullmatch(r"[+-]?\d{1,3}(?: \d{3})+(?:[.,]\d{1,2})?", raw):
            raise ValueError(tr("Nieprawidłowe grupowanie cyfr w kwocie."))
        raw = raw.replace(" ", "")
    if "," in raw and "." in raw:
        decimal_sep = "," if raw.rfind(",") > raw.rfind(".") else "."
        group_sep = "." if decimal_sep == "," else ","
        if not re.fullmatch(
            r"[+-]?\d{1,3}(?:"
            + re.escape(group_sep)
            + r"\d{3})+"
            + re.escape(decimal_sep)
            + r"\d{1,2}",
            raw,
        ):
            raise ValueError(tr("Nieprawidłowy format kwoty."))
        raw = raw.replace(group_sep, "").replace(decimal_sep, ".")
    else:
        raw = raw.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d{1,2})?", raw):
        raise ValueError(tr("Kwota musi być liczbą z maksymalnie dwoma miejscami po przecinku."))
    try:
        result = int(Decimal(raw) * 100)
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError(tr("Nieprawidłowa kwota.")) from None
    if abs(result) > MAX_MINOR:
        raise ValueError(tr("Kwota przekracza dopuszczalny zakres."))
    return result


def iso_date(value):
    value = text(value, "Data", limit=40)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y", "%d-%m-%Y", "%Y.%m.%d"):
            try:
                parsed = datetime.strptime(value, fmt).date()
                break
            except ValueError:
                pass
        else:
            raise ValueError(tr("Nieobsługiwana lub niepoprawna data: {v0}", v0=value)) from None
    return parsed.isoformat()


def date_range(start=None, end=None):
    start = iso_date(start) if start else None
    end = iso_date(end) if end else None
    if start and end and start > end:
        raise ValueError(tr("Data początkowa nie może być późniejsza od końcowej."))
    return start, end


def amount_label(minor, currency=""):
    sign = "-" if minor < 0 else ""
    whole, cents = divmod(abs(minor), 100)
    grouped = f"{whole:,}".replace(",", " ")
    return f"{sign}{grouped}.{cents:02d}" + (f" {currency}" if currency else "")
