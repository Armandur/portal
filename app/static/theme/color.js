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

// --- OKLCH (perceptuellt jämn nyansrotation) ------------------------------
// Björn Ottossons OKLab/OKLCH. Roterar man nyansen i OKLCH med konstant L och
// C blir hela paletten jämn i ljushet/mättnad - till skillnad från HSL, där
// samma S/L upplevs olika ljust/mättat beroende på nyans.

function _srgbToLinear(c) {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function _linearToSrgb(c) {
  const v = c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  return clamp(Math.round(v * 255), 0, 255);
}

function hexToOklch(hex) {
  const { r, g, b } = hexToRgb(hex);
  const lr = _srgbToLinear(r), lg = _srgbToLinear(g), lb = _srgbToLinear(b);
  const l = 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb;
  const m = 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb;
  const s = 0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb;
  const l_ = Math.cbrt(l), m_ = Math.cbrt(m), s_ = Math.cbrt(s);
  const L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_;
  const a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_;
  const bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_;
  let h = (Math.atan2(bb, a) * 180) / Math.PI;
  if (h < 0) h += 360;
  return { L, C: Math.hypot(a, bb), h };
}

function _oklchToLinear(L, C, h) {
  const hr = (h * Math.PI) / 180;
  const a = C * Math.cos(hr), bb = C * Math.sin(hr);
  const l_ = L + 0.3963377774 * a + 0.2158037573 * bb;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * bb;
  const s_ = L - 0.0894841775 * a - 1.2914855480 * bb;
  const l = l_ ** 3, m = m_ ** 3, s = s_ ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
  ];
}

function _inGamut(lin) {
  const e = 1e-4;
  return lin.every((c) => c >= -e && c <= 1 + e);
}

// Gamut-mappning: ryms inte (L, C, h) i sRGB sänks C tills det gör det, med
// nyans och ljushet bevarade. Bättre än per-kanal-klamp, som förvrider nyansen
// (t.ex. mörk orange -> röd). Binärsök på C.
function oklchToHex({ L, C, h }) {
  let c = C;
  if (!_inGamut(_oklchToLinear(L, C, h))) {
    let lo = 0, hi = C;
    for (let i = 0; i < 22; i++) {
      const mid = (lo + hi) / 2;
      if (_inGamut(_oklchToLinear(L, mid, h))) lo = mid;
      else hi = mid;
    }
    c = lo;
  }
  const [lr, lg, lb] = _oklchToLinear(L, c, h);
  return rgbToHex({ r: _linearToSrgb(lr), g: _linearToSrgb(lg), b: _linearToSrgb(lb) });
}

// --- Itten/RYB-nyanswarp (Adobe Color-känslan) ----------------------------
// Adobe Colors harmonier räknas på en artistisk RYB-nyansaxel, inte den
// optiska RGB/HSL-axeln - därför blir rödas komplement grönt (inte cyan).
// Ankarpunkter [artistisk vinkel, HSL-nyans] enligt Ittens 12-färgshjul;
// HSL-kolumnen är strikt växande så mappningen kan inverteras.
const _ITTEN = [
  [0, 0], [30, 15], [60, 30], [90, 45], [120, 60], [150, 90],
  [180, 120], [210, 180], [240, 240], [270, 270], [300, 285], [330, 330], [360, 360],
];

function _interp(x, from, to) {
  x = ((x % 360) + 360) % 360;
  for (let i = 0; i < _ITTEN.length - 1; i++) {
    const a = _ITTEN[i], b = _ITTEN[i + 1];
    if (x >= a[from] && x <= b[from]) {
      const span = b[from] - a[from] || 1;
      return a[to] + ((x - a[from]) / span) * (b[to] - a[to]);
    }
  }
  return x;
}
const artistToHsl = (a) => _interp(a, 0, 1);
const hslToArtist = (h) => _interp(h, 1, 0);

// --- Harmoni-scheman ------------------------------------------------------

// Offsets i artistiska (RYB-) grader. Basen (0) ligger alltid först - övriga
// koden räknar med att index 0 är accenten. På Itten-hjulet ger triad 120°
// isär primärerna (röd/gul/blå), komplement 180° den artistiska motfärgen osv.
const SCHEME_OFFSETS = {
  complement: [0, 180],
  "split-complement": [0, 150, 210],
  analogous: [0, 30, -30],
  triad: [0, 120, 240],
  square: [0, 90, 180, 270],
  rectangle: [0, 60, 180, 240],
  "double-split": [0, -30, 30, 150, 210],
  compound: [0, 30, 150, 210],
};

// Monokrom: samma nyans, varierad ljushet (OKLCH L) - basen först, sedan
// ljusare/mörkare toner. Kan inte uttryckas som nyansoffset, därför särfall.
function _monochrome(baseHex) {
  const base = hexToOklch(baseHex);
  return [0, 0.12, -0.12, 0.24, -0.24].map((d) =>
    oklchToHex({ L: clamp(base.L + d, 0.12, 0.95), C: base.C, h: base.h }),
  );
}

// Roterar nyansen på den artistiska RYB-axeln men bygger varje färg i OKLCH
// med basens L och C - artistiska målnyanser OCH jämn mättnad/ljushet.
function harmony(baseHex, scheme) {
  if (scheme === "monochrome") return _monochrome(baseHex);
  const offsets = SCHEME_OFFSETS[scheme] || SCHEME_OFFSETS.complement;
  const base = hexToOklch(baseHex);
  const a0 = hslToArtist(hexToHsl(baseHex).h);
  return offsets.map((off) => {
    if (off === 0) return oklchToHex(base);
    const targetHsl = artistToHsl(a0 + off);
    const refHue = hexToOklch(hslToHex({ h: targetHsl, s: 100, l: 50 })).h;
    return oklchToHex({ L: base.L, C: base.C, h: refHue });
  });
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
  hexToOklch, oklchToHex, artistToHsl, hslToArtist,
  harmony, SCHEME_OFFSETS, deriveDark, deriveHover, focusRgba,
  relativeLuminance, contrastRatio, wcagLevel,
};
