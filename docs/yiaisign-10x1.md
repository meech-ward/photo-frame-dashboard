# YIAISIGN 10.1" frame (`10X1`, RK3126, Android 6.0.1, firmware `dpf01m1a_user_YJ_2024082915`)

Record of one unit, set up on macOS (Apple silicon) on 2026-10-12. Observations are kept separate
from guesses. Unique identifiers (serial, MAC) are left out.

**Result:** ADB over USB out of the box, shipped root, a verified backup of everything before
`userdata`, and every step of the [BIUFRAME setup guide](biuframe-setup-guide.md) applied:
launcher, Firefox, vendor apps disabled, 512 MB swap, WebView 106, Let's Encrypt roots and the
navigation bar. All checks of `scripts/biuframe-setup.sh verify` pass.

**But `scripts/biuframe-setup.sh check` fails on this unit** (different fingerprint and
manufacturer), so `backup` and `apply` refuse to run as-is. The steps were run one at a time
instead; see [Setup](#setup).

## How it relates to the known RK3126 frames

It has the BIUFRAME's model name and vendor app, but the platform build and partition layout of
the Uhale 102KZ ([PR #51](https://github.com/wesbos/photo-frame-dashboard/pull/51), open at the
time of writing).

| | This frame | BIUFRAME (Synergy 10X1) | Uhale 102KZ (PR #51) |
| --- | --- | --- | --- |
| Model / manufacturer | `10X1` / `incar` | `10X1` / `Synergy` | `102KZ` / `incar` |
| Build fingerprint | `…/user.fyl.20170927.202757:userdebug/test-keys` | `…/user.thzy.20240919.143320:user/release-keys` | same as this frame |
| Partition layout | userdata at sector 2,846,720 | userdata at 3,891,200 | same as this frame |
| Home app | `com.shenju.biuframe` (Biu Frame) | same as this frame | Uhale `com.zeasn.frame` |
| ADB prompt | Shown, could be accepted | Shown | Hidden behind the kiosk |
| Wi-Fi chip | Realtek SDIO (see below) | SSV6020C (`ssv6x5x` module) | not recorded |
| Touch | `gslX680` | Hynitron `cst2xxse` | `gslX680` |
| `qemu.hw.mainkeys=0` | Brings the navigation bar back | Brings it back | No effect |

## Identity

| | |
| --- | --- |
| Box / About screen brand | YIAISIGN |
| `ro.product.model` / `brand` / `manufacturer` | `10X1` / `YIAISIGN` / `incar` |
| `ro.product.name` / `device` / `board.platform` | `YJ10` / `rk312x` / `rk312x` |
| Build fingerprint | `rockchip/rk312x/rk312x:6.0.1/MXC89K/user.fyl.20170927.202757:userdebug/test-keys` |
| Display ID | `dpf01m1a_user_YJ_2024082915` (build date 2024-08-29) |
| Android | 6.0.1, security patch 2016-11-01, kernel 3.10.0, SELinux permissive |
| `ro.secure` / `ro.debuggable` | `1` / `0` (`adb root` unavailable; use `su`) |
| USB, Android running | `2207:0011`, manufacturer string `incar`, product string `10X1` |
| eMMC | 61,079,552 sectors of 512 bytes (about 29 GB) |
| RAM | 1 GB |
| Display | 1280 × 800, 160 dpi |
| Stock boot image | 10,649,600 bytes, header v0, 16,384-byte pages, second stage 1,136,128 bytes. SHA-256 `5cfd6963732ae569c7b75099c4687296547477a783bca06b2c97d4afa19e904f`, SHA-1 `35adab8565ef51c42f21229a61cc18e424d347e5` |

The boot SHA-1 is the one `/system/bin/install-recovery.sh` expects
(`MTD:boot:10649600:35adab85…`), so the backup holds the stock image.

## Hardware

| Part | Observed | Evidence |
| --- | --- | --- |
| SoC | Rockchip RK3126 | `/proc/cpuinfo` |
| Wi-Fi | Realtek SDIO, vendor `0x024c` device `0xb703` | `/sys/bus/sdio/devices/mmc2:0001:1`. Driver built into the kernel; `lsmod` is empty. The part is probably an RTL8723CS / 8703B (a guess from the ID) |
| Touch | Silead `gslX680` | i2c-2 `0x40`, `dmesg` |
| Accelerometer | Device at i2c-2 `0x19` | Probably the SC7A20, as on the other two (not confirmed) |
| RTC | None found | Only `0x19` and `0x40` on i2c-2 |
| Bluetooth | `ro.rk.bt_enable=false` | not tested |

## Getting ADB and root

1. A USB-C cable plugged straight into the Mac. `adb devices -l` shows `unauthorized`.
2. "Allow USB debugging?" appeared on the frame. Tick **Always allow**, then **Allow**.
3. `adb devices -l`: `device usb:… product:YJ10 model:10X1 device:rk312x`.
4. `adb shell su -c id` → `uid=0(root)`. SuperSU's `su` is in `/system/xbin`, no manager app,
   no prompt. **Any app can get root.**

No developer settings, boot patch or loader mode were needed.

## Partition layout

From `/sys/block/mmcblk0/mmcblk0p*/start`, in 512-byte sectors. The loader LBAs in the kernel
command line are these minus `0x2000`, and match the 102KZ table in PR #51.

| Partition | Start | Sectors |
| --- | --- | --- |
| uboot | 16,384 | 8,192 |
| misc | 24,576 | 8,192 |
| resource | 32,768 | 32,768 |
| kernel | 65,536 | 24,576 |
| boot | 90,112 | 28,672 |
| recovery | 118,784 | 65,536 |
| backup | 184,320 | 131,072 |
| cache | 315,392 | 262,144 |
| metadata | 577,536 | 32,768 |
| kpanic | 610,304 | 8,192 |
| system | 618,496 | 2,097,152 |
| radical_update | 2,715,648 | 131,072 |
| userdata | 2,846,720 | rest |

`boot` starts at 90,112 as on the BIUFRAME (that line of `check` passes), but everything from
`recovery` on is elsewhere.

## Backup

`biuframe-setup.sh backup` cannot be used here: it runs `check` first, and its fixed length of
3,891,200 sectors would read about 510 MB into `userdata` on this layout. The same commands were
run by hand with the length taken from this unit:

```sh
N=$(adb shell su -c 'cat /sys/block/mmcblk0/mmcblk0p13/start' | tr -d '\r')   # 2846720
adb exec-out "su -c 'dd if=/dev/block/mmcblk0 bs=512 count=$N 2>/dev/null'" \
  | tee >(shasum -a 256) | gzip -1 > backups/<serial>/emmc-0-$N.img.gz
```

Checks that passed: length exactly 1,457,520,640 bytes; the gzip readback has the same SHA-256
as the stream; `boot`, `recovery`, `uboot` and 16 MiB of `system` data re-read from the frame
match the backup; no `0xCC` filler.

## Setup

Every step of `biuframe-setup.sh` except `check`, `backup` and `apply` works here unchanged.
They copy files and change packages and do not depend on partition offsets. They were run one
at a time, from bash (macOS's `/bin/bash` 3.2 cannot `source <(...)`, so use a file). The steps
ran through a small wrapper doing the same thing; this snippet was not re-run exactly as written:

This skips the script's `check`, so the block checks the identity itself and stops unless this is
the YIAISIGN build documented here.

```sh
mkdir -p diagnostics
sed '/^case /,$d' scripts/biuframe-setup.sh > diagnostics/biuframe-lib.sh
export BIUFRAME_CACHE=$PWD/diagnostics/biuframe-downloads
bash -c 'set -euo pipefail
  [ "$(adb shell getprop ro.build.display.id | tr -d "\r")" = dpf01m1a_user_YJ_2024082915 ] || { echo "STOP: not this frame"; exit 1; }
  adb shell su -c "stop daemonsu"     # stops the remount loop before /system writes
  source diagnostics/biuframe-lib.sh; ROOT=$PWD
  sh_dev "mkdir -p $DEV_TMP"
  step_apps                          # launcher first: there is no other home app
  VENDOR_DISABLE=(com.shenju.biuframe com.adups.fota com.DeviceTest)
  VENDOR_HIDE=(com.adups.fota)
  step_debloat
  step_zram; step_webview; step_certs; step_navbar'
adb reboot   # then, once booted:
bash -c 'source diagnostics/biuframe-lib.sh; ROOT=$PWD; cmd_verify'
```

Differences from the guide:

- **Install the launcher before disabling the vendor app.** `apply` disables first. Here the
  Biu Frame app was the only home app.
- **Only three of the guide's vendor packages exist:** `com.shenju.biuframe`, `com.adups.fota`
  and `com.DeviceTest`. `android.rockchip.update.service`, `com.cghs.stresstest`,
  `com.android.rk` and `com.android.rk.mediafloat` are absent, and `step_debloat` fails its
  check if they stay in the list.
- `daemonsu` was stopped (`su -c 'stop daemonsu'`) before the `/system` writes, as PR #51
  recommends, so it could not remount `/system` read-only between commands. It is back after a
  reboot. Not tested whether the steps also pass with it running.

`cmd_verify` after the reboot: WebView 106.0.5249.126 loaded, swap 512 MB, navigation bar
present, no vendor processes, Let's Encrypt roots present. Rootless Pixel Launcher was the home
app with no chooser.

Undo is as in the [guide](biuframe-setup-guide.md): `.bak` copies of `install-recovery.sh`,
`build.prop` and `webview.apk` are next to the originals, and `pm enable` restores the vendor apps.

## Not tested

- Wi-Fi with the vendor apps disabled (`wlan0` is up and Wi-Fi is enabled; no network was joined
  during this session).
- Loader mode, stock recovery, and the PIR sensor the BIUFRAME has.
- The kiosk app from `dashboard/kiosk/`.
