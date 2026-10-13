# PF1007L January firmware: USB root ADB from Windows with a one-sector edit

One USB-C-only PF1007L running the January 2026 firmware reached persistent
**USB root ADB** on 2026-10-12. The working change was one 512-byte sector in
`/system/build.prop`, changing `persist.sys.usb.config=mass_storage` to `adb`.
The original boot image remained byte-for-byte unchanged.

This complements [PR #49](https://github.com/wesbos/photo-frame-dashboard/pull/49),
which proposes sector-edit scripts for an April unit using an SD-booted
U-Boot. This January unit had the **same original setting-sector hash**, but used
native Windows FEL transport and a RAM-only U-Boot. It is another unit report,
not evidence that a fixed sector is safe on every PF1007L.

Start with [the PF1007L checks](pf1007l-start-here.md) and follow the
[backup, approval, and privacy rules](../README.md#rules-we-learned-the-hard-way).
Verify your own partition layout and original bytes before considering a write.
The machine-specific helpers and firmware captures from this session are not
included in this report.

## Unit and host

| Item | Observed value |
| --- | --- |
| About model | PF1007L, owner-reported 10.1-inch frame |
| Firmware | `YHK.F-null-A33-1001-D1024-PF1007L-321-OS-AIMOR.0.20260113` |
| AiMOR | 6.0.78 |
| SoC | Allwinner A33; FEL reported `soc=00001667(A33)` |
| Android model / hardware | `AEEZO` / `sun8i` |
| Android / ABI | 6.0.1, SDK 23 / `armeabi-v7a` |
| Display | `wm size` reported 1280×800 |
| RAM | Approximately 1 GB visible to Android |
| Ports | USB-C only for power/data, TF/microSD slot, reset pinhole |
| Working connection | USB-A to USB-C data cable, direct rear motherboard USB-A port |
| Host | Windows 11, Ubuntu under WSL 2; Windows owned the USB connection |
| Host tools | Android platform-tools 37.0.1; native Windows Python 3.13 |
| eMMC | 30,777,344 sectors of 512 bytes: **15,758,000,128 bytes** |
| Boot / system / recovery starts | 172032 / 237568 / 2400256, in sectors |
| Original boot image | 31,028 sectors, 15,886,336 bytes |
| Original boot SHA-256 | `d71c313ddaa4693948acb20af7740ccb56c88bf9376746a47fce2d00c14fc6a4` |

The case was not opened. PCB markings, the physical DRAM/eMMC chip markings,
and USB-C electrical wiring were not inspected. AiMOR is the software name;
this report does not establish a retail manufacturer from the Android model.

## What failed before the working route

| Attempt | Result on this unit |
| --- | --- |
| USB-C to USB-C | No power; the A-to-C data cable worked |
| Stock USB | `1f3a:1000`, mass storage; no ADB device |
| Network ADB / vendor-connection route | No verified ADB session; not a successful no-SD route for this unit |
| Reset and AiMOR's Recovery Mode menu | Exposed vendor backup/reset options, not usable Android recovery/ADB access |
| Test-app dialog and keyboard escape | Reached keyboard preferences; Personal dictionary returned to keyboard settings |
| Route U guarded boot-ramdisk patch | FEL transfer completed, but storage verification failed; later ADB readback proved the boot image was still original |

The [network route](pf1007l-20260410-network-adb.md) was documented for April
firmware. We did not establish that it worked on this January firmware.
Changing router-wide DNS during that investigation was followed by loss of
WSL outbound HTTPS connectivity, while Windows connectivity and DNS resolution
continued to work. The exact cause was not isolated; this is an observed
sequence, not proof that DNS resolution itself was the failure.

Router DNS was restored. WSL connectivity recovered with mirrored networking,
DNS tunneling, and automatic proxy support. The eventual USB unlock required
**no router DNS, routing, or firewall changes**. Keep the vendor-connection
experiment separate from a USB unlock and preserve a working host network.

## Stable FEL and the firmware backup

A prepared **16 GB microSD** provided stable FEL. Its first partition began at
16 MiB, leaving room for the official 8 KiB FEL stub at **byte offset 8192**.
The existing card partitions/files were preserved, and the original prefix
was independently backed up before the boot-gap write. Copying a file to the
Windows drive letter is not equivalent to writing the FEL stub into that gap.

- sunxi-tools source: `d7bbd172a5da601a08f94479de308c6fb714a19a`.
- Official 8192-byte FEL stub SHA-256:
  `2ccec08a026840571f3804671ba72afae840db27112a43f2b1f122075bc808bc`.
- U-Boot: v2025.10, `e50b1e8715011def8aff1588081a2649a2c6cd47`, with the
  [Route U read-only patch](../scripts/a33-uboot/pf1007l-uboot.patch).
- DRAM configuration: 456 MHz, ZQ 15291. The local SPL code ended at `0x457a`,
  below the build script's `0x5e00` limit.

The Windows FEL driver was bound specifically to `1f3a:efe8`. A locally built,
native Windows `sunxi-fel` used the published sunxi-tools sources; USBIP and a
Linux USB attachment were not used. The owner approved the temporary RAM
bootloader and each distinct firmware change.

Initially, the read-only U-Boot exposed the card as UMS LUN 0 and eMMC as LUN 1.
Both read-only protections were retained: UMS refused host writes and advertised
write protection. Native U-Boot `mmc write` remained available to the separately
reviewed flash script.

The verified backup covered **the first 2 GiB**, including the complete boot,
system, and recovery images. Each 128 MiB segment was read twice through separate,
uncached Windows handles, checked for `0xCC` filler, and verified after saving.
The complete saved prefix was hashed, compressed, and verified by decompressing
it. Copies were retained on two host drives.
It is not a full-device backup, so it does not meet the repository's
[backup rule](../README.md#rules-we-learned-the-hard-way).

This was an owner-approved **firmware-prefix backup**, not a full-device backup:
userdata, the remaining eMMC, and separate hardware boot areas were not captured.
The owner accepted that scope for the newly reset frame. Do not describe it as a
full eMMC backup or silently substitute it for another owner's backup requirement.
All captures and device credentials remain private.

### Windows and U-Boot read failures

Several different problems appeared, and should not be treated as one diagnosis:

- Windows console text selection paused the original visible backup process.
  Redirecting the reader's output to files avoided that host-side pause.
- The raw disk number changed when U-Boot exposed only the eMMC. Re-identify the
  LUN, capacity, and USB device after every reload; never reuse a drive number blindly.
- Use the raw length reported by `IOCTL_DISK_GET_LENGTH_INFO`. A geometry-derived
  WMI size is not a reliable exact byte count, and `Get-Disk` did not reliably list
  this eMMC with its out-of-range UDISK partition entry.
- Later UMS reads failed with Windows error 433, and the USB gadget disappeared.
  Windows also logged controller/read errors on the exposed card disk.
- A temporary START STOP handler correction did not provide a stable reader in
  this session. That does not disprove [the separately tested macOS fix](pf1007l-macos-20260529-report.md#ums-disappeared-after-about-30-seconds).
- Internal U-Boot checks also failed **before** Windows read the exported disk.
  Small reads, a 4-bit/26 MHz build, and rescans/retries still failed during bulk
  boot-image verification. Therefore the remaining failure was not established
  as merely a Windows driver or disk-eject issue.

The later bulk-read failures do not invalidate the already independently verified
backup, but they prevented claiming a successful boot-ramdisk write. An upload
completion message and USB enumeration were insufficient evidence of a flash result.
[PR #49](https://github.com/wesbos/photo-frame-dashboard/pull/49) records a similar
limit on another larger-eMMC unit. [Issue #61](https://github.com/wesbos/photo-frame-dashboard/issues/61)
reports a successful January Route S dump/write at 12 MHz, and
[PR #62](https://github.com/wesbos/photo-frame-dashboard/pull/62) reports that clock
on May firmware. The 12 MHz workaround was **not tested here**.

## The one-sector change that worked

The verified system image was clean ext4: 4096-byte blocks, no pending journal
recovery. Read-only `debugfs` inspection found `/build.prop` at inode 355, data
block 20206, size 3533 bytes. The USB property began at file byte 2807.

The physical setting sector was derived from that file mapping:

```text
system start + file block × sectors per block + file offset / 512
237568       + 20206 × 8                    + floor(2807 / 512) = 399221
```

That sector's original SHA-256 exactly matched the stock sector in PR #49:

| Sector 399221, 512 bytes | SHA-256 |
| --- | --- |
| Original | `f78d2d4e3924d752a5fdcca7722a4fa76aeff700ce09fd6076d5dea064e2a9c4` |
| This session's edited sector | `3e0b232ceeb0600a5710bc5ac1c98d483bfa8ace66e189c5451a15c00179afe4` |

Only `mass_storage` was replaced with `adb` plus nine trailing spaces. The
property parser trims those spaces; file length, inode metadata, and every other
sector remained unchanged in the locally reparsed filesystem copy. Matching a
boot image alone would not have justified using this setting sector.

The owner approved this **additional 512-byte `/system` write** after the failed
boot-patch attempt. Original/new sector files and a guarded restore script were
retained with the backup. The restore script was prepared, not executed.

The successful RAM-only U-Boot retained read-only UMS, used a 4-bit eMMC bus with
`max-frequency = <26000000>`, and enabled `CONFIG_CMD_HASH=y` and
`CONFIG_HASH_VERIFY=y`. The script loaded original/new payloads at `0x44000000`
and `0x44001000`, with a readback buffer at `0x44002000`:

1. Verify both 512-byte RAM payloads against their expected SHA-256 values.
2. Select the verified eMMC and read sector 399221.
3. Compare the current sector byte-for-byte with the original backup; refuse on
   mismatch.
4. Write **one sector** from the edited payload.
5. Read that sector back, compare every byte, and calculate its SHA-256.
6. Report the digest in a temporary USB result descriptor with a fresh session
   marker, then expose only eMMC as read-only UMS.

This let Windows observe the actual device-side readback result without another
bulk UMS read. The descriptor was changed in RAM only; no `saveenv` was used.
The returned digest was the edited-sector hash above. This was a storage
readback check, not an inference from a successful FEL upload.

To undo this particular write, the retained restore script reverses the payloads:
it requires the current sector to match the edited bytes, writes the original
512 bytes, and requires the readback to match the original `f78d2d4e…` digest.
Keep the verified backup and FEL card available: returning to `mass_storage`
can remove USB ADB on the next normal boot. This undo procedure was **not tested**.

## Verification after Android boot

Power was disconnected, the FEL microSD was removed, and Android was booted again
over the A-to-C data cable. Keeping the FEL card inserted would have returned the
frame to a black FEL screen instead of Android.

- USB changed from `1f3a:1000` to **`1f3a:1001`**, ADB only.
- Windows bound the final interface to WinUSB without a separate ADB driver
  installation on this PC.
- `adb shell id` returned **`uid=0(root)`** directly, without `adb root` or `su`.
- Both `sys.usb.config` and `persist.sys.usb.config` returned `adb`.
- Service and persistent ADB TCP-port properties were unset; the verified access
  was over USB, not Wi-Fi.
- Android's own storage driver returned exactly 15,886,336 bytes for the boot
  image. Its SHA-256 still matched `d71c313d…`, proving the earlier boot patch had
  **not applied**.
- A separate ADB read of the setting sector returned the edited hash, proving the
  setting persisted after the power cycle.

Old `adbd` merged the remote `dd` statistics into binary `exec-out` output on the
first attempt. Suppress remote stderr and validate byte counts before hashing:

```sh
# On a host shell that preserves binary output. On Windows use a binary-aware
# subprocess/file API, not Windows PowerShell 5.1 text redirection.
adb -s <frame-serial> exec-out 'dd if=/dev/block/by-name/boot bs=512 count=31028 2>/dev/null' > boot-current.bin
```

The initial read had an extra 100-byte `dd` status footer and was rejected. With
`2>/dev/null`, exact lengths and hashes matched. This is a transport/output-format
issue, not evidence of firmware corruption.

AiMOR remained the visible Home app after root access was obtained. Unlocking ADB
does not install a new launcher or dashboard. Those are separate setup steps.

## Dashboard proof of concept after unlocking

Wes's [hosted demo](https://home-dashboard.wesbos.workers.dev/) rendered at
1280×800 in Firefox, including working touch navigation to the Calendar page.
Adding it to Home as **Home HQ** opened the manifest's fullscreen view without
browser chrome. This uses the demo's sample data, not connected personal calendars.

The installed ARMv7 Firefox 143.0.4 APK came from
[Mozilla's release archive](https://archive.mozilla.org/pub/fenix/releases/143.0.4/android/fenix-143.0.4-android-armeabi-v7a/fenix-143.0.4.multi.android-armeabi-v7a.apk),
SHA-256 `af560738627d4efc9ace75e708fc48aad6a24c78ef43a89daca27e16ff3829f8`.
The launcher was Rootless Pixel Launcher 3.9.1 from
[F-Droid](https://f-droid.org/repo/amirz.rootless.nexuslauncher_30911.apk),
SHA-256 `7fa44d560dc4577374d45176220de2c0b00a71e09d6d148cdea4e0a52d38404a`.

The stock WebView 44 was left unchanged; Firefox supplied its own browser engine.
AiMOR remained installed and enabled. Opening Android Settings and returning to
the launcher and Home HQ were verified before leaving the demo on screen. This
was a browser proof of concept, not a completed automatic-start kiosk setup.

## PF1007L report summary

```text
About model / firmware: PF1007L / YHK.F-null-A33-1001-D1024-PF1007L-321-OS-AIMOR.0.20260113
AiMOR version: 6.0.78
Ports: USB-C only, TF/microSD, reset pinhole
Cable / port: USB-A to USB-C data cable, direct motherboard USB-A
Stock USB / network ADB: USB mass storage only; no verified network ADB
FEL: 1f3a:efe8; soc=00001667(A33); stable with prepared microSD
Backup: owner-approved first 2 GiB firmware prefix; two uncached reads, saved-image and gzip readback verified
eMMC: 30,777,344 sectors / 15,758,000,128 bytes
Boot: sector 172032, 31,028 sectors; original SHA-256 d71c313d… unchanged after unlock
Working route: native Windows FEL -> RAM-only read-only U-Boot -> guarded 512-byte build.prop edit
Result: USB 1f3a:1001; uid=0(root); USB property and setting-sector readback verified after power cycle
Host: Windows 11 + Ubuntu WSL 2; native Windows USB tools
First failed write-route verification: UMS disappeared / WinError 433; later internal bulk reads also failed
Undo: original setting sector and guarded restore script retained; restore not tested
```
