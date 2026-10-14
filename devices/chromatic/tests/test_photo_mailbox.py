#!/usr/bin/env python3
"""Compile the real photo module against isolated deterministic HTTP stubs."""
import pathlib
import struct
import zlib
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
            for swapped in (0, 1):
                with self.subTest(lvgl_byte_swap=swapped):
                    subprocess.run([
                        "cc", "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
                        *sanitizer,
                        "-Dmalloc=HQ_TestPhotoMalloc", "-Dcalloc=HQ_TestPhotoCalloc", "-Dfree=HQ_TestPhotoFree",
                        "-DLV_COLOR_16_SWAP=" + str(swapped),
                        "-DPNGLE_NO_GAMMA_CORRECTION", "-I" + str(ROOT / "src"),
                        "-I" + str(ROOT / "tests/photo_stubs"),
                        str(ROOT / "tests/photo_mailbox.c"), str(ROOT / "tests/photo_allocator.c"),
                        str(ROOT / "src/homehq_photo.c"),
                        str(ROOT / "src/homehq_png.c"), str(ROOT / "src/vendor/pngle/pngle.c"),
                        str(ROOT / "src/vendor/pngle/miniz.c"), "-o", str(binary),
                    ], check=True)
                    fixtures = [ROOT.parent / "badge/assets/photo-coast.png"]
                    def chunk(kind, value):
                        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))
                    header = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 320, 240, 8, 2, 0, 0, 0))
                    body = chunk(b"IDAT", zlib.compress((b"\0" + b"\x20\x60\xa0" * 320) * 240)) + chunk(b"IEND", b"")
                    for size in (1500, 327680):
                        padding = b"fixture\0" + b"x" * (size - len(header) - len(body) - 12 - 8)
                        fixture = pathlib.Path(directory) / (str(size) + ".png")
                        fixture.write_bytes(header + chunk(b"tEXt", padding) + body)
                        self.assertEqual(fixture.stat().st_size, size)
                        fixtures.append(fixture)
                    for fixture in fixtures:
                        subprocess.run([str(binary), str(fixture)], check=True)


if __name__ == "__main__":
    unittest.main()
