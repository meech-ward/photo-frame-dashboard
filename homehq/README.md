# Home HQ on a badge

Wes Bos's [photo-frame dashboard](https://github.com/wesbos/photo-frame-dashboard)
becomes seven native **320×240 MicroPython** pages. It keeps the cream palette,
family-coloured next-event card, original sample family, calendar, chores, shopping, photos,
sample home controls and agent meters. This is a separate personal demo; stable
badge release **1.0.3** and its six production launcher tiles are unchanged.

The [video](https://youtu.be/ZLycoUMltNI) describes an Android photo frame running a
web dashboard. This port runs actual badge code. The companion edits the same
household data through Supabase. The implementation uses the
[shared data contract](CONTRACT.md). The [reference audit](RESEARCH.md) records
the upstream source, full video transcript review and original social post.

For another agent, start with the [handoff and porting map](HANDOFF.md): current
source/output directories, customization routes, deployment and the seams for
another hardware target. Make changes directly in this public fork.
The [native ModRetro Chromatic port](chromatic/README.md) adapts these pages to
the ESP32/LVGL overlay; its installation and physical acceptance status are
tracked separately from the badges.

## Explore and build

Start the browser display and household editor with the [public quickstart](../HOMEHQ.md).
For the native app, follow the [Tufty build and install guide](BUILD.md).
[badge.select/guides](https://badge.select/guides) is the stable starting point
for SELECT firmware, setup and source downloads.

An unconfigured badge opens the sample household. Its clock starts at **3:18 PM**,
with Skidmark's piano lesson in 27 minutes. The landscape illustrations carry
**SAMPLE ART**; they are original artwork, not Wes's family photographs.
**SAMPLE**, **SAMPLE HOME** and **SAMPLE USAGE** mark weather, home readings and
agent meters. These providers are not connected.

The seven pages cycle in this order: **Today → Calendar → Chores → Shopping →
Photos → Home → Agents**. The footer icons line up with the physical A/B/C buttons: side chevrons change
pages, the centre icon opens/checks/undoes/plays, and detail screens use a back
arrow. Critical confirmations name the action and keys in the content.

| Control | Behavior |
| --- | --- |
| A / C | Previous / next page; inside details, A is BACK |
| UP / DOWN | Move focus between rows or browse photos |
| B | Use the centre icon: open, check/undo, play/pause or confirm |
| HOME | Return through the badge's normal launcher |

| Page | What to do |
| --- | --- |
| Today | See the whole family and next event; B opens that event |
| Calendar | Browse the next seven days; B opens the focused event |
| Chores | B opens a person or Anyone; B completes/undoes a chore; C opens the routine picker |
| Shopping | B checks the focused item; the undo icon restores it |
| Photos | UP/DOWN chooses a photo; B pauses/resumes the slideshow |
| Home | B opens a sample device; B changes its state; lock/garage changes require a second B/YES confirmation |
| Agents | B opens a usage card's detailed sample meters |

A linked member earns their own Anyone chores automatically. The unconfigured
preview and an unlinked owner ask who should receive the stars. Chores persist until undone; they do not
automatically reset each morning. Home actions save sample database state and do
not control physical appliances. Home HQ page actions need no long presses or
button chords.

Selection follows row IDs when data changes. Cached snapshots remain useful
offline. Desired-value commands carry versions, so a retry cannot toggle a
checkbox twice. Pending edits are bounded to 32 items and saved with the snapshot
to `/state/homehq-cache.json` after a short debounce. A missing/corrupt cache
falls back to the sample. A power cut before a checkpoint can lose recent unsaved
edits; physical filesystem/power-loss behavior still needs device validation.

The data flow is explicit in [service.py](badge/homehq/service.py): show the cache,
join private Realtime, refresh the authoritative snapshot, coalesce change hints,
send desired values, and overlay pending changes until acknowledgement.
[transport.py](badge/homehq/transport.py) retains the badge's cooperative HTTP,
verified TLS, WebSocket and Wi-Fi recovery implementation. Its Auth and RPC
interface matches the modern [meech-ward/supabase-micro](https://github.com/meech-ward/supabase-micro)
API at `aa30dc4e`; the public library is the interface reference, not the badge's
network engine. The browser uses normal supabase-js. For example:

```python
result = await client.auth.sign_in_with_password_async(email, password)
session = client.auth.get_session()["data"]["session"]
snapshot = await client.rpc("homehq_snapshot").execute_async()
await client.auth.sign_out_async(scope="local")
```

Only the APIs used by Home HQ are implemented in this badge adapter.
Failed Wi-Fi attempts and loss of an established radio connection show
`Waiting for connection` once per attempt. Initial joining remains `Connecting`.
Recovery releases a failed socket and rejoins; each successful join/rejoin
refreshes the authoritative snapshot.
Snapshot responses are capped at 32 KiB. Two downloaded photo slots each accept
up to 320 KiB. On the Tufty's 1 MiB state volume, replacement retains the old
slot until HTTP and image validation succeed, then frees only that slot before
writing its temporary file. Complete write and rename precede cache publication;
failed writes clean up the temporary file and retry with bundled artwork visible.
Peak photo storage is 640 KiB, leaving room for Auth, cached data and existing
state. New uploaded photos use smaller baseline JPEGs on the Tufty; the same
upload retains a normalized PNG for the Chromatic and older clients. Existing
PNG-only rows and cache metadata remain supported. A quota simulation covers full-size replacement and failure recovery;
the physical Tufty acceptance probe also proves capped replacement, real partial
flash cleanup/retry and native PNG decode. Its measured minimum free space was
216 KiB with 103 KiB of other state. See [the photo probe](tools/PHOTO-STORAGE-PROBE.md).

The photo renderer retries failed decodes on the next draw and tracks Storage
content separately from the two reusable filenames, preventing stale decoded
pixels after slot replacement. The host tests cover replacement and decode
retries; the [photo probe](tools/PHOTO-STORAGE-PROBE.md) describes physical checks.

## Personal Supabase backend

For your own badge, create a fresh **Free Supabase project** in your account and
follow the [backend deployment steps](backend-README.md#deploy-to-your-own-supabase-project)
to apply configuration, migrations and the private photo bucket. Connect the
companion below, create/sign into an ordinary owner account, then provision a
member login for each person in the household. Every device signs in separately to get its own session.

For optional development on your computer, from the repository root:

```sh
python3 homehq/tools/local.py start
python3 homehq/tools/local.py reset
python3 homehq/tools/local.py test
python3 homehq/tools/check_live.py
```

The checksum-verified project-local CLI is pinned to **2.120.0**. SELECT 2026's
experimental native runtime runs Auth, REST, Realtime, Storage and Postgres
without Docker on supported machines. `reset` recreates only this disposable
local database; omit it when keeping your local household edits. Local metadata
is saved privately, without printing its secret keys.

Auth owners initialize their home with `homehq_seed_demo()`. Linked accounts
resolve the same home, without making another copy of the sample. Private
Broadcast carries an invalidation hint; clients fetch durable rows again.
Household membership RLS protects tables, channels and private photo folders. No service-role
key belongs on a badge or in the editor. For setup, declarative migrations,
hosted target checks and the precise permissions, read the
[backend guide](backend-README.md). The configuration lives in
`supabase/config.toml`, authored SQL in `supabase/schemas/`, and CLI-generated
migrations in `supabase/migrations/`.

`python3 homehq/tools/sync_demo.py --check` proves the authored fixture matches
the native, SQL and companion projections. Run without `--check` after changing
the sample, then generate/apply a declarative migration. Applied migration files
stay in Git.

## Companion editor

```sh
npm --prefix homehq/web ci
python3 homehq/tools/companion.py
```

Open `http://127.0.0.1:5173`. The command above configures this checkout's local
Supabase backend; for your hosted project, run:

```sh
python3 homehq/tools/companion.py --url https://PROJECT.supabase.co --key-file /absolute/path/publishable-key.txt
```

The key file contains only the project's publishable/legacy anon key. The helper
writes its URL and public key to an ignored environment file and binds the editor
to your computer. It does not publish a website.

Once a project is configured, the editor always uses Supabase. A restored Auth
session connects automatically after opening or reloading the page; no demo/live
selection is needed. If signed out, **Create account** or **Sign in** in Settings
with your own household member account; complete email confirmation if required. First
sign-in seeds the sample without replacing an existing home. The header says
**Live sync** once connected, and edits and uploaded photos sync to the badge.

A missing or rejected session asks you to sign in instead of opening a local demo.
Ordinary access-token expiry refreshes automatically while the session remains valid.
While reconnecting, the editor retains its last live data and disables changes.
Edits require a signed-in session, a loaded household and a connected channel;
each join also refreshes the authoritative snapshot. **Sign out** ends only this
browser's session; independently provisioned badge sessions stay signed in. Live
clock, date and greeting use the home's timezone. An unconfigured public preview
still offers the editable offline example; its changes stay in that browser.

Use Node 22.12+ and the committed lockfile. The [companion guide](web/README.md) covers testing,
private photo preparation and hosting. The native code and editor share one
fixture and one versioned snapshot contract.

## Four badges, four logins, one family

In the companion's **Settings → Member logins**, the household owner selects a
person and their email. Enter a password to create a new ordinary Auth account,
or leave it blank to link an existing account. Link the owner's own email to their
person too. Account creation keeps the owner signed in and does not retain the
member's password. Confirm the new email if your project requires it.

Install the same compiled app and project URL/publishable key on each badge.
Each person enters their own email/password using the badge keyboard. Passwords
are masked and never written to flash. A local logout ends only that device's
session; other family badges and browsers remain connected.

The badge retains only a rotating **refresh token and user ID** in
`/state/homehq-session.json`. An access JWT stays in memory and is renewed at
startup and before expiry. Refresh tokens grant account access: this private
file is appropriate for this personal demo, but it is not encrypted storage.
Do not share device state, backups or passwords. On a revoked session, the badge
returns to sign-in. Changing accounts clears the previous account's cached
household, downloaded photos and pending commands before loading the new home.
Sign-out asks you to sync pending edits first.

Today shows the whole family. Chores starts on the authenticated member, whose
mapping comes from Supabase rather than a local preference. Any member can help
with a family task. `person_id` records its assignment, while SQL stamps
`created_by_user_id` and `completed_by_user_id` from the real Auth identity,
including shopping items. Retried completion preserves the original actor;
undo clears completion attribution. No device JWT minting or service-role key
is involved.

The [member acceptance check](tools/MEMBER-CHECK.md) exercises four different
Auth accounts sharing one household, Realtime fanout, durable reconnect and
attribution. Four physical-board radio/power behavior still needs four boards.

## Badge export and provisioning

```sh
python3 homehq/tools/build.py --toolchain "$HOMEHQ_TOOLCHAIN"
python3 homehq/tools/export.py
```

The [build guide](BUILD.md) covers pinned compiler prerequisites and firmware
compatibility. Source +compiled app output is under `homehq/build/standalone`.
The public starter ZIP includes infrastructure, editor, native source, its
minimal generic dependencies and reproducibly compiled app. The build manifest
records whether optional runtime verification ran. Private local files
are excluded through explicit allowlists.

Configure URL/public key and Wi-Fi for on-badge sign-in:

```sh
python3 homehq/tools/configure.py --url https://PROJECT.supabase.co --key-file PATH --wifi --no-login
```

This writes configuration only; sign in on the badge after installing it.
For optional laptop provisioning, omit `--no-login` and pass `--email MEMBER_EMAIL`.
Its password is prompted and never saved. Each run creates an independent
session. Provisioning writes only ignored mode0600 files under
`homehq/build/private/state`. Local HTTP is for host tests; use your
hosted HTTPS project on a physical badge. Follow the [build/install guide](BUILD.md)
to install the compiled app and copy those private files to `/state`, with an
accurate RTC for certificate verification. Without configuration, the offline
sample opens immediately.
Never copy the browser's rotating refresh token to a badge. Revoke its Auth
session to remove access, and remove the private files before sharing the badge.

Badge Auth sessions, optional Wi-Fi credentials, household cache and downloaded
photos live under `/state`; treat those files as private. The public starter
excludes them. Unconfigured preview edits stay in local storage, while live household
rows and prepared 320×240 photos stay in your household-scoped Supabase project.

## Verify

From the repository root:

```sh
python3 -m unittest discover -s homehq/tests
python3 homehq/tools/sync_demo.py --check
node homehq/web/tools/check-upstream.mjs
npm --prefix homehq/web run typecheck
npm --prefix homehq/web test
npm --prefix homehq/web run build
```

These checks need no connected badge or hosted household. The
[web guide](web/README.md#verification) covers browser tests, and the
[backend guide](backend-README.md) covers an isolated local Supabase stack.

### Optional native framebuffer checks

The renderer requires a separately supplied compatible MicroPython/picovector
WASM runtime and matching Tufty ROM fonts. Those simulator artifacts are not
included in this repository or required for the normal build. See
[build prerequisites](BUILD.md#optional-native-runtime-check).

After building, install Pillow and pass both asset paths explicitly:

```sh
node homehq/tools/render_native.mjs homehq/build/standalone/mpy/homehq \
  /tmp/homehq-frames /absolute/path/micropython.mjs /absolute/path/rom/fonts
python3 homehq/tools/check_native_frames.py /tmp/homehq-frames
```

This checks 41 page/detail/member/login states and nine countdowns (0–10080
minutes) against unrestricted native font pixels to catch clipping and collisions.
Add `--countdown-only` for a focused render. Virtual pixels do not establish
physical button, radio, battery or optical behavior.

### Hardware acceptance

Development Tuftys have been tested for compiled app loading, all seven pages,
email/password sign-in, saved-session recovery, cross-account Realtime updates,
and JPEG/PNG rendering and cached-photo recovery. The
[installed-app](tools/DEVICE-PROBE.md), [Auth](tools/AUTH-DEVICE-PROBE.md) and
[photo storage](tools/PHOTO-STORAGE-PROBE.md) guides describe the probes and their
scope. A successful install is not itself an acceptance test.

Four distinct Auth clients have passed household fanout and reconnect checks
using the native transport on a computer; this does not establish four physical
badges' simultaneous radio behavior. Battery endurance, abrupt physical power
loss, extended soak and complete physical-switch coverage remain unmeasured.
Firmware compatibility is limited to the tuple documented in [BUILD.md](BUILD.md).
