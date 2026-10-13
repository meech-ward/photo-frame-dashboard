#!/usr/bin/env python3
"""Build the PF1007L one-sector build.prop edit for an SD-booted U-Boot card.

Writes, under diagnostics/a33-sector/ (git-ignored):
  sector-orig.bin, sector-adb.bin      the stock and edited 512-byte sectors, pinned by SHA-256
  check/sector-write.cmd               reads and saves the sector, compares it, never writes
  apply/sector-write.cmd               the guarded one-sector write (stock -> adb)
  restore/sector-write.cmd             the guarded undo (adb -> stock)

With --mkimage, each .cmd is also compiled to a33.scr next to it. Nothing here touches a card
or a frame. See docs/pf1007l-sector-edit-sdcard.md.

The stock sector is eMMC sector 399221 (0x61775) of the April 20260410 firmware: 512 bytes of
/system/build.prop text. The edit changes 12 bytes, persist.sys.usb.config=mass_storage to
persist.sys.usb.config=adb plus a #padding comment, so the file length does not change.
"""
import argparse
import base64
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / 'scripts/a33-sdboot/sector-write.cmd.in'
OUT = ROOT / 'diagnostics/a33-sector'

STOCK_SHA = 'f78d2d4e3924d752a5fdcca7722a4fa76aeff700ce09fd6076d5dea064e2a9c4'
ADB_SHA = '27907679fd0a15d87f03ab0326bb0ee3319ef6cd07cc07ca7e49504698ba8713'
OLD = b'persist.sys.usb.config=mass_storage\n'
NEW = b'persist.sys.usb.config=adb\n#padding\n'
STOCK = base64.b64decode(
    'ZWQudGVsZXBob255PWZhbHNlCmRhbHZpay52bS5ib290LWRleDJvYXQtdGhyZWFkcz00CmRhbHZp'
    'ay52bS5kZXgyb2F0LXRocmVhZHM9MwpkYWx2aWsudm0uaW1hZ2UtZGV4Mm9hdC10aHJlYWRzPTQK'
    'ZGFsdmlrLnZtLmRleDJvYXQtZmxhZ3M9LS1uby13YXRjaC1kb2cKZGFsdmlrLnZtLmppdC5jb2Rl'
    'Y2FjaGVzaXplPTAKcm8uYW0ucmVzY2hlZHVsZV9zZXJ2aWNlPXRydWUKcm8uZnJwLnBzdD0vZGV2'
    'L2Jsb2NrL2J5LW5hbWUvZnJwCnBlcnNpc3Quc3lzLnVzYi5jb25maWc9bWFzc19zdG9yYWdlCnJv'
    'LmFkYi5zZWN1cmU9MApyby5zeXMubXV0ZWRybT10cnVlCnJ3LmxvZ2dlcj0wCnJvLmNvbmZpZy5t'
    'ZWRpYT0xCmRhbHZpay52bS5oZWFwc2l6ZT0zODRtCmRhbHZpay52bS5oZWFwc3RhcnRzaXplPTht'
    'CmRhbHZpay52bS5oZWFwZ3Jvd3RobGltaXQ9ODBtCmRhbHZpay52bS5oZWFwdGFyZ2V0dXRpbGl6'
    'YXRpb249MC43NQpkYWx2aWsudm0uaGVhcG1pbmZyZWU9NTEyawpkYWx2aWsudm0uaGVhcG1heGY=')

# The check variant is the apply script with its one eMMC write replaced by a no-op branch.
WRITE_START = '                setenv a33_stage writing\n                mmc dev 1\n                if mmc write ${t} ${sec} 1; then'
WRITE_FAIL = '                  setenv result FAIL_MMC_WRITE'


def die(message):
    sys.exit(f'STOP: {message}')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fill(template, mode, source, target, sums):
    values = {'MODE': mode, 'FROM': source, 'TO': target,
              'SHA_FROM': sums[source], 'SHA_TO': sums[target]}
    for key, value in values.items():
        template = template.replace(f'@{key}@', value)
    if '@' in template.replace('@android', ''):
        die('unfilled placeholder in the template')
    return template


def check_variant(apply_script):
    if apply_script.count(WRITE_START) != 1 or apply_script.count(WRITE_FAIL) != 1:
        die('the apply script does not have exactly one guarded write')
    script = apply_script.replace(WRITE_START, '                setenv a33_stage check_only\n                if test 1 = 0; then')
    script = script.replace(WRITE_FAIL, '                  setenv result CHECK_OK_SECTOR_IS_ORIGINAL_NO_WRITE')
    script = script.replace('sector-before-apply.bin', 'sector-before-check.bin')
    script = script.replace('sector-after-apply.bin', 'sector-after-check.bin')
    script = script.replace('# a33: guarded one-sector edit', '# a33 CHECK ONLY (no eMMC write): guarded one-sector edit', 1)
    return script


def emmc_writes(script):
    code = [line for line in script.splitlines() if not line.strip().startswith('#')]
    return sum('mmc write' in line or 'mmc erase' in line or 'saveenv' in line for line in code)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mkimage', help='U-Boot mkimage to compile each script to a33.scr')
    args = parser.parse_args()

    if len(STOCK) != 512 or sha256(STOCK) != STOCK_SHA or STOCK.count(OLD) != 1:
        die('embedded stock sector is damaged')
    edited = STOCK.replace(OLD, NEW[:len(OLD)])
    if len(edited) != 512 or sha256(edited) != ADB_SHA:
        die('edited sector does not match its pinned SHA-256')

    files = {'sector-orig.bin': STOCK, 'sector-adb.bin': edited}
    sums = {name: sha256(data) for name, data in files.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    (OUT / 'SHA256SUMS').write_text(''.join(f'{sums[n]}  {n}\n' for n in files))

    template = TEMPLATE.read_text()
    scripts = {
        'apply': fill(template, 'apply', 'sector-orig.bin', 'sector-adb.bin', sums),
        'restore': fill(template, 'restore', 'sector-adb.bin', 'sector-orig.bin', sums),
    }
    scripts['check'] = check_variant(scripts['apply'])
    expected_writes = {'check': 0, 'apply': 1, 'restore': 1}
    for mode, script in scripts.items():
        if emmc_writes(script) != expected_writes[mode]:
            die(f'{mode}: unexpected number of eMMC write commands')
        folder = OUT / mode
        folder.mkdir(exist_ok=True)
        (folder / 'sector-write.cmd').write_text(script)
        if args.mkimage:
            subprocess.run([args.mkimage, '-q', '-A', 'arm', '-T', 'script', '-C', 'none',
                            '-n', f'a33 sector {mode}', '-d', str(folder / 'sector-write.cmd'),
                            str(folder / 'a33.scr')], check=True)
        print(f'{mode:8s} eMMC writes: {expected_writes[mode]}  -> {folder / "sector-write.cmd"}')
    print(f'sector-orig.bin {STOCK_SHA}')
    print(f'sector-adb.bin  {ADB_SHA}')


if __name__ == '__main__':
    main()
