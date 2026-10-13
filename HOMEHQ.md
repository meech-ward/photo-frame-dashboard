# Home HQ additions

This fork keeps [Wes Bos's photo-frame dashboard](https://github.com/wesbos/photo-frame-dashboard)
and adds a Supabase household backend, an editor and native device ports under
`homehq/`. The original root README and `dashboard/` remain unchanged.

## Run the dashboard in development

Use Node 22.12 or newer. From this repository root:

```sh
npm --prefix homehq/web ci
cd homehq/web
npm run dev
```

Open the Local URL printed by Vite. `/` uses Wes's original dashboard frontend,
with its seven pages, styles, navigation and photo layouts. The original files
are pinned unchanged in `homehq/web/upstream/`; the Supabase adapter and small
integration overrides live in `homehq/web/src/upstream.ts` and
`upstream-data.ts`. Run `node tools/check-upstream.mjs` from `homehq/web` to
verify that pinned copy. Vite serves source with hot reload in development.

Choose **Edit household** or open `/editor.html` for accounts, member setup,
household editing and photo uploads. Without project configuration, the public
preview is clearly labelled local-only and uses original mock data. It is not
connected to a real household or other devices.

## Connect your own Supabase project

Create a fresh project and follow
[the backend deployment guide](homehq/backend-README.md#deploy-to-your-own-supabase-project)
to apply the configuration and migrations, including Auth, household policies,
private Realtime and the private `homehq-photos` Storage bucket. The authored
declarative schema is in `homehq/supabase/schemas/`; deployed history is in
`homehq/supabase/migrations/`. The demo operator's hosted helper targets their
specific project; use the general deployment guide for your own project.

In `homehq/web`, copy `.env.example` to the ignored `.env.local` and replace its
example values with your project URL and public **publishable key**. These
variables are the only app project configuration; sign-in asks only for
email/password. For production, provide them in the build environment. Restart
Vite after changing environment configuration. Never put a secret or
service-role key in the frontend, and never copy an existing user's session.

Sign in or create an ordinary owner account in `/editor.html`. Confirmation
follows your project's Auth settings. The first owner sign-in initializes the
example household; use Settings to create/link logins for its other members.
Each browser and device signs in independently. They share the household's
database rows and private Realtime channel, while Auth records who performed
an action. See [the web guide](homehq/web/README.md) for the exact data flow.

Use **Photos → Add photo** in the editor. It prepares a 320×240 PNG, uploads it
to the private bucket and registers its `homehq_photos` row. Files dropped
directly into Storage need that metadata row before a display can find them.

Weather, home controls and agent-provider readings remain visibly labelled
samples. The integration does not connect real appliances or provider accounts.
Unsupported thermostat, camera, media, scene, historical chore and favourite
features are not presented as durable controls. Calendar data is the same
bounded seven-day snapshot used by the native app.

## Native devices and canonical source

The native MicroPython Tufty app is in `homehq/badge/homehq/`; a separate
Chromatic port is in `homehq/chromatic/`. Their platform and physical acceptance
requirements are documented in those directories and
[the Home HQ handoff](homehq/HANDOFF.md).

**This fork is sufficient to run the web frontend and deploy its backend. The
`homehq/` directory alone is not a standalone native badge build.** Tufty builds
also collect shared UI/keyboard modules, badge networking, CA files, fonts and
the compatible Badgeware runtime from the full
[meech-ward/select-badge repository](https://github.com/meech-ward/select-badge).
Use its current `homehq/` source and
[build/install guide](https://github.com/meech-ward/select-badge/blob/main/homehq/BUILD.md)
for a native build, or use the complete exported starter described there.
Do not assume this fork's app folder contains the full device dependency set.

The maintained source for these additions is
[meech-ward/select-badge/homehq](https://github.com/meech-ward/select-badge/tree/main/homehq).
Wes's original dashboard is preserved here so the additions can be reviewed
beside it rather than replacing his frontend with a recreation.

## Check the web additions

From `homehq/web`:

```sh
node tools/check-upstream.mjs
npm run typecheck
npm test
npm run build
```

Browser and local backend checks are described in
[the web guide](homehq/web/README.md). Neither these commands nor this fork's
presence imply that a physical device has been installed or tested.
