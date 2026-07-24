# landscape.html - v3 changes

Follows v2 (dashboard_changes_v1.md). Same scope note applies: `docs/landscape.html`
only, client-side changes against loaded JSON unless stated otherwise.

---

## 1. Revert "new trials over time by mechanism" to linear y-axis

v2 change #5 set this to log scale - undo that, back to linear
(`scales: { y: { type: 'linear' } }` or simply remove the type override).
**Keep the hover behavior from v2** (list of compound names, capped at 5,
"+N more") - only the axis scale is reverting, not the hover feature.

## 2. Add an "Active / Ongoing" status filter tab

A fifth tab alongside Completed / Recruiting / Unknown / Terminated, same
toggle behavior as the rest (see v2 change #1 - union filtering, cascades
to every chart on the page).

- Maps to the raw registry status `ACTIVE_NOT_RECRUITING` - trials that are
  ongoing but not currently enrolling new patients. This is a real,
  distinct CT.gov status that wasn't represented by any of the original
  four tabs.
- **Note on remaining unmapped statuses:** CT.gov also has
  `NOT_YET_RECRUITING`, `WITHDRAWN`, `SUSPENDED`, and
  `ENROLLING_BY_INVITATION`, none of which map to any of the five tabs
  either. For now, leave these folded into the "Unknown" tab's bucket (same
  as the original four-tab setup presumably already did) - flag this rather
  than silently deciding it, since you may want dedicated tabs for these
  later, particularly `WITHDRAWN` and `SUSPENDED`, which are meaningfully
  different from "we don't know the status."

## 3. Change "trials by mechanism" hover breakdown from compound to target

v2 change #3 specified a hover pie chart broken down by
`interventions.name` (specific compound, e.g. "AL002"). Replace with a
breakdown by `interventions.target` (the druggable target, e.g. "TREM2") -
see the schema.sql/classify_prompt.md updates that add this field, sent
alongside this file. **This requires the target-classification backfill to
have run first** - if `interventions.target` is still null/unpopulated when
this dashboard change is implemented, the hover panel will have nothing to
show. Sequence: run the target classification pass -> regenerate
`data/landscape.json` -> then this dashboard change will actually have data
to render.

- Same capping/grouping approach as v2's compound breakdown: top 8 targets
  by count within the hovered bucket, everything else grouped into "Other."
- Same panel-based implementation approach as v2 (reuse the existing
  hover-breakdown panel component - just change its data source).
- Trials with `target = 'unknown'` (the LLM's honest-uncertainty response)
  should show up as their own "Unknown" slice, not get silently dropped or
  merged into "Other" - a large Unknown slice is itself useful information
  about classification coverage.
