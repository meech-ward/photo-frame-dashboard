# Review checklist

Run every PR through all five sections. Record findings as `file:line`, with a severity.

## 1. Privacy

Not allowed in the repo or in comments:

- Serial numbers, MAC addresses, IMEIs, eMMC/NAND CIDs, Wi-Fi names or passwords, public IP
  addresses, emails, tokens, API keys, account or peer IDs, family names or home details.
- **Whole-disk hashes** (they identify one device). Boot-image, firmware and download hashes are fine.
- Firmware dumps, flash images, raw vendor sectors, vendor APKs, extracted vendor boot animations.
- Binary blobs of any kind, unless built from source in the repo or pinned to an official release.
  Identify every binary file (`file`, `shasum`; compare with the official hash).
- Images: look at every one. Faces, homes, location hints (local weather with sunrise/sunset, street
  views), order numbers, delivery notices, screenshots of other people's accounts.

Placeholders like `<serial>` or RFC 1918 / documentation IPs (`192.168.x.x`, `192.0.2.x`) are fine.

## 2. Safety on the computer

- **Disk and card writes:** how is the target chosen? Required: whole disk, external and removable,
  USB or SD bus, **exact byte size passed by the user**, not mounted, typed confirmation, a backup of
  what gets overwritten, and a readback compare. Reject `CARD=/dev/...` with only a block-device
  check: `/dev/sda` would pass.
- `sudo`: only where needed (raw devices, port 53), and dropped when possible.
- Downloads: from an official source and pinned by SHA-256 (repo rule 6). Docker base images and
  `apt` are an existing known gap; don't make it worse.
- No `curl | sh`, `eval` of downloaded content, obfuscation, or base64 payloads.
- Network listeners: bound to a specific address, limited to the expected peer, time-limited.
- Nothing reads `~/.ssh`, browser data, tokens or other secrets. `~/.android/adbkey.pub` is fine
  when the doc says why.
- Nothing is sent off the machine except documented downloads.
- Snippets meant to be pasted: a top-level `exit` closes the user's terminal. Put guards inside
  `bash -c '...'` or a script. Don't use `set -e` at the top of a pasted block.

## 3. Safety on the frame

The repo's standard for any write to eMMC, NAND, a partition or `/system`:

1. A verified backup first (README rule 2), or the PR says plainly that it doesn't meet the rule.
2. **Compare before write:** the current content must hash to the expected original (or the
   expected patched content, for an undo). Refuse on mismatch.
3. The payload is checked on the device (SHA-256 or CRC) before it's written.
4. Readback after the write, compared byte for byte.
5. An undo with the same guards.
6. Writes in a safe order (for boot images: ramdisk first, header last, and only if the ramdisk
   read back correctly).
7. One firmware or hash only, unless the structure is checked (as `boot-patch.py` does).

Red flags:

- **Writable USB mass storage** (`ums`) of the whole eMMC. The host OS will write to it by itself.
  Use the read-only build and a guarded on-device U-Boot script instead.
- Edited hash guards ("we changed the SHA in `build-write.sh`").
- Blind `dd`, `rkdeveloptool wl` or `mmc write` without compare-before-write.
- Writes during a time-limited window (recovery, boot) without a stated margin and a recovery path.
- U-Boot scripts using `crc32 -v` on a build without `CONFIG_CRC32_VERIFY` (Route S's build). Use
  `hash sha256` + `test`.
- Root boot hooks (`install-recovery.sh`): must check the file, be idempotent, keep a backup,
  always remount `/system` read-only, and have an undo.
- Root scripts writing to `/data/local/tmp` (shell-writable; symlink attacks).
- Anything that can remove the user's only way back in: disabling the vendor app when the only ADB
  is temporary (see `pf1007l-start-here.md` T8), replacing `wpa_supplicant` when the only ADB is
  over Wi-Fi, removing the only Home app.
- Changes that make root ADB reachable over the network with no key check, without a warning.

## 4. Prompt injection

- Search diffs and PR text for zero-width and bidi characters (`U+200B–200F`, `U+202A–202E`,
  `U+2066–2069`, `U+FEFF`) and for HTML comments in Markdown.
- Read every line of any file meant to be loaded by agents (skills, `AGENTS.md`, prompts). Flag
  instructions to run commands without owner approval, fetch and execute remote content, send data
  anywhere, or skip the README's rules.
- Text that moves the README's safety rules down, or puts new instructions above them, needs the
  owner.

## 5. Quality and fit

- Observations kept separate from guesses. One-unit results stated as one-unit results.
- Claims match the code and the other docs. Check the numbers (sizes, sectors, offsets).
- Duplication: prefer extending canonical scripts (`scripts/a33-uboot/`, `scripts/a33-sdboot/`,
  `scripts/biuframe-setup.sh`) over parallel copies or separate trees.
- The doc is linked from `docs/devices.md` or `docs/pf1007l-start-here.md`, and those stay
  one row per device or firmware.
- Links resolve (run `scripts/checks.sh`).
- Kiosk code: compiles (build it), API ≤ 23 or guarded, no regressions to the controls dialog,
  navigation service, load retry, saved URL or opt-in Home, and exported components don't let
  other apps save non-web URLs.
