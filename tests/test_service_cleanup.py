import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import database as db
from app import ledger, main, ports
from app.routes import api


class ServiceCleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        self.original_ledger_path = ledger.LEDGER_PATH
        db.DB_PATH = Path(self.tmp.name) / "portal.db"
        ledger.LEDGER_PATH = Path(self.tmp.name) / "ledger.md"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        ledger.LEDGER_PATH = self.original_ledger_path
        self.tmp.cleanup()

    def _service(self, name, port, pid=99_999_999, kind="ephemeral", **extra):
        return db.create_service({
            "name": name,
            "project": "test",
            "port": port,
            "pid": pid,
            "kind": kind,
            **extra,
        })

    def test_cleanup_removes_only_dead_silent_ephemeral(self):
        self._service("dead", 62001)
        self._service("alive", 62002, pid=os.getpid())
        self._service("listening", 62003)
        self._service("docs", None, docs_md="docs")
        self._service("systemd", 62004, kind="systemd")
        self._service("docker", 62005, kind="docker")
        listening = ports._ListeningPorts({
            62003: {"port": 62003, "pids": [], "processes": []},
        })

        with patch("app.ledger.write_ledger") as write_ledger:
            self.assertEqual(
                ports.clean_dead_ephemeral_services(listening),
                ["dead"],
            )
            write_ledger.assert_called_once_with()
            self.assertEqual(ports.clean_dead_ephemeral_services(listening), [])
            write_ledger.assert_called_once_with()

        self.assertIsNone(db.get_service("dead"))
        for name in ("alive", "listening", "docs", "systemd", "docker"):
            self.assertIsNotNone(db.get_service(name), name)

    def test_scanner_failures_abort_cleanup(self):
        self._service("candidate", 62011)
        failures = (
            FileNotFoundError(),
            subprocess.TimeoutExpired("ss", 10),
            SimpleNamespace(returncode=1, stdout="", stderr="fel"),
        )
        for failure in failures:
            if isinstance(failure, BaseException):
                side_effect, return_value = failure, None
            else:
                side_effect, return_value = None, failure
            with self.subTest(failure=type(failure).__name__), patch(
                "app.ports.subprocess.run",
                side_effect=side_effect,
                return_value=return_value,
            ):
                listening = ports.scan_listening_ports()
                self.assertFalse(listening.reliable)
                self.assertEqual(ports.clean_dead_ephemeral_services(listening), [])
                self.assertIsNotNone(db.get_service("candidate"))

        self.assertEqual(
            ports.clean_dead_ephemeral_services(ports._ListeningPorts()),
            ["candidate"],
        )

    def test_successful_empty_scan_is_reliable(self):
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("app.ports.subprocess.run", return_value=completed):
            listening = ports.scan_listening_ports()
        self.assertTrue(listening.reliable)
        self.assertEqual(listening, {})

    def test_concurrent_upgrade_to_managed_prevents_delete(self):
        self._service("race", 62012)
        original = ports.delete_dead_ephemeral_candidate

        def upgrade_then_delete(name, port, pid):
            db.update_service(name, {"kind": "systemd", "unit": "race.service"})
            return original(name, port, pid)

        with patch.object(
            ports, "delete_dead_ephemeral_candidate", side_effect=upgrade_then_delete
        ):
            self.assertEqual(
                ports.clean_dead_ephemeral_services(ports._ListeningPorts()), []
            )
        service = db.get_service("race")
        self.assertEqual(service["kind"], "systemd")
        self.assertEqual(service["unit"], "race.service")

    def test_api_list_cleans_ephemeral_but_keeps_systemd(self):
        self._service("api-dead", 62021)
        self._service("api-systemd", 62022, kind="systemd")
        with patch.object(api, "scan_listening_ports", return_value=ports._ListeningPorts()):
            result = api.list_services()
        names = {service["name"] for service in result}
        self.assertNotIn("api-dead", names)
        self.assertIn("api-systemd", names)

    def test_lifespan_runs_cleanup(self):
        async def run_lifespan():
            with (
                patch.object(main, "init_db"),
                patch.object(main, "import_ledger"),
                patch.object(main, "clean_dead_ephemeral_services") as cleanup,
                patch.object(main, "_register_self"),
                patch.object(main, "write_ledger"),
                patch.object(main, "clean_expired_shares"),
            ):
                async with main.lifespan(main.app):
                    pass
                cleanup.assert_called_once_with()

        asyncio.run(run_lifespan())


if __name__ == "__main__":
    unittest.main()
