# PF1007 May firmware on macOS: the eMMC fails after HS_TIMING=1, legacy timing fixes it

One PF1007 on `V10-1680.0.20260529`, rooted with Route U from an Apple silicon Mac on
2026-10-13. Stock ADB was off. The FEL U-Boot found the SD card but not the eMMC, in the base
build, with the [START STOP patch](patches/pf1007l-v2025.10-start-stop.patch), and at 4-bit / 26 MHz.

An MMC trace showed the cause. The eMMC accepted the switch to 4-bit, then accepted the switch to
high-speed timing (`HS_TIMING=1`), and then never answered again. U-Boot printed
`unable to select a mode: -1`, the same message as [#41](pf1007l-windows-20260529-report.md),
which used 1-bit at 25 MHz. A build that removes only the high-speed host capabilities, and keeps
4-bit at up to 26 MHz, exposed the full eMMC. The backup, the guarded boot patch and the full
readback all passed with that build.

Observed on one unit. Not tested: whether 8-bit works with legacy timing, or whether other
May units with the 30,535,680-sector eMMC need this.

## Report

```text
About model / firmware:   PF1007; fingerprint AEEZO/astar_m86_8723cs/astar-m86_8723cs:6.0.1/MOB30R/20260529:eng/test-keys
AiMOR version:            6.0.78
Ports (DC jack, or USB-C only): USB-C only, TF slot
Cable and port that gave USB data: USB-A to USB-C data cable, Mac port (the first cable gave no data)
T3 USB IDs seen / adb devices output: 1f3a:1000; adb devices empty
T3b network ADB result (port 5555): not tested; the frame stayed off Wi-Fi
T4 sunxi-fel version output: AWUSBFEX soc=00001667(A33) 00000001 ver=0001 44 08 scratchpad=00007e00 00000000 00000000
T5 check-dump stage / chunks: skipped (Route U)
eMMC size in sectors:     30,535,680 (Samsung, product name MAG2GC)
Boot partition start sector: 172032
Boot image SHA-256 (sector 172032, 31,028 sectors):
                          6c118dc1aa583797884c33cd3ac3796c72b2bd3a3f1fcafd1bf0982ae5f29e2c
Route used and result:    Route U with the START STOP patch and the no-HS patch below:
                          read-only backup, guarded boot patch, full readback -> 1f3a:1002,
                          adb -d shell id = uid=0(root)
Host OS:                  macOS 26.5.1, Apple silicon; OrbStack for Docker
First failed step and its exact output: Route U section 4: only the SD card appeared as a ums disk.
                          FEL U-Boot: "unable to select a mode: -1" for mmc 1
```

## What happened, in order

| Step | Result |
| --- | --- |
| Route U base build | `ums` showed one disk: the SD card. No eMMC |
| START STOP patch, `CONFIG_SYS_DEVICE_NULLDEV` | The same. The SD card disk was stable |
| Also 4-bit, `max-frequency = <26000000>` | The same |
| Diagnostic build: console log kept in SRAM A2 at `0x48000`, as in #24 | No log. On this unit, SRAM A2 did not keep its content through the watchdog reset |
| Diagnostic build: console log in DRAM, saved to the SD card with `fatwrite` (see below) | Full log with `CONFIG_MMC_TRACE`. It showed the failure below |
| 4-bit, up to 26 MHz, **no high-speed host capabilities** | Both disks appeared. The eMMC was `UMS disk 1`, 15,634,268,160 bytes, read-only |
| `emmc-macos.py backup-resume` | 15 segments, each read twice from the disk and once from the file. Passed |
| T6 | Boot at sector 172032, SHA-256 `6c118dc1…`, the same as #8, #16, #28 and #41 |
| `boot-patch.py` | Ramdisk `[192004, 203060)`, header `[172032, 172034)`, the same as the [May report](pf1007l-macos-20260529-report.md) |
| Guarded write with the same no-HS build, hardened scripts (see below) | `emmc-macos.py verify-resume`: "Verified: the eMMC equals the backup plus exactly the planned boot patch." |
| Normal start, card removed | `1f3a:1002`; `adb -d shell id` = `uid=0(root)` |

## The failure in the MMC trace

With `CONFIG_MMC_TRACE`, `mmc dev 1` at 4-bit and 26 MHz showed this. The eMMC is in transfer
state (`CURR STATE:4`) after the bus-width switch, and stops answering after the timing switch:

```text
CMD_SEND:6
		ARG			 0x03b70100      <- EXT_CSD[183] BUS_WIDTH = 1 (4-bit)
		MMC_RSP_R1b		 0x00000900
CMD_SEND:13
		ARG			 0x00010000
		MMC_RSP_R1,5,6,7 	 0x00000900
CURR STATE:4
CMD_SEND:6
		ARG			 0x03b90100      <- EXT_CSD[185] HS_TIMING = 1
		MMC_RSP_R1b		 0x00000900
CMD_SEND:13
		ARG			 0x00010000
		RET			 -110
```

The CMD13 status polls after it all returned `-110`, and U-Boot printed
`unable to select a mode: -1`. The SD card on `mmc 0` worked in the same run, in SD High Speed
at 50 MHz.

`max-frequency` and `bus-width` do not prevent the switch: the sunxi driver always sets
`MMC_MODE_HS_52MHz | MMC_MODE_HS` in `host_caps`, so U-Boot tries `HS_TIMING=1` at any clock.
This is probably why 4-bit / 26 MHz did not help here, and why #41's 1-bit legacy build worked.

## The fix

[`patches/pf1007l-v2025.10-no-mmc-hs.patch`](patches/pf1007l-v2025.10-no-mmc-hs.patch) applies on
top of `pf1007l-uboot.patch`. Apply it inside the disposable build container, to the copy of
`diagnostics/u-boot`, as the [May report's recipe](pf1007l-macos-20260529-report.md) does, and use
a separate output directory. Never patch `diagnostics/u-boot` itself: `build-uboot.sh` then refuses
to run because the tree has changes other than its own patch.

- The eMMC node gets `bus-width = <4>`, `max-frequency = <26000000>` and a
  `pf1007l,no-mmc-hs` property.
- `sunxi_mmc.c` clears `host_caps` when the node has that property. The other MMC controllers
  are not changed.

U-Boot then keeps the eMMC in legacy timing. The tested build also had the START STOP patch and
`CONFIG_SYS_DEVICE_NULLDEV` with `setenv stdin nulldev`, as in the
[May report's build](pf1007l-macos-20260529-report.md). To reproduce it, copy the source as that
report does, then apply both patches before `make`. These lines go inside the May recipe, which
also has the `docker run`, the `ums-readonly.cmd` with `setenv stdin nulldev` and the SPL size
check. Don't run them on their own:

```sh
patch --dry-run --fuzz=0 -p1 < /patches/pf1007l-v2025.10-start-stop.patch
patch --fuzz=0 -p1 < /patches/pf1007l-v2025.10-start-stop.patch
patch --dry-run --fuzz=0 -p1 < /patches/pf1007l-v2025.10-no-mmc-hs.patch
patch --fuzz=0 -p1 < /patches/pf1007l-v2025.10-no-mmc-hs.patch
make O=/build pf1007l_backup_defconfig
scripts/config --file /build/.config --enable SYS_DEVICE_NULLDEV
make O=/build olddefconfig && make O=/build -j"$(nproc)"
```

The SPL ended at `0x456a`, well inside the `0x5e00` limit. The tested binary was made with the
same edits applied by a script; a rebuild from the patch files differed only in build timestamps
and the checksums that cover them.

## A console log that survives the reset (record, not a procedure)

The frame has no serial console, and this unit reset into FEL before a host could read SRAM.
This diagnostic build kept the log in DRAM and saved it to the FEL card:

- `common/console.c`: after relocation, `membuf_init(&gd->console_out, (char *)0x46000000, 0x100000)`
  instead of `membuf_new` (`CONFIG_CONSOLE_RECORD=y`), so the record buffer has a fixed address.
- `CONFIG_MMC_TRACE=y` prints every MMC command and response.
- The boot script ran read-only queries (`mmc list`, `mmc dev 1`, `mmc info`, `mmc rescan`,
  `mmc dev 0`), then saved the whole buffer to the card's FAT partition, and reset:

  ```text
  if fatload mmc 0:1 0x45000000 PFDIAG.TXT; then fatwrite mmc 0:1 0x46000000 UBLOG.TXT 0x100000; fi
  reset
  ```

  It writes only if a marker file (`PFDIAG.TXT`), which the owner put on that FAT partition,
  is present. This keeps the write off the eMMC.

This writes to the FEL card's FAT partition, so ask the owner first. It does not write to the eMMC.

## The write step

`boot-patch.py` makes the guarded scripts. Before the write, the generated scripts were
changed as in the [May report's stronger guards](pf1007l-macos-20260529-report.md#stronger-generated-write-script-guards):
null console, `mmc dev`, both preflight reads, four CRCs and two compares in one condition;
the header is written only after the ramdisk write, readback and compare pass; then a header
readback and compare; then `ums 0 mmc 1`. A Bash stub harness ran 19 failure cases plus success
for both the apply and the restore script. Every failure stopped before the next write, and every
case ended in `ums`.

Because the write script runs `ums 0 mmc 1`, the eMMC appears as **`UMS disk 0`**, not
`UMS disk 1` as in the backup step. Give the verify step that disk.

## After root

These matched the [PF1007L guide](allwinner-a33-pf1007l.md) and needed no changes:

- Rootless Launcher 3.9.1, then `pm disable` for `com.efercro.os.aimor`, `com.yhk.qeota`
  (`API_10-usaFrame-P-L_Yes-20240603`) and `com.DeviceTest`. All three showed `enabled="2"`
  two seconds later and stayed disabled after a power cycle. No connection to port 7806.
  The way back is root ADB over USB from the boot patch, which does not need AiMOR
  (compare [#56](pf1007l-20260410-network-adb.md)).
- WebView 106.0.5249.126 with its three ARM libraries, as in section 6 of the guide.
  405,824 KiB were free on `/system` before the swap. After the restart: no `dlopen` errors,
  and the kiosk rendered a local test page with JavaScript.

Notes for testing WebView without the kiosk:

- `com.android.htmlviewer` uses the system WebView, so it shows whether the engine loads. It has
  JavaScript turned off.
- HTML Viewer cannot read `/sdcard`: a test page there gave `ERR_ACCESS_DENIED`. A world-readable
  file in `/data/local/tmp` worked.

Sensors, from `dumpsys sensorservice`: a Silan SC7A20 3-axis accelerometer, an LTR-C216R light
sensor and an `AW.` temperature sensor. No gyroscope.
