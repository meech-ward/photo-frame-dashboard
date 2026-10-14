# Development and source map

[The repository README](../../README.md) is the entry point for running the project.
This directory explains the backend and device contract; platform READMEs own their
build/install commands. Develop the application in this public fork.

## Source ownership

| Change | Source |
| --- | --- |
| Dashboard presentation and interactions | `dashboard/js/`, `dashboard/css/`, `dashboard/index.html` |
| Supabase browser client and settings | `dashboard/src/` |
| Backend | `supabase/config.toml`, `supabase/schemas/`, `supabase/migrations/` |
| Badge drawing, buttons and sync | `devices/badge/view.py`, `model.py`, `service.py`, `transport.py` |
| Chromatic | `devices/chromatic/src/` and its pinned MCU platform patch |
| Shared sample data | `fixtures/demo.json`, generated projections via `tools/sync_demo.py` |
| Build and private provisioning | `tools/build.py`, `tools/configure.py` |

There is one copy of Wes’s frontend in `dashboard/`. Small explicit data/action
hooks connect its existing views to Supabase. Household settings cover account,
member and metadata administration without duplicating the seven display screens.
The native clients have independent layouts appropriate to their displays/buttons.

The browser uses ordinary `supabase-js`, build-time Vite environment variables,
Auth sessions and private household Realtime/Storage. A changed notification
causes a fresh authoritative read. The web projection includes the full calendar;
`homehq_snapshot()` remains the bounded device contract. See [backend setup](backend.md)
and [the wire contract](contract.md).

## Local development and checks

From the repository root:

```sh
npm --prefix dashboard ci
npm --prefix dashboard run dev
npm --prefix dashboard run typecheck
npm --prefix dashboard test
npm --prefix dashboard run build
python3 -m unittest discover -s devices/badge/tests -q
python3 tools/sync_demo.py --check
python3 tools/check_public.py
```

Browser interaction tests and dependencies are in the [web guide](../../dashboard/README.md).
SQL changes use the [declarative workflow](backend.md#declarative-changes).
Native bytecode checks use the [badge build guide](../../devices/badge/README.md);
Chromatic checks use its [platform guide](../../devices/chromatic/README.md).
[Hosted development checks](hosted-tooling.md) are optional and target an explicitly
selected disposable project. They are not ordinary setup steps.

Test the surface changed. File moves need path/build checks; Auth, database and
UI changes need their corresponding behavior checks. A unit test does not prove
physical Wi-Fi, display timing or a device installation. Record exactly what ran.

## Generated output and private data

`build/`, `dashboard/dist/`, compiler/CLI downloads and device dumps are generated
or private; they are not canonical source. `build/mpy/homehq/` is the compiled
badge app and installs at `/system/apps/homehq`. The repository directory name
`devices/badge` does not need to match that installed name.

Keep populated `.env.local`, Wi-Fi configuration, refresh tokens, photos, device
backups and hosted-account records out of Git. Never copy one device’s rotating
refresh token onto another device. Each device signs in independently; native
passwords are transient and access tokens stay in memory.

The minimal badge dependencies are pinned with public source hashes in
`devices/badge/vendor/provenance.json`. They include runtime/UI source, fonts and
certificate roots, not the complete SELECT firmware. [badge.select/guides](https://badge.select/guides)
is the stable firmware/setup reference. Build and install this app from the
normal repository; there is no separate starter source tree to maintain.

## Porting to another device

Reuse [contract.md](contract.md), Auth, database and the model where appropriate.
Adapt rendering, input, lifecycle, networking and memory/storage limits explicitly.
A browser-capable display can run the existing dashboard at a reachable hosted URL.
A laptop loopback URL cannot serve another device.

On the badge, keep HTTP/TLS/WebSocket work out of drawing and input. Its cooperative
transport implements the used API subset of the modern
[Supabase MicroPython library](https://github.com/meech-ward/supabase-micro), pinned
in the source record. It is not a replacement for the full public SDK.
The Chromatic C/LVGL port illustrates another implementation of the same contract.

Verify login, refresh/restart, identity clearing, authorized data access, Realtime
reconnect, concurrent desired-value writes and photo decode limits on a new port.
Existing hardware evidence does not transfer automatically to another runtime.

## Cleanup verification — 2026-10-13

The consolidated layout passed 52 web unit tests, 16 browser tests, TypeScript
checking and the production web build. Browser cloud responses were synthetic;
the optional live-project browser test was not run. A fresh disposable local
Supabase stack passed 171 SQL assertions with no declarative drift.

Native checks passed 168 badge tests, 19 tooling tests, 51 Chromatic tests and
all six CMake host checks (one optional private-fixture case was skipped).
The relocated badge build retained all 60 source/bytecode/asset hashes from the
accepted payload; compiled imports, Auth rendering and photo decode passed in
the WASM runtime. Public-source links and shared sample parity also passed.
No hosted migration or physical device deployment was performed for this cleanup.

## Attribution and contribution

[fork-source.json](fork-source.json) records the upstream source. [Research](research.md)
records the original project/video; [contributing](contributing.md) explains component
licenses and Wes’s community-build contribution route. The [social draft](social.md)
is unpublished. Preserve original attribution and dependency license notices.
