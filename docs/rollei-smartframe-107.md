# Rollei Smart Frame WiFi 107 (10.1" Frameo, RK3126, Android 6.0.1)

Record of one unit, bought from [Verkkokauppa.com](https://www.verkkokauppa.com/fi/product/1019555/Rollei-Smart-Frame-WiFi-107-digitaalinen-valokuvakehys-musta)
(Finland, 99.99 €), started 2026-10-13, macOS host. Observations are kept separate from guesses. Unique
identifiers (serial, MAC, IP, the factory ADB key's host name) are left out; they live in the ignored
`backups/` and `diagnostics/` folders.

Same SoC and Android version as the [BIUFRAME](biuframe.md), but a different vendor build (Harmony /
ZhiHeXing, Wi-Fi chip `rk915` instead of `ssv6x5x`). `scripts/biuframe-setup.sh check` refuses this unit
by design.

## Observations (read-only unless noted)

### Identity

| | |
| --- | --- |
| Retail name | Rollei Smart Frame WiFi 107, 10.1" IPS touchscreen, 32 GB (retailer listings) |
| Brand / model | `Rollei` / `Frame` (`ro.product.device=SmartFrameWiFi107`, manufacturer `Harmony`) |
| Firmware | `F6010T_ZhiHeXing_1010-V1.0.1202603121415.release-keys`, built 2026-03-12 |
| Fingerprint | `rockchip/rk312x/rk312x:6.0.1/ZhiHeXing/user.wanghy.20260312.141337:user/release-keys` |
| SoC | Rockchip RK3126 (`ro.board.platform=rk312x`, `ro.hardware=rk30board`), 32-bit (`armeabi-v7a`) |
| Kernel | Linux 3.10.0, built 2026-03-12 |
| Android | 6.0.1, API 23, security patch 2016-07-05, `user` build, `ro.debuggable=0`, `ro.secure=1` |
| SELinux | **Permissive** (`androidboot.selinux=permissive` on the kernel command line) |
| Display | 1280x800, 160 dpi |
| RAM / storage | about 1 GB RAM, 29 GB eMMC (`mmcblk0`), userdata 27 GB |
| WebView | `com.google.android.webview` 107.0.5304.36 in `/system/app/webview`, recent enough for the dashboard |
| Wi-Fi | onboard radio works (`wlan0`), driver module `rk915` |
| SystemUI | `com.android.systemui` is **disabled**: no status or navigation bar |
| Frameo | `net.frameo.frame` v1.32.12 (78070), the HOME app |

### USB and ADB

- A **USB-C to USB-C** cable gave nothing: no USB device on the Mac, no accessory prompt.
- A **USB-A to USB-C** cable worked: `2207:0006`, USB product name `Frame`, ADB only
  (`sys.usb.config=adb`, `persist.sys.usb.config=adb`).
- **ADB is on out of the box.** The owner did not touch Frameo's Beta → ADB Access toggle or any
  Android setting.
- `adb devices` showed the frame as `device` (authorized) straight away. The owner saw no prompt, and
  with SystemUI disabled there is nowhere for one to appear.
- `ro.adb.secure=1`, yet `/data/misc/adb/adb_keys` holds a single key, from a vendor developer's
  laptop (dated 2021), not the Mac's key. No `/adb_keys` in the ramdisk.
- After a reboot, the freshly started `adbd` authorized the Mac again with no prompt, and `adb_keys`
  was unchanged. **USB ADB does not appear to check keys: any computer with a data cable gets a
  shell, and with the shipped `su`, root.**
- No network ADB: nothing listens on 5555; `service.adb.tcp.port` and `persist.adb.tcp.port` are empty.
  Frameo listens on one high TCP port.

### Root

`adb shell su -c id` returns `uid=0(root)` immediately, with no prompt and no manager app.
`/system/xbin/su` (133 KB, owner root, dated 2026-03-12) ships in the firmware. `adb shell` itself is
uid 2000. **Any app on the frame can probably get root without asking.**

### Software of interest

| Package | Location | Notes |
| --- | --- | --- |
| `net.frameo.frame` v1.32.12 | system app, updated in `/data/app` | Slideshow app and HOME activity. Cloud connected. |
| `com.adups.fota` v5.24 | `/system/app/FotaUpdate` | Adups OTA updater, running. Contacts servers in China on the BIUFRAME. |
| `com.adups.fota.sysoper` | system | Adups helper. |
| `android.rockchip.update.service` | system | Rockchip updater, running. |
| `com.cghs.stresstest` | system | Factory stress test, running. |
| `com.DeviceTest` | system | Factory test app. |
| `com.android.browser` | system | Stock AOSP browser. |

No third-party apps.

### Partition table (eMMC `mmcblk0`, 512-byte sectors)

Rockchip `mtdparts` from the kernel command line; eMMC sector = loader sector + 8192.

| Partition | Name | Start | Size (sectors) |
| --- | --- | --- | --- |
| p1 | uboot | 16384 | 8192 |
| p2 | misc | 24576 | 8192 |
| p3 | resource | 32768 | 32768 |
| p4 | kernel | 65536 | 24576 |
| p5 | boot | 90112 | 24576 |
| p6 | recovery | 114688 | 65536 |
| p7 | backup | 180224 | 131072 |
| p8 | cache | 311296 | 262144 |
| p9 | metadata | 573440 | 32768 |
| p10 | kpanic | 606208 | 8192 |
| p11 | system | 614400 | 2097152 |
| p12 | radical_update | 2711552 | 131072 |
| p13 | userdata | 2842624 | 58236928 |

`/system` is mounted read-only; `/cache` and `/data` are read-write.

## Backup (2026-10-13, verified)

`backups/<serial>/emmc-0-2842624.img.gz` (ignored by git): eMMC sectors 0-2,842,624, everything before
`userdata`, 1,455,423,488 bytes raw, 422.8 MB gzipped. Streamed with
`adb exec-out "su -c 'dd if=/dev/block/mmcblk0 bs=512 count=2842624'"` in 230 s. The SHA-256 of the raw
stream equals the gzip readback hash. No 512-byte sector is entirely `0xCC`. Independent re-reads match
the backup for the loader area (sectors 0-16383), `uboot`, `misc`, `resource`, `kernel`, `boot`,
`recovery`, `backup`, `kpanic`, `system` (all 1 GiB) and `radical_update`. `cache` and `metadata` are in
the backup but were not re-read, since they are mounted read-write. `userdata` and `rpmb` were not backed up.

`adb exec-out "su -c ..."` is byte-exact on this unit: no LF to CR LF translation (the
[Pastigio](pastigio-frame156.md#backup-2026-10-09-verified) trap), and the stream had the exact
expected length.

| Image | SHA-256 |
| --- | --- |
| `boot` (p5, `ANDROID!` header) | `f3ed5edeaf0ed5d4c3525afb1d33334584cdb13032c6aa9cdd8c6d04e434d1a2` |
| `recovery` (p6, `ANDROID!` header) | `5c2ff246b1f4d6491d7dae80044981912550b2a5469f17dc094266c62dbc82d6` |
| `kernel` (p4) | `3858d26c7b68f1d927d6585de4c37e9c5df3174e6fed5c8fe700f7998593eb54` |

Hashes cover the whole partition, padding included.

Restore would need Rockchip loader mode and `rkdeveloptool`; neither has been tried on this unit.

## Status against the README phase map

| Phase | State |
| --- | --- |
| 1 Identify | Done. Not a BIUFRAME, so its setup script does not apply as written. |
| 2 ADB | Done: on out of the box over USB, with a USB-A to USB-C cable. No settings changed. |
| 3 Loader mode | Not needed so far. Not tested. |
| 4 Back up | Done and verified (see Backup). Restore path untested. |
| 5 Root | Shipped `su` works. |
| 6 Make it useful | Done: the kiosk is the Home app and boots into the dashboard (see Changes made). |
| 7 Networking | Onboard Wi-Fi works. |
| 8 Vendor updates | Done: Adups FOTA and the Rockchip updater are disabled (see Changes made). |
| 9 Security hand-off | Pending. |

## Changes made to the frame (2026-10-13)

All reversible package states in `/data`; nothing under `/system` or any flash partition was written.
Made after the verified backup.

| Change | How | Undo |
| --- | --- | --- |
| Adups FOTA off | `su -c 'pm disable com.adups.fota; pm hide com.adups.fota'` | `su -c 'pm unhide com.adups.fota; pm enable com.adups.fota'` |
| Adups reboot helper off | `su -c 'pm disable com.adups.fota.sysoper'` (`/system/app/FotaUpdateReboot`) | `su -c 'pm enable com.adups.fota.sysoper'` |
| Rockchip updater off | `su -c 'pm disable android.rockchip.update.service'` | `su -c 'pm enable android.rockchip.update.service'` |
| Kiosk installed | `adb install -r dashboard/kiosk/build/homehq.apk` (`com.wesbos.homehq`, local build with a HOME intent filter, see below) | `adb uninstall com.wesbos.homehq` |
| Frameo off | `su -c 'pm disable net.frameo.frame'` | `su -c 'pm enable net.frameo.frame'` (its data is untouched) |
| Stress test off | `su -c 'pm disable com.cghs.stresstest; pm hide com.cghs.stresstest'` | `su -c 'pm unhide com.cghs.stresstest; pm enable com.cghs.stresstest'` |
| Device test off | `su -c 'pm disable com.DeviceTest'` | `su -c 'pm enable com.DeviceTest'` |
| Kiosk Back/Dashboard buttons on | Owner, on the frame: two-finger hold → Android settings → Accessibility → Home HQ navigation | Turn it off in the same place |

Verified after the first reboot (updaters only): `sys.boot_completed=1`, all three `enabled=2`
(`com.adups.fota` also `hidden=true`), no updater processes, no `ActivityManager` start lines for them,
Frameo back as the HOME activity, and ADB returned.

Verified after the second reboot (everything): the resumed activity is `com.wesbos.homehq/.MainActivity`,
no Frameo, Adups, Rockchip updater or factory test processes, and the dashboard is on screen. The first
load fails with `ERR_NAME_NOT_RESOLVED` before Wi-Fi is up; the kiosk's 5 s retry then loads it.

### Kiosk as Home

- Android 6 has no `pm set-home-activity` or `cmd package set-home-activity`. With Frameo disabled,
  the kiosk is the only HOME activity (there is no Launcher3 and no Settings `FallbackHome`), so
  Android picks it without asking.
- The kiosk in `main` is not a Home app. This unit runs a local build with a `MAIN` + `HOME` +
  `DEFAULT` intent filter on `MainActivity`, the same change as open PR #40. Open PR #43 does it as an
  opt-in alias instead; with only one Home app, enabling the alias is enough on this frame.
- With SystemUI disabled there is no Back or Home button. Android settings is still reachable from the
  kiosk's two-finger menu, and the kiosk's Home HQ navigation buttons can be switched on from there.
- If Frameo is re-enabled, there are two Home apps again and Android 6 shows a chooser at the next
  Home press.

### Clock

There is no battery-backed clock: each boot starts at 2021-05-15 02:00 (that is also the date on the
factory `adb_keys`) until network time arrives over Wi-Fi.

## Guesses (unverified)

- Whether HTTPS can fail at boot if Wi-Fi connects before network time: with the clock at 2021 the
  certificate check would fail, and the kiosk only retries network errors, not certificate errors. Not
  seen on the one reboot tested.
- Why `adbd` skips key authorization despite `ro.adb.secure=1`: a build flag in this vendor's `adbd`,
  or something else. Not tested from a second computer.

## Security notes for the owner

- `su` gives root with no prompt, so any app installed on this frame can take root. Install nothing untrusted.
- Android 6.0.1 with a 2016-07 security patch; SELinux is permissive. Keep the frame on a guest or IoT network.
- Anyone with physical access and a USB-A to USB-C cable gets root, with no prompt on the screen.
- Adups FOTA and the Rockchip updater shipped running and can change the firmware. Both are now
  disabled; re-enabling them (or a factory reset) brings them back.

## Host note

The kiosk build needs JDK 17. With Homebrew's JDK 23 as the default `javac`, build-tools 34's `d8`
crashes on `MainActivity$2.class` (`NullPointerException ... String.length()`). Building with
`JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home` and that JDK's `bin` first
on `PATH` works.
