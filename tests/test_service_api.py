import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import database as db
from app.routes import api


class ServiceApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "portal.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def test_portless_systemd_service_is_accepted(self):
        body = api.ServiceIn(
            name="managed",
            project="managed",
            kind="systemd",
            unit="managed.service",
        )
        with (
            patch.object(api, "write_ledger"),
            patch.object(api, "scan_listening_ports", return_value={}),
        ):
            result = api.create_service(body)
        self.assertIsNone(result["port"])
        self.assertEqual(result["kind"], "systemd")
        self.assertEqual(result["unit"], "managed.service")

    def test_portless_ephemeral_still_requires_docs(self):
        body = api.ServiceIn(name="ephemeral", project="ephemeral")
        with self.assertRaises(HTTPException) as raised:
            api.create_service(body)
        self.assertEqual(raised.exception.status_code, 400)


    def test_extra_links_render_on_the_service_port_and_can_be_cleared(self):
        body = api.ServiceIn(
            name="pixel-agents",
            project="pixel-agents",
            port=8028,
            extra_links=[{"label": "Med token", "url_path": "/?token=abc"}],
        )
        with (
            patch.object(api, "write_ledger"),
            patch.object(api, "scan_listening_ports", return_value={}),
        ):
            created = api.create_service(body)
            self.assertEqual(
                created["extra_links"],
                [{"label": "Med token", "url": f"http://{api.SERVICE_HOST}:8028/?token=abc"}],
            )
            cleared = api.update_service("pixel-agents", api.ServicePatch(extra_links=[]))
        self.assertEqual(cleared["extra_links"], [])

    def test_extra_link_path_must_start_with_slash(self):
        with self.assertRaises(ValueError):
            api.ExtraLink(label="x", url_path="http://elsewhere/")


if __name__ == "__main__":
    unittest.main()
