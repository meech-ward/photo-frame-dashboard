#!/usr/bin/env bash
# Write the Route U root-ADB boot patch over USB during stock recovery's root-ADB window
# (AiMOR factory reset). Tested on one unit (V10-1680 20260529); see
# docs/pf1007l-macos-20260529-recovery-boot-write.md before you use it. Owner approval required.
#
# Usage, from the repository root, BEFORE you start the factory reset:
#   scripts/a33-uboot/recovery-patch.sh check  [timeout-seconds]   # no write: identify + read + classify
#   scripts/a33-uboot/recovery-patch.sh write  [timeout-seconds]
# Inputs: diagnostics/recovery-patch/ from recovery-patch-build.py.
#
# Recovery has no shell, so every check runs from the host inside the window:
#   1. find the boot node from sysfs: start 172032, size 65536, PARTNAME=boot if reported.
#      Never write /dev/block/by-name/boot: it is a symlink, and adbd (Android 6
#      file_sync_service.cpp do_send) unlinks a symlink or regular file before a push, so the
#      push would replace the link and write nothing to the eMMC.
#   2. the node must be a block device (S_IFBLK).
#   3. write only: pull the node and require its first 31,028 sectors to be the original image.
#   4. write only: push A (original header + patched ramdisk), then push B (patched header).
#      adbd opens an existing block device without truncation and writes from byte 0; closing it
#      flushes it (Linux 3.4 __blkdev_put: sync_blockdev). Recovery's reboot also syncs first.
#   5. pull the node again and classify it: patched, original, or neither.
# Any failure before step 4 exits with no write.
set -u
cd "$(dirname "$0")/../.." || exit 1
mode=${1:-}; [ "$mode" = check ] || [ "$mode" = write ] || { sed -n '2,10p' "$0"; exit 1; }
P=diagnostics/recovery-patch
out=$P/run-$(date +%Y%m%d-%H%M%S)-$$
[ -e "$out" ] && { echo "STOP: run dir exists: $out"; exit 2; }
mkdir -p "$out/sys"; log=$out/log.txt
ADB=${ADB:-adb}
deadline=$((SECONDS + ${2:-1200}))
say()   { echo "$(date +%T) $*" | tee -a "$log"; }
abort() { say "STOP (no write): $*"; exit 2; }
sha()   { shasum -a 256 | cut -d' ' -f1; }
plan()  { python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1]))
for k in sys.argv[2:]: d=d[k]
print(d)' "$P/plan.json" "$@"; }

[ -f "$P/plan.json" ] || abort "no $P/plan.json; run recovery-patch-build.py first"
START=$(plan partition_start); SECTORS=$(plan partition_sectors); IMG=$(plan image_bytes)
ORIG=$(plan sha256 original-image.bin); PATCHED=$(plan sha256 patched-image.bin)
for f in pushA pushB; do
  [ "$(sha <"$P/$f.bin")" = "$(plan sha256 "$f.bin")" ] || abort "$f.bin does not match plan.json"
done
[ "$(wc -c <"$P/pushA.bin" | tr -d ' ')" -eq "$IMG" ] || abort "pushA.bin size"

classify() {  # $1 = pulled image file
  local n h
  n=$(wc -c <"$1" 2>/dev/null | tr -d ' ')
  [ "${n:-0}" -ge "$IMG" ] || { echo "incomplete (${n:-0} bytes)"; return; }
  h=$(head -c "$IMG" "$1" | sha)
  if [ "$h" = "$PATCHED" ]; then echo patched; elif [ "$h" = "$ORIG" ]; then echo original; else echo "neither ($h)"; fi
}

$ADB start-server >/dev/null 2>&1
say "$mode: plan verified; waiting for recovery ADB"
while [ "$($ADB -d get-state 2>/dev/null)" != recovery ]; do
  [ $SECONDS -lt $deadline ] || abort "deadline, recovery never appeared"; sleep 0.2
done
say "recovery ADB up"

