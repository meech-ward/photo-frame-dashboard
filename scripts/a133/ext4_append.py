#!/usr/bin/env python3
"""Append bytes to an existing file inside an ext4 image IN PLACE, only when the data fits in the slack of
the file's last (unshared) block. Works with shared_blocks images (no metadata_csum). Uses debugfs for lookups.
usage: ext4_append.py image /path/in/fs data_file"""
import re, struct, subprocess, sys
DEBUGFS = subprocess.check_output(['brew', '--prefix', 'e2fsprogs'], text=True).strip() + '/sbin/debugfs'
img, path, addf = sys.argv[1:4]
add = open(addf, 'rb').read()
def dbg(cmd): return subprocess.run([DEBUGFS, '-R', cmd, img], capture_output=True, text=True).stdout
st = dbg(f'stat {path}')
ino = int(re.search(r'Inode: (\d+)', st).group(1)); size = int(re.search(r'Size: (\d+)', st).group(1))
assert 'Type: regular' in st and 'metadata_csum' not in subprocess.run([DEBUGFS, '-R', 'stats', img], capture_output=True, text=True).stdout
blocks = [int(b) for b in dbg(f'blocks {path}').split()]
BS = 4096; assert len(blocks) == -(-size // BS), (len(blocks), size)
last = blocks[-1]; used = size - (len(blocks) - 1) * BS
assert used + len(add) <= BS, f'not enough slack: {BS - used} < {len(add)}'
# verify last block not referenced by any other inode
n_inodes = int(re.search(r'Inode count:\s+(\d+)', dbg('stats')).group(1))
cmds = ''.join(f'blocks <{i}>\n' for i in range(1, n_inodes + 1))
out = subprocess.run([DEBUGFS, '-f', '-', img], input=cmds, capture_output=True, text=True).stdout
owners = [int(m.group(1)) for m in re.finditer(r'blocks <(\d+)>\n([^\n]*)', out) if str(last) in m.group(2).split()]
assert owners == [ino], f'block {last} owners {owners}'
m = re.search(r'located at block (\d+), offset (0x[0-9a-f]+)', dbg(f'imap {path}'))
iblk, ioff = int(m.group(1)), int(m.group(2), 16)
with open(img, 'r+b') as f:
    f.seek(iblk * BS + ioff); inode = bytearray(f.read(256))
    assert struct.unpack_from('<I', inode, 4)[0] == size & 0xffffffff and struct.unpack_from('<I', inode, 0x6C)[0] == size >> 32
    f.seek(last * BS); blk = bytearray(f.read(BS)); assert not any(blk[used:]), 'slack not zero'
    blk[used:used + len(add)] = add; f.seek(last * BS); f.write(blk)
    struct.pack_into('<I', inode, 4, size + len(add)); f.seek(iblk * BS + ioff); f.write(inode)
print(f'{path}: inode {ino}, last block {last} (unshared), size {size} -> {size + len(add)}')
