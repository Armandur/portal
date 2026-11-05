// Modelljobb: pågående körningar grupperade per endpoint, med förlopp,
// beräknad sluttid och previews. Jobben pollas ofta, endpointernas hälsa
// sällan - en sondering kostar en timeout per nedsläckt maskin.

const MJ_LISTA = document.getElementById("mj-lista");
const MJ_AVSLUTADE = document.getElementById("mj-avslutade");
const MJ_FEL = document.getElementById("mj-fel");
const MJ_DLG = document.getElementById("mj-dlg");

let mjJobb = { pagaende: [], avslutade: [] };
let mjEndpoints = [];

function mjTid(s) {
  if (s === null || s === undefined) return "okänt";
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1).replace(".", ",")} h`;
}

function mjKlocka(sekunderKvar) {
  return new Date(Date.now() + sekunderKvar * 1000)
    .toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" });
}

const mjDecimal = (x) => String(x).replace(".", ",");

function mjSpar(s) {
  const okand = s.totalt === null;
  const takt = s.per_enhet ? `${mjDecimal(s.per_enhet)} s per enhet` : "takt okänd än";
  let info;
  if (s.lage === "klar") info = `klar · ${s.klara} st · ${takt}`;
  else if (s.lage === "väntar") info = "väntar · sluttid okänd tills spåret startat";
  else if (okand) info = `${s.klara} gjorda · ${takt} · totalt okänt`;
  else {
    const kvar = s.kvar_sekunder !== null
      ? ` · klart ${mjKlocka(s.kvar_sekunder)} (om ${mjTid(s.kvar_sekunder)})` : "";
    info = `${s.klara} av ${s.totalt} (${s.procent} %) · ${takt}${kvar}`;
  }
  // Modellens egna siffror, när klienten skickar dem (VERSION 2).
  const extra = [];
  if (s.tok_per_s) extra.push(`${mjDecimal(s.tok_per_s)} tok/s`);
  if (s.avklippta) extra.push(`${s.avklippta} avklippta`);
  if (extra.length) info += ` · ${extra.join(" · ")}`;
  const vantar = s.vantar_sekunder !== null && s.vantar_sekunder !== undefined
    ? `<span class="spar-info ${s.fastnat ? "mj-fastnat" : ""}">${s.fastnat ? "Har troligen fastnat: " : ""}väntar på svar sedan ${escapeHtml(mjTid(s.vantar_sekunder))}${s.anrop_rubrik ? ` (${escapeHtml(s.anrop_rubrik)})` : ""}</span>` : "";
  const bredd = s.lage === "klar" ? 100 : (s.procent || 0);
  // Okänt totalt: stapeln glider i stället, och då får ingen inline-bredd
  // skriva över den.
  const stil = okand && s.lage !== "klar" ? "" : ` style="width:${bredd}%"`;
  return `<div class="spar"><span class="spar-namn">${escapeHtml(s.modell)}</span>
    <div class="mj-bar ${s.lage === "klar" ? "klar" : ""} ${okand && s.lage === "pågår" ? "okand" : ""}"
      role="progressbar" aria-valuemin="0" aria-valuemax="100" ${okand ? "" : `aria-valuenow="${bredd}"`}><i${stil}></i></div>
    <span class="spar-info">${escapeHtml(info)}</span>${vantar}</div>`;
}

const MJ_AVKLIPPT = ["length", "max_tokens"];

function mjMetaText(meta) {
  if (!meta) return "";
  const delar = [];
  if (meta.tokens) delar.push(`${meta.tokens} token`);
  if (meta.tok_per_s) delar.push(`${mjDecimal(meta.tok_per_s)} tok/s`);
  if (meta.total_s) delar.push(`${mjDecimal(meta.total_s)} s`);
  if (meta.done_reason) delar.push(`stopp: ${meta.done_reason}`);
  return delar.join(" · ");
}

// Svar i json-format visas indraget. Går det inte att tolka visas texten som den är.
function mjFormatera(text, format) {
  if (!text || format !== "json") return text || "";
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch (_) {
    return text;
  }
}

function mjPreview(j, p) {
  // Kortet visar det som säger mest: en bild om någon del har en, och svaret
  // före indata som text.
  const bildUrl = p.indata.bild || p.svar.bild;
  const bild = bildUrl ? `<img src="${escapeHtml(bildUrl)}" alt="" loading="lazy">` : "";
  const text = p.svar.text || p.indata.text || "";
  return `<button class="prev ${p.jamfor ? "jamforbar" : ""}" data-uuid="${escapeHtml(j.uuid)}" data-id="${p.id}">
    ${bild}${p.jamfor ? `<span class="badge docs">jämför</span> ` : ""}${p.meta && MJ_AVKLIPPT.includes(p.meta.done_reason) ? `<span class="badge down">avklippt</span> ` : ""}<strong>${escapeHtml(p.rubrik)}</strong> · <span class="muted">${escapeHtml(p.spar)}</span>
    <span class="txt">${escapeHtml(text)}</span></button>`;
}

// Jobbets prompt och de spår som har en egen. Spår utan egen prompt kör
// jobbets och listas inte separat.
function mjPrompter(j) {
  const lista = [];
  if (j.prompt) lista.push({ rubrik: j.spar.some((s) => s.prompt) ? "Jobbet" : "", text: j.prompt });
  for (const s of j.spar) if (s.prompt) lista.push({ rubrik: s.modell, text: s.prompt });
  return lista;
}

function mjPromptHtml(p) {
  return `${p.rubrik ? `<h4>${escapeHtml(p.rubrik)}</h4>` : ""}<pre>${escapeHtml(p.text)}</pre>`;
}

function mjJobbHtml(j) {
  const sluttid = j.overgivet ? `övergivet, tyst i ${mjTid(j.sedan)}`
    : j.klar ? `klart efter ${mjTid(j.tid)}`
    : j.kvar_sekunder !== null ? `allt klart ca ${mjKlocka(j.kvar_sekunder)}` : "sluttid okänd";
  const vem = [j.projekt, j.agare, j.host].filter(Boolean).map(escapeHtml).join(" · ");
  const varningar = [];
  if (j.tyst) varningar.push(`Inget hört på ${mjTid(j.sedan)}. Gränsen för det här jobbet är ${mjTid(j.tyst_grans)}.`);
  if (j.ansprak_konflikt) varningar.push(`Anspråket gick inte att ta: ${j.ansprak_konflikt}`);
  const previews = j.previews.slice(0, 24);
  const prompter = mjPrompter(j);
  return `<div class="jobb">
    <div class="jobb-head"><strong>${escapeHtml(j.beskrivning)}</strong>
      <span class="muted jobb-sub">${escapeHtml(sluttid)}</span></div>
    <div class="muted jobb-sub">${vem}${vem ? " · " : ""}pågått ${mjTid(j.tid)} · senast hört ${mjTid(j.sedan)} sedan</div>
    ${varningar.map((v) => `<p class="varning">${escapeHtml(v)}</p>`).join("")}
    ${j.spar.map(mjSpar).join("")}
    ${prompter.length ? `<details class="prompt" data-nyckel="prompt-${escapeHtml(j.uuid)}">
      <summary>Prompt</summary>${prompter.map(mjPromptHtml).join("")}</details>` : ""}
    ${j.fel.slice(-3).map((f) => `<p class="felrad">${escapeHtml(f.modell ? `${f.modell}: ` : "")}${escapeHtml(f.text)}</p>`).join("")}
    ${previews.length ? `<div class="remsa" data-uuid="${escapeHtml(j.uuid)}">${previews.map((p) => mjPreview(j, p)).join("")}</div>` : ""}
  </div>`;
}

function mjEndpointMeta(ep) {
  if (!ep) return "";
  const delar = [];
  if (ep.description) delar.push(escapeHtml(ep.description));
  if (ep.ansprak) delar.push(`anspråk: ${escapeHtml(ep.ansprak.agare)}, ${ep.ansprak.minuter_kvar} min kvar`);
  if (ep.laddade) {
    delar.push(ep.laddade.length
      ? `laddat: ${ep.laddade.map((m) => `${escapeHtml(m.namn)}${m.gpu_procent !== null ? ` ${m.gpu_procent} % GPU` : ""}`).join(", ")}`
      : "inget laddat");
  }
  return delar.join(" · ");
}

function mjBadge(ep) {
  if (!ep) return `<span class="badge docs">extern</span>`;
  const delar = [];
  if (ep.up !== undefined) delar.push(`<span class="badge ${ep.up ? "up" : "down"}">${ep.up ? "uppe" : "svarar inte"}</span>`);
  if (ep.is_active) delar.push(`<span class="badge docs">aktiv i växlaren</span>`);
  return delar.join("");
}

function mjRita() {
  // Remsornas scrollläge överlever omritningen, annars hoppar de tillbaka
  // till början var 5:e sekund medan man läser.
  // Samma sak för en utfälld prompt.
  const scroll = {};
  MJ_LISTA.querySelectorAll(".remsa").forEach((r) => { scroll[r.dataset.uuid] = r.scrollLeft; });
  const oppna = new Set([...document.querySelectorAll("details[data-nyckel][open]")].map((d) => d.dataset.nyckel));

  const grupper = new Map(mjEndpoints.map((e) => [e.name, []]));
  for (const j of mjJobb.pagaende) {
    const nyckel = j.endpointnamn || j.endpoint || "okänd endpoint";
    if (!grupper.has(nyckel)) grupper.set(nyckel, []);
    grupper.get(nyckel).push(j);
  }
  MJ_LISTA.innerHTML = [...grupper.entries()].map(([namn, jobb]) => {
    const ep = mjEndpoints.find((e) => e.name === namn);
    const meta = mjEndpointMeta(ep);
    return `<article class="endpoint ${ep && ep.is_active ? "ollama-active" : ""}">
      <div class="ep-head"><h3>${escapeHtml(namn)}</h3>${mjBadge(ep)}</div>
      ${meta ? `<p class="ep-meta muted">${meta}</p>` : ""}
      ${jobb.map(mjJobbHtml).join("") || `<p class="ep-meta muted">Inga pågående jobb.</p>`}
    </article>`;
  }).join("") || `<p class="muted">Inga endpoints och inga pågående jobb.</p>`;

  MJ_LISTA.querySelectorAll(".remsa").forEach((r) => { r.scrollLeft = scroll[r.dataset.uuid] || 0; });

  document.getElementById("mj-avslutade-rubrik").textContent = `Avslutade jobb (${mjJobb.avslutade.length})`;
  MJ_AVSLUTADE.innerHTML = mjJobb.avslutade.map(mjJobbHtml).join("")
    || `<p class="muted">Inga avslutade jobb ännu.</p>`;
  document.querySelectorAll("details[data-nyckel]").forEach((d) => { d.open = oppna.has(d.dataset.nyckel); });
}

function mjVisaFel(text) {
  MJ_FEL.hidden = !text;
  MJ_FEL.textContent = text || "";
}

async function mjHamtaJobb() {
  try {
    mjJobb = await apiFetch("/api/modelljobb");
    mjVisaFel("");
    mjRita();
  } catch (err) {
    mjVisaFel(`Kunde inte hämta jobben: ${err.message}`);
  }
}

async function mjHamtaEndpoints(sondera) {
  try {
    mjEndpoints = await apiFetch(`/api/ollama/endpoints${sondera ? "?probe=1" : ""}`);
    mjRita();
  } catch (err) {
    mjVisaFel(`Kunde inte hämta endpoints: ${err.message}`);
  }
}

function mjDelHtml(del_, format, alt) {
  const delar = [];
  if (del_.bild) delar.push(`<img src="${escapeHtml(del_.bild)}" alt="${escapeHtml(alt)}">`);
  if (del_.text) delar.push(`<pre>${escapeHtml(mjFormatera(del_.text, format))}</pre>`);
  return delar.join("");
}

function mjOppnaJamforelse(uuid, id) {
  const j = [...mjJobb.pagaende, ...mjJobb.avslutade].find((x) => x.uuid === uuid);
  if (!j) return;
  const vald = j.previews.find((p) => p.id === id);
  if (!vald) return;
  // Samma rubrik från varje spår, sida vid sida. Jämförelsepreviews går före,
  // de är de som garanterat finns kvar för alla modeller.
  const samma = j.previews.filter((p) => p.rubrik === vald.rubrik);
  const spar = [...new Set([...j.spar.map((s) => s.modell), ...samma.map((p) => p.spar)])];
  // Indata är densamma för alla spår, så den visas en gång överst.
  const indata = samma.find((p) => p.indata.bild || p.indata.text);
  const jobbPrompt = j.prompt
    ? `<details><summary>Prompt</summary><pre>${escapeHtml(j.prompt)}</pre></details>` : "";
  document.getElementById("mj-dlg-titel").textContent = `${vald.rubrik} · ${j.beskrivning}`;
  document.getElementById("mj-dlg-bild").innerHTML =
    (indata ? `<h4 class="mj-del">Indata</h4>${mjDelHtml(indata.indata, "text", `Indata ${vald.rubrik}`)}` : "")
    + jobbPrompt;
  document.getElementById("mj-dlg-jamfor").innerHTML = spar.map((s) => {
    const svar = samma.filter((p) => p.spar === s).sort((a, b) => b.jamfor - a.jamfor)[0];
    const egen = j.spar.find((x) => x.modell === s && x.prompt);
    const prompt = egen
      ? `<details><summary>Spårets prompt</summary><pre>${escapeHtml(egen.prompt)}</pre></details>` : "";
    const innehall = svar ? (mjDelHtml(svar.svar, svar.format, `Svar från ${s}`) || `<p class="ep-meta muted">(tomt svar)</p>`)
      : `<p class="ep-meta muted">Inget sparat svar för den här rubriken.</p>`;
    const meta = svar ? mjMetaText(svar.meta) : "";
    const metaHtml = meta ? `<p class="ep-meta ${MJ_AVKLIPPT.includes(svar.meta.done_reason) ? "mj-fastnat" : "muted"}">${escapeHtml(meta)}</p>` : "";
    return `<div><h4>${escapeHtml(s)}</h4>${metaHtml}${innehall}${prompt}</div>`;
  }).join("");
  MJ_DLG.showModal();
}

document.addEventListener("click", (e) => {
  const knapp = e.target.closest(".prev");
  if (knapp) mjOppnaJamforelse(knapp.dataset.uuid, Number(knapp.dataset.id));
});
document.getElementById("mj-stang").addEventListener("click", () => MJ_DLG.close());
MJ_DLG.addEventListener("click", (e) => { if (e.target === MJ_DLG) MJ_DLG.close(); });

mjHamtaEndpoints(false).then(() => mjHamtaEndpoints(true));
mjHamtaJobb();
setInterval(mjHamtaJobb, 5000);
setInterval(() => mjHamtaEndpoints(true), 30000);
