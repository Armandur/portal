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
  tw: "0",
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
  return spec;
}

// --- tokens.css-generering ------------------------------------------------

function accentBlock(spec, mode) {
  const p = spec.prefix;
  const a = spec.accent[mode];
  const hover = C.deriveHover(a, mode);
  const lines = [
    `--${p}-accent: ${a};`,
    `--${p}-accent-hover: ${hover};`,
    `--${p}-accent-focus: ${C.focusRgba(a)};`,
    // Läsbar knapptext på accenten (svart/vitt efter kontrast) - annars
    // behåller Pico vit --primary-inverse även på en ljus accent.
    `--${p}-accent-ink: ${bestText(a)};`,
  ];
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
  parts.push(
    `${picoSel} {\n` +
      `  --pico-primary: var(--${p}-accent);\n` +
      `  --pico-primary-hover: var(--${p}-accent-hover);\n` +
      `  --pico-primary-underline: var(--${p}-accent);\n` +
      `  --pico-primary-background: var(--${p}-accent);\n` +
      `  --pico-primary-hover-background: var(--${p}-accent-hover);\n` +
      `  --pico-primary-inverse: var(--${p}-accent-ink);\n` +
      `  --pico-primary-focus: var(--${p}-accent-focus);\n}`,
  );
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
  };
}

function refresh() {
  const s = currentInputs();
  writeState(s);
  const spec = buildSpec(s);
  renderSchemes(s.base, s.scheme);
  $("preview").innerHTML = renderPreview(spec, "light") + renderPreview(spec, "dark");
  $("css-out").textContent = generateCss(spec);
}

const COLOR_IDS = ["base", ...STATUS_KEYS];

function applyState(s) {
  $("base").value = s.base;
  $("scheme").value = s.scheme;
  for (const k of STATUS_KEYS) $(k).value = s[k];
  $("prefix").value = s.prefix;
  $("threeway").checked = s.tw === "1";
}

function init() {
  applyState(readState());

  // Coloris (Rasmus standard-väljare) om laddad; annars faller vi tillbaka på
  // native <input type=color> så fälten fungerar även utan Coloris.
  if (window.Coloris) {
    Coloris({ themeMode: "auto", format: "hex", alpha: false });
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

  // Klick på harmoni-swatch -> sätt som accent
  $("schemes").addEventListener("click", (e) => {
    const btn = e.target.closest(".hs");
    if (!btn) return;
    $("base").value = btn.dataset.hex;
    if (window.Coloris) $("base").dispatchEvent(new Event("input", { bubbles: true }));
    refresh();
  });

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
