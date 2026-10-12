# Build the standalone badge app

From the repository root:

```sh
python3 homehq/tools/build.py
```

The builder exports `homehq/build/standalone/source/homehq/` and a bytecode-only
`homehq/build/standalone/mpy/homehq/`. Private provisioning files use a separate
`homehq/build/private/` directory, so rebuilding cannot overwrite an Auth session.
It copies canonical app/UI source, the repository's
generic `realtime` and `aiohttp` packages, its cooperative reconnect policy,
verified TLS support, public GTS
certificate roots, original sample artwork and the Mona Sans outline with its
OFL notice. The app adds its own root to `sys.path`; no conference networking
installation or fleet token is required.

The export uses an explicit file allowlist. Badge config, Auth sessions, cached
household data, Wi-Fi passwords and other files under `/state` are excluded.
`homehq/build/` is ignored build output. Edit canonical `.py` files and rebuild.

## Prerequisites and compatibility

Use the repository's existing pinned MicroPython toolchain at
`~/.cache/badge-playground/micropython/mpy-cross/build/mpy-cross`, or pass
`--toolchain /path/to/badge-playground`. It must come from Pimoroni MicroPython
commit `b29530abbd0550c8ab6963024aef36f3cd6cd278`, the `bw-1.28.0-3` pin used
with Badgeware v3.0.2. The builder checks that source commit and the emitted
format against `py/persistentcode.h`; it emits pure bytecode with 31-bit small
integers. Each module is compiled twice with a stable embedded filename and
must be byte-identical. `manifest.json` records the toolchain and every export
hash.

No compiler, firmware or runtime is installed or built by this command. Follow
the repository's existing toolchain setup if the pinned compiler is missing.
The firmware must provide Badgeware, picovector, asyncio, TLS and the native
fonts API. Firmware using a different `.mpy` format needs matching bytecode;
a successful source build does not establish arbitrary firmware compatibility.

For real bytecode imports and an offline Today frame in the pinned native
MicroPython WASM runtime:

```sh
python3 homehq/tools/build.py \
  --verify-runtime playground/public/runtime/micropython.mjs
```

The runtime requires matching `provenance.json` and byte-exact ROM fonts in the
existing pinned Tufty source. This check imports the bundled dependencies and
the compiled app entry, requires the local outline font, and decodes/displays a
deterministic opaque RGBA PNG above 256 KiB and below the 320 KiB photo limit.
The verifier also exercises the compiled GC-policy lifecycle: preserve a smaller
existing threshold and restore it on normal exit or an injected service-close
error. That test image is generated only in the verifier's memory filesystem and is
excluded from the export. The check proves interpreter/graphics loading, not physical
Wi-Fi, frame timing, battery life or RP2350 heap behavior.

## Verified development-device compatibility

The selected Tufty2350 runtime **bw-1.29.0-gc** (2026-09-22, `_mpy=7942`)
accepts this pinned pure-bytecode export. The original fifteen-module build imported all dependencies
and the actual installed app drew its seven HIRES pages and decoded a maximum
320 KiB PNG. No firmware flash/downgrade was needed. This observed tuple does
not make other firmware versions interchangeable. See the
[installed-app probe](tools/DEVICE-PROBE.md) and
[physical photo probe](tools/PHOTO-STORAGE-PROBE.md).

## Installing later

