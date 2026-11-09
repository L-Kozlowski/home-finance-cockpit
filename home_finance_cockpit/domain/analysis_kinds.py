"""Explicit transaction meaning; incoming money is not automatically a refund."""

from home_finance_cockpit.localization import tr

ANALYSIS_KINDS = {
    "standard": "Zwykła operacja",
    "salary": "Pensja / wynagrodzenie",
    "refund": "Zwrot zakupu",
    "reimbursement": "Rozliczenie od innej osoby",
    "transfer": "Przelew własny",
}
REFUND_KINDS = {"refund", "reimbursement"}


def cost_contribution(amount, kind="standard", after_refunds=False):
    if kind == "transfer":
        return 0
    return -amount if amount < 0 or (after_refunds and kind in REFUND_KINDS) else 0


def validate_analysis_kind(kind, amount):
    if not isinstance(kind, str) or kind not in ANALYSIS_KINDS:
        raise ValueError(tr("Nieprawidłowy charakter transakcji."))
    if kind in REFUND_KINDS | {"salary"} and amount <= 0:
        raise ValueError(
            tr(
                "Pensja, zwrot i rozliczenie muszą być wpływami. Dla wypływu wybierz zwykłą operację lub przelew własny."
            )
        )
    return kind
