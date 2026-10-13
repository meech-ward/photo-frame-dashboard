# Rovesky 10.1" battery-powered frame with Uhale (Allwinner A33 `astar_d7`, Android 6.0.1)

Record of one unit, started 2026-10-12. Observations are kept separate from guesses. Unique
identifiers (serial, MAC, IP) are left out; they live in the ignored `backups/` folder.
Host: macOS on Apple silicon. Cable: USB-A to USB-C, plus the DC power adapter.

Listing for this model: <https://www.amazon.com/dp/B0G3N3BNJW> (plain link, no affiliate tag).

**Short version:** this frame has an **internal battery** (no other frame in this repo documents one),
ships with **stock ADB over USB** (no boot patch, FEL or SD card)
and a setuid-root `su` that needs no prompt. The vendor app is Uhale (`com.zeasn.frame`), not
AiMOR. The frame already ships WebView 106, so the PF1007L WebView swap is not needed. The kiosk
and dashboard ran with the steps in [allwinner-a33-pf1007l.md](allwinner-a33-pf1007l.md) sections
5 and 7. Nothing was written to flash or `/system`.

This is **not** a PF1007L. The About screen shows no `PF1007L` or `AIMOR`, and the partition
layout differs. Do not use the PF1007L firmware table or boot hashes for it.

## Observations (read-only unless noted)

### Identity

