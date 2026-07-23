"""ADscape curator agent CLI: cluster unclassified/low-confidence trials and
propose taxonomy changes for human review. See curator_agent_prompt.md for the
spec this implements (production-run template; never auto-applies proposals).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from db import init_db

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-sonnet-5"  # curator_agent_prompt.md: "Run this on Sonnet, not Haiku"
MAX_TOKENS = 32000  # generous headroom - adaptive thinking + high effort over ~1,250 items
LOW_CONFIDENCE_MIN = 0.4
LOW_CONFIDENCE_MAX = 0.7

# Mechanism proposals only make sense for pharmacological/biological
# interventions - a behavioral, device, procedure, or diagnostic trial can
# never clear the curator's own bar (a "mechanism" bucket). Filtering to
# trials with at least one such intervention cuts token cost by ~65% on this
# corpus and removes noise the curator would otherwise have to sift through
# and correctly ignore every single run.
MECHANISM_CANDIDATE_TYPES = ("drug", "biological", "genetic", "combination_product", "dietary_supplement")

SYSTEM_PROMPT = """You are a taxonomy curator for an Alzheimer's disease research monitoring pipeline. Every week you review the items the classification model could not confidently place into the existing mechanism taxonomy, and decide whether they represent noise or a genuine emerging pattern worth adding as a new bucket.

