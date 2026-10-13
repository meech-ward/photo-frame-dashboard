#!/system/bin/sh
# PF1007L boot fixes. install.sh adds one line to /system/bin/install-recovery.sh that runs this
# file; init runs install-recovery.sh as root early in every boot (service flash_recovery).
# Settings: /data/local/frame-boot.conf (see frame-boot.conf.example).
# init kills the whole service process group when the main process exits, so this file must end
# with an exec of a process that never exits (frame-fixmac.sh loops forever).
CONF=/data/local/frame-boot.conf
[ -r $CONF ] && . $CONF
B=/system/bin

[ "$POWER_FIX" = 1 ] && $B/sh $B/frame-powerfix.sh &

# Hide the Wi-Fi driver from Android's boot-time load; frame-wifidefer.sh removes this bind mount
# and starts Wi-Fi once boot has completed. The mount ends at reboot.
if [ "$WIFI_DEFER" = 1 ] && [ -n "$WIFI_DRIVER" ] && [ -e "$WIFI_DRIVER" ]; then
    : > /data/local/frame-empty.ko
    mount -o bind /data/local/frame-empty.ko "$WIFI_DRIVER"
fi
$B/sh $B/frame-wifidefer.sh &
$B/sh $B/frame-timesync.sh &
exec $B/sh $B/frame-fixmac.sh
