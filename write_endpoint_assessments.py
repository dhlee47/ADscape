"""Batch-write endpoint_assessments rows from a JSON file of assessments I
(Claude) produced by directly reading staging/endpoint_source/*.json and
reasoning through classify_prompt.md's endpoint met/significance rubric
myself - see endpoint_backfill_no_api.md. Not a classification script; this
just persists judgments already made in the conversation.

Input JSON shape: a list of objects with outcome_id, met,
statistically_significant, confidence, rationale, source_url.
"""

import json
import sys

from db import connect

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VALID_MET = {"met", "not_met", "mixed", "unknown"}
VALID_SIG = {"yes", "no", "not_reported", "not_applicable"}


def main(path):
    assessments = json.loads(open(path, encoding="utf-8").read())
    conn = connect()

    written = 0
    skipped = 0
    for a in assessments:
        if a.get("met") not in VALID_MET:
            print(f"  SKIP outcome_id={a.get('outcome_id')}: invalid met={a.get('met')!r}")
            skipped += 1
            continue
        if a.get("statistically_significant") not in VALID_SIG:
            print(f"  SKIP outcome_id={a.get('outcome_id')}: invalid statistically_significant={a.get('statistically_significant')!r}")
            skipped += 1
            continue

        conn.execute(
            """
            INSERT INTO endpoint_assessments
                (outcome_id, met, statistically_significant, source_url, confidence, rationale, assessed_by)
            VALUES (?, ?, ?, ?, ?, ?, 'llm')
            """,
            (
                a["outcome_id"],
                a["met"],
                a["statistically_significant"],
                a.get("source_url"),
                a.get("confidence"),
                a.get("rationale"),
            ),
        )
        written += 1

    conn.commit()
    print(f"Wrote {written} endpoint_assessments row(s), skipped {skipped} invalid.")


if __name__ == "__main__":
    main(sys.argv[1])
