# Home HQ dashboard

This is Wes Bos’s dashboard, extended with Supabase persistence and shared
accounts. The original seven views, styles, slideshow, kiosk tools and deployment
configuration remain here. There is one dashboard application.

## Run locally

Use Node 22.12 or newer. From this directory:

```sh
npm ci
cp .env.example .env.local
npm run dev
```

Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in `.env.local` to your
project. Apply the [backend setup](../docs/homehq/backend.md) first. Restart Vite
when environment values change. For production, supply the same variables in
the build environment and run `npm run build`. `npm run deploy` retains Wes’s
Cloudflare Wrangler deployment command.

The project URL and publishable key are public application configuration. Users
sign in with email and password through **Settings**; they never enter project
configuration. Supabase manages each browser’s independent session. Signing out
of a browser does not sign out the badges.

Without either environment variable, the app opens Wes’s original local
prototype. Its interactions are temporary. Partial or invalid configuration
shows a setup error. A configured app never substitutes example data for a
missing login or disconnected project.

## What is connected

The dashboard saves event creation, chore completion and Undo, grocery additions,
quantities, completion and clearing, and the supported sample lights, locks and
garage actions. Calendar creation uses Wes’s original event sheet.

`/settings.html` contains account controls, family profiles, member login setup,
photo uploads and household metadata forms. It is a management page, not another
dashboard. The owner can create or link member accounts; each badge signs in
independently with its member’s email and password. Email confirmation follows
the project’s Auth settings.

Weather, home readings and agent usage remain labelled samples. Thermostat,
cameras, media, scenes, weekly chore history and favourites are not connected.
The web calendar receives the full household event collection, including past
and future dates. The device snapshot keeps its separate bounded payload.

Uploaded JPEG, PNG and WebP files produce three private Storage objects: an
aspect-preserving web JPEG up to 2048 pixels on its longest side, a 320×240
baseline JPEG for the badge, and a 320×240 PNG for Chromatic and older clients.
The web image retains portrait orientation; device copies are centre-cropped.
Only after all uploads succeed are their content-addressed paths published in
the photo row. A failed upload keeps the existing photo. Browser encoding removes
original EXIF metadata. Older rows without a web image continue to display their
existing device image. Reupload an older photo to obtain the larger web version.

Removing a photo row does not delete its content-addressed Storage objects, which
can be shared by another row. Failed multi-object uploads may also leave unused
private objects; owners can remove these through the Storage dashboard.

## Code map

- `js/` and `css/`: Wes’s dashboard and presentation, with small explicit data hooks.
- `src/dashboard.ts`: connects those hooks to Supabase and publishes fresh household state.
- `src/dashboard-data.ts`: maps database field names and timestamps to the dashboard’s DATA shape.
- `src/backend.ts`: ordinary Supabase Auth, table/RPC writes, private Broadcast and Storage calls.
- `src/settings.ts`: account, member, photo and metadata management.
- `src/badge-png.ts` and `src/badge-jpeg.ts`: device image compatibility checks.

`App.dataSource` is the optional persistence boundary. Native view handlers call
its named actions before changing data. Connected mode publishes the server’s
snapshot after successful writes; unconfigured mode retains the original local
behaviour. No renderer methods are replaced at runtime and no document-wide
capture listener redirects native actions.

Realtime Broadcast sends invalidation hints on the private household channel.
The client rereads `homehq_web_snapshot()` after each hint and after every join
or rejoin, recovering edits missed offline. The badge uses its smaller
`homehq_snapshot()` contract. Versioned completion/device writes detect conflicts;
SQL attributes actions to the actual signed-in user. The status label describes
this browser’s subscription, not another device’s Wi-Fi connection.

## Verification

```sh
npm run typecheck
npm test
npm run build
npx playwright install chromium
```

Browser tests use two Vite servers: a prototype with no project variables and a
configured build whose cloud requests are entirely intercepted. From this
directory, start them in separate terminals:

```sh
VITE_SUPABASE_URL= VITE_SUPABASE_PUBLISHABLE_KEY= npm run dev -- --host 127.0.0.1 --port 5184 --strictPort
```

```sh
VITE_SUPABASE_URL=https://reload-test.supabase.co VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_test_key npm run dev -- --host 127.0.0.1 --port 5185 --strictPort
```

Then run `npm run test:e2e`. These browser tests exercise the actual Supabase JS
client against synthetic Auth/RPC/Storage/WebSocket responses; they do not prove
a hosted project or physical device. The optional `live.spec.ts` requires
`HOMEHQ_TEST_URL`, `HOMEHQ_TEST_KEY` and `HOMEHQ_LIVE_WEB_URL` pointing at a
**disposable local** project and a third configured Vite server. It creates test
accounts and data, so it is skipped without explicit configuration.
