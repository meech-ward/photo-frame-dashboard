# kioskwatch: return to the kiosk when idle (rooted frames)

Some firmware has no SystemUI at all: no navigation bar, no Back or Home. On a PF1007L
(`321-OS-AIMOR.0.20260113`) `pm list packages` shows no `com.android.systemui`. Once you open
Android Settings or a launcher from the kiosk, the only way back is a power cycle.

[Home HQ navigation](../../dashboard/kiosk/README.md#frames-without-home-or-back-buttons) adds
Back and Dashboard buttons without root, and is the first thing to try. `kioskwatch.sh` is a
fallback for frames that already have root ADB. It needs no tap at all: if another app has been
in front for 2 minutes with no touches, it starts the kiosk again. Every touch restarts the
2 minutes, so it won't interrupt someone typing a Wi-Fi password.

How it works: a background `getevent -qc1` on the touchscreen updates a stamp file. Every 15 s
the script checks `mCurrentFocus`, and if it isn't the kiosk and the stamp is older than `IDLE`
seconds, it runs `am start`. It logs to logcat with tag `kioskwatch`.

Settings at the top of the script: `KIOSK` (package, default `com.wesbos.homehq`), `IDLE`
(seconds, default 120) and `TOUCH_NAME`. The default `gslX680` is the PF1007L touchscreen. Find
yours with:

```sh
adb shell 'for d in /sys/class/input/event*; do echo "$d $(cat $d/device/name)"; done'
```

## Try it without changing /system

```sh
adb push scripts/kioskwatch/kioskwatch.sh /data/local/tmp/
adb shell 'nohup sh /data/local/tmp/kioskwatch.sh >/dev/null 2>&1 &'
adb shell am start -a android.settings.WIFI_SETTINGS
# don't touch the frame; about 2 minutes later:
adb shell 'logcat -d -s kioskwatch'
```

It stops at the next power cycle.

## Start it at boot (writes /system, owner approval first)

This needs a boot hook that runs as root. On the PF1007L, `/system/bin/install-recovery.sh` is
started by init as root at every boot. This block checks the file, keeps the first backup, adds one line
after the shebang only once, and always remounts `/system` read-only. **Not yet tested from a cold
boot.**

```sh
adb pull /system/bin/install-recovery.sh install-recovery.sh.before-kioskwatch
adb push scripts/kioskwatch/kioskwatch.sh /data/local/tmp/
adb shell '
f=/system/bin/install-recovery.sh
head -1 $f | grep -q "^#!" || { echo "STOP: $f is missing or not a script"; exit 1; }
grep -q kioskwatch $f && { echo "Already installed; nothing to do"; exit 0; }
mount -o remount,rw /system || exit 1
ok=1
[ -e $f.before-kioskwatch ] || cp $f $f.before-kioskwatch || ok=0
[ $ok = 1 ] && cp /data/local/tmp/kioskwatch.sh /system/bin/kioskwatch.sh \
  && chmod 0755 /system/bin/kioskwatch.sh \
  && sed -i "1a /system/bin/sh /system/bin/kioskwatch.sh >/dev/null 2>&1 &" $f || ok=0
sync
mount -o remount,ro /system
if [ $ok = 1 ]; then head -3 $f; else echo "FAILED: compare $f with $f.before-kioskwatch"; fi'
```

**Undo:** remount `/system` read-write, copy `install-recovery.sh.before-kioskwatch` back over
`install-recovery.sh`, delete `/system/bin/kioskwatch.sh`, remount read-only and power cycle.

Avoid `reboot` and `adb reboot` on the PF1007L: on the unit this was tested on, a software
reboot hangs and only a power cycle restarts it.
