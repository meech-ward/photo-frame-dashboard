#!/usr/bin/env python3
"""Offline fixture/real-host-filesystem checks; no USB or network operations."""
import asyncio
import binascii
import contextlib
import gc
import importlib.util
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import zlib

HERE = Path(__file__).resolve().parent
DEFAULT = HERE.parent / 'badge' / 'homehq' / 'transport.py'


def load_probe():
    machine = types.ModuleType('machine')
    machine.unique_id = lambda: bytes.fromhex('e7e7d70437b93611')
    namespace = {'HOMEHQ_PHOTO_PROBE_RUN': False, '__name__': 'photo_storage_probe_offline'}
    with patch.dict(sys.modules, {'machine': machine}):
        exec(compile((HERE / 'photo_storage_probe.py').read_text(), str(HERE / 'photo_storage_probe.py'), 'exec'), namespace)
    return namespace


def ilistdir(path):
    return [(entry.name, 0x4000 if entry.is_dir() else 0x8000, 0, entry.stat().st_size)
            for entry in os.scandir(path)]


class PhotoProbeTests(unittest.TestCase):
    def setUp(self):
        self.probe = load_probe()
        self.directory = tempfile.TemporaryDirectory(prefix='homehq-photo-probe-')
        self.root = Path(self.directory.name)
        self.probe['STATE'] = str(self.root)
        self.patches = [patch.object(gc, 'mem_free', lambda: 4 * 1024 * 1024, create=True),
                        patch.object(time, 'ticks_ms', lambda: int(time.monotonic() * 1000), create=True),
                        patch.object(time, 'ticks_diff', lambda end, start: end - start, create=True),
                        patch.object(os, 'ilistdir', ilistdir, create=True)]
        for item in self.patches:
            item.start()
        source = Path(os.environ.get('HOMEHQ_PROBE_TRANSPORT', str(DEFAULT)))
        spec = importlib.util.spec_from_file_location('homehq_photo_probe_product', source)
        self.transport = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.transport)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_exact_cap_png_has_valid_chunks_and_real_rgb_pixels(self):
        body, offset, end = self.probe['maximum_photo']()
        self.assertEqual(len(body), 327680)
        self.assertTrue(self.transport.valid_photo(body))
        for value in (65, 66, 67, 68):
            self.probe['variant'](body, offset, end, value)
            position = 8
            compressed = []
            text = None
            while position < len(body):
                size = struct.unpack('>I', body[position:position + 4])[0]
                kind = bytes(body[position + 4:position + 8])
                data = body[position + 8:position + 8 + size]
                crc = struct.unpack('>I', body[position + 8 + size:position + 12 + size])[0]
                self.assertEqual(crc, binascii.crc32(kind + data) & 0xffffffff)
                if kind == b'IDAT':
                    compressed.append(data)
                if kind == b'tEXt':
                    text = data
                position += 12 + size
            self.assertEqual(position, len(body))
            self.assertTrue(text.startswith(b'Comment\0'))
            self.assertEqual(text[-1], value)
            self.assertEqual(zlib.decompress(b''.join(compressed)),
                             (b'\0' + self.probe['RGB'] * 320) * 240)

    def test_real_files_three_replacements_partial_cleanup_retry_and_state_integrity(self):
        secret = self.root / 'homehq-session.json'
        secret.write_bytes(b'private-session-must-never-be-printed')
        other = self.root / 'other-state.bin'
        other.write_bytes(b's' * (103 * 1024))
        slots = tuple(str(self.root / ('homehq-photo-{}.png'.format(i))) for i in range(2))
        baseline = self.probe['state_hashes'](slots)
        records = []
        monitor = self.probe['FilesystemMonitor'](os, open, slots, records)
        body, offset, end = self.probe['maximum_photo']()
        original_os = self.transport.os
        self.transport.os = monitor
        self.transport.open = monitor.open
        try:
            asyncio.run(self.probe['downloads'](self.transport, monitor, slots, body, offset, end, records))
        finally:
            self.transport.os = original_os
            del self.transport.open
        self.assertEqual(monitor.peak_photo_bytes, 655360)
        self.assertEqual([row['phase'] for row in records],
                         ['download', 'download', 'download', 'rejected_response', 'partial_write', 'retry'])
        self.assertEqual(self.probe['state_hashes'](slots), baseline)
        self.assertEqual(secret.read_bytes(), b'private-session-must-never-be-printed')
        self.assertFalse(any(self.root.glob('*.tmp')))

    def test_peak_monitor_rejects_previous_three_file_replacement_design(self):
        body, offset, end = self.probe['maximum_photo']()
        slots = tuple(str(self.root / ('homehq-photo-{}.png'.format(i))) for i in range(2))
        for slot in slots:
            Path(slot).write_bytes(body)
        monitor = self.probe['FilesystemMonitor'](os, open, slots, [])
        with self.assertRaisesRegex(RuntimeError, 'Photo storage exceeded'):
            with monitor.open(slots[0] + '.tmp', 'wb') as target:
                target.write(body)
        self.assertGreater(monitor.peak_photo_bytes, 655360)

    def test_wrong_uid_refuses_before_writes_and_prints_no_credentials(self):
        secret = self.root / 'homehq-session.json'; secret.write_bytes(b'never-print-this-session')
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(RuntimeError):
            self.probe['main']()
        self.assertEqual(secret.read_bytes(), b'never-print-this-session')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['homehq-session.json'])
        self.assertNotIn('never-print-this-session', output.getvalue())
        self.assertIn('"stage": "gate"', output.getvalue())

    def test_existing_photo_refuses_and_is_never_cleaned(self):
        existing = self.root / 'homehq-photo-0.png'; existing.write_bytes(b'previous-owned-photo')
        self.probe['gate'] = lambda: {'uid': self.probe['TARGET'], 'runtime_mpy': 7942}
        self.probe['machine'].WDT = lambda timeout: types.SimpleNamespace(feed=lambda: None)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(RuntimeError):
            self.probe['main']()
        self.assertEqual(existing.read_bytes(), b'previous-owned-photo')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['homehq-photo-0.png'])


if __name__ == '__main__':
    unittest.main()
