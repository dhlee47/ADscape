"""ADscape classification CLI: assign unclassified trials to a mechanism bucket
(Haiku). See classify_prompt.md for the spec this implements (mechanism-bucket
task only - the modality-classification task in that file is a separate,
not-yet-built step keyed on intervention name rather than trial).
"""

import argparse
import json
import os
import sys
import time

import anthropic
from dotenv import load_dotenv

from db import init_db

load_dotenv()

# Windows defaults stdout/stderr to the OS ANSI codepage (cp1252) even when
# redirected to a file, which raises UnicodeEncodeError on trial titles
# containing characters like 'alpha' (Greek). Force UTF-8 so a crash here
# can't silently drop uncommitted classifications.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 150
COMMIT_EVERY = 1
MAX_RETRIES = 5
LOW_CONFIDENCE_THRESHOLD = 0.4

# Copied verbatim from classify_prompt.md's "System prompt" block (mechanism-
# bucket task) - keep in sync if that file changes.
SYSTEM_PROMPT = """You are a classification component in an Alzheimer's disease research monitoring pipeline. Your only job is to assign one incoming item (a paper, preprint, or clinical trial record) to the single best-fitting mechanism bucket from a fixed taxonomy, or flag it as unclassified.

You will be given:
1. The current taxonomy (bucket id, description, and representative agents for each bucket)
2. One item to classify: its source type (literature / preprint / trial), title, and abstract or summary

Rules:
- Choose exactly one bucket_id from the taxonomy that best matches the item's primary mechanism of action or research focus.
- If the item does not clearly fit any bucket, do not force it. Return bucket_id = "unclassified" instead.
- If unclassified, extract the specific drug name, gene/protein target, or mechanism term that is driving the mismatch, in candidate_entity.
- Do not classify based on the disease indication alone (everything here is already Alzheimer's-related) - classify based on mechanism.
- Confidence should reflect how central the mechanism is to the item, not how well-written the abstract is. A trial that only mentions a mechanism in passing should get lower confidence than one where it's the primary intervention.
- Be terse. rationale must be one sentence, under 25 words.

Output ONLY valid JSON, no other text, matching this schema:
{
  "bucket_id": "<taxonomy bucket id, or 'unclassified'>",
  "confidence": <float 0.0-1.0>,
  "candidate_entity": "<only if unclassified, else null>",
  "rationale": "<one sentence, under 25 words>"
}"""


def load_taxonomy_for_prompt(conn):
    """Per classify_prompt.md's implementation notes: id, description, and
    representative_agents only - the other fields are for ingestion
    filtering, not classification, and just add token cost here."""
    rows = conn.execute(
        "SELECT bucket_id, description, representative_agents FROM mechanism_buckets "
        "WHERE bucket_id != 'unclassified'"
    ).fetchall()
    return [
        {
            "id": row["bucket_id"],
            "description": row["description"],
            "representative_agents": json.loads(row["representative_agents"] or "[]"),
        }
        for row in rows
    ]


def build_summary(conn, trial):
    """Trials aren't ingested with a free-text abstract (descriptionModule
    was never mapped in api_source.md), so synthesize a summary from the
    structured fields that actually drive mechanism - interventions,
    conditions, and primary outcomes."""
    nct_id = trial["nct_id"]
    interventions = conn.execute(
        "SELECT name, type FROM interventions WHERE nct_id = ?", (nct_id,)
    ).fetchall()
    outcomes = conn.execute(
        "SELECT measure FROM outcomes WHERE nct_id = ? AND outcome_type = 'primary'", (nct_id,)
    ).fetchall()
    conditions = json.loads(trial["conditions"] or "[]")

    parts = []
    if trial["official_title"] and trial["official_title"] != trial["brief_title"]:
        parts.append(f"Official title: {trial['official_title']}")
    if conditions:
        parts.append(f"Conditions: {', '.join(conditions)}")
    if interventions:
        iv = "; ".join(f"{i['name']} ({i['type']})" for i in interventions if i["name"])
        if iv:
            parts.append(f"Interventions: {iv}")
    if outcomes:
        oc = "; ".join(o["measure"] for o in outcomes if o["measure"])
        if oc:
            parts.append(f"Primary outcomes: {oc}")

    return "\n".join(parts) if parts else "(no additional structured data available)"


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def classify_one(client, taxonomy_json, title, summary):
    user_message = (
        f"TAXONOMY:\n{taxonomy_json}\n\n"
        f"ITEM TO CLASSIFY:\nsource_type: trial\ntitle: {title}\nsummary: {summary}"
    )
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return _extract_json(resp.content[0].text)
        except anthropic.RateLimitError as exc:
            last_exc = exc
            time.sleep(2**attempt)
        except (anthropic.APIStatusError, anthropic.APIConnectionError, json.JSONDecodeError) as exc:
            last_exc = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"classify_one failed after {MAX_RETRIES} attempts: {last_exc}")


def cmd_classify(limit=None, dry_run=False):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set - put it in .env.")
        sys.exit(1)

    conn = init_db()
    client = anthropic.Anthropic()

    taxonomy = load_taxonomy_for_prompt(conn)
    valid_bucket_ids = {b["id"] for b in taxonomy} | {"unclassified"}
    taxonomy_json = json.dumps(taxonomy, indent=2)

    query = "SELECT nct_id, brief_title, official_title, conditions FROM trials WHERE bucket_id IS NULL"
    if limit:
        query += f" LIMIT {int(limit)}"
    trials = conn.execute(query).fetchall()

    print(f"{len(trials)} unclassified trial(s) to process{' (dry run)' if dry_run else ''}.")

    counts = {"classified": 0, "low_confidence": 0, "unclassified": 0, "errors": 0}
    for i, trial in enumerate(trials, 1):
        summary = build_summary(conn, trial)
        try:
            result = classify_one(client, taxonomy_json, trial["brief_title"], summary)
        except Exception as exc:
            print(f"  [{i}/{len(trials)}] {trial['nct_id']}: ERROR - {exc}")
            counts["errors"] += 1
            continue

        bucket_id = result.get("bucket_id") or "unclassified"
        if bucket_id not in valid_bucket_ids:
            result["rationale"] = f"{result.get('rationale', '')} [invalid bucket_id from model: {bucket_id}]"
            bucket_id = "unclassified"

        confidence = result.get("confidence")
        rationale = result.get("rationale", "")
        candidate_entity = result.get("candidate_entity")
        if bucket_id == "unclassified" and candidate_entity:
            rationale = f"{rationale} [candidate_entity: {candidate_entity}]"

        if bucket_id == "unclassified":
            counts["unclassified"] += 1
        elif confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
            counts["low_confidence"] += 1
        else:
            counts["classified"] += 1

        print(f"  [{i}/{len(trials)}] {trial['nct_id']}: {bucket_id} (conf={confidence}) - {rationale}")

        if not dry_run:
            conn.execute(
                "UPDATE trials SET bucket_id = ?, classification_confidence = ?, "
                "classification_rationale = ? WHERE nct_id = ?",
                (bucket_id, confidence, rationale, trial["nct_id"]),
            )
            if i % COMMIT_EVERY == 0:
                conn.commit()

    if not dry_run:
        conn.commit()

    print(
        f"\nDone. classified={counts['classified']} low_confidence={counts['low_confidence']} "
        f"unclassified={counts['unclassified']} errors={counts['errors']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify unclassified ADscape trials by mechanism bucket.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N unclassified trials.")
    parser.add_argument("--dry-run", action="store_true", help="Classify but don't write results to the DB.")
    args = parser.parse_args()
    cmd_classify(limit=args.limit, dry_run=args.dry_run)
