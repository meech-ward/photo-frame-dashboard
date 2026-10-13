# Home HQ agent handoff

Current state: **2026-10-12**. Start here to customize the demo, deploy another
household or plan a port. Read repository `AGENTS.md` and the
[development map](https://github.com/meech-ward/select-badge/blob/main/docs/development.md) before editing. The current request
defines the work; deployment history does not authorize new device/cloud actions.

## Get the current source

Canonical repository: [meech-ward/select-badge](https://github.com/meech-ward/select-badge),
**`origin/main`, directory `homehq/`**. The persistent local `main` mirror can
lag while unrelated user files are present. Use an isolated worktree from
freshly fetched `origin/main`, not that mirror:

```sh
git -C /Users/supa-sam/Projects/badge fetch --prune origin
git -C /Users/supa-sam/Projects/badge worktree add \
  /private/tmp/homehq-next-task -b codex/homehq-next-task origin/main
cd /private/tmp/homehq-next-task
```

Choose a fresh path/name if those exist. Follow the
[integration workflow](https://github.com/meech-ward/select-badge/blob/main/docs/agent-git-workflow.md). Completed work is on
`main`; finished task worktrees have been removed. The primary checkout's
unrelated root `supabase/` directory is not this app's backend.

## Source map

Paths are relative to the repository or extracted starter root.

| Purpose | Canonical path |
| --- | --- |
| Overview, buttons and account setup | [homehq/README.md](README.md) |
| Household identity, wire format, RPCs and Realtime | [homehq/CONTRACT.md](CONTRACT.md) |
| Pure interaction, navigation and time model | [homehq/badge/homehq/model.py](badge/homehq/model.py) |
| Native typography, icons and photo drawing | [homehq/badge/homehq/view.py](badge/homehq/view.py) |
| Badgeware entry, lifecycle and button dispatch | [homehq/badge/homehq/__init__.py](badge/homehq/__init__.py) |
| Native credentials form and keyboard | [homehq/badge/homehq/login.py](badge/homehq/login.py) |
| Snapshot, desired-value queue, identity/cache and photo orchestration | [homehq/badge/homehq/service.py](badge/homehq/service.py), [cache.py](badge/homehq/cache.py) |
| Badge cooperative HTTP/TLS/WebSocket/Wi-Fi engine | [homehq/badge/homehq/transport.py](badge/homehq/transport.py) |
| Modern Auth API subset and refresh-only records | [homehq/badge/homehq/auth_client.py](badge/homehq/auth_client.py) |
| Browser UI and standard supabase-js client | [homehq/web/](web/README.md): `upstream/` (original display), `src/upstream.ts`/`upstream-data.ts` (adapter), `src/main.ts`/`style.css` (editor), `backend.ts` (shared client) |
| Backend setup and permissions | [homehq/backend-README.md](backend-README.md) |
| Auth/Storage/local-runtime configuration | [homehq/supabase/config.toml](supabase/config.toml) |
| Authored SQL / applied forward migrations | `homehq/supabase/schemas/` / `homehq/supabase/migrations/` |
| Authored sample data / projection checker | [homehq/fixtures/demo.json](fixtures/demo.json), [tools/sync_demo.py](tools/sync_demo.py) |
| Build, export and private configuration | [homehq/BUILD.md](BUILD.md), `homehq/tools/build.py`, `export.py`, `configure.py` |
| Unit, SQL, browser, wire and native-render checks | `homehq/tests/`, `homehq/supabase/tests/`, `homehq/web/tests/`, `homehq/tools/` |
| Wes source, full video/transcript review, social draft | [homehq/RESEARCH.md](RESEARCH.md), [SOCIAL.md](SOCIAL.md) |
| Measurements, failed assumptions and deployment deviations | [Home HQ evidence](https://github.com/meech-ward/select-badge/blob/main/benchmark/results/reports/2026-10-11-homehq-local.md) |

## Local outputs and private state

| Location on this machine | Contents |
| --- | --- |
| `/Users/supa-sam/Projects/badge/build/homehq-demo/` | Extracted public starter; public export, not the canonical development checkout |
| `/Users/supa-sam/Projects/badge/build/homehq-private-20261012/` | Ignored operator metadata, `member-logins.private.txt`, device backups and result records |
| `/Users/supa-sam/.codex/visualizations/2026/10/11/01a12c4b-20d5-7002-a4fb-92885219daab/` | `homehq-starter.zip`, `homehq-delivery.json`, render/native evidence |

Edit canonical source and regenerate these outputs. Passwords, Wi-Fi details
and sessions must not be printed, committed or exported. Private temporary
controllers are not required source dependencies; the checked-in guides/probes
describe reproducible behavior. Never blindly restore an old rotating refresh
token from a backup.

## Current implementation and deployment

Home HQ is a separate personal demo with seven native 320×240 pages, an editor,
ordinary email/password Auth, one shared household with linked members, private
Realtime/Storage, versioned checklist writes and server-stamped creator/completer
identities. Weather, appliances and agent meters remain labelled samples. No real
provider integration or social post has been published. Stable badge 1.0.3 and
its six production tiles remain unchanged; Home HQ is an extra development tile.

The modern interface reference is
[meech-ward/supabase-micro](https://github.com/meech-ward/supabase-micro), checked
at `aa30dc4e16a7ee7afc31b305b4011c4b4e87dc6c`. The badge keeps its own cooperative
network engine and matches only Home HQ's required Auth/RPC methods. It does not
vendor or implement the entire public SDK. Browser clients use normal supabase-js.

The hosted demo is **Home HQ**, project `cicgysjddsjsbgofpxwr`, in **DevRel Free**
organization `yuueonycfgiwijatkqyv`, independently of BadgeLink and DevRel Pro.
Household `511eb57d-7662-45e6-a897-897961498ddc` has four distinct Auth identities.
Stable person IDs/labels are Wes=`alex`, Claudia=`jordan`, Buzzsaw=`maya`,
Skidmark=`otto`; names are labels, not the authorization key.

At the owner's request, existing demo accounts were renamed and given one easy
eight-letter password through the server-only Auth admin API. All four fresh
password sign-ins and authorized household snapshots passed; UUIDs, membership
and history were preserved. Emails are `wes@home.test`, `claudia@home.test`,
`buzz@home.test`, `skid@home.test`. Credentials are in the private login sheet
and operator JSON, omitted from public guides/exports. The temporary privileged
key stayed in operator memory, never on a
device/browser or in a saved file. Badge flash retains only refresh token/user ID,
not a password or access JWT. Every device/browser owns a separate Auth session.
Clients use a project publishable key plus ordinary Auth; no custom device JWT
is minted. Local sign-out affects that device's session, not the other members.

The companion at `http://127.0.0.1:5191/` uses Wes’s original dashboard.
The retained household editor/account/upload UI is at `/editor.html`.
Current development source is `/Users/supa-sam/Projects/badge-homehq/homehq/web`;
the public starter also carries the same frontend. It is a local server, not a public deployment or a guaranteed service
after restart. Its ignored `.env.local` supplies `VITE_SUPABASE_URL` and
`VITE_SUPABASE_PUBLISHABLE_KEY`; these are the only browser project configuration.
The account form asks only for email/password, and legacy browser connection
settings are ignored. Restart using
the [companion helper](web/README.md#run-against-your-hosted-project) with existing
public-key configuration supplied privately; never copy a browser Auth token.

To restart the dashboard/editor using its saved configuration/dependencies:

```sh
cd /Users/supa-sam/Projects/badge-homehq/homehq/web
npm run dev -- --host 127.0.0.1 --port 5191 --strictPort
```

If that port is already serving this dashboard, reuse it. For a clean installation
or another project, follow `web/README.md` and install from its lockfile.

| Device | Recorded acceptance / latest state |
| --- | --- |
| Tufty `6d9430717fc47ddf` | Full earlier native Auth/rotation/recovery, private photo/storage and cross-account Realtime acceptance; member run used Claudia. Latest countdown `view.mpy` is now installed and native75/MIN pixels match the other board exactly. All196 other system/state hashes matched. It had no saved session/cache before this update and was handed back at normal sign-in. |
| Tufty `03bfbc20532aa948` | Same 20-module app, independently logged in as Wes; latest countdown `view.mpy` installed. Interactive app returned Live/revision 238/pending 0; all 197 unrelated system/state hashes matched during the UI copy. |
| Pico `e7e7d70437b93611` | Explicitly excluded; never opened or modified. |

Both Tuftys use `bw-1.29.0-gc` (2026-09-22), `_mpy=7942`. Firmware was not
flashed and storage was not formatted. USB port names can move: select by actual
USB/native identity. The published physical probes deliberately guard the first
UID/runtime; adapt a target only after explicitly selecting another board.

The [dated evidence](https://github.com/meech-ward/select-badge/blob/main/benchmark/results/reports/2026-10-11-homehq-local.md)
records corrections for native `str.isalnum`, WebSocket idle/recovery, photo
bounds, readonly-FAT installation and cropped `75`. Latest checks include 156
host tests, 121 SQL assertions, 49 local wire assertions, 19 companion browser
cases, 41 compiled screen states and nine countdown glyph controls. Four distinct
hosted accounts passed fanout/reconnect; this is not four physical boards or a
concurrent two-board acceptance test. Battery/power-loss guarantees, four-board
radio behavior and other hardware ports remain unverified. Native TLS connection
work can pause an update around 0.8 s. Limits and failed results remain in the report.

## Customization and deployment routes

Change native appearance in `view.py`, interaction in `model.py`, and browser
additions in `web/src/upstream.ts`/`upstream.css`; `web/src/style.css`/`main.ts`
own the retained editor. `web/upstream/` is pinned original source: see
[UPSTREAM.md](web/UPSTREAM.md) before changing it. Keep network work out of drawing and
input. App-local `ui.py` is generated from `shared/ui.py`; edit shared source only
for a shared change, following the repository sync rules.

Edit `fixtures/demo.json` for authored samples, then run `tools/sync_demo.py`
and follow the [declarative workflow](backend-README.md#declarative-changes).
Live family edits belong in the configured companion. Reset/reseed deliberately
replaces sample data; it is not routine deployment. Applied migrations are
immutable; generate a new forward migration for a schema change.

For another account/project, follow the ordinary
[fresh-project guide](backend-README.md#deploy-to-your-own-supabase-project),
[editor guide](web/README.md) and [badge install recipe](BUILD.md#app-only-install-from-the-public-starter).
`tools/hosted.py` is an exact-target Free DevRel operator helper, not a general
project selector. Create/link the owner and member accounts in the new editor;
each device signs in separately with project URL/public-key configuration.

The app folder alone is not the full dependency set. `tools/build.py` collects
shared UI/keyboard, generic aiohttp/Realtime/backoff, verified TLS roots and fonts
from elsewhere in the repository. The public starter includes these sources plus
`badge/source/homehq/`, `badge/mpy/homehq/` and its manifest. Use compatible
compiler/firmware. Follow each surface's focused checks; documentation-only work
needs link/Git checks, not builds, live services or devices.

## Porting to another device

The backend, wire contract and web companion are device-independent. The shortest
browser-capable route is the existing companion in that device's browser/kiosk.
Configure reachable hosting and Auth origins using the guides above; laptop
loopback5191 is not a remote-device URL. Kiosk-specific display/input behavior
still needs its own acceptance.

For a native port, reuse `CONTRACT.md` and pure `model.py`. Replace `__init__.py`'s
Badgeware lifecycle/injected globals, `view.py`/`SignInView`'s hardcoded 320×240
picovector/fonts, and A/B/C/UP/DOWN input with the target's display/runtime/input.
Choose framebuffer, photo and decoded-memory budgets for the new hardware.
Uploaded photo descriptors now carry a PNG `path` and optional `jpeg_path`.
Tufty prefers the baseline JPEG; the Chromatic retains the streaming PNG path.
Use the [photo contract](CONTRACT.md) when adding another device instead of
assuming a filename extension or copying a device-specific cache implementation.

`Service` accepts an injected transport and configurable `state_root`. Preserve
snapshot/status/command/poll, desired-value conflicts/retries, account-separated
cache/outbox and saving rotated refresh tokens before further RPC work.
`cache.py` assumes JSON, writable storage and same-directory temp-file rename;
verify those semantics on the target.

The badge transport depends on MicroPython WLAN, custom aiohttp connection hooks,
verified TLS, the Realtime client and an asyncio loop pumped with
`run_until_complete`. Adapt WLAN, sockets/TLS, wrapping monotonic timers, UTC/epoch,
loop ownership and persistence deliberately. A running async application needs
appropriate loop integration. On a normal Pico, the modern public SDK defines the
API reference; choose a supported client and retain the required Auth/RPC shapes.
Do not claim the badge's measured recovery/timing behavior for a different client.

Test the new target's login, refresh/rotation/restart, local logout/identity
clearing, authorized snapshots, private changed hints/rejoin/catch-up, write
retry/conflict behavior and photo storage/decode bounds. The supplied `.mpy`
payload requires compatible bytecode/small-integer settings **and** Badgeware
graphics; copying it to another board is not a native port. The
[native Chromatic MCU port](chromatic/README.md) now implements the seven pages,
ordinary sign-in, household sync and target-specific caching/photos in C/LVGL.
Its host checks pass and the image fits the original app partition; installation
and physical acceptance are still pending. Its RAM-only downloaded photos and
smaller NVS cache budget are deliberate target limits, not badge measurements.
