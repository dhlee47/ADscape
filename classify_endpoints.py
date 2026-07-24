"""ADscape endpoint-category classification CLI. See classify_prompt.md's
"Endpoint category prompt" (updated post taxonomy_discovery_prompt.md - see
taxonomy_discovery_response.json for the review that added
pharmacokinetics/neuropsychiatric_behavioral/quality_of_life_wellbeing/
physical_function_motor). Populates outcomes.endpoint_category.

Cached by exact (measure, description) pair, not per-row - classify_prompt.md
notes this has a lower hit rate than the target/modality prompts (endpoints
are far more varied), but still worth it for verbatim-repeated measures.
"""

import json
import os
import sys
import time
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
MAX_WORKERS = 16
MAX_RETRIES = 5

SYSTEM_PROMPT = """You are categorizing a clinical trial endpoint by what kind of thing it measures. You will be given the endpoint's measure name and description (from a trial registry).

Choose exactly one category:
- biomarker: a molecular/imaging measure (amyloid PET, plasma p-tau, CSF markers, MRI volumetrics, etc.) - not a direct measure of how a patient feels or functions
- cognitive_clinical: a cognitive or clinical rating scale (CDR-SB, ADAS-Cog, MMSE, ADCOMS, etc.)
- functional_adl: activities of daily living / functional status measures (ADCS-ADL, caregiver burden, etc.)
- safety_tolerability: adverse events, ARIA incidence, discontinuation due to side effects, lab safety panels
- pharmacokinetics: drug exposure/disposition measures (plasma concentration, Cmax, AUC, half-life, volume of distribution, renal clearance)
- neuropsychiatric_behavioral: behavioral/psychiatric symptom rating scales (NPI, CMAI, GDS, GAI, BEHAVE-AD) - distinct from cognitive_clinical's cognitive-testing scales, even though both are "clinical rating scales"
- quality_of_life_wellbeing: patient- or caregiver-reported quality of life, well-being, caregiver burden/self-efficacy, or satisfaction measures - not focused on basic/instrumental ADLs specifically
- physical_function_motor: objective physical performance/motor measures (gait speed, balance, strength, physical fitness battery scores)
- other: anything not clearly fitting the above - including trial-conduct/feasibility measures (recruitment rates, adherence, app usage, usability surveys), which are deliberately not their own category since they aren't therapeutic-outcome endpoints

Be terse. rationale must be one sentence, under 20 words.

Output ONLY valid JSON, no other text:
{
  "endpoint_category": "<one of the categories above>",
  "confidence": <float 0.0-1.0>,
  "rationale": "<one sentence, under 20 words>"
}"""

VALID_CATEGORIES = {
    "biomarker", "cognitive_clinical", "functional_adl", "safety_tolerability",
    "pharmacokinetics", "neuropsychiatric_behavioral", "quality_of_life_wellbeing",
    "physical_function_motor", "other",
}


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def gather_items(conn, only_unclassified=True):
    rows = conn.execute("SELECT DISTINCT measure, description FROM outcomes").fetchall()
    if only_unclassified:
        already_done = {
            (r["measure"], r["description"])
            for r in conn.execute(
                "SELECT DISTINCT measure, description FROM outcomes WHERE endpoint_category IS NOT NULL"
            ).fetchall()
        }
        rows = [r for r in rows if (r["measure"], r["description"]) not in already_done]
    return rows


def classify_one(client, measure, description):
    user_message = f"MEASURE: {measure}\nDESCRIPTION: {description or '(none)'}"
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
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

    items = gather_items(conn)
    if limit:
        items = items[:limit]

    print(f"{len(items)} distinct (measure, description) pair(s) to classify{' (dry run)' if dry_run else ''} "
          f"({MAX_WORKERS} concurrent workers).")

    done = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(classify_one, client, r["measure"], r["description"]): r for r in items}
        for future in as_completed(futures):
            row = futures[future]
            done += 1
            try:
                result = future.result()
            except Exception as exc:
                errors += 1
                print(f"  [{done}/{len(items)}] ERROR - {exc}")
                continue

            category = result.get("endpoint_category") or "other"
            if category not in VALID_CATEGORIES:
                category = "other"
            confidence = result.get("confidence")
            rationale = result.get("rationale", "")

            print(f"  [{done}/{len(items)}] {row['measure'][:60]!r}: {category} (conf={confidence}) - {rationale}")

            if not dry_run:
                conn.execute(
                    "UPDATE outcomes SET endpoint_category = ?, endpoint_category_confidence = ? "
                    "WHERE measure = ? AND (description = ? OR (description IS NULL AND ? IS NULL))",
                    (category, confidence, row["measure"], row["description"], row["description"]),
                )
                if done % 100 == 0:
                    conn.commit()

    if not dry_run:
        conn.commit()

    print(f"\nDone. {done - errors}/{len(items)} classified, {errors} error(s).")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Classify each distinct (measure, description) pair's endpoint category.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N pairs (for testing).")
    parser.add_argument("--dry-run", action="store_true", help="Classify but don't write results to the DB.")
    args = parser.parse_args()
    cmd_classify(limit=args.limit, dry_run=args.dry_run)
