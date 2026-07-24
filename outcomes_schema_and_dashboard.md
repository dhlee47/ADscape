# Outcome/endpoint taxonomy: schema fix + build-out + dashboard

## 1. Resolve the schema.sql conflict (do this first)

Good catch on the regression - here's the resolution: **your live-verified
values win, not the file's.** Specifically:
- `interventions.type` - keep your verified live enum (11 values including
  genetic/combination_product/diagnostic_test), not the 6-value guess
- `enrollment_type` - keep `ESTIMATED`, not `ANTICIPATED`

I've loosened both constraints in the source `schema.sql` (removed the
guessed CHECK lists, left a comment pointing back to your verified findings)
so this doesn't happen again on the next handoff. When merging the new
columns/tables below into your working copy, merge them in - don't let this
file's version of those two specific fields overwrite what you already
verified.

## 2. Build out the rest of the outcome/endpoint schema

Go ahead and build all of it now, not just target-classification - it's
needed for the dashboard changes below anyway. That's:
- `interventions.target` + the target classification prompt (already
  in progress per your note)
- `outcomes.endpoint_category`
- `trials.stop_reason_category`
- `trials.regulatory_status` (hand-curated per schema.sql's comment -
  don't build an LLM classification step for this one, the actual set of
  approved AD drugs is small enough to fill in by hand)
- the new `endpoint_assessments` table

**Sequencing matters here - do this in order, not all at once:**
1. Run the taxonomy discovery pass (`taxonomy_discovery_prompt.md`) against
   the already-backfilled `outcomes` and `trials.why_stopped` data first
2. I'll review the output with the user and we'll send back a finalized
   category list if anything changes
3. Only then run the per-item `endpoint category prompt` and
   `stop reason category prompt` from `classify_prompt.md` against the full
   dataset
4. Leave the Sonnet-based endpoint met/significance prompt for later - it
   needs a source-text retrieval step (publications/press releases) that
   doesn't exist yet, it's genuinely separate scope from the rest of this,
   don't block the dashboard work below on it

## 3. Dashboard additions (landscape.html)

Two new sections, added to the existing landscape.html rather than a new
page - keep everything in one place for now. Both should respect the
existing status filter tabs (cascade from the same filter state as the rest
of the page).

### "Stop reasons by mechanism"

Grouped/stacked bar chart. X-axis: mechanism bucket. Bars stacked by
`stop_reason_category`, counting trials where `stop_reason_category` is not
null and not `'not_applicable'`. This is what makes "did secretase trials
fail mostly on safety?" a glanceable chart rather than something requiring a
manual query - directly surfaces the insight pattern discussed earlier this
session.

- Exclude `not_applicable` from the chart itself (that's the vast majority
  of trials, still running or completed normally - including it would
  swamp the signal). Show total trial count per bucket as a small label
  instead, for context.
- Hovering a stacked segment: show the actual trial titles + NCT IDs in
  that bucket/reason combination (a text list, capped at 5 - same pattern
  as the compound-list hover from earlier, not a nested pie).

### "Endpoint outcomes by category"

Grouped bar chart. X-axis: mechanism bucket. For each bucket, two bars:
% of `biomarker` endpoints with `met = 'met'`, and % of `cognitive_clinical`
endpoints with `met = 'met'` (join `outcomes` -> `endpoint_assessments`,
filtered by `endpoint_category`). This is the chart that directly shows
"anti-amyloid met biomarker but not cognitive" as a visual gap between two
bars for the same bucket, rather than something you'd have to read a table
to notice.

- Will be empty/sparse until the Sonnet endpoint-assessment prompt has
  actually been run against real source text (see the "leave for later"
  note above) - that's expected, not a bug, when this is first built. Build
  the chart now against whatever `endpoint_assessments` rows exist (even
  zero), so it's ready to populate once that data starts flowing, rather
  than building it later as a separate task.
- Show the underlying N (count of assessed endpoints per bar) alongside the
  percentage - a 100% bar built from 2 endpoints reads very differently
  than one built from 40, don't let the chart imply more confidence than
  the sample size supports.
