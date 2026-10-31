"""Klient för portalens modelljobb: förlopp, sluttid och previews på /modelljobb.

Hämta filen in i projektet och importera den. Den använder bara stdlib (Pillow
om den finns, för att skala ner bilder):

    curl -o modelljobb.py http://ubuntu-ai:8890/api/modelljobb/klient.py

    from modelljobb import Jobb

    with Jobb("Bildkontroll av verserna", {"qwen3.5:9b": 1179, "gemma4:12b": 1179},
              endpoint=url, prompt=PROMPT) as jobb:
        for modell in ("qwen3.5:9b", "gemma4:12b"):
            jobb.borjar(modell)
            for fil in filer:
                svar = fraga(modell, fil)
                jobb.klar_med(modell, fil.name)
                jobb.preview(modell, fil.name, svar=svar, indata_bild=fil, format="json")
            jobb.modell_klar(modell)

Metoderna har samma namn som `Status` i kyrkohandbokens storstil_status.py,
men konstruktorn tar beskrivningen först och skriver ingen lokal fil.
Klienten fäller aldrig jobbet: svarar inte portalen loggar den en gång och kör
vidare. Portalen tar och släpper ollama-anspråket åt jobbet.
"""

import base64
import io
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path

VERSION = "1"
PORTAL = os.environ.get("PORTAL_URL", "http://ubuntu-ai:8890").rstrip("/")
TIMEOUT = 2.0
BILD_MAX_BYTES = 200 * 1024
BILD_MAX_PX = 480

logger = logging.getLogger("modelljobb")


