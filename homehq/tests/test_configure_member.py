"""Family setup resolves a preference without widening the Auth contract."""
from pathlib import Path
import sys
import unittest
import json
import os
import tempfile
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from configure import validate_member
import configure


class MemberProvisioningTests(unittest.TestCase):
    def test_name_resolves_to_stable_id(self):
        self.assertEqual(validate_member({"people": [{"id": "p1", "name": "Claudia"}]}, "claudia"), "p1")

    def test_duplicate_names_require_id(self):
        data = {"people": [{"id": "p1", "name": "Sam"}, {"id": "p2", "name": "Sam"}]}
        with self.assertRaises(ValueError):
            validate_member(data, "Sam")
        self.assertEqual(validate_member(data, "p2"), "p2")

    def test_missing_or_malformed_home_rejects_member(self):
        for data in (None, {}, {"people": [None, {}]}):
            with self.assertRaises(ValueError):
                validate_member(data, "unknown")


class ConfigureLoginTests(unittest.TestCase):
    def test_configuration_only_needs_no_account_password_or_auth_request(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["configure.py", "--url", "https://example.invalid", "--no-login", "--wifi", "--output-dir", directory]
            with patch.object(sys, "argv", args), patch("configure.project", return_value=("https://example.invalid", "sb_publishable_test")), \
                 patch("configure.input", return_value="private-network", create=True), \
                 patch("configure.getpass.getpass", return_value="private-wifi") as prompt, \
                 patch("configure.urllib.request.urlopen") as network, redirect_stdout(StringIO()):
                configure.main()
            self.assertEqual(prompt.call_count, 1, "only Wi-Fi password is requested")
            network.assert_not_called()
            self.assertEqual(sorted(Path(directory).iterdir()), [Path(directory) / "homehq-config.json"])
            config = json.loads((Path(directory) / "homehq-config.json").read_text())
            self.assertEqual(config["publishable_key"], "sb_publishable_test")
            self.assertEqual(os.stat(Path(directory) / "homehq-config.json").st_mode & 0o777, 0o600)

    def test_host_signin_writes_only_refresh_token_and_user_id(self):
        class Response:
            def __enter__(self):
                return StringIO(json.dumps({"access_token": "ephemeral-jwt", "refresh_token": "renewal",
                                           "expires_at": 100, "user": {"id": "person-auth"}}))
            def __exit__(self, *args):
                pass
        with tempfile.TemporaryDirectory() as directory:
            args = ["configure.py", "--url", "https://example.invalid", "--email", "person@example.test", "--output-dir", directory]
            with patch.object(sys, "argv", args), patch("configure.project", return_value=("https://example.invalid", "sb_publishable_test")), \
                 patch("configure.getpass.getpass", return_value="not-saved-password"), \
                 patch("configure.urllib.request.urlopen", return_value=Response()), redirect_stdout(StringIO()):
                configure.main()
            raw = (Path(directory) / "homehq-session.json").read_text()
            self.assertEqual(json.loads(raw), {"v": 1, "refresh_token": "renewal", "user_id": "person-auth"})
            self.assertNotIn("ephemeral-jwt", raw)
            self.assertNotIn("not-saved-password", raw)
            self.assertEqual(os.stat(Path(directory) / "homehq-session.json").st_mode & 0o777, 0o600)
