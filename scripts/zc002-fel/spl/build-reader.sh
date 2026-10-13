#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UBOOT_SRC=${1:-${UBOOT_SRC:-}}
OUT=${2:-"$HERE/out"}
PINNED_COMMIT=ece349ade2973e220f524ce59e59711cc919263f

if [ -z "$UBOOT_SRC" ]; then
	echo "usage: $0 /path/to/u-boot-checkout [output-directory]" >&2
	exit 2
fi
if [ "$(git -C "$UBOOT_SRC" rev-parse HEAD)" != "$PINNED_COMMIT" ]; then
	echo "U-Boot checkout must be at pinned commit $PINNED_COMMIT" >&2
	exit 2
fi
case "$OUT" in
	/*) ;;
	*) OUT="$(pwd)/$OUT" ;;
esac

export ARCH=arm
export CROSS_COMPILE=${CROSS_COMPILE:-arm-linux-gnueabihf-}
JOBS=${JOBS:-2}

cd "$UBOOT_SRC"
cp "$HERE/hd-reader.c" arch/arm/mach-sunxi/hd-reader.c
python3 "$HERE/patch-reader.py"
make q8_a33_tablet_1024x600_defconfig
scripts/kconfig/merge_config.sh -m .config "$HERE/reader.config"
make olddefconfig
if grep -q '^CONFIG_SPL_MMC_WRITE=' .config; then
	echo 'refusing to build a reader with SPL MMC write support' >&2
	exit 1
fi
make -j"$JOBS" spl/u-boot-spl.bin

mkdir -p "$OUT"
tools/mksunxiboot --default-dt sun8i-a33-q8-tablet \
	spl/u-boot-spl.bin "$OUT/zc002-fel-reader-spl.bin"
cp spl/u-boot-spl.map "$OUT/reader.map"
${CROSS_COMPILE}nm -n spl/u-boot-spl > "$OUT/reader.symbols"
if grep -Eq '[[:space:]](blk_dwrite|mmc_bwrite|mmc_write_blocks)$' "$OUT/reader.symbols"; then
	echo 'reader contains an unexpected storage-write symbol' >&2
	exit 1
fi
cp .config "$OUT/resolved.config"
printf 'SPL image written to %s\n' "$OUT/zc002-fel-reader-spl.bin"
