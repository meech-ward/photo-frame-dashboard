"""Projection consistency without retaining private household values in output."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from projection_inventory import PAGES, project, footprint

ROOT = Path(__file__).resolve().parents[1]


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="homehq-projection-")
        library = Path(cls.temporary.name) / "project.so"
        allocator = Path(cls.temporary.name) / "allocator.c"
        allocator.write_text("""#undef malloc
#undef free
#include <stdlib.h>
#include <stddef.h>
static size_t limit, calls, last;
void HQ_TestLimit(size_t value) { limit=value; calls=last=0; }
size_t HQ_TestCalls(void) { return calls; }
size_t HQ_TestLast(void) { return last; }
void *HQ_TestAlloc(size_t size) {
    ++calls; last=size;
    return limit && size>limit ? NULL : malloc(size);
}
void HQ_TestFree(void *value) { free(value); }
""")
        subprocess.run(["cc", "-shared", "-fPIC", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-Dmalloc=HQ_TestAlloc", "-Dfree=HQ_TestFree",
                        str(ROOT / "src/homehq_projection.c"), str(ROOT / "src/homehq_wire.c"),
                        str(allocator), "-o", str(library)], check=True)
        cls.native = ctypes.CDLL(str(library))
        cls.native.HQ_ProjectWire.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p]
        cls.native.HQ_ProjectWire.restype = ctypes.c_bool
        cls.native.HQ_ProjectCopy.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p]
        cls.native.HQ_ProjectCopy.restype = ctypes.c_void_p
        cls.native.HQ_TestLimit.argtypes = [ctypes.c_size_t]
        cls.native.HQ_TestLimit.restype = None
        cls.native.HQ_TestCalls.restype = cls.native.HQ_TestLast.restype = ctypes.c_size_t
        cls.native.HQ_TestFree.argtypes = [ctypes.c_void_p]
        cls.native.HQ_TestFree.restype = None
        cls.inputs = [json.loads((ROOT.parents[1] / "fixtures/demo.json").read_text())]
        private = os.environ.get("HQ_PROJECTION_PRIVATE_SNAPSHOT")
        if private:
            cls.inputs.append(json.loads(Path(private).read_text()))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def native_project(self, value, page):
        source = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        buffer = ctypes.create_string_buffer(source)
        self.assertTrue(self.native.HQ_ProjectWire(buffer, len(source), page.encode()), "valid projection rejected")
        self.assertLessEqual(len(buffer.value), len(source))
        canonical = ctypes.create_string_buffer(source)
        self.native.HQ_TestLimit(0)
        copied = self.native.HQ_ProjectCopy(canonical, len(source), page.encode())
        self.assertTrue(copied, "copy of valid projection rejected")
        try:
            self.assertTrue(ctypes.string_at(copied) == buffer.value, "copy and in-place bytes differ")
            self.assertEqual(canonical.value, source)
        finally:
            self.native.HQ_TestFree(copied)
        return json.loads(buffer.value), buffer.value

    def test_all_rows_and_active_semantics_match_inventory(self):
        for index, value in enumerate(self.inputs):
            for page in PAGES:
                with self.subTest(input=index, page=page):
                    actual, encoded = self.native_project(value, page)
                    # Do not print dictionary diffs: the optional live fixture
                    # contains private household identifiers and text.
                    self.assertTrue(actual == project(value, page), "semantic projection differs from inventory")
                    buffer = ctypes.create_string_buffer(encoded)
                    self.assertTrue(self.native.HQ_ProjectWire(buffer, len(encoded), page.encode()))
                    self.assertTrue(json.loads(buffer.value) == actual, "projection is not idempotent")
                    self.assertLess(footprint(actual)[0], footprint(value)[0] // 2)

    def test_escaped_values_nested_state_and_unknown_fields(self):
        value = json.loads(json.dumps(self.inputs[0]))
        value["events"][0]["notes"] = "UTF-8: café ° / quotes \" \\ newline\n emoji 🌊"
        value["events"][0]["ignored"] = {"id": "nested-only", "surprise": [1, True, None]}
        value["devices"][0]["state"] = {"on": True, "level": 88, "extra": {"ignored": "value"}}
        value["members"] = [{"user_id": "synthetic-owner"}]
        value["home"]["not-used"] = "discarded"
        for page in PAGES:
            actual, _ = self.native_project(value, page)
            self.assertTrue(actual == project(value, page), "escaped or nested projection differs")

    def test_optional_jpeg_variant_keeps_png_selection_and_projection_size(self):
        value = json.loads(json.dumps(self.inputs[0]))
        home = "12345678-1234-1234-1234-123456789abc"
        for index, photo in enumerate(value["photos"]):
            digest = hashlib.sha256(str(index).encode()).hexdigest()
            photo["path"] = home + "/" + digest + ".png"
        baseline = {page: self.native_project(value, page) for page in PAGES}
        for nullable in (True, False):
            for index, photo in enumerate(value["photos"]):
                digest = hashlib.sha256(("jpeg:" + str(index)).encode()).hexdigest()
                photo["jpeg_path"] = None if nullable else home + "/" + digest + ".jpg"
            for page in PAGES:
                with self.subTest(nullable=nullable, page=page):
                    actual, encoded = self.native_project(value, page)
                    # The ESP32 keeps its PNG codec and memory budget. An unused
                    # alternative must not replace path or grow its page graph.
                    self.assertTrue(actual == baseline[page][0], "JPEG variant changed PNG selection")
                    self.assertEqual(encoded, baseline[page][1])

    def test_exact_copy_matches_inplace_without_full_wire_allocation(self):
        for index, value in enumerate(self.inputs):
            source = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            self.assertGreater(len(source), 12000)
            for page in PAGES:
                with self.subTest(input=index, page=page):
                    actual, inplace = self.native_project(value, page)
                    original = ctypes.create_string_buffer(source)
                    # A 12 KB largest allocation accepts every view but rejects
                    # the full 17/23 KB fixture: reproduce native fragmentation.
                    self.native.HQ_TestLimit(12000)
                    copied = self.native.HQ_ProjectCopy(original, len(source), page.encode())
                    self.assertTrue(copied, "projected allocation unexpectedly failed")
                    try:
                        encoded = ctypes.string_at(copied)
                        self.assertTrue(encoded == inplace, "copy and in-place bytes differ")
                        self.assertTrue(json.loads(encoded) == actual, "copy changed active semantics")
                        self.assertEqual(original.value, source)
                        self.assertEqual(self.native.HQ_TestCalls(), 1)
                        self.assertEqual(self.native.HQ_TestLast(), len(encoded) + 1)
                    finally:
                        self.native.HQ_TestFree(copied)

    def test_copy_allocation_failure_keeps_source_unchanged(self):
        source = json.dumps(self.inputs[0], ensure_ascii=False).encode()
        original = ctypes.create_string_buffer(source)
        self.native.HQ_TestLimit(1)
        self.assertFalse(self.native.HQ_ProjectCopy(original, len(source), b"today"))
        self.assertEqual(original.value, source)
        self.assertEqual(self.native.HQ_TestCalls(), 1)
        self.native.HQ_TestLimit(0)

    def test_escaped_ascii_keys_and_reordered_roots(self):
        value = dict(reversed(list(self.inputs[0].items())))
        source = json.dumps(value, ensure_ascii=False).replace('"people":', '"peo\\u0070le":').encode()
        buffer = ctypes.create_string_buffer(source)
        self.assertTrue(self.native.HQ_ProjectWire(buffer, len(source), b"calendar"))
        self.assertTrue(json.loads(buffer.value) == project(value, "calendar"))
        canonical = ctypes.create_string_buffer(source)
        self.native.HQ_TestLimit(0)
        copied = self.native.HQ_ProjectCopy(canonical, len(source), b"calendar")
        self.assertTrue(copied)
        try:
            self.assertTrue(ctypes.string_at(copied) == buffer.value, "escaped-key copy differs")
            self.assertEqual(canonical.value, source)
        finally:
            self.native.HQ_TestFree(copied)

    def test_invalid_input_is_rejected_before_mutation(self):
        source = json.dumps(self.inputs[0]).encode()
        candidates = [source[:-1], b"[]", b"{}", source.replace(b'"schema_version": 1', b'"schema_version": true')]
        for candidate in candidates:
            buffer = ctypes.create_string_buffer(candidate)
            self.assertFalse(self.native.HQ_ProjectWire(buffer, len(candidate), b"photos"))
            self.assertEqual(buffer.value, candidate)
            self.native.HQ_TestLimit(0)
            self.assertFalse(self.native.HQ_ProjectCopy(buffer, len(candidate), b"photos"))
            self.assertEqual(buffer.value, candidate)
            self.assertEqual(self.native.HQ_TestCalls(), 0)
        buffer = ctypes.create_string_buffer(source)
        self.assertFalse(self.native.HQ_ProjectWire(buffer, len(source), b"unknown"))
        self.assertEqual(buffer.value, source)
        self.native.HQ_TestLimit(0)
        self.assertFalse(self.native.HQ_ProjectCopy(buffer, len(source), b"unknown"))
        self.assertEqual(self.native.HQ_TestCalls(), 0)


if __name__ == "__main__":
    unittest.main()
