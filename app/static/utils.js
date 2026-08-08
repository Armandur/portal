// Gemensamma hjälpare för portalens frontend.

/**
 * Hämtar JSON från API:t. Kastar Error med serverns felmeddelande
 * (detail-fältet) vid HTTP-fel.
 */
async function apiFetch(url, options = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body && body.detail) message = body.detail;
    } catch (_) {
      // Ingen JSON-kropp - behåll statusmeddelandet
    }
    throw new Error(message);
  }
  return resp.json();
}

/**
 * Kopierar text till urklipp och svarar om det gick.
 *
 * navigator.clipboard finns BARA i säker kontext, och portalen serveras över
 * http - därför är execCommand-vägen inte en artighetsfallback utan den som
 * faktiskt används. Clipboard-API:t provas först ändå, så anropsstället blir
 * rätt av sig själv om portalen någon gång går via https.
 *
 * Elementet som markeras måste ha texten som RIKTIGT innehåll. En dold
 * <textarea> fungerar inte: value sätter inga barnnoder, så selectNodeContents
 * markerar tomt och kopieringen tar med sig ingenting - execCommand svarar
 * ändå true. Verifiera därför alltid genom att klistra in, aldrig på
 * returvärdet.
 */
async function kopieraText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      // Behörighet nekad eller osäker kontext - fall igenom till execCommand
    }
  }
  const el = document.createElement("div");
  el.textContent = text;
  el.style.cssText =
    "position:fixed;top:0;left:0;opacity:0;white-space:pre;user-select:text;";
  document.body.appendChild(el);
  const sel = getSelection();
  const forra = sel.rangeCount ? sel.getRangeAt(0) : null;
  const r = document.createRange();
  r.selectNodeContents(el);
  sel.removeAllRanges();
  sel.addRange(r);
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (_) {
    ok = false;
  }
  el.remove();
  // lägg tillbaka användarens egen markering - kopieringen ska inte rycka
  // undan det hen höll på att markera
  sel.removeAllRanges();
  if (forra) sel.addRange(forra);
  return ok;
}

/**
 * Escapar text för säker HTML-interpolation - även i attributkontext.
 * textContent->innerHTML täcker < > &; vi escapar dessutom citattecken så
 * värdet inte kan bryta ut ur ett href/class-attribut. Textnoder påverkas
 * inte visuellt: &quot;/&#39; avkodas tillbaka när strängen sätts som innerHTML.
 */
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
