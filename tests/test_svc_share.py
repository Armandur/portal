import argparse
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch


def _load_cli():
    path = Path(__file__).parents[1] / "cli" / "svc"
    loader = SourceFileLoader("svc_cli_share_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


svc = _load_cli()

SHARE_URL = "http://ubuntu-ai:8890/share/abc123/rapport.html"
DOWNLOAD_URL = f"{SHARE_URL}?download=1"


class SvcShareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "rapport.html"
        self.file.write_text("<h1>Rapport</h1>", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, **flags):
        falt = {"file": str(self.file), "desc": None, "ttl": None, "download": False}
        falt.update(flags)
        args = argparse.Namespace(**falt)
        svar = {"url": SHARE_URL, "expires_at": "2026-09-12T10:00:00+02:00"}
        ut, fel = io.StringIO(), io.StringIO()
        with patch.object(svc, "_request", return_value=svar) as anrop:
            with contextlib.redirect_stdout(ut), contextlib.redirect_stderr(fel):
                svc.cmd_share(args)
        return ut.getvalue(), fel.getvalue(), anrop

    def test_utan_flaggan_ger_laslanken_pa_stdout(self):
        ut, fel, _ = self._run()

        # Exakt en rad på stdout, annars går utdatan inte att pipa vidare.
        self.assertEqual(ut, f"{SHARE_URL}\n")
        self.assertIn(f"Nedladdning: {DOWNLOAD_URL}", fel)
        self.assertIn("Går ut:", fel)

    def test_med_flaggan_ger_nedladdningslanken_pa_stdout(self):
        ut, fel, _ = self._run(download=True)

        self.assertEqual(ut, f"{DOWNLOAD_URL}\n")
        self.assertNotIn("Nedladdning:", fel)
        self.assertIn("Går ut:", fel)

    def test_flaggan_andrar_inte_uppladdningen(self):
        _, _, anrop = self._run(download=True)

        metod, vag = anrop.call_args.args[0], anrop.call_args.args[1]
        body = anrop.call_args.args[2]
        self.assertEqual((metod, vag), ("POST", "/api/shares"))
        self.assertEqual(body["filename"], "rapport.html")
        self.assertNotIn("download", body)

    def test_hjalptexten_namner_flaggan(self):
        # Parsern byggs inuti main(), så hjälptexten läses via subprocess.
        cli = Path(__file__).parents[1] / "cli" / "svc"
        klar = subprocess.run(
            [sys.executable, str(cli), "share", "--help"],
            capture_output=True, text=True, check=True,
        )

        self.assertIn("--download", klar.stdout)
        self.assertIn("laddar ned filen", klar.stdout)


if __name__ == "__main__":
    unittest.main()
