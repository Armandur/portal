import argparse
import importlib.util
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import call, patch


def _load_cli():
    path = Path(__file__).parents[1] / "cli" / "svc"
    loader = SourceFileLoader("svc_cli_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


svc = _load_cli()


class SvcInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name) / "project"
        self.units = Path(self.tmp.name) / "units"
        self.cwd.mkdir()
        self.env = patch.dict(os.environ, {"SVC_SYSTEMD_USER_DIR": str(self.units)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _args(self, **overrides):
        values = {
            "project": "testprojekt",
            "cmd": "/usr/bin/python3 -m http.server 62031",
            "cwd": str(self.cwd),
            "port": 62031,
            "autostart": False,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_install_creates_unit_and_registers_without_command(self):
        with (
            patch.object(svc, "_run_systemctl") as systemctl,
            patch.object(
                svc, "_request", side_effect=[None, {"name": "testprojekt"}]
            ) as request,
        ):
            svc.cmd_install(self._args())

        path = self.units / "testprojekt.service"
        text = path.read_text()
        self.assertIn(f"WorkingDirectory={self.cwd}", text)
        self.assertIn("ExecStart=/usr/bin/python3 -m http.server 62031", text)
        self.assertIn("Restart=on-failure", text)
        self.assertIn("X-Portal-Managed=true", text)
        systemctl.assert_called_once_with("daemon-reload")
        create_body = request.call_args_list[1].args[2]
        self.assertEqual(create_body["kind"], "systemd")
        self.assertEqual(create_body["unit"], "testprojekt.service")
        self.assertNotIn("cmd", create_body)
        self.assertNotIn("command", create_body)
        self.assertNotIn("cwd", create_body)

    def test_install_without_port_registers_managed_catalog_entry(self):
        with (
            patch.object(svc, "_run_systemctl"),
            patch.object(
                svc, "_request", side_effect=[None, {"name": "testprojekt"}]
            ) as request,
        ):
            svc.cmd_install(self._args(port=None))
        create_body = request.call_args_list[1].args[2]
        self.assertEqual(create_body["kind"], "systemd")
        self.assertNotIn("port", create_body)

    def test_existing_service_is_updated_and_autostart_enabled(self):
        with (
            patch.object(svc, "_run_systemctl") as systemctl,
            patch.object(
                svc,
                "_request",
                side_effect=[{"name": "testprojekt"}, {"name": "testprojekt"}],
            ) as request,
        ):
            svc.cmd_install(self._args(autostart=True))
        self.assertEqual(
            systemctl.call_args_list,
            [call("daemon-reload"), call("enable", "testprojekt.service")],
        )
        self.assertEqual(request.call_args_list[1].args[:2], ("PATCH", "/api/services/testprojekt"))

    def test_existing_unit_is_not_overwritten(self):
        self.units.mkdir()
        path = self.units / "testprojekt.service"
        path.write_text("BEVARA")
        with patch.object(svc, "_run_systemctl") as systemctl:
            with self.assertRaises(SystemExit):
                svc.cmd_install(self._args())
        self.assertEqual(path.read_text(), "BEVARA")
        systemctl.assert_not_called()

    def test_invalid_inputs_are_rejected(self):
        cases = (
            {"project": "../escape"},
            {"cmd": "rad1\nrad2"},
            {"cwd": str(Path(self.tmp.name) / "saknas")},
            {"port": 70000},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(SystemExit):
                svc.cmd_install(self._args(**overrides))
        self.assertFalse(self.units.exists())

    def test_systemctl_failure_removes_new_unit(self):
        with patch.object(svc, "_run_systemctl", side_effect=SystemExit(1)):
            with self.assertRaises(SystemExit):
                svc.cmd_install(self._args())
        self.assertFalse((self.units / "testprojekt.service").exists())


if __name__ == "__main__":
    unittest.main()
