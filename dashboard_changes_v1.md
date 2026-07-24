# landscape.html - v2 changes

Scope: `docs/landscape.html` only (the Landscape Overview dashboard). Does not
touch `ops.html`. All changes are client-side against the already-loaded
`data/landscape.json` - no new SQL queries or data export changes needed
unless noted otherwise below.

---

## 1. Status filter tabs (top of page)

Turn the four status labels (Completed / Recruiting / Unknown / Terminated)
into clickable toggle buttons.

- **Behavior:** each tab is a toggle. Clicking it turns it "on" (visually
  distinct - filled/highlighted background) and re-filters every chart and
  table on the page to only trials matching the union of currently-"on"
  tabs. Clicking an "on" tab turns it back "off."
- **All-off and all-on are equivalent:** both show every trial, unfiltered.
  (i.e. an empty filter set and a full filter set both mean "no filtering.")
- **This must cascade to the whole page** - trials-by-mechanism,
  trials-by-phase, new-trials-over-time, and the sponsor table should all
  recompute from the filtered trial set, not just the section nearest the
  tabs.
- Implementation: keep a `Set` of active statuses in JS state, filter the
  in-memory trial array against it, and re-render each chart from the
  filtered array. No page reload, no re-fetch of `landscape.json`.

---

## 2. Trials by mechanism - log10 y-axis

Switch the bar chart's y-axis to logarithmic scale (Chart.js:
`scales: { y: { type: 'logarithmic' } }`).

- **Zero-count buckets are a problem on a log axis** (log(0) is undefined).
  Handle this by excluding buckets with zero trials from this chart
  entirely, rather than trying to render a zero-height log bar - list them
  in a small "(0 trials: bucket_x, bucket_y)" caption beneath the chart
  instead, so they're not silently disappearing without explanation.

---

## 3. Trials by mechanism - hover breakdown by target

On hovering a bar, show a breakdown of that bucket's trials by the actual
intervention/drug name tested (not by bucket - by the specific compound),
as a pie chart.

- **Data source:** `interventions.name`, grouped and counted for all trials
  currently in that bucket (respecting the active status filter from #1).
- **Cap the slices:** show the top 8 interventions by count, group everything
  else into a single "Other" slice - an AD trial bucket can have dozens of
  distinct compound names, an uncapped pie is unreadable.
- **Implementation approach:** rather than rendering a pie chart floating
  inside a Chart.js tooltip (fragile, easy to get wrong), use a dedicated
  small panel on the page (e.g. to the side of or below the main chart) that
  updates to show this breakdown pie whenever a bar is hovered, and clears
  or shows a placeholder when nothing's hovered. If a true floating
  tooltip-embedded pie turns out to be easy with whatever charting approach
  is in use, that's a fine upgrade - just don't spend much time chasing it
  if it's fighting the library.

---

## 4. Trials by phase - hide N/A, hover breakdown by mechanism

- **Hide N/A:** exclude trials where `phase` is `'NA'` (the raw API value
  for not-applicable, e.g. many observational studies) from this chart.
- **Hover breakdown:** same pattern as #3, but keyed by `bucket_id` instead
  of intervention name - hovering a phase bar shows a pie chart of that
  phase's trials broken down by mechanism bucket. Same panel-based
  implementation approach as #3 (reuse the same panel/component for both
  rather than building two separate ones).

---

## 5. New trials over time by mechanism - log y-axis, hover compound list

- **Log y-axis:** same as #2, same zero-value caveat. A given
  bucket/year combination with zero trials simply won't have a plotted
  point for that year - that's fine and expected for a line chart (unlike
  the bar chart in #2, no special-case handling needed, just don't plot a
  point where the count is zero).
- **Hover on a data point:** show a list of the actual intervention/compound
  names tested among trials contributing to that point (that
  bucket + year), **capped at 5 items** - if more than 5, show 5 and append
  "+N more" (e.g. "lecanemab, donanemab, gantenerumab, solanezumab,
  bapineuzumab +3 more").
- Standard Chart.js tooltip customization is fine here (unlike #3/#4, this
  is a text list, not an embedded chart, so a floating tooltip is
  straightforward).

---

## Testing note

After implementing, sanity-check #1's cascading behavior specifically -
toggle a single status tab on and confirm all four sections (mechanism bar,
phase bar, time series, sponsor table) actually changed, not just the one
you were looking at when you tested.
