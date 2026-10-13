#!/system/bin/sh
# kioskwatch: on firmware with no navigation bar, Settings or a launcher can't be left without a
# power cycle. After IDLE seconds with no touches while another app is in front, bring the kiosk
# back. Needs root (reads the touchscreen with getevent). See scripts/kioskwatch/README.md.
KIOSK=${KIOSK:-com.wesbos.homehq}
IDLE=${IDLE:-120}
TOUCH_NAME=${TOUCH_NAME:-gslX680}
STAMP=/data/local/tmp/kioskwatch.touch

while [ "$(getprop sys.boot_completed)" != 1 ]; do sleep 5; done

DEV=
for d in /sys/class/input/event*; do
  [ "$(cat $d/device/name 2>/dev/null)" = "$TOUCH_NAME" ] && DEV=/dev/input/${d##*/}
done
[ -n "$DEV" ] || { log -t kioskwatch "no input device named $TOUCH_NAME, exiting"; exit 1; }
log -t kioskwatch "watching $DEV, idle limit ${IDLE}s"

touch $STAMP
# Touch stamp: its mtime is the last touch (at most one update every 2 s).
( while true; do getevent -qc1 $DEV >/dev/null 2>&1; touch $STAMP; sleep 2; done ) &

while true; do
  sleep 15
  case "$(dumpsys window windows | grep -m1 mCurrentFocus)" in *$KIOSK/*) continue ;; esac
  idle=$(( $(date +%s) - $(stat -c %Y $STAMP) ))
  if [ $idle -ge $IDLE ]; then
    log -t kioskwatch "no touch for ${idle}s outside the kiosk, returning to it"
    am start -n $KIOSK/.MainActivity >/dev/null 2>&1
    touch $STAMP
  fi
done
