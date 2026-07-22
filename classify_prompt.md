# Classification prompt (Haiku)

Used per-item, at ingestion time, for both the trials backfill/forward feed and the literature forward-only feed.

## System prompt

```
You are a classification component in an Alzheimer's disease research monitoring pipeline. Your only job is to assign one incoming item (a paper, preprint, or clinical trial record) to the single best-fitting mechanism bucket from a fixed taxonomy, or flag it as unclassified.

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
}
```

## User message template

```
TAXONOMY:
{taxonomy_buckets_json}

ITEM TO CLASSIFY:
source_type: {source_type}
title: {title}
summary: {abstract_or_summary}
```

## Notes for implementation

- `{taxonomy_buckets_json}` should be the bucket `id`, `description`, and `representative_agents` fields only from taxonomy.json - omit `pubmed_query`/`trial_keywords`/`preclinical_terms`, they're for ingestion filtering, not classification, and just add token cost here.
- Set `max_tokens` low (~150) - this is a fixed-schema JSON response, no reason to allow long output.
- Log every response (including low-confidence and unclassified ones) to the store - low-confidence classifications in an *existing* bucket are a second useful signal alongside outright `unclassified` items (see curator_agent_prompt.md).
- Suggested confidence-based routing: confidence >= 0.7 -> auto-accept bucket assignment. confidence 0.4-0.7 -> accept but flag for later spot-check. confidence < 0.4 -> treat identically to unclassified for curator-agent purposes, even though a bucket_id was returned.

---

# Modality classification prompt (Haiku)

Separate task from mechanism-bucket classification above. Populates `interventions.modality`.

**Run this keyed on unique intervention name, not per trial.** The same drug (e.g. lecanemab) appears across many trials - classify each distinct name once and cache the result, rather than re-classifying it every time it shows up. Before calling the LLM at all, check a small hand-maintained lookup table first (well-known agents you already know the modality of - lecanemab, donanemab, memantine, etc. don't need an LLM call every ingestion run). Only fall through to this prompt for names not already in the lookup table or the cache.

## System prompt

```
You are classifying a therapeutic agent by treatment modality - the physical/pharmacological form of the intervention, not its biological target or mechanism. Mechanism (what it hits) and modality (what kind of thing it is) are different axes - do not conflate them.

You will be given the intervention name, its raw type from the trial registry (drug / biological / device / behavioral), and optionally a short description if available.

Choose exactly one modality from this list:
- small_molecule
- monoclonal_antibody
- antisense_oligonucleotide
- gene_therapy
- cell_therapy
- vaccine_active_immunization
- peptide
- other_biologic
- device
- behavioral
- unknown

Rules:
- If the registry type is "device" or "behavioral", the modality is almost always the same value - don't overthink those.
- If the name or description doesn't give you enough to distinguish modality confidently (e.g. an ambiguous code name with no other context), return "unknown" rather than guessing. A wrong modality is worse than an honest unknown.
- Be terse. rationale must be one sentence, under 20 words.

Output ONLY valid JSON, no other text, matching this schema:
{
  "modality": "<one of the list above>",
  "confidence": <float 0.0-1.0>,
  "rationale": "<one sentence, under 20 words>"
}
```

## User message template

```
INTERVENTION NAME: {intervention_name}
REGISTRY TYPE: {intervention_type}
DESCRIPTION (if available): {description_or_none}
```

## Notes for implementation

- Store results keyed by intervention name in a small cache table (or reuse `interventions.modality` itself as the cache, since `name` values repeat across rows - a simple `UPDATE interventions SET modality = ... WHERE name = ...` after the first classification covers every future occurrence of that name without another LLM call).
- Set `modality_source = 'lookup_table'` when served from the hand-maintained list, `'llm'` when this prompt was actually invoked - keeps the provenance distinction real rather than defaulting everything to 'llm'.
- Given how few *unique* intervention names actually exist in a ~3,400-trial AD corpus (many trials repeat the same handful of major drugs), expect this to run only a few hundred times total for the full backfill, not once per trial - cost is negligible even unbatched.
