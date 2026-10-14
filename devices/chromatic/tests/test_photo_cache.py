#!/usr/bin/env python3
"""Flash/NVS are mocks; this test never opens a serial port or physical flash."""
import os
import pathlib
import subprocess
import tempfile
import unittest

CHROMATIC = pathlib.Path(__file__).resolve().parents[1]


class PhotoCacheTest(unittest.TestCase):
    def test_mock_flash_ownership_powerloss_and_identity(self):
        with tempfile.TemporaryDirectory(prefix="homehq-photo-cache-") as temporary:
            binary = pathlib.Path(temporary) / "cache_check"
            command = ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-O1", "-g",
                       "-I", str(CHROMATIC / "tests/cache_stubs"),
                       str(CHROMATIC / "tests/test_photo_cache.c"), "-o", str(binary)]
            if os.environ.get("HQ_CACHE_SANITIZE") == "1":
                command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            compiled = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("identity, cold boot, bounds, ownership, faults, torn writes and cancellation passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
