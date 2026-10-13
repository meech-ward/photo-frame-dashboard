# scripts/a133: LOOFII C-3 (Allwinner A133) tools

Written for and tested on **one** LOOFII C-3 (see `docs/allwinner-a133-loofii-c3.md`). Check the identity values there first.
Nothing here writes to a device unless you name the phase explicitly. `a133-flash.sh flash-gsi` and `rollback` set `FB_ALLOW_FLASH` themselves, so they ask you to type `flash` first and check each partition's size on the device before writing. Run `fbflash.py` directly only if you know what you are doing.

Requirements: Python 3 with `pyusb` (+ libusb; on macOS `brew install libusb`), `e2fsprogs` (`e2fsck`, `debugfs`),
`sunxi-tools` (`sunxi-fel`) for FEL, `dtc` for the display overlay, Node 22+ for `cdp-eval.mjs`.

| Script | What it does | Writes to the device? |
|---|---|---|
| `fb.py` | Talk to the A133 U-Boot fastboot (`1f3a:1010`) with pyusb (macOS `fastboot` hangs on it): `getvar:*`, `reboot` (needs `FB_ALLOW_REBOOT=1`) | reboot only |
| `fbflash.py` | Send sparse pieces to **one** named partition. Refuses unless `FB_ALLOW_FLASH=<that partition>` and `FB_PART_BYTES=<exact partition size>` are set and every piece's sparse header matches that size with RAW/DONT_CARE chunks only | **yes** |
| `validate_pieces.py` | Check every sparse piece (header, chunk types RAW/DONT_CARE only, total size == partition, coverage). U-Boot doesn't bounds-check sparse images, so always run this first | no |
| `mksparse.py` | Split a raw image into independent sparse pieces (each covers the whole partition: RAW for its range, DONT_CARE elsewhere). `FORCE_RAW=1` avoids FILL chunks | no |
| `liblp.py` | Minimal Android 10 dynamic-partition (LP metadata v10.0) parser/serializer | no |
| `build_super.py` | Build a new `super` from the factory `super` dump + a GSI: `system` replaced, `vendor`/`product` byte-identical, metadata rewritten | no |
| `validate_super.py` | Independent checks of the built `super` vs factory + GSI (geometry, metadata slots/checksums, extents, data hashes) | no |
| `ext4_rewrite_small.py` | Replace a ≤4096-byte file that sits in one unshared block of an ext4 image, in place (e.g. `/system/bin/phh-on-boot.sh`) | no |
| `ext4_append.py` | Append bytes to a file inside an ext4 image when they fit in the last block's slack (e.g. `/system/product/etc/build.prop`) | no |
| `patch_gsi_orientation.py` | One-off: append `ro.surface_flinger.primary_display_orientation` to phh AOSP 12.1 **v416** `system-squeak-arm32_binder64-ab-vanilla`. Block/inode numbers are for that exact image and are verified before writing; use `ext4_append.py` for anything else | no |
| `a133-flash.sh` | Runbook phases: `preflight`, `to-uboot`, `flash-gsi`, `verify-gsi`, `fel-to-uboot` (FEL -> RTC flag `0x07000118=0x5F` -> watchdog reset -> U-Boot fastboot), `rollback`, `verify-factory`. `preflight` prints the exact partition sizes and the current `super` hash to compare with your backup; `verify-*` read the partition back after boot. Settings are environment variables listed at the top of the script | **yes** (named phases) |
| `cdp-eval.mjs` | Evaluate JS in the kiosk WebView over the DevTools socket (`adb forward tcp:9333 localabstract:webview_devtools_remote_<pid>`) — handy for on-device perf measurements | no |
| `templates/` | `firewall.sh` (set `LAN_CIDR`), `adb-key-restore.sh` (paste your own key, without the user@host comment), `kiosk-defaults.sh`, `sensors-sepolicy.cil`, `dtbo-60hz.dts` | via your image build |

Typical offline rebuild after editing files in the GSI image:
```sh
python3 ext4_rewrite_small.py gsi.img /system/bin/phh-on-boot.sh my-on-boot.sh
e2fsck -fn gsi.img
python3 build_super.py factory-super.img gsi.img super-new.img
python3 validate_super.py super-new.img factory-super.img gsi.img
FORCE_RAW=1 python3 mksparse.py super-new.img pieces/super 33554432
python3 validate_pieces.py 2147483648 super-new.img pieces/super.*.simg
# flash only the pieces that differ from what's on the device, then verify sha256(/dev/block/by-name/super) after boot
```
Keep your factory dumps, built images and pieces in the ignored `backups/` folder.
