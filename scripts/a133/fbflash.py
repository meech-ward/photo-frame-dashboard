#!/usr/bin/env python3
"""Flash sparse pieces to ONE named partition via Allwinner U-Boot fastboot (1f3a:1010).
Guards (all checked before anything is sent):
  - the partition must equal env FB_ALLOW_FLASH;
  - env FB_PART_BYTES must be the partition's exact size (read it on the device first:
    `adb shell blockdev --getsize64 /dev/block/by-name/<partition>`), and every piece must be an Android sparse
    image whose total size equals it, using only RAW and DONT_CARE chunks that add up to that total.
U-Boot fastboot on this board does not bounds-check sparse images, so a wrong piece can write past the partition.
usage: fbflash.py <partition> piece0.simg [piece1 ...]"""
import os, struct, sys
part, files = sys.argv[1], sys.argv[2:]
if os.environ.get("FB_ALLOW_FLASH") != part: sys.exit(f"REFUSED: set FB_ALLOW_FLASH={part} to confirm")
try: want = int(os.environ["FB_PART_BYTES"])
except (KeyError, ValueError): sys.exit("REFUSED: set FB_PART_BYTES to the exact size of the partition (blockdev --getsize64)")
if not files: sys.exit("no pieces given")
def check_piece(f):
    with open(f, "rb") as h:
        magic, _maj, _min, fhs, chs, blk, total, nchunks, _crc = struct.unpack("<IHHHHIIII", h.read(28))
        if magic != 0xED26FF3A: sys.exit(f"REFUSED: {f} is not an Android sparse image")
        if blk * total != want: sys.exit(f"REFUSED: {f} covers {blk * total} B, partition is {want} B")
        h.seek(fhs); seen = 0
        for _ in range(nchunks):
            ctype, _r, cblks, csize = struct.unpack("<HHII", h.read(chs)); h.seek(h.tell() - chs + csize)
            if ctype not in (0xCAC1, 0xCAC3): sys.exit(f"REFUSED: {f} has chunk type {ctype:#x} (only RAW/DONT_CARE allowed)")
            seen += cblks
        if seen != total: sys.exit(f"REFUSED: {f} chunks cover {seen} blocks, header says {total}")
for f in files: check_piece(f)
print(f"{len(files)} piece(s) checked against {part} = {want} B")
import usb.core, usb.util
d = usb.core.find(idVendor=0x1f3a, idProduct=0x1010) or sys.exit("no U-Boot fastboot device")
try: d.set_configuration()
except usb.core.USBError: pass
intf = d.get_active_configuration()[(0, 0)]
epo = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
epi = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)
def resp(timeout=60000):
    msgs = []
    while True:
        r = bytes(epi.read(512, timeout=timeout)).decode(errors="replace"); msgs.append(r)
        if r[:4] in ("OKAY", "FAIL", "DATA"): return r, msgs
def cmd(c, timeout=60000):
    epo.write(c.encode()); return resp(timeout)
r, m = cmd("getvar:max-download-size"); maxdl = int(r[4:], 16); print("max-download-size", hex(maxdl))
for f in files:
    data = open(f, "rb").read(); assert len(data) <= maxdl, f"{f} too big"
    r, m = cmd(f"download:{len(data):08x}")
    if not r.startswith("DATA"): sys.exit(f"download refused: {m}")
    for i in range(0, len(data), 1 << 20): epo.write(data[i:i + (1 << 20)], timeout=60000)
    r, m = resp(); print(f"{os.path.basename(f)}: download {len(data)} B -> {m}")
    if not r.startswith("OKAY"): sys.exit("download failed")
    r, m = cmd(f"flash:{part}", timeout=300000); print(f"  flash:{part} -> {m}")
    if not r.startswith("OKAY"): sys.exit("flash failed")
print("done")
