# Installed Home HQ acceptance probe

## JPEG photos on an explicitly selected Tufty

`jpeg_device_probe.py` checks the installed compiled app with existing household
photos. It requires an explicit matching device UID, a Tufty2350 runtime with
`_mpy=7942`, and never installs files, switches accounts or writes cloud data.
First verify the installed app hashes and select the actual USB identity. Set
`TUFTY_PORT` and `TUFTY_UID` from your connected device, then run:

```sh
mpremote connect "$TUFTY_PORT" \
  exec "HOMEHQ_PROBE_TARGET='$TUFTY_UID'; HOMEHQ_JPEG_PROBE_OPTIONS={'uid':'$TUFTY_UID','timeout_ms':45000}" \
  run tools/jpeg_device_probe.py
```

It waits for Live, preserves the existing identity, and requires an empty outbox.
Two existing `jpeg_path` rows must render through the actual app with native
320×240 decode, matching content hashes and `.img` cache files. Uncached photos
require exactly one download each. Checkpoint reconstruction must return the
same local file without another HTTP request. Output contains measurements and
booleans, never photo paths, captions or credentials. Hardware switches and
optical appearance are not checked.

After a host-requested hard reset and USB re-enumeration, set
`require_cached=True` and `offline_cache=True` in the options, retaining your
explicit target and matching `uid`. This suppresses network polling during the bounded check, so a successful HTTP
retry cannot hide a missing persisted JPEG. Both photos must render from their
saved files with zero downloads. Restore the normal interactive app afterward;
these probes return to REPL and do not leave its event loop running.

## General page and networking probe

`device_probe.py` opens **installed compiled** `/system/apps/homehq` through
`badgeware.launch`. It requires a caller-supplied `HOMEHQ_PROBE_TARGET` matching
the detected UID and a Tufty2350 runtime with `_mpy=7942`. It refuses missing or
mismatched targets, other board models, source shadows and an incomplete
20-module export (including native Auth and keyboard). It never discovers a USB device, installs files or prints
credentials, household content or raw transport errors. Use the explicitly
selected Tufty port after backup and installation have been verified.

From the repository root, with `TUFTY_PORT` and `TUFTY_UID` set to that device:

```sh
mpremote connect "$TUFTY_PORT" exec "HOMEHQ_PROBE_TARGET='$TUFTY_UID'" run tools/device_probe.py
```

The default run prevents network polling. It measures the first useful Today
present, imports all compiled dependencies, times three dirty updates and
display presentations per page, and walks A/C, UP/DOWN, B and detail BACK through
the real model. Shopping B previews its command and rolls it back without an RPC.
It closes the service and verifies only its owned Home HQ cache checkpoint.
The existing 16-second boot watchdog is fed throughout the bounded replacement
loop. Entry mode, clear behavior, run/badge bindings, imports and paths are
restored. Keep physical buttons untouched during the probe, including HOME.

Each `HOMEHQ_PROBE` line is JSON. Timing targets are **review thresholds**, not
prior hardware measurements: useful first present within 1,000 ms, dirty update
within 100 ms, and at least 512 KiB free heap. The summary's `ok` means the
behavioral gates passed; inspect the separate target booleans for performance.
The bytecode inventory warms the filesystem before launch, so this is not a
cold-boot benchmark. Online `update_us` includes service work. Repeating dirty
frames forces drawing; an idle dashboard normally retains its last frame.

## Physical framebuffer capture

Capture one page to the owned 307,200-byte `/state/homehq-probe.rgba` file:

```sh
mpremote connect "$TUFTY_PORT" exec "HOMEHQ_PROBE_TARGET='$TUFTY_UID'; HOMEHQ_PROBE_OPTIONS={'capture':'file','page':'photos'}" run tools/device_probe.py
mpremote connect "$TUFTY_PORT" fs cp :/state/homehq-probe.rgba /private/tmp/homehq-photos.rgba
mpremote connect "$TUFTY_PORT" fs rm :/state/homehq-probe.rgba
```

