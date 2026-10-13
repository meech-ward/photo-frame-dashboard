#!/usr/bin/env bash
# LOOFII C-3 (A133) flash/rollback runbook. Each phase must be invoked explicitly by name; nothing runs without an argument.
# Writes go through fbflash.py. flash-gsi and rollback ask you to type 'flash' first, and each partition's
# size on the device must match before it is written.
# Settings (environment):
#   PIECES_DIR      dir with pieces-super/, pieces-factory-super/, pieces-factory-metadata/, pieces-udisk-wipe/ (each with SHA256SUMS)
#   SUPER_NEW_SHA   sha256 of YOUR built super image (verify-gsi compares the device against it)
#   FACTORY_SUPER_SHA  sha256 of the super partition in YOUR factory backup (preflight and verify-factory compare against it)
#   SUPER_BYTES METADATA_BYTES UDISK_BYTES  exact partition sizes, as printed by `preflight` (fbflash.py refuses without them)
#   PY              python with pyusb (default: python3)     FEL  sunxi-fel binary (default: sunxi-fel)
# macOS: libusb from Homebrew (DYLD_LIBRARY_PATH=/opt/homebrew/lib) and `ioreg` for USB detection.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export DYLD_LIBRARY_PATH=${DYLD_LIBRARY_PATH:-/opt/homebrew/lib}
PY=${PY:-python3}; B=${PIECES_DIR:-./backups/a133-pieces}
FEL=${FEL:-sunxi-fel}
SUPER_NEW_SHA=${SUPER_NEW_SHA:-}; FACTORY_SUPER_SHA=${FACTORY_SUPER_SHA:-}

verify_sums() { (cd "$1" && shasum -a 256 -c SHA256SUMS --quiet) && echo "checksums OK: $1"; }
wait_uboot() { for i in $(seq 1 60); do ioreg -p IOUSB -l | grep -q '"idProduct" = 4112' && { sleep 2; $PY $HERE/fb.py getvar:version; return 0; }; sleep 2; done; echo "U-Boot fastboot not seen"; return 1; }
bytes_for() { case $1 in super) echo "${SUPER_BYTES:?set SUPER_BYTES (see preflight)}";; metadata) echo "${METADATA_BYTES:?set METADATA_BYTES}";; UDISK) echo "${UDISK_BYTES:?set UDISK_BYTES}";; esac; }
fb_size() { $PY $HERE/fb.py "getvar:partition-size:$1" | sed -n "s/.*OKAY\(0x[0-9a-fA-F]*\).*/\1/p"; }
check_size() { # the partition on the device must be exactly the size the pieces were built for
  local part=$1 want=$2 got; got=$(fb_size "$part")
  if [ -z "$got" ]; then
    echo "U-Boot did not report the size of $part; check it against preflight yourself."
    confirm "$part (size unchecked)"
  elif [ $((got)) -ne "$want" ]; then
    echo "STOP: $part on the device is $((got)) bytes, expected $want. Nothing written."; exit 1
  fi; }
confirm() { # every write phase needs a typed confirmation
  echo "About to WRITE: $*"
  read -r -p "Type 'flash' to continue: " a < /dev/tty || a=
  [ "$a" = flash ] || { echo "Not confirmed. Nothing written."; exit 1; }; }
flash() { local part=$1 dir=$2 n; n=$(bytes_for "$part"); verify_sums "$dir"; check_size "$part" "$n"
  $PY $HERE/validate_pieces.py "$n" - "$dir"/*.simg || { echo "pieces failed validation; nothing written"; exit 1; }
  FB_PART_BYTES=$n FB_ALLOW_FLASH=$part $PY $HERE/fbflash.py "$part" $(ls "$dir"/*.simg | sort); }
super_sha() { adb shell sha256sum /dev/block/by-name/super | cut -d" " -f1; }

case "${1:-}" in
  preflight)   # read-only, on Android with root ADB: identity, exact sizes, current super hash vs your backup
    adb shell 'getprop ro.board.platform; getprop ro.product.device; for p in super UDISK metadata; do echo "$p $(blockdev --getsize64 /dev/block/by-name/$p)"; done; gsi_tool status'
    s=$(super_sha); echo "super now=$s"
    [ -n "$FACTORY_SUPER_SHA" ] && { [ "$s" = "$FACTORY_SUPER_SHA" ] && echo "super == factory backup" || echo "super differs from factory backup (fine if you already flashed a GSI; stop if you didn't)"; }
    for d in $B/pieces-super $B/pieces-factory-super $B/pieces-udisk-wipe $B/pieces-factory-metadata; do verify_sums $d; done ;;
  to-uboot)    # Android -> U-Boot fastboot
    adb reboot bootloader; wait_uboot ;;
  flash-gsi)   # in U-Boot fastboot: super <- GSI 12.1 layout; metadata <- factory (pre-DSU); UDISK head zeroed
    confirm "super <- GSI, metadata <- factory, UDISK head zeroed (ERASES user data), then reboot"
    flash super    $B/pieces-super
    flash metadata $B/pieces-factory-metadata
    flash UDISK    $B/pieces-udisk-wipe
    FB_ALLOW_REBOOT=1 $PY $HERE/fb.py reboot ;;
  verify-gsi)  # after GSI boots with ADB (read-only)
    adb wait-for-device
    adb shell 'getprop ro.build.version.release; getprop ro.system.build.fingerprint; getprop sys.boot_completed; mount | grep -E " /data | / "'
    s=$(super_sha); echo "super=$s"; if [ -n "$SUPER_NEW_SHA" ] && [ "$s" = "$SUPER_NEW_SHA" ]; then echo "super MATCHES built image"; else echo "super MISMATCH"; exit 1; fi ;;
  fel-to-uboot) # rescue when neither ADB nor fastboot appears: device must be in FEL (hold reset while powering on)
    $FEL version; $FEL readl 0x07000118; $FEL writel 0x07000118 0x5f; $FEL readl 0x07000118
    echo "Release the reset button now; watchdog reset in 5s"; sleep 5; $FEL wdreset || true; wait_uboot ;;
  rollback)    # in U-Boot fastboot: restore factory super + metadata, zero UDISK head (stock reformats /data)
    confirm "super <- factory, metadata <- factory, UDISK head zeroed (ERASES user data), then reboot"
    flash super    $B/pieces-factory-super
    flash metadata $B/pieces-factory-metadata
    flash UDISK    $B/pieces-udisk-wipe
    FB_ALLOW_REBOOT=1 $PY $HERE/fb.py reboot ;;
  verify-factory) # after rollback boots stock Android (read-only)
    adb wait-for-device; s=$(super_sha); echo "super=$s"
    if [ -n "$FACTORY_SUPER_SHA" ] && [ "$s" = "$FACTORY_SUPER_SHA" ]; then echo "super MATCHES factory backup"; else echo "super MISMATCH (or FACTORY_SUPER_SHA not set)"; exit 1; fi ;;
  *) echo "usage: $0 {preflight|to-uboot|flash-gsi|verify-gsi|fel-to-uboot|rollback|verify-factory}"; exit 2 ;;
esac
