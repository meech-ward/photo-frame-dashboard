#!/usr/bin/env python3
"""Minimal liblp (Android 10 dynamic partitions, metadata v10.0) parser/serializer.
Layout on the super device:
  [0,4096)            reserved (zeros)
  [4096,8192)         geometry (primary)
  [8192,12288)        geometry (backup)
  [12288, +max*slots) primary metadata slots
  [.., +max*slots)    backup metadata slots
Format: system/core/fs_mgr/liblp/include/liblp/metadata_format.h (android10-release)."""
import hashlib, struct

SECTOR = 512
RESERVED = 4096
GEOM_SIZE = 4096
GEOM_MAGIC = 0x616C4467
HDR_MAGIC = 0x414C5030
GEOM_FMT = '<II32sIII'          # magic, struct_size, checksum, metadata_max_size, slot_count, logical_block_size
HDR_FMT = '<IHHI32sI32s' + 'III' * 4
HDR_SIZE = struct.calcsize(HDR_FMT)  # 128
PART_FMT, EXT_FMT, GRP_FMT, BDEV_FMT = '<36sIIII', '<QIQI', '<36sIQ', '<QIIQ36sI'

def _cstr(b): return b.split(b'\0', 1)[0].decode()
def _pad(s, n): b = s.encode(); assert len(b) <= n; return b + b'\0' * (n - len(b))

def parse_geometry(buf):
    magic, size, csum, maxsz, slots, lbs = struct.unpack_from(GEOM_FMT, buf)
    assert magic == GEOM_MAGIC, hex(magic)
    raw = bytearray(buf[:size]); raw[8:40] = b'\0' * 32
    assert hashlib.sha256(raw).digest() == csum, 'geometry checksum'
    return dict(struct_size=size, metadata_max_size=maxsz, metadata_slot_count=slots, logical_block_size=lbs)

def build_geometry(g):
    raw = bytearray(struct.pack(GEOM_FMT, GEOM_MAGIC, g['struct_size'], b'\0' * 32,
                                g['metadata_max_size'], g['metadata_slot_count'], g['logical_block_size']))
    raw[8:40] = hashlib.sha256(raw).digest()
    return bytes(raw) + b'\0' * (GEOM_SIZE - len(raw))

def parse_metadata(buf):
    f = struct.unpack_from(HDR_FMT, buf)
    magic, major, minor, hsize, hcsum, tsize, tcsum = f[:7]
    assert magic == HDR_MAGIC and (major, minor) == (10, 0), (hex(magic), major, minor)
    raw = bytearray(buf[:hsize]); raw[12:44] = b'\0' * 32
    assert hashlib.sha256(raw).digest() == hcsum, 'header checksum'
    tables = buf[hsize:hsize + tsize]
    assert hashlib.sha256(tables).digest() == tcsum, 'tables checksum'
    desc = [f[7 + 3 * i: 10 + 3 * i] for i in range(4)]
    def rows(i, fmt):
        off, n, es = desc[i]; assert es == struct.calcsize(fmt)
        return [struct.unpack_from(fmt, tables, off + k * es) for k in range(n)]
    m = dict(header_size=hsize,
             partitions=[dict(name=_cstr(r[0]), attributes=r[1], first_extent_index=r[2], num_extents=r[3], group_index=r[4]) for r in rows(0, PART_FMT)],
             extents=[dict(num_sectors=r[0], target_type=r[1], target_data=r[2], target_source=r[3]) for r in rows(1, EXT_FMT)],
             groups=[dict(name=_cstr(r[0]), flags=r[1], maximum_size=r[2]) for r in rows(2, GRP_FMT)],
             block_devices=[dict(first_logical_sector=r[0], alignment=r[1], alignment_offset=r[2], size=r[3], partition_name=_cstr(r[4]), flags=r[5]) for r in rows(3, BDEV_FMT)],
             _desc=desc)
    return m

def build_metadata(m):
    parts = b''.join(struct.pack(PART_FMT, _pad(p['name'], 36), p['attributes'], p['first_extent_index'], p['num_extents'], p['group_index']) for p in m['partitions'])
    exts = b''.join(struct.pack(EXT_FMT, e['num_sectors'], e['target_type'], e['target_data'], e['target_source']) for e in m['extents'])
    grps = b''.join(struct.pack(GRP_FMT, _pad(g['name'], 36), g['flags'], g['maximum_size']) for g in m['groups'])
    bdevs = b''.join(struct.pack(BDEV_FMT, b['first_logical_sector'], b['alignment'], b['alignment_offset'], b['size'], _pad(b['partition_name'], 36), b['flags']) for b in m['block_devices'])
    tables = parts + exts + grps + bdevs
    o1, o2, o3 = len(parts), len(parts) + len(exts), len(parts) + len(exts) + len(grps)
    desc = [(0, len(m['partitions']), 52), (o1, len(m['extents']), 24), (o2, len(m['groups']), 48), (o3, len(m['block_devices']), 64)]
    hdr = bytearray(struct.pack(HDR_FMT, HDR_MAGIC, 10, 0, HDR_SIZE, b'\0' * 32, len(tables), hashlib.sha256(tables).digest(), *[x for d in desc for x in d]))
    hdr[12:44] = hashlib.sha256(hdr).digest()
    return bytes(hdr) + tables

def read_super_metadata(dev):
    """Return (geometry, [slot metadata bytes primary...], [backup...]) from a super image file object/bytes."""
    g = parse_geometry(dev[RESERVED:RESERVED + GEOM_SIZE])
    assert dev[RESERVED:RESERVED + GEOM_SIZE] == dev[RESERVED + GEOM_SIZE:RESERVED + 2 * GEOM_SIZE], 'backup geometry differs'
    base = RESERVED + 2 * GEOM_SIZE; mx, n = g['metadata_max_size'], g['metadata_slot_count']
    prim = [dev[base + i * mx: base + (i + 1) * mx] for i in range(n)]
    back = [dev[base + n * mx + i * mx: base + n * mx + (i + 1) * mx] for i in range(n)]
    return g, prim, back

def metadata_region_end(g):
    return RESERVED + 2 * GEOM_SIZE + 2 * g['metadata_max_size'] * g['metadata_slot_count']

def partition_extents(m, name):
    p = next(p for p in m['partitions'] if p['name'] == name)
    return m['extents'][p['first_extent_index']: p['first_extent_index'] + p['num_extents']]

def describe(m):
    out = []
    for p in m['partitions']:
        ex = partition_extents(m, p['name'])
        out.append(f"{p['name']:10} grp={m['groups'][p['group_index']]['name']:8} attr={p['attributes']} "
                   f"size={sum(e['num_sectors'] for e in ex) * SECTOR:>12} extents=" +
                   ", ".join(f"[{e['target_data']}+{e['num_sectors']}]" for e in ex))
    for g in m['groups']: out.append(f"group {g['name']:8} flags={g['flags']} max={g['maximum_size']}")
    for b in m['block_devices']: out.append(f"bdev {b['partition_name']} first_logical_sector={b['first_logical_sector']} align={b['alignment']} off={b['alignment_offset']} size={b['size']} flags={b['flags']}")
    return "\n".join(out)
