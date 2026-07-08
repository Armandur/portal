// Kortvyn: hämtar tjänster och portar från API:t och renderar klientside.
// Uppdateras automatiskt var 30 sekund.

const STATUS_LABELS = {
  up: "Uppe",
  down: "Nere",
  conflict: "Konflikt",
  mixed: "Delvis uppe",
  docs: "Docs",
};

function statusBadge(status) {
  const label = STATUS_LABELS[status] || status;
  return `<span class="badge ${escapeHtml(status)}">${escapeHtml(label)}</span>`;
}

function aggregateStatus(services) {
  // Dokumentationsposter (utan port) räknas inte in i upp/nere-bedömningen
  const live = services.filter((s) => s.status !== "docs");
  if (live.length === 0) return "docs";
  if (live.some((s) => s.status === "conflict")) return "conflict";
  if (live.every((s) => s.status === "up")) return "up";
  if (live.every((s) => s.status === "down")) return "down";
  return "mixed";
}

// Grupperar tjänster per projekt (bevarar portordningen från API:t)
function groupByProject(services) {
  const groups = new Map();
  for (const svc of services) {
    if (!groups.has(svc.project)) groups.set(svc.project, []);
    groups.get(svc.project).push(svc);
  }
  return [...groups.values()];
}

function renderServiceRow(svc, showLabel) {
  // För portlösa poster pekar huvudlänken redan på dokumentationssidan -
  // ingen separat docs-länk behövs då.
  const isDocsOnly = svc.port == null;
  const docsLink = svc.has_docs && !isDocsOnly
    ? `<a href="/docs/${encodeURIComponent(svc.name)}">Dokumentation</a>`
    : "";
  const label = svc.description || svc.name;
  const head = showLabel
    ? `<div class="svc-row-head">
         <span class="svc-label">${escapeHtml(label)}</span>
         ${statusBadge(svc.status)}
       </div>`
    : svc.description
      ? `<p class="desc">${escapeHtml(svc.description)}</p>`
      : "";
  return `
    <div class="svc-row">
      ${head}
      <div class="card-links">
        <a href="${escapeHtml(svc.url)}">${escapeHtml(svc.url)}</a>
        ${docsLink}
      </div>
    </div>`;
}

function renderProjectCard(services) {
  const multi = services.length > 1;
  const headStatus = multi ? aggregateStatus(services) : services[0].status;
  const rows = services.map((svc) => renderServiceRow(svc, multi)).join("");
  const ports = services
    .filter((s) => s.port != null)
    .map((s) => s.port)
    .join(", ");
  const portLine = ports
    ? `<span class="project">port ${escapeHtml(ports)}</span>`
    : "";
  return `
    <div class="card">
      <div class="card-head">
        <h3>${escapeHtml(services[0].project)}</h3>
        ${statusBadge(headStatus)}
      </div>
      ${portLine}
      ${rows}
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
      ? groupByProject(services).map(renderProjectCard).join("")
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
