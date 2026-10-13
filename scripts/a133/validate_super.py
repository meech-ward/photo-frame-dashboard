#!/usr/bin/env python3
"""Independent validation of a rebuilt super image vs the factory super + GSI image.
usage: validate_super.py new_super.img factory_super.img gsi_system.img"""
import hashlib, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import liblp
S = liblp.SECTOR
ok = True
def check(cond, msg):
    global ok; ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + msg)
def sha_range(path, start, length):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        f.seek(start)
        while length:
            b = f.read(min(length, 64 << 20)); assert b; h.update(b); length -= len(b)
    return h.hexdigest()

new, fac, gsi = sys.argv[1:4]
check(os.path.getsize(new) == os.path.getsize(fac) == 2147483648, 'size == factory super (2 GiB)')
nh, fh = open(new, 'rb').read(1 << 20), open(fac, 'rb').read(1 << 20)
check(nh[:liblp.RESERVED] == b'\0' * liblp.RESERVED, 'reserved 4 KiB is zero')
check(nh[liblp.RESERVED:liblp.RESERVED + 2 * liblp.GEOM_SIZE] == fh[liblp.RESERVED:liblp.RESERVED + 2 * liblp.GEOM_SIZE],
      'primary+backup geometry byte-identical to factory')
g, prim, back = liblp.read_super_metadata(nh)
mds = []
for i, (p, b) in enumerate(zip(prim, back)):
    m = liblp.parse_metadata(p)  # asserts magic/version/header+tables SHA-256
    check(True, f'slot {i} primary parses, v10.0, header+tables checksums valid')
    check(p == b, f'slot {i} backup == primary')
    re = liblp.build_metadata(m); check(p[:len(re)] == re and not any(p[len(re):]), f'slot {i} canonical re-encode identical')
    mds.append(m)
check(mds[0] == mds[1] or all(x == mds[0] for x in mds), 'all slots identical layout')
m = mds[0]
bd = m['block_devices'][0]
fac_g, fac_p, _ = liblp.read_super_metadata(fh)
fac_m = liblp.parse_metadata(fac_p[1])
check(m['block_devices'] == fac_m['block_devices'], 'block device entry identical to factory')
check(m['groups'] == fac_m['groups'], 'groups identical to factory (default, sb max 2139095040)')
check(liblp.metadata_region_end(g) <= bd['first_logical_sector'] * S, f"metadata region end {liblp.metadata_region_end(g)} <= first logical byte {bd['first_logical_sector']*S}")
check({p['name'] for p in m['partitions']} == {'system', 'vendor', 'product'}, 'partitions = system, vendor, product (scratch dropped)')
# bounds / overlap / alignment
spans = []
for p in m['partitions']:
    ex = liblp.partition_extents(m, p['name'])
    for e in ex:
        check(e['target_type'] == 0 and e['target_source'] == 0, f"{p['name']} extent linear on super")
        check(e['target_data'] >= bd['first_logical_sector'] and e['target_data'] + e['num_sectors'] <= bd['size'] // S,
              f"{p['name']} extent [{e['target_data']}+{e['num_sectors']}] within device")
        check((e['target_data'] * S) % bd['alignment'] == 0, f"{p['name']} extent start 1 MiB aligned")
        spans.append((e['target_data'], e['target_data'] + e['num_sectors'], p['name']))
spans.sort()
check(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), 'no extent overlaps: ' + ', '.join(f'{n}[{s}-{e})' for s, e, n in spans))
grp_total = sum(sum(e['num_sectors'] for e in liblp.partition_extents(m, p['name'])) * S for p in m['partitions'])
check(grp_total <= m['groups'][1]['maximum_size'], f'group sb usage {grp_total} <= max')
for name in ('vendor', 'product'):
    ne, fe = liblp.partition_extents(m, name), liblp.partition_extents(fac_m, name)
    check(ne == fe, f'{name} extents identical to factory')
    hn = [sha_range(new, e['target_data'] * S, e['num_sectors'] * S) for e in ne]
    hf = [sha_range(fac, e['target_data'] * S, e['num_sectors'] * S) for e in fe]
    check(hn == hf, f'{name} data byte-identical to factory ({hn[0][:16]})')
    p = next(p for p in m['partitions'] if p['name'] == name)
    check(p['attributes'] == 1, f'{name} readonly attribute')
# system logical reconstruction
h = hashlib.sha256(); n = 0
with open(new, 'rb') as f:
    for e in liblp.partition_extents(m, 'system'):
        f.seek(e['target_data'] * S); rem = e['num_sectors'] * S; n += rem
        while rem:
            b = f.read(min(rem, 64 << 20)); h.update(b); rem -= len(b)
gh = sha_range(gsi, 0, os.path.getsize(gsi))
check(n == os.path.getsize(gsi), f'system logical size {n} == GSI image size')
check(h.hexdigest() == gh, f'system reconstructed from extents == GSI sha256 {gh[:16]}')
print('\nOVERALL:', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
