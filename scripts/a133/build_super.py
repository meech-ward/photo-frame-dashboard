#!/usr/bin/env python3
"""Build a replacement super image: GSI as `system`, factory `vendor` + `product` byte-identical
at their original locations, `scratch` dropped. Offline only.
usage: build_super.py factory_super.img gsi_system.img out_super.img"""
import hashlib, json, shutil, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import liblp
S = liblp.SECTOR
ALIGN = 2048  # 1 MiB in sectors

def main(factory, gsi, out):
    fac = open(factory, 'rb').read()
    g, prim, back = liblp.read_super_metadata(fac[:1 << 20])
    base = liblp.parse_metadata(prim[1])          # slot 1 = original factory layout (no scratch)
    cur = liblp.parse_metadata(prim[0])           # slot 0 = current (with scratch)
    for name in ('vendor', 'product'):            # vendor/product must be identical in both
        assert liblp.partition_extents(base, name) == liblp.partition_extents(cur, name), name
    bdev = base['block_devices'][0]
    total = bdev['size'] // S
    vend = liblp.partition_extents(base, 'vendor'); prod = liblp.partition_extents(base, 'product')
    gsi_size = os.path.getsize(gsi); assert gsi_size % S == 0
    need = gsi_size // S
    # system extent A: from first logical sector up to vendor start; extent C: after product, 1 MiB aligned
    a_start, a_len = bdev['first_logical_sector'], vend[0]['target_data'] - bdev['first_logical_sector']
    p_end = prod[-1]['target_data'] + prod[-1]['num_sectors']
    c_start = -(-p_end // ALIGN) * ALIGN
    c_len = need - a_len
    assert c_len > 0 and c_start + c_len <= total, (c_start, c_len, total)
    sys_ext = [dict(num_sectors=a_len, target_type=0, target_data=a_start, target_source=0),
               dict(num_sectors=c_len, target_type=0, target_data=c_start, target_source=0)]
    grp_sb = next(i for i, x in enumerate(base['groups']) if x['name'] == 'sb')
    new = dict(partitions=[], extents=[], groups=base['groups'], block_devices=base['block_devices'])
    for name, exts in (('system', sys_ext), ('vendor', vend), ('product', prod)):
        p = next(p for p in base['partitions'] if p['name'] == name)
        new['partitions'].append(dict(name=name, attributes=p['attributes'], first_extent_index=len(new['extents']),
                                      num_extents=len(exts), group_index=grp_sb))
        new['extents'] += [dict(e) for e in exts]
    md = liblp.build_metadata(new)
    assert len(md) <= g['metadata_max_size']
    slot = md + b'\0' * (g['metadata_max_size'] - len(md))
    # assemble image: start from factory bytes (keeps vendor/product/geometry exactly), then overwrite
    shutil.copyfile(factory, out)
    with open(out, 'r+b') as f:
        mbase = liblp.RESERVED + 2 * liblp.GEOM_SIZE
        f.seek(mbase); f.write(slot * (2 * g['metadata_slot_count']))   # all primary + backup slots
        with open(gsi, 'rb') as src:
            for e in sys_ext:
                f.seek(e['target_data'] * S); remaining = e['num_sectors'] * S
                while remaining:
                    chunk = src.read(min(remaining, 64 << 20)); assert chunk; f.write(chunk); remaining -= len(chunk)
            assert src.read(1) == b''
    print(liblp.describe(new))
    json.dump(dict(new=new, geometry=g), open(out + '.layout.json', 'w'), indent=1, default=str)

if __name__ == '__main__':
    main(*sys.argv[1:4])
