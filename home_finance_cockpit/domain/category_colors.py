"""Optional root-category colors, shared by the ledger and report snapshots."""

import re

from home_finance_cockpit.localization import tr

PALETTE = (
    (None, "Brak koloru"),
    ("#22D3EE", "Cyjanowy"),
    ("#3B82F6", "Błękitny"),
    ("#8B5CF6", "Lawendowy"),
    ("#F59E0B", "Złoty"),
    ("#10B981", "Zielony"),
    ("#EF4444", "Czerwony"),
    ("#06B6D4", "Turkusowy"),
    ("#7B8FA6", "Szaroniebieski"),
)


def validate_color(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(tr("Kolor musi mieć format #RRGGBB lub oznaczać brak koloru."))
    return value.upper()
