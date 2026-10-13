# Home HQ source and porting map

Start with the [public quickstart](https://github.com/meech-ward/photo-frame-dashboard/blob/main/HOMEHQ.md).
This fork preserves Wes Bos's original photo-frame project and keeps its
Supabase integration and native device ports under `homehq/`. A fresh clone is
sufficient for the web/backend source and Tufty application build; Chromatic
uses a separate pinned public MCU checkout and ESP-IDF workspace.

## Source map

| Purpose | Source |
| --- | --- |
| Original Wes dashboard and Android frame tools (public fork) | Root `dashboard/`, `docs/`, `scripts/` |
| Reused, pinned original frontend | `homehq/web/upstream/`, [UPSTREAM.md](web/UPSTREAM.md) |
| Dashboard adapter and household editor | `homehq/web/src/upstream.ts`, `upstream-data.ts`, `main.ts`, `backend.ts` |
| Shared household and device contract | [CONTRACT.md](CONTRACT.md) |
| Auth, private Realtime/Storage and database permissions | [backend guide](backend-README.md), `homehq/supabase/config.toml`, `schemas/`, `migrations/` |
| Authored sample data and projections | `homehq/fixtures/demo.json`, `tools/sync_demo.py` |
| Tufty native layout and interaction | `homehq/badge/homehq/view.py`, `model.py`, `login.py` |
| Tufty sync, persistence and cooperative networking | `service.py`, `cache.py`, `transport.py`, `auth_client.py` in that app |
| Tufty's minimal generic dependencies | `homehq/vendor/tufty/` in this fork; [provenance](https://github.com/meech-ward/photo-frame-dashboard/blob/main/homehq/vendor/tufty/provenance.json) |
| Native Chromatic app and platform patch | `homehq/chromatic/src/`, `tools/prepare.py`, [Chromatic guide](chromatic/README.md) |
| Source build, export and private provisioning | [BUILD.md](BUILD.md), `homehq/tools/build.py`, `export.py`, `configure.py` |
| Focused checks | `homehq/tests/`, `supabase/tests/`, `web/tests/`, `chromatic/tests/`, `tools/` |
| Attribution, reference research and contribution draft | [RESEARCH.md](RESEARCH.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SOCIAL.md](SOCIAL.md) |

The web app is Vite with TypeScript and standard supabase-js. Wes's original
frontend is reused unchanged; a small adapter feeds it the household snapshot
and handles its supported writes. The editor provides accounts, metadata edits
and uploads. Native layouts are separate MicroPython/picovector and C/LVGL
implementations adapted to each display and its buttons.

The maintained SELECT-side source is
[meech-ward/select-badge/homehq](https://github.com/meech-ward/select-badge/tree/main/homehq).
This public fork records mirrored source revisions in `homehq/fork-source.json`.
The generic Tufty dependency copies are byte-identical to their recorded source
revision. In SELECT, the builder prefers their canonical shared paths; in this
fork, it uses the small vendored dependency set. Do not import the conference's
fleet apps, admin backend or credentials into Home HQ.

## Generated output and private state

| Path | Contents |
| --- | --- |
| `homehq/web/dist/` | Static web build; configure public Vite variables before building |
| `homehq/build/standalone/` | Tufty source/bytecode plus its build manifest |
| `homehq/artifacts/` | Optional exported starter ZIP |
| `homehq/build/private/` | Private provisioning output; project config and independent device sessions |
| `homehq/.tools/`, `.supabase-home/`, `.local.private.json` | Ignored local CLI/runtime metadata |
| Device `/state/` | Tufty Wi-Fi/project config, refresh-only Auth record, snapshot/outbox and photo slots |
| Separate Chromatic build/programming workspace | MCU dependency, ESP-IDF tools, generated firmware and private provisioning |

Edit source and regenerate output. No populated environment file, Wi-Fi password,
refresh token, personal photo, device dump or existing user's state belongs in a
public commit or export. Never restore another device's rotating refresh token.
Public URL/publishable-key configuration is separate from the ordinary Auth
session each browser/device obtains by signing in.

## Change or deploy this project

For your own project, follow the
[fresh Supabase deployment guide](backend-README.md#deploy-to-your-own-supabase-project),
[web setup](web/README.md), [Tufty install](BUILD.md#app-only-install) or
[Chromatic build/install](chromatic/README.md). Each device uses the same household
backend and its own login. The owner creates/links member logins in the editor.
The exact-target hosted operator helper is for the original demo operator;
it is not the deployment path for someone else's project.

Change Tufty appearance in `view.py`, interaction in `model.py`, and sign-in in
`login.py`. Keep networking out of drawing/input. Change browser integration in
`upstream.ts`, `upstream-data.ts` and `upstream.css`, or the editor in `main.ts` and
`style.css`. Check [UPSTREAM.md](web/UPSTREAM.md) before changing the pinned
original frontend. Shared Tufty modules are vendored dependencies with recorded
provenance; update them through their maintained source and refresh the allowlist.

Change authored examples in `fixtures/demo.json`, run `tools/sync_demo.py`, then
follow the declarative migration workflow. Applied migrations are immutable;
generate a new forward migration for a schema change. Live household edits
belong in the editor. A reset/reseed replaces data and is a deliberate local-demo
operation, not routine deployment.

## Current behavior and limits

All targets share ordinary email/password Auth, one household, private Realtime,
Storage photos and server-recorded action identity. Today shows the family;
Chores starts on the signed-in member. Versioned desired-value writes prevent
retries from toggling a checkbox twice. Refresh tokens are durable, passwords
are transient, and access tokens remain in memory on native devices.

Uploaded photos have a PNG `path` and optional `jpeg_path`. The browser prepares
both 320×240 variants. Tufty prefers baseline JPEG and retains PNG compatibility;
Chromatic uses its streaming PNG decoder. Use the contract rather than assuming
a file extension or copying another target's cache implementation.

The original mock household supplies the names and examples. Native calendar
views use a bounded seven-day snapshot. Weather, appliance controls and agent
meters are visibly labelled samples. Bundled illustrations are sample art,
not photographs of Wes's family. No real appliance/provider integration is
included.

Tufty and Chromatic have recorded native live/reconnect/photo acceptance; their
platform guides link the dated evidence and remaining measurements. A successful
build or install is not evidence of battery endurance, abrupt power-loss safety,
all-device radio behavior or another firmware/hardware combination. Home HQ is
an additional development app and does not change the stable SELECT badge roster.

## Port to another device

The backend, web app and contract are independent of hardware. A browser-capable
display can run the existing web app at a reachable hosted URL. Laptop loopback
is not a URL another device can use; follow the web guide for hosting/Auth origins.
Kiosk input and display behavior still require their own acceptance.

For a native port, reuse `CONTRACT.md` and the pure household model. Replace the
Badgeware lifecycle/injected globals, display/font renderer and button mapping.
Choose explicit framebuffer, decoded-photo and persistent-cache limits for the
new device. Preserve account-separated cache/outbox, desired-value writes,
Auth refresh rotation, private changed hints and authoritative refresh on join.

The Tufty transport owns MicroPython WLAN, TLS and a cooperatively pumped async
loop. Its required Auth/RPC interface follows
[meech-ward/supabase-micro](https://github.com/meech-ward/supabase-micro) at
`aa30dc4e16a7ee7afc31b305b4011c4b4e87dc6c`; it is a specialized implementation,
not the complete public SDK. Adapt networking, monotonic time, UTC, loop ownership
and storage semantics explicitly. A normal Pico can use the public SDK's
supported interface; the badge's measured behavior does not transfer to a
replacement client automatically.

Test the new target's login, refresh/restart, local logout/identity clearing,
authorized snapshots, private Realtime reconnect/catch-up, retry/conflict writes
and photo storage/decode limits. Compatible bytecode is only one requirement:
copying the Tufty `.mpy` payload to another board does not supply Badgeware
or create a native port. Chromatic's existing C/LVGL port is a concrete example
of replacing those seams while retaining the household backend.