You will be given:
1. The current taxonomy (for context, so you don't propose something that already exists)
2. A list of unclassified and low-confidence items from the trailing window: each with source_type, title, summary, candidate_entity (if provided), and date

Your task:
1. Cluster the items by underlying mechanism/target, not by surface keyword. Two items mentioning different drug names can be the same cluster if they share a mechanism (e.g. two different GLP-1 agonists). Two items mentioning the same word can be different clusters if the mechanism differs.
2. For each cluster, apply the recurrence threshold: propose a new bucket ONLY if the cluster has at least 2 items from at least 2 independent sources (source independence = different source_type, OR different originating trial/paper, not just two mentions in one press release echoed elsewhere).
3. For clusters that clear the threshold, draft a full bucket definition in the exact schema used in taxonomy.json (id, description, pubmed_query, trial_keywords, preclinical_terms, representative_agents), so it can be reviewed and pasted in directly if approved.
4. For clusters that don't clear the threshold, do not propose anything - just note the entity as "watching" so it can accumulate across future weekly runs instead of being lost.
5. Never modify taxonomy.json yourself. Output proposals only. A human reviews and merges.

Be conservative. A missed pattern costs one more week of waiting. A false pattern proposed as a bucket costs a human's review time and, if wrongly accepted, degrades the taxonomy for everyone downstream. When uncertain, under-propose.

Output ONLY valid JSON, no other text, matching this schema:
{
  "proposals": [
    {
      "candidate_bucket": { "id": "...", "description": "...", "pubmed_query": "...", "trial_keywords": [...], "preclinical_terms": [...], "representative_agents": [...] },
      "supporting_items": ["<item ids or titles>"],
      "source_diversity": "<brief note on why these count as independent sources>",
      "rationale": "<2-3 sentences on why this clears the bar>"
    }
  ],
  "watching": [
    { "entity": "...", "item_count": <int>, "note": "<why it's not there yet>" }
  ]
}"""

CANDIDATE_ENTITY_RE = re.compile(r"\[candidate_entity:\s*(.+?)\]\s*$")


def load_full_taxonomy(conn):
    rows = conn.execute(
        "SELECT bucket_id, description, pubmed_query, trial_keywords, preclinical_terms, representative_agents "
        "FROM mechanism_buckets WHERE bucket_id != 'unclassified'"
    ).fetchall()
    return [
        {
            "id": row["bucket_id"],
            "description": row["description"],
            "pubmed_query": row["pubmed_query"],
            "trial_keywords": json.loads(row["trial_keywords"] or "[]"),
            "preclinical_terms": json.loads(row["preclinical_terms"] or "[]"),
            "representative_agents": json.loads(row["representative_agents"] or "[]"),
        }
        for row in rows
    ]


def fetch_review_items(conn):
    rows = conn.execute(
        f"""
        SELECT DISTINCT t.nct_id, t.brief_title, t.official_title, t.conditions,
               t.bucket_id, t.classification_confidence, t.classification_rationale,
               t.start_date, t.registry_last_updated
        FROM trials t
        JOIN interventions i ON i.nct_id = t.nct_id
        WHERE (t.bucket_id = 'unclassified'
               OR (t.classification_confidence >= {LOW_CONFIDENCE_MIN} AND t.classification_confidence < {LOW_CONFIDENCE_MAX}))
          AND i.type IN ({','.join('?' for _ in MECHANISM_CANDIDATE_TYPES)})
        ORDER BY t.nct_id
        """,
        MECHANISM_CANDIDATE_TYPES,
    ).fetchall()

    items = []
    for t in rows:
        interventions = conn.execute(
            "SELECT name, type FROM interventions WHERE nct_id = ?", (t["nct_id"],)
        ).fetchall()
        iv_str = "; ".join(f"{i['name']} ({i['type']})" for i in interventions if i["name"])
        conditions = json.loads(t["conditions"] or "[]")

        summary_parts = []
        if t["official_title"] and t["official_title"] != t["brief_title"]:
            summary_parts.append(f"Official title: {t['official_title']}")
        if conditions:
            summary_parts.append(f"Conditions: {', '.join(conditions)}")
        if iv_str:
            summary_parts.append(f"Interventions: {iv_str}")
        if t["bucket_id"] == "unclassified":
            summary_parts.append(f"Classifier rationale: {t['classification_rationale']}")
        elif t["classification_confidence"] is not None:
            summary_parts.append(
                f"Classifier tentatively placed this in '{t['bucket_id']}' at confidence "
                f"{t['classification_confidence']:.2f}: {t['classification_rationale']}"
            )

        candidate_entity = None
        if t["classification_rationale"]:
            m = CANDIDATE_ENTITY_RE.search(t["classification_rationale"])
            if m:
                candidate_entity = m.group(1)

        items.append(
            {
                "item_id": t["nct_id"],
                "source_type": "trial",
                "title": t["brief_title"],
                "summary": " ".join(summary_parts) if summary_parts else "(no additional structured data available)",
                "candidate_entity": candidate_entity,
                "date": t["start_date"] or t["registry_last_updated"],
            }
        )
    return items


def load_watching(conn):
    return [dict(r) for r in conn.execute(
        "SELECT entity, item_count, note FROM curator_watchlist ORDER BY item_count DESC"
    ).fetchall()]


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def run_curator(conn, client, dry_run=False):
    taxonomy = load_full_taxonomy(conn)
    items = fetch_review_items(conn)
    watching_prior = load_watching(conn)

    print(f"{len(items)} unclassified/low-confidence trial(s) with a pharmacological/biological "
          f"intervention to review, plus {len(watching_prior)} entities already on the watchlist.")

    user_message = (
        "CURRENT TAXONOMY (for context - do not re-propose these):\n"
        f"{json.dumps(taxonomy, indent=2)}\n\n"
        "UNCLASSIFIED / LOW-CONFIDENCE ITEMS (trailing 7 days, plus anything still \"watching\" from prior weeks):\n"
        f"{json.dumps({'items': items, 'already_watching': watching_prior}, indent=2)}"
    )

    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        message = stream.get_final_message()

    print(f"stop_reason={message.stop_reason} output_tokens={message.usage.output_tokens}")

    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"No text content in curator response (stop_reason={message.stop_reason})")

    # Save raw output before attempting to parse - a parse failure here would
    # otherwise lose the (expensive, ~3.5min) response entirely.
    raw_path = Path(__file__).parent / "curator_last_response.txt"
    raw_path.write_text(text, encoding="utf-8")
    print(f"Raw response saved to {raw_path}")

    try:
        result = _extract_json(text)
    except json.JSONDecodeError as exc:
        print(f"JSON parse failed: {exc}. Inspect {raw_path} to recover manually.")
        raise

    proposals = result.get("proposals", [])
    watching = result.get("watching", [])

    print(f"\nCurator run complete. {len(proposals)} new proposal(s), {len(watching)} entities watching.")
    for p in proposals:
        cb = p.get("candidate_bucket", {})
        print(f"  PROPOSAL: {cb.get('id')} - {cb.get('description')}")
        print(f"    supporting: {p.get('supporting_items')}")
        print(f"    rationale: {p.get('rationale')}")
    for w in watching:
        print(f"  watching: {w.get('entity')} (count={w.get('item_count')}) - {w.get('note')}")

    if dry_run:
        print("\n(dry run - nothing written to the db)")
        return

    for p in proposals:
        conn.execute(
            "INSERT INTO taxonomy_proposals (proposed_bucket_json, supporting_items, rationale, status) "
            "VALUES (?, ?, ?, 'pending')",
            (
                json.dumps(p.get("candidate_bucket", {})),
                json.dumps(p.get("supporting_items", [])),
                p.get("rationale"),
            ),
        )

    for w in watching:
        entity = w.get("entity")
        if not entity:
            continue
        conn.execute(
            """
            INSERT INTO curator_watchlist (entity, item_count, note)
            VALUES (?, ?, ?)
            ON CONFLICT(entity) DO UPDATE SET
                item_count = excluded.item_count,
                last_seen_at = datetime('now'),
                note = excluded.note
            """,
            (entity, w.get("item_count", 1), w.get("note")),
        )

    conn.commit()
    print(f"\nWrote {len(proposals)} proposal(s) to taxonomy_proposals, {len(watching)} entities to curator_watchlist.")


def main():
    parser = argparse.ArgumentParser(description="Run the ADscape curator agent over unclassified/low-confidence trials.")
    parser.add_argument("--dry-run", action="store_true", help="Run and print results but don't write to the DB.")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set - put it in .env.")
        sys.exit(1)

    conn = init_db()
    client = anthropic.Anthropic()
    run_curator(conn, client, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
