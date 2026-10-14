# Four-client hosted acceptance

`check_family.py` drives four independently signed-in ordinary Auth sessions
through the app's `devices/badge/transport.py` and its cooperative WebSocket
dependencies on CPython. Its default preserves the original four sessions for
one owner; `--member-files` verifies four separate accounts in one household.
Both modes subscribe to the household's private Broadcast channel. No admin key,
new user, household reset, photo upload, or saved browser/badge refresh token is
used. The explicit project reference must match your protected metadata file;
see [hosted helper setup](../docs/homehq/hosted-tooling.md).

Run the same-owner mode from the repository root while no one is editing the household:

```sh
python3 tools/check_family.py \
  --metadata .hosted.private.json \
  --project-ref YOUR_PROJECT_REF \
  --owner-file .hosted.owner.private.json \
  --report /private/tmp/homehq-family-result.json
```

The metadata and ordinary owner credentials must be regular mode-0600 files.
`--homehq-root` can point the check at the repository root when running
from a review worktree. The report contains only counts, revisions, source hash,
phase labels, and latencies; it contains no credentials or household contents.

For separate accounts, first create three ordinary email/password accounts and
link them through the owner's **Member logins** form. Link the owner to one person and
the accounts to the other three household people. Supply three private JSON files:

```json
{"project_ref":"YOUR_PROJECT_REF","email":"MEMBER_EMAIL","password":"MEMBER_PASSWORD"}
```

An optional `url` must match this project and an optional `user_id` must match
the account returned by Auth. Keep each file mode 0600 and outside the public repository. Add `--member-files /private/path/claudia.json /private/path/buzzsaw.json
/private/path/skidmark.json` to the command. The probe creates no new users or
membership: it signs into those already linked accounts with four fresh sessions.
It verifies four distinct Auth UUIDs resolve one home, edits through a member's
badge transport, and checks the database's `completed_by_user_id` on
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

These checks exercise four real hosted protocol clients sharing one household.
They do not establish four physical badges' radio, flash, power or button
behavior. Each physical device should obtain an independent ordinary Auth
session by signing in. Members share household editing permissions; account
linking remains owner-only. Use the [local member check](MEMBER-CHECK.md) to
exercise the account and authorization flow without a hosted project.
