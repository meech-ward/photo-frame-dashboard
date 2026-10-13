# VESWWE 10.1-inch Wi-Fi photo frame

> Another frame with the same `VESWWE DP100` About screen reports `ro.product.model` `DP101`,
> Android 10 and WebView 113. It needs none of the steps below; see [veswwe-dp101.md](veswwe-dp101.md).

Investigation started 2026-10-12. This is a record of one owner's unit, not a
flashing guide. Hardware identity is established through stock USB ADB.

End result: owner-controlled launcher and Firefox, a working floating Home
button, and Frameo plus the two vendor updaters disabled. Normal reboots were
verified. A Mac-served webpage rendered with JavaScript through USB while the
frame's internet access remained blocked. No firmware flash or system APK edit
was needed. Account-connected dashboards and standalone kiosk startup have not
been configured.

## Confirmed observations

- Owner describes the frame as a VESWWE 10.1-inch Wi-Fi digital photo frame.
- Owner's About-screen photo confirms hardware brand/model `VESWWE DP100` and
  Frameo version `v1.27.3 (54680)`. This is the app version, not an Android or
  firmware build identifier. No Android version or SoC is visible on this screen.
- The frame boots and displays its settings with the supplied PSU.
- Owner reports one USB-C port and one microSD slot, with no other ports.
- A second Mac connection using a USB-C-to-A adapter and A-to-C cable powered
  the frame on (owner observation). After a delay, macOS enumerated `DP100`,
  USB vendor string `rockchip`, VID:PID `2207:0001`. This confirms USB data on
  that connection. ADB later identified the platform as RK3326.
- Official Android platform-tools 37.0.1 were downloaded from Google into
  ignored diagnostics. Archive SHA-256 matched Homebrew's package metadata:
  `ee39ad5967e95c2a07f04dbcbde96b1a0c916ba376096db5d2f498b7727a5d1d`.
  Initial `adb devices -l` returned an empty device list after USB enumeration.
- macOS exposes one interface named `MTP`, class/subclass/protocol
  `255/255/0`; no ADB interface was seen. A subsequent `adb devices -l` was
  also empty. This was before enabling debugging in Frameo's menu.
- Owner connected the frame to Wi-Fi and applied a router block. Initial
  network ADB port test timed out; ping failed with `Host is down` and macOS
  had no ARP entry for the supplied address. Local reachability must be resolved
  before interpreting this as an ADB result. The private address is omitted.
- After the router adjustment, both the TCP test and `adb connect` returned
  `Connection refused`; ping still received no replies and ARP had no entry.
  ADB was not established. A router rejection remains possible, so this alone
  does not prove the frame's port is closed.
- The About screen shows anonymous analytics sharing enabled. Its peer ID is
  omitted from these public notes; the original photo must not be published
  without redacting it.
- Following the suggested Frameo beta-menu route, owner reported USB ADB
  available. Host confirmed an authorized `DP100` connection; the exact toggles and
  authorization prompts used were not recorded.
- `adb shell` is UID 2000; `su -c id` returns UID 0. SELinux is permissive.
  No boot patch or system APK modification was needed; approved app changes
  and their verification are recorded below.
- Initial attempt to power the frame from a Mac USB port did not power it on
  (owner observation). Cable type and data capability have not been confirmed.
  The Mac USB watcher detected no device during that attempt. This does not
  establish whether the frame supports USB data; the second connection did.

### Identity from ADB

| Field | Observation |
| --- | --- |
| Model / manufacturer | `DP100` / `rockchip` |
| Platform / hardware | `rk3326` / `rk30board` |
| Android / API | 8.1.0 / 27 |
| Security patch | 2020-06-05 |
| Firmware | `DP100_S101_20250705` |
| Fingerprint | `rockchip/rk3326_go/rk3326_go:8.1.0/OC/020325:user/release-keys` |
| ABI | `armeabi-v7a` |
| Display | 1280×800, 160 dpi |
| RAM | 976,548 KiB total |
| WebView | `com.android.webview` 61.0.3163.98 |
| Frameo | `/system/priv-app/Frameo`, v1.27.3, version code 54680 |
| USB configuration after ADB | `mtp,adb` |
| Root | shipped `/system/xbin/su`; `adb root` also works |
| Storage | logical NAND `rknand0`, 60,555,264 sectors |
| Userdata | sector 6,538,240; mounted via `dm-0` as F2FS |
| System / vendor / OEM | ext4, mounted read-only |

