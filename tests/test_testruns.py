import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request

from app import database as db
from app import testruns
from app.routes import api, pages


class LinkifyTest(unittest.TestCase):
    def test_backticks_blir_kod(self):
        ut = testruns.linkify("Kör `sudo systemctl restart portal` och vänta")
        self.assertIn("<code>sudo systemctl restart portal</code>", ut)

    def test_adress_i_backticks_blir_kod_inte_lank(self):
        """Ordningen mot linkifieringen: kodspann vinner över adresser."""
        ut = testruns.linkify("Kör `curl http://ubuntu-ai:8890/api/health`")
        self.assertIn("<code>curl http://ubuntu-ai:8890/api/health</code>", ut)
        self.assertNotIn("<a href", ut)

    def test_html_i_kod_escapas(self):
        ut = testruns.linkify("Skriv `<b>hej</b>` i fältet")
        self.assertIn("<code>&lt;b&gt;hej&lt;/b&gt;</code>", ut)
        self.assertNotIn("<b>", ut)

    def test_fetstil_blir_strong(self):
        ut = testruns.linkify("Klicka på **Exportera CSV** och vänta")
        self.assertIn("Klicka på <strong>Exportera CSV</strong> och vänta", ut)

    def test_fetstil_i_kod_ror_inte_stjarnorna(self):
        ut = testruns.linkify("Kör `echo **hej**` i skalet")
        self.assertIn("<code>echo **hej**</code>", ut)
        self.assertNotIn("<strong>", ut)

    def test_lank_inuti_fetstil_blir_klickbar(self):
        ut = testruns.linkify("**Öppna [anmälan](http://ubuntu-ai:8100/a)**")
        self.assertIn('<a href="http://ubuntu-ai:8100/a"', ut)
        self.assertTrue(ut.startswith("<strong>Öppna <a"), ut)
        self.assertIn("</a></strong>", ut)

    def test_ensamma_stjarnor_blir_tecken(self):
        ut = testruns.linkify("Skriv 2 ** 3 i fältet")
        self.assertNotIn("<strong>", ut)
        self.assertIn("**", ut)

    def test_ensam_backtick_blir_tecken(self):
        ut = testruns.linkify("En ensam ` ska inte starta kod")
        self.assertNotIn("<code>", ut)
        self.assertIn("`", ut)

    def test_block_blir_pre(self):
        ut = testruns.linkify("Kör:\n```sh\ncd /srv\n./start.sh\n```")
        self.assertIn("<pre><code>cd /srv\n./start.sh</code></pre>", ut)
        # språktaggen äts, den ska inte hamna i blocket
        self.assertNotIn("sh\ncd", ut)

    def test_block_escapas_och_lankifieras_inte(self):
        ut = testruns.linkify("```\ncurl http://x <b>\n```")
        self.assertIn("<pre><code>curl http://x &lt;b&gt;</code></pre>", ut)
        self.assertNotIn("<a href", ut)

    def test_oavslutat_block_ater_inte_resten(self):
        """Utan avslutande rad blir backtickarna tecken - inte ett block som
        sväljer resten av punkten."""
        ut = testruns.linkify("```\ncd /srv\nog så vidare")
        self.assertNotIn("<pre>", ut)
        self.assertIn("og så vidare", ut)

    def test_text_runt_blocket_ar_kvar(self):
        ut = testruns.linkify("Före `x`:\n```\nkod\n```\nEfter http://ubuntu-ai:8890/t")
        self.assertIn("<code>x</code>", ut)
        self.assertIn("<pre><code>kod</code></pre>", ut)
        self.assertIn('<a href="http://ubuntu-ai:8890/t"', ut)

    def test_markdownlank_ar_kvar(self):
        ut = testruns.linkify("Öppna [anmälan](http://ubuntu-ai:8100/anmal) nu")
        self.assertIn('<a href="http://ubuntu-ai:8100/anmal"', ut)
        self.assertIn(">anmälan</a>", ut)

    def test_ren_adress_ar_kvar_med_punkt_utanfor(self):
        ut = testruns.linkify("Gå till http://ubuntu-ai:8890/test.")
        self.assertIn('<a href="http://ubuntu-ai:8890/test"', ut)
        self.assertTrue(ut.endswith("</a>."))

    def test_brodtext_escapas(self):
        ut = testruns.linkify("Fält med <script> & co")
        self.assertNotIn("<script>", ut)
        self.assertIn("&lt;script&gt;", ut)


