# ClinicalTrials.gov API v2 - ingestion spec

Trials-only scope (v0.1). No RSS needed here - CT.gov has a proper REST API
that returns structured JSON matching our schema far better than a feed would.

Official docs: https://clinicaltrials.gov/data-api/api
Base endpoint: https://clinicaltrials.gov/api/v2/studies

**Verified against a live response (2026-07-22).** The field-mapping table below
was confirmed against a real `GET /api/v2/studies` call plus the API's own
`/api/v2/studies/metadata` schema endpoint, and against a 1,000-record sample
pulled with `query.cond=Alzheimer Disease`. All paths in the table below match
as documented, with two corrections carried into `schema.sql`:

- `designModule.enrollmentInfo.type` returns `ACTUAL` or `ESTIMATED` in v2, not
  `ANTICIPATED` (that was a v1-era value). `schema.sql`'s `enrollment_type`
  CHECK constraint was updated to `('ACTUAL','ESTIMATED')`.
- `armsInterventionsModule.interventions[].type` (`InterventionType`) has 11
  possible values, not 6 - confirmed via metadata plus an empirical scan of
  1,000 real records: `DRUG, DEVICE, BIOLOGICAL, PROCEDURE, RADIATION,
  BEHAVIORAL, GENETIC, DIETARY_SUPPLEMENT, COMBINATION_PRODUCT,
  DIAGNOSTIC_TEST, OTHER`. The ingestion script lowercases this value on
  write; `schema.sql`'s `interventions.type` CHECK constraint was widened to
  the full lowercased set.

`whyStopped` and `collaborators[]` both resolve exactly as documented (just
not populated on every trial, which is expected/optional per the registry's
own rules).

## Backfill query (run once)

```
GET https://clinicaltrials.gov/api/v2/studies
    ?query.cond=Alzheimer Disease
    &pageSize=1000
    &format=json
```

- Paginate using the cursor-based `nextPageToken` returned in each response
  (pass it back as `&pageToken=...` on the next request) until no token is
  returned - do NOT use offset-based pagination, v2 does not support it.
- `query.cond` searches the conditions field specifically (narrower/cleaner
  than `query.term`, which searches everywhere including descriptions).
- Expect roughly 3,000-4,000 total records based on prior research in this
  conversation - if the actual count comes back far outside that range,
  treat it as a signal something's wrong with the query before proceeding
  (e.g. too broad, or an unintended filter).

## Forward/incremental query (runs daily via cron)

```
GET https://clinicaltrials.gov/api/v2/studies
    ?query.cond=Alzheimer Disease
    &query.term=AREA[LastUpdatePostDate]RANGE[<last_run_date>,MAX]
    &pageSize=1000
    &format=json
```

Important: this catches both brand-new trials AND updates to trials already
in our database - a status change, a new result posting, a phase change on
an existing NCT ID. Don't design the forward sync as "only look for new NCT
IDs" - re-fetching and upserting on `nct_id` is the correct approach, since
an existing trial's `overall_status` flipping to COMPLETED or `results_posted`
flipping to true is exactly the kind of update this pipeline should catch.

`<last_run_date>` = the date of the previous successful run, tracked
somewhere durable (a small state file or a `pipeline_runs` table - not yet
in schema.sql, add if Claude Code doesn't already track this some other way).

## Useful additional query params (not required for v1, noted for later)

- `filter.overallStatus` - comma-separated status filter if you want to
  narrow later (e.g. only actively recruiting)
- `query.intr` - intervention/drug name search, useful if you ever want to
  do a targeted pull for one specific agent rather than the full AD corpus
- `fields` - restrict the response to only the fields you need, reduces
  payload size on the full backfill

## Field mapping: API response -> schema.sql

The v2 response nests everything under `protocolSection` (per official docs
and third-party guides). Expected structure, to be confirmed on first call:

| schema.sql column | API path (under protocolSection) |
|---|---|
| trials.nct_id | identificationModule.nctId |
| trials.brief_title | identificationModule.briefTitle |
| trials.official_title | identificationModule.officialTitle |
| trials.overall_status | statusModule.overallStatus |
| trials.study_type | designModule.studyType |
| trials.phase | designModule.phases (array - join with comma) |
| trials.start_date | statusModule.startDateStruct.date |
| trials.primary_completion_date | statusModule.primaryCompletionDateStruct.date |
| trials.completion_date | statusModule.completionDateStruct.date |
| trials.why_stopped | statusModule.whyStopped |
| trials.registry_last_updated | statusModule.lastUpdatePostDateStruct.date |
| trials.enrollment_count | designModule.enrollmentInfo.count |
| trials.enrollment_type | designModule.enrollmentInfo.type |
| trials.sex | eligibilityModule.sex |
| trials.minimum_age | eligibilityModule.minimumAge |
| trials.maximum_age | eligibilityModule.maximumAge |
| trials.conditions | conditionsModule.conditions (array - join or store as JSON) |
| trials.results_posted | top-level `hasResults` field (outside protocolSection) |
| sponsors (lead) | sponsorCollaboratorsModule.leadSponsor.{name, class} |
| sponsors (collaborators) | sponsorCollaboratorsModule.collaborators[] |
| interventions | armsInterventionsModule.interventions[].{name, type} |
| outcomes (primary) | outcomesModule.primaryOutcomes[].{measure, description, timeFrame} |
| outcomes (secondary) | outcomesModule.secondaryOutcomes[].{measure, description, timeFrame} |

Not mapped to any column: `eligibilityModule.eligibilityCriteria` (the free-text
block containing biomarker/stage criteria) - flagged previously as a v2
enhancement, not stored in v1.

## Rate limiting / etiquette

No published hard rate limit as of this writing, but the backfill involves
~4-6 sequential paginated requests total (1000/page, ~3-4K records) - not a
volume that should concern anyone. Add a small delay (e.g. 200ms) between
requests as standard good-citizen practice, and set a descriptive User-Agent
header identifying the script.
