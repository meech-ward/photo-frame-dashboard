"""Offline tests for the read-only ZC002 FEL host transaction tool."""

from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zlib

HELPER = Path(__file__).with_name("fel-read.py")
SPEC = importlib.util.spec_from_file_location("zc002_fel_read", HELPER)
assert SPEC and SPEC.loader
fel_read = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fel_read
SPEC.loader.exec_module(fel_read)


def make_image() -> tuple[bytes, str]:
    image = bytearray(0x6000)
    image[4:12] = fel_read.EGON_MAGIC
    struct.pack_into("<I", image, 16, len(image))
    request_offset = 0x1200
    end_offset = 0x1400
    symbols = (
        f"00001200 D hd_reader_request\n"
        f"00001400 D _end\n"
    )
    struct.pack_into("<I", image, 12, fel_read._egon_checksum(image))
    return bytes(image), symbols


def result_data(*, cid=(1, 2, 3, 4), sectors=200000, blocks=2,
                phase=5, rc=0, dev=1, blocklen=512, op=0, written=0,
                bus_width=1, clock=12_000_000, trace_count=0, filler_crc=0) -> bytes:
    result = bytearray(fel_read.RESULT_BYTES)
    fields = [fel_read.RESULT_MAGIC, fel_read.RESULT_VERSION, phase, rc, dev, blocklen,
              sectors & 0xFFFFFFFF, sectors >> 32, bus_width, clock, *cid, trace_count]
    struct.pack_into("<15I", result, 0, *fields)
    struct.pack_into("<6I", result, fel_read.RESULT_EXTRA_OFFSET,
                     op, filler_crc, 0, 0, written, blocks)
    return bytes(result)


class FelReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image, self.symbols = make_image()
        self.cid = (1, 2, 3, 4)
        self.data = b"A" * 1024
        self.expected_crc = zlib.crc32(self.data)

    def test_request_is_bound_and_checksum_rebuilt(self) -> None:
        request = fel_read.build_read_request(
            self.image, self.symbols, lba=172032, blocks=2, sectors=200000,
            cid_words=self.cid,
        )
        offset = 0x1200
        words = struct.unpack_from("<16I", request, offset)
        self.assertEqual(words, (fel_read.REQUEST_MAGIC, 3, 172032, 0, 2, 12_000_000,
                                 1, 3, 0, 0, 0, *self.cid, 200000))
        checksum_words = bytearray(request)
        struct.pack_into("<I", checksum_words, 12, fel_read.EGON_CHECKSUM_MAGIC)
        expected_checksum = sum(
            struct.unpack(f"<{len(checksum_words) // 4}I", checksum_words)
        ) & 0xFFFFFFFF
        self.assertEqual(struct.unpack_from("<I", request, 12)[0], expected_checksum)

    def test_refuses_range_and_transfer_limits_before_subprocess(self) -> None:
        with mock.patch.object(fel_read.subprocess, "run") as run:
            with self.assertRaisesRegex(fel_read.ReadError, "capacity"):
                fel_read.build_read_request(self.image, self.symbols, lba=199999, blocks=2,
                                            sectors=200000, cid_words=self.cid)
            with self.assertRaisesRegex(fel_read.ReadError, "limit"):
                fel_read.build_read_request(self.image, self.symbols, lba=0, blocks=9,
                                            sectors=200000, cid_words=self.cid, clock_hz=400_000)
            with self.assertRaisesRegex(fel_read.ReadError, "mode 3"):
                fel_read.build_read_request(self.image, self.symbols, lba=0, blocks=1,
                                            sectors=200000, cid_words=self.cid, electrical_mode=1)
            self.assertEqual(run.call_count, 0)

    def test_rejects_bad_checksum_and_symbol_bounds_before_subprocess(self) -> None:
        damaged = bytearray(self.image)
        damaged[0x2000] ^= 1
        bad_symbols = "00005fc0 D hd_reader_request\n00006010 D _end\n"
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            root = Path(temp)
            spl = root / "spl.bin"
            symbols = root / "symbols.txt"
            out = root / "dump.bin"
            symbols.write_text(self.symbols, encoding="ascii")
            with mock.patch.object(fel_read.subprocess, "run") as run:
                spl.write_bytes(damaged)
                with self.assertRaisesRegex(fel_read.ReadError, "checksum"):
                    fel_read.read_once(spl_path=spl, symbols_path=symbols, fel="sunxi-fel",
                                       output_path=out, lba=0, blocks=2, sectors=200000,
                                       cid_words=self.cid)
                spl.write_bytes(self.image)
                symbols.write_text(bad_symbols, encoding="ascii")
                with self.assertRaisesRegex(fel_read.ReadError, "symbols extend"):
                    fel_read.read_once(spl_path=spl, symbols_path=symbols, fel="sunxi-fel",
                                       output_path=out, lba=0, blocks=2, sectors=200000,
                                       cid_words=self.cid)
                self.assertEqual(run.call_count, 0)

    def _mock_fel(self, *, result: bytes | None = None, data: bytes | None = None):
        valid_result = result or result_data(cid=self.cid, sectors=200000, blocks=2, filler_crc=self.expected_crc)
        valid_data = data if data is not None else self.data

        def run(args, **kwargs):
            if args[-1] == "version":
                return mock.Mock(returncode=0, stdout="AWUSBFEX soc=00001667(A33)\n", stderr="")
            if "spl" in args:
                Path(args[-1]).write_bytes(valid_result)
            elif args[0] == "sunxi-fel" and args[1] == "read":
                Path(args[-1]).write_bytes(valid_data)
            return mock.Mock(returncode=0, stdout="", stderr="")

        return run

    def _execute_mocked(self, temp: str, *, result: bytes | None = None,
                        data: bytes | None = None) -> tuple[int, Path, mock.Mock]:
        root = Path(temp)
        spl = root / "spl.bin"
        symbols = root / "symbols.txt"
        out = root / "dump.bin"
        spl.write_bytes(self.image)
        symbols.write_text(self.symbols, encoding="ascii")
        run = mock.Mock(side_effect=self._mock_fel(result=result, data=data))
        with mock.patch.object(fel_read.subprocess, "run", run):
            count = fel_read.read_once(spl_path=spl, symbols_path=symbols, fel="sunxi-fel",
                                       output_path=out, lba=172032, blocks=2, sectors=200000,
                                       cid_words=self.cid)
        return count, out, run

    def test_read_success_validates_result_crc_and_uses_read_only_commands(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            count, out, run = self._execute_mocked(temp)
            self.assertEqual(count, len(self.data))
            self.assertEqual(out.read_bytes(), self.data)
            flat = [arg for call in run.call_args_list for arg in call.args[0]]
            self.assertNotIn("write", flat)
            self.assertEqual(sum(call.args[0][1] == "version" for call in run.call_args_list), 2)

    def test_refuses_wrong_cid_and_truncated_result_before_output(self) -> None:
        cases = [
            result_data(cid=(9, 2, 3, 4), sectors=200000, blocks=2, filler_crc=self.expected_crc),
            result_data(cid=self.cid, sectors=200000, blocks=2, filler_crc=self.expected_crc)[:-1],
        ]
        for bad in cases:
            with self.subTest(length=len(bad)), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
                root = Path(temp)
                spl = root / "spl.bin"; spl.write_bytes(self.image)
                symbols = root / "symbols.txt"; symbols.write_text(self.symbols, encoding="ascii")
                out = root / "dump.bin"
                run = mock.Mock(side_effect=self._mock_fel(result=bad))
                with mock.patch.object(fel_read.subprocess, "run", run):
                    with self.assertRaises(fel_read.ReadError):
                        fel_read.read_once(spl_path=spl, symbols_path=symbols, fel="sunxi-fel",
                                           output_path=out, lba=172032, blocks=2, sectors=200000,
                                           cid_words=self.cid)
                self.assertFalse(out.exists())

    def test_refuses_filler_and_bad_status_before_output(self) -> None:
        for result, payload, error in (
            (result_data(cid=self.cid, sectors=200000, blocks=2, filler_crc=zlib.crc32(b"\xcc" * 1024)),
             b"\xcc" * 1024, "filler"),
            (result_data(cid=self.cid, sectors=200000, blocks=2, phase=4, filler_crc=self.expected_crc),
             self.data, "complete"),
        ):
            with self.subTest(error=error), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
                root = Path(temp)
                spl = root / "spl.bin"; spl.write_bytes(self.image)
                symbols = root / "symbols.txt"; symbols.write_text(self.symbols, encoding="ascii")
                out = root / "dump.bin"
                run = mock.Mock(side_effect=self._mock_fel(result=result, data=payload))
                with mock.patch.object(fel_read.subprocess, "run", run):
                    with self.assertRaisesRegex(fel_read.ReadError, error):
                        fel_read.read_once(spl_path=spl, symbols_path=symbols, fel="sunxi-fel",
                                           output_path=out, lba=172032, blocks=2, sectors=200000,
                                           cid_words=self.cid)
                self.assertFalse(out.exists())

    def test_refuses_wrong_crc_and_unexpected_result_metadata(self) -> None:
        cases = (
            (result_data(cid=self.cid, blocks=2, filler_crc=self.expected_crc ^ 1), self.data, "CRC"),
            (result_data(cid=self.cid, blocks=2, bus_width=4, filler_crc=self.expected_crc), self.data, "bus width"),
        )
        for result, payload, error in cases:
            with self.subTest(error=error), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
                root = Path(temp)
                spl = root / "spl.bin"; spl.write_bytes(self.image)
                symbols = root / "symbols.txt"; symbols.write_text(self.symbols, encoding="ascii")
                out = root / "dump.bin"
                run = mock.Mock(side_effect=self._mock_fel(result=result, data=payload))
                with mock.patch.object(fel_read.subprocess, "run", run):
                    with self.assertRaisesRegex(fel_read.ReadError, error):
                        fel_read.read_once(spl_path=spl, symbols_path=symbols, fel="sunxi-fel",
                                           output_path=out, lba=172032, blocks=2, sectors=200000,
                                           cid_words=self.cid)
                self.assertFalse(out.exists())

    def test_identify_accepts_only_expected_pre_read_mismatch(self) -> None:
        valid = result_data(cid=self.cid, sectors=200000, blocks=1,
                            phase=3, rc=(-1100) & 0xFFFFFFFF)
        self.assertEqual(fel_read._read_identity(valid), (self.cid, 200000))
        for invalid in (
            result_data(cid=self.cid, sectors=200000, blocks=1, phase=5, rc=0),
            result_data(cid=self.cid, sectors=200000, blocks=1, phase=3, rc=0),
            result_data(cid=(0, 0, 0, 0), sectors=200000, blocks=1,
                        phase=3, rc=(-1100) & 0xFFFFFFFF),
        ):
            with self.assertRaises(fel_read.ReadError):
                fel_read._read_identity(invalid)

    def test_identify_uses_only_fixed_one_block_readonly_probe(self) -> None:
        identity = result_data(cid=self.cid, sectors=200000, blocks=1,
                               phase=3, rc=(-1100) & 0xFFFFFFFF)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            root = Path(temp)
            spl = root / "spl.bin"; spl.write_bytes(self.image)
            symbols = root / "symbols.txt"; symbols.write_text(self.symbols, encoding="ascii")

            def run(args, **kwargs):
                if args[-1] == "version":
                    return mock.Mock(returncode=0, stdout="soc=00001667(A33)", stderr="")
                if "spl" in args:
                    request = Path(args[3]).read_bytes()
                    fields = struct.unpack_from("<16I", request, 0x1200)
                    self.assertEqual(fields[2:5], (0, 0, 1))
                    self.assertEqual(fields[8:16], (0, 0, 0, 0, 0, 0, 0, 0))
                    Path(args[-1]).write_bytes(identity)
                return mock.Mock(returncode=0, stdout="", stderr="")

            runner = mock.Mock(side_effect=run)
            with mock.patch.object(fel_read.subprocess, "run", runner):
                self.assertEqual(fel_read.identify_once(spl_path=spl, symbols_path=symbols,
                                                         fel="sunxi-fel"), (self.cid, 200000))
            commands = [call.args[0][1:] for call in runner.call_args_list]
            self.assertEqual(sum(command[0] == "read" for command in commands), 0)
            self.assertEqual(sum(command[0] == "version" for command in commands), 2)


if __name__ == "__main__":
    unittest.main()
