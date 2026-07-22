# Dashboard build spec (v1) - Landscape Overview + Pipeline Ops

Two static HTML dashboards, both reading from the same SQLite db (`schema.sql`).
No backend/server - generate data as static JSON at build time, render client-side.
This matches the "static HTML v1" approach from prior discussion (GitHub Pages
hosting, no server to maintain).

## Shared technical approach

- **Data generation:** a small Python script queries the SQLite db, writes the
  results each dashboard needs to static JSON files (e.g. `data/landscape.json`,
  `data/ops.json`). Re-run this script any time the db updates - for now, a
  manual re-run after each backfill/sync is fine; wiring it into the same
  GitHub Actions workflow as the daily sync is a natural v2 step, not required
  for this first attempt.
- **Rendering:** vanilla HTML/JS + Chart.js loaded via CDN
  (`https://cdn.jsdelivr.net/npm/chart.js`) for all charts. No build step, no
  framework - keep this simple and inspectable.
- **Folder structure** (inside the repo):
  ```
  /docs
    /data
      landscape.json
      ops.json
    index.html          <- small landing page linking both dashboards
    landscape.html
    ops.html
  ```
  Using `/docs` specifically (not e.g. `/dashboard`) because GitHub Pages can
  serve directly from a repo's `/docs` folder on the main branch - no separate
  branch or build pipeline needed for hosting.

---

## Dashboard 1: Landscape Overview (`landscape.html`)

Purpose: scan the state of the field at a glance - aggregate/business view,
not individual-trial detail.

**Header strip:** total trial count, last sync timestamp (from whatever
`pipeline_runs`/state tracking Claude Code has implemented), a small
breakdown of trials by `overall_status`.

**Trials by mechanism (bar chart):** COUNT(*) from `trials` GROUP BY
`bucket_id`, joined to `mechanism_buckets` for readable labels. Include the
`unclassified` bucket as its own bar, don't hide it - a growing unclassified
count is itself a signal worth seeing at a glance.

**Trials by phase (stacked/grouped bar):** COUNT(*) GROUP BY `phase`. Since
`phase` is stored as a raw comma-joined string from the API (see schema.sql
comment), bucket anything containing "PHASE3" as Phase 3, etc., and give
combination phases (e.g. "PHASE2,PHASE3") their own explicit category rather
than silently collapsing them into one or the other.

**New trials over time (line chart):** COUNT(*) GROUP BY year of
`start_date`, one line per `bucket_id`. This is the chart most likely to
visually surface an emerging mechanism before the curator agent formally
flags it - worth a glance each time you check the dashboard.

**Top sponsors (table, not chart):** COUNT(*) GROUP BY `sponsors.name` WHERE
`role = 'lead'`, top 15, with a column showing which mechanism bucket(s)
each sponsor is active in (helps answer "who's betting on what").

**Optional stretch, skip if it adds much build time:** clicking a bar segment
filters a small table beneath the charts to just those trials (client-side
JS filter over the already-loaded JSON, no new query needed). Nice to have,
not required for a first attempt.

---

## Dashboard 2: Pipeline Ops (`ops.html`)

Purpose: is the pipeline itself working correctly - a triage view for you as
operator, not a view of the science. This is the more important dashboard
to trust before leaning on Dashboard 1's numbers.

**Sync status strip:** last successful sync timestamp, row counts ingested
in the most recent run, any errors from the last run if Claude Code is
logging them anywhere.

**Curator proposals pending review (table):** straight from
`taxonomy_proposals` WHERE `status = 'pending'` - show `proposed_bucket_json`
(rendered readably, not raw JSON dump), `rationale`, and `proposed_at`. This
table being non-empty is the single most actionable thing this dashboard can
surface - it means something needs your judgment call.

**Low-confidence classifications needing spot-check (table):** trials WHERE
`classification_confidence` is in the 0.4-0.7 range (the "flagged" tier from
`classify_prompt.md`'s own routing logic) - NCT ID, title, assigned bucket,
confidence, rationale. Sort by confidence ascending so the shakiest calls
surface first.

**Curator watchlist (table):** straight from `curator_watchlist` - entity
name, item_count, first/last seen. Lets you see what's accumulating toward
the recurrence threshold before it clears it.

**Spot-check history (small chart + table):** from `spot_check_log` -
agreement rate (match/partial/mismatch) over time, plus the raw log entries.
Will be empty until you've actually run the manual spot-check process from
`spot_check_eval.md` at least once - that's expected, not a bug.

---

## Repo & publishing instructions for Claude Code

Repo: `dhlee47/ADscape` (private) - Claude Code should already have this
checked out locally with push access, since it's currently working on the
backfill against this repo.

1. Build both dashboards into `/docs` per the structure above.
2. Commit with a clear message (e.g. `Add landscape and ops dashboards (v1)`)
   and push to the branch Claude Code is currently working on. If it's been
   committing backfill work directly to `main`, keep doing the same here for
   consistency - branching/PR review is worth introducing later, not
   necessary to change mid-task for a solo project.
3. **One manual step outside Claude Code's control:** GitHub Pages needs to
   be enabled once, by you, in the repo's Settings -> Pages -> set source to
   "Deploy from a branch," branch `main`, folder `/docs`. This is a one-time
   repo-settings toggle, not something achievable via a plain `git push` -
   flag this back to yourself as a to-do rather than expecting Claude Code
   to have done it automatically.
4. Once Pages is enabled, both dashboards are reachable at
   `https://dhlee47.github.io/ADscape/landscape.html` and
   `https://dhlee47.github.io/ADscape/ops.html` (and `index.html` as the
   landing page linking both).
