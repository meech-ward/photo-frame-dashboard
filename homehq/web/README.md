# Home HQ companion

The default display now runs the **original Wes Bos dashboard frontend**, with
its seven screens, typography, navigation and slideshow. The source is pinned,
kept unchanged under `upstream/`, and verified by `node tools/check-upstream.mjs`.
See [upstream and additions](UPSTREAM.md) and the
[GitHub fork](https://github.com/meech-ward/photo-frame-dashboard).

`src/upstream.ts` adds the existing Supabase Auth, snapshot, versioned writes,
private Realtime and Storage client to that frontend. `src/upstream-data.ts`
projects our household contract into its DATA structure. The native badge and
backend require no migration or reinstall for this browser change.

Use **Edit household** to open `/editor.html`: the existing companion is retained
for account settings, member setup, metadata edits and photo uploads. **Back to
dashboard** returns to the original display. The dashboard's chore/checklist and
supported sample device actions persist through the same backend. Event creation
and bulk list cleanup open the editor. Chore stars retain the assignment; SQL
separately records the authenticated person who performed the action.

Original weather, home/agent provider readings are explicitly samples. Unsupported
thermostat, cameras, media, scenes, weekly chore history and favourites are not
presented as durable controls. Calendar grids show the bounded seven-day snapshot;
dates outside that range have no fetched events. Photos support the original
layouts, with Cover fallback when there are too few images for Pair/Collage.

## Start locally

Use Node 22.12 or newer. From this directory:

```sh
npm ci
npm run dev
```

Open Vite’s printed Local URL. Without project configuration, the public preview
opens Wes’s original mock-data prototype with a local-only label. Its direct
prototype interactions are transient. The separate editor’s offline edits and
prepared photos stay in this browser’s local storage. Settings → Reset
demo restores the original example. Its labelled demo clock starts at 3:18 PM so
the Piano lesson scenario is always available.

For live mode, first apply the setup under `../supabase/`, then configure the
project once in this application's environment:

```sh
cp .env.example .env.local
```

Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in `.env.local`,
then run `npm run dev`. For a production deployment, supply those variables in
the build environment before `npm run build`. Vite bundles the public client
configuration using its [standard environment handling](https://vite.dev/guide/env-and-mode).
Restart Vite after changing an environment file. An incomplete/invalid
configuration reports an app setup error instead of silently loading mock data.
Old `homehq.connection.v1` browser settings are ignored.

Choose Edit household and sign in with email/password. Users do not enter or
save the project URL/key. Auth session persistence stays with supabase-js.
Email confirmation follows your project’s normal Auth settings. The first sign-in
calls `homehq_seed_demo(false)`; it preserves an existing home and resolves a
linked member to the shared household. The owner sets up member logins in Settings
before their first dashboard sign-in. The badge has its own email/password
sign-in screen, as described in the parent Home HQ README. Never copy the editor’s refresh token to the badge.

With a project configured, the editor always connects to Supabase. A restored
session connects automatically across reloads, including browsers with an old
saved demo preference. There is no offline/demo switch in this configured setup.
A missing or rejected session shows **Sign in**, with account controls
in Settings, rather than substituting local sample data. **Sign out** uses local
scope, ending only this browser's session and preserving independent badge
sessions. The live clock, date and greeting use the home's IANA timezone,
wherever the browser is running. Ordinary access-token expiry refreshes
automatically while the session remains valid.

During connection loss the last live snapshot stays visible with a reconnecting
status. Edits require a valid session, a loaded household and a connected channel;
the client retries instead of saving into the offline example. Every join/rejoin
also refreshes the authoritative snapshot. A warm rejoin can enable edits before
that asynchronous refresh completes; versioned writes still detect conflicts.
The **Live sync** label reports this editor's own subscription, not the physical
badge's Wi-Fi state.

The browser uses the build's public publishable key plus the signed-in member's
normal Auth session. URL/key configuration is never saved by the browser UI.
Secret and service-role keys are rejected and never belong in `VITE_` variables.
Sign-in, refresh and recovery reuse one client and its Auth listener.

## Run against your hosted project

After deploying a Home HQ project using the [backend guide](../backend-README.md),
set the two variables above in `homehq/web/.env.local`, then run:

```sh
npm --prefix homehq/web ci
npm --prefix homehq/web run dev -- --port 5191 --strictPort
```

Open `/editor.html?settings=1` to sign in. The URL and public key are application
configuration; each browser/device has its own ordinary Auth session.

The optional `homehq/tools/companion.py` helper can populate the same ignored
`.env.local` from CLI/local-stack metadata or a hosted `--url`/`--key-file`.
It is an operator convenience, not a browser configuration mechanism. Normal
Vite dev/build commands work directly without it.

## The data flow

`src/backend.ts` contains the unchanged Supabase surface used by the display and editor:

1. Normal `createClient`, Auth sign-in/signup and session refresh.
2. `homehq_snapshot()` reads the same version 1 document as the badge.
3. A private channel named `homehq:<snapshot.home.id>` listens for `changed` Broadcasts.
   Hints coalesce into snapshot reads. Every successful join/rejoin refetches state,
   so an edit missed offline is recovered from durable rows.
4. `homehq_set_done` sends the desired boolean and known version. A conflict refreshes
   the authoritative row; retries do not toggle an item a second time. Shared chores
   credit the signed-in member automatically. SQL records the actual Auth actor
   independently of assigned chore stars. Undo sends a new desired-state command.
5. `homehq_save_event` saves the event and attendee links in one transaction.
   People, checklist descriptions and photo metadata use ordinary household-scoped table
   writes. Versions and revisions are owned by SQL.
6. `homehq_set_device` changes clearly labelled sample lights/locks/garage state.
   Locks and garage actions have explicit confirmation. No physical-home provider
   integration is included.
7. Photo uploads are centre-cropped to 320×240, encoded as a non-interlaced PNG and
   stored in the private `homehq-photos` bucket at `<owner>/<sha256>.png`. Original
   files and EXIF metadata are not uploaded. Signed URLs display the private images.
   The converter combines PNG image-data chunks without changing pixels: the
   badge decoder rejects certain valid multi-chunk PNGs generated by browsers.
   [Native codec regression](https://github.com/meech-ward/select-badge/blob/main/benchmark/results/reports/2026-10-12-homehq-photo-recovery.md#actual-uploaded-image-cause-and-converter-correction)
   records the failure and the browser-to-native verification command.

Weather, home readings and agent usage retain visible **Sample** labels. The editor
does not imply that real weather or provider accounts are connected. `src/types.ts`
matches `../CONTRACT.md`; timestamps on the wire are Unix seconds.

Photo limits: JPEG/PNG/WebP, at most 20 MB before preprocessing and 320 KiB after
PNG conversion, matching the badge's bounded reader. Poorly compressible 320×240
photos can exceed 256 KiB and remain valid under this cap. The first uploaded
image replaces a bundled sample descriptor. Removing a descriptor does not delete
its content-addressed Storage object, which can be shared by another descriptor.
A metadata-write failure can likewise leave an unused private object. These objects
can be cleaned in the owner’s Storage dashboard.

Live calendar times use the home's IANA timezone, including offset changes at the
event date. The calendar pages through the bounded seven-day snapshot. A person
with existing event/chore links must be reassigned before removal.

## Verification

```sh
npm run typecheck
npm test
npm run build
npm run test:e2e
```

The browser tests use two local Vite servers so the public prototype and an
environment-configured app are tested separately. Start these in separate
terminals from this directory, then run `npm run test:e2e`:

```sh
VITE_SUPABASE_URL= VITE_SUPABASE_PUBLISHABLE_KEY= npm run dev -- --port 5184 --strictPort
VITE_SUPABASE_URL=https://reload-test.supabase.co VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_test_only npm run dev -- --port 5185 --strictPort
```

The configured tests intercept every Auth/RPC/Storage/WebSocket request; the
synthetic key is not a real project credential. `HOMEHQ_WEB_URL` and
`HOMEHQ_CONFIGURED_WEB_URL` can override those test URLs.
Demo tests cover family/event edits, versioned checkbox intent and Undo, shared-chore
attribution, shopping, confirmed sample controls, real PNG preprocessing and phone
overflow. Screenshots are written under ignored `test-results/`.

Live tests run only against an explicitly supplied **disposable local** project:
run a separate Vite server with that local project’s environment configuration,
then set `HOMEHQ_LIVE_WEB_URL` to its origin and `HOMEHQ_TEST_URL`/`HOMEHQ_TEST_KEY`
(its publishable key), or set
`HOMEHQ_LOCAL_ENV_FILE` to the local helper’s private JSON metadata file. They create
their own test accounts, exercise independent same-owner sessions and Realtime,
and check another owner cannot read/update rows or join the first owner’s channel.
They leave test accounts in that disposable project; reset it when finished.

No hosted Site is created or published by these commands. Physical badge rendering,
latency, Wi-Fi recovery and private photo decoding require the separate device pass.

## Member logins

Settings lists the family and whether each person has a linked login. Only the
household owner sees the setup form: choose the person, enter their email, and
optionally a password to create a new account. Existing accounts need only email.
A temporary non-persistent Auth client creates the account without replacing the
owner's session; the owner then authorizes its membership. The form clears the
password after submission. Required email confirmation follows project settings.

Members see the same household, with their own chore/calendar filter initially
selected and Anyone chores still visible. Completion displays the authenticated
member's name when available. Sign-out and account changes clear selection and
Undo; browser logout never revokes another device's session.
