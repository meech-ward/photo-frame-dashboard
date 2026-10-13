# Uhale 102KZ access notes

One 10.1-inch "Powered by Uhale" frame, model 102KZ, tested on macOS on 2026-10-12. **Root
ADB over USB, a verified backup of every partition except userdata, a normal launcher, and
status and navigation bars are working.** This is a record of one unit, not a setup script.

The 102KZ is the same board class as the
[BIUFRAME 10.1"](biuframe-setup-guide.md): Rockchip RK3126, Android 6.0.1, SuperSU `su`
already in `/system/xbin`, SELinux permissive. Read that guide first. This page covers what
was different on the 102KZ:

- ADB stays `unauthorized` and the prompt can never be tapped, so access needed a boot
  ramdisk change from Rockchip loader mode.
- `qemu.hw.mainkeys=0` does not bring the navigation bar back on this firmware.
- Two things the BIUFRAME notes leave open were confirmed here: how to enter loader mode, and
  that `daemonsu` is what keeps remounting `/system`.

## Confirmed identity

| Field | Observed value |
| --- | --- |
| Model | `102KZ` |
| Product / platform | `rk312x` / `rk312x`, brand `rockchip` |
| Android / ABI | Android 6.0.1, SDK 23, security patch 2016-11-01 / `armeabi-v7a` |
| Build fingerprint | `rockchip/rk312x/rk312x:6.0.1/MXC89K/user.fyl.20170927.202757:userdebug/test-keys` |
| Build display ID | `102KZ_user_UHALE_202607231646` |
| USB, Android running | `2207:0006` (ADB), vendor string `incar`, product string `102KZ` |
| USB, loader mode | `2207:310d` |
| Internal eMMC | 61,071,360 sectors of 512 bytes (about 29.8 GB) |
| Home app | Uhale, `com.zeasn.frame`, running as a full-screen kiosk |
| Stock boot image | 10,616,832 bytes, SHA-256 `4cafbaefb1b32dceabc13e7cdd3e196a6b33418e4bb91f0155c1580fa2c41be1`, SHA-1 `26d1c074467649d913131549c319cb76011b97e1` |

The fingerprint's 2017 date is the platform build; the display ID carries the firmware date.
The boot image's SHA-1 is the one the firmware's own `/system/bin/install-recovery.sh` expects
(`MTD:boot:10616832:26d1c074…`), so the backup it was computed from is the stock image.

## Why the BIUFRAME route stops at ADB

- `adbd` runs out of the box and the frame enumerates as `2207:0006`, but `adb devices` shows
  `unauthorized`.
- The "Allow USB debugging?" prompt is drawn behind the Uhale kiosk. Nothing on screen can be
  tapped to reach it. Reboots, cold boots and replugging did not surface it.
- A USB-C to USB-C cable showed nothing on the bus. A USB-A to USB-C cable enumerated at once.

Not tried: the hidden-Settings route that worked on the [Uhale SI006](si006-uhale.md)
(Settings → About, tap System version repeatedly). It may also work here and would avoid
flashing. If you have a 102KZ, try that first and report back.

## What worked

### 1. Loader mode

1. Unplug the frame's USB-C cable, which powers it off.
2. Press and hold the reset pinhole with a paperclip.
3. Still holding, plug the USB-C cable into the computer. Keep holding for 6 to 8 seconds,
   then release.
4. `rkdeveloptool ld` lists the frame with `Pid=0x310d` and `Loader`.

This worked each time it was used. The frame runs from USB power alone in loader mode.
`rkdeveloptool rd` returns to Android.

### 2. Back up `boot` before changing anything

```sh
rkdeveloptool rl 0x14000 0x7000 boot-stock.img     # must start with ANDROID!
```

The kernel command line on this unit puts `boot` at loader LBA `0x14000`, `0x7000` sectors
long. Our first backup read only `0x6000` sectors. That covered the whole Android image, but read
the full `0x7000` sectors anyway. Check the offsets against your own unit (see the partition table
below) before you trust them.

### 3. The boot image, and what was changed

- Android boot header v0, page size 16,384, gzip-compressed `newc` cpio ramdisk, and a second
  stage. This matches what [biuframe.md](biuframe.md) records for the BIUFRAME.
- `scripts/build-debug-boot.py` (header v2, 2,048-byte pages) and the Allwinner A33 patchers
  (2,048-byte pages, no second stage) both reject this image. A patcher for this layout is not
  in the repo yet.

The ramdisk was rebuilt with two changes, leaving the kernel and second stage untouched:

1. The computer's public ADB key (`~/.android/adbkey.pub`) added as `/adb_keys`. `adbd` trusts
   keys in that file without showing a prompt.
2. In `default.prop`: `ro.secure=0`, `ro.debuggable=1`, and a new line `ro.adb.secure=0`.

Every other cpio entry kept its original mode, owner and device numbers. The header's
`ramdisk_size` was updated and the image re-padded to 16,384-byte pages.

**The second change is broader than it needs to be.** `ro.adb.secure=0` turns ADB
authorization off, so any computer on USB gets a shell, and so does anything on the network
if network ADB is ever switched on. `/adb_keys` alone should be enough to authorize one
computer while leaving authorization on for everyone else. That narrower version was not
tested on this unit. If you repeat this, try `/adb_keys` alone first.

### 4. Write, read back, reboot

**Before writing,** check that your backup is the stock image this patch was made from: its size is
exactly `0x7000` sectors and its SHA-256 matches the stock boot hash recorded above. Stop if it
doesn't. Then:

```sh
rkdeveloptool wl 0x14000 boot-patched.img
rkdeveloptool rl 0x14000 0x7000 readback.img
cmp readback.img boot-patched.img && echo "readback matches"   # stop here if this fails
rkdeveloptool rd
```

The loader did not verify the boot image; the changed image booted. The header ID was
recomputed, but given the BIUFRAME finding that the stock ID matches no known scheme, it is
unlikely anything checks it.

### 5. Result

```sh
adb shell su -c id        # uid=0(root) gid=0(root)
```

- No prompt appeared at any point.
- `adb root` does nothing on this `adbd`. Use `adb shell su -c '...'`.
- A multi-line command passed to `adb shell su -c` ran as the unprivileged shell user
  instead, after `su` printed its usage. Push a script and run `su -c 'sh /data/local/tmp/script.sh'`.

### Undo

From loader mode, write the stock image back:

```sh
rkdeveloptool wl 0x14000 boot-stock.img && rkdeveloptool rd
```

## Partition table on this unit

From the kernel command line (`mtdparts=rk29xxnand:...`). Offsets are loader LBAs in
512-byte sectors. Read your own before using any of these.

| Partition | Start | Sectors |
| --- | --- | --- |
| uboot | `0x2000` | `0x2000` |
| misc | `0x4000` | `0x2000` |
| resource | `0x6000` | `0x8000` |
| kernel | `0xE000` | `0x6000` |
| boot | `0x14000` | `0x7000` |
| recovery | `0x1B000` | `0x10000` |
| backup | `0x2B000` | `0x20000` |
| cache | `0x4B000` | `0x40000` |
| metadata | `0x8B000` | `0x8000` |
| kpanic | `0x93000` | `0x2000` |
| system (ext4, 1 GiB) | `0x95000` | `0x200000` |
| radical_update | `0x295000` | `0x20000` |
| userdata | `0x2B5000` | rest of the eMMC, about 27.8 GB |

Every partition except userdata was backed up, and each image matched an MD5 taken on the
device. `/system` restores with one command, after checking `system.img` against its recorded MD5:
`rkdeveloptool wl 0x95000 system.img`.

## `daemonsu` is what remounts `/system`

The BIUFRAME notes saw `/system` being remounted about 12 times a minute and named SuperSU's
`daemonsu` as the likely cause. On the 102KZ this was measured by reading the ext4 mount count
in the `/system` superblock (2 bytes at offset 1076 of the partition):

| `daemonsu` service | Interval | Mount count |
| --- | --- | --- |
| stopped | 30 s | 3651 → 3651 |
| running | 30 s | 3651 → 3658 |
| running | next 30 s | 3658 → 3664 |
| stopped again | 30 s | 3664 → 3664 |

Why it loops: `init.rc` defines `service daemonsu /system/xbin/daemonsu --auto-daemon` without
`oneshot`. The daemon forks and its parent exits, so init restarts the service about every
5 seconds (`dmesg` shows one start per 5 s), and each start remounts `/system`.

What this means in practice:

- A `/system` image read while the service runs will not match a second read. Run
  `su -c 'stop daemonsu'` before imaging or checksumming `/system`.
- `/system` can turn read-only between two commands. Remount and write in the same command:
  `su -c 'mount -o rw,remount /system && <write>'`.
- `su` kept working with the service stopped. The daemon that already forked stays alive.

To stop the loop on every boot, this was appended to `/system/bin/install-recovery.sh`, which
init runs once per boot as root (the same hook the BIUFRAME guide uses):

```sh
sleep 15
stop daemonsu
```

Undo by restoring the original `install-recovery.sh`. Keep a copy before editing it.

## Status and navigation bars

- This firmware has no status bar and no navigation bar, and the frame has no Home or Back
  key, so nothing leaves a full-screen app.
- Appending `qemu.hw.mainkeys=0` to `/system/build.prop`, which brings the navigation bar back
  on the BIUFRAME, had no effect here.
- The cause: the vendor's `framework-res.apk` sets the bar heights to 0 dp.

A runtime resource overlay restored them. It is a resource-only APK that targets the
`android` package:

```xml
<!-- AndroidManifest.xml -->
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="your.name.barsoverlay" android:versionCode="1" android:versionName="1.0">
    <overlay android:targetPackage="android" android:priority="1" />
</manifest>
```

```xml
<!-- res/values/dimens.xml -->
<resources>
    <dimen name="status_bar_height">24dp</dimen>
    <dimen name="navigation_bar_height">48dp</dimen>
    <dimen name="navigation_bar_height_landscape">48dp</dimen>
    <dimen name="navigation_bar_width">48dp</dimen>
</resources>
```

Signed with a v1 (JAR) signature and placed at `/system/vendor/overlay/BarsOverlay.apk`,
mode 0644. After a reboot both bars are there: 24 dp and 48 dp on a 1280 × 800, 160 dpi screen.
Undo by deleting the file and rebooting. This is the same mechanism as the WebView provider
overlay in the [SI006 notes](si006-uhale.md).

## Hardware, for people writing apps

The firmware's sensor and feature lists are a generic Rockchip template and overstate what is
on the board.

| Component | Observed |
| --- | --- |
| SoC / GPU | RK3126, four Cortex-A7 cores, Mali-400 MP, OpenGL ES 2.0 only |
| RAM | 1 GB; about 200 MB free at idle. Java heap limit 80 MB, 384 MB with `largeHeap` |
| Display | 1280 × 800 landscape, 160 dpi (1 dp = 1 px), panel refresh about 56.6 Hz |
| Storage | `/data` about 27 GB free; `/system` 1 GiB with about 465 MB free |
| Touch | Multitouch, `gslX680` |
| Accelerometer | `sc7a20`, real. Coarse: about 11.3 m/s² was read on the gravity axis |
| Light, proximity, gyroscope, compass | Listed by `SensorManager`, not present. Only the touch panel and accelerometer are on the I2C bus; the kernel's light-sensor drivers found no chip |
| Speaker | Works |
| Microphone | None. `AudioRecord` opens, but the recording is a constant value |
| Camera, battery, RTC backup | None. The clock reads 1970 after power-on until NTP answers |
| Bluetooth | `ro.rk.bt_enable` is `false`; Settings shows no address. Not tested further |
| WebView | Chromium 107 on this unit as found; whether that is stock was not recorded |

The frame is powered through the same USB-C port used for ADB, and it is on whenever it has
power.

## Vendor software

| Package or service | What it is |
| --- | --- |
| `com.zeasn.frame` | The Uhale app: the kiosk home screen and its cloud service |
| `com.adups.fota` | Adups FOTA updater, as on the BIUFRAME |
| `lan-server`, TCP 17802 and 17803 | Part of Uhale. Plaintext on 17802, self-signed TLS on 17803, a `LAN/1.1` protocol the Uhale phone app uses to drive the frame. Not examined further |

- Uhale keeps per-device key files (`zeasn_auth`). Treat them like credentials: keep them out
  of anything you share.
- On this unit Uhale and Adups were removed from `/system` after copies were taken, and a
  launcher installed as the home app. `pm disable` and `pm hide`, as the BIUFRAME guide does,
  are reversible and are the better first step.
- With Uhale gone, nothing on the frame listens on a TCP port.
- `ril-daemon`, the phone radio daemon, runs although there is no modem. It is stopped by the
  same boot hook as `daemonsu`.

## Limits and what is untested

- One unit. Firmware `102KZ_user_UHALE_202607231646`. Another 102KZ may differ.
- The hidden-Settings route from the SI006 notes was not tried.
- The `/adb_keys`-only boot change, with ADB authorization left on, was not tried.
- Network ADB works after `setprop service.adb.tcp.port 5555` and restarting `adbd`, and
  resets at reboot. With `ro.adb.secure=0` it gives root to anything on the network, so it was
  left off.
- Stock recovery and the `recovery-from-boot` check in `install-recovery.sh` were not
  examined after the boot change. The frame has booted normally since.
- Restoring `/data` from a file-level copy was not test-run.
