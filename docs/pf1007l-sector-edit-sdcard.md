# PF1007L April firmware: root ADB with a one-sector edit from the SD card

This route gives root ADB over USB on the April `20260410` firmware. It writes **one 512-byte
sector** of the eMMC from an SD-booted U-Boot: the line in `/system/build.prop` that turns ADB off.
It needs an SD card, but no FEL, no USB data during the write and no boot image patch. The boot
partition is not touched.

Unit D (#13) was rooted with the same edit through Route U, with a script that was not published.
This page publishes the scripts used on one more unit, with a check-only run first. Everything
below was done on one unit on 2026-10-12, from macOS (Apple silicon). Follow the
[repository rules](../README.md#rules-we-learned-the-hard-way) and read
[aimor-remote-root-shell.md](aimor-remote-root-shell.md) first.

## 1. Applicability

| Item | Tested value |
| --- | --- |
| Firmware | `YHK.F-null-A33-1001-D1024-PF1007L-321-OS-AIMOR.0.20260410`, AiMOR 6.0.78 |
| Boot image SHA-256 (sector 172032, 31,028 sectors) | `8ffc2a7d95972422b97ecf7e82da7002011bdacedcbfcc74dd52ae871b98a24e` |
| eMMC | `016G92`, manufacturer `0x11`, 30,777,344 sectors |
| Sector 399221 SHA-256 | `f78d2d4e3924d752a5fdcca7722a4fa76aeff700ce09fd6076d5dea064e2a9c4` |

The sector must hold exactly the stock text. The check-only run (section 4) reads it and refuses on
any difference. On other firmware the sector is different: the May report
([pf1007l-macos-20260529-report.md](pf1007l-macos-20260529-report.md)) did not match it.

Some April units override the setting from `/data/property/persist.sys.usb.config`
([start page](pf1007l-start-here.md#known-firmware-and-units)). An AiMOR factory reset clears
`/data/property`, and this unit had just been reset, so it held no override. If ADB does not appear
after the write, see section 7.

## 2. What it changes

| | |
| --- | --- |
| Sector | eMMC sector 399221 (`0x61775`), inside `system` (p7). It is 512 bytes of `/system/build.prop` text |
| Change | 12 bytes. `persist.sys.usb.config=mass_storage` becomes `persist.sys.usb.config=adb` plus a `#padding` line, so the file length stays the same. `ro.adb.secure=0` is already set, so ADB needs no approval prompt |
| Result | `1f3a:1001`, `adb -d shell id` → `uid=0(root)` |
| eMMC traffic | About 1.5 KB, within a second of power-on |

ext4 has no checksum on file data, and the file length does not change, so the file system stays
consistent.

## 3. Build the scripts

`scripts/a33-sdboot/make-sector-scripts.py` writes the two sector files and three U-Boot scripts to
the ignored `diagnostics/a33-sector/`. The stock sector is embedded in the script and pinned by
SHA-256. The edited sector is derived from it and also pinned.

| Script | eMMC writes | Does |
| --- | --- | --- |
| `check/` | none | Reads the sector, saves it to the card as `sector-before-check.bin`, and reports whether it is the stock sector |
| `apply/` | one `mmc write` of 1 sector | Writes the edited sector, guarded (see below) |
| `restore/` | one `mmc write` of 1 sector | Writes the stock sector back, with the same guards |

Guards in `apply` and `restore`, in order, from
[`sector-write.cmd.in`](../scripts/a33-sdboot/sector-write.cmd.in):

1. Both files on the card are exactly 512 bytes with the expected SHA-256.
2. The eMMC sector hashes to the expected current contents. If it already holds the target, nothing
   is written (`ALREADY_APPLIED_NO_WRITE`). Anything else is refused (`REFUSED_SECTOR_NOT_EXPECTED`).
3. The current sector is saved to the card before the write.
4. After the write, the sector is read back and must match by SHA-256 and byte compare.

Compile with the `mkimage` from the Route S U-Boot build (`diagnostics/a33-sdboot/build/tools/mkimage`,
a Linux binary):

```sh
# Linux or WSL
python3 -I scripts/a33-sdboot/make-sector-scripts.py --mkimage diagnostics/a33-sdboot/build/tools/mkimage

# macOS: generate, then compile in the Route S build container
python3 -I scripts/a33-sdboot/make-sector-scripts.py
for m in check apply restore; do
  docker run --rm --network none \
    --mount type=bind,src="$PWD/diagnostics/a33-sdboot/build/tools/mkimage",dst=/mkimage,readonly \
    --mount type=bind,src="$PWD/diagnostics/a33-sector/$m",dst=/w \
    --entrypoint /mkimage <route-s-build-image> -q -A arm -T script -C none \
    -n "a33 sector $m" -d /w/sector-write.cmd /w/a33.scr
done
```

`<route-s-build-image>` is the Docker image that built Route S's U-Boot. On this unit it was the
image from the macOS card helpers in #14 (`frame-a33-sdboot-build` at the time).

## 4. Check-only run (no eMMC write)

1. Prepare a Route S card: U-Boot in the card's boot area and a FAT32 partition. On Windows use
   `fel-sdcard.py` ([SD card guide](allwinner-a33-sdcard-adb-wifi.md)). On macOS this unit used an
   earlier version of the card helpers in #14.
   This unit's card had U-Boot rebuilt with the eMMC at **4-bit, 26 MHz** (two lines in
   `sun8i-a33-sinlinx-sina33.dts`: `bus-width = <4>;` and `max-frequency = <26000000>;`, see
   [U-Boot settings](pf1007l-start-here.md#u-boot-settings-that-fixed-ums-problems)). The sector
   scripts were not tried with the default 8-bit build.
2. On the card's FAT partition, replace `a33.scr` with `check/a33.scr`, and add `sector-orig.bin` and
   `sector-adb.bin`.
3. Card into the **unplugged** frame. Power it for one to two minutes. The screen stays black.
4. Card back to the computer. Read `a33-sector-status.txt` (NUL-terminated `key=value` lines).

**Pass:** `result=CHECK_OK_SECTOR_IS_ORIGINAL_NO_WRITE`, and `sector-before-check.bin` is
byte-identical to `sector-orig.bin`. Keep a copy of `sector-before-check.bin` with your backups.

Anything else: stop. Do not run `apply`.

## 5. Apply (owner approval for this write)

1. Replace `a33.scr` on the card with `apply/a33.scr`.
2. Card into the unplugged frame. Power it for about a minute.
3. **Unplug, then remove the card.** With the card in, the frame boots U-Boot, not Android.
4. Read `a33-sector-status.txt` on the computer.

**Pass:** `result=OK_WRITTEN_AND_VERIFIED`, `h_before` = `f78d2d4e…`, `h_after` = `27907679…`.
`sector-after-apply.bin` must equal `sector-adb.bin`.

Then connect the frame with a USB-A to USB-C data cable and boot Android:

```sh
adb -d shell id                              # uid=0(root)
adb -d shell getprop persist.sys.usb.config  # adb
```

On this unit: `1f3a:1001` about 20 s after power-on, `uid=0(root)`, no prompt. Continue with
[T8](pf1007l-start-here.md#t8-lock-it-down-before-the-frame-stays-online) **before** the frame goes
on Wi-Fi, then take a full backup over ADB (section 8).

## 6. Undo

Same as section 5 with `restore/a33.scr`. It refuses unless the sector holds the edited bytes.

## 7. If ADB does not appear

- `getprop persist.sys.usb.config` shows `mass_storage`: `/data/property` overrides `build.prop`
  on this unit. The sector edit did not fail. That case needs a different route, see
  [the start page](pf1007l-start-here.md#test-sequence).
- The frame does not boot: the card is still in it, or the sector is not what the status file says.
  Run `check` again and report the result.

## 8. Why only one sector: U-Boot's eMMC access on this unit

Before this route, the full Route S dump was tried four times. U-Boot read the eMMC correctly for a
while, then **every read failed until the next power cycle**. U-Boot itself kept running and kept
writing status files to the SD card.

| Run | U-Boot eMMC setting | Result |
| --- | --- | --- |
| 1–3 | 8-bit (Route S default) | Stopped after 0 to 2 good chunks (`FAIL first read`). Chunks that did read were identical across runs |
| 4 | **4-bit at 26 MHz** | Chunks 00–02 read, chunk 03 failed |
| 5 | 4-bit at 26 MHz, 8 attempts per chunk, `mmc rescan` between attempts | Chunks 00–02 read (one retry), chunk 03 failed all 8 attempts |
| 6 | 4-bit at 26 MHz, 1 MiB reads, 4 attempts each, continue past failures | The first 18 MiB read, then **all** of the next 238 MiB failed (the run was stopped there) |

Successful reads were always correct (two reads compared, and chunks matched across runs and
against the reads in section 9). So the failure is not a bad area of the eMMC: after some time the
eMMC stops answering U-Boot, and `mmc rescan` does not bring it back. The stock Android kernel reads
the same eMMC without errors. The power supply during these runs was not recorded.

This is the [U-Boot settings](pf1007l-start-here.md#u-boot-settings-that-fixed-ums-problems) problem
again, but here 4-bit at 26 MHz and read retries were **not** enough. A one-sector edit needs about
1.5 KB of eMMC traffic in the first second, which every run so far managed. Bulk reads are better
done afterwards over root ADB.

**Full backup over root ADB:** `adb -d exec-out 'dd if=/dev/block/mmcblk0 bs=1048576'` read
15,758,000,128 bytes at about 8 MiB/s (about 30 minutes). A second whole-disk pass will **not**
match on a running frame: `/data` (`UDISK`), `cache`, `alog` and the FAT `bootloader` partition are
mounted read-write. Compare per partition instead. Hash each fixed region on the frame
(`/sbin/busybox dd … | /sbin/busybox sha256sum`) and the same range of the image on the computer.
On this unit every fixed region matched: the first 36 MiB, `env`, `boot`, `system`, `misc`,
`recovery`, `metadata`, `private`, `frp`, `empty`, `media_data`. `mmcblk0boot0` and `mmcblk0boot1`
(4 MiB each) matched over two reads.

## 9. Stock recovery runs root ADB during a factory reset

The same window appears on May `20260519` and `20260529`, and the boot patch has been written in it
([recovery boot write](pf1007l-macos-20260529-recovery-boot-write.md)).

On this unit, AiMOR's factory reset reboots into stock Android recovery to wipe `/data`. For about
13 to 20 seconds, recovery runs ADB **as root, with no authorization**. Seen on three resets.

To reach it: hold the reset pin while connecting power. AiMOR's own "Recovery Mode" screen opens (an
app screen: Backup, Restore, Clear user data, Reset network, Factory reset). Choose Factory reset.
After one reset, AiMOR asks you to finish setup before it offers a factory reset again.

| | |
| --- | --- |
| USB ID | `18d1:d001`; `adb devices` shows `recovery` |
| Recovery `default.prop` | `ro.secure=0`, `ro.adb.secure=0`, `ro.debuggable=1`, `persist.sys.usb.config=adb` |
| Shell | **None.** `adb shell` fails: `exec '/system/bin/sh' failed`, because `/system` is not mounted |
| File transfer | **Works, as root.** `adb ls`, and `adb pull` of `/dev/block/by-name/*` |
| `/cache/recovery/command` | `--wipe_data`, `--locale=en` |

In one window this unit pulled `boot`, `env`, `misc`, `recovery` and `bootloader` (16 to 32 MiB each,
6 to 11 MB/s). Start the pulls before the reset, for example with `adb wait-for-usb-recovery`
followed by `adb -d pull /dev/block/by-name/boot boot.img`. The boot image hash from this copy
matched the later full backup and #17. So it is a way to run
[T6](pf1007l-start-here.md#t6-compatibility-gate-is-your-boot-image-the-tested-one) with no SD
card. It erases the frame's user data.

**Security:** anyone with a data cable and access to the frame's menu can read eMMC partitions as
root during a factory reset. `adb push` is also available in that window. Writing through it was not tried: the reboot can come at any moment.

## 10. Other observations from this unit

- **Power-on `1f3a:efe8` window.** For 3 to 4 seconds at every power-on, with or without the reset
  pin. `sunxi-fel version` always failed: `usb_bulk_recv() ERROR -1: Input/Output Error` (more than
  15 boots). It is not the Boot ROM's FEL. Unit A saw the same.
- **T3b with no internet:** the frame and the computer on a phone hotspot with mobile data off.
  AiMOR showed "Server connection lost". Port 5555 was refused. Useful when the router cannot block
  TCP 7806.
- **Bluetooth: not usable.** No `com.android.bluetooth`, no Bluetooth HAL, no Bluetooth driver loaded
  (only `aic8800_fdrv` for Wi-Fi), no Bluetooth rfkill. Android still lists the feature.
- **USB audio: not supported.** No `snd-usb-audio` module, built in or loadable. A USB microphone
  will not work even in host mode. The A33 codec has a capture channel, and the audio policy lists a
  built-in mic. Whether a mic is fitted was not checked.
- **macOS:** the frame needed an A-to-C data cable through a C-to-A adapter. A C-to-C cable gave no
  power, and the first A-to-C cable carried no data. `system_profiler SPUSBDataType` printed
  nothing on macOS 26. `SPUSBHostDataType` worked.

## Report

```text
About model / firmware: PF1007L / YHK.F-null-A33-1001-D1024-PF1007L-321-OS-AIMOR.0.20260410
AiMOR version: 6.0.78
Ports (DC jack, or USB-C only): USB-C only
Cable and port that gave USB data (or none): USB-A to USB-C data cable through a USB-C-to-A adapter (macOS). C-to-C: no power
T3 USB IDs seen / adb devices output: 1f3a:efe8 for 3-4 s at power-on, then 1f3a:1000; adb empty
T3b network ADB result (port 5555): refused (phone hotspot, no internet)
T4 sunxi-fel version output (or skipped): power-on efe8 window: usb_bulk_recv() ERROR -1. Stub card not used
T5 check-dump stage / chunks (or skipped): never completed; eMMC stops answering U-Boot (section 8)
eMMC size in sectors: 30,777,344 (016G92, manfid 0x11)
Boot partition start sector: 172032
Boot image SHA-256 (sector 172032, 31,028 sectors): 8ffc2a7d95972422b97ecf7e82da7002011bdacedcbfcc74dd52ae871b98a24e
Route used and result: one-sector build.prop edit from the SD card (this page): OK_WRITTEN_AND_VERIFIED, root ADB over USB
Host OS: macOS 26, Apple silicon
First failed step and its exact output: T5: st_00=FAIL first read (8-bit); st_03=FAIL first read after 8 attempts (4-bit, 26 MHz)
```
