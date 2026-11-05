import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, modelljobb, ollama
from app import database as db
from app.main import app

_spec = importlib.util.spec_from_file_location("modelljobb_klient", modelljobb.KLIENT)
klient = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(klient)

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class _Svar(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class KlientTest(unittest.TestCase):
    """Klienten pratar med portalens riktiga router. Bara nätet byts ut."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = (db.DB_PATH, config.MODELLJOBB_DIR)
        db.DB_PATH = Path(self.tmp.name) / "portal.db"
        config.MODELLJOBB_DIR = Path(self.tmp.name) / "modelljobb"
        db.init_db()
        ollama.ensure_seed()
        modelljobb.init_schema()
        self.client = TestClient(app)
        self.anrop = []
        self.portal_nere = False
        patcher = patch.object(klient.urllib.request, "urlopen", self._urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.client.close()
        db.DB_PATH, config.MODELLJOBB_DIR = self.original
        self.tmp.cleanup()

    def _urlopen(self, req, timeout=None):
        if self.portal_nere:
            raise urllib.error.URLError("Connection refused")
        vag = req.full_url.split("ubuntu-ai:8890", 1)[1]
        self.anrop.append((req.get_method(), vag))
        svar = self.client.request(req.get_method(), vag, content=req.data,
                                   headers={"Content-Type": "application/json"})
        if svar.status_code >= 400:
            raise urllib.error.HTTPError(req.full_url, svar.status_code, "fel", {},
                                         io.BytesIO(svar.content))
        return _Svar(svar.content)

    def _jobb(self, **kw):
        kw.setdefault("endpoint", "tervo2")
        kw.setdefault("agare", "kh-session")
        return klient.Jobb("Bildkontroll", {"a": 10, "b": 10}, portal="http://ubuntu-ai:8890", **kw)

    def _las(self, jobb):
        return self.client.get(f"/api/modelljobb/{jobb.uuid}").json()

    def test_strypningen_tappar_inte_slutlaget(self):
        # Tio klar_med på några millisekunder ska ge en enda PUT, men
        # modell_klar skickas alltid. Utan tvingad sändning stod klara på 0.
        jobb = self._jobb(strypning=60)
        jobb.borjar("a")
        for i in range(10):
            jobb.klar_med("a", f"ps_{i}.jpg")
        puts_fore = sum(1 for m, _ in self.anrop if m == "PUT")
        jobb.modell_klar("a")
        self.assertEqual(puts_fore, 2)  # konstruktorn och borjar
        spar = self._las(jobb)["spar"][0]
        self.assertEqual(spar["klara"], 10)
        self.assertEqual(spar["lage"], "klar")

    def test_with_avslutar_och_slapper_anspraket(self):
        with self._jobb() as jobb:
            self.assertIsNotNone(self.client.get("/api/ollama/endpoints/tervo2/claim").json()["ansprak"])
        self.assertTrue(self._las(jobb)["klar"])
        self.assertIsNone(self.client.get("/api/ollama/endpoints/tervo2/claim").json()["ansprak"])

    def test_undantag_syns_som_fel_och_kastas_vidare(self):
        with self.assertRaises(RuntimeError):
            with self._jobb() as jobb:
                jobb.borjar("a")
                jobb.klar_med("a", "ps_1.jpg")
                raise RuntimeError("modellen svarade inte")
        data = self._las(jobb)
        self.assertTrue(data["klar"])
        self.assertIn("modellen svarade inte", data["fel"][-1]["text"])
        self.assertEqual(data["fel"][-1]["modell"], "a")

    def test_nere_portal_faller_inte_jobbet_och_loggar_en_gang(self):
        self.portal_nere = True
        with self.assertLogs("modelljobb", "WARNING") as loggar:
            jobb = self._jobb()
            jobb.borjar("a")
            jobb.fel("a", "x")
            jobb.avsluta()
        self.assertEqual(len(loggar.records), 1)

    def test_jamforurvalet_ar_detsamma_mellan_processer(self):
        # Två processer med olika hash-salt ska välja samma rubriker. Med
        # hash() i stället för crc32 skilde sig listorna, och jämförelsen
        # mellan modeller i olika körningar blev tom.
        kod = (
            "import importlib.util, sys; s = importlib.util.spec_from_file_location('k', sys.argv[1]); "
            "k = importlib.util.module_from_spec(s); s.loader.exec_module(k); "
            "j = k.Jobb.__new__(k.Jobb); j.jamfor_var = 20; "
            "print([r for r in (f'ps_{i:03}.jpg' for i in range(400)) if j.jamfor_urval(r)])"
        )
        urval = [
            subprocess.run([sys.executable, "-c", kod, str(modelljobb.KLIENT)], check=True,
                           capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": salt}).stdout
            for salt in ("1", "2")
        ]
        self.assertEqual(urval[0], urval[1])
        self.assertGreater(urval[0].count("ps_"), 5)

    def test_preview_med_bildfil_och_strypning(self):
        jobb = self._jobb(preview_strypning=60)
        bild = Path(self.tmp.name) / "ps_1.jpg"
        bild.write_bytes(JPEG)
        with patch.dict("sys.modules", {"PIL": None}):  # utan Pillow skickas bytes som de är
            self.assertTrue(jobb.preview("a", "ps_1.jpg", svar='{"x": 1}', indata_bild=bild,
                                         format="json", jamfor=False))
            self.assertFalse(jobb.preview("a", "ps_2.jpg", svar="y", jamfor=False))
            self.assertTrue(jobb.preview("a", "ps_3.jpg", svar="z", jamfor=True))
        previews = self._las(jobb)["previews"]
        self.assertEqual({p["rubrik"] for p in previews}, {"ps_1.jpg", "ps_3.jpg"})
        forsta = next(p for p in previews if p["rubrik"] == "ps_1.jpg")
        self.assertEqual(self.client.get(forsta["indata"]["bild"]).content, JPEG)

    def test_trasig_bild_faller_inte_jobbet(self):
        jobb = self._jobb()
        with self.assertLogs("modelljobb", "WARNING"):
            jobb.preview("a", "x", svar="y", indata_bild=Path(self.tmp.name) / "finns-inte.jpg",
                         jamfor=True)
        self.assertEqual(self._las(jobb)["previews"][0]["indata"]["bild"], None)

    def test_spar_far_egen_prompt(self):
        jobb = self._jobb(prompt="Läs ackorden.", prompter={"b": "Läs ackorden kort."})
        data = self._las(jobb)
        self.assertEqual(data["prompt"], "Läs ackorden.")
        self.assertEqual([s.get("prompt") for s in data["spar"]], [None, "Läs ackorden kort."])

    def test_fastnat_anrop_syns_fast_skriptet_star_still(self):
        # anrop_borjar stryps, och sedan står skriptet i anropet. Utan timern
        # kom ingen mer rapport, och portalen visste inte om anropet.
        jobb = self._jobb(strypning=0.3)
        jobb.borjar("a")
        jobb.anrop_borjar("a", "ps_7.jpg")
        self.assertIsNone(self._las(jobb)["spar"][0]["vantar_sekunder"])
        time.sleep(0.6)  # skriptet väntar på modellen
        s = self._las(jobb)["spar"][0]
        self.assertEqual(s["anrop_rubrik"], "ps_7.jpg")
        self.assertIsNotNone(s["vantar_sekunder"])
        jobb.avsluta()

    def test_ollamas_siffror_summeras_och_avklippt_skickas_direkt(self):
        jobb = self._jobb(strypning=60)
        jobb.borjar("a")
        svar = {"eval_count": 300, "eval_duration": 10_000_000_000, "total_duration": 12_000_000_000,
                "done_reason": "stop"}
        jobb.klar_med("a", "ps_1.jpg", svar_meta=svar)
        jobb.klar_med("a", "ps_2.jpg", svar_meta={**svar, "done_reason": "length"})
        s = self._las(jobb)["spar"][0]
        self.assertEqual(s["klara"], 2)  # avklippt tvingade fram rapporten trots strypningen
        self.assertEqual(s["tokens"], 600)
        self.assertEqual(s["tok_per_s"], 30.0)
        self.assertEqual(s["avklippta"], 1)
        self.assertIsNone(s["vantar_sekunder"])
        jobb.preview("a", "ps_2.jpg", svar="...", svar_meta={**svar, "done_reason": "length"}, jamfor=True)
        meta = self._las(jobb)["previews"][0]["meta"]
        self.assertEqual(meta, {"tokens": 300, "tok_per_s": 30.0, "total_s": 12.0, "done_reason": "length"})

    def test_anthropics_svar_forstas(self):
        meta = klient._meta({"usage": {"output_tokens": 512}, "stop_reason": "max_tokens"})
        self.assertEqual(meta, {"tokens": 512, "done_reason": "max_tokens"})
        self.assertIn(meta["done_reason"], klient.AVKLIPPT)

    def test_portalen_serverar_klienten(self):
        svar = self.client.get("/api/modelljobb/klient.py")
        self.assertEqual(svar.status_code, 200)
        self.assertIn(f'VERSION = "{klient.VERSION}"', svar.text)


if __name__ == "__main__":
    unittest.main()
