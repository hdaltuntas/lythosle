/* Lythosle front end -------------------------------------------------------
 * Keeps one plain object for the model and one for the analysis options,
 * renders the form from it, posts it to /api/analyze and draws the result.
 * No build step and no framework: the page is served straight from disk.
 * ------------------------------------------------------------------------ */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const PALETTE = ["#D97757", "#C4A883", "#7EA89B", "#9B8AA6", "#B5A642",
                 "#8FA6C4", "#C98B8B", "#6F8F6F", "#A88C6B", "#8C8C8C"];

const state = {
  model: null,
  options: null,
  result: null,
  methods: [],
  examples: [],
  busy: false,
};

/* ------------------------------------------------------------- utilities */
function clone(obj) { return JSON.parse(JSON.stringify(obj)); }

function num(v, fallback = 0) {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : fallback;
}

function fmt(v, digits = 2) {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function setPath(obj, path, value) {
  const keys = path.split(".");
  let node = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    if (node[keys[i]] == null || typeof node[keys[i]] !== "object") node[keys[i]] = {};
    node = node[keys[i]];
  }
  node[keys[keys.length - 1]] = value;
}

function pointsToText(pts) {
  if (!pts) return "";
  return pts.map((p) => `${p[0]} ${p[1]}`).join("\n");
}

function textToPoints(text) {
  const out = [];
  for (const line of text.split(/[\n;]/)) {
    const parts = line.trim().split(/[\s,]+/).filter(Boolean);
    if (parts.length < 2) continue;
    const x = parseFloat(parts[0]), y = parseFloat(parts[1]);
    if (Number.isFinite(x) && Number.isFinite(y)) out.push([x, y]);
  }
  return out;
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, isError ? 7000 : 3200);
}