Repeat with `today`, `calendar`, `chores`, `shopping`, `photos`, `home`, `agents`
for a contact sheet. Only one capture is retained because seven raw images
would exceed `/state`. Capture happens after `display.update()` and before the
next clear, using the real framebuffer without a second full-size allocation.
Convert the host file with Pillow:

```python
from pathlib import Path
from PIL import Image
raw = Path('/private/tmp/homehq-photos.rgba').read_bytes()
assert len(raw) == 320 * 240 * 4
Image.frombytes('RGBA', (320, 240), raw).convert('RGB').save('/private/tmp/homehq-photos.png')
```

Bytes are RGBA, top-left row-major; no channel swap or rotation is needed.
RGB conversion matches the panel, which ignores alpha. A `capture='stream'`
option streams all seven base64 buffers between `HOMEHQ_RGBA_BEGIN`/`DATA`/`END`
markers instead; redirect its larger output to a private host log. Captures can
contain household data and must be reviewed before sharing.

## Configured Supabase acceptance

After verifying Wi-Fi, RTC, project provisioning and the device session:

```sh
mpremote connect "$TUFTY_PORT" exec "HOMEHQ_PROBE_TARGET='$TUFTY_UID'; HOMEHQ_PROBE_OPTIONS={'online':True,'timeout_ms':30000}" run tools/device_probe.py
```

This requires a Realtime joined state plus a freshly requested authoritative
snapshot. Each wait is capped at 30 seconds (configurable up to 60 seconds).
This does not change Wi-Fi or configure a project.

Add `await_change=True` to observe a companion edit made during its 30-second
window. The probe requires a newer authoritative revision before the normal
60-second fallback refresh can fire, exercising Realtime hint -> snapshot.
The outbox must be empty for this observation. Restore the companion edit after
the run if it was only a test.

For an explicitly authorized sample-project write, add `roundtrip=True`. With
an empty outbox it uses Shopping B to toggle the selected item, waits for an
authoritative versioned acknowledgement, and restores its original done value
with another acknowledged command. A failed/interrupting roundtrip can leave
the value changed or a desired value queued; inspect the companion and owned
outbox before rerunning. Do not use this option on an unrelated live household.

This probe exercises model button semantics and the actual pixels sent to the
display. It does not prove physical switch debounce, text readability on glass,
long-run memory stability or battery life. A native framebuffer capture is not
an optical photograph of the display.


## Quiet socket and recovery options

`idle_ms=65000` proves at least two Phoenix heartbeat rounds on the same
response/socket, with no new connection or disconnect; it records collected
heap separately from the conservative uncollected minimum. `radio_recovery=True`
holds only the selected badge's radio off briefly, observes Offline, then requires
a newer joined snapshot after automatic reconnection. `auth_refresh=True` forces
a new ordinary refresh and checks the rotated token is durable before readiness.
`expected_cache_revision=N` verifies the first cached revision after reboot.
These options require a configured disposable Home HQ household, not fleet data.

`await_change=True` emits a safe `HOMEHQ_PROBE_SIGNAL` at its observation window.
`hold_after_toggle_ms=15000` emits another signal after the native desired-value
acknowledgement, allowing a companion observer to see it before restoration.
Signals contain only phase names, never IDs, credentials or household text.

For an owner-prepared disposable content-addressed PNG, `private_photo_path`
and `private_photo_sha256` require exact 327,680-byte download/hash and native
320×240 decoder/pixel proof. The fixture uses a solid RGB test image with legal
ancillary padding; its descriptor/object must be restored/removed by the host
controller afterward. Those options do not upload or delete cloud data. Always
use the schema's `<owner>/<sha256>.png` path: arbitrary filenames are correctly
rejected by the normal Storage policy.

The disposable photo option suppresses incidental photo requests during the
baseline page walk, then counts real download starts after the fresh snapshot.
Exactly one start is required, including the subsequent forced Auth refresh.
Use a newly hashed fixture each time; an already cached URI cannot prove a
network transfer. The record includes the longest individual update separately
from total download time, so cooperative background latency is not reported as
a continuous input stall.