class Jobb:
    """Ett jobb med ett eller flera spår, ett per modell.

    `spar` är {modell: totalt} eller en lista med modeller när totalen är
    okänd (ad hoc-körningar). `strypning` är minsta antal sekunder mellan två
    rapporter om löpande förlopp. Tillståndsbyten skickas alltid direkt.
    `jamfor_var` styr urvalet för jämförelsevyn: ungefär var n:te rubrik.
    `prompter` ger spår en egen prompt, {modell: prompt}, när den skiljer
    sig från jobbets `prompt`.
    """

    def __init__(self, beskrivning: str, spar, *, endpoint: str | None = None,
                 projekt: str | None = None, agare: str | None = None,
                 prompt: str | None = None, prompter: dict[str, str] | None = None,
                 strypning: float = 5.0,
                 preview_strypning: float = 10.0, jamfor_var: int = 20,
                 portal: str | None = None):
        if isinstance(spar, dict):
            spar_lista = [{"modell": m, "klara": 0, "totalt": n} for m, n in spar.items()]
        else:
            spar_lista = [{"modell": m, "klara": 0, "totalt": None} for m in spar]
        for s in spar_lista:
            if prompter and s["modell"] in prompter:
                s["prompt"] = prompter[s["modell"]]
        self.uuid = str(uuid.uuid4())
        self.portal = (portal or PORTAL).rstrip("/")
        self.strypning = strypning
        self.preview_strypning = preview_strypning
        self.jamfor_var = max(1, jamfor_var)
        self.data = {
            "beskrivning": beskrivning,
            "projekt": projekt or Path.cwd().name,
            "agare": agare or os.environ.get("MODELLJOBB_AGARE") or Path.cwd().name,
            "endpoint": endpoint,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "version": VERSION,
            "prompt": prompt,
            "start": time.time(),
            "klar": False,
            "spar": spar_lista,
            "fel": [],
            "aktuell": None,
        }
        self._senast_skickat = 0.0
        self._senast_preview: dict[str, float] = {}
        self._portal_nere = False
        self._skicka(tvinga=True)

    # -- Samma gränssnitt som storstil_status.Status -------------------------

    def borjar(self, modell: str, redan_klara: int = 0) -> None:
        s = self._spar(modell)
        s["start"], s["klara"], s["fran"] = time.time(), redan_klara, redan_klara
        self._skicka(tvinga=True)

    def klar_med(self, modell: str, rubrik: str | None = None) -> None:
        s = self._spar(modell)
        s["klara"] += 1
        if s.get("start") is None:
            s["start"] = time.time()
        self.data["aktuell"] = {"modell": modell, "rubrik": rubrik}
        self._skicka()

    def fel(self, modell: str, text: str) -> None:
        self.data["fel"] = (self.data["fel"] + [{"tid": time.time(), "modell": modell,
                                                  "text": str(text)[:300]}])[-20:]
        self._skicka(tvinga=True)

    def modell_klar(self, modell: str) -> None:
        self._spar(modell)["slut"] = time.time()
        self._skicka(tvinga=True)

    def avsluta(self) -> None:
        self.data["klar"], self.data["aktuell"] = True, None
        self._skicka(tvinga=True)

    # -- Previews ------------------------------------------------------------

    def jamfor_urval(self, rubrik: str) -> bool:
        """Samma svar i alla processer, så varje modell jämförs på samma rubriker.

        crc32 i stället för hash(), som Python saltar per process.
        """
        return zlib.crc32(rubrik.encode("utf-8")) % self.jamfor_var == 0

    def preview(self, modell: str, rubrik: str, *, svar: str | None = None,
                indata: str | None = None, svar_bild=None, indata_bild=None,
                format: str = "text", jamfor: bool | None = None) -> bool:
        """Skickar ett svar att visa. Bilder är bytes eller en sökväg.

        Löpande previews stryps per spår. Jämförelsepreviews skickas alltid.
        Svarar True om previewn skickades.
        """
        if jamfor is None:
            jamfor = self.jamfor_urval(rubrik)
        nu = time.time()
        if not jamfor and nu - self._senast_preview.get(modell, 0) < self.preview_strypning:
            return False
        self._senast_preview[modell] = nu
        kropp = {"spar": modell, "rubrik": rubrik, "format": format, "jamfor": jamfor,
                 "indata": {"text": indata, "bild_base64": _bild(indata_bild)},
                 "svar": {"text": svar, "bild_base64": _bild(svar_bild)}}
        return self._http("POST", f"/api/modelljobb/{self.uuid}/preview", kropp) is not None

    # -- Context manager -----------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, typ, varde, tb):
        # Ett undantag avslutar också jobbet, så anspråket släpps. Felet
        # syns på sidan och kastas vidare som vanligt.
        if varde is not None:
            self.fel(self.data["aktuell"]["modell"] if self.data["aktuell"] else "",
                     f"Avbröts: {typ.__name__}: {varde}")
        self.avsluta()
        return False

    # -- Internt -------------------------------------------------------------

    def _spar(self, modell: str) -> dict:
        for s in self.data["spar"]:
            if s["modell"] == modell:
                return s
        s = {"modell": modell, "klara": 0, "totalt": None}
        self.data["spar"].append(s)
        return s

    def _skicka(self, tvinga: bool = False) -> None:
        nu = time.time()
        if not tvinga and nu - self._senast_skickat < self.strypning:
            return
        self._senast_skickat = nu
        self._http("PUT", f"/api/modelljobb/{self.uuid}", {**self.data, "skickad": nu})

    def _http(self, metod: str, vag: str, kropp: dict) -> dict | None:
        req = urllib.request.Request(
            f"{self.portal}{vag}", data=json.dumps(kropp).encode("utf-8"), method=metod,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                svar = json.load(resp)
        except urllib.error.HTTPError as exc:
            # Portalen svarar men avvisar: ett fel i anropet, inte i nätet.
            logger.warning("Portalen avvisade %s %s (%s): %s", metod, vag, exc.code,
                           exc.read().decode("utf-8", "replace")[:300])
            return None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if not self._portal_nere:
                logger.warning("Portalen svarar inte (%s). Jobbet fortsätter utan rapporter.", exc)
            self._portal_nere = True
            return None
        if self._portal_nere:
            logger.warning("Portalen svarar igen.")
            self._portal_nere = False
        return svar


def _bild(bild) -> str | None:
    """Base64 av bilden, nedskalad om Pillow finns. None om den inte går att skicka.

    En bild som inte går att läsa ger en loggrad, aldrig ett undantag. En
    preview får inte fälla jobbet.
    """
    if bild is None:
        return None
    try:
        data = Path(bild).read_bytes() if isinstance(bild, (str, Path)) else bytes(bild)
    except OSError as exc:
        logger.warning("Kunde inte läsa bilden till previewn: %s", exc)
        return None
    try:
        from PIL import Image
    except ImportError:
        if len(data) > BILD_MAX_BYTES:
            logger.warning("Bilden är %d kB och Pillow saknas. Previewn skickas utan bild.",
                           len(data) // 1024)
            return None
        return base64.b64encode(data).decode("ascii")
    try:
        im = Image.open(io.BytesIO(data))
        im.thumbnail((BILD_MAX_PX * 2, BILD_MAX_PX))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=75)
    except Exception as exc:  # Pillow kastar många olika typer för trasiga bilder.
        logger.warning("Kunde inte skala ner bilden till previewn: %s", exc)
        return None
    return base64.b64encode(buf.getvalue()).decode("ascii")
