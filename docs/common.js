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
  __unclassified_pending__:               { family: "other", weight: 2 },
};

// Each anchor validated as a 3-slot categorical set against the dark surface:
//   node validate_palette.js "#0fa8a3,#c98500,#9573e0" --mode dark --surface "#101517"
//   -> ALL CHECKS PASS (lightness band, chroma floor, CVD separation, normal-vision floor, contrast)
const FAMILY_ANCHOR = {
  biologic: "#0fa8a3",
  small_molecule: "#c98500",
  other: "#9573e0",
};
const FAMILY_LIGHTNESS_STEP = 0.055; // per weight step, within-family only (not re-validated
                                      // against the categorical CVD band past the anchor - a
                                      // lighter tint of the same hue doesn't reintroduce
                                      // cross-hue confusion, it's a sequential tint, not a new color)
const FAMILY_LIGHTNESS_CEILING = 0.82;

function hexToHsl(hex) {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h, s;
  const l = (max + min) / 2;
  if (max === min) { h = s = 0; }
  else {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      default: h = (r - g) / d + 4;
    }
    h /= 6;
  }
  return [h * 360, s, l];
}
function hslToHex(h, s, l) {
  h /= 360;
  const hue2rgb = (p, q, t) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  let r, g, b;
  if (s === 0) { r = g = b = l; }
  else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }
  const toHex = (v) => Math.round(v * 255).toString(16).padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

function colorForBucket(bucketId) {
  const meta = BUCKET_FAMILY[bucketId];
  if (!meta) return mutedColor();
  const [h, s, l] = hexToHsl(FAMILY_ANCHOR[meta.family]);
  const lightened = Math.min(l + meta.weight * FAMILY_LIGHTNESS_STEP, FAMILY_LIGHTNESS_CEILING);
  return hslToHex(h, s, lightened);
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
// Not in the catalog above on purpose: a "not yet classified" pending state
// (bucket_id null - e.g. new trials from a re-sync, before classify.py has
// run on them) isn't a taxonomy bucket, so it shouldn't show up forever as
// a "(0 trials: ...)" catalog entry when the pipeline is fully caught up
// (the normal state). Charts add it dynamically only when actually present.
const UNCLASSIFIED_PENDING = { bucket_id: "__unclassified_pending__", label: "Not yet classified" };

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
