#!/usr/bin/env python3
"""Offline guard/credential tests; never contacts a Supabase project."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hosted
import check_family


class HostedSafety(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="homehq-hosted-guards-")
        self.root = Path(self.directory.name)
        self.metadata = self.root / "metadata.private.json"
        self.ref = "abcdefghijklmnopqrst"
        self.data = {"project_ref": self.ref}
        hosted.private_write(self.metadata, self.data)

    def tearDown(self):
        self.directory.cleanup()

    def test_wrong_or_missing_target_denied(self):
        for ref in ("zzzzzzzzzzzzzzzzzzzz", "", None, "../other-project"):
            with self.subTest(ref=ref), self.assertRaises(hosted.HostedFailure):
                hosted.verified(self.metadata, ref)

    def test_caller_project_does_not_require_a_specific_organization_or_plan(self):
        for extra in ({}, {"organization_id": "my-organization", "plan": "pro",
                           "project_name": "My family", "verified_new_project": False}):
            hosted.private_write(self.metadata, dict(self.data, **extra))
            self.assertEqual(hosted.verified(self.metadata, self.ref)["project_ref"], self.ref)

    def test_family_probe_refuses_mismatched_project_before_reading_accounts(self):
        with self.assertRaises(hosted.HostedFailure):
            check_family.run(self.root, self.metadata, "zzzzzzzzzzzzzzzzzzzz",
                             self.root / "missing-owner.private.json")

    def test_family_cli_accepts_and_forwards_the_callers_project(self):
        arguments = ["check_family.py", "--metadata", str(self.metadata),
                     "--project-ref", self.ref]
        with patch.object(check_family.sys, "argv", arguments), patch.object(check_family, "run") as run:
            self.assertEqual(check_family.main(), 0)
        self.assertEqual(run.call_args.args[2], self.ref)

    def test_private_permissions_and_symlink_are_denied(self):
        self.metadata.chmod(0o644)
        with self.assertRaises(hosted.HostedFailure):
            hosted.private_read(self.metadata)
        self.metadata.chmod(0o600)
        link = self.root / "link.private.json"; link.symlink_to(self.metadata)
        with self.assertRaises(hosted.HostedFailure):
            hosted.private_read(link)
        with self.assertRaises(hosted.HostedFailure):
            hosted.private_write(link, {})

    def test_url_is_derived_and_cannot_be_redirected_by_metadata(self):
        data = dict(self.data); data["url"] = "https://another-project.supabase.co"
        hosted.private_write(self.metadata, data)
        self.assertEqual(hosted.verified(self.metadata, self.ref)["url"], "https://" + self.ref + ".supabase.co")

    def test_privileged_keys_are_rejected(self):
        claims = base64.urlsafe_b64encode(json.dumps({"role": "service_role"}).encode()).decode().rstrip("=")
        for key in ("sb_secret_private", "header." + claims + ".signature"):
            with self.assertRaises(hosted.HostedFailure):
                hosted.public_key(key)

    def test_management_keeps_default_login_and_password_off_command_line(self):
        calls = []
        data = dict(self.data); data["database_password"] = "test-private-password"

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, hosted.VERSION + "\n" if command[-1] == "--version" else "done", "")

        with patch.dict(os.environ, {"SUPABASE_HOME": "/isolated-local-runtime"}), patch.object(hosted.subprocess, "run", fake_run):
            hosted.cli(self.root, ["db", "push", "--project-ref", self.ref, "--dry-run", "--skip-vault"], data)
        command, kwargs = calls[-1]
        self.assertNotIn("test-private-password", command)
        self.assertIn("--project-ref", command)
        self.assertEqual(command[command.index("--project-ref") + 1], self.ref)
        self.assertNotIn("SUPABASE_HOME", kwargs["env"])
        self.assertEqual(kwargs["env"]["SUPABASE_DB_PASSWORD"], "test-private-password")
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)

    def test_management_error_does_not_forward_credentials(self):
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, hosted.VERSION, "") if command[-1] == "--version" else subprocess.CompletedProcess(command, 1, "SECRET-A", "SECRET-B")
        with patch.object(hosted.subprocess, "run", fake_run):
            with self.assertRaises(hosted.HostedFailure) as caught:
                hosted.cli(self.root, ["config", "diff", "--project-ref", self.ref], self.data)
        self.assertNotIn("SECRET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
