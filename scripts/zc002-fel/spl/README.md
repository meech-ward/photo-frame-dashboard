# ZC002 FEL-returning read-only SPL storage helper

This directory contains the readable source and build inputs for a small
Allwinner A33 SPL helper. It initializes the frame's eMMC, records controller
and card information in a fixed DRAM result structure, performs bounded block
reads, and then returns through the normal FEL path. The SPL has no storage-write
operation, and its build disables `CONFIG_SPL_MMC_WRITE`. Its source is pinned to
the official [U-Boot repository](https://source.denx.de/u-boot/u-boot.git) at
commit `ece349ade2973e220f524ce59e59711cc919263f`.

The original private helper also supported guarded writes. This public reader
has had both that write operation and its CRC-preflight operation removed;
requests for either are rejected before MMC initialization. The original helper
was used in a per-unit workflow with a private request.
That request, its CID, and the resulting binary are intentionally absent here.
The public source sets all request words to zero. **Do not use it unchanged:
the all-zero request fails the magic/version check before MMC I/O.** A host
must fill a request from the specific unit it has independently verified and
rebuild the SPL image so the eGON checksum covers the changed data. The build
script invokes `mksunxiboot` to make that checksummed image. The sanitized
source compiled from the pinned commit in a network-disabled container; it has
not been run on hardware.

The helper's result layout and DRAM addresses are retained. These are DRAM
addresses, not SRAM addresses: the result structure begins at `0x43000000`,
read data begins at `0x43001000`. There is no write-input buffer in this reader.
Keep `struct hd_result` and these addresses unchanged when collecting results
with existing host tooling.

## Request format

`hd_reader_request` is 16 words. The zeroed initializer is intentionally
invalid. For a unit-specific request, its fields are:

| Word(s) | Meaning |
| --- | --- |
| 0 | Request magic `0x48445731` |
| 1 | Request version `3` |
| 2–3 | Starting LBA, low word then high word |
| 4 | Block count |
| 5 | Requested clock: `400000` or `12000000` Hz |
| 6 | MMC device index; this board helper requires `1` |
| 7 | Board-specific electrical mode selector |
| 8 | Operation: must be `0` (read); all other values are rejected |
| 9–10 | Reserved legacy CRC fields; both must be zero |
| 11–14 | The same unit's 16-byte CID, represented as four words whose in-memory bytes match the card CID |
| 15 | That unit's sector count |

The helper rejects a request if the magic, version, MMC index, request bounds,
clock, card CID, or sector count do not match. Read operation `0` accepts
at most 2048 blocks at 12 MHz or 8 blocks at 400 kHz. Nonzero operation or reserved
CRC fields are rejected before MMC initialization. The version-3 result layout
is retained for the host tool; its former input-CRC, readback-CRC and written-block
fields stay zero. The successful read still returns its data CRC and block count.

## Build

Use a disposable U-Boot checkout at the pinned commit; the build script modifies
that source tree by adding its SPL file and patching the FEL return point. This
package does not download source or execute a device command. The official upstream repository
is `https://source.denx.de/u-boot/u-boot.git`. The build needs Python 3, an ARM
hard-float cross compiler, and the normal U-Boot build tools. On a Linux build
host with those dependencies installed:

```sh
git -C /path/to/u-boot rev-parse HEAD
sh ./build-reader.sh /path/to/u-boot ./out
```

The first command should print
`ece349ade2973e220f524ce59e59711cc919263f`. To choose a different cross
compiler prefix or job count, set `CROSS_COMPILE` or `JOBS` in the environment.
The script builds `q8_a33_tablet_1024x600_defconfig`, merges
`reader.config`, inserts `hd_storage_probe()` immediately before the SPL
returns to FEL, builds the SPL, and wraps it with the board's eGON header using
`mksunxiboot`. The output directory receives the image, map, symbol table, and resolved
configuration; no generated binaries are part of this source package. The build
refuses an enabled SPL MMC write option or a linked storage-write symbol.

The default zero initializer remains fail-closed. Use the read-only host
transaction tool below to inject a per-unit request into a temporary copy of
the built image; never publish that request or image because words 11–14
identify the card.

## Read-only host transaction

[`../fel-read.py`](../fel-read.py) provides one bounded read operation for a
matching Allwinner A33 unit. It patches a copy of the checksummed SPL image with
an explicit LBA, block count, capacity, and four CID words, verifies the eGON
header and symbol bounds, then checks the result structure, reported CID and
capacity, status, returned byte count, and CRC. It has no write operation. The
unit-specific request image is kept in a temporary directory beside the output
and removed after the transaction; the read data is written only to a new
output file. Keep the supplied CID private. `--identify` uses the source's
expected identity-mismatch response to report CID/capacity before any block
read; it always requests one block at LBA 0 with operation 0 and an all-zero
CID/capacity, so the SPL stops at the identity guard before `blk_dread`. It
does initialize MMC and reset the controller. The printed identity is private.

Build the image and symbol table as described above. First confirm the frame is
already in FEL and run the identity-only probe. Record its private output for
the subsequent command; don't copy it into an issue or report:

```sh
python3 scripts/zc002-fel/fel-read.py \
  --spl ./out/zc002-fel-reader-spl.bin \
  --symbols ./out/reader.symbols \
  --sunxi-fel sunxi-fel \
  --identify
```

Then run one bounded read using only that unit's reported CID and capacity:

```sh
python3 scripts/zc002-fel/fel-read.py \
  --spl ./out/zc002-fel-reader-spl.bin \
  --symbols ./out/reader.symbols \
  --sunxi-fel sunxi-fel \
  --lba 172032 --blocks 8 --sectors 60620800 \
  --cid-words 0x00000000,0x00000000,0x00000000,0x00000000 \
  --output ./private-read.bin
```

Replace the zero CID placeholders with the identity probe's output; they are
deliberately invalid. A full 16 MiB boot read requires multiple transactions, each no larger than 2048
sectors at 12 MHz or 8 sectors at 400 kHz. The command does not make a complete
backup automatically and does not test recovery. It is not a boot writer or a
general-purpose disk-imaging tool. This command path is covered by synthetic
offline tests, but has not been run against a device with the sanitized image.

## Provenance and checks

`hd-reader.c` is GPL-2.0-or-later, compatible with U-Boot's license. The
injection script and build script carry the same SPDX identifier. This source
package is a cleaned and de-identified presentation of the helper used with a
private request; source formatting and comments were made readable while the
request/result data layout, MMC initialization, MMIO addresses, bounded reads,
identity checks and read CRC were retained. The earlier write-capable source
compiled from the pinned commit in an isolated network-disabled container; this
read-only revision still needs a full SPL rebuild and hardware validation. Its C
probe is exercised by native host tests with simulated MMC and MMIO; those tests
do not execute on a frame or establish electrical compatibility. The host
transaction tool has not been tested on another frame.
