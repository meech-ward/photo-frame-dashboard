#!/usr/bin/env python3
"""Build the Route U root-ADB boot patch from a boot partition pulled in stock recovery.

Usage (from the repository root):
  python3 -I scripts/a33-uboot/recovery-patch-build.py diagnostics/recovery-pull/boot.img <boot-sha256>

<boot-sha256> is the full T6 hash (SHA-256 of the first 31,028 sectors) that you checked
against the firmware table. Only the two tested May images are accepted (see TESTED), and the
script refuses an image whose hash differs from the one you passed.

This uses boot-patch.py's own build() and verify(): the same patch, the same structural checks
(one cpio file changed; header changes limited to the ramdisk size and image ID). It does not
check the partition's start sector, because it has no partition table: recovery-patch.sh checks
that on the device (sysfs start 172032, size 65536) before it writes anything.

Writes diagnostics/recovery-patch/:
  pushA.bin           original header + kernel + patched ramdisk slot (the first push)
  pushB.bin           patched header sectors only (the second push)
  original-image.bin  the original 31,028-sector image (undo copy)
  patched-image.bin   the expected result, for the read-back
  plan.json           sizes and SHA-256 values that recovery-patch.sh checks
Nothing here touches a device.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "diagnostics/recovery-patch"
IMAGE_SECTORS, PART_START, PART_SECTORS = 31028, 172032, 65536
# Firmware whose recovery-window write has been tested. Add a hash only after it is tested.
TESTED = {
    "6c118dc1aa583797884c33cd3ac3796c72b2bd3a3f1fcafd1bf0982ae5f29e2c": "V10-1680.0.20260529",
    "9a6e2456952f3dc2b99e64ea021321397bdc824364b5c8b42f503f847261630a": "FL-AIMOR-OS.0.20260519",
}


def fail(message):
    sys.exit(f"STOP: {message}")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, want = Path(sys.argv[1]), sys.argv[2].lower()
    if want not in TESTED:
        fail("this route has only been tested on May 20260519 and 20260529 boot images "
             f"({', '.join(h[:8] for h in TESTED)}); refusing {want[:8]}")
    spec = importlib.util.spec_from_file_location("boot_patch", REPO / "scripts/a33-uboot/boot-patch.py")
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)

    old = src.read_bytes()
    if len(old) != PART_SECTORS * 512:
        fail(f"{src} is {len(old)} bytes; a whole boot partition is {PART_SECTORS * 512}")
    img = IMAGE_SECTORS * 512
    sha = lambda b: hashlib.sha256(b).hexdigest()
    if sha(old[:img]) != want:
        fail(f"T6 hash is {sha(old[:img])}, not the {want} you passed")

    new, ramdisk_offset, slot = bp.build(old)
    header_sectors = bp.verify(old, new, ramdisk_offset, slot)
    header = header_sectors * 512
    if len(new) != len(old) or new[img:] != old[img:]:
        fail("the patch changed bytes past the boot image")
    if old[header:ramdisk_offset] != new[header:ramdisk_offset]:
        fail("bytes between the header and the ramdisk slot changed")

    push_a = old[:ramdisk_offset] + new[ramdisk_offset:img]     # header still original
    push_b = new[:header]
    OUT.mkdir(parents=True, exist_ok=True)
    files = {"pushA.bin": push_a, "pushB.bin": push_b,
             "original-image.bin": old[:img], "patched-image.bin": new[:img]}
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    plan = {"partition_start": PART_START, "partition_sectors": PART_SECTORS, "image_bytes": img,
            "header_bytes": header, "ramdisk_offset": ramdisk_offset, "ramdisk_slot": slot,
            "sha256": {name: sha(data) for name, data in files.items()}}
    (OUT / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(f"Changed: header sectors [0, {header_sectors}) and ramdisk slot at +{ramdisk_offset} ({slot} bytes)")
    print("Checks passed: one cpio file changed; header changes limited to ramdisk size + ID.")
    print(f"original {plan['sha256']['original-image.bin']}\npatched  {plan['sha256']['patched-image.bin']}")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
