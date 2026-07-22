// Shared helpers for the ADscape dashboards. Categorical order follows
// taxonomy.json's bucket order (fixed order, never re-cycled) - see
// dataviz skill's color-formula.md for why order matters for CVD safety.
const BUCKET_ORDER = [
  "anti_amyloid_immunotherapy",
  "amyloid_production",
  "tau_targeted",
  "neuroinflammation_microglia_complement",
  "apoe_lipid_metabolism",
  "synaptic_neurotransmitter",
  "regenerative_neurotrophic",
  "unclassified",
  "__unclassified_pending__",
];

const isDark = () => {
  const stamped = document.documentElement.getAttribute("data-theme");
  if (stamped === "dark") return true;
  if (stamped === "light") return false;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
};

const CATEGORICAL = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948", "#898781"],
  dark:  ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767", "#898781"],
};

function colorForBucket(bucketId) {
  const idx = BUCKET_ORDER.indexOf(bucketId);
  const palette = CATEGORICAL[isDark() ? "dark" : "light"];
  return idx === -1 ? palette[palette.length - 1] : palette[idx % palette.length];
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function chartFontDefaults() {
  return {
    color: cssVar("--text-secondary"),
    font: { family: "system-ui, -apple-system, 'Segoe UI', sans-serif", size: 12 },
  };
}

async function loadJSON(path) {
  const res = await fetch(path);
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
