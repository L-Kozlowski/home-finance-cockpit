"""Atomic review edits without changing transaction amounts or import provenance."""

from home_finance_cockpit.domain.category_colors import validate_color
from home_finance_cockpit.localization import tr


def save_review(
    db,
    transaction_id,
    category_id,
    included,
    color,
    *,
    classify=False,
    expected=None,
    expected_color=...,
    analysis_kind=None,
):
    color = validate_color(color)
    if not isinstance(included, bool):
        raise ValueError(tr("Wybór udziału w raportach musi być wartością tak/nie."))
    with db.transaction():
        current = db.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()
        if current is None:
            raise ValueError(tr("Transakcja już nie istnieje. Odśwież listę."))
        if expected is not None and any(
            current[key] != expected[key]
            for key in (
                "category_id",
                "category_source",
                "matched_rule_id",
                "category_conflict",
                "include_in_reports",
                "analysis_kind",
            )
        ):
            raise ValueError(
                tr("Transakcja została zmieniona. Anuluj edycję i otwórz ją ponownie.")
            )
        category = db.category(category_id)
        root = db.category(category["parent_id"] or category["id"])
        if (
            expected_color is not Ellipsis
            and root["color"] != expected_color
            and color != root["color"]
        ):
            raise ValueError(
                tr("Kolor kategorii został zmieniony. Anuluj edycję i otwórz ją ponownie.")
            )
        db.set_category_color(root["id"], color)
        if classify or current["category_id"] != category_id:
            db.execute(
                """UPDATE transactions SET category_id=?,category_source='manual',
                          matched_rule_id=NULL,category_conflict=0 WHERE id=?""",
                (category_id, transaction_id),
            )
        db.set_report_inclusion(transaction_id, included)
        if analysis_kind is not None:
            db.set_analysis_kind(transaction_id, analysis_kind)
