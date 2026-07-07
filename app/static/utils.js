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

/** Escapar text för säker HTML-interpolation. */
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}
