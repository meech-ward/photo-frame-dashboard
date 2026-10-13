# VESWWE DP100 that reports DP101 (Android 10, `ceres` platform)

A record of **one unit**, set up on 2026-10-13. Its About screen says `VESWWE DP100`, like the
frame in [veswwe-10.1.md](veswwe-10.1.md), but ADB shows a different board and Android version.
Nothing from the RK3326 docs or `scripts/` applies to it. Check `ro.product.model` and
`ro.board.platform` before following either page.

End result: Home HQ is the Home app and boots into the dashboard, touch works, Frameo is disabled
and the Adups updater is removed for user 0. No root, WebView swap, backup image, boot patch or
flash was needed. Everything below is reversible over ADB.

**Tested on:** one unit, bought from [Amazon.ca B0H2FC19YB](https://www.amazon.ca/dp/B0H2FC19YB),
from a Mac (Apple silicon, macOS 26) with Google's platform-tools 37.0.1 over USB.

## Identity

| Field | Value seen on this unit |
| --- | --- |
| About screen | `VESWWE DP100`, Frameo `v1.32.12 (78070)` |
| `ro.product.model` | `DP101` |
| `ro.board.platform` | `ceres` |
| Android | 10 |
| `ro.build.display.id` | `DP101_Frameo_V02_26061607` |
| `ro.product.cpu.abi` | `armeabi-v7a` |
| Display | `wm size` 800x1280 (shown landscape), 68 Hz, density **190** (188 × 189 dpi) |
| WebView | `com.android.webview` 113.0.5672.136 (version code 567263600), the only WebView package |
| Home app (stock) | `net.frameo.frame/.ui.activities.AWaitForDeferredInitCompleted` |
| Vendor packages | `net.frameo.frame`, `com.adups.fota` |
| Screen defaults | `screen_off_timeout` 2147483647, `stay_on_while_plugged_in` 0, brightness 178 (manual) |

Not recorded: SoC (see Guesses), kernel, RAM, USB IDs, the cable used, and the result of
`su -c id` (the command printed nothing before the session was interrupted). Root was not needed.

## Setup that worked

1. **ADB:** Frameo Settings → About → **Enable Beta Program**, then **ADB access**. `adb devices`
   showed the frame as `device` after accepting the prompt.
2. **Install and set as Home** (from [the kiosk README](../dashboard/kiosk/README.md)):

   ```sh
   adb install -r homehq.apk
   adb shell am start -n com.wesbos.homehq/.MainActivity --es url https://your-dashboard/
   adb shell am start -n com.wesbos.homehq/.MainActivity --ez home true
   adb shell cmd package set-home-activity com.wesbos.homehq/.Home
   adb shell pm grant com.wesbos.homehq android.permission.WRITE_SECURE_SETTINGS
   ```

   `cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME`
   then returned `com.wesbos.homehq/.Home`. The Home HQ navigation service was listed in
   `enabled_accessibility_services` before and after a reboot.
3. **Density:** at the stock density of 190 the bottom of a 1280×800 dashboard was cut off. This
   fixed it (owner confirmed the dashboard fits):

   ```sh
   adb shell wm density 160      # undo: adb shell wm density reset
   ```

   `wm density` showed `Override density: 160` after a reboot. A dark band along two edges of the
   screen is the bezel: `dumpsys display` reports an app area of the full 800×1280.
4. **Wi-Fi check before disabling Frameo:** `dumpsys wifi | grep -m1 mWifiInfo` showed the network
   connected (`Supplicant state: COMPLETED`), so Wi-Fi is stored in Android, not only in Frameo.
   It reconnected after the reboot with Frameo disabled.
5. **Frameo and Adups:**

   ```sh
   adb shell pm list packages -s -e > frame-packages-backup.txt
   adb shell pm disable-user --user 0 net.frameo.frame
   adb shell pm disable-user --user 0 com.adups.fota
   ```

   After a reboot both were listed as disabled, but `com.adups.fota` was still running, with a new
   PID on each check (5544, then 5995). Removing it for user 0 stopped it; no `frameo` or `fota`
   process was running afterwards:

   ```sh
   adb shell pm uninstall -k --user 0 com.adups.fota
   ```

6. **Reboot:** the Frameo boot logo appears, then Home HQ's "Connect to Wi-Fi?" screen for about a
   minute while Wi-Fi connects, then the dashboard. Touch works.

USB ADB still connected after the reboot with Frameo disabled. Checked by hand on the panel: a
two-finger hold opened the Home HQ controls, **Android settings** opened Settings, Apps listed Frameo
as disabled, and the floating **Dashboard** button returned to the kiosk (README rule 9).

## Undo

```sh
adb shell cmd package install-existing com.adups.fota
adb shell pm enable com.adups.fota
adb shell pm enable net.frameo.frame
adb shell cmd package set-home-activity net.frameo.frame/.ui.activities.AWaitForDeferredInitCompleted
adb shell wm density reset
```

To undo the kiosk as Home, see the [kiosk README](../dashboard/kiosk/README.md#start-at-boot).

## Guesses

- `ceres` is probably an Allwinner Android 10 platform name, but the SoC was not read from
  `/proc/cpuinfo` or USB IDs on this unit.
- Why density 190 clipped the page: the WebView lays out in CSS pixels of 160/190 device pixels,
  so a 1280×800 screen becomes about 1078×674 CSS pixels, and a page built for 1280×800 does not
  fit. Not measured on the device.
- The Frameo boot logo is in the firmware's boot image; changing it was not attempted.
