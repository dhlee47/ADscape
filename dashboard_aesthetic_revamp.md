# Dashboard aesthetic revamp: dense data-terminal (dark mode)

Applies to both `landscape.html` and `ops.html` - they should read as one
consistent product, not two independently-styled pages. The
`frontend-design` plugin is installed and should activate automatically for
this work; use plan mode to preview the direction before writing CSS.

## Purpose and audience

This is a personal research/ops tool for tracking Alzheimer's disease
clinical trials by mechanism, sponsor, and outcome - built and used by one
person (a bench scientist) who wants to monitor the pipeline the way you'd
monitor a live system, not read a polished report. Not a marketing page,
not a client-facing deliverable. Data density and legibility matter more
than visual flourish.

## Direction: dense data-terminal

Aesthetic reference point: a trading/monitoring terminal - dark background,
high-contrast accent colors carrying real meaning, monospace typography,
tight information density. You have real latitude on the specific palette
and layout choices within that direction - this is a brief, not a pixel
spec. Make deliberate choices and commit to them rather than defaulting to
generic dark-mode-with-purple-accents.

## Specific problems in the current version to fix

The current dashboard (cream/beige background, card-based, rounded
corners, default rainbow chart palette) has a few concrete issues worth
addressing as part of this revamp, not just a color swap:

- **The mechanism bar chart's colors carry no meaning** - currently a
  default categorical palette cycling through red/orange/green/blue/purple/
  gray/pink with no logic. In the new palette, colors should map to
  something real - e.g. group buckets by broad category (immunotherapy vs.
  small-molecule vs. non-pharmacological) with related hues, or use a
  single accent hue at varying intensity rather than unrelated colors per
  bar.
- **The hover-breakdown panel is a large blank colored box when nothing's
  hovered** (see dashboard_changes_v1.md for its original spec) - give it a
  proper empty state (a muted placeholder icon + short instruction text),
  not empty colored space.
- **The "Endpoint outcomes by category" empty state is currently just flat
  text** - since this section will stay empty for a while (endpoint
  assessments haven't been populated yet, see outcomes_schema_and_dashboard.md),
  give its empty state real visual treatment - explain what it will show
  once populated, not just absence.
- **Status filter tabs** should read clearly as toggles in a dark UI -
  active/inactive states need to be obvious at a glance (e.g. filled +
  glowing accent color when on, outlined/muted when off), not just a subtle
  shade shift that's hard to read against a dark background.

## Technical notes for dark mode specifically

- Chart.js needs explicit theming for dark backgrounds - default gridlines,
  axis labels, and tooltip backgrounds assume a light background and will
  be unreadable or jarring otherwise. Set gridline colors to something
  subtle (low-opacity light gray, not pure white), tooltip backgrounds to
  match the panel color (not Chart.js's default white), and confirm text
  contrast against the dark background meets reasonable readability
  standards.
- Use monospace fonts with tabular figures for numbers specifically (stats
  strip, table columns, chart axis labels) so numbers align vertically -
  this is a big part of what makes a dashboard feel like a terminal rather
  than a themed webpage.
- Check the pie/donut charts (trials by phase, hover breakdowns) still read
  clearly against dark backgrounds - some default chart color sets look
  fine on light backgrounds and muddy on dark ones.

## Process

Use plan mode to propose the specific palette, font choices, and layout
adjustments before implementing - this is exactly the kind of change worth
previewing rather than discovering after a full rewrite. Once approved,
implement consistently across both HTML files and commit/push per the
repo instructions already established (dhlee47/ADscape).
