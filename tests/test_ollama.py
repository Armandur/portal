import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database as db
from app import ollama
from app.main import app


class OllamaRouteTest(unittest.TestCase):
    """Proven går via routen, inte via lagringsfunktionerna direkt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "portal.db"
        db.init_db()
        ollama.ensure_seed()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def test_active_ger_seedad_endpoint(self):
        svar = self.client.get("/api/ollama/active")
        self.assertEqual(svar.status_code, 200)
        self.assertEqual(svar.json()["name"], "tervo2")
        self.assertEqual(svar.json()["url"], "http://192.168.1.2:11434")

    def test_vaxling_andrar_vad_active_svarar(self):
        self.client.post(
            "/api/ollama/endpoints",
            json={"name": "windows", "url": "http://192.168.1.50:11434/"},
        )
        # Avslutande snedstreck ska vara bortklippt när klienten läser URL:en
        self.assertEqual(
            self.client.get("/api/ollama/active").json()["url"],
            "http://192.168.1.2:11434",
        )

        bytt = self.client.post("/api/ollama/active", json={"name": "windows"})
        self.assertEqual(bytt.status_code, 200)

        efter = self.client.get("/api/ollama/active").json()
        self.assertEqual(efter["name"], "windows")
        self.assertEqual(efter["url"], "http://192.168.1.50:11434")

    def test_active_rors_inte_av_natverket(self):
        """Läsvägen får aldrig sondera - varje LLM-anrop passerar den."""
        with patch.object(ollama, "probe", side_effect=AssertionError("sonderade")):
            svar = self.client.get("/api/ollama/active")
        self.assertEqual(svar.status_code, 200)

    def test_probe_flaggan_markerar_nere(self):
        with patch.object(ollama, "probe", return_value={"up": False, "models": []}):
            rader = self.client.get("/api/ollama/endpoints?probe=1").json()
        self.assertEqual(len(rader), 1)
        self.assertFalse(rader[0]["up"])

    def test_probe_ger_laddad_modell_och_version(self):
        laddad = {
            "up": True, "models": ["qwen3.6:35b-a3b"], "version": "0.16.2",
            "laddade": [{"namn": "qwen3.6:35b-a3b", "storlek_gb": 22.5,
                         "gpu_procent": 39, "context": 32768, "minuter_kvar": 47}],
        }
        with patch.object(ollama, "probe", return_value=laddad):
            rad = self.client.get("/api/ollama/endpoints?probe=1").json()[0]
        self.assertEqual(rad["version"], "0.16.2")
        self.assertEqual(rad["laddade"][0]["gpu_procent"], 39)
        self.assertEqual(rad["laddade"][0]["minuter_kvar"], 47)

    def test_dod_endpoint_kostar_ett_anrop_inte_tre(self):
        """tags avgör liveness - svarar den inte hoppas ps och version över."""
        besokta = []

        def falsk_hamta(url, timeout):
            besokta.append(url)
            return None

        with patch.object(ollama, "_hamta", side_effect=falsk_hamta):
            resultat = ollama.probe("http://nere:11434")
        self.assertFalse(resultat["up"])
        self.assertEqual(besokta, ["http://nere:11434/api/tags"])

    def test_minuter_kvar_tal_skrap(self):
        self.assertIsNone(ollama._minuter_kvar(None))
        self.assertIsNone(ollama._minuter_kvar("inte en tid"))
        # Tid utan tidszon går inte att jämföra säkert mot UTC
        self.assertIsNone(ollama._minuter_kvar("2026-09-21T20:00:00"))

    def test_ansprak_tas_lases_och_slapps_via_routen(self):
        tomt = self.client.get("/api/ollama/endpoints/tervo2/claim").json()
        self.assertIsNone(tomt["ansprak"])

        tagit = self.client.post(
            "/api/ollama/endpoints/tervo2/claim",
            json={"agare": "seriedatabas", "minuter": 90, "notis": "8000 sidor"},
        )
        self.assertEqual(tagit.status_code, 200)
        a = tagit.json()["ansprak"]
        self.assertEqual(a["agare"], "seriedatabas")
        self.assertEqual(a["notis"], "8000 sidor")
        self.assertAlmostEqual(a["minuter_kvar"], 90, delta=1)

        self.assertEqual(
            self.client.get("/api/ollama/endpoints/tervo2/claim").json()["ansprak"]["agare"],
            "seriedatabas",
        )

        slappt = self.client.delete("/api/ollama/endpoints/tervo2/claim")
        self.assertTrue(slappt.json()["slapptes"])
        self.assertIsNone(
            self.client.get("/api/ollama/endpoints/tervo2/claim").json()["ansprak"]
        )

    def test_annans_levande_ansprak_ger_409(self):
        self.client.post(
            "/api/ollama/endpoints/tervo2/claim", json={"agare": "seriedatabas"}
        )
        krock = self.client.post(
            "/api/ollama/endpoints/tervo2/claim", json={"agare": "annan-session"}
        )
        self.assertEqual(krock.status_code, 409)
        self.assertIn("seriedatabas", krock.json()["detail"])

    def test_eget_ansprak_gar_att_forlanga(self):
        self.client.post(
            "/api/ollama/endpoints/tervo2/claim",
            json={"agare": "seriedatabas", "minuter": 10},
        )
        om = self.client.post(
            "/api/ollama/endpoints/tervo2/claim",
            json={"agare": "seriedatabas", "minuter": 120},
        )
        self.assertEqual(om.status_code, 200)
        self.assertAlmostEqual(om.json()["ansprak"]["minuter_kvar"], 120, delta=1)

    def test_utgatt_ansprak_raknas_som_ledigt(self):
        forflutet = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE ollama_endpoints SET claimed_by = 'gammal', claimed_until = ?"
                " WHERE name = 'tervo2'",
                (forflutet,),
            )
        self.assertIsNone(
            self.client.get("/api/ollama/endpoints/tervo2/claim").json()["ansprak"]
        )
        # ... och någon annan får ta det utan konflikt
        ny = self.client.post(
            "/api/ollama/endpoints/tervo2/claim", json={"agare": "ny-session"}
        )
        self.assertEqual(ny.status_code, 200)

    def test_ansprak_ror_inte_natverket(self):
        with patch.object(ollama, "probe", side_effect=AssertionError("sonderade")):
            self.client.post(
                "/api/ollama/endpoints/tervo2/claim", json={"agare": "x"}
            )
            svar = self.client.get("/api/ollama/endpoints/tervo2/claim")
        self.assertEqual(svar.status_code, 200)

    def test_ansprak_pa_okand_endpoint_ger_404(self):
        self.assertEqual(
            self.client.get("/api/ollama/endpoints/finns-inte/claim").status_code, 404
        )
        self.assertEqual(
            self.client.post(
                "/api/ollama/endpoints/finns-inte/claim", json={"agare": "x"}
            ).status_code,
            404,
        )

    def test_stopgap_flaggan_folger_med(self):
        self.client.post(
            "/api/ollama/endpoints",
            json={"name": "tillfallig", "url": "http://x:11434", "stopgap": True},
        )
        rader = {r["name"]: r for r in self.client.get("/api/ollama/endpoints").json()}
        self.assertTrue(rader["tillfallig"]["stopgap"])
        self.assertFalse(rader["tervo2"]["stopgap"])

    def test_active_har_samma_form_som_forut(self):
        """Kontraktet projekten kodar mot får inte växa av misstag."""
        self.client.post(
            "/api/ollama/endpoints/tervo2/claim", json={"agare": "seriedatabas"}
        )
        self.assertEqual(
            set(self.client.get("/api/ollama/active").json()), {"name", "url"}
        )

    def test_aktiv_endpoint_gar_inte_att_ta_bort(self):
        svar = self.client.delete("/api/ollama/endpoints/tervo2")
        self.assertEqual(svar.status_code, 409)
        self.assertEqual(self.client.get("/api/ollama/active").json()["name"], "tervo2")

    def test_okant_namn_ger_404(self):
        svar = self.client.post("/api/ollama/active", json={"name": "finns-inte"})
        self.assertEqual(svar.status_code, 404)

    def test_adress_utan_schema_avvisas(self):
        svar = self.client.post(
            "/api/ollama/endpoints", json={"name": "trasig", "url": "192.168.1.50:11434"}
        )
        self.assertEqual(svar.status_code, 400)
        self.assertIn("http://", svar.json()["detail"])


if __name__ == "__main__":
    unittest.main()