class ParseItemsTest(unittest.TestCase):
    def test_rader_slas_ihop_som_forut(self):
        items = testruns.parse_items("## Rubrik\n1. Första raden\n   och andra raden\n")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["body"], "Första raden och andra raden")
        self.assertEqual(items[0]["heading"], "Rubrik")

    def test_block_behaller_radbrytningar(self):
        items = testruns.parse_items(
            "1. Kör detta:\n"
            "   ```sh\n"
            "   cd /srv\n"
            "   ./start.sh\n"
            "   ```\n"
            "   och kolla loggen.\n"
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["body"],
            "Kör detta:\n```sh\ncd /srv\n./start.sh\n```\noch kolla loggen.",
        )

    def test_struktur_inuti_block_ar_kod(self):
        """En rad som börjar med '1. ' eller '## ' inuti ett block är kod,
        inte en ny punkt - annars klipps blocket mitt itu."""
        items = testruns.parse_items(
            "1. Klistra in:\n"
            "   ```\n"
            "   1. inte en punkt\n"
            "   ## inte en rubrik\n"
            "   ```\n"
            "2. Nästa punkt\n"
        )
        self.assertEqual(len(items), 2)
        self.assertIn("1. inte en punkt", items[0]["body"])
        self.assertIn("## inte en rubrik", items[0]["body"])
        self.assertEqual(items[1]["body"], "Nästa punkt")

    def test_djupare_indrag_i_block_star_kvar(self):
        items = testruns.parse_items(
            "1. Kör:\n   ```\n   if x:\n       y()\n   ```\n"
        )
        self.assertIn("if x:\n    y()", items[0]["body"])

    def test_block_gar_hela_vagen_till_pre(self):
        """Parsern och renderaren måste hänga ihop - var för sig bevisar de
        inte att ett block i inskickad markdown blir ett block på sidan."""
        items = testruns.parse_items(
            "1. Kör:\n   ```\n   cd /srv\n   ```\n   och kolla loggen.\n"
        )
        ut = testruns.linkify(items[0]["body"])
        self.assertIn("<pre><code>cd /srv</code></pre>", ut)
        # texten efter blocket är det som avslöjar om raden efter ``` klistrats
        # ihop med den avslutande raden - då matchar fence-regexen inte alls
        self.assertIn("och kolla loggen.", ut)
        self.assertNotIn("```", ut)


