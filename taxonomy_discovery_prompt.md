# Taxonomy discovery pass: endpoint categories + stop reasons (Sonnet, one-time)

Run this ONCE, after the trials backfill (so `outcomes.measure`/`description`
and `trials.why_stopped` are populated), and BEFORE running the per-item
`endpoint category prompt` and `stop reason category prompt` from
classify_prompt.md. Purpose: both of those prompts' taxonomies were hand-picked
from general domain knowledge, not checked against this project's actual data -
same blind spot that missed "stopped early for overwhelming efficacy" during
design. This pass finds gaps like that before you commit to a fixed taxonomy
and classify thousands of items against it.

Same reasoning as the curator agent: clustering is a batch, whole-dataset
operation that doesn't compose with incremental daily ingestion, so it's a
one-time refinement step, not something that runs on an ongoing basis. Once
you've reviewed the output and updated the taxonomies, go back to the fixed,
per-item classification prompts for everything going forward.

---

## Data prep (before calling the model)

**Endpoints:** pull `DISTINCT measure, description` from `outcomes`. Expect
heavy duplication - the same instruments (CDR-SB, ADAS-Cog, amyloid PET SUVr,
etc.) repeat across hundreds of trials, so the unique set should be far
smaller than the total row count. If the deduped set is still large (say,
over ~800 unique entries), take a random sample of that size rather than
feeding everything in - the goal here is discovering categories that exist,
not exhaustively covering every entry, so a sample is sufficient and keeps
the call a reasonable size.

**Stop reasons:** pull `DISTINCT why_stopped` from `trials` WHERE
`why_stopped IS NOT NULL`. This set is inherently small (only
terminated/withdrawn/suspended trials) - no sampling needed, feed it all in.

---

## System prompt

```
You are reviewing real data to check whether two existing category taxonomies are complete, before they're used to classify thousands of items. For each taxonomy, you'll see the existing categories and a sample of real text that will eventually be classified into them.

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
}
```

## User message template

```
=== ENDPOINT CATEGORY TAXONOMY ===

Existing categories:
- biomarker: a molecular/imaging measure (amyloid PET, plasma p-tau, CSF markers, MRI volumetrics, etc.) - not a direct measure of how a patient feels or functions
- cognitive_clinical: a cognitive or clinical rating scale (CDR-SB, ADAS-Cog, MMSE, ADCOMS, etc.)
- functional_adl: activities of daily living / functional status measures (ADCS-ADL, caregiver burden, etc.)
- safety_tolerability: adverse events, ARIA incidence, discontinuation due to side effects, lab safety panels
- other: anything not clearly fitting the above

Sample of real endpoint measure/description text ({n} of {total} unique entries{", randomly sampled" if sampled}):
{endpoint_measure_sample_json}

=== STOP REASON TAXONOMY ===

Existing categories:
- safety_toxicity: stopped due to safety findings, adverse events, or toxicity - including off-target effects
- lack_of_efficacy: stopped because interim results showed the drug wasn't working, futility analysis, DSMB recommendation on efficacy grounds
- business_funding: stopped for sponsor/business reasons - funding, strategic priority changes, company acquisition or restructuring
- enrollment_futility: stopped because the trial couldn't recruit enough participants, unrelated to the drug itself
- other: a reason that doesn't fit the above, or a vague/uninformative explanation

All distinct why_stopped text ({n} entries, full set - not sampled):
{why_stopped_full_json}
```

---

## After you get the output

1. Read `existing_category_coverage` first - a category showing "not seen"
   across your whole corpus isn't necessarily wrong, but worth knowing (e.g.
   if `enrollment_futility` never appears, maybe AD trials rarely fail on
   enrollment, or maybe the wording in your data doesn't match what the
   per-item prompt is looking for).
2. For each `proposed_new_categories` entry, decide by hand: accept, reject,
   or merge into an existing category with a wording tweak. Don't
   auto-accept - this is exactly the same human-in-the-loop principle as the
   curator agent's taxonomy proposals.
3. For accepted categories, update in two places, kept in sync:
   - `schema.sql`'s CHECK constraints (`outcomes.endpoint_category` and/or
     `trials.stop_reason_category`)
   - `classify_prompt.md`'s corresponding system prompt category lists
4. Only after both are updated, run the per-item classification prompts
   against the full dataset.
