// Kortvyn: hämtar tjänster och portar från API:t och renderar klientside.
// Uppdateras automatiskt var 30 sekund.

const STATUS_LABELS = {
  up: "Uppe",
  down: "Nere",
  conflict: "Konflikt",
};

function renderServiceCard(svc) {
  const status = STATUS_LABELS[svc.status] || svc.status;
  const docsLink = svc.has_docs
    ? `<a href="/docs/${encodeURIComponent(svc.name)}">Dokumentation</a>`
    : "";
  const desc = svc.description
    ? `<p class="desc">${escapeHtml(svc.description)}</p>`
    : "";
  return `
    <div class="card">
      <div class="card-head">
        <h3>${escapeHtml(svc.name)}</h3>
        <span class="badge ${escapeHtml(svc.status)}">${escapeHtml(status)}</span>
      </div>
      <span class="project">${escapeHtml(svc.project)} - port ${svc.port}</span>
      ${desc}
      <div class="card-links">
        <a href="${escapeHtml(svc.url)}">${escapeHtml(svc.url)}</a>
        ${docsLink}
      </div>
    </div>`;
}

function renderUnregistered(ports) {
  const unregistered = ports.listening.filter((p) => !p.registered);
  if (unregistered.length === 0) {
    return '<p class="muted">Alla lyssnande portar är registrerade.</p>';
  }
  const rows = unregistered
    .map(
      (p) => `
      <tr>
        <td>${p.port}</td>
        <td>${p.pids.length ? p.pids.join(", ") : '<span class="muted">okänd</span>'}</td>
        <td>${p.processes.length ? escapeHtml(p.processes.join(", ")) : '<span class="muted">okänd</span>'}</td>
      </tr>`
    )
    .join("");
  return `
    <table>
      <thead><tr><th>Port</th><th>PID</th><th>Process</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function refresh() {
  const servicesEl = document.getElementById("services");
  const unregisteredEl = document.getElementById("unregistered");
  const infoEl = document.getElementById("refresh-info");
  try {
    const [services, ports] = await Promise.all([
      apiFetch("/api/services"),
      apiFetch("/api/ports"),
    ]);
    servicesEl.innerHTML = services.length
      ? services.map(renderServiceCard).join("")
      : '<p class="muted">Inga tjänster registrerade ännu.</p>';
    unregisteredEl.innerHTML = renderUnregistered(ports);
    infoEl.textContent =
      "Uppdaterad " + new Date().toLocaleTimeString("sv-SE");
  } catch (err) {
    servicesEl.innerHTML = `<p class="muted">Kunde inte hämta tjänster: ${escapeHtml(err.message)}</p>`;
  }
}

refresh();
setInterval(refresh, 30000);
