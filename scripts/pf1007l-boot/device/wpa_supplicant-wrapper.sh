#!/system/bin/sh
# Installed as /system/bin/wpa_supplicant; the real binary is moved to wpa_supplicant.real.
# Sets the Wi-Fi MAC from /data/local/frame-boot.conf before wpa_supplicant associates, so DHCP
# never sees the random MAC the AIC8800 driver picks at each load.
CONF=/data/local/frame-boot.conf
[ -r $CONF ] && . $CONF
if [ -n "$MAC" ]; then
    i=0
    while [ ! -e /sys/class/net/wlan0/address ] && [ $i -lt 10 ]; do
        sleep 1
        i=$((i + 1))
    done
    cur=$(cat /sys/class/net/wlan0/address 2> /dev/null)
    if [ -n "$cur" ] && [ "$cur" != "$MAC" ]; then
        ip link set wlan0 down
        ip link set wlan0 address $MAC
        log -t frame-fixmac "wpa_supplicant start: wlan0 $cur -> $MAC"
    fi
fi
exec /system/bin/wpa_supplicant.real "$@"
