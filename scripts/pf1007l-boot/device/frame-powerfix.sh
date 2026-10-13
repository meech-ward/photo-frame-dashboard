#!/system/bin/sh
# The PF1007L has no battery. Its AXP223 power chip starts each boot with the VBUS input limited to
# 500 mA (register 0x30 = 0x21), and the kernel lifts it to no limit (0x63) only about 31 s in.
# The Wi-Fi chip powers up at 27-31 s; if it does so first, its current spike can brown the frame
# out. Set 0x63 (VHOLD 4.4 V, no current limit) from early boot, and check again in case the driver
# lowers it when it detects the supply again. The axppower vbuslimit file did not stop this.
B=/sys/devices/platform/axp22_board
[ -w $B/axp22_reg ] || exit 0
i=0
while true; do
    echo 30 > $B/axp22_reg
    cur=$(cat $B/axp22_reg)
    if [ "${cur#*=}" != 63 ]; then
        echo 3063 > $B/axp22_reg
        log -t frame-powerfix "lifted VBUS input limit at uptime $(cut -d' ' -f1 /proc/uptime)s ($cur)"
    fi
    if [ $i -lt 240 ]; then
        sleep 0.5
        i=$((i + 1))
    else
        sleep 10
    fi
done
