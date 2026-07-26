// Kortvyn: hämtar tjänster och portar från API:t och renderar klientside.
// Uppdateras automatiskt var 30 sekund.

const STATUS_LABELS = {
  up: "Uppe",
  down: "Nere",
  conflict: "Konflikt",
  drift: "Drift",
  starting: "Startar",
  stopping: "Stoppar",
  unknown: "Okänd",
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
  if (live.some((s) => s.status === "drift")) return "drift";
  if (live.some((s) => s.status === "conflict")) return "conflict";
  if (live.every((s) => s.status === "up")) return "up";
  if (live.every((s) => s.status === "down")) return "down";
  return "mixed";
}

const serviceUiState = new Map();

function serviceAction(svc) {
  if (!svc.controllable) return null;
  if (svc.status === "down") return { action: "start", label: "Starta" };
  if (svc.status === "up") return { action: "stop", label: "Stoppa" };
  return null;
}

function renderServiceControl(svc) {
  const state = serviceUiState.get(svc.name) || {};
  const control = serviceAction(svc);
  if (!control && !state.error) return "";
  const name = escapeHtml(svc.name);
  const activeAction = state.action || control?.action;
  const label = state.pending
    ? activeAction === "start" ? "Startar..." : "Stoppar..."
    : control?.label;
  const button = control
    ? `<button type="button" class="outline svc-action"
              data-service="${name}" data-action="${control.action}"
              aria-label="${control.label} ${name}"
              ${state.pending ? `disabled aria-busy="true"` : ""}>
        ${escapeHtml(label)}
      </button>`
    : "";
  const error = state.error
    ? `<small class="svc-action-error" role="alert">${escapeHtml(state.error)}</small>`
    : "";
  return `<div class="svc-control">${button}${error}</div>`;
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
      ${renderServiceControl(svc)}
    </div>`;
}

// Todo-räknare per projekt, fylld när /api/todos landar. Kortvyn och
// todo-sektionen hämtas oberoende, så kortet kan renderas innan siffrorna
// finns - då utelämnas raden och fylls i vid nästa rendering.
let todoCounts = new Map();

function renderProjectTodos(project) {
  const counts = todoCounts.get(project);
  if (!counts || !counts.open) return "";
  const doing = counts.doing
    ? ` <span class="badge doing">${counts.doing} pågår</span>`
    : "";
  return `
    <div class="card-todos">
      <a href="${escapeHtml(counts.url)}" target="_blank" rel="noopener">
        ${counts.open} ${counts.open === 1 ? "todo" : "todos"}
      </a>${doing}
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
      ${renderProjectTodos(services[0].project)}
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

// Portalen visar bara överblicken - detaljvyn är backlogs egen webb-UI, som
// varje rad länkar till. Sidoeffekt: fyller todoCounts åt kortvyn.
function renderTodos(data) {
  todoCounts = new Map(
    (data.projects || []).map((p) => [p.project, p])
  );
  if (!data.available) {
    return `<p class="muted">Todos otillgängliga: ${escapeHtml(data.error || "okänt fel")}.</p>`;
  }
  // Backend signalerar truncated när task-listan avkortades av gränsen - då kan
  // öppna todos saknas, vilket ska synas i stället för att döljas.
  const warning = data.truncated
    ? '<p class="notice warn">Listan är avkortad - vissa öppna todos kan saknas.</p>'
    : "";
  if (!data.projects.length) {
    return warning + '<p class="muted">Inga öppna todos.</p>';
  }
  const rows = data.projects
    .map(
      (p) => `
      <tr>
        <td><a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">${escapeHtml(p.project)}</a></td>
        <td class="num">${p.open}</td>
        <td>${p.doing ? `<span class="badge doing">${p.doing} pågår</span>` : '<span class="muted">-</span>'}</td>
      </tr>`
    )
    .join("");
  return `
    ${warning}
    <table>
      <thead><tr><th>Projekt</th><th class="num">Öppna</th><th>Pågår</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr><td>Totalt</td><td class="num">${data.total}</td><td></td></tr>
      </tfoot>
    </table>`;
}

let currentServices = [];

function renderServices(services) {
  currentServices = services;
  return services.length
    ? groupByProject(services).map(renderProjectCard).join("")
    : `<p class="muted">Inga tjänster registrerade ännu.</p>`;
}

function replaceService(service) {
  currentServices = currentServices.map((item) =>
    item.name === service.name ? service : item
  );
  document.getElementById("services").innerHTML = renderServices(currentServices);
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function settleService(service) {
  let latest = service;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    replaceService(latest);
    if (!["starting", "stopping"].includes(latest.status)) return;
    await delay(400);
    latest = await apiFetch(`/api/services/${encodeURIComponent(latest.name)}`);
  }
  replaceService(latest);
}

// Varje sektion hämtas och renderas oberoende: ett fel i en fetch fastnar
// inte de andra korten i "Laddar...", och felet pekar ut rätt sektion.
const SECTIONS = [
  {
    id: "services",
    url: "/api/services",
    label: "tjänster",
    render: renderServices,
  },
  { id: "todos", url: "/api/todos", label: "todos", render: renderTodos },
  { id: "shares", url: "/api/shares", label: "delningar", render: renderShares },
  { id: "unregistered", url: "/api/ports", label: "portar", render: renderUnregistered },
];

document.getElementById("services").addEventListener("click", async (event) => {
  const button = event.target.closest(".svc-action");
  if (!button) return;

  const action = button.dataset.action;
  const serviceName = button.dataset.service;
  const existingState = serviceUiState.get(serviceName);
  if (existingState?.pending) return;
  serviceUiState.set(serviceName, { pending: true, action, error: null });
  document.getElementById("services").innerHTML = renderServices(currentServices);

  try {
    const service = await apiFetch(
      `/api/services/${encodeURIComponent(serviceName)}/${action}`,
      { method: "POST" }
    );
    await settleService(service);
    serviceUiState.delete(serviceName);
  } catch (err) {
    serviceUiState.set(serviceName, {
      pending: false,
      action,
      error: `Kunde inte ${action === "start" ? "starta" : "stoppa"} tjänsten: ${err.message}`,
    });
  }
  document.getElementById("services").innerHTML = renderServices(currentServices);
});

async function refresh() {
  let servicesRendered = false;
  await Promise.all(
    SECTIONS.map(async (sec) => {
      const el = document.getElementById(sec.id);
      try {
        const data = await apiFetch(sec.url);
        el.innerHTML = sec.id === "services" ? renderServices(data) : sec.render(data);
        if (sec.id === "services") servicesRendered = true;
      } catch (err) {
        el.innerHTML = `<p class="muted">Kunde inte hämta ${escapeHtml(sec.label)}: ${escapeHtml(err.message)}</p>`;
      }
    })
  );
  // Sektionerna hämtas parallellt, så todo-siffrorna kan landa efter korten.
  // Rendera om korten en gång när båda finns, annars saknas räknaren tills
  // nästa varv. Bara om services-hämtningen lyckades - annars skulle ett
  // felmeddelande skrivas över med inaktuella kort.
  if (servicesRendered && todoCounts.size) {
    document.getElementById("services").innerHTML = renderServices(currentServices);
  }
  document.getElementById("refresh-info").textContent =
    "Uppdaterad " + new Date().toLocaleTimeString("sv-SE");
}

refresh();
setInterval(refresh, 30000);