Use [the repository deployment procedure](https://github.com/meech-ward/select-badge/blob/main/docs/deploy.md) when an owner
authorizes a development badge installation. The compiled directory installs
at `/system/apps/homehq`. Replace that app's previous files: a `.py` beside a
matching `.mpy` wins silently in MicroPython. Keep the manifest for comparison.
The app-local font is a fallback for badges without the system Mona Sans face.

Set the badge RTC accurately before using certificate-verified HTTPS. For
online use, install project URL/publishable key and Wi-Fi configuration into
`/state`, then sign in on the badge with your own household account. Optional
laptop provisioning saves a separate refresh-only session. Never put populated
configuration or sessions in the shared export.
With no configuration, the complete offline demo opens immediately.

### App-only install from the public starter

The ZIP already contains verified bytecode at `badge/mpy/homehq`; rebuilding is
optional. Use compatible Badgeware firmware as described above. Install
`mpremote` on the computer (`python3 -m pip install mpremote`) for the separate
state/clock step. Only one serial controller should use a badge at a time.

With the selected badge connected, double-tap its rear RESET button to enter
**Badgeware Disk Mode**. Back up the entire mounted volume, including hidden
files. This is the `TUFTY`/`Tufty2350` disk, whose root maps to `/system`.
From the extracted starter, set its actual mount path and copy only this app:

```sh
export TUFTY_MOUNT=/Volumes/TUFTY
test -d "$TUFTY_MOUNT/apps" &&
test ! -e "$TUFTY_MOUNT/apps/homehq" &&
cp -R badge/mpy/homehq "$TUFTY_MOUNT/apps/homehq" &&
sync
```

For an update, back up and replace only the existing `apps/homehq` directory
first. Do not merge source `.py` files beside `.mpy`. Eject the volume cleanly,
then let the badge boot normally. Firmware and other app directories are not
part of this copy. Home HQ appears after the existing launcher tiles.

Prepare this badge's config without logging in on the computer:

```sh
python3 homehq/tools/configure.py --url https://PROJECT.supabase.co \
  --key-file /private/path/publishable-key.txt --wifi --no-login \
  --output-dir /private/path/this-badge-state
mpremote connect list
export TUFTY_PORT=/dev/cu.usbmodemREPLACE_WITH_SELECTED_BADGE
mpremote connect "$TUFTY_PORT" fs cp \
  /private/path/this-badge-state/homehq-config.json :/state/homehq-config.json reset
```

Select the Tufty's actual port/USB identity from the list, especially with other
boards connected. Disk Mode exposes `/system`, so copying config to the disk
does **not** populate `/state`. The serial step above copies only the config;
never copy another device's Auth session or household cache.

Set the RTC from the computer's accurate UTC clock before verified HTTPS.
The badge uses UTC for certificate checks and countdowns, even when the
computer's local timezone differs:

```sh
python3 - <<'PY'
import datetime, os, subprocess
now = datetime.datetime.now(datetime.timezone.utc)
rtc = (now.year, now.month, now.day, now.weekday(),
       now.hour, now.minute, now.second, 0)
code = "import machine; machine.RTC().datetime(" + repr(rtc) + ")"
subprocess.run(["mpremote", "connect", os.environ["TUFTY_PORT"],
                "exec", code, "reset"], check=True)
PY
```

Open Home HQ from the launcher. A configured badge with no saved session shows
the native email/password form. Enter the account linked in the owner's web
**Settings → Member logins**, then choose **Sign in**. Repeat the same app and
configuration steps for another badge; each person creates an independent
session by logging in on their own screen.

Pending checklist values are capped at 32 distinct items; a full queue refuses
another item visibly. If writable storage is full or read-only, the app keeps
its in-memory state and displays “Storage busy. Retrying.” while attempting a
checkpoint every three seconds. Closing the app makes one further best-effort
attempt. Values held only in memory cannot survive power loss until a local
checkpoint or server acknowledgement succeeds.
The companion can delete an item while its badge action is pending. An exact
SQL `PT404` removes that obsolete action, refreshes the snapshot, and lets later
items drain; ordinary endpoint errors keep pending actions. Successful snapshots
also discard actions for rows which no longer exist.

This builder changes no production roster, release version, existing app,
firmware or badge. Home HQ remains a deliberate development installation.

The current member-login development payload has20 modules and30 files. Its
compiled Auth/password/refresh/RPC/form APIs execute in the pinned runtime gate;
all installed bytes matched, with unrelated system hashes unchanged. On the
selected Tufty the [Auth acceptance](tools/AUTH-DEVICE-PROBE.md) also passes
actual login, renewal persistence, interpreter recovery and cross-account
Realtime/member completion. The earlier fifteen-module evidence remains history.
