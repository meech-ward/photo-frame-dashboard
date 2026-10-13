"""Host-only safety tests for the offline ZC002 boot candidate builder."""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import gzip
import hashlib
import importlib.util
import io
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).with_name("prepare-root.py")
SPEC = importlib.util.spec_from_file_location("zc002_prepare_root", HELPER)
assert SPEC and SPEC.loader
prepare_root = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare_root
SPEC.loader.exec_module(prepare_root)


def make_newc(name: str, data: bytes, inode: int, mode: int = 0o100644) -> bytes:
    fields = [inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name.encode()) + 1, 0]
    return prepare_root.encode_newc(name, data, fields)


def make_adb_key() -> bytes:
    # Structurally valid deterministic 2048-bit Android RSA public key fixture.
    modulus = (1 << 2048) - 159
    low_word = modulus & 0xFFFFFFFF
    n0inv = (-pow(low_word, -1, 1 << 32)) & 0xFFFFFFFF
    rr = pow(2, 4096, modulus)
    raw = struct.pack("<II", 64, n0inv)
    raw += modulus.to_bytes(256, "little")
    raw += rr.to_bytes(256, "little")
    raw += struct.pack("<I", 65537)
    return base64.b64encode(raw) + b" laptop@example # stripped comment\n"


def make_fixture() -> tuple[bytes, bytes, prepare_root.Target]:
    adbd = bytearray(0x1010)
    adbd[0xF9A:0xFA0] = bytes.fromhex("002717200021")
    adbd[0xFFE:0x100A] = bytes.fromhex("fa6021f0e8ea002840f0a780")
    policy = bytearray(96)
    struct.pack_into("<II", policy, 0, 0xF97CFF8C, 0)
    struct.pack_into("<I", policy, 4, 8)
    policy[8:16] = b"fixture!"
    struct.pack_into("<3I", policy, 32, 64, 64, 1)
    policy[44:56] = b"\0" * 12
    struct.pack_into("<3I", policy, 56, 64, 0, 0)
    usb_rc = (
        b"on property:sys.usb.config=mtp\n"
        b"    write /sys/class/android_usb/android0/idProduct 1006\n"
        b"    write /sys/class/android_usb/android0/functions ${sys.usb.config}\n"
        b"    setprop sys.usb.state ${sys.usb.config}\n"
        b"on property:sys.usb.config=mass_storage\n"
        b"    write /sys/class/android_usb/android0/idProduct 1000\n"
        b"    write /sys/class/android_usb/android0/functions ${sys.usb.config}\n"
        b"    setprop sys.usb.state ${sys.usb.config}\n"
    )
    files = [
        make_newc("sbin/adbd", bytes(adbd), 1),
        make_newc("sepolicy", bytes(policy), 2),
        make_newc("default.prop", b"persist.sys.usb.config=none\n", 3),
        make_newc("init.sun8i.usb.rc", usb_rc, 4),
        make_newc("TRAILER!!!", b"", 5),
    ]
    raw_ramdisk = b"".join(files)
    ramdisk_gzip = gzip.compress(raw_ramdisk, mtime=0)
    page = 2048
    kernel_size = 4096
    ramdisk_offset = page + kernel_size
    ramdisk_slot = 32768
    boot = bytearray(65536)
    boot[:8] = prepare_root.BOOT_MAGIC
    struct.pack_into("<10I", boot, 8, kernel_size, 0, len(ramdisk_gzip), 0, 0, 0, 0, page, 0, 0)
    boot[page:page + kernel_size] = b"K" * kernel_size
    boot[ramdisk_offset:ramdisk_offset + ramdisk_slot] = ramdisk_gzip + b"\0" * (ramdisk_slot - len(ramdisk_gzip))
    target = dataclasses.replace(
        prepare_root.TARGET,
        boot_size=len(boot),
        boot_sha256=prepare_root.sha256(bytes(boot)),
        adbd_sha256=prepare_root.sha256(bytes(adbd)),
        sepolicy_sha256=prepare_root.sha256(bytes(policy)),
        ramdisk_offset=ramdisk_offset,
        ramdisk_slot=ramdisk_slot,
    )
    return bytes(boot), make_adb_key(), target


class PrepareRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.boot, self.key, self.target = make_fixture()

    def test_candidate_changes_only_header_and_ramdisk_slot(self) -> None:
        candidate, manifest = prepare_root.prepare_boot(self.boot, self.key, self.target)
        ro = self.target.ramdisk_offset
        end = ro + self.target.ramdisk_slot
        self.assertEqual(len(candidate), len(self.boot))
        self.assertEqual(candidate[1024:ro], self.boot[1024:ro])
        self.assertEqual(candidate[end:], self.boot[end:])
        kernel_size, _ka, ramdisk_size, _ra, second_size, _sa, _tags, page, _dt, _unused = struct.unpack_from("<10I", candidate, 8)
        self.assertEqual(second_size, 0)
        expected_id = hashlib.sha1()
        second_offset = ro + prepare_root.align_page(ramdisk_size, page)
        for start, size in ((page, kernel_size), (ro, ramdisk_size), (second_offset, 0)):
            expected_id.update(candidate[start:start + size])
            expected_id.update(struct.pack("<I", size))
        self.assertEqual(candidate[576:596], expected_id.digest())
        two_field_id = hashlib.sha1()
        for start, size in ((page, kernel_size), (ro, ramdisk_size)):
            two_field_id.update(candidate[start:start + size])
            two_field_id.update(struct.pack("<I", size))
        self.assertNotEqual(candidate[576:596], two_field_id.digest())
        self.assertEqual(manifest["original_boot_sha256"], hashlib.sha256(self.boot).hexdigest())
        self.assertEqual(manifest["scope"], "offline preparation only; no device access or flash write")
        ramdisk_size = struct.unpack_from("<I", candidate, 16)[0]
        records, _ = prepare_root.parse_newc(gzip.decompress(candidate[ro:ro + ramdisk_size]))
        files = {r["name"]: r["data"] for r in records}
        self.assertEqual(files["sbin/adbd"][0xF9C:0xF9E], bytes.fromhex("35e0"))
        self.assertEqual(files["adb_keys"], self.key.split()[0] + b"\n")
        self.assertNotIn(b"laptop@example", files["adb_keys"])
        self.assertIn(b"start adbd", files["init.sun8i.usb.rc"])

    def test_refuses_wrong_boot_hash_before_patching(self) -> None:
        bad_target = dataclasses.replace(self.target, boot_sha256="0" * 64)
        with self.assertRaisesRegex(prepare_root.PatchError, "boot hash"):
            prepare_root.prepare_boot(self.boot, self.key, bad_target)

    def test_refuses_modified_adbd_even_if_boot_hash_is_updated(self) -> None:
        offset = self.target.ramdisk_offset
        size = struct.unpack_from("<I", self.boot, 16)[0]
        records, trailer = prepare_root.parse_newc(gzip.decompress(self.boot[offset:offset + size]))
        damaged_records = []
        for record in records:
            if record["name"] == "sbin/adbd":
                data = bytearray(record["data"])
                data[0x200] ^= 1
                damaged_records.append(prepare_root.encode_newc(record["name"], bytes(data), record["fields"]))
            else:
                damaged_records.append(record["raw"])
        ramdisk_gzip = gzip.compress(b"".join(damaged_records) + trailer, mtime=0)
        bad_boot = bytearray(self.boot)
        struct.pack_into("<I", bad_boot, 16, len(ramdisk_gzip))
        bad_boot[offset:offset + self.target.ramdisk_slot] = ramdisk_gzip + b"\0" * (self.target.ramdisk_slot - len(ramdisk_gzip))
        target = dataclasses.replace(self.target, boot_sha256=prepare_root.sha256(bytes(bad_boot)))
        with self.assertRaisesRegex(prepare_root.PatchError, "adbd hash"):
            prepare_root.prepare_boot(bytes(bad_boot), self.key, target)

    def test_refuses_unrecognized_adbd_bytes(self) -> None:
        target = dataclasses.replace(self.target, adbd_sha256="0" * 64)
        with self.assertRaisesRegex(prepare_root.PatchError, "adbd hash"):
            prepare_root.prepare_boot(self.boot, self.key, target)

    def test_refuses_invalid_rsa_public_key(self) -> None:
        with self.assertRaisesRegex(prepare_root.PatchError, "RSA"):
            prepare_root.prepare_boot(self.boot, b"bm90LWEtcHVibGljLWtleQ== test", self.target)

    def test_refuses_existing_output_directory_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            out = Path(temp) / "existing"
            out.mkdir()
            marker = out / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = prepare_root.main([
                    "--boot", str(Path(temp) / "missing-boot"),
                    "--adb-public-key", str(Path(temp) / "missing-key"),
                    "--output-dir", str(out),
                ])
            self.assertEqual(result, 2)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
            self.assertIn("already exists", stderr.getvalue())

    def test_spl_injection_is_repeatable_on_a_synthetic_tree(self) -> None:
        spl_dir = Path(__file__).parent / "spl"
        patcher_path = spl_dir / "patch-reader.py"
        spec = importlib.util.spec_from_file_location("zc002_patch_reader", patcher_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        patcher = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = patcher
        spec.loader.exec_module(patcher)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            root = Path(temp)
            mach = root / "arch" / "arm" / "mach-sunxi"
            mach.mkdir(parents=True)
            board = mach / "board.c"
            makefile = mach / "Makefile"
            board.write_text(
                'void sunxi_board_init(void)\n{\n'
                '\tdebug("Returning to FEL sp=%x, lr=%x\\n", fel_stash.sp, fel_stash.lr);\n}\n',
                encoding="utf-8",
            )
            makefile.write_text("obj-y += board.o\n", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                patcher.main()
                first_board = board.read_text(encoding="utf-8")
                first_makefile = makefile.read_text(encoding="utf-8")
                patcher.main()
            finally:
                os.chdir(old_cwd)
            self.assertEqual(board.read_text(encoding="utf-8"), first_board)
            self.assertEqual(makefile.read_text(encoding="utf-8"), first_makefile)
            self.assertEqual(first_board.count("hd_storage_probe();"), 1)
            self.assertIn("extern void hd_storage_probe(void);", first_board)
            self.assertEqual(first_makefile.count("hd-reader.o"), 1)


if __name__ == "__main__":
    unittest.main()
