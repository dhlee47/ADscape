"""ADscape target-classification CLI: assign a druggable target (gene/protein
symbol) to each distinct intervention name. See classify_prompt.md's "Target
classification prompt" section - keyed on unique name (not per-trial row),
cached, with the intervention's most-common mechanism bucket passed in as
disambiguating context. Populates interventions.target.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from dotenv import load_dotenv

from db import init_db

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 150
MAX_WORKERS = 16  # concurrent Haiku calls - I/O-bound, ~4,850 unique names is too
                 # many to run one-at-a-time in an interactive session
MAX_RETRIES = 5

SYSTEM_PROMPT = """You are identifying the specific druggable target (gene or protein) that a therapeutic agent acts on - one level more specific than its broad mechanism category. For example, within a "neuroinflammation" mechanism, one drug might target TREM2 specifically, another might target the NLRP3 inflammasome, another the complement cascade - these are different targets within the same broad mechanism.

You will be given the intervention name, its already-assigned mechanism bucket (for context - most targets are consistent with their bucket, use this to narrow down, not override actual evidence), and its type.

Return the target as a standard gene/protein symbol or well-established name where one exists (e.g. "TREM2", "BACE1", "APOE", "amyloid-beta", "tau", "NLRP3", "GLP-1R"). If you don't have enough information to identify the specific target with reasonable confidence, return "unknown" rather than guessing - a wrong target is worse than an honest unknown, especially since this will be cached and reused for every future trial testing the same drug.

Be terse. rationale must be one sentence, under 20 words.

Output ONLY valid JSON, no other text, matching this schema:
{
  "target": "<gene/protein symbol, or 'unknown'>",
  "confidence": <float 0.0-1.0>,
  "rationale": "<one sentence, under 20 words>"
}"""


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def gather_names(conn, only_unclassified=True):
    """One entry per distinct intervention name, with the most common
    bucket_id/type among the trials that reference it, for prompt context."""
    rows = conn.execute(
        """
        SELECT i.name, i.type, t.bucket_id
        FROM interventions i
        JOIN trials t ON t.nct_id = i.nct_id
        WHERE i.name IS NOT NULL AND trim(i.name) != ''
        """
    ).fetchall()

    by_name_bucket = defaultdict(Counter)
    by_name_type = defaultdict(Counter)
    for r in rows:
        by_name_bucket[r["name"]][r["bucket_id"]] += 1
        by_name_type[r["name"]][r["type"]] += 1

    bucket_desc = {
        b["bucket_id"]: b["description"]
        for b in conn.execute("SELECT bucket_id, description FROM mechanism_buckets").fetchall()
    }

    already_done = set()
    if only_unclassified:
        already_done = {
            r["name"] for r in conn.execute("SELECT DISTINCT name FROM interventions WHERE target IS NOT NULL")
        }

    items = []
    for name in by_name_bucket:
        if name in already_done:
            continue
        bucket_id = by_name_bucket[name].most_common(1)[0][0]
        itype = by_name_type[name].most_common(1)[0][0]
        items.append(
            {
                "name": name,
                "bucket_id": bucket_id,
                "bucket_description": bucket_desc.get(bucket_id, ""),
                "type": itype,
            }
        )
    return items


def classify_one_target(client, item):
    user_message = (
        f"INTERVENTION NAME: {item['name']}\n"
        f"ASSIGNED MECHANISM BUCKET: {item['bucket_id']} - {item['bucket_description']}\n"
        f"REGISTRY TYPE: {item['type']}"
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
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError, json.JSONDecodeError) as exc:
            last_exc = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"failed after {MAX_RETRIES} attempts: {last_exc}")


def cmd_classify(limit=None, dry_run=False):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set - put it in .env.")
        sys.exit(1)

    conn = init_db()
    client = anthropic.Anthropic()

    items = gather_names(conn)
    if limit:
        items = items[:limit]

    print(f"{len(items)} distinct intervention name(s) to target-classify{' (dry run)' if dry_run else ''} "
          f"({MAX_WORKERS} concurrent workers).")

    done = 0
    errors = 0
    unknown = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(classify_one_target, client, item): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            done += 1
            try:
                result = future.result()
            except Exception as exc:
                errors += 1
                print(f"  [{done}/{len(items)}] {item['name']}: ERROR - {exc}")
                continue

            target = result.get("target") or "unknown"
            confidence = result.get("confidence")
            rationale = result.get("rationale", "")
            if target == "unknown":
                unknown += 1

            print(f"  [{done}/{len(items)}] {item['name']} ({item['bucket_id']}): {target} (conf={confidence}) - {rationale}")

            if not dry_run:
                conn.execute(
                    "UPDATE interventions SET target = ?, target_confidence = ?, target_source = 'llm' WHERE name = ?",
                    (target, confidence, item["name"]),
                )
                if done % 20 == 0:
                    conn.commit()

    if not dry_run:
        conn.commit()

    print(f"\nDone. {done - errors}/{len(items)} classified ({unknown} 'unknown'), {errors} error(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify each distinct intervention name's druggable target.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N names (for testing).")
    parser.add_argument("--dry-run", action="store_true", help="Classify but don't write results to the DB.")
    args = parser.parse_args()
    cmd_classify(limit=args.limit, dry_run=args.dry_run)
