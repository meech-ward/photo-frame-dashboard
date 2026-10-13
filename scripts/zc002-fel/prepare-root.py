#!/usr/bin/env python3
"""Prepare the historical ZC002 boot patch offline; never flashes it.

See docs/pastigio-zc002.md for the smaller host-key plus stock-su route first.
This candidate changes adbd and SELinux policy.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import gzip
import hashlib
import json
import os
import re
import struct
import sys
import zlib
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class Target:
    boot_size: int = 16 * 1024 * 1024
    boot_sha256: str = "e54245aa3620d314283c7592a59de6a87268c35ab9ac59dd8ac23ff0b54ab366"
    adbd_sha256: str = "b5ec816bcc70371d1af42bfa51be298fd879755937029c2a232c5c566623a750"
    sepolicy_sha256: str = "e538aed0f5a5b93935b897d848ec75477ee5eb8f5bcfd42ff16ce5579ce01e49"
    page_size: int = 2048
    ramdisk_offset: int = 10_168_320
    ramdisk_slot: int = 4_743_168
    adbd_branch_offset: int = 0xF9C
    adbd_after_offset: int = 0xFFE
    adbd_branch_from: bytes = bytes.fromhex("1720")
    adbd_branch_to: bytes = bytes.fromhex("35e0")
    adbd_before: bytes = bytes.fromhex("002717200021")
    adbd_after: bytes = bytes.fromhex("fa6021f0e8ea002840f0a780")
    policy_magic: int = 0xF97CFF8C
    adbd_type_id: int = 100
    shell_type_id: int = 481


TARGET = Target()
BOOT_MAGIC = b"ANDROID!"
CPIO_MAGIC = b"070701"
BOOT_CANDIDATE_NAME = "boot-root-candidate.bin"
MANIFEST_NAME = "manifest.json"


class PatchError(ValueError):
    """Input does not match the one verified stock image/layout."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def align4(size: int) -> int:
    return (size + 3) & ~3


def align_page(size: int, page: int) -> int:
    return (size + page - 1) // page * page


