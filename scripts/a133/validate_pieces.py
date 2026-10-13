#!/usr/bin/env python3
"""Validate sparse pieces for U-Boot fastboot flashing.
usage: validate_pieces.py <partition_bytes> <expected_raw_image|-> piece0 [piece1 ...]
Checks per piece: magic/version/header sizes, blk_sz 4096, identical total_blks, chunk sum == total_blks,
only RAW/DONT_CARE chunks (the types proven on-device in test D2), size <= 32 MiB, and that every RAW
byte lands inside the partition (U-Boot does not bounds-check sparse writes).
Then replays all pieces in order onto a zero buffer and compares with the expected image (if given)."""
import hashlib, struct, sys, os
MAX = 32 << 20
part_bytes, expected, pieces = int(sys.argv[1]), sys.argv[2], sys.argv[3:]
ok = True
def check(c, m):
    global ok; ok &= bool(c)
    if not c: print('FAIL', m)
tb0 = None; written = []  # (start, end) byte ranges
for p in pieces:
    d = open(p, 'rb').read()
    magic, maj, mnr, fh, ch, bs, tb, tc, _ = struct.unpack_from('<IHHHHIIII', d)
    check(len(d) <= MAX, f'{p} size {len(d)} <= 32 MiB')
    check((magic, maj, mnr, fh, ch, bs) == (0xED26FF3A, 1, 0, 28, 12, 4096), f'{p} header')
    tb0 = tb0 or tb; check(tb == tb0, f'{p} total_blks consistent')
    check(tb * bs <= part_bytes, f'{p} total_blks*4096 {tb*bs} <= partition {part_bytes}')
    off, blk = fh, 0
    for _ in range(tc):
        t, _r, n, tot = struct.unpack_from('<HHII', d, off)
        check(t in (0xCAC1, 0xCAC3), f'{p} chunk type {hex(t)} is RAW/DONT_CARE')
        if t == 0xCAC1:
            check(tot == ch + n * bs, f'{p} RAW chunk size'); written.append((blk * bs, (blk + n) * bs, p, off + ch))
            check((blk + n) * bs <= part_bytes, f'{p} RAW end within partition')
        else: check(tot == ch, f'{p} DONT_CARE size')
        blk += n; off += tot
    check(blk == tb, f'{p} chunk blocks {blk} == total_blks {tb}')
    check(off == len(d), f'{p} no trailing bytes')
written.sort()
check(all(a[1] <= b[0] for a, b in zip(written, written[1:])), 'RAW ranges do not overlap across pieces')
covered = sum(e - s for s, e, *_ in written)
print(f'{len(pieces)} pieces, total_blks={tb0} ({tb0*4096} B), RAW bytes written={covered}, max RAW end={max(e for _, e, *_ in written)}')
if expected != '-':
    exp_size = os.path.getsize(expected)
    check(covered == exp_size and written[0][0] == 0 and all(a[1] == b[0] for a, b in zip(written, written[1:])),
          'RAW ranges contiguous and exactly cover expected image')
    h = hashlib.sha256(); cache = {}
    for s, e, p, doff in written:
        if p not in cache: cache.clear(); cache[p] = open(p, 'rb').read()
        h.update(cache[p][doff:doff + (e - s)])
    eh = hashlib.sha256(open(expected, 'rb').read()).hexdigest()
    check(h.hexdigest() == eh, f'replayed pieces sha256 {h.hexdigest()[:16]} == expected {eh[:16]}')
print('OVERALL:', 'PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
