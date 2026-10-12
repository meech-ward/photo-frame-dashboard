#!/usr/bin/env python3
"""Exercise the actual C decoder with fragmented, valid and rejected PNGs."""
import ctypes
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "src"
WIDTH, HEIGHT = 128, 72
BACKGROUND = (15, 23, 42)


def chunk(name, data):
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))


def make_png(kind=2, width=320, height=240, depth=8, interlace=0):
    header = struct.pack(">IIBBBBB", width, height, depth, kind, 0, 0, interlace)
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            if kind == 3:
                row.append((x + y) % 2)
            else:
                row.extend((x % 256, y % 256, (x + y) % 256))
                if kind == 6:
                    row.append((x + y) % 256)
        rows.append(row)
    palette = chunk(b"PLTE", bytes([250, 80, 10, 5, 220, 160])) if kind == 3 else b""
    transparency = chunk(b"tRNS", bytes([255, 96])) if kind == 3 else b""
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + palette + transparency +
            chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def packed(red, green, blue):
    return (red >> 3) << 11 | (green >> 2) << 5 | blue >> 3


def blend(source, alpha):
    return tuple((source[i] * alpha + BACKGROUND[i] * (255 - alpha) + 127) // 255 for i in range(3))


class DecoderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="homehq-png-test-")
        library = pathlib.Path(cls.directory.name) / ("decoder.dylib" if sys.platform == "darwin" else "decoder.so")
        subprocess.run([
            "cc", "-std=c99", "-O1", "-Wall", "-Wextra", "-DPNGLE_NO_GAMMA_CORRECTION",
            "-shared", "-fPIC", str(SOURCE / "homehq_png.c"),
            str(SOURCE / "vendor/pngle/pngle.c"), str(SOURCE / "vendor/pngle/miniz.c"),
            "-o", str(library),
        ], check=True)
        cls.decoder = ctypes.CDLL(str(library))
        cls.decoder.HQ_PngNew.argtypes = [ctypes.POINTER(ctypes.c_uint16)]
        cls.decoder.HQ_PngNew.restype = ctypes.c_void_p
        cls.decoder.HQ_PngFeed.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        cls.decoder.HQ_PngFeed.restype = ctypes.c_bool
        cls.decoder.HQ_PngComplete.argtypes = [ctypes.c_void_p]
        cls.decoder.HQ_PngComplete.restype = ctypes.c_bool
        cls.decoder.HQ_PngDestroy.argtypes = [ctypes.c_void_p]

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def decode(self, data, fragment=1024):
        # Sentinels around the caller-owned output catch a write past the card.
        storage = (ctypes.c_uint16 * (WIDTH * HEIGHT + 2))()
        storage[0], storage[-1] = 0xCAFE, 0xBEEF
        pixels = ctypes.cast(ctypes.byref(storage, 2), ctypes.POINTER(ctypes.c_uint16))
        stream = self.decoder.HQ_PngNew(pixels)
        self.assertTrue(stream)
        accepted = True
        try:
            for pos in range(0, len(data), fragment):
                part = data[pos:pos + fragment]
                if not self.decoder.HQ_PngFeed(stream, part, len(part)):
                    accepted = False
                    break
            complete = self.decoder.HQ_PngComplete(stream)
            self.assertEqual((storage[0], storage[-1]), (0xCAFE, 0xBEEF))
            return accepted, complete, list(storage)[1:-1]
        finally:
            self.decoder.HQ_PngDestroy(stream)

    def assert_samples(self, kind, pixels):
        for dy in (0, 19, 40, 71):
            for dx in (0, 20, 55, 95):
                x, y = (2 * dx + 1) * 320 // 192, (2 * dy + 1) * 240 // 144
                if kind == 3:
                    rgb, alpha = ((250, 80, 10), 255) if (x + y) % 2 == 0 else ((5, 220, 160), 96)
                else:
                    rgb = (x % 256, y % 256, (x + y) % 256)
                    alpha = (x + y) % 256 if kind == 6 else 255
                self.assertEqual(pixels[dy * WIDTH + dx + 16], packed(*blend(rgb, alpha)))
        for y in range(HEIGHT):
            self.assertEqual(pixels[y * WIDTH], packed(*BACKGROUND))
            self.assertEqual(pixels[y * WIDTH + 127], packed(*BACKGROUND))

    def test_rgb_palette_and_rgba_fragments_preserve_geometry_and_alpha(self):
        for kind, fragment in ((2, 1), (3, 7), (6, 1024)):
            with self.subTest(kind=kind, fragment=fragment):
                accepted, complete, pixels = self.decode(make_png(kind), fragment)
                self.assertTrue(accepted)
                self.assertTrue(complete)
                self.assert_samples(kind, pixels)

    def test_bad_signature_dimensions_depth_type_and_interlace(self):
        valid = make_png()
        cases = [b"x" + valid[1:], make_png(width=321), make_png(height=239),
                 make_png(depth=16), make_png(kind=0), make_png(interlace=1)]
        for data in cases:
            with self.subTest(ihdr=data[:33]):
                accepted, complete, _ = self.decode(data, 1)
                self.assertFalse(accepted)
                self.assertFalse(complete)

    def test_truncated_crc_corrupt_and_incomplete_raster_never_complete(self):
        valid = make_png()
        corrupt = bytearray(valid)
        corrupt[-1] ^= 1
        # A valid CRC and IEND cannot substitute for a whole decoded raster.
        partial_rows = b"\0" + bytes(320 * 3)
        incomplete = valid[:33] + chunk(b"IDAT", zlib.compress(partial_rows)) + chunk(b"IEND", b"")
        for data in (valid[:20], valid[:-1], valid[:-12], bytes(corrupt), incomplete):
            with self.subTest(length=len(data)):
                _, complete, _ = self.decode(data, 17)
                self.assertFalse(complete)

    def test_oversize_download_is_rejected(self):
        accepted, complete, _ = self.decode(make_png() + bytes(327681), 1024)
        self.assertFalse(accepted)
        self.assertFalse(complete)

    def test_real_bundled_samples_decode(self):
        assets = SOURCE.parents[1] / "badge/homehq/assets"
        for name in ("coast", "lake", "mountain"):
            with self.subTest(name=name):
                _, complete, _ = self.decode((assets / f"photo-{name}.png").read_bytes(), 137)
                self.assertTrue(complete)


if __name__ == "__main__":
    unittest.main()
