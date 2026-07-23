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


if __name__ == "__main__":
    unittest.main()
