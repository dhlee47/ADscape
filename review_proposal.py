"""ADscape proposal review CLI: accept or reject curator_agent.py's pending
taxonomy proposals. See curator_agent_prompt.md - proposals are never
auto-applied; this is the human-reviewed merge step.

accept:
  1. Merges the candidate_bucket into taxonomy.json (inserted just before
     'unclassified', taxonomy.json's version patch bumped) and into
     mechanism_buckets (source='curator_proposal', so it's distinguishable
     from the hand-authored 'seed' buckets).
  2. Marks the taxonomy_proposals row 'accepted'.
  3. Resets the proposal's supporting trials to bucket_id=NULL and
     reclassifies them (classify.py's own logic, reused) against the now-
     expanded taxonomy - the classifier re-evaluates each trial fresh
     rather than blindly trusting the curator's cluster.

reject: marks the row 'rejected'. Nothing else touched.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from classify import build_summary, classify_one, load_taxonomy_for_prompt
from db import init_db

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"
NCT_RE = re.compile(r"NCT\d{8}")
BUCKET_FIELDS = ("description", "pubmed_query", "trial_keywords", "preclinical_terms", "representative_agents")


def list_pending(conn):
    rows = conn.execute(
        "SELECT id, proposed_bucket_json, rationale, proposed_at FROM taxonomy_proposals "
        "WHERE status = 'pending' ORDER BY id"
    ).fetchall()
    if not rows:
        print("No pending proposals.")
        return
    for r in rows:
        cb = json.loads(r["proposed_bucket_json"])
        print(f"[{r['id']}] {cb['id']} - {cb['description']}")
        print(f"      proposed_at={r['proposed_at']}")
        print(f"      rationale: {r['rationale']}")


def _extract_nct_ids(supporting_items_json):
    items = json.loads(supporting_items_json or "[]")
    ids = []
    for item in items:
        m = NCT_RE.search(item)
        if m:
            ids.append(m.group(0))
    return ids


def _load_proposal(conn, proposal_id):
    row = conn.execute("SELECT * FROM taxonomy_proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        print(f"No proposal with id={proposal_id}.")
        sys.exit(1)
    if row["status"] != "pending":
        print(f"Proposal {proposal_id} is already '{row['status']}', not pending - nothing to do.")
        sys.exit(1)
    return row


def reject(conn, proposal_id):
    row = _load_proposal(conn, proposal_id)
    conn.execute(
        "UPDATE taxonomy_proposals SET status = 'rejected', reviewed_at = datetime('now') WHERE id = ?",
        (proposal_id,),
    )
    conn.commit()
    cb = json.loads(row["proposed_bucket_json"])
    print(f"Rejected proposal {proposal_id} ({cb['id']}). taxonomy.json and trials untouched.")


def _merge_into_taxonomy_json(bucket_id, candidate_bucket):
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    bucket_entry = {k: candidate_bucket.get(k) for k in BUCKET_FIELDS}

    new_buckets = {}
    inserted = False
    for key, value in taxonomy["buckets"].items():
        if key == "unclassified" and not inserted:
            new_buckets[bucket_id] = bucket_entry
            inserted = True
        new_buckets[key] = value
    if not inserted:
        new_buckets[bucket_id] = bucket_entry
    taxonomy["buckets"] = new_buckets

    parts = taxonomy.get("version", "0.1.0").split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    taxonomy["version"] = ".".join(parts)

    TAXONOMY_PATH.write_text(json.dumps(taxonomy, indent=2) + "\n", encoding="utf-8")
    return taxonomy["version"], bucket_entry


def accept(conn, client, proposal_id):
    row = _load_proposal(conn, proposal_id)
    candidate_bucket = json.loads(row["proposed_bucket_json"])
    bucket_id = candidate_bucket["id"]

    if conn.execute("SELECT 1 FROM mechanism_buckets WHERE bucket_id = ?", (bucket_id,)).fetchone():
        print(f"bucket_id '{bucket_id}' already exists in mechanism_buckets - resolve manually "
              f"(rename in the proposal, or reject it) before accepting.")
        sys.exit(1)

    # 1. taxonomy.json is the source of truth (db.py's init_db() reloads mechanism_buckets
    # from it on every run) - merge there first, then mirror into the db directly.
    version, bucket_entry = _merge_into_taxonomy_json(bucket_id, candidate_bucket)
    print(f"Added '{bucket_id}' to taxonomy.json (version -> {version}).")

    # db.py's _load_taxonomy() always stamps fresh inserts source='seed', which would lose
    # the seed-vs-curator-proposal provenance distinction schema.sql's own comment calls
    # for - insert directly instead (safe: we just confirmed no existing row above).
    conn.execute(
        """
        INSERT INTO mechanism_buckets
            (bucket_id, description, pubmed_query, trial_keywords, preclinical_terms, representative_agents, source)
        VALUES (?, ?, ?, ?, ?, ?, 'curator_proposal')
        """,
        (
            bucket_id,
            bucket_entry["description"],
            bucket_entry.get("pubmed_query"),
            json.dumps(bucket_entry.get("trial_keywords") or []),
            json.dumps(bucket_entry.get("preclinical_terms") or []),
            json.dumps(bucket_entry.get("representative_agents") or []),
        ),
    )

    conn.execute(
        "UPDATE taxonomy_proposals SET status = 'accepted', reviewed_at = datetime('now') WHERE id = ?",
        (proposal_id,),
    )
    conn.commit()
    print(f"Marked proposal {proposal_id} accepted.")

    # 2. reclassify exactly the supporting trials against the now-expanded taxonomy -
    # other unclassified trials that might also fit this bucket are left alone (they'll
    # be picked up by a future classify.py/curator_agent.py run, not this one).
    nct_ids = _extract_nct_ids(row["supporting_items"])
    if not nct_ids:
        print("No supporting NCT ids parsed from the proposal - nothing to reclassify.")
        return

    placeholders = ",".join("?" for _ in nct_ids)
    trials = conn.execute(
        f"SELECT nct_id, brief_title, official_title, conditions FROM trials WHERE nct_id IN ({placeholders})",
        nct_ids,
    ).fetchall()
    missing = set(nct_ids) - {t["nct_id"] for t in trials}
    if missing:
        print(f"Warning: {len(missing)} supporting NCT id(s) not found in trials table: {sorted(missing)}")

    taxonomy_for_prompt = load_taxonomy_for_prompt(conn)
    valid_bucket_ids = {b["id"] for b in taxonomy_for_prompt} | {"unclassified"}
    taxonomy_json = json.dumps(taxonomy_for_prompt, indent=2)

    print(f"Reclassifying {len(trials)} supporting trial(s) against the updated taxonomy...")
    landed_in_new_bucket = 0
    for i, trial in enumerate(trials, 1):
        summary = build_summary(conn, trial)
        try:
            result = classify_one(client, taxonomy_json, trial["brief_title"], summary)
        except Exception as exc:
            print(f"  [{i}/{len(trials)}] {trial['nct_id']}: ERROR - {exc}")
            continue

        result_bucket = result.get("bucket_id") or "unclassified"
        if result_bucket not in valid_bucket_ids:
            result_bucket = "unclassified"
        confidence = result.get("confidence")
        rationale = result.get("rationale", "")
        if result_bucket == bucket_id:
            landed_in_new_bucket += 1

        print(f"  [{i}/{len(trials)}] {trial['nct_id']}: {result_bucket} (conf={confidence}) - {rationale}")
        conn.execute(
            "UPDATE trials SET bucket_id = ?, classification_confidence = ?, classification_rationale = ? WHERE nct_id = ?",
            (result_bucket, confidence, rationale, trial["nct_id"]),
        )
        conn.commit()

    print(
        f"\nDone. {landed_in_new_bucket}/{len(trials)} supporting trials landed in '{bucket_id}'; "
        f"any others were reclassified independently rather than force-fit (the classifier "
        f"re-evaluates each trial fresh instead of trusting the curator's cluster blindly)."
    )


def main():
    parser = argparse.ArgumentParser(description="Review pending ADscape taxonomy proposals.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List pending proposals.")
    p_accept = sub.add_parser("accept", help="Accept a proposal: merge into taxonomy.json and reclassify its supporting trials.")
    p_accept.add_argument("id", type=int)
    p_reject = sub.add_parser("reject", help="Reject a proposal - marks it rejected, no other changes.")
    p_reject.add_argument("id", type=int)
    args = parser.parse_args()

    conn = init_db()

    if args.command == "list":
        list_pending(conn)
    elif args.command == "reject":
        reject(conn, args.id)
    elif args.command == "accept":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY not set - put it in .env.")
            sys.exit(1)
        accept(conn, anthropic.Anthropic(), args.id)


if __name__ == "__main__":
    main()
