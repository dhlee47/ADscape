"""ADscape regulatory-status hand-curation. Per schema.sql's own comment:
deliberately NOT LLM-inferred - the set of FDA-approved AD drugs is small
and well-known, worth getting exactly right by hand rather than delegating.

Only tags trials whose intervention list includes one of the small set of
approved/discontinued AD drugs below (matched case-insensitively as a name
substring, so combination-product and dosage-variant names still match, e.g.
"Aricept (donepezil IR 10 mg)" matches the donepezil pattern). Every other
trial's regulatory_status is left NULL - this list is not an attempt to also
hand-classify "not_approved"/"pending_review" for the much larger set of
experimental compounds, which is exactly the kind of large/low-value-per-item
classification schema.sql says to avoid doing by hand.

Known status as of this writing (verify before reusing after a large gap -
this list goes stale as new approvals/withdrawals happen):
  - lecanemab (Leqembi) - FDA full approval, July 2023
  - donanemab (Kisunla) - FDA approval, July 2024
  - aducanumab (Aduhelm) - discontinued: Biogen withdrew it from the market
    in Jan 2024 (had accelerated approval 2021-2024)
  - donepezil (Aricept), memantine (Namenda), rivastigmine (Exelon),
    galantamine (Razadyne/Reminyl) - long-approved symptomatic drugs, all
    generic
"""

import sys
from datetime import datetime, timezone

from db import init_db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (name substring, regulatory_status) - checked in order, first match wins
KNOWN_DRUGS = [
    ("lecanemab", "approved"),
    ("donanemab", "approved"),
    ("aducanumab", "discontinued"),
    ("donepezil", "approved"),
    ("memantine", "approved"),
    ("rivastigmine", "approved"),
    ("galantamine", "approved"),
    ("tacrine", "discontinued"),  # withdrawn for hepatotoxicity; kept even though
                                   # no matching trials in this corpus as of writing
]


def main():
    conn = init_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    total_tagged = 0
    for pattern, status in KNOWN_DRUGS:
        nct_ids = [
            r["nct_id"]
            for r in conn.execute(
                "SELECT DISTINCT nct_id FROM interventions WHERE lower(name) LIKE ?",
                (f"%{pattern.lower()}%",),
            ).fetchall()
        ]
        if not nct_ids:
            print(f"{pattern}: 0 trials found")
            continue

        placeholders = ",".join("?" for _ in nct_ids)
        conn.execute(
            f"""
            UPDATE trials
            SET regulatory_status = ?, regulatory_status_source = 'human', regulatory_status_updated_at = ?
            WHERE nct_id IN ({placeholders}) AND regulatory_status IS NULL
            """,
            [status, now] + nct_ids,
        )
        print(f"{pattern}: {len(nct_ids)} trial(s) tagged '{status}'")
        total_tagged += len(nct_ids)

    conn.commit()

    remaining = conn.execute(
        "SELECT COUNT(*) AS c FROM trials WHERE regulatory_status IS NOT NULL"
    ).fetchone()["c"]
    print(f"\nDone. {remaining} trial(s) now have a hand-curated regulatory_status "
          f"({total_tagged} match events across the known-drug list - some trials "
          f"match more than one pattern, e.g. donepezil+memantine combination trials).")


if __name__ == "__main__":
    main()
