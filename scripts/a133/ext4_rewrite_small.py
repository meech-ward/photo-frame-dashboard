#!/usr/bin/env python3
"""Replace the contents of a single-block file in an ext4 image IN PLACE (old and new size <= 4096, block unshared).
usage: ext4_rewrite_small.py image /path/in/fs new_content_file"""
import re, struct, subprocess, sys
DEBUGFS = subprocess.check_output(['brew', '--prefix', 'e2fsprogs'], text=True).strip() + '/sbin/debugfs'
img, path, newf = sys.argv[1:4]; new = open(newf, 'rb').read(); BS = 4096
def dbg(cmd): return subprocess.run([DEBUGFS, '-R', cmd, img], capture_output=True, text=True).stdout
st = dbg(f'stat {path}'); ino = int(re.search(r'Inode: (\d+)', st).group(1)); size = int(re.search(r'Size: (\d+)', st).group(1))
blocks = [int(b) for b in dbg(f'blocks {path}').split()]
assert len(blocks) == 1 and size <= BS and 0 < len(new) <= BS, (blocks, size, len(new))
n = int(re.search(r'Inode count:\s+(\d+)', dbg('stats')).group(1))
out = subprocess.run([DEBUGFS, '-f', '-', img], input=''.join(f'blocks <{i}>\n' for i in range(1, n + 1)), capture_output=True, text=True).stdout
owners = [int(m.group(1)) for m in re.finditer(r'blocks <(\d+)>\n([^\n]*)', out) if str(blocks[0]) in m.group(2).split()]
assert owners == [ino], owners
m = re.search(r'located at block (\d+), offset (0x[0-9a-f]+)', dbg(f'imap {path}')); iblk, ioff = int(m.group(1)), int(m.group(2), 16)
with open(img, 'r+b') as f:
    f.seek(iblk * BS + ioff); inode = bytearray(f.read(256)); assert struct.unpack_from('<I', inode, 4)[0] == size
    f.seek(blocks[0] * BS); f.write(new + b'\0' * (BS - len(new)))
    struct.pack_into('<I', inode, 4, len(new)); f.seek(iblk * BS + ioff); f.write(inode)
print(f'{path}: inode {ino}, block {blocks[0]} (unshared), size {size} -> {len(new)}')
