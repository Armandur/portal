"""ntfy-notiser för modelljobb: klart, avbrutet, tyst och övergivet.

Bara jobb som har pågått längre än gränsen ger notiser, så korta prov tiger.
Portalen skickar en notis per övergång och sparar den i jobbraden. Det blir
alltså ingen ny notis vid varje rapport eller kontroll. Klart och avbrutet
upptäcks när klienten rapporterar. Tyst och övergivet kan bara upptäckas
utifrån, så `kontrollera` körs periodiskt från appens lifespan.

Utan NTFY_URL, NTFY_TOPIC och NTFY_TOKEN i miljön skickas inga notiser.
"""

import logging
import os
import threading
import time
import urllib.error
import urllib.request
from email.header import Header

from app import config
from app.database import get_conn

logger = logging.getLogger(__name__)

NTFY_URL = os.environ.get("NTFY_URL", "").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")
KONTROLL_SEKUNDER = 60

# Klienten skriver det här prefixet när with-blocket avbryts av ett undantag.
AVBROTS = "Avbröts:"

_LAGEN = {
    "klar": ("klart", "3", "white_check_mark"),
    "fel": ("avbrutet", "3", "warning,x"),
    "tyst": ("tyst", "3", "warning,hourglass"),
    "igang": ("igång igen", "2", "arrow_forward"),
    "overgivet": ("övergivet", "3", "warning,skull"),
}


def aktiv() -> bool:
    return bool(NTFY_URL and NTFY_TOPIC and NTFY_TOKEN)


def _titel(text: str) -> str:
    """RFC 2047 för svenska tecken. ntfy avkodar det, ren ascii skickas som den är."""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return Header(text, "utf-8").encode()


def _tid(sekunder: int) -> str:
    if sekunder < 90:
        return f"{sekunder} s"
    if sekunder < 5400:
        return f"{round(sekunder / 60)} min"
    return f"{sekunder / 3600:.1f} h".replace(".", ",")


def meddelande(jobb: dict, lage: str) -> tuple[dict, str]:
    """Rubriker och kropp för en notis. Ren funktion, så den går att prova."""
    ord_, prio, taggar = _LAGEN[lage]
    rader = [jobb["beskrivning"]]
    rader.append(" · ".join(filter(None, [
        jobb.get("endpointnamn") or jobb.get("endpoint"), _tid(jobb["tid"]),
        f"tyst i {_tid(jobb['sedan'])}" if lage in ("tyst", "overgivet") else None,
    ])))
    rader.append(", ".join(
        f"{s['modell']} {s['klara']}" + (f"/{s['totalt']}" if s.get("totalt") is not None else "")
        for s in jobb["spar"]
    ))
    if lage == "fel" and jobb["fel"]:
        rader.append(jobb["fel"][-1]["text"][:200])
    rubriker = {
        "Authorization": f"Bearer {NTFY_TOKEN}",
        "Title": _titel(f"Modelljobb / {ord_}"),
        "Priority": prio,
        "Tags": taggar,
        "Click": f"{config.PORTAL_BASE_URL}/modelljobb",
    }
    return rubriker, "\n".join(r for r in rader if r)


def _posta(rubriker: dict, kropp: str) -> None:
    req = urllib.request.Request(f"{NTFY_URL}/{NTFY_TOPIC}", data=kropp.encode("utf-8"),
                                 headers=rubriker, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("ntfy-notisen gick inte fram: %s", exc)


def _i_bakgrunden(fn, *args) -> None:
    """Klientens PUT har 2 s timeout och ska inte vänta på ntfy."""
    threading.Thread(target=fn, args=args, daemon=True).start()


def _skicka(jobb: dict, lage: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE modelljobb SET notis_lage = ? WHERE uuid = ?", (lage, jobb["uuid"]))
    if not aktiv():
        return
    _i_bakgrunden(_posta, *meddelande(jobb, lage))


def _langt_nog(jobb: dict) -> bool:
    return jobb["notis"] and jobb["tid"] >= config.MODELLJOBB_NOTIS_EFTER_MIN * 60


def efter_rapport(jobb: dict, var_klar: bool) -> None:
    """Anropas efter varje PUT med jobbets nya läge."""
    if not _langt_nog(jobb):
        return
    if jobb["klar"] and not var_klar:
        avbrutet = any(f["text"].startswith(AVBROTS) for f in jobb["fel"])
        _skicka(jobb, "fel" if avbrutet else "klar")
    elif not jobb["klar"] and jobb["notis_lage"] in ("tyst", "overgivet"):
        _skicka(jobb, "igang")


def kontrollera() -> int:
    """Skickar notis för jobb som nyss blivit tysta eller övergivna. Svarar antal."""
    from app import modelljobb

    antal = 0
    jobben = modelljobb.lista()
    for jobb in jobben["pagaende"] + jobben["avslutade"]:
        if jobb["klar"] or not _langt_nog(jobb):
            continue
        lage = "overgivet" if jobb["overgivet"] else "tyst" if jobb["tyst"] else None
        if lage and jobb["notis_lage"] != lage:
            _skicka(jobb, lage)
            antal += 1
    return antal


def vakt() -> None:
    """Körs i en egen tråd så länge portalen lever."""
    while True:
        time.sleep(KONTROLL_SEKUNDER)
        try:
            kontrollera()
        except Exception:  # Vakten får inte dö av ett enstaka fel, men felet ska synas.
            logger.exception("Kontrollen av tysta modelljobb misslyckades")


def starta_vakt() -> None:
    if not aktiv():
        logger.info("Modelljobb skickar inga notiser: NTFY_URL, NTFY_TOPIC eller NTFY_TOKEN saknas.")
        return
    threading.Thread(target=vakt, daemon=True, name="modelljobb-vakt").start()

