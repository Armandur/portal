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
    ? `<span class="card-project">port ${escapeHtml(ports)}</span>`
    : "";
  return `
    <article>
      <div class="card-head">
        <h3>${escapeHtml(services[0].project)}</h3>
        ${statusBadge(headStatus)}
      </div>
      ${portLine}
      ${rows}
    </article>`;
}

function humanSize(n) {
  if (typeof n !== "number") return "?";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return i === 0 ? `${n} B` : `${n.toFixed(1)} ${units[i]}`;
}

function renderShares(shares) {
  if (!shares.length) {
    return '<p class="muted">Inga aktiva delningar.</p>';
  }
  const rows = shares
    .map(
      (s) => `
      <tr>
        <td><a href="${escapeHtml(s.url)}">${escapeHtml(s.filename)}</a></td>
        <td>${s.description ? escapeHtml(s.description) : '<span class="muted">-</span>'}</td>
        <td>${escapeHtml(humanSize(s.size))}</td>
        <td>${
          s.expires_at
            ? escapeHtml(new Date(s.expires_at).toLocaleString("sv-SE"))
            : '<span class="muted">aldrig</span>'
        }</td>
      </tr>`
    )
    .join("");
  return `
    <table>
      <thead><tr><th>Fil</th><th>Beskrivning</th><th>Storlek</th><th>Går ut</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
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
  const sharesEl = document.getElementById("shares");
  const unregisteredEl = document.getElementById("unregistered");
  const infoEl = document.getElementById("refresh-info");
  try {
    const [services, ports, shares] = await Promise.all([
      apiFetch("/api/services"),
      apiFetch("/api/ports"),
      apiFetch("/api/shares"),
    ]);
    servicesEl.innerHTML = services.length
      ? groupByProject(services).map(renderProjectCard).join("")
      : '<p class="muted">Inga tjänster registrerade ännu.</p>';
    sharesEl.innerHTML = renderShares(shares);
    unregisteredEl.innerHTML = renderUnregistered(ports);
    infoEl.textContent =
      "Uppdaterad " + new Date().toLocaleTimeString("sv-SE");
  } catch (err) {
    servicesEl.innerHTML = `<p class="muted">Kunde inte hämta tjänster: ${escapeHtml(err.message)}</p>`;
  }
}

refresh();
setInterval(refresh, 30000);
