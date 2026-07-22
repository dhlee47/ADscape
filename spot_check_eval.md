# Spot-check eval against Alzforum (manual, infrequent)

Purpose: a lightweight sanity check on classification and outcome-assessment
quality, using Alzforum's expert-curated therapeutics database as ground
truth. Not automated, not part of the scheduled pipeline - run by hand at
natural checkpoints (after initial backfill, after material prompt changes).

## Why manual, not scraped

Alzforum's content is expert-curated and proprietary. Opening a handful of
pages yourself to compare is a normal, appropriate use of their public site.
Building an automated scraper to pull their content into this pipeline on a
schedule is a different thing - don't do that here.

## Sampling method

Pick 15-20 trials, not randomly - stratify deliberately:
- A few from each mechanism bucket that has meaningful volume (not just the
  buckets with the most data)
- A mix of classification_confidence levels: some >0.8, some in the 0.4-0.7
  "flagged for spot-check" range from classify_prompt.md's own routing logic
- At least 2-3 trials for drugs that have a well-known, well-documented
  outcome (e.g. a discontinued Phase 3) - these are the easiest to grade
  outcome_assessment against, since Alzforum's narrative will be explicit

## Process per trial

1. Look up the drug/trial on Alzforum's therapeutics database
   (https://www.alzforum.org/therapeutics)
2. Compare:
   - Our `bucket_id` assignment vs. Alzforum's stated target/mechanism
   - Our `outcome_assessments.assessment` + `rationale` vs. Alzforum's
     narrative account of what happened
3. Rate agreement: match / partial / mismatch
4. Note *why* on any partial or mismatch - this is the useful part, not the
   score itself. A mismatch pattern across several trials (e.g. always
   over-confident on combination trials) is more informative than any
   single trial's score.

## What to do with results

- Consistent mismatches in one bucket -> revisit that bucket's description
  in taxonomy.json, it's probably ambiguous
- Consistent overconfidence -> tighten the confidence-routing thresholds in
  classify_prompt.md
- outcome_assessment doing poorly in general -> expected per the earlier
  discussion; consider whether it's worth keeping as auto-generated at all,
  or whether it should always route to human review before being trusted
- Log results in `spot_check_log` (see schema.sql) so drift over time is
  visible, not just a one-off impression