def parse_newc(data: bytes) -> tuple[list[dict], bytes]:
    """Parse a newc archive while preserving each untouched record verbatim."""
    records = []
    files = set()
    pos = 0
    while True:
        start = pos
        if len(data) - pos < 110 or data[pos:pos + 6] != CPIO_MAGIC:
            raise PatchError("ramdisk is not a complete newc archive")
        try:
            fields = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16) for i in range(13)]
        except ValueError as exc:
            raise PatchError("invalid newc header field") from exc
        name_size, file_size = fields[11], fields[6]
        name_start = pos + 110
        name_end = name_start + name_size
        if name_size < 1 or name_end > len(data) or data[name_end - 1] != 0:
            raise PatchError("invalid newc filename length")
        try:
            name = data[name_start:name_end - 1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PatchError("newc filename is not UTF-8") from exc
        data_start = align4(name_end)
        data_end = data_start + file_size
        next_pos = align4(data_end)
        if next_pos > len(data):
            raise PatchError(f"truncated newc entry: {name}")
        if name != "TRAILER!!!":
            if name in files:
                raise PatchError(f"duplicate ramdisk path: {name}")
            files.add(name)
        records.append({
            "name": name,
            "fields": fields,
            "data": data[data_start:data_end],
            "raw": data[start:next_pos],
        })
        pos = next_pos
        if name == "TRAILER!!!":
            return records, data[pos:]


def encode_newc(name: str, data: bytes, fields: list[int]) -> bytes:
    fields = fields[:]
    fields[6] = len(data)
    header = CPIO_MAGIC + b"".join(f"{value:08x}".encode("ascii") for value in fields)
    name_bytes = name.encode("utf-8") + b"\0"
    body = header + name_bytes
    body += b"\0" * (-len(body) % 4)
    body += data
    body += b"\0" * (-len(body) % 4)
    return body


def validate_adb_public_key(line: bytes) -> bytes:
    """Return the canonical ADB RSA key line without its optional comment."""
    tokens = line.strip().split()
    if not tokens:
        raise PatchError("ADB public-key file is empty")
    try:
        key = base64.b64decode(tokens[0], validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise PatchError("ADB public key is not valid base64") from exc
    if len(key) != 524 or struct.unpack_from("<I", key)[0] != 64:
        raise PatchError("expected a 2048-bit Android ADB RSA public key")
    n0inv = struct.unpack_from("<I", key, 4)[0]
    modulus_bytes = key[8:264]
    modulus = int.from_bytes(modulus_bytes, "little")
    rr = int.from_bytes(key[264:520], "little")
    exponent = struct.unpack_from("<I", key, 520)[0]
    if modulus.bit_length() != 2048 or modulus % 2 == 0 or exponent != 65537:
        raise PatchError("ADB RSA key modulus or exponent is invalid")
    if ((n0inv * (modulus & 0xFFFFFFFF)) + 1) & 0xFFFFFFFF:
        raise PatchError("ADB RSA key Montgomery inverse is invalid")
    if rr != pow(2, 4096, modulus):
        raise PatchError("ADB RSA key Montgomery residue is invalid")
    return tokens[0] + b"\n"


def patch_sepolicy(policy: bytes, target: Target) -> bytes:
    if sha256(policy) != target.sepolicy_sha256:
        raise PatchError("sepolicy hash does not match the verified ZC002 build")
    if len(policy) < 8 or struct.unpack_from("<I", policy)[0] != target.policy_magic:
        raise PatchError("sepolicy magic does not match the verified policy format")
    identity_length = struct.unpack_from("<I", policy, 4)[0]
    map_offset = 8 + identity_length + 16
    if map_offset + 12 > len(policy):
        raise PatchError("sepolicy identifier table is out of bounds")
    size, high, count = struct.unpack_from("<3I", policy, map_offset)
    if (size, high, count) != (64, 64, 1):
        raise PatchError("sepolicy first type bitmap layout differs from the tested build")
    target_offset = map_offset + 12 + count * 12
    if target_offset + 12 > len(policy):
        raise PatchError("sepolicy target bitmap is out of bounds")
    size, high, count = struct.unpack_from("<3I", policy, target_offset)
    if (size, high, count) != (64, 0, 0):
        raise PatchError("sepolicy target bitmap is not the tested empty map")
    if target.adbd_type_id < 64 or target.shell_type_id < 64 or target.shell_type_id >= 512:
        raise PatchError("configured SELinux type IDs are outside the verified bitmap")
    bitmap = struct.pack("<3I", 64, 512, 2)
    bitmap += struct.pack("<IQ", 64, 1 << (target.adbd_type_id - 64))
    bitmap += struct.pack("<IQ", 448, 1 << (target.shell_type_id - 448))
    return policy[:target_offset] + bitmap + policy[target_offset + 12:]


def patch_usb_rc(source: bytes) -> bytes:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchError("USB init file is not UTF-8") from exc
    newline = "\r\n" if "\r\n" in text else "\n"
    for mode, product, new_product in (("mtp", "1006", "1007"), ("mass_storage", "1000", "1002")):
        pattern = re.compile(
            rf"(?ms)^on property:sys\.usb\.config={re.escape(mode)}\r?\n.*?(?=^on |\Z)"
        )
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise PatchError(f"expected one stock {mode} USB action")
        block = matches[0].group()
        if "start adbd" in block:
            raise PatchError(f"stock {mode} USB action already starts adbd")
        block, count = re.subn(rf"(?m)^(\s*write\s+\S*/idProduct\s+){product}\s*$",
                               rf"\g<1>{new_product}", block)
        if count != 1:
            raise PatchError(f"stock {mode} action has an unexpected USB product ID")
        block, count = re.subn(r"(?m)^(\s*write\s+\S*/functions\s+)\$\{sys\.usb\.config\}\s*$",
                               rf"\g<1>{mode},adb", block)
        if count != 1:
            raise PatchError(f"stock {mode} action has unexpected USB functions")
        marker = re.compile(r"(?m)^(\s*)setprop sys\.usb\.state")
        if len(list(marker.finditer(block))) != 1:
            raise PatchError(f"stock {mode} action lacks the expected state update")
        block = marker.sub(rf"\1start adbd{newline}\1setprop sys.usb.state", block)
        text = text[:matches[0].start()] + block + text[matches[0].end():]
    return text.encode("utf-8")


def _entry(records: list[dict], name: str) -> dict:
    matches = [record for record in records if record["name"] == name]
    if len(matches) != 1:
        raise PatchError(f"expected exactly one ramdisk entry: {name}")
    return matches[0]


def prepare_boot(original: bytes, public_key_line: bytes, target: Target = TARGET) -> tuple[bytes, dict]:
    if len(original) != target.boot_size:
        raise PatchError(f"boot input must be exactly {target.boot_size} bytes")
    original_hash = sha256(original)
    if original_hash != target.boot_sha256:
        raise PatchError("boot hash does not match the verified ZC002 stock image")
    if original[:8] != BOOT_MAGIC:
        raise PatchError("boot image does not have an Android legacy header")
    kernel_size, _kernel_addr, ramdisk_size, _ramdisk_addr, second_size, _second_addr, _tags, page, _dt, _unused = struct.unpack_from("<10I", original, 8)
    if page != target.page_size or second_size != 0:
        raise PatchError("boot header page size or second-stage layout differs")
    ramdisk_offset = page + align_page(kernel_size, page)
    if ramdisk_offset != target.ramdisk_offset:
        raise PatchError("boot ramdisk offset differs from the verified image")
    if ramdisk_size <= 0 or ramdisk_size > target.ramdisk_slot:
        raise PatchError("boot ramdisk size does not fit the verified slot")
    compressed = original[ramdisk_offset:ramdisk_offset + ramdisk_size]
    try:
        ramdisk = gzip.decompress(compressed)
    except (OSError, EOFError, zlib.error) as exc:
        raise PatchError("boot ramdisk is not a complete gzip stream") from exc
    records, trailer = parse_newc(ramdisk)
    files = {record["name"]: record for record in records if record["name"] != "TRAILER!!!"}
    for required in ("sbin/adbd", "sepolicy", "default.prop", "init.sun8i.usb.rc"):
        if required not in files:
            raise PatchError(f"required ramdisk entry is missing: {required}")

    adbd = bytearray(files["sbin/adbd"]["data"])
    if sha256(adbd) != target.adbd_sha256:
        raise PatchError("adbd hash does not match the verified ZC002 build")
    offset = target.adbd_branch_offset
    if (adbd[offset - 2:offset + 4] != target.adbd_before
            or adbd[target.adbd_after_offset:target.adbd_after_offset + len(target.adbd_after)] != target.adbd_after
            or adbd[offset:offset + 2] != target.adbd_branch_from):
        raise PatchError("adbd instruction context does not match the verified branch site")
    adbd[offset:offset + 2] = target.adbd_branch_to
    patched_policy = patch_sepolicy(files["sepolicy"]["data"], target)
    prop = files["default.prop"]["data"]
    if prop.count(b"persist.sys.usb.config=none") != 1:
        raise PatchError("default.prop does not have the single expected USB property")
    patched_prop = prop.replace(b"persist.sys.usb.config=none", b"persist.sys.usb.config=mtp,adb")
    patched_usb = patch_usb_rc(files["init.sun8i.usb.rc"]["data"])
    if any(record["name"] == "adb_keys" for record in records):
        raise PatchError("stock ramdisk unexpectedly already contains adb_keys")

    key_line = validate_adb_public_key(public_key_line)
    changes = {
        "sbin/adbd": bytes(adbd),
        "sepolicy": patched_policy,
        "default.prop": patched_prop,
        "init.sun8i.usb.rc": patched_usb,
    }
    output_records = []
    for record in records:
        if record["name"] == "TRAILER!!!":
            fields = [max(item["fields"][0] for item in records) + 1, 0o100644, 0, 0, 1,
                      0, len(key_line), 0, 0, 0, 0, len(b"adb_keys\0"), 0]
            output_records.append(encode_newc("adb_keys", key_line, fields))
            output_records.append(record["raw"])
        elif record["name"] in changes:
            output_records.append(encode_newc(record["name"], changes[record["name"]], record["fields"]))
        else:
            output_records.append(record["raw"])
    new_ramdisk = b"".join(output_records) + trailer
    new_gzip = gzip.compress(new_ramdisk, compresslevel=9, mtime=0)
    if len(new_gzip) > target.ramdisk_slot:
        raise PatchError("patched ramdisk does not fit the original slot")
    if gzip.decompress(new_gzip) != new_ramdisk:
        raise PatchError("patched ramdisk failed gzip round-trip validation")

    candidate = bytearray(original)
    struct.pack_into("<I", candidate, 16, len(new_gzip))
    candidate[ramdisk_offset:ramdisk_offset + target.ramdisk_slot] = (
        new_gzip + b"\0" * (target.ramdisk_slot - len(new_gzip))
    )
    # Recompute Android's legacy SHA-1 image ID over the unchanged kernel and new ramdisk.
    header = struct.unpack_from("<10I", candidate, 8)
    kernel_size, _ka, new_size, _ra, second_size, _sa, _tags, page, _dt, _unused = header
    if second_size:
        raise PatchError("unexpected second-stage image")
    image_id = hashlib.sha1()
    second_offset = ramdisk_offset + align_page(new_size, page)
    for start, size in ((page, kernel_size), (ramdisk_offset, new_size),
                        (second_offset, second_size)):
        image_id.update(candidate[start:start + size])
        image_id.update(struct.pack("<I", size))
    candidate[576:608] = image_id.digest() + b"\0" * 12
    # Verify the stored ID from the finalized header, including the zero-sized
    # second-stage field required by the legacy Android boot-image algorithm.
    stored = candidate[576:596]
    verify_id = hashlib.sha1()
    for start, size in ((page, kernel_size), (ramdisk_offset, new_size),
                        (second_offset, second_size)):
        verify_id.update(candidate[start:start + size])
        verify_id.update(struct.pack("<I", size))
    if stored != verify_id.digest():
        raise PatchError("rebuilt legacy Android image ID did not verify")

    if candidate[1024:ramdisk_offset] != original[1024:ramdisk_offset]:
        raise PatchError("unexpected change outside the Android header and ramdisk")
    if candidate[ramdisk_offset + target.ramdisk_slot:] != original[ramdisk_offset + target.ramdisk_slot:]:
        raise PatchError("unexpected change after the original ramdisk slot")
    verified_records, _ = parse_newc(gzip.decompress(candidate[ramdisk_offset:ramdisk_offset + new_size]))
    verified_files = {record["name"]: record["data"] for record in verified_records}
    if verified_files.get("sbin/adbd") != bytes(adbd) or verified_files.get("sepolicy") != patched_policy:
        raise PatchError("repacked candidate did not preserve the validated patch")
    if verified_files.get("adb_keys") != key_line:
        raise PatchError("candidate did not contain the normalized trusted public key")

    manifest = {
        "format": 1,
        "device_match": "Pastigio ZC002 / MS33-V2.0 / ZC002_20260313; verify the device separately",
        "original_boot_sha256": original_hash,
        "candidate_boot_sha256": sha256(candidate),
        "original_adbd_sha256": target.adbd_sha256,
        "original_sepolicy_sha256": target.sepolicy_sha256,
        "candidate_adbd_sha256": sha256(bytes(adbd)),
        "candidate_sepolicy_sha256": sha256(patched_policy),
        "changed_ramdisk_paths": list(changes) + ["adb_keys"],
        "adb_authentication": "preserved; only the supplied trusted public key is added",
        "public_key_comment_stripped": True,
        "ramdisk_offset": ramdisk_offset,
        "ramdisk_slot_bytes": target.ramdisk_slot,
        "ramdisk_original_compressed_bytes": ramdisk_size,
        "ramdisk_candidate_compressed_bytes": len(new_gzip),
        "allowed_boot_change_regions": [
            {"name": "legacy_header", "start": 0, "end_exclusive": 1024},
            {"name": "original_ramdisk_slot", "start": ramdisk_offset,
             "end_exclusive": ramdisk_offset + target.ramdisk_slot},
        ],
        "scope": "offline preparation only; no device access or flash write",
    }
    return bytes(candidate), manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boot", required=True, type=Path, help="verified original full 16 MiB boot partition")
    parser.add_argument("--adb-public-key", required=True, type=Path, help="trusted adbkey.pub public key")
    parser.add_argument("--output-dir", required=True, type=Path, help="new directory for candidate and manifest")
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists():
            raise PatchError("output directory already exists; choose a new empty path")
        original = args.boot.read_bytes()
        public_key = args.adb_public_key.read_bytes()
        candidate, manifest = prepare_boot(original, public_key)
        args.output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        if os.name == "posix":
            args.output_dir.chmod(0o700)
        candidate_path = args.output_dir / BOOT_CANDIDATE_NAME
        manifest_path = args.output_dir / MANIFEST_NAME
        candidate_path.write_bytes(candidate)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if os.name == "posix":
            candidate_path.chmod(0o600)
            manifest_path.chmod(0o600)
    except (OSError, PatchError) as exc:
        print(f"refusing to prepare candidate: {exc}", file=sys.stderr)
        return 2
    print(f"Candidate: {args.output_dir / BOOT_CANDIDATE_NAME}")
    print(f"Manifest:  {args.output_dir / MANIFEST_NAME}")
    print("Offline candidate only; this tool does not write to a device.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
