#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Perform one bounded, read-only transaction with the ZC002 FEL SPL helper."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zlib


EGON_MAGIC = b"eGON.BT0"
EGON_CHECKSUM_MAGIC = 0x5F0A6C39
MAX_SPL_BYTES = 0x6000
REQUEST_MAGIC = 0x48445731
REQUEST_VERSION = 3
RESULT_MAGIC = 0x48445231
RESULT_VERSION = 3
RESULT_BYTES = 0x800
RESULT_EXTRA_OFFSET = 450 * 4
DATA_ADDRESS = 0x43001000
RESULT_ADDRESS = 0x43000000
SECTOR_BYTES = 512


class ReadError(ValueError):
    """Raised when an input or device result does not satisfy the ABI."""


def _egon_checksum(image: bytes | bytearray) -> int:
    if len(image) % 4:
        raise ReadError("SPL image length must be a multiple of four")
    words = bytearray(image)
    struct.pack_into("<I", words, 12, EGON_CHECKSUM_MAGIC)
    return sum(struct.unpack(f"<{len(words) // 4}I", words)) & 0xFFFFFFFF


def _validate_spl(image: bytes, symbols: str) -> tuple[int, int]:
    if len(image) < 32 or len(image) > MAX_SPL_BYTES or len(image) % 4:
        raise ReadError("SPL image length is outside the supported eGON bounds")
    if image[4:12] != EGON_MAGIC:
        raise ReadError("missing Allwinner eGON magic")
    declared_size = struct.unpack_from("<I", image, 16)[0]
    if declared_size != len(image):
        raise ReadError("eGON header length does not match SPL file length")
    if _egon_checksum(image) != struct.unpack_from("<I", image, 12)[0]:
        raise ReadError("invalid eGON checksum")

    def symbol_offset(name: str) -> int:
        matches = re.findall(rf"^\s*([0-9a-fA-F]+)\s+[A-Za-z]\s+{re.escape(name)}\s*$", symbols, re.M)
        if len(matches) != 1:
            raise ReadError(f"symbols must contain exactly one {name}")
        return int(matches[0], 16)

    request_offset = symbol_offset("hd_reader_request")
    end_offset = symbol_offset("_end")
    if request_offset < 32 or request_offset % 4 or end_offset < request_offset + 64:
        raise ReadError("request symbol bounds are invalid")
    if end_offset > len(image) or end_offset > MAX_SPL_BYTES:
        raise ReadError("SPL symbols extend beyond the image or supported memory")
    if image[request_offset:request_offset + 64] != bytes(64):
        raise ReadError("SPL request template is not the expected zeroed fail-closed request")
    return request_offset, end_offset


def build_read_request(
    image: bytes,
    symbols: str,
    *,
    lba: int,
    blocks: int,
    sectors: int,
    cid_words: tuple[int, int, int, int],
    clock_hz: int = 12_000_000,
    electrical_mode: int = 3,
) -> bytes:
    """Validate and prepare a per-unit request; never accesses a device."""
    if not 0 <= lba <= 0xFFFFFFFFFFFFFFFF or blocks < 1:
        raise ReadError("LBA and block count must be positive and in range")
    if sectors < 1 or sectors > 0xFFFFFFFF or lba + blocks > sectors:
        raise ReadError("requested range exceeds the supplied device capacity")
    if blocks > 2048 or (clock_hz == 400_000 and blocks > 8):
        raise ReadError("request exceeds the SPL read limit for the selected clock")
    if clock_hz not in (400_000, 12_000_000):
        raise ReadError("clock must be 400000 or 12000000 Hz")
    if electrical_mode != 3:
        raise ReadError("only the unit-tested electrical mode 3 is supported")
    if len(cid_words) != 4 or any(not 0 <= word <= 0xFFFFFFFF for word in cid_words):
        raise ReadError("CID must be supplied as four 32-bit words")
    request_offset, _end_offset = _validate_spl(image, symbols)
    values = (
        REQUEST_MAGIC, REQUEST_VERSION, lba & 0xFFFFFFFF, lba >> 32,
        blocks, clock_hz, 1, electrical_mode, 0, 0, 0, *cid_words, sectors,
    )
    prepared = bytearray(image)
    struct.pack_into("<16I", prepared, request_offset, *values)
    struct.pack_into("<I", prepared, 12, 0)
    struct.pack_into("<I", prepared, 12, _egon_checksum(prepared))
    if _egon_checksum(prepared) != struct.unpack_from("<I", prepared, 12)[0]:
        raise ReadError("failed to rebuild eGON checksum")
    return bytes(prepared)


