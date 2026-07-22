# AD landscape tracker - config & prompt spec (v0.1)

This is the spec layer, not the implementation - hand these files to Claude Code as the contract for the actual pipeline build.

## Files in this set

- `taxonomy.json` - mechanism bucket definitions (metabolic_vascular deliberately omitted - see below)
- `holdout_eval.json` - ground truth + grading criteria for the leave-one-out eval. Keep this out of any prompt context; it's for grading only.
- `classify_prompt.md` - per-item classification prompt (Haiku), run at ingestion time
- `curator_agent_prompt.md` - weekly taxonomy-review prompt (Sonnet), plus the eval-mode variant
- `schema.sql` - SQLite schema (trials + sponsors + interventions + outcomes + outcome_assessments + curator_watchlist + taxonomy_proposals)
- `api_source.md` - ClinicalTrials.gov API v2 endpoint, query params, and field mapping to schema.sql
- `spot_check_eval.md` - manual, infrequent QA process for comparing pipeline output against Alzforum

## Scope: trials-only (v0.2)

Literature and preclinical arms have been dropped from scope entirely, not just deferred - see the "is this useful" discussion for why. This project is now scoped as a single, tractable corpus:

- **Trials arm:** full historical backfill (~3,400 records) + ongoing forward sync via `AREA[LastUpdatePostDate]RANGE[...]`, catching both new trials and updates to existing ones (status changes, results postings). No RSS involved - ClinicalTrials.gov's REST API v2 returns structured JSON directly.
- **Biomarker/diagnostic tagging:** explicitly out of scope for v1 - may be added later as an orthogonal tag dimension, not a mechanism bucket.
- **International coverage:** ClinicalTrials.gov includes many non-US trials but is not exhaustive globally - see international-coverage discussion for why this isn't a simple add.

## Pipeline stages these files plug into

1. Ingestion (`api_source.md` - ClinicalTrials.gov API v2, backfill + forward sync)
2. Classification (`classify_prompt.md`, Haiku, per trial)
3. Structured store (`schema.sql`, SQLite)
4. Weekly curator review (`curator_agent_prompt.md`, Sonnet) - proposes taxonomy changes, never auto-applies them
5. Dashboard (static HTML v1, see prior discussion)

## Why build this when Alzforum already exists?

Worth stating explicitly, since it changes what "success" means here. Alzforum maintains an expert-curated database of AD therapeutics classified by mechanism, and an annual peer-reviewed pipeline report does the same at a landscape level. A solo LLM-tagged pipeline is very unlikely to out-perform that on accuracy - and shouldn't try to.

The actual value of this project is:
1. **Skill-building** - practicing agentic AI patterns (classification, curator loops, evals) in a domain you can personally judge for correctness.
2. **The curator agent's real question isn't "can we tag trials" - it's "can an agent detect an emerging mechanism before it's been hand-curated anywhere."** That's not something Alzforum's manual process can answer about itself.

So Alzforum isn't a competitor to build past - it's the **eval oracle**. Grade the classifier's bucket assignments and the curator agent's proposals against Alzforum's own categorization and update cadence, rather than treating "did we build a good trial database" as the success metric. See `spot_check_eval.md` for how this plugs in as a lightweight, infrequent QA step rather than a full pipeline stage.

## Leave-one-out eval

`metabolic_vascular` is withheld from `taxonomy.json` on purpose. Run the trials backfill through classification with the reduced taxonomy, then run the curator agent (eval-mode template in `curator_agent_prompt.md`) against the resulting unclassified set. Grade against `holdout_eval.json`. If it passes, this is a decent proof of concept that the curator agent can discover real taxonomy gaps from data alone rather than needing them hand-specified - worth running before trusting it on genuinely novel/unknown mechanisms going forward.

## Repo setup

Initialize this folder as a git repo and push it to a private GitHub repo before wiring up the GitHub Actions cron job - Actions requires the code to actually live in GitHub to run. Before your first commit: put the Anthropic API key in a local `.env` (never committed - see `.gitignore`), and for the Actions version put it in the repo's encrypted Secrets settings instead. The included `.gitignore` excludes the SQLite `.db` file by default, treating it as regenerable from the backfill + sync scripts rather than versioned - remove that line if you'd rather commit it for a simple backup snapshot instead (reasonable at this data volume, just makes for noisier git history).

## Still open (not in this file set yet)

- `pipeline_runs` tracking (or equivalent state) to record the last successful sync date for the forward incremental query - referenced in `api_source.md` but not yet in `schema.sql`
- GitHub Actions workflow (schedule, secrets handling for the Anthropic API key)
- Dashboard build (static HTML v1, per prior discussion)
- Live verification of the field-mapping table in `api_source.md` against a real API response before writing the ingestion script
