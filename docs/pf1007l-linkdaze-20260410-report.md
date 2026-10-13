# PF1007L report: Linkdaze PF1007BK, April 20260410, temporary ADB without flashing

Tested 2026-10-12/13 from a Linux host with the frame on Wi-Fi and a Windows
host for USB. Read-only tests first (T3/T3b), then the AiMOR-channel route (T3c)
for this exact firmware. No boot image was written; `/system` was later replaced
for WebView 106 after a verified backup (out of scope for this report).

## Tested unit

| Item | Observed value |
| --- | --- |
| Retail model | Linkdaze PF1007BK (box says PF1007BK, About screen says PF1007L) |
| About model / firmware | PF1007L / `YHK.F-null-A33-1001-D1024-PF1007L-321-OS-AIMOR.0.20260410` |
| AiMOR | `com.efercro.os.aimor`, 6.0.78 |
| Android model / hardware | `AEEZO` / `sun8i` (Allwinner A33 family) |
| Android / display | 6.0.1, API 23 / 1280 × 800 |
| Stock WebView | 44.0.2403.119 |
| Ports | USB-C only, TF slot, button |
| eMMC | 30,777,344 sectors (15,758,000,128 bytes) |
| Partition map | boot `mmcblk0p6`, system `mmcblk0p7` (1,073,741,824 bytes), recovery `mmcblk0p9` |
| Boot image (31,028 sectors at sector 172032) | `8ffc2a7d95972422b97ecf7e82da7002011bdacedcbfcc74dd52ae871b98a24e` |
| USB stock | `1f3a:1000` mass storage only, `adb devices` empty |
| Stock network ADB | Port 5555 refused, 8086 open (AiMOR file service) |
| Build tags | `astar_m86_8723cs-eng`, test-keys; `ro.debuggable=1` |

The boot hash matches the April row of the firmware table exactly.

## T3c result

One vendor-channel runtime command (`setprop service.adb.tcp.port 5555;
stop adbd; start adbd`) through a temporary local redirect of
`imsconnect.efercro.com` gave root ADB over Wi-Fi (`uid=0`, no key check),
verified with `sun8i`, Android 6.0.1 and the firmware above. DNS was restored
afterwards. Reboot ends the access. Our redirect ran from a Pi-hole local DNS
override instead of the documented per-host proxy; the frame side is identical.

## Findings worth folding into the guides

1. **Persistent ADB properties work on this firmware.** Both survived a reboot on this
   `ro.debuggable=1` build, with no boot patch and no re-run of the vendor-channel route:
   - USB: `setprop persist.sys.usb.config mass_storage,adb` keeps USB ADB. Prefer this one.
     To turn it off: `setprop persist.sys.usb.config mass_storage`.
   - Wi-Fi: `setprop persist.adb.tcp.port 5555`. **After every boot, port 5555 is root ADB with
     no key check, open to the whole network.** Only use it on a network you control, and turn it
     off with `setprop persist.adb.tcp.port ""` once USB ADB works. Toggling Wi-Fi off and on
     kills the listener until the next boot.

   Each is a write to `/data/property`, so ask the owner first. An AiMOR factory reset clears
   both.
2. **The "set a static IP" advice is not actionable on this unit.**
   Its Wi-Fi settings screen has no Modify/Advanced option, so no static IP can
   be set on the frame. A router DHCP reservation cannot work either: the
   AIC8800 cycled through seven distinct MACs and just as many DHCP addresses in
   one evening, one per Wi-Fi reconnect. The first four bytes of the MAC stayed
   the same. Find the frame by that prefix in your router's or computer's ARP
   table, then confirm with a TCP 5555 probe and `getprop ro.serialno`, rather
   than relying on a static IP.
3. **USB-C to C carries nothing**, confirming the A-to-C rule: no power, no
   device. A USB-A port (via adapter on USB-C-only hosts) plus an A-to-C data
   cable enumerates `1f3a:1000` immediately.
4. **Kiosk at boot:** a local build with a Home filter and a boot receiver
   opened the dashboard on a cold boot with no touches. The repo's kiosk now
   does this without a code change: enable it as Home with `--ez home true`
   ([kiosk README](../dashboard/kiosk/README.md#start-at-boot)).
