# Four-client hosted acceptance

`check_family.py` drives four independently signed-in ordinary Auth sessions
through the actual `badge/homehq/transport.py` and its cooperative WebSocket
dependencies on CPython. Its default preserves the original four sessions for
one owner; `--member-files` verifies four separate accounts in one household.
Both modes subscribe to the household's private Broadcast channel. No admin key,
new user, household reset, photo upload, or saved browser/badge refresh token is
used. This check accepts only the explicitly authorized new DevRel Free Home HQ
project, `cicgysjddsjsbgofpxwr`, backed by the guarded private deployment metadata.

Run the original same-owner mode from the repository root while `g2` is idle:

```sh
python3 homehq/tools/check_family.py \
  --metadata homehq/.hosted.private.json \
  --project-ref cicgysjddsjsbgofpxwr \
  --owner-file homehq/.hosted.owner.private.json \
  --report /private/tmp/homehq-family-result.json
```

The metadata and ordinary owner credentials must be regular mode-0600 files.
`--homehq-root` can point the check at the canonical source tree when running
from a review worktree. The report contains only counts, revisions, source hash,
phase labels, and latencies; it contains no credentials or household contents.

For separate accounts, first create three ordinary email/password accounts and
link them through the owner's **Member logins** form. Map the owner to Wes and
the accounts to Claudia, Buzzsaw and Skidmark. Supply three private JSON files:

```json
{"project_ref":"cicgysjddsjsbgofpxwr","email":"MEMBER_EMAIL","password":"MEMBER_PASSWORD"}
```

An optional `url` must match this project and an optional `user_id` must match
the account returned by Auth. Keep each file mode 0600 and outside the starter
export. Add `--member-files /private/path/claudia.json /private/path/buzzsaw.json
/private/path/skidmark.json` to the command. The probe creates no new users or
membership: it signs into those already linked accounts with four fresh sessions.
It verifies four distinct Auth UUIDs resolve one home, edits through a member's
canonical badge transport, and checks the database's `completed_by_user_id` on
all four snapshots. Member mode creates a uniquely named temporary shopping row,
uses that fixture for every edit, and deletes only that owned row afterward.
Existing checklist values and completion attribution are not rewritten. A
different member performs the fixture undo.

The sequence joins all four clients and reads authoritative snapshots, saves
one versioned desired checkbox value through a client, and requires a private
Broadcast hint followed by a fresh native HTTPS snapshot on every client.
It restores the original value using the newly observed version, disconnects
client 4, saves another edit, and reconnects client 4 using its own session.
That client must read the durable missed edit after joining. Finally, the check
restores the original value and verifies all four native snapshots agree.

Four legitimate edits/restores advance the item's version and household revision;
the original desired value is restored. Member mode also advances revision for
fixture creation/deletion; cleanup verifies its creator and deletes only its
unique fixture. Default mode refuses to overwrite an unrelated concurrent item
edit. Both modes sign out only the four new sessions with local scope.
If cleanup reports failure, inspect the stable item before another run rather
than resetting the home or revoking saved device/browser sessions.

The 2026-10-12 hosted run passed using canonical transport SHA-256
`be5d70eaaf82ecb1d23ede712a7f2d8dc6ef1fee0087053c1531761bcdffee8a`.
All four clients joined in 836.9 ms, recorded zero transport errors, and read the
full sample: 4 people, 38 events, 33 chores, 24 shopping items, 20 photos,
5 agent cards and 5 sample devices. The first edit reached fresh snapshots in
269.2–325.8 ms from mutation start; Broadcast hint to snapshot was 129.6–177.0 ms.
Client 4 missed one hint while disconnected and joined/read the durable edit in
670.8 ms. The original desired value was restored and all four new sessions
signed out. These are measurements from one host/network run, not latency
guarantees on MicroPython hardware.

This proves four real hosted protocol clients can share one private household.
It does not prove four physical badges, their radio/flash/power behavior, or
separate device radio or button behavior. Physical family provisioning should use
an independent ordinary Auth session for each member's account. Members share
ordinary household editing permissions; account linking remains owner-only.
The measurements above are the earlier same-owner baseline, not a claim that
the new distinct-account mode ran on four physical badges.