Kernel command line reports `storagemedia=nand`, verified-boot state `orange`,
`oem_unlocked=0`, and `veritymode=enforcing`. Do not substitute existing eMMC
device guides or assume a logical NAND image contains physical NAND/OOB data.

### Boot-format preflight

A read-only backup preflight verified a 4 KiB transport hash, then stopped on
the expectation of `ANDROID!` boot magic. No backup was captured at that stage.
Independent reads showed `KRNL` wrappers for boot, kernel and recovery, and
`LOADER  ` for uboot. Boot starts with `4b524e4c28e71400` followed by gzip magic
`1f8b`; its wrapper advertises 1,369,896 payload bytes. The capture preflight was
corrected to check this unit's observed format. No boot modification is planned.

### Root ADB and backup transport

`adb exec-out` through shipped SuperSU translates LF bytes to CRLF: a 4,096-byte
boot probe arrived as 4,106 bytes. Base64 inside `su -c` preserves the payload;
the decoded probe matched the on-device hash. Compression before base64 improved
transfer speed, but this route was still slow.

`adb root` reported `restarting adbd as root`. USB authorization was required
again; owner accepted with "Always allow". A fresh `adb shell id` confirmed UID 0.
This allows direct binary reads without `su` or base64; the 4 KiB probe matched
the on-device hash. Restarting ADB interrupted the running capture, which was
retained privately with an `INCOMPLETE` filename. The direct-root capture starts
from sector zero. This restarts only adbd; no boot or system partition was edited.

A private live archive of `/data/system`, `/data/misc`, `/data/property` and
`/data/data/net.frameo.frame` passed gzip/tar checks (538 entries, 1,604,065 bytes
compressed). This is not an atomic userdata snapshot, excludes photos and most
app data, and skips tar warnings for live special files. Firmware verification
is tracked separately.

