#!/usr/bin/env python3
"""Only isolated mock NOR/NVS are accessed; never a device or physical flash."""
import os
import pathlib
import subprocess
import tempfile
import unittest

CHROMATIC = pathlib.Path(__file__).resolve().parents[1]


class PhotoStageTest(unittest.TestCase):
    def test_mock_flash_transaction_and_cancellation(self):
        with tempfile.TemporaryDirectory(prefix="homehq-photo-stage-") as temporary:
            binary = pathlib.Path(temporary) / "stage_check"
            command = ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-O1", "-g",
                       "-I", str(CHROMATIC / "tests/stage_stubs"),
                       str(CHROMATIC / "tests/test_photo_stage.c"), "-o", str(binary)]
            if os.environ.get("HQ_STAGE_SANITIZE") == "1":
                command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            compiled = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("bounds, lazy yields, commit/CRC, faults, restart and cancellation passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
