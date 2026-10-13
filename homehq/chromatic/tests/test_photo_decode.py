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
        allocator = pathlib.Path(cls.directory.name) / "allocator.c"
        allocator.write_text("""#undef calloc
#undef free
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
typedef union { max_align_t alignment; size_t length; } Header;
static size_t limit, fail_at, calls, live, maximum, first, borrowed_frees;
static void *borrowed;
void HQ_TestBorrow(void *pointer) { borrowed=pointer; borrowed_frees=0; }
size_t HQ_TestBorrowedFrees(void) { return borrowed_frees; }
void HQ_TestAllocator(size_t max, size_t fail) { limit=max; fail_at=fail; calls=maximum=first=0; }
size_t HQ_TestLive(void) { return live; }
size_t HQ_TestCalls(void) { return calls; }
size_t HQ_TestMaximum(void) { return maximum; }
size_t HQ_TestFirst(void) { return first; }
void *HQ_TestCalloc(size_t count, size_t size) {
    if(size && count>SIZE_MAX/size) return NULL;
    size_t bytes=count*size;
    ++calls; if(!first) first=bytes;
    if(bytes>maximum) maximum=bytes;
    if((limit && bytes>limit) || calls==fail_at || bytes>SIZE_MAX-sizeof(Header)) return NULL;
    Header *header=calloc(1,sizeof(*header)+bytes);
    if(!header) return NULL;
    header->length=bytes; live+=bytes; return header+1;
}
void HQ_TestFree(void *value) {
    if(!value) return;
    if(value==borrowed) { ++borrowed_frees; return; }
    Header *header=(Header *)value-1; live-=header->length; free(header);
}
""")
        subprocess.run([
            "cc", "-std=c11", "-O1", "-Wall", "-Wextra", "-DPNGLE_NO_GAMMA_CORRECTION",
            "-Dcalloc=HQ_TestCalloc", "-Dfree=HQ_TestFree",
            "-shared", "-fPIC", str(SOURCE / "homehq_png.c"),
            str(SOURCE / "vendor/pngle/pngle.c"), str(SOURCE / "vendor/pngle/miniz.c"),
            str(allocator),
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
        cls.decoder.HQ_PngPrepare.restype = ctypes.c_void_p
        cls.decoder.HQ_PngPrepareWithDictionary.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        cls.decoder.HQ_PngPrepareWithDictionary.restype = ctypes.c_void_p
        cls.decoder.HQ_PngSetPixels.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16)]
        cls.decoder.HQ_PngSetPixels.restype = ctypes.c_bool
        cls.decoder.HQ_TestAllocator.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
        cls.decoder.HQ_TestBorrow.argtypes = [ctypes.c_void_p]
        for name in ("HQ_TestLive", "HQ_TestCalls", "HQ_TestMaximum", "HQ_TestFirst", "HQ_TestBorrowedFrees"):
            getattr(cls.decoder, name).restype = ctypes.c_size_t

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.assertEqual(self.decoder.HQ_TestLive(), 0)
        self.decoder.HQ_TestAllocator(0, 0)
        self.decoder.HQ_TestBorrow(None)

    def tearDown(self):
        self.assertEqual(self.decoder.HQ_TestLive(), 0)
        self.decoder.HQ_TestAllocator(0, 0)
        self.decoder.HQ_TestBorrow(None)

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

    def test_split_decoder_reserves_dictionary_before_fragmented_tls_heap(self):
        self.decoder.HQ_TestAllocator(32768, 0)
        stream = self.decoder.HQ_PngPrepare()
        self.assertTrue(stream, "a 32 KiB largest block must admit the split decoder")
        self.assertEqual(self.decoder.HQ_TestFirst(), 32768)
        self.assertEqual(self.decoder.HQ_TestMaximum(), 32768)
        self.assertEqual(self.decoder.HQ_TestCalls(), 3)
        storage = (ctypes.c_uint16 * (WIDTH * HEIGHT))()
        try:
            self.assertFalse(self.decoder.HQ_PngFeed(stream, b"x", 1))
            self.assertTrue(self.decoder.HQ_PngSetPixels(stream, storage))
            self.assertFalse(self.decoder.HQ_PngSetPixels(stream, storage))
            # Once TLS and destination allocation have fragmented the heap,
            # validated PNG processing must need only bounded small scanlines.
            self.decoder.HQ_TestAllocator(12000, 0)
            data = make_png(6)
            for pos in range(0, len(data), 137):
                part = data[pos:pos + 137]
                self.assertTrue(self.decoder.HQ_PngFeed(stream, part, len(part)))
            self.assertTrue(self.decoder.HQ_PngComplete(stream))
            self.assertLessEqual(self.decoder.HQ_TestMaximum(), 1288)
            self.assert_samples(6, list(storage))
        finally:
            self.decoder.HQ_PngDestroy(stream)

    def test_prepared_allocation_failures_release_every_partial_buffer(self):
        for failing in (1, 2, 3):
            with self.subTest(allocation=failing):
                self.decoder.HQ_TestAllocator(32768, failing)
                self.assertFalse(self.decoder.HQ_PngPrepare())
                self.assertEqual(self.decoder.HQ_TestLive(), 0)
        self.decoder.HQ_TestAllocator(32768, 0)
        stream = self.decoder.HQ_PngPrepare()
        self.assertTrue(stream)
        storage = (ctypes.c_uint16 * (WIDTH * HEIGHT))()
        try:
            self.assertTrue(self.decoder.HQ_PngSetPixels(stream, storage))
            self.decoder.HQ_TestAllocator(1, 0)
            data = make_png()
            self.assertFalse(self.decoder.HQ_PngFeed(stream, data, len(data)))
            self.assertFalse(self.decoder.HQ_PngComplete(stream))
        finally:
            self.decoder.HQ_PngDestroy(stream)

    def test_borrowed_dictionary_needs_only_small_blocks_and_remains_caller_owned(self):
        storage = (ctypes.c_uint8 * (32768 + 32))()
        for i in range(len(storage)): storage[i] = 0xA5
        dictionary = ctypes.cast(ctypes.byref(storage, 16), ctypes.c_void_p)
        self.decoder.HQ_TestBorrow(dictionary)
        self.decoder.HQ_TestAllocator(12000, 0)
        for capacity in (0, 32767):
            self.assertFalse(self.decoder.HQ_PngPrepareWithDictionary(dictionary, capacity))
        self.assertFalse(self.decoder.HQ_PngPrepareWithDictionary(None, 32768))
        self.assertEqual(self.decoder.HQ_TestCalls(), 0)
        for failing in (1, 2):
            self.decoder.HQ_TestAllocator(12000, failing)
            self.assertFalse(self.decoder.HQ_PngPrepareWithDictionary(dictionary, 32768))
            self.assertEqual(self.decoder.HQ_TestLive(), 0)
            self.assertEqual(self.decoder.HQ_TestBorrowedFrees(), 0)
        self.decoder.HQ_TestAllocator(12000, 0)
        stream = self.decoder.HQ_PngPrepareWithDictionary(dictionary, 32768)
        self.assertTrue(stream)
        pixels = (ctypes.c_uint16 * (WIDTH * HEIGHT))()
        try:
            self.assertEqual(self.decoder.HQ_TestCalls(), 2)
            self.assertLessEqual(self.decoder.HQ_TestMaximum(), 12000)
            self.assertTrue(self.decoder.HQ_PngSetPixels(stream, pixels))
            data = make_png(6)
            for pos in range(0, len(data), 193):
                part = data[pos:pos + 193]
                self.assertTrue(self.decoder.HQ_PngFeed(stream, part, len(part)))
            self.assertTrue(self.decoder.HQ_PngComplete(stream))
            self.assert_samples(6, list(pixels))
        finally:
            self.decoder.HQ_PngDestroy(stream)
        self.assertEqual(self.decoder.HQ_TestBorrowedFrees(), 0)
        self.assertEqual(list(storage[:16]), [0xA5] * 16)
        self.assertEqual(list(storage[-16:]), [0xA5] * 16)
        # A destroyed decoder cannot reclaim or keep a lifetime claim on this
        # buffer: the service can immediately reuse the same slot for JSON.
        ctypes.memset(dictionary, 0x5A, 32768)
        self.assertEqual(storage[16], 0x5A)


if __name__ == "__main__":
    unittest.main()
