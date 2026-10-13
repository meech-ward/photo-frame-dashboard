#!/usr/bin/env python3
"""Prepare, verify the dump, or remove the PF1007L SD bootloader on macOS."""
import argparse
import fcntl
import importlib.util
import gzip
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 4 * 1024 * 1024
OFFSET = 8192
SECTOR = 512
MAX_CARD = 256 * 1000**3
DKIOCSYNCHRONIZECACHE = 0x20006416
EXPECTED_BYTES = None  # set from the command line; guards against a disk number that changed


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def info(identifier):
    return plistlib.loads(subprocess.check_output(
        ['/usr/sbin/diskutil', 'info', '-plist', identifier]))


WORK = ROOT / 'diagnostics/a33-sdboot/macos-card'
STATE = WORK / 'card.json'
BACKUP = WORK / 'card-prefix.bin.gz'
DISK_KEYS = ('MediaName', 'TotalSize', 'DeviceBlockSize', 'Internal',
             'RemovableMedia', 'BusProtocol', 'VirtualOrPhysical')
PART_KEYS = ('VolumeUUID', 'PartitionMapPartitionOffset', 'IOKitSize',
             'FilesystemName', 'FilesystemType')


def card_disk(disk):
    require(re.fullmatch(r'disk[1-9][0-9]*', disk), 'Use diskN from diskutil list external physical')
    current = info(disk)
    require(current.get('Internal') is False and current.get('WholeDisk') is True and
            current.get('RemovableMedia') is True and current.get('BusProtocol') == 'USB' and
            current.get('VirtualOrPhysical') == 'Physical', 'Expected a removable USB card reader')
    require(4 * 1000**3 <= current.get('TotalSize', 0) <= MAX_CARD,
            'Expected a 4–256 GB card')
    require(current.get('TotalSize') == EXPECTED_BYTES,
            f"{disk} is {current.get('TotalSize')} bytes, not the {EXPECTED_BYTES} you passed")
    require(current.get('DeviceBlockSize') == SECTOR, 'Expected 512-byte sectors')
    return current


def save_target(disk):
    current = card_disk(disk)
    part = info(disk + 's1')
    require(current.get('Content') == 'FDisk_partition_scheme' and
            part.get('FilesystemName') == 'MS-DOS FAT32' and part.get('VolumeUUID'),
            'Expected MBR / FAT32 with a volume UUID')
    target = {'disk': {k: current[k] for k in DISK_KEYS},
              'partition': {k: part[k] for k in PART_KEYS}}
    STATE.write_text(json.dumps(target, indent=2) + '\n')
    owner = int(os.environ.get('SUDO_UID', os.getuid()))
    group = int(os.environ.get('SUDO_GID', os.getgid()))
    os.chown(WORK, owner, group)
    os.chown(STATE, owner, group)
    return target


def verify_target(target, disk):
    current = card_disk(disk)
    part = info(disk + 's1')
    for expected, actual in ((target['disk'], current), (target['partition'], part)):
        require(all(actual.get(k) == v for k, v in expected.items()),
                'This is not the saved card')
    require(current.get('Content') == 'FDisk_partition_scheme', 'Expected MBR')
    return Path(part['MountPoint']) if part.get('MountPoint') else None


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def load_artifacts():
    output = ROOT / 'diagnostics/a33-sdboot'
    entries = dict(line.split()[::-1] for line in (output / 'SHA256SUMS').read_text().splitlines())
    require(set(entries) == {'u-boot-sunxi-with-spl.bin', 'a33.scr'}, 'Unexpected build manifest')
    artifacts = {name: (output / name).read_bytes() for name in entries}
    for name, data in artifacts.items():
        require(hashlib.sha256(data).hexdigest() == entries[name], f'Build hash mismatch: {name}')
    image = artifacts['u-boot-sunxi-with-spl.bin']
    require(image[4:12] == b'eGON.BT0', 'Missing Allwinner SPL header')
    require(OFFSET + len(image) <= 1024 * 1024, 'Boot image exceeds the upstream 1 MiB limit')
    script = artifacts['a33.scr']
    check_script(script, (ROOT / 'scripts/a33-sdboot/emmc-dump.cmd').read_bytes())
    return image, script