| | |
| --- | --- |
| Label | "Rovesky" 10.1" smart photo frame, vendor app "Powered by uhale" |
| About screen | Update string `FSTR - 5.1.1 - 5010100`, build number `RAM.user.2025-12-25+10:23:17`, system version `6.0.1` |
| Model / device / board | `ro.product.model=RAM`, `ro.product.device=astar-d7`, `ro.product.brand=Allwinner`, `ro.product.board=exdroid` |
| Fingerprint | `Allwinner/astar_d7/astar-d7:6.0.1/MOB30R/20251225:user/test-keys` |
| SoC | Allwinner A33 (`ro.board.platform=astar`, `ro.hardware=sun8i`), 32-bit ARMv7 |
| Kernel | Linux 3.4.39 |
| Android | 6.0.1, security patch 2016-07-05, SDK 23 |
| Display | 1280x800, 160 dpi |
| RAM / storage | about 1 GB RAM, eMMC 30,535,680 sectors (`mmcblk0`), `/data` 25.7 GB |
| Vendor app | `com.zeasn.frame` from `/system/app/uhale_5.1.1_5010100_20251203_rk_signed/` |
| Other vendor packages | `com.DeviceTest`, `com.softwinner.dragonfire`, `dragonaging`, `dragonphone` (Allwinner test apps). No AiMOR (`com.efercro.os.aimor`) and no `com.yhk.qeota` |
| WebView | `com.android.webview` **106.0.5249.126** in `/system/app/webview` (stock, 210 MB `base.apk`, with `oat/arm/base.odex`) |
| SystemUI | No SystemUI package, so no status bar or navigation bar |
| SELinux | Permissive |
| Wi-Fi | Realtek, kernel module `8189fs` over SDIO. Never connected during this session |
| Touch | `gslX680new` |
| Battery | Internal battery present, see [Battery](#battery) |

### Battery

The frame has an internal battery, which no other frame in the [device index](devices.md)
documents. From `/sys/class/power_supply/battery` and `dumpsys battery`, with the DC adapter and the
USB cable both attached:

| | |
| --- | --- |
| `present` | 1 |
| `status` / `capacity` | `Full` / 100 |
| `voltage_now` | 4,191,000 µV (4.19 V) |
| `technology` | `LiFe` (the driver's label) |
| `health` | 2 (good) |
| Temperature | 30.0 °C |
| Supplies | `ac` online 1, `usb` online 1 |

Guess, not verified: 4.19 V is a full Li-ion or LiPo cell, so the `LiFe` label is probably just a
driver string. Not measured: capacity in mAh, runtime on battery, whether it charges from the USB
cable alone, and whether the frame boots with no mains. The unplug test needs a person at the frame
and was not run.

Why it matters for this repo: a frame that can run unplugged can sit on a shelf or move room to room,
and Android's battery state is readable over ADB (`dumpsys battery`) for the dashboard.

### USB

With the USB-A to USB-C cable, the frame enumerated on the Mac as `1f3a:1009` (manufacturer
string "USB Developer", USB 2.0 high speed). `/sys/class/android_usb/android0/functions` reads
`ptp,adb`. It was **not** seen on the first checks with a USB-A to USB-C cable and DC power
attached, even after a reboot and about 40 seconds of polling. It appeared a few minutes later,
after the owner tried other cable and port arrangements (which were not recorded), so this unit
may be fussy about the cable or port.

Before it appeared, the Mac showed only an unrelated hub's Billboard device (VIA vendor ID), not
the frame. A Billboard device is not an Allwinner `1f3a` device.

### ADB and root

- `adb devices -l` lists the frame as `device` with no prompt on screen (there is no SystemUI package, which may be why). `adb shell id` gives `uid=2000(shell)`.
- `/system/xbin/su` is present, mode `-rwxr-xr-x root shell`, 133,472 bytes (SuperSU style).
  `adb shell su -c id` returns `uid=0(root)` with no prompt. `/system/xbin/daemonsu` is also present.
- `/system/build.prop` has `ro.adb.secure=1`, `persist.sys.usb.config=ptp,adb` and
  **`service.adb.tcp.port=5555`**. With Wi-Fi never connected, `netstat` shows `adbd` listening on
  `0.0.0.0:5555`.
- **Network ADB was not tested** because the frame was never put online. `ro.adb.secure=1` is
  set, but whether the TCP listener checks keys is **unverified**. Treat the open listener as
  possible root ADB over Wi-Fi until someone tests it.
- `pm disable` as the `shell` user fails with `SecurityException ... package uid=1000`. It works
  through `su -c`. `adb shell input keyevent KEYCODE_WAKEUP` wakes the screen.

### Partitions and boot image

Read from `/sys/class/block/*/start` and `size` (512-byte sectors):

| Partition | Device | Start | Size |
| --- | --- | --- | --- |
| env | `mmcblk0p5` | 139264 | 32768 |
| boot | `mmcblk0p6` | **172032** | 32768 |
| system | `mmcblk0p7` | **204800** | **4194304** (2 GiB) |
| recovery | `mmcblk0p9` | 4431872 | 65536 |

The boot partition starts at the same sector as the PF1007L, but `system` starts at 204800 (PF1007L:
237568) and is twice the size. The boot image has an `ANDROID!` header, page size 2048, kernel
10,304,216 bytes, ramdisk 4,321,371 bytes, giving an image of **14,630,912 bytes** (PF1007L: 15,886,336).

| Check | Value |
| --- | --- |
| Boot image SHA-256, first 8, over the 14,630,912-byte image | `04744a9e` |
| Same, over the guide's 31,028-sector range (includes partition padding) | `8c90e69f` |

The bytes after the image in the partition are all zero. A boot patch was **not** needed or tried.
Route U and Route S were not run. Guess, not verified: Route U's structure checks were written
for the PF1007L image and may not accept this one.

### Backup, and the `daemonsu` remount loop

Every partition was read twice with `su -c dd` over `adb exec-out`, and the hashes compared
(plus a gzip readback check): env, boot, recovery, bootloader, misc, frp, metadata, private,
media_data, empty, alog, and system. This is not a full-device backup (userdata and the eMMC boot areas were
not captured).

**The first two `system` reads never matched.** Each full read of `/system` produced a different
hash. Cause, measured:

- The two raw reads differed in about 1,469 bytes, all within the first 7 MiB, and nowhere else.
- `dmesg` showed `EXT4-fs (mmcblk0p7): re-mounted` in bursts roughly every 4.5 to 5 seconds,
  hundreds of times, with `/system` shown as `ro`.
- The superblock block read the same three times in a row, but
  `/sys/fs/ext4/mmcblk0p7/lifetime_write_kbytes` rose by about 72 KiB in 10 seconds.
- `init.svc.daemonsu` was `restarting` (a crash loop), and the remounts stopped when `su -c "stop daemonsu"` was run. They had not stopped when the Uhale app and `com.DeviceTest` were disabled.
- With `daemonsu` stopped, two raw reads and the gzip readback all matched.

Guess, not verified: the SuperSU daemon remounts `/system` each time it restarts. After a reboot
`daemonsu` was `restarting` again, so the stop only lasts until the next boot.

### Uhale and the vendor app

- The About screen update page has **Automatic download** on and **Automatic installation** on by
  default ("Once enabled, software updates will be automatically installed during non-sleep").
  The frame was kept offline, so no update was observed. See [app-updates.md](app-updates.md).
- `logcat` shows SELinux `avc: denied { execute_no_trans }` for `/system/xbin/su` from the
  `system_app` domain, with `permissive=1`. Guess, not verified: the Uhale app, which runs as
  uid `system`, calls `su`. It was not decompiled, so which code does is unknown.
- After `pm disable com.zeasn.frame` and `com.DeviceTest` (via `su`), a reboot (`su -c reboot`, back
  in about 33 seconds, no hang) kept both `enabled="2"` in `package-restrictions.xml`.

### Launcher and kiosk

- Rootless Launcher 3.9.1 (the pinned APK from the guide) installed with `adb install` and took
  Home. The panel showed the launcher.
- The kiosk APK built from `dashboard/kiosk/` with JDK 17 and build-tools 34.0.0 installed and ran.
  With `adb reverse tcp:4173 tcp:4173` and the guide's `am start` command, the owner saw the
  dashboard with sample data on the panel.
- `logcat` showed `eglChooseConfig failed with error EGL_BAD_ATTRIBUTE` twice at start; the page
  rendered anyway.
- The screen went to sleep with the launcher in focus (`mWakefulness=Asleep`, backlight 0), which
  looks like a black panel. Check with `dumpsys power` and `input keyevent KEYCODE_WAKEUP` before
  assuming a launcher failure.
- Not tested here: HTTPS hosting from the frame (see the trust-store note in
  [pf1007l-start-here.md](pf1007l-start-here.md#then-set-it-up)), boot auto-start, and Wi-Fi.

## Undo

- `su -c "pm enable com.zeasn.frame"` and `su -c "pm enable com.DeviceTest"` re-enable the apps.
- `adb uninstall amirz.rootless.nexuslauncher` and `adb uninstall com.wesbos.homehq` remove the added apps.
- `adb reverse --remove tcp:4173` removes the port mapping.
- Nothing was written to flash, so there is no flash undo.

## Open questions

- Does `adbd` on port 5555 accept a host key it has never seen (as on the Joyhong)?
- Which code in the Uhale app calls `su`, and what does it contact when online?
- Do other Rovesky or Uhale frames with `astar_d7` and different build dates match this one?
