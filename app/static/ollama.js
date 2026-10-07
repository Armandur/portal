// Ollama-växlaren: visar registrerade endpoints, vilken som är aktiv och om
// de svarar. Egen fil och egen uppdateringstakt - kortvyns 30-sekundersvarv
// skulle annars kunna byta ut listan mitt i en klickning.

const OLLAMA_LIST = document.getElementById("ollama-endpoints");
const OLLAMA_MSG = document.getElementById("ollama-message");

let ollamaBusy = false;

function ollamaBadge(ep) {
  if (ep.up === undefined) return "";
  const state = ep.up ? "up" : "down";
  const antal = ep.models.length;
  const label = ep.up ? `${antal} ${antal === 1 ? "modell" : "modeller"}` : "Svarar inte";
  return `<span class="badge ${state}">${escapeHtml(label)}</span>`;
}

// Vad servern har laddat just nu. Tomt betyder att nästa anrop får betala
// modelladdningen, och det är värt att se innan man skickar ett jobb dit.
function renderLaddade(ep) {
  if (!ep.up) return "";
  if (!ep.laddade || !ep.laddade.length) {
    return `<p class="ollama-laddad muted">Ingen modell laddad</p>`;
  }
  return ep.laddade
    .map((m) => {
      const delar = [];
      if (m.gpu_procent !== null) delar.push(`${m.gpu_procent}% GPU`);
      if (m.context) delar.push(`${Math.round(m.context / 1024)}k kontext`);
      if (m.storlek_gb) delar.push(`${String(m.storlek_gb).replace(".", ",")} GB`);
      if (m.minuter_kvar !== null) delar.push(`${m.minuter_kvar} min kvar`);
      const tung = m.gpu_procent !== null && m.gpu_procent < 50;
      return `<p class="ollama-laddad">
        <strong>${escapeHtml(m.namn)}</strong>
        <span class="${tung ? "ollama-delvis" : "muted"}">${escapeHtml(delar.join(" - "))}</span>
      </p>`;
    })
    .join("");
}

// Rådgivande anspråk, som filanspråken i arbetar. Visar ålder och ägare och
// spärrar ingenting - den som läser avgör om hen ska vänta.
// En 20-timmarskörning blir 1200 minuter, och det går inte att läsa.
function varaktighet(minuter) {
  if (minuter < 120) return `${minuter} min`;
  const timmar = Math.floor(minuter / 60);
  const rest = minuter % 60;
  return rest ? `${timmar} h ${rest} min` : `${timmar} h`;
}

function renderAnsprak(ep) {
  if (!ep.ansprak) return "";
  const a = ep.ansprak;
  const notis = a.notis ? ` - ${a.notis}` : "";
  return `<p class="ollama-ansprak">
    <strong>${escapeHtml(a.agare)}</strong> kör här
    <span class="muted">${escapeHtml(varaktighet(a.minuter_kvar))} kvar${escapeHtml(notis)}</span>
  </p>`;
}

function renderEndpoints(endpoints) {
  if (!endpoints.length) {
    return `<p class="muted">Inga endpoints registrerade.</p>`;
  }
  return endpoints
    .map((ep) => {
      const name = escapeHtml(ep.name);
      const aktiv = ep.is_active;
      const anspraksknapp = ep.ansprak
        ? `<button type="button" class="outline secondary ollama-slapp" data-name="${name}"
                   >Släpp anspråk</button>`
        : `<button type="button" class="outline ollama-ta" data-name="${name}"
                   >Ta anspråk</button>`;
      const knapp = aktiv
        ? `<span class="badge doing">Aktiv</span>`
        : `<button type="button" class="outline ollama-pick" data-name="${name}"
                   ${ollamaBusy ? `disabled aria-busy="true"` : ""}>Använd</button>`;
      const ta_bort = aktiv
        ? ""
        : `<button type="button" class="outline secondary ollama-del" data-name="${name}"
                   aria-label="Ta bort ${name}">Ta bort</button>`;
      return `<article${aktiv ? ' class="ollama-active"' : ""}>
        <div class="card-head">
          <h3>${name}</h3>
          ${ep.stopgap ? `<span class="badge drift">Tillfällig</span>` : ""}
          ${ollamaBadge(ep)}
        </div>
        <p class="muted">${escapeHtml(ep.description || "")}</p>
        <p><code>${escapeHtml(ep.url)}</code>${
          ep.version ? ` <small class="muted">ollama ${escapeHtml(ep.version)}</small>` : ""
        }</p>
        ${renderLaddade(ep)}
        ${renderAnsprak(ep)}
        <div class="card-links">${knapp}${anspraksknapp}${ta_bort}</div>
      </article>`;
    })
    .join("");
}

function ollamaMelding(text, fel = false) {
  OLLAMA_MSG.textContent = text || "";
  OLLAMA_MSG.className = fel ? "ollama-fel" : "muted";
}

async function laddaEndpoints() {
  try {
    const data = await apiFetch("/api/ollama/endpoints?probe=1");
    OLLAMA_LIST.innerHTML = renderEndpoints(data);
  } catch (err) {
    OLLAMA_LIST.innerHTML = `<p class="muted">Kunde inte hämta endpoints: ${escapeHtml(err.message)}</p>`;
  }
}

OLLAMA_LIST.addEventListener("click", async (event) => {
  const pick = event.target.closest(".ollama-pick");
  const del = event.target.closest(".ollama-del");
  const ta = event.target.closest(".ollama-ta");
  const slapp = event.target.closest(".ollama-slapp");
  if (!pick && !del && !ta && !slapp) return;
  if (ollamaBusy) return;

  ollamaBusy = true;
  ollamaMelding("");
  try {
    if (pick) {
      const svar = await apiFetch("/api/ollama/active", {
        method: "POST",
        body: JSON.stringify({ name: pick.dataset.name }),
      });
      ollamaMelding(`Projekten pratar nu med ${svar.name}.`);
    } else if (ta) {
      const agare = prompt("Vem tar anspråket?", "portal-anvandare");
      if (agare === null) {
        ollamaBusy = false;
        return;
      }
      const svar = await apiFetch(
        `/api/ollama/endpoints/${encodeURIComponent(ta.dataset.name)}/claim`,
        { method: "POST", body: JSON.stringify({ agare, minuter: 60 }) }
      );
      ollamaMelding(`${svar.ansprak.agare} har ${ta.dataset.name} i 60 minuter.`);
    } else if (slapp) {
      await apiFetch(
        `/api/ollama/endpoints/${encodeURIComponent(slapp.dataset.name)}/claim`,
        { method: "DELETE" }
      );
      ollamaMelding(`Anspråket på ${slapp.dataset.name} släppt.`);
    } else {
      await apiFetch(`/api/ollama/endpoints/${encodeURIComponent(del.dataset.name)}`, {
        method: "DELETE",
      });
      ollamaMelding(`${del.dataset.name} borttagen.`);
    }
  } catch (err) {
    ollamaMelding(err.message, true);
  }
  ollamaBusy = false;
  await laddaEndpoints();
});

document.getElementById("ollama-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  ollamaMelding("");
  try {
    await apiFetch("/api/ollama/endpoints", {
      method: "POST",
      body: JSON.stringify({
        name: form.namn.value,
        url: form.url.value,
        description: form.beskrivning.value,
      }),
    });
    form.reset();
    ollamaMelding("Endpoint tillagd.");
  } catch (err) {
    ollamaMelding(err.message, true);
  }
  await laddaEndpoints();
});

laddaEndpoints();
setInterval(laddaEndpoints, 60000);
