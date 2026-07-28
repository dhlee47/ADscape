// Shared helpers for the ADscape dashboards - dense data-terminal aesthetic,
// dark mode only (dashboard_aesthetic_revamp.md). Mechanism buckets are
// grouped into 3 hand-curated modality families rather than the old 8-slot
// arbitrary categorical cycle, so chart color carries real meaning. This is
// a hand-curated mechanism-domain mapping, NOT derived from the raw
// interventions.type registry field - checked that field during planning and
// it's too noisy to split on automatically (CT.gov frequently tags monoclonal
// antibodies as generic "drug" type, not "biological"). weight = rank within
// the family by trial count (0 = most trials = darkest/most saturated).
const BUCKET_FAMILY = {
  // biologic/immunotherapy: mAbs, cell/gene therapy, TREM2/complement antibodies
  anti_amyloid_immunotherapy:            { family: "biologic", weight: 0 },
  neuroinflammation_microglia_complement: { family: "biologic", weight: 1 },
  regenerative_neurotrophic:              { family: "biologic", weight: 2 },
  tau_targeted:                           { family: "biologic", weight: 3 },
  // small-molecule/pharmacological
  synaptic_neurotransmitter:              { family: "small_molecule", weight: 0 },
  amyloid_production:                     { family: "small_molecule", weight: 1 },
  metabolic_insulin_glucose_signaling:    { family: "small_molecule", weight: 2 },
  apoe_lipid_metabolism:                  { family: "small_molecule", weight: 3 },
  pde9_cgmp_signaling:                    { family: "small_molecule", weight: 4 },
  senolytic_cellular_senescence:          { family: "small_molecule", weight: 5 },
  // non-pharmacological / catch-all
  unclassified:                           { family: "other", weight: 0 },
  ketone_metabolic_substrate:             { family: "other", weight: 1 },
};

// Each anchor validated as a 3-slot categorical set against the dark surface:
//   node validate_palette.js "#0fa8a3,#b26e00,#9573e0" --mode dark --surface "#101517"
//   -> ALL CHECKS PASS (lightness band, chroma floor, CVD separation, normal-vision floor, contrast)
// (small_molecule anchor is #b26e00, not the page accent's #c98500 - see
// FAMILY_RAMPS below for why.)
const FAMILY_ANCHOR = {
  biologic: "#0fa8a3",
  small_molecule: "#b26e00",
  other: "#9573e0",
};

// Per-family lightness ramp (weight 0 = anchor, increasing weight = lighter
// tint of the same hue), hardcoded rather than computed at runtime - the old
// runtime HSL-lightening scheme (fixed +0.055 per step, capped at L=0.82)
// produced steps as close as 0.018 apart for the 6-member small_molecule
// family, i.e. adjacent buckets read as nearly the same color. Regenerated
// per family in OKLCH and validated as an ordinal ramp
// (dashboard_changes_v4.md #2 - "avoid ... two different blues next to each
// other" applies within a family too, not just across families):
//   node validate_palette.js "#0fa8a3,#46bfba,#69d6d1,#8aeee9" --mode dark --surface "#101517" --ordinal
//   node validate_palette.js "#b26e00,#c3831a,#d29948,#e2af6b,#f1c48b,#ffdbaa" --mode dark --surface "#101517" --ordinal
//   node validate_palette.js "#9573e0,#ab8cf5" --mode dark --surface "#101517" --ordinal
//   -> ALL CHECKS PASS (all adjacent gaps >= the 0.06 OKLCH ΔL floor)
// small_molecule's anchor had to drop from #c98500 (L=0.670) to #b26e00
// (L=0.598) to fit: with 6 members needing >=0.06 apart, starting at 0.670
// forces the lightest step past OKLCH L~0.95, where this hue desaturates
// toward white faster than the gap requirement can track - verified no
// chroma-taper schedule closes that last gap from a 0.670 start.
const FAMILY_RAMPS = {
  biologic: ["#0fa8a3", "#46bfba", "#69d6d1", "#8aeee9"],
  small_molecule: ["#b26e00", "#c3831a", "#d29948", "#e2af6b", "#f1c48b", "#ffdbaa"],
  other: ["#9573e0", "#ab8cf5"],
};

function colorForBucket(bucketId) {
  const meta = BUCKET_FAMILY[bucketId];
  if (!meta) return mutedColor();
  const ramp = FAMILY_RAMPS[meta.family];
  return ramp[meta.weight] || ramp[ramp.length - 1];
}

function mutedColor() {
  return "#6b7a80"; // visible-on-near-black neutral, for "Other"/unmapped fills
}

// Generic 8-slot categorical set for ad-hoc breakdowns that aren't mechanism
// buckets or stop reasons (e.g. the mechanism-chart hover panel's top-8
// compound/target names - those are arbitrary per-hover, not a fixed
// taxonomy, so they don't get their own hand-curated family mapping):
//   node validate_palette.js "#3987e5,#d95926,#199e70,#c98500,#d55181,#008300,#9085e9,#e66767" --mode dark --surface "#101517"
//   -> ALL CHECKS PASS
const BREAKDOWN_PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

