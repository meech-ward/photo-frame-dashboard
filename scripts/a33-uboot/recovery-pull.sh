#!/usr/bin/env bash
# Copy partitions out of stock recovery's root-ADB window during an AiMOR factory reset
# (18d1:d001, about 13 to 20 s, file transfer only). Read-only: adb pull only.
#
# Usage, from the repository root, BEFORE you start the factory reset:
#   scripts/a33-uboot/recovery-pull.sh [timeout-seconds]
# Then on the frame: hold the reset pin while connecting power, release, choose Factory reset
# on AiMOR's Recovery Mode screen. The script pulls boot first, then env, misc, bootloader and
# recovery while the window lasts, and prints boot's T6 hash. It re-arms if boot is incomplete.
# The factory reset erases the frame's user data.
set -u
cd "$(dirname "$0")/../.." || exit 1
out=diagnostics/recovery-pull
mkdir -p "$out"
log=$out/log.txt
deadline=$((SECONDS + ${1:-1200}))
img=$((31028 * 512))
say() { echo "$(date +%T) $*" | tee -a "$log"; }

adb start-server >/dev/null 2>&1
say "armed: waiting for recovery ADB (18d1:d001)"
try=0
while [ $SECONDS -lt $deadline ]; do
  if [ "$(adb -d get-state 2>/dev/null)" != recovery ]; then sleep 0.2; continue; fi
  try=$((try + 1)); d=$out/try$try; mkdir -p "$d"
  say "try$try: recovery ADB up"
  adb -d pull /dev/block/by-name/boot "$d/boot.img" >>"$log" 2>&1; say "try$try: boot pull exit=$?"
  adb -d ls /dev/block/by-name >"$d/by-name.txt" 2>&1
  adb -d ls /dev/block >"$d/dev-block.txt" 2>&1
  for p in env misc bootloader recovery; do
    adb -d pull "/dev/block/by-name/$p" "$d/$p.img" >>"$log" 2>&1; say "try$try: $p pull exit=$?"
  done
  size=$(wc -c <"$d/boot.img" 2>/dev/null | tr -d ' ')
  if [ "${size:-0}" -eq $((65536 * 512)) ] && [ "$(head -c 8 "$d/boot.img")" = "ANDROID!" ]; then
    sha=$(head -c $img "$d/boot.img" | shasum -a 256 | cut -d' ' -f1)
    say "boot: $size bytes, ANDROID! header, T6 SHA-256 $sha"
    say "Compare it with the firmware table (T6) before you build anything."
    exit 0
  fi
  say "try$try: boot incomplete (${size:-0} bytes); re-arming"
  while [ "$(adb -d get-state 2>/dev/null)" = recovery ]; do sleep 0.2; done
done
say "deadline reached without a complete boot copy"; exit 1
