# PF1007L / AiMOR May 2026 firmware (20260519): Linux unit report

This PF1007L reached root ADB and a replacement Android home screen using
[Route U](allwinner-a33-mainline-uboot.md) from a Linux host. With a low-power
U-Boot configured for **4-bit eMMC at up to 26 MHz**, sustained reads repeatedly
lost the USB device, including through a powered dock. Changing only the eMMC
frequency cap to **12 MHz** in that build allowed the full backup and subsequent
post-write verification to complete.

Observed on 2026-10-12/13 with Arch Linux (Omarchy / Hyprland), a Framework Laptop 16,
and `adb` reporting version 1.0.41. Compared against repository main at
[`fbe9a30`](https://github.com/wesbos/photo-frame-dashboard/commit/fbe9a30ac4f9c77d3863e19a5e98d9eadb04ab03).
**This is a unit report, not a new default recovery configuration.** Power rails
and the actual bus clock were not instrumented. USB loss alone does not prove a
brownout or identify its electrical cause. The optional source patch below does
not change the repository's default build or make another unit's offsets safe.
Serials, MAC addresses, eMMC CIDs, network details, dumps and the whole-eMMC hash
are withheld.

## Unit report

```text
Model / firmware: PF1007L; Android model property AEEZO
  ro.build.display.id:  astar_m86_8723cs-eng 6.0.1 MOB30R 20260519 test-keys.1
  ro.build.fingerprint: AEEZO/astar_m86_8723cs/astar-m86_8723cs:6.0.1/MOB30R/20260519:eng/test-keys
  build date: Tue May 19 2026
AiMOR version: 6.0.78
SoC / OS: Allwinner A33 (sun8i), Android 6.0.1, SDK 23, armeabi-v7a, SELinux Disabled
eMMC: 30,777,344 sectors (15,758,000,128 bytes)
USB IDs: FEL 1f3a:efe8; stock Android 1f3a:1000; U-Boot gadget 1f3a:1010;
  patched Android 1f3a:1002
Host data path: frame USB into a powered Lenovo TP USB 3.0 Pro Dock, downstream
  of a Realtek hub, into a Framework Laptop 16.
```

## Sustained-read failures and the successful configuration

The default 8-bit build and an initial 4-bit / 26 MHz build failed at the first
eMMC read. A low-power build with `CONFIG_SUNXI_NO_PMIC=y` and CPU frequency
`408000000` got further: two sustained reads stopped at 41,779,200 and 42,024,960
bytes, roughly five seconds into reading. The USB device disappeared.

Adding the powered Lenovo dock did not resolve the 26 MHz failure. With the same
powered path and the same other source changes, lowering `max-frequency` to
`12000000` gave sustained transfers of about **4.5-4.8 MB/s**. This comparison
supports the lower cap as a useful workaround on this unit; it does not establish
that the dock was unnecessary, that every change below was required, or that all
larger-eMMC units need 12 MHz.

The successful build used U-Boot v2025.10 at
`e50b1e8715011def8aff1588081a2649a2c6cd47`, the repository's
`pf1007l-uboot.patch`, and these additional changes:

1. **eMMC timing** in the backup device tree (`mmc2`): `bus-width = <4>` and
   `max-frequency = <12000000>`.
2. **Low-power U-Boot** in `pf1007l_backup_defconfig`: `CONFIG_SUNXI_NO_PMIC=y` and
   `CONFIG_SYS_CLK_FREQ=408000000`. This leaves PMIC initialization out of this
   U-Boot build; it does not mean that the board has no PMIC.
3. **START STOP guard** in `drivers/usb/gadget/f_mass_storage.c` (`do_start_stop`):
   eject only on an explicit unload request (`(cmnd[4] & 0x03) == 0x02`), using the
   [existing correction](patches/pf1007l-v2025.10-start-stop.patch). Its contribution
   to this Linux result was not tested independently.

DRAM settings stayed at 456 MHz / ZQ 15291. No MMC retry loop, no-HS driver change
or null-console configuration was added. Both UMS read-only protections remained:
the write callback refuses writes and the LUN reports write-protect. Native
`mmc write` remained available; this session used it only in the separately
approved boot-patch script.

**These settings affect only the FEL-loaded recovery U-Boot.** They were not
installed as Android's bootloader or storage driver. The Android change was the
separate boot-ramdisk USB/ADB patch, not a CPU or eMMC speed change.

### Optional source patch and build limitation

The [12 MHz / low-power patch](patches/pf1007l-v2025.10-linux-12mhz.patch)
records the two configuration changes. Apply it together with the existing
START STOP patch, on top of the default `scripts/a33-uboot/pf1007l-uboot.patch`.
It is not applied by `build-uboot.sh`.

As in the [May report's host-only build](pf1007l-macos-20260529-report.md#reproduce-the-ram-only-build),
apply additional patches only to a disposable source copy, with a separate
output directory. Do not modify an existing source tree that already carries
experimental changes. Within that container, these are the patch/build steps
for this variant (the source already has the default repository patch):

```sh
patch --dry-run --fuzz=0 -p1 < /patches/pf1007l-v2025.10-start-stop.patch
patch --fuzz=0 -p1 < /patches/pf1007l-v2025.10-start-stop.patch
patch --dry-run --fuzz=0 -p1 < /patches/pf1007l-v2025.10-linux-12mhz.patch
patch --fuzz=0 -p1 < /patches/pf1007l-v2025.10-linux-12mhz.patch
make O=/build pf1007l_backup_defconfig
make O=/build -j"$(nproc)"
```

Unlike the May recipe, this build did not enable `SYS_DEVICE_NULLDEV` and used
the unmodified `scripts/a33-uboot/ums-readonly.cmd`, not its `nulldev` wrapper.
These are host-side build steps, not instructions to load or flash a frame.

**The existing build helper's SPL check did not pass for this variant.** It
reported `SPL code ends at 0x6000`. Inspection of the retained image showed an
eGON-declared SPL length of `0x4000`, its last nonzero byte at `0x3ee6`, and
`0xff` padding between `0x4000` and `0x6000`. The helper counts that padding as
code, as also reported in #16. The device-tree name was present.

The session proceeded after that manual inspection. This report does not change
or waive the `0x5e00` safety limit: another image needs its own SPL/linker-layout
check. Do not ignore arbitrary `0xff` bytes, increase the limit to make a build
pass, or load a leftover binary after a failed build.

During preparation of this report, a host-only rebuild from the pinned source
and published patches passed. The five source files changed by the combined
patches matched the retained hardware-tested source byte-for-byte. The compiled
device tree contained bus width 4 and frequency cap 12000000; the SPL linker
symbol `__image_copy_end` was `0x3ee8` and the eGON length was `0x4000`, both
below the unchanged `0x5e00` limit. That rebuild was not loaded onto the frame.

## Backup and guarded boot write

`emmc-macos.py backup-resume` completed all 15 segments. Each segment was read
twice from eMMC and once back from the image file, with matching hashes; the
filler and gzip-readback checks passed. The backup covers the full
**15,758,000,128-byte eMMC user area** exposed by UMS, not separately exposed
hardware boot partitions or RPMB. One full device-read pass took about 56 minutes.

Two boot ranges were checked; the 31,028-sector hash matches #24:

| Boot range, starting at sector 172032 | SHA-256 |
| --- | --- |
| Actual image, 29,292 sectors | `71807e93aa8875afcfba70112fbec075c33737b06fd22ae7807bc757a834dc64` |
| Comparison range, 31,028 sectors | `9a6e2456952f3dc2b99e64ea021321397bdc824364b5c8b42f503f847261630a` |

The patch generator used this unit's own verified backup. Its planned ranges
were header `[172032, 172034)` and ramdisk `[191844, 201324)`. After explicit
owner approval, the reviewed script wrote the ramdisk and then the header,
checking write/readback results before the next write.

Before booting Android, the entire user area was compared with the backup plus
exactly those planned payloads. `verify-resume` completed without a USB drop:

```text
Verified: the eMMC equals the backup plus exactly the planned boot patch.
```

The original backup and generated `restore-boot.scr` were retained. The
[Route U undo procedure](allwinner-a33-mainline-uboot.md#6-guarded-write) loads
the original payloads with the guarded restore script, then verifies the result.
Restore was not exercised on this unit; do not present a retained undo plan as
a tested rollback.

## Linux host notes

- `scripts/a33-uboot/emmc-macos.py` runs on Linux. `open_disk_linux` wants the
  **bare** block name (`sdb`, not `/dev/sdb`), model `UMS disk N`, an exact size
  match, a `/usb` sysfs path, `ro=1`, and no mounted partitions.
- The UMS device letter **changes between enumerations** (it was `sdb`, later
  `sda`). Recheck size, model, USB identity, read-only state and mounts before
  every operation; size and a remembered letter alone are not enough.
- The desktop auto-mounter (`udiskie`) mounted eMMC partitions. It was paused and
  those partitions unmounted before the read/verify runs, then resumed afterwards.
- `backup-resume` / `verify-resume` persist per-segment state under `backups/`,
  allowing completed segments to be reused after a dropout. The successful
  12 MHz backup and post-write verify did not need to recover from a dropout.
  Do not boot Android between the backup, patch and whole-device comparison:
  normal Android writes would invalidate the unchanged-disk expectation.

## Android, navigation and vendor-package disable

After removing the FEL card and booting Android, USB enumerated as `1f3a:1002`
and `adb -d shell id` returned `uid=0(root)` directly. Both USB configuration
properties still read `mass_storage`; the patched action adds ADB without
changing those property strings.

With owner approval, the guide's pinned Rootless Launcher 3.9.1 and Firefox
143.0.4 ARMv7 APKs were hash-checked and installed. The owner selected Rootless
as the default Home app and confirmed it was visible before AiMOR was disabled.
`com.efercro.os.aimor`, `com.yhk.qeota` and `com.DeviceTest` each showed
`enabled="2"` in the on-disk package restrictions before rebooting.

After **one post-disable reboot**, root USB ADB still worked, all three packages
still showed `enabled=2`, their processes were absent, and Android reported
Rootless as the foreground Home activity. No connection to port 7806 was listed.
The frame remained off Wi-Fi, so this was **not an online network-isolation test**
or evidence that Android 6 is generally safe on a trusted network. No persistent
firewall was installed. Keep it on an isolated guest/IoT network if connecting it.
The disabled packages remain installed; `pm enable PACKAGE` reverses a disable
and also restores that package's risks.

This firmware has no `com.android.systemui`. Opening Firefox left the owner
without on-screen Home/Back controls; sending Home over ADB returned it to
Rootless. Keep USB available until a navigation solution is installed, such as the kiosk's
[navigation buttons](../dashboard/kiosk/README.md#frames-without-home-or-back-buttons) (not tested on this unit):

```sh
adb -d shell input keyevent KEYCODE_HOME
adb -d shell input keyevent KEYCODE_BACK
adb -d shell am start -a android.settings.WIFI_SETTINGS
```

The Wi-Fi command opens Android Settings; it does not supply network credentials.
WebView replacement, kiosk installation and network use were not tested in this
session. The FEL card was kept separately for recovery.

## Relation to other reports

- [#24](https://github.com/wesbos/photo-frame-dashboard/issues/24): matching May
  boot-image hash, but that unit completed recovery at 4-bit / 26 MHz with a powered
  hub and read retries. It is not evidence that 12 MHz is universally required.
- [Windows + WSL May report](pf1007l-windows-wsl-20260519-report.md): 12 MHz
  helped eMMC reads at 8-bit, but that report did not test 12 MHz UMS or complete
  a full backup. This Linux run adds a successful 4-bit / 12 MHz UMS backup and
  full post-write comparison.
- [#16](https://github.com/wesbos/photo-frame-dashboard/issues/16): low-power
  configuration and the same SPL-padding check issue; its power explanation was
  an inference, not a measurement.
- [May 2026 macOS report](pf1007l-macos-20260529-report.md): same START STOP
  correction, without this unit's low-power configuration.
