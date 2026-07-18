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

function renderTodoRow(todo) {
  const prio = `P${todo.priority}`;
  const doing = todo.status === "doing"
    ? '<span class="badge doing">pågår</span>'
    : "";
  const src = todo.source
    ? `<span class="badge src">${escapeHtml(todo.source)}</span>`
    : "";
  const ctx = todo.project_path
    ? `<code class="todo-ctx">${escapeHtml(todo.project_path)}</code>`
    : "";
  // description_html är renderad + sanerad server-side (bleach allowlist),
  // därför säker att injicera. Korta beskrivningar (collapse=false) renderas
  // inline; långa fälls ihop i en <details> med prosa-summary (escapas).
  let desc = "";
  if (todo.description_html) {
    desc = todo.collapse
      ? `<details class="todo-desc">
          <summary>${escapeHtml(todo.description_summary || "Detaljer")}</summary>
          <div class="todo-desc-body">${todo.description_html}</div>
        </details>`
      : `<div class="todo-desc todo-desc-body">${todo.description_html}</div>`;
  }
  // Titeln (med ref) länkar till tasken i backlog web-UI:t.
  return `
    <div class="todo-row">
      <span class="badge prio-${escapeHtml(prio)}">${escapeHtml(prio)}</span>
      <a class="todo-title" href="${escapeHtml(todo.web_url)}" target="_blank" rel="noopener">
        <span class="todo-ref">${escapeHtml(todo.ref)}</span> ${escapeHtml(todo.title)}
      </a>
      ${doing}
      ${src}
      ${ctx}
      ${desc}
    </div>`;
}

function renderTodoCard(group) {
  const rows = group.todos.map(renderTodoRow).join("");
  return `
    <article>
      <div class="card-head">
        <h3>${escapeHtml(group.project)}</h3>
        <span class="badge">${group.todos.length}</span>
      </div>
      ${rows}
    </article>`;
}

function renderTodos(data) {
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
  return warning + data.projects.map(renderTodoCard).join("");
}

// Varje sektion hämtas och renderas oberoende: ett fel i en fetch fastnar
// inte de andra korten i "Laddar...", och felet pekar ut rätt sektion.
const SECTIONS = [
  {
    id: "services",
    url: "/api/services",
    label: "tjänster",
    render: (services) =>
      services.length
        ? groupByProject(services).map(renderProjectCard).join("")
        : '<p class="muted">Inga tjänster registrerade ännu.</p>',
  },
  { id: "todos", url: "/api/todos", label: "todos", render: renderTodos },
  { id: "shares", url: "/api/shares", label: "delningar", render: renderShares },
  { id: "unregistered", url: "/api/ports", label: "portar", render: renderUnregistered },
];

async function refresh() {
  await Promise.all(
    SECTIONS.map(async (sec) => {
      const el = document.getElementById(sec.id);
      try {
        el.innerHTML = sec.render(await apiFetch(sec.url));
      } catch (err) {
        el.innerHTML = `<p class="muted">Kunde inte hämta ${escapeHtml(sec.label)}: ${escapeHtml(err.message)}</p>`;
      }
    })
  );
  document.getElementById("refresh-info").textContent =
    "Uppdaterad " + new Date().toLocaleTimeString("sv-SE");
}

refresh();
setInterval(refresh, 30000);
