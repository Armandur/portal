// Tema-builder: UI-wiring. Läser bas-/statusfärger + schema, ritar live-preview
// i ljust och mörkt, räknar WCAG och genererar en tokens.css-snutt. All
// färgmatematik ligger i color.js (window.ThemeColor).

const C = window.ThemeColor;

const DEFAULTS = {
  base: "#2563eb",
  scheme: "complement",
  ok: "#2f8f52",
  warn: "#b5872b",
  danger: "#b5342f",
  marker: "#d94f2b",
  prefix: "svk",
  tw: "1",
  comp: "0",
};

const STATUS_KEYS = ["ok", "warn", "danger", "marker"];
const $ = (id) => document.getElementById(id);

// --- URL-state ------------------------------------------------------------

function readState() {
  const q = new URLSearchParams(location.search);
  const s = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS)) {
    if (q.has(k)) s[k] = q.get(k);
  }
  return s;
}

function writeState(s) {
  const q = new URLSearchParams();
  for (const k of Object.keys(DEFAULTS)) {
    if (s[k] !== DEFAULTS[k]) q.set(k, s[k]);
  }
  const qs = q.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

// --- Spec: rå inputvärden -> alla härledda ljus/mörk-färger ---------------

function buildSpec(s) {
  const spec = { prefix: s.prefix || "svk", threeway: s.tw === "1", vars: {} };
  const put = (name, light) => {
    spec.vars[name] = { light, dark: C.deriveDark(light) };
  };
  spec.accent = { light: s.base, dark: C.deriveDark(s.base) };
  put("accent", s.base);
  for (const k of STATUS_KEYS) put(k, s[k]);
  // Följefärger (opt-in): schemats övriga nyanser blir extra accenter.
  spec.companions = [];
  if (s.comp === "1") {
    spec.companions = C.harmony(s.base, s.scheme)
      .slice(1)
      .map((light) => ({ light, dark: C.deriveDark(light) }));
  }
  return spec;
}

// --- tokens.css-generering ------------------------------------------------

// En accentfamilj (accent, -hover, -focus, -ink) för ett läge. suffix är ""
// för huvudaccenten, "-2"/"-3"... för följefärger.
function accentFamily(prefix, suffix, hex, mode) {
  return [
    `--${prefix}-accent${suffix}: ${hex};`,
    `--${prefix}-accent${suffix}-hover: ${C.deriveHover(hex, mode)};`,
    `--${prefix}-accent${suffix}-focus: ${C.focusRgba(hex)};`,
    // Läsbar knapptext (svart/vitt efter kontrast) - annars behåller Pico
    // vit --primary-inverse även på en ljus accent.
    `--${prefix}-accent${suffix}-ink: ${bestText(hex)};`,
  ];
}

function accentBlock(spec, mode) {
  const p = spec.prefix;
  const lines = accentFamily(p, "", spec.accent[mode], mode);
  spec.companions.forEach((c, i) => {
    lines.push(...accentFamily(p, `-${i + 2}`, c[mode], mode));
  });
  for (const k of STATUS_KEYS) lines.push(`--${p}-${k}: ${spec.vars[k][mode]};`);
  return lines;
}

function indent(lines, pad) {
  return lines.map((l) => pad + l).join("\n");
}

function generateCss(spec) {
  const p = spec.prefix;
  const light = indent(accentBlock(spec, "light"), "  ");
  const dark = indent(accentBlock(spec, "dark"), "  ");
  const darkNested = indent(accentBlock(spec, "dark"), "    ");
  const parts = [];
  parts.push(`/* Identitet ovanpå Pico - genererad av portalens tema-builder. */`);
  parts.push(`:root {\n${light}\n}`);
  if (spec.threeway) {
    // 3-vägs: auto-dark ELLER tvingat mörkt (temaväxel med data-theme).
    parts.push(
      `@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {\n${darkNested}\n  }\n}`,
    );
    parts.push(`:root[data-theme="dark"] {\n${dark}\n}`);
  } else {
    // 2-vägs: enbart prefers-color-scheme (ingen data-theme).
    parts.push(`@media (prefers-color-scheme: dark) {\n  :root {\n${darkNested}\n  }\n}`);
  }
  // Pico-primary-familjen -> accent. Trippelselektorn matchar Picos egen
  // specificitet (0,2,0) så accenten vinner även i 2-vägsläge.
  const picoSel = spec.threeway
    ? `:root:not([data-theme=dark]), :root[data-theme=light], :root[data-theme=dark]`
    : `:root:not([data-theme=dark]), :root[data-theme=dark]`;
  const picoRole = (role, suffix) => [
    `--pico-${role}: var(--${p}-accent${suffix});`,
    `--pico-${role}-hover: var(--${p}-accent${suffix}-hover);`,
    `--pico-${role}-underline: var(--${p}-accent${suffix});`,
    `--pico-${role}-background: var(--${p}-accent${suffix});`,
    `--pico-${role}-hover-background: var(--${p}-accent${suffix}-hover);`,
    `--pico-${role}-inverse: var(--${p}-accent${suffix}-ink);`,
    `--pico-${role}-focus: var(--${p}-accent${suffix}-focus);`,
  ];
  const picoLines = picoRole("primary", "");
  // Första följefärgen driver Picos sekundär-roll.
  if (spec.companions.length) picoLines.push(...picoRole("secondary", "-2"));
  parts.push(`${picoSel} {\n${indent(picoLines, "  ")}\n}`);
  return parts.join("\n\n") + "\n";
}

// --- Live-preview ---------------------------------------------------------

const SURFACE = { light: "#ffffff", dark: "#11141a" };
const TEXT = { light: "#1b1f24", dark: "#e6e9ef" };

function bestText(bg) {
  return C.contrastRatio(bg, "#ffffff") >= C.contrastRatio(bg, "#111111")
    ? "#ffffff"
    : "#111111";
}

function wcagTag(ratio) {
  const lvl = C.wcagLevel(ratio);
  const cls = lvl === "fail" ? "wc-fail" : "wc-pass";
  return `<span class="wc ${cls}">${ratio.toFixed(2)} ${lvl}</span>`;
}

function renderPreview(spec, mode) {
  const a = spec.accent[mode];
  const hover = C.deriveHover(a, mode);
  const surf = SURFACE[mode];
  const txt = TEXT[mode];
  const btnText = bestText(a);
  const status = STATUS_KEYS.map((k) => {
    const c = spec.vars[k][mode];
    return `<span class="chip" style="color:${c};border-color:${c}">${k}</span>`;
  }).join("");
  const cAccentWhite = C.contrastRatio(a, "#ffffff");
  const cAccentSurf = C.contrastRatio(a, surf);
  const cBtnText = C.contrastRatio(a, btnText);
  return `
    <div class="pv" style="background:${surf};color:${txt}">
      <div class="pv-label">${mode === "light" ? "Ljust" : "Mörkt"}</div>
      <div class="pv-row">
        <button class="pv-btn" style="background:${a};color:${btnText}">Primär</button>
        ${spec.companions.length
          ? `<button class="pv-btn" style="background:${spec.companions[0][mode]};color:${bestText(spec.companions[0][mode])}">Sekundär</button>`
          : ""}
        <button class="pv-btn pv-out" style="color:${a};border-color:${a}">Kontur</button>
        <a href="#" class="pv-link" style="color:${a}" onclick="return false">En länk</a>
      </div>
      <div class="pv-swatch" style="background:${a}"></div>
      <div class="pv-hover" style="background:${hover}"></div>
      <div class="pv-chips">${status}</div>
      <dl class="pv-wcag">
        <div><dt>Knapptext</dt><dd>${wcagTag(cBtnText)}</dd></div>
        <div><dt>Accent / vitt</dt><dd>${wcagTag(cAccentWhite)}</dd></div>
        <div><dt>Accent / yta</dt><dd>${wcagTag(cAccentSurf)}</dd></div>
      </dl>
    </div>`;
}

// --- Harmoni-swatches -----------------------------------------------------

function renderSchemes(base, scheme) {
  const hexes = C.harmony(base, scheme);
  $("schemes").innerHTML = hexes
    .map(
      (h) =>
        `<button class="hs" style="background:${h}" data-hex="${h}" title="${h} - klicka för att sätta som accent"></button>`,
    )
    .join("");
}

// --- Orkestrering ---------------------------------------------------------

function currentInputs() {
  return {
    base: $("base").value,
    scheme: $("scheme").value,
    ok: $("ok").value,
    warn: $("warn").value,
    danger: $("danger").value,
    marker: $("marker").value,
    prefix: $("prefix").value.trim() || "svk",
    tw: $("threeway").checked ? "1" : "0",
    comp: $("companions").checked ? "1" : "0",
  };
}

// Uppdaterar preview/export/swatches ur formulärets värden (rör inte hjulet).
function render() {
  const s = currentInputs();
  writeState(s);
  const spec = buildSpec(s);
  renderSchemes(s.base, s.scheme);
  $("preview").innerHTML = renderPreview(spec, "light") + renderPreview(spec, "dark");
  $("css-out").textContent = generateCss(spec);
}

// Full uppdatering vid formulärändring: rendera OCH spegla in i hjulet.
function refresh() {
  render();
  syncWheelFromInputs();
}

// --- iro.js-hjul ----------------------------------------------------------

let wheel = null;
let syncingWheel = false; // hindrar återkoppling när vi själva sätter färger

function syncWheelFromInputs() {
  if (!wheel) return;
  const s = currentInputs();
  syncingWheel = true;
  wheel.setColors(C.harmony(s.base, s.scheme));
  syncingWheel = false;
}

// Vid drag: den gripna (aktiva) punkten blir accenten, övriga sätts till
// schemats markörer. Vi rör inte den aktiva punkten (den följer pekaren) -
// så ingen kamp mot dragrörelsen.
function onWheelInput() {
  if (syncingWheel || !wheel) return;
  const base = wheel.color.hexString;
  const activeIdx = wheel.color.index;
  const markers = C.harmony(base, $("scheme").value).slice(1);
  syncingWheel = true;
  let mi = 0;
  wheel.colors.forEach((col, idx) => {
    if (idx === activeIdx) return;
    if (mi < markers.length) col.hexString = markers[mi++];
  });
  syncingWheel = false;
  $("base").value = base;
  render();
}

function initWheel(base, scheme) {
  if (!window.iro) return; // utan iro faller vi tillbaka på Coloris + swatches
  wheel = new iro.ColorPicker("#wheel", {
    width: 190,
    colors: C.harmony(base, scheme),
    layout: [{ component: iro.ui.Wheel }],
    handleRadius: 7,
    activeHandleRadius: 11,
    borderWidth: 1,
    borderColor: "rgba(128,128,128,0.4)",
  });
  wheel.on("input:change", onWheelInput);
  // Vid drag-slut: spegla in värdet i Coloris så dess miniatyr inte blir stale
  // (säkert här - draget är över, ingen kamp mot pekaren).
  wheel.on("input:end", () => {
    if (window.Coloris) $("base").dispatchEvent(new Event("input", { bubbles: true }));
  });
}

// --- Sparade teman (DB via /api/themes) -----------------------------------

let _themeSpecs = {}; // namn -> spec, för laddning utan extra hämtning

async function loadThemeList() {
  try {
    renderThemeList(await apiFetch("/api/themes"));
  } catch (e) {
    $("theme-list").innerHTML =
      `<li class="muted">Kunde inte hämta teman: ${escapeHtml(e.message)}</li>`;
  }
}

function renderThemeList(themes) {
  _themeSpecs = {};
  const list = $("theme-list");
  if (!themes.length) {
    list.innerHTML = `<li class="muted">Inga sparade teman än.</li>`;
    return;
  }
  list.innerHTML = themes
    .map((t) => {
      _themeSpecs[t.name] = t.spec;
      const url = escapeHtml(t.tokens_url);
      const n = escapeHtml(t.name);
      return `<li class="theme-item">
        <span class="theme-name">${n}</span>
        <a class="theme-url" href="${url}" target="_blank" rel="noopener">tokens.css</a>
        <span class="theme-actions">
          <button class="secondary outline" data-load="${n}">Ladda</button>
          <button class="secondary outline" data-del="${n}">Radera</button>
        </span>
      </li>`;
    })
    .join("");
}

async function saveTheme() {
  const name = $("theme-name").value.trim().toLowerCase();
  const msg = $("save-msg");
  if (!/^[a-z0-9-]+$/.test(name)) {
    msg.textContent = "Ogiltigt namn: bara a-z, 0-9 och bindestreck.";
    msg.className = "save-msg err";
    return;
  }
  try {
    const theme = await apiFetch("/api/themes", {
      method: "POST",
      body: JSON.stringify({
        name,
        spec: currentInputs(),
        tokens_css: $("css-out").textContent,
      }),
    });
    msg.innerHTML = `Sparat. Claude hämtar via <a href="${escapeHtml(theme.tokens_url)}" target="_blank" rel="noopener">${escapeHtml(theme.tokens_url)}</a>`;
    msg.className = "save-msg ok";
    loadThemeList();
  } catch (e) {
    msg.textContent = "Kunde inte spara: " + e.message;
    msg.className = "save-msg err";
  }
}

function applyTheme(name) {
  const spec = _themeSpecs[name];
  if (!spec) return;
  applyState({ ...DEFAULTS, ...spec });
  if (window.Coloris) {
    for (const id of COLOR_IDS) $(id).dispatchEvent(new Event("input", { bubbles: true }));
  }
  refresh();
  $("theme-name").value = name;
}

async function deleteTheme(name) {
  try {
    await apiFetch("/api/themes/" + encodeURIComponent(name), { method: "DELETE" });
    loadThemeList();
  } catch (e) {
    const msg = $("save-msg");
    msg.textContent = "Kunde inte radera: " + e.message;
    msg.className = "save-msg err";
  }
}

const COLOR_IDS = ["base", ...STATUS_KEYS];

function applyState(s) {
  $("base").value = s.base;
  $("scheme").value = s.scheme;
  for (const k of STATUS_KEYS) $(k).value = s[k];
  $("prefix").value = s.prefix;
  $("threeway").checked = s.tw === "1";
  $("companions").checked = s.comp === "1";
}

function init() {
  const s0 = readState();
  applyState(s0);
  initWheel(s0.base, s0.scheme);

  // Coloris (Rasmus standard-väljare) om laddad; annars faller vi tillbaka på
  // native <input type=color> så fälten fungerar även utan Coloris.
  if (window.Coloris) {
    Coloris({ themeMode: "auto", format: "hex", alpha: false });
    // Coloris läser fältens värde vid init; URL-state kan ha satt ett annat
    // värde efter det, så miniatyrerna måste speglas in (annars visar de
    // HTML-defaulten). Sker före våra egna input-lyssnare -> ingen extra refresh.
    for (const id of COLOR_IDS) {
      $(id).dispatchEvent(new Event("input", { bubbles: true }));
    }
  } else {
    for (const id of COLOR_IDS) $(id).type = "color";
  }

  // Ett färgfält per färg. Coloris avfyrar input-event på samma fält.
  for (const id of COLOR_IDS) {
    $(id).addEventListener("input", () => {
      if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test($(id).value.trim())) refresh();
    });
  }
  $("scheme").addEventListener("change", refresh);
  $("prefix").addEventListener("input", refresh);
  $("threeway").addEventListener("change", refresh);
  $("companions").addEventListener("change", refresh);

  // Klick på harmoni-swatch -> sätt som accent
  $("schemes").addEventListener("click", (e) => {
    const btn = e.target.closest(".hs");
    if (!btn) return;
    $("base").value = btn.dataset.hex;
    if (window.Coloris) $("base").dispatchEvent(new Event("input", { bubbles: true }));
    refresh();
  });

  // Sparade teman
  $("save-theme").addEventListener("click", saveTheme);
  $("theme-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); saveTheme(); }
  });
  $("theme-list").addEventListener("click", (e) => {
    const load = e.target.closest("[data-load]");
    const del = e.target.closest("[data-del]");
    if (load) applyTheme(load.dataset.load);
    else if (del) deleteTheme(del.dataset.del);
  });
  loadThemeList();

  $("copy-css").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("css-out").textContent);
      const b = $("copy-css");
      const orig = b.textContent;
      b.textContent = "Kopierat!";
      setTimeout(() => (b.textContent = orig), 1500);
    } catch {
      // Utan clipboard-behörighet: markera texten så användaren kan Ctrl+C
      const r = document.createRange();
      r.selectNodeContents($("css-out"));
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
    }
  });

  refresh();
}

document.addEventListener("DOMContentLoaded", init);
