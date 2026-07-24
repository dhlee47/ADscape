"""ADscape taxonomy discovery pass: check whether the endpoint_category and
stop_reason_category taxonomies (fixed lists already in classify_prompt.md)
actually cover this project's real data, before committing thousands of
per-item classification calls to them. One-time, not part of ongoing
ingestion - see taxonomy_discovery_prompt.md. Report only: never writes to
the db or edits any taxonomy file - proposals are for human review.
"""

import json
import os
import random
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from db import init_db

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8000
ENDPOINT_SAMPLE_CAP = 800

SYSTEM_PROMPT = """You are reviewing real data to check whether two existing category taxonomies are complete, before they're used to classify thousands of items. For each taxonomy, you'll see the existing categories and a sample of real text that will eventually be classified into them.

Your job for each taxonomy:
1. Read through the sample text.
2. For each existing category, note whether it's well-represented in the sample or seems to have few/no matches.
3. Identify clusters of text that don't fit ANY existing category well - these are gaps.
4. For each gap cluster, propose a new category: a short id, a one-sentence description, and 3-5 example texts from the sample that would fall into it.
5. Do NOT propose a new category for a small handful of one-off items that don't clearly cluster together - isolated edge cases can fall into the existing "other" category. Only propose a new category when you see a real recurring pattern, not just anything that doesn't fit neatly.
6. Be conservative - adding an unnecessary category creates ambiguity for every future classification call. A missed gap costs less than a false one; when uncertain, don't propose.

Output ONLY valid JSON, no other text, matching this schema:
{
  "endpoint_category_review": {
    "existing_category_coverage": [
      {"category": "<id>", "representation": "<well-represented|sparse|not seen>"}
    ],
    "proposed_new_categories": [
      {
        "id": "<short_snake_case_id>",
        "description": "<one sentence>",
        "example_texts": ["<up to 5 examples from the sample>"],
        "rationale": "<why this doesn't fit any existing category, 1 sentence>"
      }
    ]
  },
  "stop_reason_category_review": {
    "existing_category_coverage": [
      {"category": "<id>", "representation": "<well-represented|sparse|not seen>"}
    ],
    "proposed_new_categories": [
      {
        "id": "<short_snake_case_id>",
        "description": "<one sentence>",
        "example_texts": ["<up to 5 examples from the sample>"],
        "rationale": "<why this doesn't fit any existing category, 1 sentence>"
      }
    ]
  }
}"""

ENDPOINT_CATEGORIES_TEXT = """- biomarker: a molecular/imaging measure (amyloid PET, plasma p-tau, CSF markers, MRI volumetrics, etc.) - not a direct measure of how a patient feels or functions
- cognitive_clinical: a cognitive or clinical rating scale (CDR-SB, ADAS-Cog, MMSE, ADCOMS, etc.)
- functional_adl: activities of daily living / functional status measures (ADCS-ADL, caregiver burden, etc.)
- safety_tolerability: adverse events, ARIA incidence, discontinuation due to side effects, lab safety panels
- other: anything not clearly fitting the above"""

STOP_REASON_CATEGORIES_TEXT = """- safety_toxicity: stopped due to safety findings, adverse events, or toxicity - including off-target effects
- lack_of_efficacy: stopped because interim results showed the drug wasn't working, futility analysis, DSMB recommendation on efficacy grounds
- business_funding: stopped for sponsor/business reasons - funding, strategic priority changes, company acquisition or restructuring
- enrollment_futility: stopped because the trial couldn't recruit enough participants, unrelated to the drug itself
- other: a reason that doesn't fit the above, or a vague/uninformative explanation"""


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def gather_endpoint_sample(conn):
    rows = conn.execute("SELECT DISTINCT measure, description FROM outcomes").fetchall()
    total = len(rows)
    sampled = total > ENDPOINT_SAMPLE_CAP
    if sampled:
        rows = random.sample(rows, ENDPOINT_SAMPLE_CAP)
    entries = [{"measure": r["measure"], "description": r["description"]} for r in rows]
    return entries, total, sampled


def gather_stop_reasons(conn):
    rows = conn.execute("SELECT DISTINCT why_stopped FROM trials WHERE why_stopped IS NOT NULL").fetchall()
    return [r["why_stopped"] for r in rows]


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set - put it in .env.")
        sys.exit(1)

    conn = init_db()
    client = anthropic.Anthropic()

    endpoint_entries, endpoint_total, endpoint_sampled = gather_endpoint_sample(conn)
    stop_reasons = gather_stop_reasons(conn)

    print(
        f"Endpoint sample: {len(endpoint_entries)} of {endpoint_total} unique measure/description pairs"
        f"{' (randomly sampled)' if endpoint_sampled else ' (full set)'}."
    )
    print(f"Stop reasons: {len(stop_reasons)} distinct why_stopped text(s) (full set).")

    sample_note = ", randomly sampled" if endpoint_sampled else ""
    user_message = f"""=== ENDPOINT CATEGORY TAXONOMY ===

Existing categories:
{ENDPOINT_CATEGORIES_TEXT}

Sample of real endpoint measure/description text ({len(endpoint_entries)} of {endpoint_total} unique entries{sample_note}):
{json.dumps(endpoint_entries, indent=2)}

=== STOP REASON TAXONOMY ===

Existing categories:
{STOP_REASON_CATEGORIES_TEXT}

All distinct why_stopped text ({len(stop_reasons)} entries, full set - not sampled):
{json.dumps(stop_reasons, indent=2)}"""

    print("\nCalling Sonnet for the discovery pass...")
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
        raise RuntimeError(f"No text content in response (stop_reason={message.stop_reason})")

    raw_path = Path(__file__).parent / "taxonomy_discovery_response.json"
    raw_path.write_text(text, encoding="utf-8")
    print(f"Raw response saved to {raw_path}")

    result = _extract_json(text)

    for taxonomy_name, key in (
        ("Endpoint category", "endpoint_category_review"),
        ("Stop reason category", "stop_reason_category_review"),
    ):
        review = result.get(key, {})
        print(f"\n=== {taxonomy_name} taxonomy ===")
        print("Existing category coverage:")
        for c in review.get("existing_category_coverage", []):
            print(f"  {c['category']}: {c['representation']}")
        proposals = review.get("proposed_new_categories", [])
        if not proposals:
            print("No new categories proposed.")
        else:
            print(f"{len(proposals)} new categor{'y' if len(proposals) == 1 else 'ies'} proposed:")
            for p in proposals:
                print(f"  [{p['id']}] {p['description']}")
                print(f"    rationale: {p['rationale']}")
                print(f"    examples: {p['example_texts']}")

    print(
        "\nThis is a report only - nothing written to the db or any taxonomy file. "
        "Per taxonomy_discovery_prompt.md: review each proposal by hand (accept/reject/merge) "
        "before updating schema.sql + classify_prompt.md and running the per-item classification."
    )


if __name__ == "__main__":
    main()
