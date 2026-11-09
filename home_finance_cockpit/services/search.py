"""Search visible transaction fields without changing the stored source data."""

import unicodedata

from home_finance_cockpit.domain.analysis_kinds import ANALYSIS_KINDS
from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr


def normalize(value):
    decomposed = unicodedata.normalize("NFKD", str(value).casefold().replace("ł", "l"))
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def search_transactions(rows, query):
    terms = normalize(query).split()
    if not terms:
        return list(rows)
    result = []
    for row in rows:
        fields = [
            str(row[key] or "")
            for key in (
                "date",
                "wallet",
                "from_to",
                "category",
                "subcategory",
                "currency",
                "description",
            )
        ]
        if "analysis_kind" in row.keys():
            caption = ANALYSIS_KINDS.get(row["analysis_kind"], "")
            fields.extend((caption, tr(caption)))
        amount = amount_label(row["amount_minor"])
        plain_amount = amount.replace(" ", "")
        fields.extend(
            (
                amount,
                plain_amount,
                plain_amount.replace(".", ","),
                "wydatek expense" if row["amount_minor"] < 0 else "wpływ income",
            )
        )
        searchable = normalize(" ".join(fields))
        if all(term in searchable for term in terms):
            result.append(row)
    return result