function download(name, text, type = "application/json") {
  const blob = new Blob([text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ------------------------------------------------------------ default model */
function slopeProfile(height, ratio, toeBench, crestBench) {
  const x1 = toeBench, x2 = x1 + ratio * height;
  return [[0, 0], [x1, 0], [x2, height], [x2 + crestBench, height]];
}

function defaultModel() {
  return {
    name: "New slope",
    units: "metric",
    profile: slopeProfile(10, 2, 12, 20),
    water_unit_weight: 9.81,
    materials: [{
      name: "Soil 1", unit_weight: 19, sat_unit_weight: 20,
      strength_model: "mohr_coulomb", cohesion: 5, friction_angle: 30,
      su: 0, su_gradient: 0, ru: 0, color: PALETTE[1], impenetrable: false,
    }],
    layers: [{ material: "Soil 1" }],
    water_table: null,
    seismic: { kh: 0, kv: 0 },
    surcharges: [],
    supports: [],
    tension_crack: { enabled: false, depth: null, auto: false, water_fill: 0 },
  };
}

function defaultOptions() {
  return {
    methods: ["ordinary", "bishop", "janbu_corrected", "spencer", "morgenstern_price"],
    n_slices: 50,
    force_function: "half_sine",
    direction: "auto",
    search_each_method: false,
    search: {
      mode: "auto", method: "bishop", n_slices: 25,
      nx: 12, ny: 12, n_tangent: 12, refine_passes: 3,
      radius_mode: "tangent", optimize: false,
    },
  };
}

/* ------------------------------------------------------------------ forms */
function renderBoundFields() {
  $$("[data-path]").forEach((el) => {
    const value = getPath(state, el.dataset.path);
    if (el.type === "checkbox") el.checked = Boolean(value);
    else if (value === null || value === undefined) el.value = "";
    else el.value = value;
  });
  $$("[data-points]").forEach((el) => {
    el.value = pointsToText(getPath(state, el.dataset.points));
  });
}

function bindInputs() {
  document.addEventListener("change", (ev) => {
    const el = ev.target;
    if (el.dataset && el.dataset.path) {
      let value;
      if (el.type === "checkbox") value = el.checked;
      else if (el.type === "number") value = el.value === "" ? null : num(el.value);
      else value = el.value;
      setPath(state, el.dataset.path, value);
      if (el.dataset.path === "model.name" || el.dataset.path.startsWith("model.")) syncJsonEditor();
    }
    if (el.dataset && el.dataset.points) {
      const pts = textToPoints(el.value);
      setPath(state, el.dataset.points, pts.length ? pts : null);
      syncJsonEditor();
      drawPlot();
    }
  });
}

function materialRow(mat, index) {
  const undrained = mat.strength_model === "undrained";
  return `
  <div class="item" data-material="${index}">
    <div class="item-head">
      <input type="color" value="${mat.color || PALETTE[index % PALETTE.length]}"
             data-path="model.materials.${index}.color" aria-label="Colour">
      <input type="text" value="${escapeAttr(mat.name)}" data-mat-name="${index}" aria-label="Name">
      <button class="btn danger" data-remove-material="${index}" title="Remove">&times;</button>
    </div>
    <div class="row">
      <label class="field"><span>Unit weight &gamma;</span>
        <input type="number" step="0.1" data-path="model.materials.${index}.unit_weight"></label>
      <label class="field"><span>Saturated &gamma;<sub>sat</sub></span>
        <input type="number" step="0.1" data-path="model.materials.${index}.sat_unit_weight"></label>
    </div>
    <label class="field"><span>Strength model</span>
      <select data-path="model.materials.${index}.strength_model" data-rerender="materials">
        <option value="mohr_coulomb">Mohr-Coulomb (c', &phi;')</option>
        <option value="undrained">Undrained (s<sub>u</sub>)</option>
        <option value="infinite">Infinitely strong</option>
        <option value="no_strength">No strength</option>
      </select></label>
    ${undrained ? `
    <div class="row three">
      <label class="field"><span>s<sub>u</sub></span>
        <input type="number" step="0.5" data-path="model.materials.${index}.su"></label>
      <label class="field"><span>d s<sub>u</sub>/dz</span>
        <input type="number" step="0.1" data-path="model.materials.${index}.su_gradient"></label>
      <label class="field"><span>datum y</span>
        <input type="number" step="0.5" data-path="model.materials.${index}.su_datum"></label>
    </div>` : `
    <div class="row three">
      <label class="field"><span>c'</span>
        <input type="number" step="0.5" data-path="model.materials.${index}.cohesion"></label>
      <label class="field"><span>&phi;' (deg)</span>
        <input type="number" step="0.5" data-path="model.materials.${index}.friction_angle"></label>
      <label class="field"><span>r<sub>u</sub></span>
        <input type="number" step="0.05" min="0" max="1" data-path="model.materials.${index}.ru"></label>
    </div>`}
    <label class="check"><input type="checkbox" data-path="model.materials.${index}.impenetrable"
      data-rerender="none"> Impenetrable (slip surfaces stay above it)</label>
  </div>`;
}

function escapeAttr(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderMaterials() {
  $("#materials").innerHTML = state.model.materials.map(materialRow).join("");
  renderLayers();
}

function renderLayers() {
  const options = state.model.materials
    .map((m) => `<option value="${escapeAttr(m.name)}">${escapeAttr(m.name)}</option>`).join("");
  $("#layers").innerHTML = state.model.layers.map((lay, i) => `
    <div class="item">
      <div class="item-head">
        <span class="swatch" style="background:${materialColor(lay.material)}"></span>
        <select data-path="model.layers.${i}.material">${options}</select>
        ${i ? `<button class="btn danger" data-remove-layer="${i}">&times;</button>` : ""}
      </div>
      ${i ? `<label class="field"><span>Top boundary &mdash; <code>x y</code> per line</span>
        <textarea rows="4" data-points="model.layers.${i}.boundary"></textarea></label>`
          : `<p class="hint">This layer starts at the ground surface.</p>`}
    </div>`).join("");
  renderBoundFields();
}

function materialColor(name) {
  const m = state.model.materials.find((x) => x.name === name);
  return (m && m.color) || "#8C8C8C";
}

function renderSurcharges() {
  $("#surcharges").innerHTML = (state.model.surcharges || []).map((s, i) => `
    <div class="item">
      <div class="row three">
        <label class="field"><span>x from</span><input type="number" step="0.5" data-path="model.surcharges.${i}.x1"></label>
        <label class="field"><span>x to</span><input type="number" step="0.5" data-path="model.surcharges.${i}.x2"></label>
        <label class="field"><span>pressure</span><input type="number" step="1" data-path="model.surcharges.${i}.pressure"></label>
      </div>
      <div class="item-head">
        <label class="check"><input type="checkbox" data-path="model.surcharges.${i}.include_in_seismic"> seismic inertia</label>
        <button class="btn danger" data-remove-surcharge="${i}">&times;</button>
      </div>
    </div>`).join("");
  renderBoundFields();
}

function renderSupports() {
  $("#supports").innerHTML = (state.model.supports || []).map((s, i) => `
    <div class="item">
      <div class="item-head">
        <input type="text" value="${escapeAttr(s.name || "Support")}" data-path="model.supports.${i}.name">
        <button class="btn danger" data-remove-support="${i}">&times;</button>
      </div>
      <div class="row">
        <label class="field"><span>head x</span><input type="number" step="0.5" data-path="model.supports.${i}.x1"></label>
        <label class="field"><span>head y</span><input type="number" step="0.5" data-path="model.supports.${i}.y1"></label>
      </div>
      <div class="row">
        <label class="field"><span>anchor x</span><input type="number" step="0.5" data-path="model.supports.${i}.x2"></label>
        <label class="field"><span>anchor y</span><input type="number" step="0.5" data-path="model.supports.${i}.y2"></label>
      </div>
      <label class="field"><span>Capacity (force per unit width)</span>
        <input type="number" step="5" data-path="model.supports.${i}.capacity"></label>
    </div>`).join("");
  renderBoundFields();
}

function renderMethodChoices() {
  $("#methods").innerHTML = "<legend>Methods</legend>" + state.methods.map((m) => `
    <label class="check"><input type="checkbox" data-method="${m.key}"
      ${state.options.methods.includes(m.key) ? "checked" : ""}> ${m.label}</label>`).join("");
  $("#primary-method").innerHTML = state.methods
    .map((m) => `<option value="${m.key}">${m.label}</option>`).join("");
  $("#primary-method").value = state.options.search.method;
}

function renderAll() {
  renderMaterials();
  renderSurcharges();
  renderSupports();
  renderMethodChoices();
  renderBoundFields();
  $("#water-mode").value = state.model.water_table ? "table" : "none";
  $("#water-fields").hidden = !state.model.water_table;
  syncJsonEditor();
  drawPlot();
}

function syncJsonEditor() {
  const editor = $("#json-editor");
  if (document.activeElement !== editor) {
    editor.value = JSON.stringify({ model: state.model, options: state.options }, null, 2);
  }
}

/* ------------------------------------------------------------- API calls */
async function api(path, options) {
  const response = await fetch(path, options);
  let payload;
  try { payload = await response.json(); }
  catch (err) { throw new Error(`${response.status} ${response.statusText}`); }
  if (!response.ok) throw new Error(payload.error || `${response.status}`);
  return payload;
}

async function loadExamples() {
  const data = await api("/api/examples");
  state.examples = data.examples;
  $("#example-select").innerHTML = '<option value="">Load an example…</option>' +
    data.examples.map((e) => `<option value="${e.key}">${e.title}</option>`).join("");
}

async function loadMethods() {
  const data = await api("/api/methods");
  state.methods = data.methods;
}

async function loadExample(key) {
  if (!key) return;
  const data = await api(`/api/examples/${key}`);
  state.model = data.model;
  state.options = Object.assign(defaultOptions(), data.options);
  state.options.search = Object.assign(defaultOptions().search, data.options.search || {});
  normaliseModel();
  renderAll();
  // show the real profile rather than the template generator
  const pointsTab = $$(".seg-btn").find((b) => b.dataset.geom === "points");
  if (pointsTab) pointsTab.click();
  await run();
}

function normaliseModel() {
  const m = state.model;
  m.units = m.units || "metric";
  if (m.water_unit_weight == null) m.water_unit_weight = m.units === "imperial" ? 62.4 : 9.81;
  m.seismic = m.seismic || { kh: 0, kv: 0 };
  m.surcharges = m.surcharges || [];
  m.supports = m.supports || [];
  m.tension_crack = m.tension_crack || { enabled: false, depth: null, auto: false, water_fill: 0 };
  m.materials.forEach((mat, i) => {
    mat.color = mat.color || PALETTE[i % PALETTE.length];
    mat.strength_model = mat.strength_model || "mohr_coulomb";
  });
  m.layers = m.layers && m.layers.length ? m.layers : [{ material: m.materials[0].name }];
}

async function run() {
  if (state.busy) return;
  state.busy = true;
  const button = $("#run");
  button.disabled = true;
  $(".spinner", button).hidden = false;
  $(".label", button).textContent = "Running…";
  const started = performance.now();
  try {
    applyManualBox();
    const result = await api("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: state.model, options: state.options }),
    });
    state.result = result;
    renderResults();
    drawPlot();
    if (result.ok) {
      toast(`${result.methods.length} methods in ${((performance.now() - started) / 1000).toFixed(1)} s`);
    } else {
      toast(result.notes[0] || "no slip surface found", true);
    }
  } catch (err) {
    toast(err.message, true);
  } finally {
    state.busy = false;
    button.disabled = false;
    $(".spinner", button).hidden = true;
    $(".label", button).textContent = "Run analysis";
  }
}

function applyManualBox() {
  const search = state.options.search;
  if (!$("#manual-box").checked) {
    delete search.center_x; delete search.center_y; delete search.tangent_y;
    return;
  }
  const g = (id) => num($(id).value, NaN);
  const pairs = [["center_x", "#box-x0", "#box-x1"], ["center_y", "#box-y0", "#box-y1"],
                 ["tangent_y", "#box-t0", "#box-t1"]];
  for (const [key, a, b] of pairs) {
    const lo = g(a), hi = g(b);
    if (Number.isFinite(lo) && Number.isFinite(hi)) search[key] = [lo, hi];
    else delete search[key];
  }
}

/* --------------------------------------------------------------- results */
function fsClass(fs) {
  if (!Number.isFinite(fs)) return "";
  if (fs < 1.0) return "bad";
  if (fs < 1.3) return "warn";
  return "ok";
}

function renderResults() {
  const r = state.result;
  const tbody = $("#method-table tbody");
  if (!r || !r.ok) {
    $("#fs-value").textContent = "—";
    $("#fs-value").className = "fs-value";
    $("#fs-method").textContent = (r && r.notes && r.notes[0]) || "no result";
    tbody.innerHTML = "";
    $("#notes").innerHTML = "";
    $("#summary").textContent = "";
    return;
  }
  const primary = r.methods.find((m) => m.method === r.primary_method) || r.methods[0];
  $("#fs-value").textContent = fmt(primary.fs, 3);
  $("#fs-value").className = "fs-value " + fsClass(primary.fs);
  $("#fs-method").textContent = `${primary.label} — critical surface of ${r.methods.length} method${r.methods.length > 1 ? "s" : ""}`;

  const s = r.surface || {};
  const meta = [
    ["Surface", s.kind === "circular" ? "circular" : "non-circular"],
    s.kind === "circular" ? ["Centre", `${fmt(s.xc, 1)}, ${fmt(s.yc, 1)}`] : null,
    s.kind === "circular" ? ["Radius", fmt(s.radius, 1)] : null,
    ["Sliding weight", fmt(r.mass && r.mass.weight, 0)],
    ["Slices", r.mass ? r.mass.n_slices : "—"],
    ["Surfaces tried", r.search ? r.search.evaluated : "—"],
    ["Run time", `${fmt(r.runtime_s, 2)} s`],
  ].filter(Boolean);
  $("#fs-meta").innerHTML = meta.map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join("");

  tbody.innerHTML = r.methods.map((m) => {
    const per = r.per_method && r.per_method[m.method];
    const fsText = fmt(m.fs, 3) + (per ? ` <span class="hint">(${fmt(per.fs, 3)} own)</span>` : "");
    return `<tr class="${m.method === r.primary_method ? "primary-row" : ""}">
      <td>${m.label}${m.converged ? "" : ' <span class="hint">not converged</span>'}</td>
      <td class="num-strong">${fsText}</td>
      <td>${m.equilibrium}</td>
      <td>${m.lambda === null || m.lambda === undefined ? "—" : fmt(m.lambda, 3)}</td>
      <td>${m.iterations || "—"}</td>
    </tr>`;
  }).join("");

  const notes = [...(r.notes || []), ...r.methods.flatMap((m) => m.notes || [])];
  $("#notes").innerHTML = [...new Set(notes)].map((n) => `<li>${escapeAttr(n)}</li>`).join("");

  renderSliceTable(r.slices || []);
  renderLambdaPlot();
  $("#summary").textContent = summaryText(r);
}

function summaryText(r) {
  const lines = [];
  lines.push(`${r.name}  (${r.units})`);
  lines.push("=".repeat(56));
  const g = r.geometry || {};
  lines.push(`slope height        ${fmt(g.height, 2)}`);
  lines.push(`average inclination ${fmt(g.angle, 1)} deg`);
  lines.push(`toe / crest         x = ${fmt(g.x_toe, 2)} / ${fmt(g.x_crest, 2)}`);
  if (r.mass) {
    lines.push(`sliding weight      ${fmt(r.mass.weight, 1)} per unit width`);
    if (r.mass.crack_depth) lines.push(`tension crack depth ${fmt(r.mass.crack_depth, 2)}`);
    if (r.mass.supports && r.mass.supports.length) {
      lines.push(`reinforcement       ${r.mass.supports.length} element(s) intersected`);
    }
  }
  lines.push("");
  lines.push("method                          FS      equilibrium      lambda");
  lines.push("-".repeat(64));
  for (const m of r.methods) {
    lines.push(`${m.label.padEnd(30)}${fmt(m.fs, 3).padStart(6)}  ${m.equilibrium.padEnd(16)}` +
               `${m.lambda == null ? "" : fmt(m.lambda, 3)}`);
  }
  if (r.search) {
    lines.push("");
    lines.push(`surfaces evaluated  ${r.search.evaluated} (${r.search.rejected} rejected)`);
  }
  return lines.join("\n");
}

const SLICE_COLUMNS = [
  ["index", "#", 0], ["x", "x", 2], ["width", "b", 3], ["alpha_deg", "α (deg)", 2],
  ["height", "h", 2], ["weight", "W", 1], ["base_length", "l", 3], ["u", "u", 1],
  ["cohesion", "c", 1], ["phi_deg", "φ (deg)", 1], ["material", "material", null],
  ["normal_stress", "σn", 1], ["shear_strength", "τf", 1], ["shear_mobilised", "τm", 1],
];

function renderSliceTable(rows) {
  const table = $("#slice-table");
  table.querySelector("thead").innerHTML =
    `<tr>${SLICE_COLUMNS.map(([, label]) => `<th>${label}</th>`).join("")}</tr>`;
  table.querySelector("tbody").innerHTML = rows.map((row) => `<tr>${
    SLICE_COLUMNS.map(([key, , digits]) => {
      const v = row[key];
      return `<td>${digits === null ? escapeAttr(v) : fmt(v, digits)}</td>`;
    }).join("")}</tr>`).join("");
}

/* ------------------------------------------------------------- plotting */
function svgEl(tag, attrs, text) {
  const parts = Object.entries(attrs || {})
    .map(([k, v]) => `${k}="${typeof v === "number" ? round(v) : v}"`).join(" ");
  return text === undefined ? `<${tag} ${parts}/>` : `<${tag} ${parts}>${text}</${tag}>`;
}

function round(v) { return Math.round(v * 100) / 100; }

function niceStep(range, target) {
  const raw = range / Math.max(target, 1);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
  return step * mag;
}

function drawPlot() {
  const svg = $("#plot");
  const render = state.result && state.result.render;
  const width = Math.max(svg.clientWidth || svg.parentElement.clientWidth || 900, 480);

  let extents;
  if (render) {
    extents = render.extents;
  } else if (state.model && state.model.profile && state.model.profile.length > 1) {
    const xs = state.model.profile.map((p) => p[0]);
    const ys = state.model.profile.map((p) => p[1]);
    const h = Math.max(...ys) - Math.min(...ys) || 1;
    extents = { x_min: Math.min(...xs), x_max: Math.max(...xs),
                y_min: Math.min(...ys) - 0.15 * h, y_max: Math.max(...ys) + 0.1 * h };
  } else {
    svg.innerHTML = "";
    return;
  }

  const pad = { l: 46, r: 18, t: 16, b: 34 };
  let xRange = extents.x_max - extents.x_min || 1;
  let yRange = extents.y_max - extents.y_min || 1;
  // include the circle centre and the search grid so nothing is clipped away
  const extra = [];
  if (render && render.surface && render.surface.kind === "circular") {
    extra.push([render.surface.xc, render.surface.yc]);
  }
  if (render && render.search_grid && $("#show-grid").checked) {
    render.search_grid.forEach((g) => extra.push([g.x, g.y]));
  }
  let xMin = extents.x_min, xMax = extents.x_max, yMin = extents.y_min, yMax = extents.y_max;
  for (const [x, y] of extra) {
    xMin = Math.min(xMin, x - 0.02 * xRange); xMax = Math.max(xMax, x + 0.02 * xRange);
    yMin = Math.min(yMin, y - 0.02 * yRange); yMax = Math.max(yMax, y + 0.03 * yRange);
  }
  xRange = xMax - xMin; yRange = yMax - yMin;

  const plotW = width - pad.l - pad.r;
  const scale = plotW / xRange;
  const plotH = Math.min(Math.max(yRange * scale, 220), 620);
  const height = plotH + pad.t + pad.b;
  const sy = plotH / yRange;
  const X = (x) => pad.l + (x - xMin) * scale;
  const Y = (y) => pad.t + plotH - (y - yMin) * sy;
  const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${round(X(p[0]))},${round(Y(p[1]))}`).join("");

  const out = [];
  out.push(svgEl("rect", { x: 0, y: 0, width, height, fill: "var(--plot-bg)" }));

  // axes -------------------------------------------------------------
  const xStep = niceStep(xRange, 10), yStep = niceStep(yRange, 6);
  for (let x = Math.ceil(xMin / xStep) * xStep; x <= xMax; x += xStep) {
    out.push(svgEl("line", { x1: X(x), y1: pad.t, x2: X(x), y2: pad.t + plotH,
                             stroke: "var(--grid)", "stroke-width": 1 }));
    out.push(svgEl("text", { x: X(x), y: height - 12, "text-anchor": "middle",
                             fill: "var(--text-3)", "font-size": 10.5 }, round(x)));
  }
  for (let y = Math.ceil(yMin / yStep) * yStep; y <= yMax; y += yStep) {
    out.push(svgEl("line", { x1: pad.l, y1: Y(y), x2: pad.l + plotW, y2: Y(y),
                             stroke: "var(--grid)", "stroke-width": 1 }));
    out.push(svgEl("text", { x: pad.l - 7, y: Y(y) + 3.5, "text-anchor": "end",
                             fill: "var(--text-3)", "font-size": 10.5 }, round(y)));
  }

  if (render) {
    // materials -------------------------------------------------------
    for (const layer of render.layers) {
      out.push(svgEl("path", { d: path(layer.polygon) + "Z", fill: layer.color,
                               "fill-opacity": 0.5, stroke: layer.color,
                               "stroke-opacity": 0.85, "stroke-width": 1 }));
    }
    // water table -----------------------------------------------------
    if (render.water_table) {
      out.push(svgEl("path", { d: path(render.water_table), fill: "none",
                               stroke: "var(--water)", "stroke-width": 1.8,
                               "stroke-dasharray": "7 4" }));
      const p0 = render.water_table[0];
      out.push(svgEl("path", { d: `M${round(X(p0[0]) + 4)},${round(Y(p0[1]))}l6,-7h-12z`,
                               fill: "var(--water)" }));
    }
    // surcharges ------------------------------------------------------
    for (const s of render.surcharges || []) {
      const x1 = Math.min(s.x1, s.x2), x2 = Math.max(s.x1, s.x2);
      const top = Math.max(s.y1, s.y2) + 0.06 * yRange;
      out.push(svgEl("line", { x1: X(x1), y1: Y(top), x2: X(x2), y2: Y(top),
                               stroke: "var(--text-2)", "stroke-width": 1.4 }));
      const n = Math.max(2, Math.round((x2 - x1) * scale / 26));
      for (let i = 0; i <= n; i++) {
        const x = x1 + (x2 - x1) * i / n;
        out.push(svgEl("path", { d: `M${round(X(x))},${round(Y(top))}V${round(Y(top) + 13)}` +
                                    `m-3,-4l3,4l3,-4`, fill: "none",
                                 stroke: "var(--text-2)", "stroke-width": 1.2 }));
      }
      out.push(svgEl("text", { x: X(0.5 * (x1 + x2)), y: Y(top) - 5, "text-anchor": "middle",
                               fill: "var(--text-2)", "font-size": 10.5 }, `${s.pressure}`));
    }
    // search grid -----------------------------------------------------
    if (render.search_grid && $("#show-grid").checked && render.search_grid.length) {
      const values = render.search_grid.map((g) => g.fs);
      const lo = Math.min(...values), hi = Math.max(...values);
      const best = render.search_grid.reduce((a, b) => (b.fs < a.fs ? b : a));
      out.push(svgEl("circle", { cx: X(best.x), cy: Y(best.y), r: 6, fill: "none",
                                 stroke: "var(--accent)", "stroke-width": 1.4 }));
      for (const g of render.search_grid) {
        const t = hi > lo ? (g.fs - lo) / (hi - lo) : 0;
        out.push(svgEl("circle", { cx: X(g.x), cy: Y(g.y), r: 2.2,
                                   fill: heat(t), "fill-opacity": 0.8 }));
      }
    }
    // reinforcement ---------------------------------------------------
    for (const sup of render.supports || []) {
      out.push(svgEl("path", { d: path([sup.p1, sup.p2]), stroke: "var(--accent-2)",
                               "stroke-width": 2, fill: "none" }));
      out.push(svgEl("circle", { cx: X(sup.p1[0]), cy: Y(sup.p1[1]), r: 2.6,
                                 fill: "var(--accent-2)" }));
    }
    // slices ----------------------------------------------------------
    if (render.slices && $("#show-slices").checked) {
      for (const s of render.slices) {
        out.push(svgEl("path", { d: path(s.polygon) + "Z", fill: "none",
                                 stroke: "var(--text-3)", "stroke-width": 0.5,
                                 "stroke-opacity": 0.75 }));
      }
    }
    // tension crack ---------------------------------------------------
    if (render.tension_crack) {
      const tc = render.tension_crack;
      out.push(svgEl("path", { d: path([[tc.x, tc.y_top], [tc.x, tc.y_bottom]]),
                               stroke: "var(--bad)", "stroke-width": 2, fill: "none" }));
    }
    // ground surface --------------------------------------------------
    out.push(svgEl("path", { d: path(render.profile), fill: "none",
                             stroke: "var(--text)", "stroke-width": 1.6 }));
    // critical surface ------------------------------------------------
    if (render.surface) {
      const surf = render.surface;
      if (surf.kind === "circular") {
        const c = [surf.xc, surf.yc];
        for (const end of [surf.points[0], surf.points[surf.points.length - 1]]) {
          out.push(svgEl("path", { d: path([c, end]), stroke: "var(--accent)",
                                   "stroke-width": 1, "stroke-dasharray": "4 4",
                                   "stroke-opacity": 0.6, fill: "none" }));
        }
        out.push(svgEl("path", { d: `M${round(X(c[0]) - 6)},${round(Y(c[1]))}h12` +
                                    `M${round(X(c[0]))},${round(Y(c[1]) - 6)}v12`,
                                 stroke: "var(--accent)", "stroke-width": 1.6 }));
      }
      out.push(svgEl("path", { d: path(surf.points), fill: "none",
                               stroke: "var(--accent)", "stroke-width": 2.6,
                               "stroke-linecap": "round" }));
      const fs = state.result && state.result.critical_fs;
      if (Number.isFinite(fs)) {
        const mid = surf.points[Math.floor(surf.points.length / 2)];
        const label = `FS = ${fmt(fs, 3)}`;
        const lx = X(mid[0]), ly = Y(mid[1]) + 20;
        out.push(svgEl("rect", { x: lx - 34, y: ly - 13, width: 68, height: 19, rx: 5,
                                 fill: "var(--accent)" }));
        out.push(svgEl("text", { x: lx, y: ly + 0.5, "text-anchor": "middle", fill: "#fff",
                                 "font-size": 11.5, "font-weight": 500 }, label));
      }
    }
    // legend ----------------------------------------------------------
    if ($("#show-legend").checked) {
      const items = render.layers.map((l) => [l.color, l.material]);
      const seen = new Set();
      const names = [...new Set(items.map((i) => i[1]))];
      const boxW = 26 + 7 * Math.max(...names.map((n) => n.length), 4);
      out.push(svgEl("rect", { x: pad.l + 4, y: pad.t + 2, width: boxW,
                               height: 15 * names.length + 6, rx: 6,
                               fill: "var(--plot-bg)", "fill-opacity": 0.82 }));
      let ly = pad.t + 14;
      for (const [color, name] of items) {
        if (seen.has(name)) continue;
        seen.add(name);
        out.push(svgEl("rect", { x: pad.l + 10, y: ly - 7, width: 9, height: 9, rx: 2, fill: color }));
        out.push(svgEl("text", { x: pad.l + 24, y: ly + 1.5, fill: "var(--text-2)",
                                 "font-size": 11 }, escapeAttr(name)));
        ly += 15;
      }
    }
  } else if (state.model) {
    out.push(svgEl("path", { d: path(state.model.profile), fill: "none",
                             stroke: "var(--text)", "stroke-width": 1.6 }));
    out.push(svgEl("text", { x: width / 2, y: pad.t + plotH / 2, "text-anchor": "middle",
                             fill: "var(--text-3)", "font-size": 13 },
                   "Run an analysis to find the critical surface"));
  }

  svg.setAttribute("viewBox", `0 0 ${round(width)} ${round(height)}`);
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);
  svg.innerHTML = out.join("");
}

function heat(t) {
  // low FS (t = 0) reads as the warning colour, high FS fades to neutral
  const stops = [[0, [188, 80, 56]], [0.5, [201, 140, 62]], [1, [110, 130, 120]]];
  let a = stops[0], b = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i][0] && t <= stops[i + 1][0]) { a = stops[i]; b = stops[i + 1]; break; }
  }
  const f = b[0] === a[0] ? 0 : (t - a[0]) / (b[0] - a[0]);
  const c = a[1].map((v, i) => Math.round(v + (b[1][i] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function renderLambdaPlot() {
  const svg = $("#lambda-plot");
  const r = state.result;
  const series = (r && r.methods || []).filter((m) => m.lambda_plot && m.lambda_plot.length);
  if (!series.length) {
    svg.innerHTML = svgEl("text", { x: 20, y: 30, fill: "var(--text-3)", "font-size": 12 },
                          "Run Spencer or Morgenstern-Price to see the lambda plot");
    return;
  }
  const m = series[0];
  const pts = m.lambda_plot.filter((p) => p.fm && p.ff);
  const width = Math.max(svg.clientWidth || 800, 420), height = 260;
  const pad = { l: 48, r: 110, t: 16, b: 34 };
  const lams = pts.map((p) => p["lambda"]);
  const values = pts.flatMap((p) => [p.fm, p.ff]);
  const xMin = Math.min(...lams), xMax = Math.max(...lams);
  let yMin = Math.min(...values), yMax = Math.max(...values);
  const padY = 0.08 * (yMax - yMin || 1);
  yMin -= padY; yMax += padY;
  const X = (v) => pad.l + (v - xMin) / (xMax - xMin || 1) * (width - pad.l - pad.r);
  const Y = (v) => pad.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (height - pad.t - pad.b);
  const line = (key, color) => pts.map((p, i) =>
    `${i ? "L" : "M"}${round(X(p["lambda"]))},${round(Y(p[key]))}`).join("");

  const out = [];
  const yStep = niceStep(yMax - yMin, 5);
  for (let y = Math.ceil(yMin / yStep) * yStep; y <= yMax; y += yStep) {
    out.push(svgEl("line", { x1: pad.l, y1: Y(y), x2: width - pad.r, y2: Y(y),
                             stroke: "var(--grid)", "stroke-width": 1 }));
    out.push(svgEl("text", { x: pad.l - 7, y: Y(y) + 3.5, "text-anchor": "end",
                             fill: "var(--text-3)", "font-size": 10.5 }, round(y)));
  }
  const xStep = niceStep(xMax - xMin, 6);
  for (let x = Math.ceil(xMin / xStep) * xStep; x <= xMax; x += xStep) {
    out.push(svgEl("text", { x: X(x), y: height - 12, "text-anchor": "middle",
                             fill: "var(--text-3)", "font-size": 10.5 }, round(x)));
  }
  out.push(svgEl("path", { d: line("fm", ""), fill: "none", stroke: "var(--accent)", "stroke-width": 2 }));
  out.push(svgEl("path", { d: line("ff", ""), fill: "none", stroke: "var(--water)", "stroke-width": 2 }));
  if (Number.isFinite(m.lambda) && Number.isFinite(m.fs)) {
    out.push(svgEl("circle", { cx: X(m.lambda), cy: Y(m.fs), r: 4.5, fill: "var(--text)" }));
    out.push(svgEl("text", { x: X(m.lambda) + 8, y: Y(m.fs) - 8, fill: "var(--text)",
                             "font-size": 11 }, `λ = ${fmt(m.lambda, 3)}, FS = ${fmt(m.fs, 3)}`));
  }
  out.push(svgEl("text", { x: width - pad.r + 12, y: pad.t + 14, fill: "var(--accent)",
                           "font-size": 11.5 }, "moment  Fm"));
  out.push(svgEl("text", { x: width - pad.r + 12, y: pad.t + 32, fill: "var(--water)",
                           "font-size": 11.5 }, "force  Ff"));
  out.push(svgEl("text", { x: width - pad.r + 12, y: pad.t + 54, fill: "var(--text-3)",
                           "font-size": 11 }, m.label.split(" (")[0]));
  svg.setAttribute("viewBox", `0 0 ${round(width)} ${height}`);
  svg.innerHTML = out.join("");
}

/* --------------------------------------------------------------- wiring */
function initTheme() {
  const fromUrl = new URLSearchParams(location.search).get("theme");
  const saved = ["auto", "light", "dark"].includes(fromUrl)
    ? fromUrl : (localStorage.getItem("lythosle-theme") || "auto");
  document.documentElement.dataset.theme = saved;
  $("#theme-toggle").addEventListener("click", () => {
    const order = ["auto", "light", "dark"];
    const next = order[(order.indexOf(document.documentElement.dataset.theme) + 1) % 3];
    document.documentElement.dataset.theme = next;
    localStorage.setItem("lythosle-theme", next);
    toast(`theme: ${next}`);
    drawPlot();
    renderLambdaPlot();
  });
}

function initEvents() {
  $("#run").addEventListener("click", run);
  $("#example-select").addEventListener("change", (ev) => loadExample(ev.target.value));

  $("#add-material").addEventListener("click", () => {
    const i = state.model.materials.length;
    state.model.materials.push({
      name: `Soil ${i + 1}`, unit_weight: 19, sat_unit_weight: 20,
      strength_model: "mohr_coulomb", cohesion: 5, friction_angle: 30,
      su: 0, su_gradient: 0, ru: 0, color: PALETTE[i % PALETTE.length], impenetrable: false,
    });
    renderMaterials(); renderBoundFields(); syncJsonEditor();
  });

  $("#add-layer").addEventListener("click", () => {
    const model = state.model;
    const ys = model.profile.map((p) => p[1]);
    const depth = (Math.max(...ys) - Math.min(...ys)) || 10;
    const xs = model.profile.map((p) => p[0]);
    const base = Math.min(...ys) - 0.4 * depth * model.layers.length;
    model.layers.push({
      material: model.materials[Math.min(model.layers.length, model.materials.length - 1)].name,
      boundary: [[Math.min(...xs), base], [Math.max(...xs), base]],
    });
    renderLayers(); syncJsonEditor(); drawPlot();
  });

  $("#add-surcharge").addEventListener("click", () => {
    const xs = state.model.profile.map((p) => p[0]);
    const span = (Math.max(...xs) - Math.min(...xs)) / 6;
    state.model.surcharges.push({ x1: Math.max(...xs) - 2 * span, x2: Math.max(...xs) - span,
                                  pressure: 20, include_in_seismic: false });
    renderSurcharges(); syncJsonEditor();
  });

  $("#add-support").addEventListener("click", () => {
    const xs = state.model.profile.map((p) => p[0]);
    const ys = state.model.profile.map((p) => p[1]);
    const mid = (Math.min(...xs) + Math.max(...xs)) / 2;
    state.model.supports.push({ name: `Support ${state.model.supports.length + 1}`,
                                x1: mid, y1: (Math.min(...ys) + Math.max(...ys)) / 2,
                                x2: mid + 0.15 * (Math.max(...xs) - Math.min(...xs)),
                                y2: Math.min(...ys), capacity: 100 });
    renderSupports(); syncJsonEditor(); drawPlot();
  });

  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-remove-material],[data-remove-layer]," +
                                 "[data-remove-surcharge],[data-remove-support]");
    if (!el) return;
    const d = el.dataset;
    if (d.removeMaterial !== undefined) {
      if (state.model.materials.length < 2) return toast("keep at least one material", true);
      const removed = state.model.materials.splice(Number(d.removeMaterial), 1)[0];
      state.model.layers = state.model.layers.filter((l) => l.material !== removed.name);
      if (!state.model.layers.length) state.model.layers = [{ material: state.model.materials[0].name }];
      renderMaterials();
    } else if (d.removeLayer !== undefined) {
      state.model.layers.splice(Number(d.removeLayer), 1); renderLayers();
    } else if (d.removeSurcharge !== undefined) {
      state.model.surcharges.splice(Number(d.removeSurcharge), 1); renderSurcharges();
    } else if (d.removeSupport !== undefined) {
      state.model.supports.splice(Number(d.removeSupport), 1); renderSupports();
    }
    renderBoundFields(); syncJsonEditor(); drawPlot();
  });

  // renaming a material has to follow through into the layers
  document.addEventListener("input", (ev) => {
    const el = ev.target;
    if (el.dataset && el.dataset.matName !== undefined) {
      const i = Number(el.dataset.matName);
      const old = state.model.materials[i].name;
      state.model.materials[i].name = el.value;
      state.model.layers.forEach((l) => { if (l.material === old) l.material = el.value; });
      renderLayers(); syncJsonEditor();
    }
  });

  document.addEventListener("change", (ev) => {
    const el = ev.target;
    if (el.dataset && el.dataset.rerender === "materials") { renderMaterials(); renderBoundFields(); }
    if (el.dataset && el.dataset.method !== undefined) {
      const key = el.dataset.method;
      const set = new Set(state.options.methods);
      el.checked ? set.add(key) : set.delete(key);
      state.options.methods = state.methods.map((m) => m.key).filter((k) => set.has(k));
      if (!state.options.methods.includes(state.options.search.method)) {
        state.options.search.method = state.options.methods[0] || "bishop";
        $("#primary-method").value = state.options.search.method;
      }
      syncJsonEditor();
    }
    if (el.id === "water-mode") {
      const on = el.value === "table";
      $("#water-fields").hidden = !on;
      if (on && !state.model.water_table) {
        const xs = state.model.profile.map((p) => p[0]);
        const ys = state.model.profile.map((p) => p[1]);
        const y = Math.min(...ys) + 0.25 * (Math.max(...ys) - Math.min(...ys));
        state.model.water_table = [[Math.min(...xs), y], [Math.max(...xs), y]];
      } else if (!on) {
        state.model.water_table = null;
      }
      renderBoundFields(); syncJsonEditor(); drawPlot();
    }
    if (el.id === "manual-box") $("#box-fields").hidden = !el.checked;
    if (["show-slices", "show-grid", "show-legend"].includes(el.id)) drawPlot();
  });

  $$(".seg-btn").forEach((btn) => btn.addEventListener("click", () => {
    $$(".seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
    $("#geom-template").hidden = btn.dataset.geom !== "template";
    $("#geom-points").hidden = btn.dataset.geom !== "points";
  }));

  $("#t-apply").addEventListener("click", () => {
    state.model.profile = slopeProfile(num($("#t-height").value, 10), num($("#t-ratio").value, 2),
                                       num($("#t-toe").value, 12), num($("#t-crest").value, 20));
    renderBoundFields(); syncJsonEditor(); drawPlot();
    toast("profile updated");
  });

  $$("#tabs .tab").forEach((tab) => tab.addEventListener("click", () => {
    $$("#tabs .tab").forEach((t) => t.classList.toggle("active", t === tab));
    $$(".tab-panel").forEach((p) => { p.hidden = p.dataset.panel !== tab.dataset.tab; });
    if (tab.dataset.tab === "lambda") renderLambdaPlot();
  }));

  $("#json-apply").addEventListener("click", () => {
    try {
      const data = JSON.parse($("#json-editor").value);
      state.model = data.model || data;
      if (data.options) state.options = Object.assign(defaultOptions(), data.options);
      normaliseModel();
      renderAll();
      $("#json-status").textContent = "applied";
    } catch (err) {
      $("#json-status").textContent = `could not parse: ${err.message}`;
      toast("invalid JSON", true);
    }
  });

  $("#json-download").addEventListener("click", () => {
    const name = (state.model.name || "model").replace(/\W+/g, "-").toLowerCase();
    download(`${name}.json`, JSON.stringify({ model: state.model, options: state.options }, null, 2));
  });

  $("#download-svg").addEventListener("click", () => {
    const svg = $("#plot").cloneNode(true);
    svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const styles = getComputedStyle(document.documentElement);
    let markup = new XMLSerializer().serializeToString(svg);
    markup = markup.replace(/var\(--([\w-]+)\)/g,
                            (_, name) => styles.getPropertyValue(`--${name}`).trim() || "#888");
    download("slope-section.svg", markup, "image/svg+xml");
  });

  $("#download-csv").addEventListener("click", () => {
    const rows = (state.result && state.result.slices) || [];
    if (!rows.length) return toast("nothing to export yet", true);
    const keys = Object.keys(rows[0]);
    const csv = [keys.join(",")].concat(
      rows.map((r) => keys.map((k) => (r[k] === null ? "" : r[k])).join(","))).join("\n");
    download("slices.csv", csv, "text/csv");
  });

  window.addEventListener("resize", () => { drawPlot(); renderLambdaPlot(); });
  document.addEventListener("keydown", (ev) => {
    if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") { ev.preventDefault(); run(); }
  });
}

async function init() {
  initTheme();
  bindInputs();
  initEvents();
  state.model = defaultModel();
  state.options = defaultOptions();
  try {
    await Promise.all([loadMethods(), loadExamples()]);
  } catch (err) {
    toast(`could not reach the server: ${err.message}`, true);
  }
  renderAll();
  const wanted = new URLSearchParams(location.search).get("example");
  const start = state.examples.find((e) => e.key === wanted) || state.examples[0];
  if (start) {
    $("#example-select").value = start.key;
    await loadExample(start.key);
  }
}

init();
