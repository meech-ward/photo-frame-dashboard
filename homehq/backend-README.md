# Home HQ personal Supabase starter

This project is independent of BadgeLink and the conference fleet. It implements
the [Home HQ contract](CONTRACT.md) for a personal Supabase Auth owner: a durable
agenda, chore and shopping lists, sample home controls, photo metadata and visibly
labelled weather/agent samples. It does not change the badge's stable `1.0.3`
release, roster or existing cloud project.

Each owner creates one home. Ordinary member accounts join that home through
owner-authorized `homehq_link_member(email,person_id)`; they have shared household
data permissions and independent Auth sessions. Settings can create a member
account without switching the owner. No privileged runtime key is required.
The mapping is one home/person per account for this small demo.

## Source and offline sample

[Wes Bos's photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard)
is the reference. `fixtures/demo.json` projects its `dashboard/js/data.js` mock
data onto this contract, with an anchor of 2026-10-11 at 15:18 in Toronto. It keeps
all four people and their colours, 38 events overlapping the next seven days,
33 chores, 24 shopping items, 20 photo descriptors and all five agent cards.
The 85-day background calendar is omitted because the badge only needs a week.

`homehq_seed_demo()` moves event wall times to the owner's current local date;
it uses IANA timezone rules when converting to UTC so a daylight-saving change
does not shift a piano lesson. Ordinary initialization preserves existing data.
`homehq_seed_demo(true)` explicitly replaces the owner's sample rows and carries
item/device versions forward, so queued commands from before reset remain stale. Chores
are a persistent demo checklist: they do not silently reset or recur at midnight.
Progress and stars can be derived from completed rows instead of retry-sensitive
increment operations.

Five interactive devices are curated from the reference's home controls: kitchen,
living-room and porch lights, a garage door and a front-door lock. Their mutations
change sample database state; they are not connected to physical appliances.
The home summary derives light counts and lock state from those rows. Photo
descriptors use the bundled `assets/photo-coast.png` illustration until a user
uploads a photo; the artwork is illustrative, not a photograph of the sample family.

## Reproducible local setup

Use the repository's pinned Supabase CLI **2.120.0**. The SELECT-era experimental
stack needs 2.119.0 or later and is opted in here with `stack = true`.
No ports are fixed in `config.toml`: each checkout/branch gets its own local stack.
On Apple silicon with macOS 14+, or supported Linux, the native runtime needs
`tar`, initial download access and writable CLI storage, but no Docker daemon.
Docker is another supported runtime. See [native runtime requirements](https://supabase.com/docs/guides/local-development/docker-and-native-runtimes).

From this directory (`homehq/`), using the pinned CLI:

```sh
supabase --version
supabase stack --help
supabase start --runtime native --eager
supabase db reset --local
supabase test db supabase/tests/homehq.test.sql
python3 tools/check_live.py
```

`--eager` keeps Auth, REST, Realtime and Storage running during integration tests.
The local seed creates the private photos bucket. It does not create a public
password or reusable session: sign up through the companion, then call
`homehq_seed_demo()` as the signed-in owner. The local email-confirmation setting
lets a developer try that flow without an external SMTP provider.

`supabase status` returns this stack's endpoints and keys. The browser needs only
its API URL and publishable key. CLI status also contains privileged local keys;
do not paste the whole status output into a public config, screenshot or badge.
The local development services stay on the development machine; a physical
badge's TLS/network proof uses the separately deployed hosted project.

## Declarative changes

`supabase/schemas/*.sql` is the authored source. Migrations are generated artifacts
that stay in Git once they have been applied or shared. `pg-delta` orders SQL
dependencies, so there is no legacy `schema_paths` list to maintain.

```sh
supabase db schema declarative sync --help
supabase db schema declarative sync --name descriptive_change --no-apply --strict-coverage
supabase migration up --local
supabase test db supabase/tests/homehq.test.sql
```

Review the generated SQL before applying it. `sync` compares declared files with
migration history, rather than reading local Studio edits. With `pg-delta`,
`db diff` compares the live database with migrations and does not use the schema
files. See [Declarative Schemas 2.0](https://supabase.com/docs/guides/local-development/declarative-database-schemas).
Generate migrations with the CLI; do not invent timestamps or hand-author the
same change in both the schema and a guessed migration filename.

## Deploy to your own Supabase project

Create a fresh project in your account, then work from this directory. Confirm
the CLI's resolved target before pushing; use a project dedicated to Home HQ.

```sh
supabase login
supabase link --project-ref YOUR_HOMEHQ_PROJECT_REF
supabase config diff
supabase config push
supabase db push --include-seed --dry-run
supabase db push --include-seed
```

Use the companion's hosted origin for `auth.site_url` and redirect URLs when
deploying the companion publicly. Decide whether its signup page needs email
confirmation and configure SMTP if required. A fresh owner account initializes
its own sample data through the authenticated RPC. `config pull` imports hosted
setting changes; review that diff before committing it.

The bucket's privacy, file-size and MIME settings are declared in `config.toml`;
its owner-folder policies are in the schema. The browser crops JPEG, PNG and
WebP uploads to 320×240, producing a baseline JPEG at quality 0.85 and a
normalized non-interlaced PNG. Each output uses its own SHA-256 address:
`<owner UUID>/<hash>.jpg` in `jpeg_path`, and `<owner UUID>/<hash>.png` in `path`.
The Tufty prefers JPEG, while the Chromatic and older badges retain PNG support.
Both private objects are uploaded before updating `homehq_photos`. Uploaded objects are
separate from SQL migrations: metadata alone does not transfer image bytes to
another project. Authenticated Storage download avoids expiring signed URLs in
persistent badge snapshots. No `service_role`, secret API key or database
password is used by the browser or badge.

## Tables and client calls

All household tables use the existing `owner_id` as their stable home UUID,
ordinary foreign keys and membership RLS. `homehq_members` resolves the signed-in
account to that home; members cannot grant themselves membership or link accounts. Explicit grants
make the Data API work on projects that do not auto-expose new objects.
The schema first revokes existing authenticated table privileges, then grants
the required operations. This removes Supabase's default ALL grants: `TRUNCATE`
cannot bypass RLS, and home `revision`, `updated_at` and owner reassignment remain
unavailable to direct client writes. Tests verify actual privileges and rejected
operations after rebuilding the database from migrations.

| Table | Editable fields / purpose |
| --- | --- |
| `homehq_members` | owner-authorized Auth user → household person mapping |
| `homehq_homes` | `title`, `timezone`, `demo`; server owns `revision` |
| `homehq_people` | `id`, `name`, `color`, `home`, `status`, `eta`, `sort_order` |
| `homehq_events` | `id`, `starts_at`, `ends_at`, `title`, `travel`, `loc`, `notes`, `all_day` |
| `homehq_event_people` | composite event/person relation; use event-save RPC for replacement |
| `homehq_checklist` | `kind`, `id`, `title`, `person_id`, `routine`, `stars`, `category`, `store`, `quantity`, `note`, `sort_order` |
| `homehq_devices` | light/lock/garage state with server-owned `version`; all controls are samples |
| `homehq_cards` | bounded `data` JSON for `weather`, `home_status`, `agents` |
| `homehq_photos` | `id`, `path`, optional `jpeg_path`, `asset`, `caption`, `place`, `sort_order` |

Checklist `kind` is `chore` or `shopping`; `person_id = NULL` means a chore is for
anyone. Assigned chores require that person's `done_by`; an any-person chore
requires a chosen household person when completing it. Shopping completion has
server-stamped Auth attribution too. SQL owns `created_by_user_id` and
`completed_by_user_id`; clients cannot spoof them. Snapshot keys map `person_id` to `who`, `title` to shopping
`name`, and `starts_at`/`ends_at` to Unix-second `start`/`end`.
Events also carry optional `start_offset_minutes` and `end_offset_minutes` from
their own timestamps in the home's IANA timezone. A week crossing daylight-saving
time uses each event's offset instead of applying today's offset to the whole week.

The companion uses normal Supabase JS calls:

```js
const { data } = await supabase.rpc('homehq_snapshot')
await supabase.rpc('homehq_set_done', {
  p_kind: 'shopping', p_id: 'g1', p_done: true, p_version: 1,
})
await supabase.rpc('homehq_set_device', {
  p_id: 'kitchen-light', p_state: { on: false }, p_version: 1,
})
```

Both mutation RPCs return `{status: 'saved' | 'conflict', item, revision}`.
They take desired values rather than toggles. Under a row lock, matching state
is successful without another version increment; stale contradictory state
returns a conflict. The caller renders the authoritative returned item and
refetches the snapshot. SQL tests cover serial interleavings of competing
versions; simultaneous request tests must also exercise the real HTTP path.

`homehq_save_event(p_id, p_title, p_start, p_end, p_people, p_loc, p_notes,
p_travel, p_all_day)` validates owner-local people and saves both event and
attendee rows in one transaction. It returns the canonical event. Other metadata
can be edited through normal owner-scoped table calls; version/revision columns
are not client-authored.

## Realtime and correctness

Resolve the household from `homehq_snapshot().home.id`, then subscribe to
`homehq:<home.id>` with `private: true`, receive the `changed` event, and fetch
the snapshot. Separate member Auth UUIDs share this household channel. Join/rejoin and each invalidation
schedule a snapshot; several hints coalesce. Use a periodic fallback refresh and
save successful snapshots locally so reconnects do not blank the badge.

The database trigger sends only `{section, revision}` with `realtime.send`'s
private flag enabled. It lives in a non-exposed schema, has no client execute
permission; its definer access updates a server-owned revision and publishes a
notification after an RLS-authorized row change. The two narrow private
membership functions also use definer access to resolve `auth.uid()` without
policy recursion and to link an account after checking household ownership.
Exposed RPCs are all security invokers. Clients have a private-topic SELECT policy and no
Broadcast INSERT policy. No Realtime managed tables, functions or grants are
altered. See [private Realtime authorization](https://supabase.com/docs/guides/realtime/authorization).

Notifications are not the durable record. Missing one or losing a socket cannot
lose a completed chore; reconnection reads the tables again. The snapshot returns
at most eight people, 64 events in seven local calendar days, 64 chores, 64
shopping items, 16 devices and 20 photos. It refuses excess rows and any response
larger than 32 KiB instead of silently truncating the home. Text/JSON fields have
independent constraints so malformed data cannot grow without bound.

## Evidence boundary

`supabase/tests/homehq.test.sql` proves owner/cross-owner/anonymous RLS,
anonymous RPC denial, sample counts and snapshot bounds, checklist/device replay
and version conflicts, chore attribution, atomic calendar failure preservation,
private message-store policies and Storage owner folders, all in a rolled-back
database transaction. Running that SQL does **not** prove Auth sign-in, REST RPC
delivery, an authorized WebSocket join or a delivered Broadcast.

`tools/check_live.py` runs those real local HTTP/WebSocket checks using fresh
ordinary Auth owners and the actual badge transport on CPython. It also races
two HTTP mutations, verifies Storage access denials, downloads both a private
sample and a valid PNG larger than 256 KiB, and checks session refresh rotation.
It drives the actual native service through an item deleted by the companion
while another action remains queued, then verifies the next action is saved.
Generated credentials stay in memory; the
private CLI metadata is read silently. The probe removes only its own home rows
and uploaded object, then signs its sessions out. Its random local Auth accounts
remain until the dev stack is destroyed because the probe uses no admin key.
All 73 SQL checks and 26 live assertions passed after a separate native-stack
reset on 2026-10-12, including the inherited authenticated-grant correction.
Physical response time,
heap use, refresh recovery and photo decode remain hardware checks.

Use the ordinary CLI deployment workflow above for your hosted project. The
[member check](tools/MEMBER-CHECK.md) tests household access and Realtime locally
before deploying changes.

## Member accounts and on-badge Auth

Use Settings → Member logins as the owner to create/link each account before its
first dashboard sign-in. An account that already owns a different home cannot
be moved silently. The owner can link their own account to a person.
`homehq_snapshot()` adds `home.id`, `viewer` and `members`; private Broadcast and
Storage authorization resolve the same home independently of each Auth UUID.

The non-exposed `homehq_private.current_home_id()` uses narrowly scoped definer
access to avoid membership-table policy recursion; it accepts no identity/home
argument and resolves only `auth.uid()`. The private linking function needs
`auth.users` email lookup, checks that the caller owns the home, and rejects
cross-home links. The exposed wrapper and all data RPCs remain invokers.

Run both SQL files and the [four-account wire check](tools/MEMBER-CHECK.md) after
membership changes. Actor FK indexes support referential cleanup; Auth-user
deletion clears attribution rather than restoring a removed user ID.
