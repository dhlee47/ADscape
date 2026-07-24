# Rescope: one-time backfill only, no further API token usage

## Project direction change

Drop the forward-sync plan entirely - no GitHub Actions cron job, no
scheduled script calling the Anthropic API on a weekly/monthly basis. This
project is now scoped as a one-time backfill: get the trials db as complete
and well-classified as reasonably possible in this pass, then stop. Any
future updates to the data happen as manually-triggered Claude Code sessions
later, not an unattended pipeline.

**Practical implication:** don't build anything that authenticates with
`ANTHROPIC_API_KEY` or calls `api.anthropic.com` for classification work
going forward. Do the classification directly, as part of this Claude Code
session, using your own reasoning - not by writing and running a script
that makes API calls on your behalf. This session is already a Claude
session (running on the user's subscription); routing the same work through
a script that calls the API separately would just add token billing for no
benefit.

## Task: endpoint met/significance classification (the deferred piece)

This is the `endpoint_assessments` table from `schema.sql` and the
"Endpoint met/significance assessment prompt (Sonnet)" section of
`classify_prompt.md` - previously deferred because it needs source text
beyond registry metadata. Do this now, directly, scoped to the subset
already sized (Option B from the earlier cost-estimate discussion):

```sql
WHERE results_posted = 1
  AND overall_status IN ('COMPLETED', 'TERMINATED')
  AND bucket_id IS NOT NULL
  AND bucket_id != 'unclassified'
```

**Source text:** use CT.gov's own `resultsSection` data (already available
from the API response used for the backfill - re-fetch per trial if it
wasn't stored the first time around) - this is the whole point of Option
B's scope, no PubMed/press-release retrieval needed here.

**Follow the same rubric already written in `classify_prompt.md`'s endpoint
assessment prompt** - the `met`/`not_met`/`mixed`/`unknown` and
`statistically_significant` categories, and specifically the instruction to
prefer "unknown"/"not_reported" over guessing when the source text is
ambiguous. That section was written as an API system prompt, but the
judgment rubric in it applies exactly the same way to your own reasoning
here - read it as your instructions for this task, not just as a template
for a call you're not making.

For each outcome you assess, write to `endpoint_assessments`:
- `met`, `statistically_significant`, `confidence`, `rationale` per the
  existing schema
- `source_url` - the ClinicalTrials.gov study page
  (`https://clinicaltrials.gov/study/{nct_id}`) or more specific results
  section reference if available
- `assessed_by = 'llm'` - this is still an LLM's inference (yours), the
  billing mechanism doesn't change that classification. Don't mark it
  `'human'`.

## What NOT to do as part of this

- Don't build the source-text retrieval pipeline (PubMed/press-release
  fallback) - that was Option C scope, still out of bounds, not just
  deferred for cost reasons but for scope reasons now
- Don't build or leave behind any GitHub Actions workflow file for
  scheduled sync - if one was started, remove it
- If `stop_reason_category` (from `trials.why_stopped`) hasn't been run
  yet either, it's a good candidate to also do this same way (direct
  reasoning, no API) - it's a much smaller dataset (only
  terminated/withdrawn/suspended trials) - flag back to the user whether
  this is done or still pending, don't assume

## After this runs

Regenerate `data/landscape.json` so the "Endpoint outcomes by category"
chart actually populates, and let the user know the actual coverage
achieved (how many of the scoped outcomes got a real assessment vs.
`unknown`) so they know what the resulting chart is and isn't showing.
