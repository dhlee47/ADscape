# landscape.html - target hover-pie: re-spec + self-check eval

This change was requested in `dashboard_changes_v2.md` (item 3) but wasn't
implemented. Before re-attempting the frontend work, diagnose *which layer*
is missing - the fix is different depending on where it's actually broken.
This has three possible failure points, in dependency order:

1. `interventions.target` isn't populated (target classification hasn't run,
   or ran but failed/produced mostly nulls)
2. `interventions.target` is populated in the db, but `data/landscape.json`
   (the static export the frontend reads) doesn't include it
3. Both of the above are fine, but the hover event handler was never wired
   up to render a target-based breakdown at all

## Step 1: check the data layer first

Run this against the live db and compare to the known test cases below:

```sql
SELECT name, target, target_confidence, target_source
FROM interventions
WHERE name IN (
  'lecanemab','donanemab','aducanumab','gantenerumab','solanezumab',
  'verubecestat','atabecestat',
  'semorinemab','gosuranemab','E2814',
  'AL002','DNL919',
  'memantine','donepezil',
  'semaglutide'
);
```

### Known test cases (ground truth - verify output matches)

| intervention name | expected target | expected bucket |
|---|---|---|
| lecanemab | amyloid-beta | anti_amyloid_immunotherapy |
| donanemab | amyloid-beta | anti_amyloid_immunotherapy |
| aducanumab | amyloid-beta | anti_amyloid_immunotherapy |
| gantenerumab | amyloid-beta | anti_amyloid_immunotherapy |
| solanezumab | amyloid-beta | anti_amyloid_immunotherapy |
| verubecestat | BACE1 | amyloid_production |
| atabecestat | BACE1 | amyloid_production |
| semorinemab | tau | tau_targeted |
| gosuranemab | tau | tau_targeted |
| E2814 | tau | tau_targeted |
| AL002 | TREM2 | neuroinflammation_microglia_complement |
| DNL919 | TREM2 | neuroinflammation_microglia_complement |
| memantine | NMDA receptor | synaptic_neurotransmitter |
| donepezil | acetylcholinesterase (AChE) | synaptic_neurotransmitter |
| semaglutide | GLP-1R | metabolic_vascular (if this bucket has been added back - see holdout_eval.json, it was deliberately withheld for the leave-one-out eval; if that eval hasn't been run/resolved yet, semaglutide may legitimately still show as unclassified) |

**If most of these come back null or clearly wrong:** the problem is upstream
of the dashboard entirely - go back and run/debug the target classification
prompt from `classify_prompt.md` first. Don't touch the frontend yet.

**If these all look correct in the db:** move to step 2.

## Step 2: check the export layer

Confirm `data/landscape.json` (or whatever the actual generated filename is)
includes a `target` field per intervention, not just `name`. If the data
generation script was written before the target field existed in the schema,
it likely needs a one-line addition to include it in the query/export -
check this before assuming it's a rendering bug.

## Step 3: the actual frontend behavior

Once target data is confirmed present in the JSON the page loads:

- Hovering a bar in "trials by mechanism" shows a pie chart (in the
  dedicated breakdown panel established in `dashboard_changes_v1.md`) of
  that bucket's trials grouped by `interventions.target`, top 8 by count +
  "Other," with `target = 'unknown'` shown as its own slice (see
  `dashboard_changes_v2.md` item 3 for the full spec - this section is
  just the functional test for it, not a re-statement of the whole spec).

### Behavioral test case (not just a data check - confirms the UI itself)

Hover the **`neuroinflammation_microglia_complement`** bar specifically.
This bucket was chosen for the test on purpose: unlike
`anti_amyloid_immunotherapy` (where nearly every trial targets the same
thing and the pie would be nearly one giant slice even if broken correctly),
this bucket should show **at least 3 visibly distinct target slices**
(TREM2, NLRP3, complement-related) if target classification and the hover
logic are both actually working. A single dominant slice here is a strong
signal something's still wrong, even if step 1's SQL check looked fine in
isolation - it's the clearest indicator that the deduping/aggregation logic
in the hover handler is grouping things incorrectly.
