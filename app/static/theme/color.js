// Tema-builder: ren färgmatematik. Enda sanningskällan för konverteringar,
// harmoni-scheman, ljus->mörk-derivering och WCAG-kontrast. Ingen DOM här.

// --- Konverteringar -------------------------------------------------------

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}

function hexToRgb(hex) {
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function rgbToHex({ r, g, b }) {
  const to = (v) => clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

function rgbToHsl({ r, g, b }) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let h = 0, s = 0;
  const d = max - min;
  if (d !== 0) {
    s = d / (1 - Math.abs(2 * l - 1));
    switch (max) {
      case r: h = ((g - b) / d) % 6; break;
      case g: h = (b - r) / d + 2; break;
      default: h = (r - g) / d + 4;
    }
    h *= 60;
    if (h < 0) h += 360;
  }
  return { h, s: s * 100, l: l * 100 };
}

function hslToRgb({ h, s, l }) {
  h = ((h % 360) + 360) % 360;
  s = clamp(s, 0, 100) / 100;
  l = clamp(l, 0, 100) / 100;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r = 0, g = 0, b = 0;
  if (h < 60) { r = c; g = x; }
  else if (h < 120) { r = x; g = c; }
  else if (h < 180) { g = c; b = x; }
  else if (h < 240) { g = x; b = c; }
  else if (h < 300) { r = x; b = c; }
  else { r = c; b = x; }
  return { r: (r + m) * 255, g: (g + m) * 255, b: (b + m) * 255 };
}

function hexToHsl(hex) {
  return rgbToHsl(hexToRgb(hex));
}

function hslToHex(hsl) {
  return rgbToHex(hslToRgb(hsl));
}

// --- Harmoni-scheman ------------------------------------------------------

// Returnerar hex-nyanser (inkl. bas) enligt valt schema. Roterar nyansen i
// HSL och behåller mättnad/ljushet - enkelt men förutsägbart för en MVP.
const SCHEME_OFFSETS = {
  monochrome: [0],
  complement: [0, 180],
  "split-complement": [0, 150, 210],
  analogous: [0, 30, -30],
  triad: [0, 120, 240],
  tetrad: [0, 90, 180, 270],
};

function harmony(baseHex, scheme) {
  const base = hexToHsl(baseHex);
  const offsets = SCHEME_OFFSETS[scheme] || SCHEME_OFFSETS.complement;
  return offsets.map((deg) => hslToHex({ ...base, h: base.h + deg }));
}

// --- Ljus <-> mörk-derivering ---------------------------------------------

// Mörkvariant av en accent-/statusfärg: behåll nyans, dämpa mättnad en aning
// och lyft ljusheten så färgen läser mot en mörk bakgrund. Reverse-engineerat
// ur befintliga tokens.css-par (portal-blå, svk-panorama-grön).
function deriveDark(lightHex) {
  const { h, s, l } = hexToHsl(lightHex);
  return hslToHex({
    h,
    s: clamp(s, 25, 78),
    l: clamp(l + 22, 52, 70),
  });
}

// Hover-nyans: mörkare i ljust läge, ljusare i mörkt läge.
function deriveHover(hex, mode) {
  const { h, s, l } = hexToHsl(hex);
  const dl = mode === "dark" ? 10 : -8;
  return hslToHex({ h, s, l: clamp(l + dl, 0, 100) });
}

function focusRgba(hex, alpha = 0.375) {
  const { r, g, b } = hexToRgb(hex);
  return `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${alpha})`;
}

// --- WCAG-kontrast --------------------------------------------------------

function _linear(c) {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

function relativeLuminance(hex) {
  const { r, g, b } = hexToRgb(hex);
  return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b);
}

function contrastRatio(hex1, hex2) {
  const l1 = relativeLuminance(hex1);
  const l2 = relativeLuminance(hex2);
  const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

// WCAG-nivå för normal text (AA 4.5, AAA 7) och stor text/UI (AA 3).
function wcagLevel(ratio) {
  if (ratio >= 7) return "AAA";
  if (ratio >= 4.5) return "AA";
  if (ratio >= 3) return "AA stor";
  return "fail";
}

window.ThemeColor = {
  clamp, hexToRgb, rgbToHex, rgbToHsl, hslToRgb, hexToHsl, hslToHex,
  harmony, SCHEME_OFFSETS, deriveDark, deriveHover, focusRgba,
  relativeLuminance, contrastRatio, wcagLevel,
};
