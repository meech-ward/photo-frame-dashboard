#!/usr/bin/env python3
"""Compile the real photo module against isolated deterministic HTTP stubs."""
import pathlib
import os
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PhotoMailboxTest(unittest.TestCase):
    def test_identity_cancellation_and_http_bounds(self):
        with tempfile.TemporaryDirectory(prefix="homehq-photo-test-") as directory:
            binary = pathlib.Path(directory) / "photo-mailbox"
            sanitizer = ["-g", "-fsanitize=address,undefined"] if os.environ.get("HQ_PHOTO_SANITIZE") == "1" else []
            subprocess.run([
                "cc", "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
                *sanitizer,
                "-DPNGLE_NO_GAMMA_CORRECTION", "-I" + str(ROOT / "src"),
                "-I" + str(ROOT / "tests/photo_stubs"),
                str(ROOT / "tests/photo_mailbox.c"), str(ROOT / "src/homehq_photo.c"),
                str(ROOT / "src/homehq_png.c"), str(ROOT / "src/vendor/pngle/pngle.c"),
                str(ROOT / "src/vendor/pngle/miniz.c"), "-o", str(binary),
            ], check=True)
            subprocess.run([str(binary), str(ROOT.parent / "badge/homehq/assets/photo-coast.png")], check=True)


if __name__ == "__main__":
    unittest.main()