class TestSessionSidaTest(unittest.TestCase):
    """Går genom routen, inte bara filtret - filterregistreringen ligger i
    pages.py och skulle inte fångas av ett rent linkify-prov."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "portal.db"
        db.init_db()
        testruns.init_schema()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def _request(self, path: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": path,
                "headers": [],
                "query_string": b"",
            }
        )

    def test_kod_renderas_som_code_pa_sidan(self):
        testruns.create_session(
            "kodprov",
            "Kodprov",
            [{"heading": "Start", "body": "Kör `svc list` i skalet"}],
        )
        svar = pages.test_session(self._request("/test/kodprov"), "kodprov")
        kropp = svar.body.decode()
        self.assertIn("<code>svc list</code>", kropp)

    def test_block_renderas_som_pre_i_body(self):
        """Kopieringsknappen byggs i JS ur `.body pre` - paret div.body + pre
        är alltså ett kontrakt mot klientkoden, inte bara markup. Byter någon
        ut .body eller p-taggen försvinner knappen tyst."""
        testruns.create_session(
            "blockprov",
            "Blockprov",
            [{"heading": None, "body": "Kör:\n```\ncd /srv\n```"}],
        )
        kropp = pages.test_session(self._request("/test/blockprov"), "blockprov").body.decode()
        self.assertIn('<div class="body">Kör:\n<pre><code>cd /srv</code></pre></div>', kropp)
        mall = (Path(__file__).resolve().parent.parent
                / "app" / "templates" / "test.html").read_text()
        self.assertIn('querySelectorAll(".body pre")', mall)
        # kopieringen ligger i utils.js - utan den taggen är kopieraText
        # odefinierad och knappen kastar vid klick
        self.assertIn('<script src="/static/utils.js">', mall)

    def test_okand_session_ger_404(self):
        with self.assertRaises(HTTPException) as ctx:
            pages.test_session(self._request("/test/finns-ej"), "finns-ej")
        self.assertEqual(ctx.exception.status_code, 404)


class UpdateSessionTest(unittest.TestCase):
    """Går genom API-routen, inte bara testruns - modellens fields_set är
    halva logiken och skulle inte prövas av ett rent update_session-anrop."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "portal.db"
        db.init_db()
        testruns.init_schema()
        api.create_test_session(
            api.TestSessionCreate(
                slug="prov",
                title="Prov",
                items_markdown="## R\n1. Klicka spara\n2. Ladda om sidan\n",
                task_ref="TASK-1",
                project="portal",
            )
        )
        testruns.set_status("prov", 1, "ok", None)
        testruns.set_status("prov", 2, "fel", "kraschar")

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def _patch(self, **falt):
        return api.update_test_session("prov", api.TestSessionUpdate(**falt))

    def test_status_foljer_texten_inte_numret(self):
        svar = self._patch(
            items_markdown="## R\n1. Ny punkt först\n2. Klicka spara\n3. Ladda om sidan\n"
        )
        items = svar["items"]
        self.assertEqual([i["position"] for i in items], [1, 2, 3])
        self.assertEqual(items[0]["status"], "otestad")
        self.assertEqual(items[1]["status"], "ok")
        self.assertEqual(items[2]["status"], "fel")
        self.assertEqual(items[2]["note"], "kraschar")

    def test_borttagen_punkt_forsvinner(self):
        svar = self._patch(items_markdown="1. Klicka spara\n")
        self.assertEqual(len(svar["items"]), 1)
        self.assertEqual(svar["summary"]["total"], 1)

    def test_omdopt_rubrik_nollstaller_inte(self):
        svar = self._patch(items_markdown="## Annan rubrik\n1. Klicka spara\n")
        self.assertEqual(svar["items"][0]["status"], "ok")
        self.assertEqual(svar["items"][0]["heading"], "Annan rubrik")

    def test_dubbletter_far_var_sin_status(self):
        testruns.create_session(
            "dubbel", "Dubbel",
            [{"heading": None, "body": "Ladda om"}, {"heading": None, "body": "Ladda om"}],
        )
        testruns.set_status("dubbel", 1, "ok", None)
        testruns.set_status("dubbel", 2, "fel", None)
        svar = api.update_test_session(
            "dubbel", api.TestSessionUpdate(items_markdown="1. Ladda om\n2. Ladda om\n")
        )
        self.assertEqual([i["status"] for i in svar["items"]], ["ok", "fel"])

    def test_titelandring_ror_inte_tasken(self):
        svar = self._patch(title="Ny rubrik")
        self.assertEqual(svar["title"], "Ny rubrik")
        self.assertEqual(svar["task_ref"], "TASK-1")
        self.assertEqual(svar["project"], "portal")
        self.assertEqual(len(svar["items"]), 2)

    def test_tom_task_tar_bort_tasken(self):
        self.assertIsNone(self._patch(task_ref="")["task_ref"])

    def test_stangd_session_ateroppnas(self):
        testruns.close_session("prov", skriv_till_backlog=False)
        self.assertIsNotNone(testruns.get_session("prov")["closed_at"])
        self.assertIsNone(self._patch(title="Omtagning")["closed_at"])

    def test_markdown_utan_punkter_ger_400(self):
        with self.assertRaises(HTTPException) as ctx:
            self._patch(items_markdown="bara brodtext")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(len(testruns.get_session("prov")["items"]), 2)

    def test_tomt_anrop_ger_400(self):
        with self.assertRaises(HTTPException) as ctx:
            self._patch()
        self.assertEqual(ctx.exception.status_code, 400)

    def test_okand_slug_ger_404(self):
        with self.assertRaises(HTTPException) as ctx:
            api.update_test_session("finns-ej", api.TestSessionUpdate(title="x"))
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
