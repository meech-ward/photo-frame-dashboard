#!/usr/bin/env python3
"""Split a raw image into Android sparse pieces (each <= max_bytes), like `fastboot -S`.
Each piece covers the whole image: DONT_CARE for regions owned by other pieces.
Zero-filled 4K blocks are emitted as FILL chunks; others as RAW.
usage: mksparse.py raw.img out_prefix [max_bytes=33554432]"""
import struct, sys
BLK = 4096
MAGIC, MAJ, MIN, FHDR, CHDR = 0xED26FF3A, 1, 0, 28, 12
RAW, FILL, DONT_CARE = 0xCAC1, 0xCAC2, 0xCAC3

FORCE_RAW = False
def runs(data):
    """Yield (kind, start_blk, nblks) where kind is 'raw' or 'zero'."""
    n = len(data) // BLK; i = 0
    while i < n:
        z = (not FORCE_RAW) and data[i*BLK:(i+1)*BLK].count(0) == BLK
        j = i
        while j < n and ((not FORCE_RAW) and data[j*BLK:(j+1)*BLK].count(0) == BLK) == z: j += 1
        yield ('zero' if z else 'raw', i, j - i); i = j

def piece(total_blks, chunks):
    body = b''
    for kind, start, n, payload in chunks:
        if kind == 'dc':   body += struct.pack('<HHII', DONT_CARE, 0, n, CHDR)
        elif kind == 'zero': body += struct.pack('<HHII', FILL, 0, n, CHDR + 4) + b'\0\0\0\0'
        else:              body += struct.pack('<HHII', RAW, 0, n, CHDR + len(payload)) + payload
    hdr = struct.pack('<IHHHHIIII', MAGIC, MAJ, MIN, FHDR, CHDR, BLK, total_blks, len(chunks), 0)
    return hdr + body

def main(src, prefix, maxb=32*1024*1024):
    data = open(src, 'rb').read()
    assert len(data) % BLK == 0, "image size must be a multiple of 4096"
    total = len(data) // BLK
    budget = maxb - FHDR - 64  # leave room for trailing DONT_CARE
    pieces, cur, cur_size, pos = [], [], FHDR, 0
    def flush(end_blk):
        nonlocal cur, cur_size
        if cur:
            if end_blk < total: cur.append(('dc', end_blk, total - end_blk, b''))
            pieces.append(piece(total, cur))
        cur, cur_size = [], FHDR
    for kind, start, n in runs(data):
        while n:
            if not cur and start > 0: cur.append(('dc', 0, start, b'')); cur_size += CHDR
            if kind == 'zero':
                cur.append(('zero', start, n, b'')); cur_size += CHDR + 4; start += n; n = 0
            else:
                room = (budget - cur_size - CHDR) // BLK
                if room <= 0: flush(start); continue
                take = min(n, room)
                cur.append(('raw', start, take, data[start*BLK:(start+take)*BLK]))
                cur_size += CHDR + take*BLK; start += take; n -= take
                if n: flush(start)
    flush(total)
    for k, p in enumerate(pieces):
        assert len(p) <= maxb
        open(f'{prefix}.{k:03d}.simg', 'wb').write(p)
    print(f'{len(pieces)} piece(s), total_blks={total}')

def unsparse_check(prefix, n, size):
    """Re-apply pieces onto a zero buffer (simulating flash) and return bytes."""
    out = bytearray(size)
    for k in range(n):
        p = open(f'{prefix}.{k:03d}.simg', 'rb').read()
        magic, _, _, fh, ch, bs, tb, tc, _ = struct.unpack('<IHHHHIIII', p[:28]); off = fh; blk = 0
        assert magic == MAGIC
        for _ in range(tc):
            t, _, n_, tot = struct.unpack('<HHII', p[off:off+12]); d = p[off+12:off+tot]
            if t == RAW: out[blk*bs:(blk+n_)*bs] = d
            elif t == FILL: out[blk*bs:(blk+n_)*bs] = d[:4] * (n_*bs//4)
            blk += n_; off += tot
        assert blk == tb, (blk, tb)
    return bytes(out)

if __name__ == '__main__':
    import os
    FORCE_RAW = os.environ.get('FORCE_RAW') == '1'
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 32*1024*1024)
