// Shared helpers for the ADscape dashboards - light "scientific report"
// brand (see style.css header). All chart colors below are validated against
// the white figure surface (#ffffff) with the dataviz skill's
// validate_palette.js. Mechanism buckets are
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

// Modality families, light-mode. Each family is one hue, darkest = most
// trials. Anchors validated as a 3-slot categorical set:
//   node validate_palette.js "#006c98,#874300,#6246a0" --mode light --surface "#ffffff"
//   -> ALL CHECKS PASS
// and each ramp as an ordinal ramp (>= 0.06 OKLCH ΔL between steps, lightest
// step >= 2:1 vs surface):
//   node validate_palette.js "<ramp>" --mode light --surface "#ffffff" --ordinal
//   -> ALL CHECKS PASS for all three
// Generated in OKLCH: biologic h235 C.11 L.50+.07n; small_molecule h62
// C.125 L.46+.063n; other h295 C.14 L.47+.09n.
const FAMILY_ANCHOR = {
  biologic: "#006c98",
  small_molecule: "#874300",
  other: "#6246a0",
};
const FAMILY_LABELS = {
  biologic: "Biologics / immunotherapy",
  small_molecule: "Small molecule",
  other: "Other / non-pharmacological",
};
const FAMILY_RAMPS = {
  biologic: ["#006c98", "#2181af", "#3c96c5", "#54acdc"],
  small_molecule: ["#874300", "#9b5600", "#b0681a", "#c47c33", "#d98f48", "#efa35c"],
  other: ["#6246a0", "#7c60bd"],
};

// Mechanism-neutral single-series color (e.g. trials by phase) - brand navy
// family, deliberately not one of the modality hues so it doesn't imply a
// mechanism.
const NEUTRAL_SERIES = "#3a5f9e";

// Endpoint category pair (biomarker vs. cognitive/clinical) - its own
// dimension, not mechanism colors:
//   node validate_palette.js "#3a5f9e,#c8623a" --mode light --surface "#ffffff" -> ALL CHECKS PASS
const ENDPOINT_COLORS = { biomarker: "#3a5f9e", cognitive_clinical: "#c8623a" };

function colorForBucket(bucketId) {
  const meta = BUCKET_FAMILY[bucketId];
  if (!meta) return mutedColor();
  const ramp = FAMILY_RAMPS[meta.family];
  return ramp[meta.weight] || ramp[ramp.length - 1];
}

function mutedColor() {
  return "#9aa3af"; // neutral gray for "Other"/unmapped fills
}

// Generic 8-slot categorical set for ad-hoc breakdowns that aren't mechanism
// buckets or stop reasons (e.g. the mechanism-chart hover panel's top-8
// compound/target names - those are arbitrary per-hover, not a fixed
// taxonomy, so they don't get their own hand-curated family mapping):
//   node validate_palette.js "#2a78d6,#eb6834,#1baf7a,#eda100,#e87ba4,#008300,#6250d6,#e34948" --mode light --surface "#ffffff"
//   -> PASS; contrast WARN on 3 slots, relieved by the doughnut's legend + tooltip
const BREAKDOWN_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];

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
//   node validate_palette.js "#d6453f,#2a78d6,#b8467f,#2b8a3e" --mode light --surface "#ffffff"
//   -> PASS; CVD WARN 7.9 on magenta/green, relieved by in-segment count
//   labels, legend and 2px segment gaps
const STOP_REASON_CATALOG = [
  { id: "safety_toxicity", label: "Safety/toxicity", color: "#d6453f" },
  { id: "lack_of_efficacy", label: "Lack of efficacy", color: "#2a78d6" },
  { id: "enrollment_futility", label: "Enrollment futility", color: "#b8467f" },
  { id: "business_funding", label: "Business/funding", color: "#2b8a3e" },
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

const CHART_FONT = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif";

function chartFontDefaults() {
  return {
    color: cssVar("--text-secondary"),
    font: { family: CHART_FONT, size: 12 },
  };
}

// Apply brand defaults to Chart.js once per page.
function applyChartDefaults() {
  const f = chartFontDefaults();
  Chart.defaults.color = f.color;
  Chart.defaults.font.family = f.font.family;
  Chart.defaults.font.size = f.font.size;
  Chart.defaults.borderColor = cssVar("--gridline");
  Chart.defaults.maintainAspectRatio = false;
}

// Chart.js tooltip theming: dark navy box on the light page, so it reads as
// an overlay rather than another panel. Spread into options.plugins.tooltip.
function tooltipTheme() {
  return {
    backgroundColor: cssVar("--brand-ink"),
    titleColor: "#ffffff",
    bodyColor: "#dfe5ee",
    borderWidth: 0,
    padding: 10,
    cornerRadius: 4,
    boxPadding: 4,
    titleFont: { family: CHART_FONT, size: 12, weight: "600" },
    bodyFont: { family: CHART_FONT, size: 12 },
  };
}

// Canvas text font helper for custom label plugins.
function canvasFont(size, weight) {
  return `${weight || 400} ${size}px ${CHART_FONT}`;
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

function fmtDateShort(iso) {
  if (!iso) return "—";
  const d = new Date(fmtDate(iso));
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
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

// Pointer icon for breakdown-panel empty states.
const HOVER_ICON_SVG = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true">
  <path d="M5 3l6 16 2.5-6.5L20 10z"/>
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
  columns.forEach((c) => headRow.appendChild(el("th", { class: c.num ? "num" : "", text: c.label })));
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = el("tbody");
  rows.forEach((row) => {
    const tr = el("tr");
    columns.forEach((c) => {
      const val = c.render ? c.render(row) : row[c.key];
      const td = el("td", { class: c.num ? "num" : c.mono ? "mono" : "" });
      if (val instanceof Node) td.appendChild(val);
      else td.textContent = val;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  const scroller = el("div", { class: "table-scroll" });
  scroller.appendChild(table);
  container.appendChild(scroller);
}
