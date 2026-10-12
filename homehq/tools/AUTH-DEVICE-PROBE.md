# Installed native email/password Auth acceptance

`auth_device_probe.py` is a bounded acceptance script for installed compiled
Home HQ. Only the root serial controller runs it, after verifying the app's
manifest and privately backing up the existing Home HQ state. It gates exact
Tufty UID `6d9430717fc47ddf`, excludes Pico `e7e7d70437b93611`, requires firmware
`_mpy=7942`, refuses source shadows and requires the complete 20-module bytecode
payload. It launches the actual entry through `badgeware.launch`, feeds the
existing 16-second watchdog and suppresses physical input during the probe.
It does not discover USB, deploy files, change radio settings or print secrets.

Supply `HOMEHQ_AUTH_PROBE_OPTIONS` in the same fresh raw interpreter before
executing the source. The host controller must transmit these values privately
under the existing serial lock; do not put an email/password into a shell
argument, command history or a public log.

| Option | Value |
| --- | --- |
| `mode` | `switch` (default) or `restore` |
| `expected_user_id` | Exact ordinary Supabase Auth user ID after sign-in |
| `expected_home_id` | Exact shared household UUID, independent of the user ID |
| `expected_person_id` | Mapped household person ID, or `None` for an unmapped owner |
| `email`, `password` | Required privately for `switch`; absent for `restore` |
| `timeout_ms` | Per-phase cap, default 45,000; maximum 60,000 |
| `capture` | `none` (default) or `stream` |
| `sync_item_id` | Optional `restore`-only ID of the host-owned disposable shopping fixture |

The switch phase first restores the starting legacy/current saved session and
requires a fresh joined snapshot from the expected household. It checks the
migrated refresh-only file, then refuses an existing pending outbox. It logs
out with the real Service's local scope, requires a rendered blank login screen
and cleared cache/photo/outbox/decoded-image state, submits the credentials via
actual `SignIn.press('B', service)` with focus 2, and requires the new member's
Auth identity, household and verified Chores focus. A forced ordinary refresh
must rotate the token and save the refresh-only record before completion.
The password and email fields clear immediately after accepted submission.

Then run a **second fresh REPL** with `mode='restore'` and the same expected
identity/home/person values, without credentials. This separately proves the
saved renewal session recovers the member and household after app/interpreter
restart. It is not a cold power-on or radio-recovery benchmark. Each run closes
and checkpoints the owned app state; the root controller resumes normal Home HQ
interaction separately afterward.

For one focused cross-account proof, the root controller may create an unchecked
shopping fixture as this demonstration's owner (`created_by` equals its existing
household/owner UUID) and pass `sync_item_id` in restore mode. Wait for the safe
`peer_sync_ready` phase before the owner checks that fixture through the normal
API. The probe requires a Realtime `changed` hint and the authoritative checked
row within 25 seconds, shorter than the 60-second fallback refresh. It then uses
actual native Shopping B to undo and complete the fixture, requires an empty
outbox after each acknowledgement, and verifies the completion actor is the
signed-in member. The host owns creation/deletion and must remove the disposable
fixture afterward, including after a failed probe. Existing shopping items are
untouched; the probe never creates a fixture or prints its ID or row content.

`HOMEHQ_AUTH_PROBE` lines contain authored phase names, booleans, counts and
bounded frame/elapsed timings. Expected IDs, session tokens, credentials, raw
provider errors and household rows never enter those records. On failure,
inspect the last safe phase record and recover from the private backup/new
ordinary sign-in as appropriate; do not blindly restore a rotated old token.
A failed switch can leave the badge locally signed out. Shared project/Wi-Fi
configuration and all other apps' files remain intact.

With `capture='stream'`, the existing `HOMEHQ_RGBA_BEGIN`/`DATA`/`END` format emits
three 320×240 RGBA framebuffers: `auth_signed_out`, `auth_member_chores` and
`auth_member_today`. Frames contain household display data; keep their host log
private until reviewed. Capture uses a memoryview and stores no large probe file
on the badge. These are native framebuffer/model-input checks, not optical
photographs, physical-switch checks or multi-board performance evidence.
