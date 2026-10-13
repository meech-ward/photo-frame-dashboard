"""Exercise the actual SPL C probe offline, with simulated MMC and MMIO."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

SPL = Path(__file__).parent / "spl"

# No storage-write function is declared or provided. A reintroduced write call
# fails compilation/linking, rather than silently succeeding in the simulator.
STUBS = r"""
#ifndef TEST_STUBS_H
#define TEST_STUBS_H
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef unsigned long ulong;
struct mmc_config { u32 host_caps, f_max; };
struct mmc { struct mmc_config *cfg; u32 bus_width, clock, cid[4]; };
struct blk_desc { u32 blksz; u64 lba; };
#define MMC_MODE_HS 1
#define MMC_MODE_HS_52MHz 2
#define MMC_MODE_DDR_52MHz 4
#define MMC_MODE_8BIT 8
#define MMC_MODE_4BIT 16
static unsigned initialized, reads;
static int short_read;
static struct mmc_config config = {31, 0};
static struct mmc card = {&config, 1, 400000, {1, 2, 3, 4}};
static struct blk_desc disk = {512, 200000};
static u32 readl(const void *address) { (void)address; return 0; }
static void writel(u32 value, void *address) { (void)value; (void)address; }
static void clrbits_le32(void *address, u32 mask) { (void)address; (void)mask; }
static void setbits_le32(void *address, u32 mask) { (void)address; (void)mask; }
static void udelay(unsigned delay) { (void)delay; }
static int mmc_initialize(void *unused) { (void)unused; initialized++; return 0; }
static struct mmc *find_mmc_device(unsigned dev) { (void)dev; return &card; }
static int mmc_init(struct mmc *m) { (void)m; return 0; }
static struct blk_desc *mmc_get_blk_desc(struct mmc *m) { (void)m; return &disk; }
static int mmc_set_clock(struct mmc *m, u32 hz, int unused) {
    (void)unused; m->clock = hz; return 0;
}
static ulong blk_dread(struct blk_desc *d, u64 lba, u32 blocks, void *buffer) {
    (void)d; (void)lba; reads++; memset(buffer, 'A', blocks * 512);
    return short_read ? blocks - 1 : blocks;
}
#endif
"""

MAIN = r"""
int main(int argc, char **argv) {
    unsigned char result[0x800] = {0};
    u32 request[16] = {0x48445731, 3, 172032, 0, 2, 12000000, 1, 3,
                      0, 0, 0, 1, 2, 3, 4, 200000};
    if (argc != 6) return 2;
    request[8] = strtoul(argv[1], NULL, 0);
    request[9] = strtoul(argv[2], NULL, 0);
    request[10] = strtoul(argv[3], NULL, 0);
    request[15] = strtoul(argv[4], NULL, 0);
    short_read = atoi(argv[5]);
    memcpy((void *)hd_reader_request, request, sizeof(request));
    hd_storage_probe();
    memcpy(result, &test_result, sizeof(test_result));
    fwrite(result, sizeof(result), 1, stdout);
    fwrite(&initialized, sizeof(initialized), 1, stdout);
    fwrite(&reads, sizeof(reads), 1, stdout);
    return 0;
}
"""


class SplReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which(os.environ.get("CC", "cc"))
        if not compiler:
            raise unittest.SkipTest("native C compiler needed for the SPL simulator")
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        for header in ("mmc.h", "blk.h", "linux/delay.h", "linux/string.h", "asm/io.h"):
            target = root / header
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('#include "test-stubs.h"\n')
        (root / "test-stubs.h").write_text(STUBS)
        source = (SPL / "hd-reader.c").read_text()
        # Redirect the two fixed DRAM buffers and drop the ELF-only data-section
        # attribute. Request checks, MMC flow and CRC remain the production C.
        old_result = "#define HD_RESULT ((volatile struct hd_result *)0x43000000)"
        if source.count(old_result) != 1:
            raise AssertionError("update the simulator for the changed result buffer")
        source = source.replace(old_result, "static struct hd_result test_result;\n"
                                "static unsigned char test_data[2048 * 512];\n"
                                "#define HD_RESULT (&test_result)")
        source = source.replace("(void *)0x43001000", "(void *)test_data")
        source = source.replace("(const unsigned char *)0x43001000",
                                "(const unsigned char *)test_data")
        source = source.replace('__attribute__((section(".data")))', "")
        fixture = root / "probe.c"
        fixture.write_text(source + MAIN)
        cls.program = root / "probe"
        build = subprocess.run([compiler, "-std=c99", "-Werror=implicit-function-declaration",
                                "-Wno-int-to-pointer-cast", "-I", str(root), str(fixture),
                                "-o", str(cls.program)], capture_output=True, text=True)
        if build.returncode:
            raise AssertionError(build.stderr)

    def probe(self, *, op=0, old_crc=0, input_crc=0, sectors=200000, short=0):
        raw = subprocess.run([str(self.program), *map(str, (op, old_crc, input_crc, sectors, short))],
                             check=True, capture_output=True).stdout
        self.assertEqual(len(raw), 0x808)
        return (struct.unpack_from("<15I", raw),
                struct.unpack_from("<6I", raw, 450 * 4),
                struct.unpack_from("<2I", raw, 0x800))

    def test_former_write_and_preflight_ops_stop_before_mmc(self):
        for op in (1, 2, 3, 0xFFFFFFFF):
            with self.subTest(op=op):
                result, extra, calls = self.probe(op=op)
                self.assertEqual(result[2:4], (1, (-1004) & 0xFFFFFFFF))
                self.assertEqual(calls, (0, 0))
                self.assertEqual(extra[1:5], (0, 0, 0, 0))

    def test_nonzero_reserved_crc_fields_stop_before_mmc(self):
        for args in ({"old_crc": 1}, {"input_crc": 1}):
            with self.subTest(args=args):
                result, _extra, calls = self.probe(**args)
                self.assertEqual(result[3], (-1004) & 0xFFFFFFFF)
                self.assertEqual(calls, (0, 0))

    def test_read_retains_result_abi_and_data_crc(self):
        result, extra, calls = self.probe()
        self.assertEqual(result[:10], (0x48445231, 3, 5, 0, 1, 512, 200000, 0, 1, 12000000))
        self.assertEqual(result[10:14], (1, 2, 3, 4))
        self.assertEqual(extra, (0, zlib.crc32(b"A" * 1024), 0, 0, 0, 2))
        self.assertEqual(calls, (1, 1))

    def test_identity_mismatch_and_short_read_remain_failures(self):
        result, extra, calls = self.probe(sectors=199999)
        self.assertEqual(result[2:4], (3, (-1100) & 0xFFFFFFFF))
        self.assertEqual(calls, (1, 0))
        self.assertEqual(extra[1:5], (0, 0, 0, 0))
        result, extra, calls = self.probe(short=1)
        self.assertEqual(result[2:4], (5, (-1002) & 0xFFFFFFFF))
        self.assertEqual(calls, (1, 1))
        self.assertEqual(extra[1:5], (0, 0, 0, 0))


@unittest.skipUnless(os.name == "posix", "build script requires a POSIX shell")
class ReaderBuildGuardTests(unittest.TestCase):
    def test_resolved_write_config_and_linked_writer_fail_closed(self):
        # Simulate the build outputs to exercise build-reader.sh's guards; this
        # does not compile U-Boot or validate a device-specific SPL image.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, commands = root / "u-boot", root / "bin"
            commands.mkdir()
            (source / "arch/arm/mach-sunxi").mkdir(parents=True)
            (source / "scripts/kconfig").mkdir(parents=True)
            (source / "tools").mkdir()
            (source / "spl").mkdir()

            def executable(path, body):
                path.write_text("#!/bin/sh\nset -eu\n" + body)
                path.chmod(0o755)

            executable(commands / "git", "printf '%s\\n' ece349ade2973e220f524ce59e59711cc919263f\n")
            executable(commands / "make", '''
case "$*" in
  *olddefconfig*)
    if [ "$TEST_WRITE_CONFIG" = 1 ]; then printf 'CONFIG_SPL_MMC_WRITE=y\\n' >> .config; fi ;;
  *spl/u-boot-spl.bin*) printf stub > spl/u-boot-spl.bin; : > spl/u-boot-spl.map ;;
  *) : > .config ;;
esac
''')
            executable(commands / "test-nm", '''
printf '00001200 D hd_reader_request\\n00001400 D _end\\n'
if [ "$TEST_WRITE_SYMBOL" = 1 ]; then printf '00001500 T mmc_bwrite\\n'; fi
''')
            executable(source / "scripts/kconfig/merge_config.sh", 'cat "$3" > "$2"\n')
            executable(source / "tools/mksunxiboot", 'cp "$3" "$4"\n')
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"],
                       CROSS_COMPILE="test-", TEST_WRITE_CONFIG="0", TEST_WRITE_SYMBOL="0")
            for config, symbol, error in (("1", "0", "SPL MMC write support"),
                                          ("0", "1", "storage-write symbol"),
                                          ("0", "0", None)):
                with self.subTest(config=config, symbol=symbol):
                    (source / "arch/arm/mach-sunxi/board.c").write_text(
                        '\tdebug("Returning to FEL sp=%x, lr=%x\\n", fel_stash.sp, fel_stash.lr);\n')
                    (source / "arch/arm/mach-sunxi/Makefile").write_text("")
                    run = subprocess.run(["sh", str(SPL.resolve() / "build-reader.sh"),
                                          str(source), str(root / f"out-{config}-{symbol}")],
                                         env=dict(env, TEST_WRITE_CONFIG=config, TEST_WRITE_SYMBOL=symbol),
                                         capture_output=True, text=True)
                    if error:
                        self.assertNotEqual(run.returncode, 0)
                        self.assertIn(error, run.stderr)
                    else:
                        self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