def planned_prefix(before, image):
    require(len(before) == PREFIX, 'Short card read')
    require(before[510:512] == b'\x55\xaa', 'Missing MBR signature')
    entries = [before[446+i*16:462+i*16] for i in range(4)]
    require(entries[0][4] in (0x0b, 0x0c), 'Partition 1 must be FAT32')
    require(all(entry[4] == 0 for entry in entries[1:]), 'Expected exactly one partition')
    start = struct.unpack_from('<I', entries[0], 8)[0] * 512
    require(start >= PREFIX and OFFSET + len(image) <= min(start, 1024 * 1024),
            'Boot image overlaps the partition or exceeds the boot area')
    require(before[OFFSET+4:OFFSET+12] != b'eGON.BT0', 'Card already contains a boot image')
    return before[:OFFSET] + image + before[OFFSET+len(image):]


def read_prefix(raw):
    with open(raw, 'rb', buffering=0) as handle:
        return handle.read(PREFIX)


def load_prefix_backup(raw, backup, image):
    current = read_prefix(raw)
    require(read_prefix(raw) == current, 'Independent card reads differ')
    if backup.exists():
        before = gzip.decompress(backup.read_bytes())
        expected = planned_prefix(before, image)
        require(current in (before, expected),
                'Card does not match the saved prefix or the complete boot image; keep the backup')
    else:
        before = current
        planned_prefix(before, image)
        with gzip.open(backup, 'xb') as handle:
            handle.write(before)
        with backup.open('rb') as handle:
            os.fsync(handle.fileno())
    require(gzip.decompress(backup.read_bytes()) == before, 'Prefix backup verification failed')
    return before


