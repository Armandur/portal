import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import supervisor
from app.ports import service_status
from app.routes import api


class ServiceStatusTest(unittest.TestCase):
    def _systemd(self, port=62051):
        return {
            "name": "managed",
            "project": "managed",
            "kind": "systemd",
            "unit": "managed.service",
            "port": port,
            "pid": None,
        }

    def test_systemd_status_matrix(self):
        listening = {62051: {"port": 62051, "pids": [123], "processes": ["python"]}}
        service = self._systemd()
        self.assertEqual(service_status(service, listening, "active"), "up")
        self.assertEqual(service_status(service, {}, "inactive"), "down")
        self.assertEqual(service_status(service, listening, "inactive"), "drift")
        self.assertEqual(service_status(service, {}, "active"), "drift")
        self.assertEqual(service_status(service, {}, "activating"), "starting")
        self.assertEqual(service_status(service, {}, "deactivating"), "stopping")
        self.assertEqual(service_status(service, listening, "unknown"), "unknown")

    def test_portless_systemd_follows_supervisor(self):
        service = self._systemd(port=None)
        self.assertEqual(service_status(service, {}, "active"), "up")
        self.assertEqual(service_status(service, {}, "inactive"), "down")
        self.assertEqual(service_status(service, {}, "unknown"), "unknown")

    def test_ephemeral_status_contract_is_unchanged(self):
        docs = {"kind": "ephemeral", "port": None}
        service = {"kind": "ephemeral", "port": 62052, "pid": 10}
        listening = {62052: {"port": 62052, "pids": [10], "processes": []}}
        conflict = {62052: {"port": 62052, "pids": [11], "processes": []}}
        self.assertEqual(service_status(docs, {}), "docs")
        self.assertEqual(service_status(service, {}), "down")
        self.assertEqual(service_status(service, listening), "up")
        self.assertEqual(service_status(service, conflict), "conflict")

    def test_duharfagel_case_is_drift(self):
        service = {
            "name": "duharfagel-dashboard",
            "kind": "systemd",
            "unit": "duharfagel.service",
            "port": 8001,
            "pid": None,
        }
        listening = {8001: {"port": 8001, "pids": [999], "processes": ["uvicorn"]}}
        self.assertEqual(service_status(service, listening, "inactive"), "drift")

    def test_api_shape_exposes_supervisor_and_drift(self):
        service = self._systemd()
        with patch("app.routes.api.portal_managed_systemd_unit", return_value=True):
            shaped = api._with_status(service, {}, {"managed.service": "active"})
        self.assertEqual(shaped["supervisor_status"], "active")
        self.assertEqual(shaped["status"], "drift")
        self.assertTrue(shaped["controllable"])

    def test_api_shape_marks_unmanaged_and_ephemeral_uncontrollable(self):
        with patch("app.routes.api.portal_managed_systemd_unit", return_value=False):
            managed = api._with_status(
                self._systemd(), {}, {"managed.service": "inactive"}
            )
        ephemeral = api._with_status(
            {"name": "temp", "kind": "ephemeral", "port": None}, {}
        )
        self.assertFalse(managed["controllable"])
        self.assertFalse(ephemeral["controllable"])


class SystemdBatchStatusTest(unittest.TestCase):
    def test_multiple_units_use_one_systemctl_call(self):
        completed = SimpleNamespace(
            returncode=3, stdout="active\ninactive\n", stderr=""
        )
        with patch("app.supervisor.subprocess.run", return_value=completed) as run:
            states = supervisor.systemd_unit_states(["a.service", "b.service", "a.service"])
        self.assertEqual(states, {"a.service": "active", "b.service": "inactive"})
        run.assert_called_once_with(
            ["systemctl", "--user", "is-active", "--", "a.service", "b.service"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_systemctl_failure_is_unknown_not_up(self):
        with patch(
            "app.supervisor.subprocess.run",
            side_effect=subprocess.TimeoutExpired("systemctl", 10),
        ):
            states = supervisor.systemd_unit_states(["a.service", "b.service"])
        self.assertEqual(states, {"a.service": "unknown", "b.service": "unknown"})


if __name__ == "__main__":
    unittest.main()
