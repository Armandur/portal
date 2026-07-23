import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import database as db
from app import supervisor
from app.routes import api


class SupervisorCommandTest(unittest.TestCase):
    def test_control_uses_argument_array_and_option_separator(self):
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch("app.supervisor.subprocess.run", return_value=completed) as run:
            supervisor.control_systemd("start", "example.service")
        run.assert_called_once_with(
            ["systemctl", "--user", "start", "--", "example.service"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_systemctl_error_is_logged_and_raised(self):
        completed = SimpleNamespace(returncode=1, stdout="", stderr="nekad")
        with (
            patch("app.supervisor.subprocess.run", return_value=completed),
            self.assertLogs("app.supervisor", level="ERROR") as logs,
            self.assertRaises(supervisor.SupervisorError),
        ):
            supervisor.control_systemd("stop", "example.service")
        self.assertIn("nekad", " ".join(logs.output))

    def test_local_marker_controls_portal_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ", {"PORTAL_SYSTEMD_USER_DIR": tmp}
        ):
            path = Path(tmp) / "managed.service"
            path.write_text("[Unit]\nDescription=test\n")
            self.assertFalse(supervisor.portal_managed_systemd_unit("managed.service"))
            path.write_text("[Unit]\nX-Portal-Managed=true\n")
            self.assertTrue(supervisor.portal_managed_systemd_unit("managed.service"))
            self.assertFalse(supervisor.portal_managed_systemd_unit("other.service"))

    def test_invalid_action_and_unit_validation(self):
        with self.assertRaises(ValueError):
            supervisor.control_systemd("restart", "example.service")
        for unit in (None, "", "--now", "../x.service", "x\n.service", "x.socket"):
            self.assertFalse(supervisor.valid_systemd_unit(unit), unit)
        self.assertTrue(supervisor.valid_systemd_unit("project@demo.service"))


class SupervisorApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "portal.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def _create(
        self, name="managed", kind="systemd", unit="managed.service", port=62041
    ):
        return db.create_service({
            "name": name,
            "project": name,
            "port": port,
            "kind": kind,
            "unit": unit,
        })

    def test_start_and_stop_use_only_database_unit(self):
        self._create()
        with (
            patch.object(api, "control_systemd") as control,
            patch.object(api, "portal_managed_systemd_unit", return_value=True),
            patch.object(
                api, "systemd_unit_state", side_effect=["active", "inactive"]
            ),
            patch.object(api, "scan_listening_ports", return_value={}),
        ):
            started = api.start_service("managed")
            stopped = api.stop_service("managed")
        self.assertEqual(
            control.call_args_list,
            [unittest.mock.call("start", "managed.service"),
             unittest.mock.call("stop", "managed.service")],
        )
        self.assertEqual(started["action"], "start")
        self.assertEqual(started["status"], "starting")
        self.assertEqual(started["supervisor_status"], "active")
        self.assertEqual(stopped["action"], "stop")

    def test_portless_managed_status_comes_from_supervisor(self):
        self._create(port=None)
        with (
            patch.object(api, "portal_managed_systemd_unit", return_value=True),
            patch.object(api, "control_systemd"),
            patch.object(
                api, "systemd_unit_state", side_effect=["active", "inactive"]
            ),
            patch.object(api, "scan_listening_ports", return_value={}),
        ):
            started = api.start_service("managed")
            stopped = api.stop_service("managed")
        self.assertEqual(started["status"], "up")
        self.assertEqual(started["supervisor_status"], "active")
        self.assertEqual(stopped["status"], "down")
        self.assertEqual(stopped["supervisor_status"], "inactive")

    def test_unknown_and_ephemeral_never_call_systemctl(self):
        self._create(name="ephemeral", kind="ephemeral", unit=None)
        with patch.object(api, "control_systemd") as control:
            for name, expected in (("saknas", 404), ("ephemeral", 400)):
                with self.subTest(name=name), self.assertRaises(HTTPException) as raised:
                    api.start_service(name)
                self.assertEqual(raised.exception.status_code, expected)
        control.assert_not_called()

    def test_missing_or_invalid_unit_is_rejected(self):
        self._create(unit=None)
        with patch.object(api, "control_systemd") as control:
            with self.assertRaises(HTTPException) as raised:
                api.start_service("managed")
        self.assertEqual(raised.exception.status_code, 400)
        control.assert_not_called()

    def test_unmarked_unit_is_rejected_without_systemctl(self):
        self._create()
        with (
            patch.object(api, "portal_managed_systemd_unit", return_value=False),
            patch.object(api, "control_systemd") as control,
        ):
            with self.assertRaises(HTTPException) as raised:
                api.start_service("managed")
        self.assertEqual(raised.exception.status_code, 400)
        control.assert_not_called()

    def test_supervisor_failure_becomes_api_error(self):
        self._create()
        with (
            patch.object(api, "portal_managed_systemd_unit", return_value=True),
            patch.object(
                api, "control_systemd", side_effect=supervisor.SupervisorError("nekad")
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                api.stop_service("managed")
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("Systemd kunde inte stoppa", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
