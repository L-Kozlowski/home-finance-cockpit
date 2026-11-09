"""Create a NEW synthetic database through the real CSV/classification services."""

import argparse
import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from home_finance_cockpit.domain.validation import money_minor
from home_finance_cockpit.reports.data import ReportOptions, snapshot
from home_finance_cockpit.services.category_files import import_category_file
from home_finance_cockpit.services.importing import commit_import, prepare_import, read_csv
from home_finance_cockpit.services.review import save_review
from home_finance_cockpit.storage import Database


def populate(db, example=ROOT / "example"):
    setup = json.loads((example / "config/demo_setup.json").read_text(encoding="utf-8"))
    wallets, batches = {}, []
    with db.transaction():
        if db.wallets() or db.transactions():
            raise ValueError("The showcase requires a new, empty database.")
        for code, symbol in (("PLN", "zł"), ("EUR", "€"), ("USD", "$")):
            if not any(row["code"] == code for row in db.currencies()):
                db.save_currency(code, symbol)
        for code, rate in setup.get("exchange_rates", {}).items():
            db.save_rate_config(code, "manual", rate)
        import_category_file(db, example / "config/categories_demo.json")
        colors = json.loads((example / "config/category_colors.json").read_text(encoding="utf-8"))
        for name, color in colors.items():
            db.set_category_color(db.find_category(name)["id"], color)
        for wallet in setup["wallets"]:
            wallets[wallet["key"]] = db.save_wallet(
                wallet["name"],
                wallet["opening"],
                wallet["currency"],
                wallet["opening_date"],
                icon_name=wallet["icon"],
            )
        for batch in setup["imports"]:
            file = read_csv(example / batch["file"], delimiter=batch.get("delimiter", "auto"))
            plan = prepare_import(db, file, wallets[batch["wallet"]], batch["mapping"])
            if plan.errors:
                raise ValueError(f"{batch['file']}: {plan.errors}")
            batches.append(
                dict(file=batch["file"], wallet=batch["wallet"], added=commit_import(db, plan))
            )
        excluded = set(setup["report_excluded_external_ids"])
        own_transfers = set(setup.get("own_transfer_descriptions", []))
        for transaction in db.transactions():
            if transaction["external_id"] in excluded:
                db.set_report_inclusion(transaction["id"], False)
            # Demo exchange legs are explicitly reviewed using mapped descriptions;
            # do not depend on retaining an unmapped bank operation-type column.
            if transaction["description"] in own_transfers:
                db.execute(
                    "UPDATE transactions SET analysis_kind='transfer' WHERE id=?",
                    (transaction["id"],),
                )
            settings = setup.get("transactions", {}).get(transaction["external_id"])
            if settings:
                db.set_analysis_kind(transaction["id"], settings["analysis_kind"])
                db.set_report_inclusion(transaction["id"], settings["include_in_reports"])
                if settings.get("category_path"):
                    root_name, child_name = settings["category_path"]
                    root = db.find_category(root_name)
                    child = db.find_category(child_name, root["id"])
                    save_review(
                        db,
                        transaction["id"],
                        child["id"],
                        settings["include_in_reports"],
                        root["color"],
                        classify=True,
                    )
        for goal in setup.get("goals", []):
            db.save_savings_goal(
                goal["name"],
                wallets.get(goal.get("wallet")),
                goal["target"],
                goal["allocated"],
                goal["deadline"],
                calculation_mode=goal["mode"],
                currency=goal.get("currency"),
            )
        # Offline, explicitly synthetic history for the FX-history presentation.
        for code in setup.get("exchange_rates", {}):
            db.store_rate_history(
                code,
                [(quote["date"], quote[code]) for quote in setup.get("rate_history", [])],
                source="manual",
                fetched_at="2026-11-01T12:00:00+00:00",
            )
        db.save_exchange_config(False, 24)
    codes = sorted({w["currency"] for w in setup["wallets"]})
    data = {
        code: snapshot(db, ReportOptions(currency=code, year=setup.get("year", 2026)))
        for code in codes
    }
    rates = {
        "PLN": Decimal(1),
        **{code: Decimal(rate) for code, rate in setup.get("exchange_rates", {}).items()},
    }
    opening = sum(money_minor(w["opening"]) * rates[w["currency"]] for w in setup["wallets"])
    wealth = {}
    for month in setup.get("months", data[codes[0]]["annual_months"]):
        wealth[month] = int(
            opening
            + sum(
                r["amount_minor"] * rates[r["currency"]]
                for r in db.transactions()
                if r["date"][:7] <= month
            )
        )
    return dict(
        transaction_count=len(db.transactions()),
        monthly_wealth_pln_minor=wealth,
        imports=batches,
        wallets=[
            dict(id=w["id"], name=w["name"], currency=w["currency"], balance_minor=w["balance"])
            for w in db.wallet_balances()
        ],
        reports={
            code: {
                m: {
                    k: data[code]["summaries"][m][k]
                    for k in ("inflows", "expenses", "net", "user_excluded_count")
                }
                for m in data[code]["annual_months"]
            }
            for code in data
        },
    )


def main():
    from home_finance_cockpit.localization import set_language

    set_language("en")
    parser = argparse.ArgumentParser(
        description="Create a new example Home Finance Cockpit database; never overwrite a file."
    )
    parser.add_argument("--output", type=Path, default=ROOT / "data/home_finance_demo.db")
    parser.add_argument("--summary", type=Path, help="Optional JSON summary of synthetic totals")
    args = parser.parse_args()
    try:
        db = Database.create_new(args.output)
        try:
            summary = populate(db)
        finally:
            db.close()
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"Created {args.output.resolve()} ({summary['transaction_count']} transactions)")


if __name__ == "__main__":
    main()
