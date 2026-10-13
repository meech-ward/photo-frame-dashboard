#!/system/bin/sh
# Keep the clock right on a frame with no battery-backed clock. After a power cut it starts in 1969
# and every HTTPS request fails ("certificate not yet valid"). Android 6's own SNTP client also took
# a rate-limit reply (NTP Kiss-o'-Death) as the time and then waited a day to try again.
# At boot: restore the last saved time (close enough for TLS), then ask NTP_SERVER (or the Wi-Fi
# gateway) every 2 s until it answers (20 s after a refusal, so a rate limiter can recover), then
# every 6 h. The time is saved every 10 minutes. Uses SNTP over toybox nc.
# mksh arithmetic is 32-bit, so the NTP-to-Unix epoch shift is done in 16-bit halves.
CONF=/data/local/frame-boot.conf
[ -r $CONF ] && . $CONF
SAVED=/data/local/frame-lasttime
# Not /data/local/tmp: the shell user can write there, and this runs as root.
REQ=/data/local/frame-ntpreq
RESP=/data/local/frame-ntpresp

saved=$(cat $SAVED 2> /dev/null)
if [ -n "$saved" ] && [ "$(date +%s)" -lt "$saved" ]; then
    # toybox date has no @epoch input; busybox does.
    /sbin/busybox date -u -s @$saved > /dev/null
    log -t frame-timesync "clock restored from saved time: $(date)"
fi

printf '\033' > $REQ
dd if=/dev/zero bs=47 count=1 2> /dev/null >> $REQ
while true; do
    server=$NTP_SERVER
    # Android 6 keeps the Wi-Fi default route in its own table.
    [ -n "$server" ] || server=$(ip route show table wlan0 2> /dev/null | grep -m1 "^default via" | cut -d" " -f3)
    if [ -z "$server" ]; then
        sleep 2
        continue
    fi
    rm -f $RESP
    nc -u -w 1 $server 123 < $REQ > $RESP 2> /dev/null
    if [ "$(wc -c < $RESP 2> /dev/null)" -ge 48 ]; then
        set -- $(od -An -tu1 -N2 $RESP)
        mode=$(($1 & 7))
        stratum=$2
        set -- $(od -An -tu1 -j40 -N5 $RESP)
        if [ $mode -eq 4 ] && [ $stratum -ge 1 ] && [ $stratum -le 15 ]; then
            hi=$(($1 * 256 + $2 - 33706))
            lo=$(($3 * 256 + $4 - 32384))
            if [ $lo -lt 0 ]; then
                lo=$((lo + 65536))
                hi=$((hi - 1))
            fi
            # nc waits 1 s after the reply arrives before it exits.
            epoch=$((hi * 65536 + lo + 1))
            drift=$((epoch - $(date +%s)))
            # toybox printf %03d prints garbage on this build, so pad by hand.
            ms=$((1000 + $5 * 1000 / 256))
            ms=${ms#1}
            if [ $drift -gt 1 ] || [ $drift -lt -1 ]; then
                # AlarmManager sets the system clock and the hardware clock.
                service call alarm 2 i64 $epoch$ms > /dev/null
                log -t frame-timesync "clock set from $server (was off by ${drift}s): $(date)"
            fi
            n=0
            while [ $n -lt 36 ]; do
                date +%s > $SAVED
                sleep 600
                n=$((n + 1))
            done
            continue
        fi
        log -t frame-timesync "$server refused (stratum $stratum), retrying in 20 s"
        sleep 20
        continue
    fi
    sleep 2
done