# 1. list the nodes (retry: the listing can lag the state by a moment)
t=$((SECONDS + 4)); nodes=""
while [ -z "$nodes" ] && [ $SECONDS -lt $t ]; do
  $ADB -d ls /dev/block >"$out/dev-block.txt" 2>&1
  nodes=$(awk '$4 ~ /^mmcblk0p[0-9]+$/ {print $4}' "$out/dev-block.txt")
  [ -n "$nodes" ] || sleep 0.2
done
[ -n "$nodes" ] || abort "no mmcblk0pN nodes listed: $(head -c 120 "$out/dev-block.txt")"
NODE=""; BOOTPN=""
for n in $nodes; do       # start for every node; size and name only where the start matches
  $ADB -d pull "/sys/class/block/$n/start" "$out/sys/$n.start" >/dev/null 2>&1
  st=$(tr -d '[:space:]' <"$out/sys/$n.start" 2>/dev/null); sz=""; pn=""
  if [ "$st" = "$START" ]; then
    $ADB -d pull "/sys/class/block/$n/size" "$out/sys/$n.size" >/dev/null 2>&1
    $ADB -d pull "/sys/class/block/$n/uevent" "$out/sys/$n.uevent" >/dev/null 2>&1
    sz=$(tr -d '[:space:]' <"$out/sys/$n.size" 2>/dev/null)
    pn=$(sed -n 's/^PARTNAME=//p' "$out/sys/$n.uevent" 2>/dev/null)
  fi
  echo "$n start=$st size=$sz name=$pn" >>"$out/partmap.txt"
  if [ "$st" = "$START" ] && [ "$sz" = "$SECTORS" ] && { [ -z "$pn" ] || [ "$pn" = boot ]; }; then
    [ -z "$NODE" ] || abort "two nodes match the boot partition ($NODE, $n)"
    NODE=/dev/block/$n; BOOTPN=$pn
  fi
done
grep -q 'start=[0-9]' "$out/partmap.txt" 2>/dev/null || abort "sysfs partition info unreadable over ADB"
[ -n "$NODE" ] || abort "no node with start=$START size=$SECTORS (see $out/partmap.txt)"
# 2. block device
mode_hex=$(awk -v n="$(basename "$NODE")" '$4==n {print $1}' "$out/dev-block.txt")
[ $(( 16#${mode_hex:-0} & 16#F000 )) -eq $(( 16#6000 )) ] || abort "$NODE mode ${mode_hex:-?} is not a block device"
say "boot is $NODE: block device, start=$START size=$SECTORS PARTNAME=${BOOTPN:-<none>}"

# 3. current contents
$ADB -d pull "$NODE" "$out/before.img" >>"$log" 2>&1
state=$(classify "$out/before.img")
say "current contents: $state"
if [ "$mode" = check ]; then say "check done, nothing written"; exit 0; fi
[ "$state" = original ] || abort "the boot partition does not hold the original image ($state)"

# 4. write: A, then B (the header changes last)
say "WRITE A start"; $ADB -d push "$P/pushA.bin" "$NODE" >>"$log" 2>&1; ra=$?; say "WRITE A exit=$ra"
rb=skipped
if [ $ra -eq 0 ]; then say "WRITE B start"; $ADB -d push "$P/pushB.bin" "$NODE" >>"$log" 2>&1; rb=$?; say "WRITE B exit=$rb"
else say "WRITE A failed: skipping B; reading back"; fi

# 5. read back
$ADB -d pull "$NODE" "$out/after.img" >>"$log" 2>&1
state=$(classify "$out/after.img")
case $state in
  patched)  say "VERIFY OK: the boot partition holds the patched image"; exit 0;;
  original) say "VERIFY: still the original image, nothing changed (A=$ra B=$rb)"; exit 4;;
  incomplete*) say "read-back cut off by the reboot ($state; A=$ra B=$rb). After boot expect 1f3a:1002 and root ADB"; exit 6;;
  *)        say "VERIFY MISMATCH: $state (A=$ra B=$rb). Do not reboot by hand if recovery is still up; restore needs Route U or S"; exit 5;;
esac