def build_identify_request(image: bytes, symbols: str) -> bytes:
    """Prepare a probe that reads only MMC identity, never a block payload."""
    request_offset, _end_offset = _validate_spl(image, symbols)
    values = (REQUEST_MAGIC, REQUEST_VERSION, 0, 0, 1, 12_000_000, 1, 3,
              0, 0, 0, 0, 0, 0, 0, 0)
    prepared = bytearray(image)
    struct.pack_into("<16I", prepared, request_offset, *values)
    struct.pack_into("<I", prepared, 12, 0)
    struct.pack_into("<I", prepared, 12, _egon_checksum(prepared))
    return bytes(prepared)


def _read_result(raw: bytes, *, cid_words: tuple[int, int, int, int], sectors: int,
                 blocks: int, clock_hz: int) -> tuple[int, int]:
    if len(raw) != RESULT_BYTES:
        raise ReadError("SPL result buffer is truncated or has an unexpected size")
    values = struct.unpack_from("<15I", raw)
    if values[0] != RESULT_MAGIC or values[1] != RESULT_VERSION:
        raise ReadError("SPL result magic/version mismatch")
    if values[2] != 5 or values[3] != 0:
        raise ReadError("SPL read did not complete successfully")
    if values[4] != 1 or values[5] != SECTOR_BYTES:
        raise ReadError("unexpected MMC device or sector size")
    if values[8] != 1 or values[9] != clock_hz or values[14] > 64:
        raise ReadError("unexpected bus width, clock, or diagnostic trace count")
    found_sectors = values[6] | (values[7] << 32)
    found_cid = tuple(values[10:14])
    if found_sectors != sectors or found_cid != cid_words:
        raise ReadError("device CID/capacity does not match the explicit request")
    extra = struct.unpack_from("<6I", raw, RESULT_EXTRA_OFFSET)
    if extra[0] != 0 or extra[2] != 0 or extra[3] != 0:
        raise ReadError("unexpected operation or read-only result fields")
    if extra[4] != 0 or extra[5] != blocks:
        raise ReadError("SPL result block count does not match the request")
    return found_sectors, extra[1]


def _read_identity(raw: bytes) -> tuple[tuple[int, int, int, int], int]:
    """Accept the expected pre-read identity mismatch response from probe mode."""
    if len(raw) != RESULT_BYTES:
        raise ReadError("SPL identity result is truncated or has an unexpected size")
    values = struct.unpack_from("<15I", raw)
    if values[0] != RESULT_MAGIC or values[1] != RESULT_VERSION:
        raise ReadError("SPL result magic/version mismatch")
    if values[2] != 3 or values[3] != ((-1100) & 0xFFFFFFFF):
        raise ReadError("identity probe did not stop at the expected pre-read check")
    if values[4] != 1 or values[5] != SECTOR_BYTES or values[14] > 64:
        raise ReadError("unexpected MMC device, sector size, or diagnostic trace count")
    sectors = values[6] | (values[7] << 32)
    cid = tuple(values[10:14])
    if not 0 < sectors <= 0xFFFFFFFF or cid == (0, 0, 0, 0):
        raise ReadError("identity probe returned an empty or unsupported CID/capacity")
    extra = struct.unpack_from("<6I", raw, RESULT_EXTRA_OFFSET)
    if extra[0] != 0 or extra[1:5] != (0, 0, 0, 0) or extra[5] != 1:
        raise ReadError("identity probe result indicates an unexpected operation")
    return cid, sectors


