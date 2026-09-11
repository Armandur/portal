import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import database as db
from app.main import app
from app.routes import pages


class ShareRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        self.original_db_share_dir = db.SHARE_DIR
        self.original_pages_share_dir = pages.SHARE_DIR

        root = Path(self.tmp.name)
        db.DB_PATH = root / "portal.db"
        db.SHARE_DIR = root / "shares"
        pages.SHARE_DIR = db.SHARE_DIR
        db.init_db()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        db.DB_PATH = self.original_db_path
        db.SHARE_DIR = self.original_db_share_dir
        pages.SHARE_DIR = self.original_pages_share_dir
        self.tmp.cleanup()

    def create_share(
        self,
        uid: str,
        filename: str,
        content: bytes,
        content_type: str,
    ):
        db.create_share(
            uid=uid,
            filename=filename,
            content=content,
            content_type=content_type,
            description=None,
            ttl_minutes=0,
        )

    def test_html_download_uses_attachment_while_default_stays_inline(self):
        self.create_share(
            "html123",
            "rapport.html",
            b"<h1>Rapport</h1>",
            "text/html",
        )

        inline = self.client.get("/share/html123/rapport.html")
        download_zero = self.client.get("/share/html123/rapport.html?download=0")
        attachment = self.client.get("/share/html123/rapport.html?download=1")

        self.assertEqual(inline.status_code, 200)
        self.assertEqual(download_zero.status_code, 200)
        self.assertEqual(attachment.status_code, 200)
        self.assertEqual(download_zero.content, inline.content)
        self.assertNotIn("content-disposition", inline.headers)
        self.assertNotIn("content-disposition", download_zero.headers)
        self.assertEqual(
            attachment.headers["content-disposition"],
            'attachment; filename="rapport.html"',
        )

    def test_markdown_download_returns_source_while_default_renders_reader(self):
        source = b"# Rubrik\n\nText i dokumentet.\n"
        self.create_share("md123", "anteckning.md", source, "text/markdown")

        inline = self.client.get("/share/md123/anteckning.md")
        download_zero = self.client.get("/share/md123/anteckning.md?download=0")
        attachment = self.client.get("/share/md123/anteckning.md?download=1")

        self.assertEqual(inline.status_code, 200)
        self.assertIn('<h1 id="rubrik">Rubrik</h1>', inline.text)
        self.assertEqual(download_zero.content, inline.content)
        self.assertNotIn("content-disposition", inline.headers)
        self.assertEqual(attachment.content, source)
        self.assertEqual(
            attachment.headers["content-disposition"],
            'attachment; filename="anteckning.md"',
        )

    def test_share_root_preserves_download_through_redirect(self):
        self.create_share("root123", "rapport.html", b"rapport", "text/html")

        default = self.client.get("/share/root123", follow_redirects=False)
        download_zero = self.client.get(
            "/share/root123?download=0", follow_redirects=False
        )
        attachment = self.client.get(
            "/share/root123?download=1", follow_redirects=False
        )

        self.assertEqual(default.headers["location"], "/share/root123/rapport.html")
        self.assertEqual(download_zero.headers["location"], default.headers["location"])
        self.assertEqual(
            attachment.headers["location"],
            "/share/root123/rapport.html?download=1",
        )

    def test_download_encodes_swedish_filename(self):
        filename = "räksmörgås.html"
        self.create_share("unicode123", filename, b"innehall", "text/html")

        response = self.client.get(f"/share/unicode123/{filename}?download=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-disposition"],
            "attachment; filename*=utf-8''r%C3%A4ksm%C3%B6rg%C3%A5s.html",
        )


if __name__ == "__main__":
    unittest.main()
