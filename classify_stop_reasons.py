"""ADscape stop-reason classification CLI. See classify_prompt.md's "Stop
reason category prompt" (updated post taxonomy_discovery_prompt.md - see
taxonomy_discovery_response.json for the review that added
investigator_departure/operational_logistical). Populates
trials.stop_reason_category.

Trials with why_stopped IS NULL get 'not_applicable' directly (no LLM call
needed - matches classify_prompt.md's own note). Classification is cached by
exact why_stopped text (328 distinct texts among 366 stopped trials), not
per-trial, since the same explanation string recurs across trials.
"""

import json
import os
import sys
import time
from collections import defaultdict
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
MAX_WORKERS = 8
MAX_RETRIES = 5

SYSTEM_PROMPT = """You are categorizing why a clinical trial stopped early, based on the registry's free-text explanation.

Choose exactly one category:
- safety_toxicity: stopped due to safety findings, adverse events, or toxicity - including off-target effects
- lack_of_efficacy: stopped because interim results showed the drug wasn't working, futility analysis, DSMB recommendation on efficacy grounds
- business_funding: stopped for sponsor/business reasons - funding, strategic priority changes, company acquisition or restructuring
- enrollment_futility: stopped because the trial couldn't recruit enough participants, unrelated to the drug itself
- investigator_departure: stopped because the principal investigator or study staff left, relocated, resigned, or was otherwise unavailable to continue the study
- operational_logistical: stopped due to logistical, supply, regulatory, or technical/operational obstacles (drug/device supply issues, contract problems, regulatory non-approval) unrelated to enrollment, safety, or efficacy
- other: a reason that doesn't fit the above, or a vague/uninformative explanation

Be terse. rationale must be one sentence, under 20 words - quote or closely paraphrase the key phrase from why_stopped that drove your categorization.

Output ONLY valid JSON, no other text:
{
  "stop_reason_category": "<one of the categories above>",
  "confidence": <float 0.0-1.0>,
  "rationale": "<one sentence, under 20 words>"
}"""

VALID_CATEGORIES = {
    "safety_toxicity", "lack_of_efficacy", "business_funding", "enrollment_futility",
    "investigator_departure", "operational_logistical", "other",
}


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def classify_one(client, why_stopped):
    user_message = f"WHY_STOPPED: {why_stopped}"
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


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set - put it in .env.")
        sys.exit(1)

    conn = init_db()
    client = anthropic.Anthropic()

    not_applicable_count = conn.execute(
        "UPDATE trials SET stop_reason_category = 'not_applicable' WHERE why_stopped IS NULL"
    ).rowcount
    conn.commit()
    print(f"{not_applicable_count} trial(s) with no why_stopped -> 'not_applicable' (no LLM call).")

    texts = [
        r["why_stopped"]
        for r in conn.execute("SELECT DISTINCT why_stopped FROM trials WHERE why_stopped IS NOT NULL").fetchall()
    ]
    print(f"{len(texts)} distinct why_stopped text(s) to classify ({MAX_WORKERS} concurrent workers).")

    done = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(classify_one, client, text): text for text in texts}
        for future in as_completed(futures):
            text = futures[future]
            done += 1
            try:
                result = future.result()
            except Exception as exc:
                errors += 1
                print(f"  [{done}/{len(texts)}] ERROR - {exc}")
                continue

            category = result.get("stop_reason_category") or "other"
            if category not in VALID_CATEGORIES:
                category = "other"
            confidence = result.get("confidence")
            rationale = result.get("rationale", "")

            print(f"  [{done}/{len(texts)}] {text[:60]!r}: {category} (conf={confidence}) - {rationale}")
            conn.execute(
                "UPDATE trials SET stop_reason_category = ?, stop_reason_confidence = ? WHERE why_stopped = ?",
                (category, confidence, text),
            )
            if done % 20 == 0:
                conn.commit()

    conn.commit()
    print(f"\nDone. {done - errors}/{len(texts)} distinct texts classified, {errors} error(s).")


if __name__ == "__main__":
    main()
