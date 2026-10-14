#!/usr/bin/env python3
"""Check the zero-allocation metadata and direct-row scanner against wire JSON."""
import ctypes
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Info(ctypes.Structure):
    _fields_ = [("home", ctypes.c_char * 96), ("viewer", ctypes.c_char * 96),
                ("revision", ctypes.c_int64), ("server_time", ctypes.c_int64), ("demo", ctypes.c_bool)]


def snapshot():
    return {"schema_version": 1, "revision": 17, "server_time": 1791746280,
            "home": {"id": "household", "demo": False}, "viewer": {"user_id": "viewer-id"},
            "people": [], "events": [], "chores": [], "shopping": [], "photos": [],
            "devices": [], "agents": []}


class WireTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="homehq-wire-test-")
        library = pathlib.Path(cls.directory.name) / ("wire.dylib" if sys.platform == "darwin" else "wire.so")
        subprocess.run(["cc", "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                        str(ROOT / "src/homehq_wire.c"), "-o", str(library)], check=True)
        cls.parser = ctypes.CDLL(str(library))
        cls.parser.HQ_WireValidate.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(Info)]
        cls.parser.HQ_WireValidate.restype = ctypes.c_bool
        cls.parser.HQ_WireHasRow.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_char_p]
        cls.parser.HQ_WireHasRow.restype = ctypes.c_bool

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def wire(self, value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() if not isinstance(value, bytes) else value

    def validate(self, value):
        wire, info = self.wire(value), Info()
        return self.parser.HQ_WireValidate(wire, len(wire), ctypes.byref(info)), info

    def has(self, value, section, row_id):
        wire = self.wire(value)
        return self.parser.HQ_WireHasRow(wire, len(wire), section.encode(), row_id.encode())

    def test_schema_clock_and_identity_types_are_validated(self):
        accepted, info = self.validate(snapshot())
        self.assertTrue(accepted)
        self.assertEqual((info.home, info.viewer, info.revision, info.server_time, info.demo),
                         (b"household", b"viewer-id", 17, 1791746280, False))
        for key in ("schema_version", "revision", "server_time"):
            for value in ("wrong", True, None, [], {}, 1.5, 1e100):
                with self.subTest(key=key, value=value):
                    self.assertFalse(self.validate(dict(snapshot(), **{key: value}))[0])
        self.assertFalse(self.validate(dict(snapshot(), schema_version=2))[0])
        self.assertFalse(self.validate(dict(snapshot(), revision=-1))[0])
        for field, key in (("home", "id"), ("viewer", "user_id")):
            for value in (None, 3, "", "x" * 96, "house/id", "x\x00bad", "mémber"):
                data = snapshot();data[field][key] = value
                self.assertFalse(self.validate(data)[0])

    def test_duplicate_metadata_and_required_arrays(self):
        wire = self.wire(snapshot())
        for duplicate in (b'"schema_version":1', b'"home":{"id":"other"}', b'"viewer":{"user_id":"other"}',
                          b'"revision":18', b'"server_time":1', b'"events":[]', b'"devices":[]'):
            self.assertFalse(self.validate(wire[:-1] + b"," + duplicate + b"}")[0])
        for section in ("people", "events", "chores", "shopping", "photos"):
            data = snapshot();del data[section]
            self.assertFalse(self.validate(data)[0])
            data = snapshot();data[section] = {}
            self.assertFalse(self.validate(data)[0])
        for home in (b'{"id":"h","id":"h"}', b'{"id":"h","demo":true,"demo":false}'):
            wire = self.wire(snapshot()).replace(b'{"id":"household","demo":false}', home)
            self.assertFalse(self.validate(wire)[0])

    def test_real_demo_and_optional_private_hosted_fixture(self):
        wire = (ROOT.parents[1] / "fixtures/demo.json").read_bytes()
        accepted, info = self.validate(wire)
        self.assertTrue(accepted)
        self.assertTrue(info.demo)
        self.assertFalse(info.home)
        fixtures = [wire]
        private = os.environ.get("HOMEHQ_HOSTED_SNAPSHOT")
        if private:
            fixtures.append(pathlib.Path(private).read_bytes())
        for fixture in fixtures:
            self.assertTrue(self.validate(fixture)[0])
            data = json.loads(fixture)
            for section in ("people", "events", "chores", "shopping", "photos", "devices", "agents"):
                for row in data.get(section, []):
                    self.assertTrue(self.has(fixture, section, row["id"]))
            self.assertFalse(self.has(fixture, "chores", "deleted-row"))

    def test_row_membership_is_direct_and_exact(self):
        data = snapshot()
        data["chores"] = [{"meta": {"id": "nested"}, "tags": ["before"], "id": "c1", "other": [{"id": "after"}]},
                          {"id": "c10"}]
        data["shopping"] = [{"id": "g1"}]
        for row in ("c1", "c10"):
            self.assertTrue(self.has(data, "chores", row))
        for row in ("c", "nested", "before", "after", "g1", "missing"):
            self.assertFalse(self.has(data, "chores", row))
        self.assertTrue(self.has(data, "shopping", "g1"))
        self.assertFalse(self.has(data, "other", "g1"))
        escaped = self.wire(data).replace(b'"c1"', b'"c\\u0031"')
        self.assertTrue(self.has(escaped, "chores", "c1"))

    def test_complete_document_bounds_escapes_and_number_grammar(self):
        wire = self.wire(snapshot())
        for suffix in (b"junk", b"\x00", b"{}"):
            self.assertFalse(self.validate(wire + suffix)[0])
        for token in (b"01", b"+1", b"1.", b"1e", b"-", b"NaN", b"Infinity", b"truex"):
            self.assertFalse(self.validate(wire[:-1] + b',"unknown":' + token + b"}")[0])
        for string in (b'"\\uD800"', b'"\\uDC00"', b'"\\uD800\\u1234"', b'"\\x"', b'"\x01"',
                       b'"\xff"', b'"\xc0\x80"', b'"\xed\xa0\x80"', b'"\xf4\x90\x80\x80"'):
            self.assertFalse(self.validate(wire[:-1] + b',"unknown":' + string + b"}")[0])
        self.assertTrue(self.validate(wire[:-1] + b',"unknown":"\\uD83D\\uDE00"}')[0])
        self.assertTrue(self.validate(dict(snapshot(), unknown="Café ☀️"))[0])
        self.assertFalse(self.validate(wire.replace(b'"schema_version"', b'"schema_version\\u0000bad"'))[0])
        self.assertTrue(self.validate(b" \n" + wire + b"\r\n")[0])
        self.assertFalse(self.validate(wire + bytes(32769))[0])
        data = snapshot();data["events"] = [{}] * 64
        self.assertTrue(self.validate(data)[0])
        data["events"].append({})
        self.assertFalse(self.validate(data)[0])
        self.assertTrue(self.validate(wire[:-1] + b',"unknown":' + b"[" * 30 + b"null" + b"]" * 30 + b"}")[0])
        self.assertFalse(self.validate(wire[:-1] + b',"unknown":' + b"[" * 31 + b"null" + b"]" * 31 + b"}")[0])


if __name__ == "__main__":
    unittest.main()
