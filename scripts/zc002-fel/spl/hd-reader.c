// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * ZC002 FEL-returning, read-only SPL storage probe.
 *
 * The request below is deliberately invalid. A host must supply a request
 * bound to its own unit and rebuild the eGON checksum before use. Leaving the
 * neutral defaults unchanged fails at the magic/version check before MMC I/O.
 */

#include <mmc.h>
#include <linux/delay.h>
#include <blk.h>
#include <asm/io.h>
#include <linux/string.h>

struct hd_result {
	u32 magic;
	u32 version;
	u32 phase;
	u32 rc;
	u32 dev;
	u32 blocklen;
	u32 sectors_lo;
	u32 sectors_hi;
	u32 bus_width;
	u32 clock;
	u32 cid[4];
	u32 trace_count;
	u32 trace[64][6];
	u32 regs_before[24];
	u32 regs_after[24];
	u32 pin_samples[3];
	u32 op;
	u32 old_crc;
	/* Retained for the version-3 result ABI; always zero in this reader. */
	u32 input_crc;
	u32 readback_crc;
	u32 written;
	u32 requested;
};

#define HD_RESULT ((volatile struct hd_result *)0x43000000)

/*
 * Host-filled request words. Indexes 11..14 hold this unit's CID. The all-zero
 * default fails closed; no device identifier or usable request is published.
 */
/* Keep the invalid zero request in the loadable image, not zeroed BSS. */
volatile u32 hd_reader_request[16] __attribute__((section(".data"))) = {
	0, 0, 0, 0, 0, 0, 0, 0,
	0, 0, 0, 0, 0, 0, 0, 0,
};

static const u32 hd_regs[24] = {
	0x01c20848, 0x01c2084c, 0x01c20850, 0x01c20858,
	0x01c2085c, 0x01c20860, 0x01c20864, 0x01c20868,
	0x01c11000, 0x01c11004, 0x01c11008, 0x01c1100c,
	0x01c11018, 0x01c1101c, 0x01c11020, 0x01c11038,
	0x01c1103c, 0x01c11078, 0x01c1105c, 0x01c20090,
	0x01c20060, 0x01c202c0, 0x01c208b4, 0x01c208c4,
};

static void hd_snapshot(volatile u32 *dst)
{
	int i;

	for (i = 0; i < 24; i++)
		dst[i] = readl((void *)hd_regs[i]);
}

static void hd_sample_pins(volatile u32 *dst)
{
	void *c0 = (void *)0x01c20848;
	void *c1 = (void *)0x01c2084c;
	void *dat = (void *)0x01c20858;
	u32 a = readl(c0);
	u32 b = readl(c1);

	dst[0] = readl(dat);
	/* Temporarily sample CLK, CMD and D0-D7 as GPIO inputs. */
	writel(a & ~0x0ff00000, c0);
	writel(0, c1);
	udelay(100);
	dst[1] = readl(dat);
	writel(b, c1);
	writel(a, c0);
	udelay(100);
	dst[2] = readl(dat);
}

#define HD_RETURN do { hd_snapshot(r->regs_after); return; } while (0)

static u32 hd_crc32(const unsigned char *p, u32 length)
{
	u32 crc = 0xffffffff;

	while (length--) {
		int i;

		crc ^= *p++;
		for (i = 0; i < 8; i++)
			crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
	}
	return ~crc;
}

void hd_storage_probe(void)
{
	volatile struct hd_result *r = HD_RESULT;
	struct mmc *m;
	struct mmc_config *cfg;
	struct blk_desc *bd;
	u64 lba;
	u32 blocks;
	u32 hz;
	ulong got;
	int rc;

	memset((void *)r, 0, sizeof(*r));
	r->magic = 0x48445231;
	r->version = 3;
	r->phase = 1;
	r->dev = hd_reader_request[6];
	hd_snapshot(r->regs_before);

	if (hd_reader_request[0] != 0x48445731 || hd_reader_request[1] != 3) {
		r->rc = -1003;
		HD_RETURN;
	}

	lba = (u64)hd_reader_request[2] | ((u64)hd_reader_request[3] << 32);
	blocks = hd_reader_request[4];
	hz = hd_reader_request[5];
	r->op = hd_reader_request[8];
	r->requested = blocks;
	/* Reject the former write/preflight operations before any MMC I/O. */
	if (r->dev != 1 || r->op != 0 ||
	    hd_reader_request[9] || hd_reader_request[10] ||
	    !blocks || blocks > 2048 ||
	    (hz != 400000 && hz != 12000000) ||
	    (hz == 400000 && blocks > 8)) {
		r->rc = -1004;
		HD_RETURN;
	}

	if (r->dev == 1 && hd_reader_request[7] == 3) {
		clrbits_le32((void *)0x01c202c0, 1U << 10);
		udelay(10);
		setbits_le32((void *)0x01c202c0, 1U << 10);
		udelay(1000);
	}

	rc = mmc_initialize(NULL);
	r->rc = rc;
	r->phase = 2;
	if (rc)
		HD_RETURN;

	m = find_mmc_device(r->dev);
	if (!m) {
		r->rc = -1001;
		HD_RETURN;
	}

	cfg = (struct mmc_config *)m->cfg;
	cfg->host_caps &= ~(MMC_MODE_HS | MMC_MODE_HS_52MHz |
			    MMC_MODE_DDR_52MHz | MMC_MODE_8BIT | MMC_MODE_4BIT);
	if (r->dev == 1 && hd_reader_request[7]) {
		if (hd_reader_request[7] == 2) {
			writel(0, (void *)0x01c11078);
			udelay(10);
		}
		writel(1, (void *)0x01c11078);
		udelay(300);
	}
	if (r->dev == 1)
		hd_sample_pins(r->pin_samples);
	if (r->dev == 1 && hd_reader_request[7] == 4) {
		clrbits_le32((void *)0x01c1105c, 0x80000000);
		clrbits_le32((void *)0x01c11004, 1U << 17);
	}

	cfg->f_max = 400000;
	r->phase = 3;
	rc = mmc_init(m);
	r->rc = rc;
	r->bus_width = m->bus_width;
	r->clock = m->clock;
	memcpy((void *)r->cid, m->cid, sizeof(m->cid));
	if (rc)
		HD_RETURN;

	bd = mmc_get_blk_desc(m);
	r->blocklen = bd->blksz;
	r->sectors_lo = bd->lba;
	r->sectors_hi = (u64)bd->lba >> 32;
	if (bd->blksz != 512 || lba > (u64)bd->lba ||
	    blocks > (u64)bd->lba - lba) {
		r->rc = -1005;
		HD_RETURN;
	}
	if (bd->lba != hd_reader_request[15] ||
	    memcmp(m->cid, (const void *)&hd_reader_request[11], 16)) {
		r->rc = -1100;
		HD_RETURN;
	}

	cfg->f_max = hz;
	rc = mmc_set_clock(m, hz, false);
	r->clock = m->clock;
	if (rc) {
		r->rc = rc;
		HD_RETURN;
	}

	r->phase = 4;
	memset((void *)0x43001000, 0xcc, blocks * 512);
	got = blk_dread(bd, lba, blocks, (void *)0x43001000);
	r->rc = (got == blocks) ? 0 : -1002;
	r->phase = 5;
	if (r->rc)
		HD_RETURN;

	r->old_crc = hd_crc32((const unsigned char *)0x43001000, blocks * 512);
	hd_snapshot(r->regs_after);
}
