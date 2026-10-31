import base64
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import config, modelljobb, ollama
from app import database as db
from app.main import app

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def _jobb(**over):
    data = {
        "beskrivning": "Bildkontroll",
        "projekt": "kyrkohandboken-new",
        "agare": "kh-session",
        "endpoint": "tervo2",
        "spar": [{"modell": "qwen3.5:9b", "klara": 0, "totalt": 100}],
    }
    data.update(over)
    return data


class ModelljobbRouteTest(unittest.TestCase):
    """Proven går via routerna, inte via modulens funktioner."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = (db.DB_PATH, config.MODELLJOBB_DIR)
        db.DB_PATH = Path(self.tmp.name) / "portal.db"
        config.MODELLJOBB_DIR = Path(self.tmp.name) / "modelljobb"
        db.init_db()
        ollama.ensure_seed()
        modelljobb.init_schema()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        db.DB_PATH, config.MODELLJOBB_DIR = self.original
        self.tmp.cleanup()

    def _put(self, uuid="jobb-0001", **over):
        svar = self.client.put(f"/api/modelljobb/{uuid}", json=_jobb(**over))
        self.assertEqual(svar.status_code, 200, svar.text)
        return svar.json()

    def _preview(self, rubrik, spar="qwen3.5:9b", jamfor=False, bild=None, uuid="jobb-0001"):
        return self.client.post(f"/api/modelljobb/{uuid}/preview", json={
            "spar": spar, "rubrik": rubrik, "jamfor": jamfor,
            "indata": {"bild_base64": base64.b64encode(bild).decode() if bild else None},
            "svar": {"text": f"svar {rubrik}"},
        })

    def test_sluttid_raknas_fran_takten_sedan_fran(self):
        # 10 nya enheter på 100 s ger 10 s per enhet. Räknades återupptagna
        # enheter (fran=40) med blev takten 2 s och sluttiden fel.
        nu = time.time()
        j = self._put(skickad=nu, spar=[{"modell": "a", "klara": 50, "totalt": 100,
                                         "fran": 40, "start": nu - 100}])
        s = j["spar"][0]
        self.assertEqual(s["per_enhet"], 10.0)
        self.assertEqual(s["kvar_sekunder"], 500)
        self.assertEqual(j["kvar_sekunder"], 500)

    def test_spar_som_inte_startat_ger_okand_sluttid(self):
        nu = time.time()
        j = self._put(skickad=nu, spar=[
            {"modell": "a", "klara": 10, "totalt": 100, "start": nu - 100},
            {"modell": "b", "klara": 0, "totalt": 100},
        ])
        self.assertEqual(j["spar"][1]["lage"], "väntar")
        self.assertIsNone(j["kvar_sekunder"])

    def test_klientens_klocka_flyttas_till_portalens(self):
        # Klienten går en timme fel. Utan skiftet blev tiden 3700 s, inte 100.
        fel_klocka = time.time() + 3600
        j = self._put(skickad=fel_klocka, start=fel_klocka - 100,
                      spar=[{"modell": "a", "klara": 10, "totalt": 20, "start": fel_klocka - 100}])
        self.assertAlmostEqual(j["tid"], 100, delta=2)
        self.assertEqual(j["spar"][0]["per_enhet"], 10.0)

    def test_put_ar_idempotent_och_senast_vinner(self):
        self._put(spar=[{"modell": "a", "klara": 5, "totalt": 10}])
        self._put(spar=[{"modell": "a", "klara": 7, "totalt": 10}])
        lista = self.client.get("/api/modelljobb").json()
        self.assertEqual(len(lista["pagaende"]), 1)
        self.assertEqual(lista["pagaende"][0]["spar"][0]["klara"], 7)

    def test_klart_jobb_flyttas_till_avslutade(self):
        self._put()
        self._put(klar=True)
        lista = self.client.get("/api/modelljobb").json()
        self.assertEqual(lista["pagaende"], [])
        self.assertTrue(lista["avslutade"][0]["klar"])

    def test_ansprak_tas_och_slapps_av_jobbet(self):
        self._put()
        ansprak = self.client.get("/api/ollama/endpoints/tervo2/claim").json()["ansprak"]
        self.assertEqual(ansprak["agare"], "kh-session")
        self._put(klar=True)
        self.assertIsNone(self.client.get("/api/ollama/endpoints/tervo2/claim").json()["ansprak"])

    def test_endpoint_som_url_loses_till_namn(self):
        # Storstil-klienten skickar URL:en från /active, inte namnet.
        j = self._put(endpoint="http://192.168.1.2:11434/")
        self.assertEqual(j["endpointnamn"], "tervo2")
        self.assertTrue(j["tog_ansprak"])

    def test_heartbeat_kortar_inte_ett_langre_eget_ansprak(self):
        self.client.post("/api/ollama/endpoints/tervo2/claim",
                         json={"agare": "kh-session", "minuter": 300})
        self._put()
        kvar = self.client.get("/api/ollama/endpoints/tervo2/claim").json()["ansprak"]["minuter_kvar"]
        self.assertGreaterEqual(kvar, 299)

    def test_klart_jobb_slapper_inte_sessionens_egna_ansprak(self):
        # Sessionen hade anspråket före jobbet. Jobbet förlängde det men tog
        # det inte, så det ska leva kvar.
        self.client.post("/api/ollama/endpoints/tervo2/claim",
                         json={"agare": "kh-session", "minuter": 300})
        self._put()
        self._put(klar=True)
        self.assertIsNotNone(self.client.get("/api/ollama/endpoints/tervo2/claim").json()["ansprak"])

    def test_upptagen_endpoint_fäller_inte_jobbet(self):
        self.client.post("/api/ollama/endpoints/tervo2/claim", json={"agare": "annan", "minuter": 60})
        j = self._put()
        self.assertIn("annan", j["ansprak_konflikt"])
        self.assertFalse(j["tog_ansprak"])

    def test_extern_endpoint_tar_inget_ansprak(self):
        j = self._put(endpoint="anthropic")
        self.assertIsNone(j["endpointnamn"])
        self.assertFalse(j["tog_ansprak"])

    def test_preview_kraver_befintligt_jobb(self):
        self.assertEqual(self._preview("ps_1.jpg").status_code, 404)

    def test_preview_bild_serveras_med_upptackt_typ(self):
        self._put()
        pid = self._preview("ps_1.jpg", bild=JPEG).json()["id"]
        svar = self.client.get(f"/api/modelljobb/jobb-0001/preview/{pid}/indata")
        self.assertEqual(svar.status_code, 200)
        self.assertEqual(svar.headers["content-type"], "image/jpeg")
        self.assertEqual(svar.headers["x-content-type-options"], "nosniff")
        self.assertEqual(svar.content, JPEG)

    def test_textjobb_och_bildgenerering_ryms_i_samma_format(self):
        # Ett textjobb har ingen bild alls. En bildgenerering har bilden i
        # svaret. Låste formatet bilden till indata blev svar.bild None.
        self._put()
        text = self.client.post("/api/modelljobb/jobb-0001/preview", json={
            "spar": "a", "rubrik": "stycke 1", "format": "json",
            "indata": {"text": "Sammanfatta stycket."}, "svar": {"text": '{"kort": "ja"}'},
        })
        self.assertEqual(text.status_code, 200)
        gen = self.client.post("/api/modelljobb/jobb-0001/preview", json={
            "spar": "b", "rubrik": "motiv 1", "indata": {"text": "en kyrka i snö"},
            "svar": {"bild_base64": base64.b64encode(JPEG).decode()},
        }).json()
        previews = {p["rubrik"]: p for p in self.client.get("/api/modelljobb/jobb-0001").json()["previews"]}
        self.assertEqual(previews["stycke 1"]["format"], "json")
        self.assertEqual(previews["stycke 1"]["indata"], {"text": "Sammanfatta stycket.", "bild": None})
        self.assertIsNone(previews["motiv 1"]["indata"]["bild"])
        url = previews["motiv 1"]["svar"]["bild"]
        self.assertEqual(url, f"/api/modelljobb/jobb-0001/preview/{gen['id']}/svar")
        self.assertEqual(self.client.get(url).content, JPEG)

    def test_okant_format_och_okand_del_avvisas(self):
        self._put()
        svar = self.client.post("/api/modelljobb/jobb-0001/preview",
                                json={"spar": "a", "rubrik": "x", "format": "html"})
        self.assertEqual(svar.status_code, 422)
        self.assertEqual(self.client.get("/api/modelljobb/jobb-0001/preview/1/annat").status_code, 422)

    def test_prompt_for_jobb_och_spar_foljer_med(self):
        j = self._put(prompt="Läs ackorden.", spar=[
            {"modell": "a", "klara": 0, "totalt": 10},
            {"modell": "b", "klara": 0, "totalt": 10, "prompt": "Läs ackorden. Svara kort."},
        ])
        self.assertEqual(j["prompt"], "Läs ackorden.")
        self.assertIsNone(j["spar"][0].get("prompt"))
        self.assertEqual(j["spar"][1]["prompt"], "Läs ackorden. Svara kort.")

    def test_svg_avvisas(self):
        self._put()
        self.assertEqual(self._preview("x", bild=SVG).status_code, 400)

    def test_jamforelse_overlever_lopande_previews(self):
        # Spåren körs efter varandra. Spår a jämför ps_1 först, sedan kommer
        # 50 löpande. När spår b når ps_1 ska a:s svar finnas kvar.
        self._put()
        self._preview("ps_1.jpg", spar="a", jamfor=True)
        for i in range(50):
            self._preview(f"ps_{i + 100}.jpg", spar="a")
        self._preview("ps_1.jpg", spar="b", jamfor=True)
        previews = self.client.get("/api/modelljobb/jobb-0001").json()["previews"]
        ps1 = {p["spar"] for p in previews if p["rubrik"] == "ps_1.jpg"}
        self.assertEqual(ps1, {"a", "b"})
        lopande_a = [p for p in previews if p["spar"] == "a" and not p["jamfor"]]
        self.assertEqual(len(lopande_a), modelljobb.MAX_LOPANDE)

    def test_trimmade_previews_tar_bort_sina_bilder(self):
        self._put()
        for i in range(modelljobb.MAX_LOPANDE + 3):
            self._preview(f"ps_{i}.jpg", bild=JPEG)
        filer = list((config.MODELLJOBB_DIR / "jobb-0001").iterdir())
        self.assertEqual(len(filer), modelljobb.MAX_LOPANDE)

    def test_ta_bort_rensar_previews_och_filer(self):
        self._put()
        self._preview("ps_1.jpg", bild=JPEG)
        self.assertEqual(self.client.delete("/api/modelljobb/jobb-0001").status_code, 200)
        self.assertFalse((config.MODELLJOBB_DIR / "jobb-0001").exists())
        self.assertEqual(self.client.get("/api/modelljobb/jobb-0001").status_code, 404)

    def test_gamla_jobb_stadas(self):
        self._put()
        with db.get_conn() as conn:
            conn.execute("UPDATE modelljobb SET senast = ?", (time.time() - 8 * 86400,))
        self.assertEqual(self.client.get("/api/modelljobb").json()["avslutade"], [])
        self.assertEqual(self.client.get("/api/modelljobb/jobb-0001").status_code, 404)

    def test_tyst_jobb_flaggas_och_overgivet_flyttas(self):
        nu = time.time()
        self._put(skickad=nu, spar=[{"modell": "a", "klara": 10, "totalt": 100, "start": nu - 100}])
        with db.get_conn() as conn:
            conn.execute("UPDATE modelljobb SET senast = ?", (nu - 200,))
        self.assertTrue(self.client.get("/api/modelljobb").json()["pagaende"][0]["tyst"])
        with db.get_conn() as conn:
            conn.execute("UPDATE modelljobb SET senast = ?", (nu - 7 * 3600,))
        lista = self.client.get("/api/modelljobb").json()
        self.assertEqual(lista["pagaende"], [])
        self.assertTrue(lista["avslutade"][0]["overgivet"])

    def test_ogiltigt_uuid_avvisas(self):
        svar = self.client.put("/api/modelljobb/kort", json=_jobb())
        self.assertEqual(svar.status_code, 400)

    def test_sidan_renderar(self):
        svar = self.client.get("/modelljobb")
        self.assertEqual(svar.status_code, 200)
        self.assertIn("/static/modelljobb.js", svar.text)


if __name__ == "__main__":
    unittest.main()
