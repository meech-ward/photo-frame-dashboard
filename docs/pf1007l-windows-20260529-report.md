# PF1007 May 2026 firmware: Windows/WSL and hosted dashboard report

One PF1007 running the May AiMOR firmware reached root USB ADB and a working
Cloudflare Pages dashboard. After selecting the kiosk as Home, the owner confirmed
automatic dashboard startup with the frame connected to wall power and USB
disconnected. Observed on 2026-10-11 and 2026-10-12.

This corroborates the [May macOS report](pf1007l-macos-20260529-report.md), but the
local ADB-enabling experiment changed a persistent USB property in userdata,
not the boot image or `/system/build.prop`. It is **not a published rooting route**:
do not reuse another unit's raw-disk offsets or payloads. Follow the
[start-page tests](pf1007l-start-here.md) first, including stock USB/network ADB checks.

## Unit report

```text
About model / firmware: PF1007; Android model property AEEZO; Android 6.0.1
  YHK.F-null-A33-1001-D1024-PF1007L-V10-1680.0.20260529
AiMOR version: 6.0.78 (code 78)
Ports: USB-C used for USB data; full port inventory not recorded
Cable and port that gave USB data: USB-A host port to USB-C frame
T3 USB IDs / ADB: no usable stock USB ADB established in this session;
  after the local property change, 1f3a:1001 and root adb shell
T3b network ADB result (port 5555): no conclusive stock result retained
T4 FEL: 1f3a:efe8; AWUSBFEX soc=00001667(A33)
T5 check-dump stage / chunks: not used; FEL/U-Boot USB storage used instead
eMMC size: 30,535,680 sectors of 512 bytes = 15,634,268,160 bytes
Boot partition start sector: 172032
Boot image SHA-256, first 31,028 sectors:
  6c118dc1aa583797884c33cd3ac3796c72b2bd3a3f1fcafd1bf0982ae5f29e2c
Route used and result: local read-only UMS backup, guarded persistent USB-property
  change in userdata, then root USB ADB; boot image unchanged
Host OS: Windows, PowerShell, Ubuntu WSL 2, usbipd-win and Docker
First useful MMC diagnostic failure: "unable to select a mode: -1"
```

The case was not opened; PCB and physical chip markings were not inspected.
The frame's boot-menu options were backup, restore, clear, reset network and
factory reset. These menu options did not establish FEL access; FEL was obtained
using the SD boot stub. The SD boot medium was removed for normal Android boot.

## FEL, eMMC and Windows disk observations

- `usbipd-win` attached the `1f3a:efe8` FEL device to Ubuntu WSL 2. `sunxi-fel
  version` positively identified A33. Uploading U-Boot changes the USB device;
  FEL disappearing after that does not alone mean the upload failed.
- Earlier local U-Boot 2025.10 Q8-based builds exposed the approximately 7.4 GiB
  removable SD medium, not the internal eMMC. An enumerated UMS disk alone was
  therefore insufficient evidence that the correct storage was available.
- A local build based on U-Boot commit
  `6d41f0a39d6423c8e57e92ebbe9f8c0333a63f72`, using
  `sun8i-a33-sinlinx-sina33`, initialized the eMMC with **1-bit, 400 kHz, legacy
  timing** in a diagnostic run. A subsequent **1-bit, maximum 25 MHz, legacy
  timing** configuration exposed the internal eMMC for the backup. MMC validation
  checks were retained. This does not establish which single setting was decisive,
  or that faster/wider modes cannot work on this unit.
- The successful USB storage ID was `1f3a:1010`. `usbipd list` showed it as
  **Not shared** while Windows accessed it; that state was appropriate for Windows
  disk reads. `Get-Disk` did not list it, but `Win32_DiskDrive` did.
- Windows' reported disk size differed from the exact capacity returned by
  `IOCTL_DISK_GET_LENGTH_INFO`. The exact result was 15,634,268,160 bytes. The
  read-only UMS build rejected the host write probe with `ERROR_WRITE_PROTECT`.
- The backup completed two full-device read passes, matching the saved-image
  SHA-256, exact size, a complete gzip decompression readback and a scan for
  4 KiB runs of `0xCC`. Boot and recovery were also reread and matched the original
  backup. **The local Windows full-read script did not explicitly bypass the host
  cache**, so these passes do not prove two independent physical-device reads.
  The current repository's backup tools and checks should be preferred. This backup does not fully
  meet the repository's [backup rule](../README.md#rules-we-learned-the-hard-way).

The local ADB change preserved the persistent property's file size, replacing
`mass_storage` with NUL-padded `adb`. The complete affected sector was read back
and checked before Android boot. Once Android rewrites a persistent property
file, restoring the old raw sector is not a safe undo method; the property service
or a separately validated recovery plan is needed. No offset, dump or reusable
write script from this experiment is included here. To turn it off again, use
`setprop persist.sys.usb.config mass_storage` as root; an AiMOR factory reset also clears `/data/property`.

## Android and hosted dashboard result

Rootless Launcher 3.9.1 provided a working Android Home screen and an escape target.
The stock WebView was 44.0.2403.119. WebView 106.0.5249.126 was installed with its
three ARM native libraries, verified by file readback; the original WebView tree
was preserved and `/system` returned to read-only.

The kiosk initially showed a white screen when loading the Cloudflare Pages HTTPS
site. Starting its activity returned `Status: ok`, but the saved Chromium log
contained `SSL error code 1, net_error -202`. The frame's clock was current;
the saved stock trust store and live filename check showed ISRG Root X1 absent.

The ISRG Root X1 certificate from [Let's Encrypt](https://letsencrypt.org/certificates/)
was checked against the independent [Mozilla CA bundle distributed by curl](https://curl.se/docs/caextract.html)
and the fingerprint recorded in the
[U-Boot guide](allwinner-a33-mainline-uboot.md#8-notes-from-this-unit-after-root).
It was added as `/system/etc/security/cacerts/6187b673.0`, root:root, mode 0644,
with PEM first and the certificate text/fingerprint following. The complete file
was read back and its SHA-256 matched; `/system` was remounted read-only.
After force-stopping and relaunching the kiosk, the owner saw the hosted dashboard.
TLS error handling was not bypassed.

The locally built Home HQ 1.1 kiosk declared `HOME` (today's kiosk needs `--ez home true` for that;
see the [kiosk README](../dashboard/kiosk/README.md#start-at-boot)), saved the hosted URL and
retried failed page loads. Its two-finger hold explicitly launched Rootless
Launcher; the owner confirmed reaching that launcher. AiMOR (`com.efercro.os.aimor`),
the vendor updater (`com.yhk.qeota`) and `com.DeviceTest` were disabled after their
original package states were saved. All three `enabled="2"` entries were checked
in the saved package-restrictions XML before the power cycle.

Android's Home settings accepted **Home HQ** immediately, with no separate OK
button. The owner then confirmed a cold start on wall power, with USB disconnected,
automatically opened the hosted dashboard over Wi-Fi. No computer server was
needed. This was a successful startup observation, not a long-duration reliability
test; vendor package/process states were not independently reread after that boot.
The dashboard still contained the repository's sample data, not live personal calendars.