def write_boot_image(raw, before, image):
    expected = planned_prefix(before, image)
    current = read_prefix(raw)
    require(current in (before, expected), 'Boot area changed after backup; keep the backup')
    # macOS raw disks require whole sectors. Preserve the original sector tail.
    length = ((len(image) + SECTOR - 1) // SECTOR) * SECTOR
    written = 0
    descriptor = os.open(raw, os.O_RDWR | os.O_NOFOLLOW)
    try:
        if current != expected:
            written = os.pwrite(descriptor, expected[OFFSET:OFFSET+length], OFFSET)
            require(written == length, 'Short boot-image write; keep the backup')
        fcntl.ioctl(descriptor, DKIOCSYNCHRONIZECACHE)
    finally:
        os.close(descriptor)
    require(read_prefix(raw) == expected, 'Full prefix readback failed; keep the backup')
    return written


def prepare(disk):
    require(os.geteuid() == 0, 'Run prepare with sudo')
    image, script = load_artifacts()
    if STATE.exists():
        target = json.loads(STATE.read_text())
        verify_target(target, disk)
    else:
        require(not BACKUP.exists(), 'Prefix backup exists without saved card identity')
        original = card_disk(disk)
        print(f"Erase {disk}: {original['MediaName']}, {original['TotalSize'] / 1e9:.1f} GB")
        require(input(f'Type ERASE {disk}: ').strip() == f'ERASE {disk}', 'Cancelled')
        current = card_disk(disk)
        require(all(current.get(k) == original.get(k) for k in DISK_KEYS + ('DeviceTreePath',)),
                'Disk changed before format')
        WORK.mkdir(parents=True, exist_ok=True)
        subprocess.run(['diskutil', 'partitionDisk', disk, 'MBR', 'Free Space', '%noformat%',
                        '16M', 'MS-DOS FAT32', 'FRAMEBOOT', '0b'], check=True)
        target = save_target(disk)
    subprocess.run(['diskutil', 'unmountDisk', disk], check=True)
    require(verify_target(target, disk) is None, 'Card is still mounted; close its Finder window')
    raw = f'/dev/r{disk}'
    require(stat.S_ISCHR(os.lstat(raw).st_mode), 'Expected a raw card device')
    before = load_prefix_backup(raw, BACKUP, image)
    os.chown(BACKUP, int(os.environ.get('SUDO_UID', os.getuid())),
             int(os.environ.get('SUDO_GID', os.getgid())))
    subprocess.run(['diskutil', 'mount', disk + 's1'], check=True)
    mount = verify_target(target, disk)
    require(mount is not None, 'Card did not mount')
    space = os.statvfs(mount)
    require(space.f_bavail * space.f_frsize >= 2_200_000_000, 'Need 2.2 GB free')
    if (mount / 'a33.scr').exists():
        require((mount / 'a33.scr').read_bytes() == script, 'Unexpected existing script')
    else:
        write_file(mount / 'a33.scr', script)
    subprocess.run(['diskutil', 'unmountDisk', disk], check=True)
    require(verify_target(target, disk) is None, 'Card is still mounted')
    write_boot_image(raw, before, image)
    subprocess.run(['diskutil', 'eject', disk], check=True)
    print('Backup card verified and ejected. Boot it in the frame for 30 minutes.')


def write_file(path, data):
    with path.open('xb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    require(path.read_bytes() == data, f'Readback failed: {path.name}')


def checked_mount(disk):
    target = json.loads(STATE.read_text())
    if verify_target(target, disk) is None:
        subprocess.run(['diskutil', 'mount', disk + 's1'], check=True)
    mount = verify_target(target, disk)
    require(mount is not None, 'Card did not mount')
    return target, mount


def checked_dump(card):
    check = module('dump_check', ROOT / 'scripts/a33-sdboot/check-dump.py')
    env = check.status(card)
    require(env.get('a33_stage') == 'finished' and env.get('emmc_dev') == 'ok',
            'Backup did not finish')
    require({k for k in env if k.startswith('st_')} == {f'st_{i:02x}' for i in range(32)},
            'Expected all 32 backup chunks')
    for i in range(32):
        fields = env[f'st_{i:02x}'].split()
        require(len(fields) >= 3 and fields[0] == 'ok' and int(fields[1], 16) == i * 131072,
                f'Backup chunk {i:02x} failed')
        require((card / f'emmc-{i:02x}.bin').stat().st_size == check.CHUNK,
                f'Backup chunk {i:02x} has the wrong size')
    check.main(card)
    (check.DEST / 'a33-status.txt').write_bytes((card / 'a33-status.txt').read_bytes())


def check_script(script, source):
    header = bytearray(script[:64])
    require(len(header) == 64, 'Short script')
    magic, crc, _, size, _, _, data_crc = struct.unpack_from('>7I', header)
    header[4:8] = bytes(4)
    payload = script[64:]
    require(magic == 0x27051956 and header[30:32] == bytes((6, 0)) and
            zlib.crc32(header) == crc and len(payload) == size and
            zlib.crc32(payload) == data_crc and
            payload == struct.pack('>II', len(source), 0) + source,
            'Compiled script does not match checked source')


def backup(disk):
    require(os.geteuid() != 0, 'Run backup without sudo')
    _, mount = checked_mount(disk)
    checked_dump(mount)
    subprocess.run(['diskutil', 'eject', disk], check=True)
    print('All 32 chunks verified and saved in backups/pf1007-emmc/. Card ejected.')


def clean(disk):
    require(os.geteuid() == 0, 'Run clean with sudo')
    target, _ = checked_mount(disk)
    image, _ = load_artifacts()
    before = gzip.decompress(BACKUP.read_bytes())
    expected = planned_prefix(before, image)
    subprocess.run(['diskutil', 'unmountDisk', disk], check=True)
    require(verify_target(target, disk) is None, 'Card is still mounted')
    raw = f'/dev/r{disk}'
    require(read_prefix(raw) == expected, 'Card boot area changed')
    descriptor = os.open(raw, os.O_RDWR | os.O_NOFOLLOW)
    try:
        require(os.pwrite(descriptor, before, 0) == PREFIX, 'Short restore write')
        fcntl.ioctl(descriptor, DKIOCSYNCHRONIZECACHE)
    finally:
        os.close(descriptor)
    require(read_prefix(raw) == before, 'Card restore readback failed')
    subprocess.run(['diskutil', 'eject', disk], check=True)
    print('SD bootloader removed. Card files are unchanged. Card ejected.')


def main():
    require(sys.platform == 'darwin', 'Run on macOS')
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=('prepare', 'backup', 'clean'))
    parser.add_argument('disk', help='diskN from diskutil list external physical')
    parser.add_argument('exact_bytes', type=int, help="the card's Disk Size in bytes, from diskutil info diskN")
    args = parser.parse_args()
    global EXPECTED_BYTES
    EXPECTED_BYTES = args.exact_bytes
    {'prepare': prepare, 'backup': backup, 'clean': clean}[args.step](args.disk)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(f'STOP: {error}') from error
