#!/usr/bin/env python3
"""Copy phh121.img and append ro.surface_flinger.primary_display_orientation=<ORIENT> to
/system/product/etc/build.prop in place (block 196166 verified unshared; inode 2679 at blk 131105 +0x600).
usage: patch_gsi_orientation.py src.img dst.img ORIENTATION_90"""
import shutil, struct, sys
src, dst, orient = sys.argv[1:4]
BS, BLK, INO_BLK, INO_OFF, OLD = 4096, 196166, 131105, 0x600, 1390
shutil.copyfile(src, dst)
with open(dst, 'r+b') as f:
    f.seek(INO_BLK * BS + INO_OFF); ino = bytearray(f.read(256))
    assert struct.unpack_from('<I', ino, 4)[0] == OLD and struct.unpack_from('<I', ino, 0x6C)[0] == 0
    f.seek(BLK * BS); blk = bytearray(f.read(BS)); old = bytes(blk[:OLD])
    assert b'ro.product.product.brand=google' in old and not any(blk[OLD:])
    new = old + (b'' if old.endswith(b'\n') else b'\n') + \
        b'# LOOFII C-3: touch digitizer is 90deg from panel; offset display, lock user_rotation\n' + \
        f'ro.surface_flinger.primary_display_orientation={orient}\n'.encode()
    blk[:len(new)] = new; f.seek(BLK * BS); f.write(blk)
    struct.pack_into('<I', ino, 4, len(new)); f.seek(INO_BLK * BS + INO_OFF); f.write(ino)
print('patched', dst, 'size', len(new))
