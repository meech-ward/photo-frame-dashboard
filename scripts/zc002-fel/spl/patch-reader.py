#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Insert the storage probe immediately before the SPL returns to FEL."""

from pathlib import Path
import re


BOARD_C = Path("arch/arm/mach-sunxi/board.c")
MACH_MAKEFILE = Path("arch/arm/mach-sunxi/Makefile")
RETURN_MARKER = '\tdebug("Returning to FEL sp=%x, lr=%x\\n", fel_stash.sp, fel_stash.lr);'
PROBE_CALL = "\textern void hd_storage_probe(void);\n\thd_storage_probe();\n"


def main() -> None:
	board = BOARD_C.read_text()
	# Make reruns deterministic if an earlier probe patch is already present.
	board = re.sub(
		r"\textern void hd_\w+_probe\(void\);\n\thd_\w+_probe\(\);\n",
		"",
		board,
	)
	if board.count(RETURN_MARKER) != 1:
		raise SystemExit("expected exactly one SPL FEL return marker in board.c")
	BOARD_C.write_text(board.replace(RETURN_MARKER, PROBE_CALL + RETURN_MARKER))

	makefile = MACH_MAKEFILE.read_text()
	if "hd-reader.o" not in makefile:
		MACH_MAKEFILE.write_text(makefile.rstrip() + "\n\nobj-$(CONFIG_SPL_BUILD) += hd-reader.o\n")


if __name__ == "__main__":
	main()