def _run_fel(executable: str, *args: str) -> str:
    try:
        completed = subprocess.run(
            [executable, *args], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReadError(f"sunxi-fel command failed: {exc}") from exc
    output = completed.stdout + completed.stderr
    if completed.returncode:
        raise ReadError(f"sunxi-fel exited with status {completed.returncode}")
    return output


def read_once(
    *, spl_path: Path, symbols_path: Path, fel: str, output_path: Path,
    lba: int, blocks: int, sectors: int, cid_words: tuple[int, int, int, int],
    clock_hz: int = 12_000_000, electrical_mode: int = 3,
) -> int:
    if output_path.exists() or output_path.is_symlink():
        raise ReadError("output file already exists; refusing to overwrite")
    if not output_path.parent.is_dir():
        raise ReadError("output parent directory must already exist")
    image = spl_path.read_bytes()
    symbols = symbols_path.read_text(encoding="ascii")
    request_image = build_read_request(
        image, symbols, lba=lba, blocks=blocks, sectors=sectors,
        cid_words=cid_words, clock_hz=clock_hz, electrical_mode=electrical_mode,
    )

    with tempfile.TemporaryDirectory(prefix="zc002-fel-read-", dir=output_path.parent) as temp:
        tmp = Path(temp)
        request_path = tmp / "request-spl.bin"
        result_path = tmp / "result.bin"
        data_path = tmp / "read-data.bin"
        request_path.write_bytes(request_image)
        if "soc=00001667" not in _run_fel(fel, "version"):
            raise ReadError("connected FEL device did not identify as Allwinner A33")
        _run_fel(fel, "-v", "spl", str(request_path), "read", hex(RESULT_ADDRESS),
                 hex(RESULT_BYTES), str(result_path))
        _sectors, expected_crc = _read_result(
            result_path.read_bytes(), cid_words=cid_words, sectors=sectors, blocks=blocks,
            clock_hz=clock_hz,
        )
        _run_fel(fel, "read", hex(DATA_ADDRESS), hex(blocks * SECTOR_BYTES), str(data_path))
        data = data_path.read_bytes()
        if len(data) != blocks * SECTOR_BYTES:
            raise ReadError("data read length does not match the requested block count")
        if data and all(byte == 0xCC for byte in data):
            raise ReadError("read data is still the SPL's 0xCC filler pattern")
        if zlib.crc32(data) != expected_crc:
            raise ReadError("read data CRC does not match the SPL result")
        if "soc=00001667" not in _run_fel(fel, "version"):
            raise ReadError("SPL did not return to the expected A33 FEL device")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(output_path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
    return len(data)


def identify_once(*, spl_path: Path, symbols_path: Path, fel: str) -> tuple[tuple[int, int, int, int], int]:
    """Return the unit's CID/capacity after a failed-closed, no-block-read probe."""
    image = spl_path.read_bytes()
    symbols = symbols_path.read_text(encoding="ascii")
    request_image = build_identify_request(image, symbols)
    with tempfile.TemporaryDirectory(prefix="zc002-fel-identify-", dir=spl_path.parent) as temp:
        tmp = Path(temp)
        request_path = tmp / "request-spl.bin"
        result_path = tmp / "result.bin"
        request_path.write_bytes(request_image)
        if "soc=00001667" not in _run_fel(fel, "version"):
            raise ReadError("connected FEL device did not identify as Allwinner A33")
        _run_fel(fel, "-v", "spl", str(request_path), "read", hex(RESULT_ADDRESS),
                 hex(RESULT_BYTES), str(result_path))
        identity = _read_identity(result_path.read_bytes())
        if "soc=00001667" not in _run_fel(fel, "version"):
            raise ReadError("SPL did not return to the expected A33 FEL device")
    return identity


def _parse_cid_words(value: str) -> tuple[int, int, int, int]:
    pieces = value.split(",")
    if len(pieces) != 4 or any(not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{8}", part) for part in pieces):
        raise argparse.ArgumentTypeError("CID must be four comma-separated 8-digit hexadecimal words")
    return tuple(int(part.removeprefix("0x").removeprefix("0X"), 16) for part in pieces)  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spl", required=True, type=Path, help="checksummed SPL image from build-reader.sh")
    parser.add_argument("--symbols", required=True, type=Path, help="reader.symbols emitted by build-reader.sh")
    parser.add_argument("--sunxi-fel", required=True, help="path/name of the locally installed sunxi-fel executable")
    parser.add_argument("--identify", action="store_true", help="read and print this unit's CID/capacity only")
    parser.add_argument("--output", type=Path, help="new local file for returned read bytes; must not exist")
    parser.add_argument("--lba", type=lambda s: int(s, 0))
    parser.add_argument("--blocks", type=int)
    parser.add_argument("--sectors", type=int, help="capacity read from this unit")
    parser.add_argument("--cid-words", type=_parse_cid_words,
                        help="four explicit 32-bit CID words from this unit, comma-separated hex")
    parser.add_argument("--clock-hz", type=int, choices=(400_000, 12_000_000), default=12_000_000)
    args = parser.parse_args(argv)
    try:
        if args.identify:
            if any(value is not None for value in (args.output, args.lba, args.blocks, args.sectors, args.cid_words)):
                parser.error("--identify cannot be combined with read arguments")
            cid_words, sectors = identify_once(spl_path=args.spl, symbols_path=args.symbols,
                                                 fel=args.sunxi_fel)
            cid_text = ",".join(f"0x{word:08x}" for word in cid_words)
            print(f"Private unit identity (do not share): --cid-words {cid_text} --sectors {sectors}")
            return 0
        if args.output is None or args.lba is None or args.blocks is None or args.sectors is None or args.cid_words is None:
            parser.error("read mode requires --output, --lba, --blocks, --sectors, and --cid-words")
        length = read_once(
            spl_path=args.spl, symbols_path=args.symbols, fel=args.sunxi_fel,
            output_path=args.output, lba=args.lba, blocks=args.blocks, sectors=args.sectors,
            cid_words=args.cid_words, clock_hz=args.clock_hz,
        )
    except (OSError, ReadError) as exc:
        parser.error(str(exc))
    print(f"Read {length} bytes to {args.output}; no eMMC write operation was issued.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
