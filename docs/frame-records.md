# Private frame records

Each agent session starts with no memory of your frame. A private record per frame tells the next
session what was changed, where the backups are, and how to undo it. It is for **your** frame;
reusable hardware findings still go in public docs (see the
[README](../README.md#check-for-updates-and-send-back-what-you-find)).

Idea and format from [issue #47](https://github.com/wesbos/photo-frame-dashboard/issues/47).

## Where records live

`frames/` at the repository root is ignored by git, as a folder or as a symlink. One folder per
frame:

```text
frames/
  kitchen-frame/
    SETUP.md
    recovery.json
    changes.jsonl
```

Ignored files don't follow new worktrees or clones, and they disappear with a deleted workspace.
Keep the records somewhere durable and link them in:

```sh
mkdir -p ~/Documents/frame-records
ln -s ~/Documents/frame-records frames
```

Tell a new session where the records are if it can't see `frames/`.

## What goes in each file

**`SETUP.md`:** the current state, in plain words.

```markdown
# Kitchen frame

- Identity: About-screen model and firmware string, `ro.build.fingerprint`, eMMC size in sectors,
  boot image SHA-256. (Not the serial or MAC address; see Privacy.)
- Access: how to get ADB now (USB / network on port 5555 / T3c), and which computer's key works.
- Installed: launcher, WebView version, kiosk version and saved URL, boot fixes.
- Disabled: vendor packages.
- Known problems and outstanding work.
```

**`recovery.json`:** backups and undo, so nobody has to search for them.

```json
{
  "backups": [
    {"what": "full eMMC", "path": "~/Documents/frame-records/kitchen-frame/emmc-full.img.gz",
     "bytes": 15758000128, "sha256": "…", "verified": "2026-10-13, two reads + gzip readback"}
  ],
  "undo": [
    {"change": "Route U boot patch", "how": "restore-boot.scr, then emmc-macos.py verify-original"}
  ],
  "tools": {"u-boot": "v2025.10 + pf1007l-uboot.patch, sha256 …"}
}
```

**`changes.jsonl`:** one line per change, oldest first.

```json
{"date": "2026-10-13", "change": "disabled com.yhk.qeota", "approved_by": "owner", "verified": "package-restrictions.xml enabled=2 after reboot", "status": "confirmed"}
{"date": "2026-10-13", "change": "kiosk 1.1 installed", "verified": "owner saw the dashboard on the panel", "status": "confirmed"}
```

Mark each result as `confirmed` (read back from the device or seen by the owner), `assumed`,
`pending` or `failed`. Failed attempts are worth keeping.

## Rules for agents

1. At the start, find out which frame you're working on. Check the connected USB devices, and ask
   the owner if it isn't clear. Then read that frame's record.
2. **Re-check the frame's identity and current state** before you rely on the record. Records go
   stale.
3. **A past approval is not permission for a new write.** Every write still needs the owner's
   approval and a verified backup, as the [README's rules](../README.md#rules-we-learned-the-hard-way) say.
4. Write the undo into `recovery.json` before an approved change. Add a line to `changes.jsonl`
   after you verify it.
5. Keep reusable findings, cleaned of private data, in public docs. Keep this frame's setup here.

## Privacy

Ignoring a folder in git doesn't protect it. Don't put Wi-Fi passwords, tokens, private keys or the
private half of an ADB key in these files. Leave serials and MAC addresses out unless you need
them. Never copy a record into an issue or pull request without the owner reviewing it.
