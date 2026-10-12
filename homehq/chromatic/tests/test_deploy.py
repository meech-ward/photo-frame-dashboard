import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("homehq_deploy", Path(__file__).resolve().parents[1] / "tools/deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeploymentBoundaryTest(unittest.TestCase):
    def run_tool(self, root, run, *, apply=True, digest=None):
        image = root / "app.bin"
        image.write_bytes(b"test-image-0.13.4-homehq1")
        args = ["deploy.py", "--image", str(image), "--sha256", digest or hashlib.sha256(image.read_bytes()).hexdigest(),
                "--port", "/dev/serial/by-id/usb-ModRetro_Chromatic_-_Player_01_012345678-if02",
                "--python", "/isolated/python", "--backup-root", str(root / "backups")]
        if apply:
            args.append("--apply")
        with patch.object(sys, "argv", args), patch.object(deploy.subprocess, "run", run), contextlib.redirect_stdout(io.StringIO()):
            deploy.main()

    def test_backup_precedes_exact_application_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                self.assertTrue(kwargs["check"])
                if "read_flash" in command:
                    Path(command[-1]).write_bytes(bytes(0x400000))
            self.run_tool(root, run)
            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0][-4:-1], ["read_flash", "0", "ALL"])
            self.assertEqual(commands[1][-5:-1], ["--after", "hard_reset", "write_flash", "0x10000"])
            record = json.loads(next((root / "backups").glob("*/deployment.private.json")).read_text())
            self.assertEqual(record["write"], "esptool-verified")

    def test_failed_backup_never_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_tool(Path(folder), run)
            self.assertEqual(len(commands), 1)
            self.assertIn("read_flash", commands[0])

    def test_unknown_write_is_retained_and_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                if "read_flash" in command:
                    Path(command[-1]).write_bytes(bytes(0x400000))
                else:
                    raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_tool(root, run)
            self.assertEqual(len(commands), 2)
            record = json.loads(next((root / "backups").glob("*/deployment.private.json")).read_text())
            self.assertEqual(record["write"], "unverified")

    def test_digest_failure_and_inspect_only_never_open_serial(self):
        with tempfile.TemporaryDirectory() as folder:
            def forbidden(*args, **kwargs):
                self.fail("Serial tool called")
            self.run_tool(Path(folder), forbidden, apply=False)
            with self.assertRaises(SystemExit):
                self.run_tool(Path(folder), forbidden, digest="invalid")


if __name__ == "__main__":
    unittest.main()
