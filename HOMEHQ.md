# Home HQ: one household, three displays

This fork builds on [Wes Bos's photo-frame dashboard](https://github.com/wesbos/photo-frame-dashboard).
It keeps his original web dashboard and adds a Supabase backend, a household
editor, and native apps for the **SELECT Tufty 2350 badge** and the
**ModRetro Chromatic**. Accounts, calendar events, chores, shopping and uploaded
photos belong to one household and sync between its signed-in devices.

Wes's `dashboard/` and Android frame guides are preserved. The root README adds
only a Home HQ entry note above his original instructions.
The additions live in `homehq/`; the [upstream manifest](homehq/web/UPSTREAM.md)
pins and verifies the 29 original frontend files reused by the connected app.
The badge and Chromatic have their own native layouts and button controls.

## Run the web app

Use Node **22.12+**. From this repository root:

```sh
npm --prefix homehq/web ci
cd homehq/web
npm run dev
```

Open Vite's printed Local URL. `/` displays Wes's dashboard. **Edit household**
opens `/editor.html` for sign-in, member accounts, editing and photo uploads.
With no Supabase configuration, the preview clearly says local-only; its data
does not sync to devices.

To connect your own household:

1. Create a Supabase project and follow the
   [backend deployment guide](homehq/backend-README.md#deploy-to-your-own-supabase-project)
   to apply the checked-in configuration and migrations.
2. Copy `homehq/web/.env.example` to the ignored `homehq/web/.env.local`.
   Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`, then restart Vite.
   Use the publishable key, never a secret or service-role key.
3. Create/sign into an owner account in the editor. The first owner sign-in
   initializes the sample household. Settings creates or links member logins;
   each browser and device signs in with its own email/password.

For hosting, run `npm run build` from `homehq/web` with those environment
variables set and deploy `dist/` as a static site. Add its URL to your project's
Auth redirect settings. The [web guide](homehq/web/README.md) covers local and
hosted setup.

Private Realtime messages tell clients to fetch the authoritative database
snapshot. Row policies and private Storage folders restrict access to household
members. Device sessions keep rotating refresh tokens; passwords are not saved.
Use **Photos → Add photo**: JPEG, PNG and WebP input is cropped to 320×240 and
stored as JPEG and PNG variants. Tufty and web prefer JPEG; Chromatic uses the
PNG variant. Uploads also create the metadata row the slideshow needs.

## Choose a device

| Target | Source | Build and install |
| --- | --- | --- |
| Web / Android photo frame | `homehq/web/`, reusing Wes's original frontend | [Web guide](homehq/web/README.md); original [Android kiosk](dashboard/kiosk/README.md) |
| SELECT badge / Pimoroni Tufty 2350 | `homehq/badge/homehq/`, native MicroPython at 320×240 | [Tufty build/install guide](homehq/BUILD.md) |
| ModRetro Chromatic | `homehq/chromatic/`, native C/LVGL at 160×144 | [Chromatic build/install guide](homehq/chromatic/README.md) |

The fork includes the Tufty app's minimal generic source, font and certificate
dependencies in [`homehq/vendor/tufty/`](homehq/vendor/tufty/README.md).
Build it from this repository with the pinned MicroPython compiler; the complete
SELECT conference repository is not a build dependency. Start at
[badge.select/guides](https://badge.select/guides) for compatible firmware, setup
and current source downloads. Configure the project's URL/public key and Wi-Fi,
then sign in on the badge.

Chromatic builds use a separate checkout of the pinned public ModRetro MCU
source plus the checked-in platform patch. They need ESP-IDF and the documented
programming connection. This app uses the console's ESP32 display overlay; it
is not a Game Boy cartridge ROM. The guide states exactly which hardware behavior
has been verified and which measurements remain open.

## Find and change the code

| Change | Start here |
| --- | --- |
| Reused dashboard and Supabase adapter | `homehq/web/upstream/`, `src/upstream.ts`, `src/upstream-data.ts` |
| Household editor and browser client | `homehq/web/src/main.ts`, `src/backend.ts` |
| Database, Auth, Realtime and photo policies | `homehq/supabase/config.toml`, `schemas/`, `migrations/` |
| Tufty layout, interaction and sync | `homehq/badge/homehq/view.py`, `model.py`, `service.py`, `transport.py` |
| Chromatic layout, sync and platform integration | `homehq/chromatic/src/`, `tools/prepare.py` |
| Shared sample data and device-independent contract | `homehq/fixtures/demo.json`, [CONTRACT.md](homehq/CONTRACT.md) |
| Source/output map and another-device porting | [HANDOFF.md](homehq/HANDOFF.md) |

The native ports use a bounded seven-day calendar and smaller layouts. Weather,
home controls and agent meters remain labelled samples; they do not connect real
appliances or provider accounts. Original sample names and events come from
Wes's mock data. Bundled landscape illustrations are labelled sample art.

## Check and contribute

```sh
python3 homehq/tools/check_public.py
python3 -m unittest discover -s homehq/tests -q
python3 homehq/tools/sync_demo.py --check
node homehq/web/tools/check-upstream.mjs
npm --prefix homehq/web run typecheck
npm --prefix homehq/web test
npm --prefix homehq/web run build
```

Native graphics, SQL, browser and Chromatic checks have their own focused guides.
An install alone does not prove physical behavior. Keep generated output,
`.env.local`, device state, Wi-Fi credentials, sessions and backups out of Git.

[Contribution guidance](homehq/CONTRIBUTING.md) explains the fork's source
provenance and the small community-build contribution requested by Wes's repo.
The [social draft](homehq/SOCIAL.md) credits the original project and links the
code; it has not been published.