The first complete direct-root capture passed byte count, gzip readback and
`0xCC` checks, plus fresh hashes for uboot, trust, resource, kernel, boot,
recovery, system and vendor. Verification stopped on an OEM mismatch. Two
fresh 128 MiB OEM reads were identical; each differed from the capture in just
one byte, partition offset `0x1702b`, changing `0x00` to `0x02`. The containing
page starts with JBD journal magic `c03b3998`. This closely matches the journal
flag change described in [PR #21](https://github.com/wesbos/photo-frame-dashboard/pull/21).
Its cause on this unit is unproven; the first verification used `su -c` even
though adbd was root. The mismatched capture is retained as `INCOMPLETE`.
A fresh capture uses direct root commands throughout, including hashes, and
must pass all comparisons before any setup changes.

The subsequent whole-disk stream stalled while USB ADB stayed responsive; its
cause is unproven. It was stopped and retained as `INCOMPLETE`. A separate
whole-disk seek test at `bs=65536 skip=40000` (2,621,440,000 bytes) returned
`Invalid argument`, matching the >2 GiB seek issue in PR #21. The next capture
reads the initial 8 MiB from `rknand0`, then each contiguous partition node up
to userdata in chunks of at most 64 MiB. Every partition's start and size is
checked against sysfs, and every chunk must return its exact expected length.
All seeks within these individual nodes remain below 2 GiB. This changes the
read method, not the expected backup region or validation criteria.

### Verified firmware backup (2026-10-12)

The bounded capture completed and passed every comparison, including OEM.
Private file: `backups/veswwe-dp100/nand-firmware-0-6538240.img.gz`.

- Scope: logical NAND sectors 0–6,538,239, everything before userdata.
- Exact raw size: 3,347,578,880 bytes; compressed size: 733,397,709 bytes.
- Stream SHA-256 matched the decompressed gzip readback SHA-256. Full-region
  hashes remain private in `firmware-validation.json`.
- No aligned 4 KiB block consisted entirely of `0xCC` filler.
- Independent full-partition SHA-256 re-reads matched uboot, trust, resource,
  kernel, boot, recovery, system, vendor, OEM and FRP.
- Entire 32 MiB boot partition SHA-256:
  `ed20bcc018f068d9057a9b8fcc5f6ab6b090c8fc8eec0bf5bfda3b649e58031b`.

This is a verified logical firmware capture, not a complete physical NAND/OOB
backup or a full userdata snapshot. Loader/recovery restoration remains untested.
All interrupted or mismatched captures remain privately named `INCOMPLETE` and
must not be used as restoration sources.

### Logical NAND partition map

Read from sysfs and `/dev/block/by-name`; all values are 512-byte sectors.

| Node | Name | Start | Size |
| --- | --- | --- | --- |
| rknand0p1 | uboot | 16384 | 8192 |
| rknand0p2 | trust | 24576 | 8192 |
| rknand0p3 | misc | 32768 | 8192 |
| rknand0p4 | resource | 40960 | 32768 |
| rknand0p5 | kernel | 73728 | 65536 |
| rknand0p6 | boot | 139264 | 65536 |
| rknand0p7 | recovery | 204800 | 131072 |
| rknand0p8 | backup | 335872 | 393216 |
| rknand0p9 | security | 729088 | 8192 |
| rknand0p10 | cache | 737280 | 786432 |
| rknand0p11 | system | 1523712 | 3932160 |
| rknand0p12 | metadata | 5455872 | 32768 |
| rknand0p13 | vendor | 5488640 | 786432 |
| rknand0p14 | oem | 6275072 | 262144 |
| rknand0p15 | frp | 6537216 | 1024 |
| rknand0p16 | userdata | 6538240 | 54016991 |

### Installed apps

Rootless Pixel Launcher 3.9.1 from F-Droid: SHA-256
`7fa44d560dc4577374d45176220de2c0b00a71e09d6d148cdea4e0a52d38404a`,
matching the repo's pin. Its APK signature verifies and minimum API is 21.

Firefox 157.0.1 from Mozilla's official Fenix archive
(`https://archive.mozilla.org/pub/fenix/releases/157.0.1/android/`, `armeabi-v7a` build): SHA-256
`a7682f654e0573413fbc0049267b7b2b483eb3406a7e4372a8ddad829c00f51c`.
Its APK signature verifies, minimum API is 26, and ABI is `armeabi-v7a`.
Signing certificate SHA-256 is
`a78b62a5165b4494b2fead9e76a280d22d937fee6251aece599446b2ea319b04`,
matching the repo's hash-verified Firefox 143.0.4 reference APK. Both APKs were
subsequently installed successfully. Firefox provides its own engine, avoiding
a system WebView swap.

### Approved reversible setup

Owner explicitly approved installing Firefox and Rootless Pixel Launcher,
setting the launcher as HOME, disabling Frameo and both vendor updaters, and
reboot verification on 2026-10-12. Implementation results follow below.

Before setup, the vendor updaters `com.adups.fota` 5.26 and
`android.rockchip.update.service` 1.8.1 were enabled, and Frameo was HOME.
Setup installed the launcher and Firefox, switched HOME to the launcher, and
disabled Frameo and both updaters for user 0, after verifying the replacement HOME.

Undo the package disables with `pm default-state --user 0 <package>` (their
original state is default, `enabled=0`), restore Frameo as HOME, then uninstall
the replacement apps. No boot flash, system remount or vendor APK deletion is
needed.

### Setup performed (2026-10-12)

USB ADB commands below use the official platform-tools prepared locally. All
changes were approved by the owner after firmware backup verification.

| Change | Command | Undo |
| --- | --- | --- |
| Install launcher | `adb -d install rootless-pixel-launcher-3.9.1.apk` | After restoring Frameo HOME: `adb -d uninstall amirz.rootless.nexuslauncher` |
| Set launcher as HOME | `adb -d shell cmd package set-home-activity --user 0 amirz.rootless.nexuslauncher/com.google.android.apps.nexuslauncher.NexusLauncherActivity` | Re-enable Frameo, then set HOME to `net.frameo.frame/.ui.activities.AWaitForDeferredInitCompleted` |
| Install browser | `adb -d install firefox-157.0.1-armeabi-v7a.apk` | `adb -d uninstall org.mozilla.firefox` |
| Disable FOTA | `adb -d shell pm disable-user --user 0 com.adups.fota` | `adb -d shell pm default-state --user 0 com.adups.fota` |
| Disable Rockchip updater | `adb -d shell pm disable-user --user 0 android.rockchip.update.service` | `adb -d shell pm default-state --user 0 android.rockchip.update.service` |
| Disable Frameo | `adb -d shell pm disable-user --user 0 net.frameo.frame` | `adb -d shell pm default-state --user 0 net.frameo.frame` |

Both installs reported `Success`, and installed versions read back as 3.9.1 and
157.0.1. Before disabling Frameo, HOME resolved to the new launcher; an explicit
launch completed with `Status: ok` and it was the resumed activity. The three
disabled packages each read back as `enabled=3` (`disabled-user`). Launching
HOME still worked afterward, with no running process for those three packages.
`persist.sys.usb.config` and `sys.usb.config` both read `mtp,adb` before reboot.
After a normal reboot, `sys.boot_completed=1`, authorized USB ADB returned
without another prompt as UID 2000, and the new launcher was both the resolved
HOME and resumed activity. All three vendor packages remained `enabled=3`,
with no running process for them. A Mac-served page through `adb reverse` was
visually verified in Firefox, including a JavaScript-generated result, with
the owner's router internet block retained.

An ADB package-only `MAIN`/`LAUNCHER` start could not resolve Firefox. Explicit
starts of `org.mozilla.firefox/org.mozilla.fenix.HomeActivity` and its launcher
alias `org.mozilla.firefox/.App` succeeded. The latter also worked after reboot.
No component was manually enabled. This shell invocation failure should not be
treated as evidence that the launcher shortcut is broken.

### Home button

The owner found there was no way to return from an app to HOME. Stock framework
resources set `navigation_bar_height`, `navigation_bar_height_landscape` and
`status_bar_height` to 0dp. The native NavigationBar window exists but has zero
height; immersive settings and status-bar disable flags were clear. A removable
framework resource-overlay APK installed, but this firmware did not register it
with OverlayManager and the bar stayed zero-height. That test APK was uninstalled;
the existing vendor overlay was left intact.

The [Frame Home helper](../scripts/home-button/README.md) was built and installed
instead. Its draggable floating house launches the default HOME activity without
root, accessibility services or key injection. Its manifest has no internet
permission. Special access was granted with:

```sh
adb -d shell appops set com.photoframe.homebutton SYSTEM_ALERT_WINDOW allow
adb -d shell am start -n com.photoframe.homebutton/.HomeSettingsActivity
```

After tapping **Show Home button**, the foreground service and overlay were
visually verified. A tap from Firefox returned to Rootless Pixel Launcher; a
drag moved the button without launching HOME. Following a further normal reboot,
its service started automatically, with the overlay permission preserved and
the saved position restored within the bounds of the current orientation.
The service may not be present at the first instant `sys.boot_completed=1`:
wait for delivery of the boot broadcast before judging startup.

Undo: tap **Hide Home button** in Frame Home, or
`adb -d uninstall com.photoframe.homebutton`. The original zero-height framework
resources and all system APKs remain unchanged.

## Identification still needed

- Label model, to compare with the app's `DP100` designation.
- Buttons, supplied PSU rating, and cable type used in the Mac power test.
- Exact beta-menu and authorization steps used to enable USB ADB.
- Stock network ADB availability, if needed; USB access now works.

Do not infer the SoC, partition layout or a compatible boot image from the
retail brand or screen size.

## Upstream research (not observations of this unit)

Checked upstream issues and pull requests on 2026-10-12. No VESWWE-specific
report appeared in the latest 30 issues or latest 30 pull requests.

- [PR #31](https://github.com/wesbos/photo-frame-dashboard/pull/31) reports a
  Joyhong JT101F-I02 Frameo / Allwinner A33 unit with stock root network ADB.
- [PR #21](https://github.com/wesbos/photo-frame-dashboard/pull/21) reports a
  Pastigio FRAME156 Frameo / Rockchip RK3326 unit.

These are unmerged reports about other units. Neither establishes the hardware
or access method for this VESWWE frame.

- [A Frameo owner's report](https://gist.github.com/Shoggomo/a0fb96ae8acf78d3192e25a082881a26)
  describes Settings → About → Beta Program revealing an ADB Access toggle.
  [ImmichFrame's app documentation](https://github.com/immichFrame/ImmichFrame/blob/main/docs/docs/getting-started/apps.md)
  also describes enabling the Frameo Beta Program as a route to ADB.
  Owner subsequently reported working USB ADB after this suggestion.


### Network hand-off

Retain the router's WAN block and allow only the local access needed for an
owner-controlled page. Disabling Frameo and the two updaters does not constitute
an audit of the rest of this Android 8.1 build (security patch 2020-06-05).
For example, factory `com.cross.browser.info` (`/system/app/HardInfo`, version
5.4.0) remains enabled and declares internet and boot permissions; its network
behavior has not been investigated. Do not describe this setup as safe for
unrestricted internet access. Network ADB was never established or enabled.

A local dashboard server can retrieve external photos/calendar/weather data
while the frame accesses only that server. Such an integration is future work;
the completed test used a local page over USB, not those account integrations.