// Full bucket catalog (id + short label) - fixed, independent of what's
// present in the currently-loaded/filtered trial set. Needed so a
// zero-count bucket under the active status filter can still be named in
// the log-axis chart's "(0 trials: ...)" caption rather than just vanishing.
const BUCKET_CATALOG = [
  { bucket_id: "anti_amyloid_immunotherapy", label: "Anti-amyloid immunotherapy" },
  { bucket_id: "amyloid_production", label: "Amyloid production (secretase)" },
  { bucket_id: "tau_targeted", label: "Tau-targeted" },
  { bucket_id: "neuroinflammation_microglia_complement", label: "Neuroinflammation/microglia" },
  { bucket_id: "apoe_lipid_metabolism", label: "APOE/lipid metabolism" },
  { bucket_id: "synaptic_neurotransmitter", label: "Synaptic/neurotransmitter" },
  { bucket_id: "regenerative_neurotrophic", label: "Regenerative/neurotrophic" },
  { bucket_id: "unclassified", label: "Unclassified" },
];
// A "not yet classified" pending state (bucket_id null - e.g. new trials
// from a re-sync, before classify.py has run on them) isn't a taxonomy
// bucket and has no catalog entry. dashboard_changes_v4.md #1 folds it into
// the same "N unclassified, not shown above" text as the 'unclassified'
// bucket on every chart that used to plot it - there's no longer a code
// path that needs a synthetic bucket_id/color for this state (see git
// history for the removed UNCLASSIFIED_PENDING sentinel if reviving one).

// Fixed order for trials.stop_reason_category, excluding 'not_applicable'
// (never charted - outcomes_schema_and_dashboard.md: it's the vast majority
// of trials and would swamp the signal). A separate categorical dimension
// from mechanism buckets (different chart, own validated 4-slot set - not
// drawn from BUCKET_FAMILY's hues, no collision risk since they never appear
// on the same chart):
//   node validate_palette.js "#e66767,#3987e5,#d55181,#008300" --mode dark --surface "#101517"
//   -> ALL CHECKS PASS
const STOP_REASON_CATALOG = [
  { id: "safety_toxicity", label: "Safety/toxicity", color: "#e66767" },
  { id: "lack_of_efficacy", label: "Lack of efficacy", color: "#3987e5" },
  { id: "enrollment_futility", label: "Enrollment futility", color: "#d55181" },
  { id: "business_funding", label: "Business/funding", color: "#008300" },
  { id: "other", label: "Other", color: null }, // null => muted, see colorForStopReason
];
function colorForStopReason(id) {
  const entry = STOP_REASON_CATALOG.find((s) => s.id === id);
  return entry && entry.color ? entry.color : mutedColor();
}

// Placebo/comparator arms swamp "which compound is this bucket actually
// testing" breakdowns without being a compound at all - excluded from the
// intervention-name hover breakdowns (dashboard_changes_v1.md #3 and #5),
// not from the underlying trial data itself.
const GENERIC_INTERVENTION_RE = /placebo|sham|usual care|standard of care|no intervention|waitlist|observation only|control group/i;
function isGenericInterventionName(name) {
  return GENERIC_INTERVENTION_RE.test(name || "");
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function chartFontDefaults() {
  // Data-terminal aesthetic is monospace throughout, chart text included -
  // no separate display face this pass (dashboard_aesthetic_revamp.md).
  return {
    color: cssVar("--text-secondary"),
    font: { family: "'JetBrains Mono', ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace", size: 11 },
  };
}

// Chart.js tooltip theming - defaults to a white box regardless of page
// theme unless explicitly overridden (dashboard_aesthetic_revamp.md
// "Technical notes"). Spread this into every chart's options.plugins.tooltip.
function darkTooltipTheme() {
  return {
    backgroundColor: cssVar("--surface-raised"),
    titleColor: cssVar("--text-primary"),
    bodyColor: cssVar("--text-secondary"),
    borderColor: cssVar("--border"),
    borderWidth: 1,
    padding: 10,
    titleFont: { family: "'JetBrains Mono', ui-monospace, monospace", size: 11, weight: "600" },
    bodyFont: { family: "'JetBrains Mono', ui-monospace, monospace", size: 11 },
  };
}

async function loadJSON(path) {
  // Cache-bust: these files regenerate frequently (generate_dashboard_data.py
  // reruns after every classify/curator/accept step) and neither the local
  // dev server nor GitHub Pages sends headers that reliably force revalidation,
  // so a plain fetch() can silently serve a stale cached copy after a reload.
  const url = path + (path.includes("?") ? "&" : "?") + "_=" + Date.now();
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

function fmtInt(n) {
  return new Intl.NumberFormat("en-US").format(n);
}

function fmtDate(iso) {
  if (!iso) return "—";
  // stored as 'YYYY-MM-DD HH:MM:SS' (sqlite datetime('now'), UTC)
  return iso.replace(" ", "T") + "Z";
}

function fmtDateDisplay(iso) {
  if (!iso) return "—";
  const d = new Date(fmtDate(iso));
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const child of [].concat(children)) {
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

// Small muted crosshair icon for breakdown-panel empty states (fix #2 in
// dashboard_aesthetic_revamp.md - a real placeholder, not blank colored space).
const HOVER_ICON_SVG = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
  <circle cx="12" cy="12" r="6"/>
  <path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>
</svg>`;

function renderTable(container, columns, rows, emptyMessage) {
  container.innerHTML = "";
  if (!rows || rows.length === 0) {
    container.appendChild(el("div", { class: "empty-state", text: emptyMessage || "No data yet." }));
    return;
  }
  const table = el("table");
  const thead = el("thead");
  const headRow = el("tr");
  columns.forEach((c) => headRow.appendChild(el("th", { text: c.label })));
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = el("tbody");
  rows.forEach((row) => {
    const tr = el("tr");
    columns.forEach((c) => {
      const val = c.render ? c.render(row) : row[c.key];
      const td = el("td", { class: c.num ? "num" : "" });
      if (val instanceof Node) td.appendChild(val);
      else td.textContent = val;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);
}
