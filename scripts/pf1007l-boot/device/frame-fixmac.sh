#!/system/bin/sh
# Keep the Wi-Fi MAC at MAC from /data/local/frame-boot.conf. The AIC8800 has no stored MAC, so the
# driver picks a random one each time it loads. The wpa_supplicant wrapper sets the MAC before Wi-Fi
# associates; this loop is the backstop. Based on frame-fixmac.sh from wesbos/photo-frame-dashboard
# PR #6. Runs forever: frame-boot-hook.sh execs it to keep the boot service alive.
CONF=/data/local/frame-boot.conf
[ -r $CONF ] && . $CONF
while true; do
    if [ -n "$MAC" ] && [ -e /sys/class/net/wlan0/address ]; then
        cur=$(cat /sys/class/net/wlan0/address)
        if [ "$cur" != "$MAC" ]; then
            ip link set wlan0 down
            ip link set wlan0 address $MAC
            ip link set wlan0 up
            log -t frame-fixmac "wlan0 $cur -> $MAC"
        fi
    fi
    sleep 10
done
