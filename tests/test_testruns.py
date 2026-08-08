import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request

from app import database as db
from app import testruns
from app.routes import pages


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


if __name__ == "__main__":
    unittest.main()
