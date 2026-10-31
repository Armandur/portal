import tempfile
import time
import unittest
from email.header import decode_header
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, modelljobb, modelljobb_notis as notis, ollama
from app import database as db
from app.main import app


def _titel(rubriker):
    text, kodning = decode_header(rubriker["Title"])[0]
    return text.decode(kodning) if isinstance(text, bytes) else text


class NotisTest(unittest.TestCase):
    """Rapporterna går via routen. Bara själva ntfy-anropet fångas upp."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = (db.DB_PATH, config.MODELLJOBB_DIR)
        db.DB_PATH = Path(self.tmp.name) / "portal.db"
        config.MODELLJOBB_DIR = Path(self.tmp.name) / "modelljobb"
        db.init_db()
        ollama.ensure_seed()
        modelljobb.init_schema()
        self.client = TestClient(app)
        self.skickat = []
        for patcher in (
            patch.multiple(notis, NTFY_URL="https://ntfy.test", NTFY_TOPIC="svc_modelljobb",
                           NTFY_TOKEN="tk_test"),
            patch.object(notis, "_posta", lambda r, k: self.skickat.append((r, k))),
            patch.object(notis, "_i_bakgrunden", lambda fn, *a: fn(*a)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.client.close()
        db.DB_PATH, config.MODELLJOBB_DIR = self.original
        self.tmp.cleanup()

    def _put(self, pagatt=300, **over):
        nu = time.time()
        data = {"beskrivning": "Bildkontroll", "endpoint": "anthropic", "skickad": nu,
                "start": nu - pagatt,
                "spar": [{"modell": "gemma4:12b", "klara": 40, "totalt": 40, "start": nu - pagatt}]}
        data.update(over)
        svar = self.client.put("/api/modelljobb/jobb-0001", json=data)
        self.assertEqual(svar.status_code, 200, svar.text)
        return svar.json()

    def _tysta(self, sekunder):
        with db.get_conn() as conn:
            conn.execute("UPDATE modelljobb SET senast = ?", (time.time() - sekunder,))

    def test_langt_jobb_ger_en_notis_nar_det_blir_klart(self):
        # Utan notis_lage som minne gav varje PUT efter klart en ny notis.
        self._put()
        self.assertEqual(self.skickat, [])
        self._put(klar=True)
        self._put(klar=True)
        self.assertEqual(len(self.skickat), 1)
        rubriker, kropp = self.skickat[0]
        self.assertEqual(_titel(rubriker), "Modelljobb / klart")
        self.assertEqual(rubriker["Click"], f"{config.PORTAL_BASE_URL}/modelljobb")
        self.assertEqual(rubriker["Authorization"], "Bearer tk_test")
        self.assertIn("Bildkontroll", kropp)
        self.assertIn("gemma4:12b 40/40", kropp)

    def test_kort_prov_ger_ingen_notis(self):
        self._put(pagatt=30)
        self._put(pagatt=30, klar=True)
        self.assertEqual(self.skickat, [])

    def test_avbrutet_jobb_ger_felnotis(self):
        self._put()
        self._put(klar=True, fel=[{"modell": "gemma4:12b", "text": "Avbröts: RuntimeError: timeout"}])
        rubriker, kropp = self.skickat[0]
        self.assertEqual(_titel(rubriker), "Modelljobb / avbrutet")
        self.assertIn("Avbröts: RuntimeError: timeout", kropp)

    def test_tyst_jobb_notifieras_en_gang_och_igang_igen(self):
        self._put()
        self._tysta(200)
        self.assertEqual(notis.kontrollera(), 1)
        self.assertEqual(notis.kontrollera(), 0)
        self.assertEqual(_titel(self.skickat[0][0]), "Modelljobb / tyst")
        self._put()
        self.assertEqual(_titel(self.skickat[-1][0]), "Modelljobb / igång igen")
        self.assertEqual(len(self.skickat), 2)

    def test_overgivet_jobb_far_egen_notis_efter_tyst(self):
        self._put()
        self._tysta(200)
        notis.kontrollera()
        self._tysta(7 * 3600)
        notis.kontrollera()
        self.assertEqual([_titel(r) for r, _ in self.skickat],
                         ["Modelljobb / tyst", "Modelljobb / övergivet"])

    def test_jobb_kan_stanga_av_notiser(self):
        self._put(notis=False)
        self._put(notis=False, klar=True)
        self.assertEqual(self.skickat, [])

    def test_utan_token_skickas_inget(self):
        with patch.object(notis, "NTFY_TOKEN", ""):
            self._put()
            self._put(klar=True)
        self.assertEqual(self.skickat, [])

    def test_gransen_gar_att_stalla_in(self):
        with patch.object(config, "MODELLJOBB_NOTIS_EFTER_MIN", 10):
            self._put()
            self._put(klar=True)
        self.assertEqual(self.skickat, [])


if __name__ == "__main__":
    unittest.main()
