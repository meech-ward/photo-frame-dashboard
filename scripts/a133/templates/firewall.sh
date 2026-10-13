# Two-way firewall for a LAN-only wall display. Paste into /system/bin/phh-on-boot.sh (runs at boot_completed as root).
# IN: loopback + your LAN (+ IPv6 link-local). OUT: loopback, LAN, multicast/broadcast, NTP; everything else REJECTed.
LAN_CIDR=192.0.2.0/24        # <-- set to your LAN, e.g. 192.168.x.0/24 (example value is a documentation range)
settings put global captive_portal_mode 0
for T in iptables ip6tables; do for C in IN OUT; do $T -N FRAME_$C; $T -F FRAME_$C
$T -A FRAME_$C -m state --state ESTABLISHED,RELATED -j ACCEPT; done
$T -A FRAME_IN -i lo -j ACCEPT; $T -A FRAME_OUT -o lo -j ACCEPT; done 2>/dev/null
iptables -A FRAME_IN -s $LAN_CIDR -j ACCEPT
for D in $LAN_CIDR 224.0.0.0/4 255.255.255.255; do iptables -A FRAME_OUT -d $D -j ACCEPT; done
iptables -A FRAME_OUT -p udp --dport 123 -j ACCEPT
for C in IN OUT; do ip6tables -A FRAME_$C -p ipv6-icmp -j ACCEPT; done
ip6tables -A FRAME_IN -s fe80::/10 -j ACCEPT
for D in fe80::/10 ff00::/8; do ip6tables -A FRAME_OUT -d $D -j ACCEPT; done
for T in iptables ip6tables; do $T -A FRAME_IN -j DROP; $T -A FRAME_OUT -j REJECT
$T -C INPUT -j FRAME_IN || $T -I INPUT -j FRAME_IN; $T -C OUTPUT -j FRAME_OUT || $T -I OUTPUT -j FRAME_OUT; done 2>/dev/null
