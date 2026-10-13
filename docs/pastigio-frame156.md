# Pastigio 15.6" Frameo frame (`FRAME156`, RK3326, Android 8.1)

Original record of one unit, started 2026-10-09, with an [additional macOS unit report](#additional-unit-tested-on-macos-2026-10-12) below. Observations are kept separate from guesses. Unique
identifiers (serial, MAC, IP) are left out; they live in the ignored `backups/` and `diagnostics/` folders.

## Observations (read-only unless noted)

### Identity

| | |
| --- | --- |
| Brand / model | `Pastigio` / `FRAME156` (`ro.product.device=FRAME156`) |
| Firmware | `FrameO.DP105F.v2026010414`, built 2026-01-04 |
| Fingerprint | `rockchip/rk3326_32bit/rk3326_32bit:8.1.0/OC/145229:user/release-keys` |
| SoC | Rockchip RK3326 (`ro.board.platform=rk3326`), ARMv8 cores with a 32-bit userspace (`armeabi-v7a`) |
| Android | 8.1.0, API 27, security patch 2020-11-05 |
| Display | 1920x1080, 170 dpi |
| RAM / storage | about 1 GB RAM, 29 GB eMMC (`mmcblk2`), userdata 26 GB |
| WebView | `com.android.webview` 106.0.5249.126 (already current for this repo's Vite target) |
| Boot | verified boot `unsupported`, `ro.boot.flash.locked=1`, SELinux **permissive** on the kernel command line, `veritymode=enforcing` |
| Wi-Fi | onboard radio works (`wlan0`) |

USB: the stock "Enable transfer from computer" setting makes the frame enumerate as
`FRAME156` (WinUSB) and then as an Android Open Accessory device (`18D1:2D00`). That is Frameo's
photo-transfer mode, **not ADB**. ADB shows up (`18D1:0006`, product `FRAME156`) only after
Frameo **Settings -> About -> Beta -> ADB Access** is enabled and "transfer from computer" is off.

### Root

`adb shell su -c id` returns `uid=0(root)` immediately, with no prompt and no manager app. `/system/xbin/su` exists
(75 KB, owner root). `adb shell` itself is uid 2000. **Any app on the frame can probably get root without asking.**

### Software of interest

| Package | Location | Notes |
| --- | --- | --- |
| `net.frameo.frame` v1.29.13 | `/system/priv-app/DP_Frameo` | The slideshow app and the **HOME** activity. System app, cloud connected. |
| `com.muxintu.app.mxota` v1.2.5 | `/system/app/MXOTA` | Vendor OTA updater with `INTERNET`. Disable before going online. |
| `com.szclink.app.cldevicetest` | `/system/app/DP105DeviceTestSM` | Factory test app. |
| `com.android.launcher3` | system | Stock launcher, disabled-by-default state not recorded. |

No browser installed.

### Partition table (eMMC `mmcblk2`, 512-byte sectors)

| Partition | Name | Start | Size (sectors) |
| --- | --- | --- | --- |
| p1 | uboot | 16384 | 8192 |
| p2 | trust | 24576 | 8192 |
| p3 | misc | 32768 | 8192 |
| p4 | resource | 40960 | 32768 |
| p5 | kernel | 73728 | 65536 |
| p6 | boot | 139264 | 77824 |
| p7 | recovery | 217088 | 143360 |
| p8 | backup | 360448 | 229376 |
| p9 | security | 589824 | 8192 |
| p10 | cache | 598016 | 786432 |
| p11 | system | 1384448 | 3145728 |
| p12 | metadata | 4530176 | 32768 |
| p13 | vendor | 4562944 | 786432 |
| p14 | oem | 5349376 | 262144 |
| p15 | frp | 5611520 | 1024 |
| p16 | userdata | 5612544 | 55450560 |

## Backup (2026-10-09, verified)

`backups/<serial>/emmc-0-5612544.img.gz` (ignored by git): eMMC sectors 0-5,612,544, everything before `userdata`,
2,873,622,528 bytes raw, 605.7 MB gzipped. The SHA-256 of the raw stream equals the gzip readback hash.
No 1 MiB block is entirely `0xCC`. Independent re-reads match the backup for `uboot`, `trust`, `misc`, `resource`,
`kernel`, `boot`, `recovery`, `security`, `backup`, `system` (all 1.5 GiB), `vendor`, `metadata` and `frp`.
`oem` (mounted read-only at `/oem`) differs in one byte: byte 43 of the ext4 journal header page at
partition offset `0x17000` is `0x02` now and `0x00` in the backup. That fits a journal flag the kernel sets at mount time, but
it is a guess; fresh reads of `oem` are identical to each other. `cache` and `userdata` are not in the backup.
`mmcblk2boot0/1`, `rpmb` and `userdata` were not backed up.

Two traps on this setup, both seen in practice:

- **`adb exec-out "su -c ..."` turns every LF byte into CR LF**, so a raw `dd` stream is longer than the partition and
  its hash is wrong. `stty -onlcr` and `dd of=/proc/self/fd/1` do not fix it. Piping through `base64` on the frame and
  `tr -d '\r' | base64 -d` on the PC gives byte-exact data. This was the first backup attempt's failure
  (2,879,386,296 bytes against 2,873,622,528 expected).
- **`dd` on the whole-disk node `/dev/block/mmcblk2` cannot seek past 2 GiB** (`Invalid argument`, 32-bit userspace),
  so re-reading `vendor` or `oem` by sector offset returns nothing. Read the partition node (`mmcblk2p13`) instead.
  A sequential read from sector 0 (as the backup does) is fine.

Restore would need Rockchip loader mode and `rkdeveloptool`; neither has been tried on this unit.

## Status against the README phase map

| Phase | State |
| --- | --- |
| 1 Identify | Done. Not a BIUFRAME or Skylight, so neither device guide applies as written. |
| 2 ADB | Done, via the Frameo beta menu. |
| 3 Loader mode | Not needed so far. Not tested. |
| 4 Back up | Done and verified (see Backup). Restore path untested. |
| 5 Root | Shipped `su` works. |
| 6 Make it useful | Done: kiosk installed and set as the Home app (see Changes made). The kiosk in this repo has no HOME intent filter; that was a local change, not included. |
| 7 Networking | Onboard Wi-Fi works. |
| 8 Vendor updates | Pending: disable `com.muxintu.app.mxota` before relying on the frame. |
| 9 Security hand-off | Pending. |

## Guesses (unverified)

- Whether `/system` can be remounted read-write the way the BIUFRAME steps assume, given `veritymode=enforcing`.
- Whether Frameo re-launches itself over a third-party HOME or kiosk app.
- Whether Frameo's cloud or the OTA app can replace system files on their own.

## Host note

This host also runs SuperDisplay, whose bundled ADB v40 fights the current platform-tools
server (v41) for the device. Stop its service while working on the frame.

## Changes made to the frame (2026-10-09 to 10-10)

All reversible; nothing under `/system` or any flash partition was written after the verified backup.

| Change | How | Undo |
| --- | --- | --- |
| Vendor OTA app off | `pm disable-user --user 0 com.muxintu.app.mxota` | `pm enable com.muxintu.app.mxota` |
| Frameo off | `pm disable-user --user 0 net.frameo.frame` | `pm enable net.frameo.frame` (its data is untouched) |
| Kiosk installed | `adb install -r dashboard/kiosk/build/homehq.apk` (`com.wesbos.homehq`) | `adb uninstall com.wesbos.homehq` |

Verified after a reboot: boots into the kiosk (set as the home app), `sys.boot_completed=1`, ADB returns, Frameo and the OTA app are not running.

### Motion sensor

A `pir-s18` node exists in the device tree with `status = "disabled"`; no driver is bound. Reading pin 17 of each GPIO
bank (17, 49, 81, 113) for 45 s while someone moved in front of the frame showed no changes, so no working PIR was
found; this does not rule out a fitted but unpowered sensor. Not pursued further for now.

### Security notes for the owner

- `su` gives root with no prompt and no manager app, so any app installed on this frame can take root. Install nothing untrusted.
- Android 8.1 with a 2020-11 security patch; SELinux is permissive. Keep the frame on a guest or IoT network.
- Management was done over USB ADB. Network ADB (5555) was also found open on the Wi-Fi address on 2026-10-10; how it was enabled was not recorded. Until it is closed, anything on the network can reach ADB, so keep the frame on an isolated network.

## Additional unit tested on macOS (2026-10-12)

Another owner's `FRAME156` matched the firmware, RK3326, Android 8.1/API 27, security patch,
1920x1080 display at 170 dpi, WebView 106 and partition table above. The host ran macOS 26.6.2.
These observations apply to this unit; the cause of the host USB behavior remains unproven.

| Additional observation | Value |
| --- | --- |
| ADB USB vendor/product | `2211:0006`, product/model `FRAME156` |
| Frameo updated system app | `v1.32.12_-_OTA_test` under `/data/app`; original system APK `v1.29.13` |
| Stock launcher | `com.android.launcher3` was already disabled before kiosk installation |
| Root and SELinux | Shipped `su` returned uid 0 without a manager prompt; ordinary shell was uid 2000; `getenforce` reported `Permissive` |
| Boot properties | `ro.boot.veritymode=enforcing`, `ro.boot.flash.locked=1` |
| eMMC size | `/dev/block/mmcblk2`, 31,264,342,016 bytes |

### ADB authorization and reconnecting after a reboot

With Frameo **Settings -> About -> Beta Program -> ADB Access** enabled and computer photo
transfer off, the host initially showed `unauthorized`. Accepting Frameo's own warning, which
linked to `frameo.com/adb_faq`, changed the host status to `device`. The authorization succeeded
without injecting an ADB key or using a loader.

Attempts to enter Rockchip loader mode with the power button did not yield a recognized loader
on this unit. A black display also occurred while ordinary Android ADB was enumerating.
This does not establish that loader mode is impossible, and a black display alone is not proof
of loader entry. The successful FRAME157 procedure in #39 concerns a different model/firmware.

During earlier cable testing, moving the USB adapter to another host port exposed the current
connection state after the host appeared to retain an old USB enumeration. That may be host or
adapter dependent.

After `adb reboot`, the host did not re-enumerate the frame within 150 seconds, although the
owner reported that the kiosk had returned. Disconnecting and reconnecting USB on the frame
side restored ADB. A changed kernel boot ID and `sys.boot_completed=1` confirmed a new boot.
The kiosk was still the default HOME and resumed activity; Frameo and the OTA app remained
disabled. The cause of the USB reconnection behavior was not established.

### Full eMMC and boot-region backup

Captured the complete eMMC through the shipped `su`, compressing the stream on the device and
encoding it in base64 before transport. The method above gave a byte-exact 1 MiB probe with
matching device/host SHA-256. Unencoded `su` newline behavior was not separately retested on
this unit.

The full gzip readback produced exactly 31,264,342,016 bytes, including `cache` and `userdata`.
No complete 1 MiB block consisted of `0xCC` filler. Independent device reads matched the saved
ranges for `uboot`, `trust`, `misc`, `resource`, `kernel`, `boot`, `recovery`, `backup`, `security`,
`system`, `metadata`, `vendor` and `frp`.

`oem` reproduced the one-byte difference described above: partition offset `0x1702b` was `0x00`
in the full capture and `0x02` in the later read. The containing page had the JBD journal
superblock magic `0xc03b3998`. A separate current OEM capture matched two further device reads.
The reason for the change was not proven.

Both 4 MiB `mmcblk2boot0` and `mmcblk2boot1` regions were also captured, each with exact gzip
readback size and two matching device hashes. `rpmb` was not captured.

Android stayed running during the full eMMC capture. `cache` and `userdata` were not compared
against later live reads, so this is **not a transactional filesystem snapshot**. After Frameo
was disabled, its private data, local media directory and installed APK were additionally
archived and the tar was read back successfully. Dumps, APKs and whole-disk hashes stayed private.
Firmware restoration and physical loader entry remain unverified.

### Kiosk startup and dashboard aspect ratio

A separately implemented WebView kiosk with a HOME intent filter loaded the published demo
using the existing WebView and CA store. The HOME component was selected with
`cmd package set-home-activity --user 0 <kiosk-package>/<activity>`. Frameo and
`com.muxintu.app.mxota` were disabled using the `pm disable-user` commands above, preserving
their installed packages and data. The existing undo commands still apply. The kiosk opened
automatically after a reboot. No change to `/system`, `/vendor`, `/oem` or firmware partitions
was needed for installation.

The published demo's fixed 1280x800 stage fitted this 1920x1080 display at 1728x1080, leaving
96-pixel black bars on each side. This was the page layout, rather than an Android window-size
limit. A local kiosk adaptation kept the logical width at 1280, adjusted the logical height to
the screen aspect ratio and compacted the home view's vertical rows, filling 1920x1080 with a
uniform scale. Device screenshots confirmed the result; separate browser tests checked stage
bounds, visible home controls, repeat application and navigation through all seven sections at
1920x1080 and 1280x800. The aspect-ratio change was tested after the reboot/startup check and
is only reported here; this contribution does not change the dashboard implementation.

Motion/PIR support, firmware restoration, other units and other firmware versions were not
tested in this report.

