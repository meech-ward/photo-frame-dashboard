#!/usr/bin/env python3
"""Pure bounded response-metadata checks; no network, credentials or device."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent


class PhotoRangeTest(unittest.TestCase):
    def test_exact_ranges_totals_and_etags(self):
        with tempfile.TemporaryDirectory(prefix="homehq-photo-range-") as directory:
            binary = pathlib.Path(directory) / "range_check"
            command = ["cc", "-std=c99", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                       str(ROOT / "test_photo_range.c"), "-o", str(binary)]
            if os.environ.get("HQ_RANGE_SANITIZE") == "1":
                command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            compiled = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("fixed totals, overflow, malformed fields and strong bounded ETags passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
