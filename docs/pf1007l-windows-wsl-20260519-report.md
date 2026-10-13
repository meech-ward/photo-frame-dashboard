# PF1007L on May firmware from Windows + WSL: 12 MHz FEL U-Boot, SD-carried boot patch

One PF1007L unit on `FL-AIMOR-OS.0.20260519`, rooted from a Windows 11 PC with WSL 2. The boot
image matched the one reported in #24, #36 and #62. Like #36, read-only `ums` never held long enough
for a backup. Unlike the reports so far, eMMC reads from the FEL-loaded U-Boot also failed at
**4-bit / 26 MHz**: two guarded write attempts refused, and a read-only diagnostic showed why. At
**8-bit / 12 MHz** the same reads were clean, and the guarded write succeeded.

Host: Windows 11, WSL 2 (Ubuntu, mirrored networking), usbipd-win 5.3.0, sunxi-tools
v1.4.2-208, Docker 29.7.2 for both U-Boot builds, Windows Python 3.14 for the card scripts.

## Report

```text
About model / firmware:   PF1007L; A33-1001-D1024-PF1007L-FL-AIMOR-OS.0.20260519
                          fingerprint AEEZO/astar_m86_8723cs/astar-m86_8723cs:6.0.1/MOB30R/20260519:eng/test-keys
AiMOR version:            6.0.78
Ports (DC jack, or USB-C only): USB-C only, TF slot
Cable and port that gave USB data: USB-A to USB-C data cable through a powered USB hub
T3 USB IDs seen / adb devices output: 1f3a:1000 (mass storage), adb devices empty
T3b network ADB result (port 5555): connection refused; only TCP 8086 open
T4 sunxi-fel version output: 1f3a:efe8; AWUSBFEX soc=00001667(A33) 00000001 ver=0001 44 08 scratchpad=00007e00 00000000 00000000
T5 check-dump stage / chunks: started; chunks 00-01 ok (frame reset during chunk 02, see below)
eMMC size in sectors:     30,777,344 (016G92, manfid 0x11)
Boot partition start sector: 172032 (env 139264, system 237568, recovery 2400256)
Boot image SHA-256 (sector 172032, 31,028 sectors):
                          9a6e2456952f3dc2b99e64ea021321397bdc824364b5c8b42f503f847261630a
Route used and result:    Route U boot patch (boot-patch.py plan), payloads carried on the SD card
                          and loaded by an 8-bit / 12 MHz FEL U-Boot -> 1f3a:1002, adb -d shell id = uid=0(root)
Host OS:                  Windows 11 + WSL 2 (Ubuntu)
First failed step and its exact output: Route U section 4: ums gadget 1f3a:1010 appeared on Windows,
                          then the device became 0000:0002 "device descriptor request failed" (twice)
```

## What happened, in order

| Step | Result |
| --- | --- |
| Route U `ums` with the #24 fixes (4-bit / 26 MHz, read retries, START STOP patch), powered hub | `1f3a:1010` appeared, then dropped to `0000:0002` within seconds. Same as #36 |
| Route S dump with `max-frequency = <12000000>` (8-bit) on the SinA33 tree | Chunks 00 and 01 verified (double read, SHA-256). The frame reset during chunk 02, about a minute after U-Boot started (compare #19). The first 128 MiB holds the MBR, env and the whole boot partition |
| `boot-patch.py` on the 128 MiB image | Passed. Ramdisk slot 4,853,760 bytes at +10,143,744; ranges `[191844, 201324)` and `[172032, 172034)`, the same as #24 and #36 |
| Route U `write-boot.scr` over FEL, 4-bit / 26 MHz U-Boot, payloads uploaded with `sunxi-fel` | No write. Frame booted with `1f3a:1000` |
| SD-carried script (as #62), same U-Boot, status file written to the card | `REFUSED_P6_NOT_ORIGINAL`; header and ramdisk read as neither original nor patched |
| Read-only diagnostic, same U-Boot | `mmc read` of 1 sector (MBR): ok, identical to the backup. 2 sectors (boot header): **FAIL**, but the bytes matched the original. 9,480 sectors (ramdisk slot): **FAIL**, 6,232 bytes differ from the original |
| Same SD-carried script, U-Boot rebuilt with `bus-width = <8>; max-frequency = <12000000>;` | `OK_WRITTEN_AND_VERIFIED`. All reads ok, p6 held the original bytes, ramdisk then header written and read back |
| Boot, card removed | `1f3a:1002`, `uid=0(root)`. The whole p6 read over ADB equals the backup plus exactly the planned payloads |

Observed: the second refusal was caused by **eMMC read errors**, and the guards worked. Not
observed: why the first attempt (payloads over FEL) wrote nothing. It had no status file, so
corrupted FEL uploads (as in #62) cannot be ruled out, but the same read errors explain it, and the
frame booted unchanged. FEL uploads ran at about 100 kB/s. Without a console, a refusal and a read
error look the same from the host; the status file made the difference.

## Changes worth trying first on May `20260519`

- Build the FEL U-Boot with the eMMC at **12 MHz** (8-bit worked here). 26 MHz 4-bit fixed #24, but
  not this unit.
- Have the write script check every `mmc read` result, not only `cmp.b`. Our
  `REFUSED_EMMC_READ_ERROR` check refuses before any write if a read reports an error.
- Write a status file to the SD card's FAT partition (`env export` + `fatwrite`) at each step, and
  record what p6 holds before the write (`crc32 -v` against the original and patched CRCs).
- Put the payloads on the card (as #62). A 3 KB script over FEL is all the USB transfer needed.

## Windows-specific notes

- **WSL needs each USB identity shared separately.** The frame appears as `1f3a:1000`, `1f3a:efe8`
  (FEL), `1f3a:1010` (`ums`) and `1f3a:1002` (root ADB). `usbipd bind --force --hardware-id <id>`
  only works while that identity is connected, so each one is bound the first time it appears, then
  `usbipd attach --wsl --busid <busid>`. FEL was never visible in WSL until `1f3a:efe8` was bound.
- **A group policy can make removable drives read-only.** Here, copying files to the card's FAT
  partition failed with "media is write protected". If that happens, the card steps need a PC
  without that policy, or an exception from whoever manages the PC. Windows may also offer to
  encrypt the frame's `ums` disk; decline.
- `fel-sdcard.py prepare` replaces the FEL stub but refuses any other boot image, so one card
  cannot go from the Route S dump back to FEL. With no second card, we zeroed only our own Route S
  U-Boot (after checking that the boot area held exactly that image), then ran `prepare` for the
  stub. Use a second card if you have one.
- After `usbipd` held the card reader, Windows did not show the card until the reader was
  re-plugged.

## Not done

- No full eMMC backup: system, recovery and userdata were not captured before the write. The patch
  touches only p6, which was backed up in full. This does not meet the repository's
  [backup rule](../README.md#rules-we-learned-the-hard-way); take a full backup if you can.
- The 12 MHz U-Boot was not tried with `ums`.
