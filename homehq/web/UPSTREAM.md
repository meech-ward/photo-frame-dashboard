# Wes Bos dashboard source and our additions

The web display uses the actual frontend from
[wesbos/photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard),
pinned at
[`fbe9a30ac4f9c77d3863e19a5e98d9eadb04ab03`](https://github.com/wesbos/photo-frame-dashboard/tree/fbe9a30ac4f9c77d3863e19a5e98d9eadb04ab03/dashboard).
`upstream/` contains the original `dashboard/index.html`, `css/`, `js/`, and
`public/`, byte for byte. The full upstream repository also contains Android
photo-frame setup, kiosk code, device research and deployment configuration;
those are outside this browser frontend slice. This integration does not run
the Android flashing or kiosk tools.

The owner's full fork is
[meech-ward/photo-frame-dashboard](https://github.com/meech-ward/photo-frame-dashboard).
Its original `dashboard/` remains untouched. The added `homehq/` directory is an
extension snapshot published only after the integration passes its checks.
Canonical development remains in
[meech-ward/select-badge, `homehq/`](https://github.com/meech-ward/select-badge/tree/main/homehq):
make changes there first, verify them, then refresh the additive fork snapshot.
Do not maintain divergent implementations in both repositories.

`upstream/index.html` records the original shell. The app's entry HTML can add
connection/account controls and the companion editor without rewriting that
shell's views. The original typography, stylesheet rules, view renderers,
slideshow layouts, navigation and demo data stay in the vendored files.

Our additions live outside `upstream/`: `src/upstream.ts` is the Supabase adapter.
The existing `src/backend.ts` client, account/project setup, household editing
and private photo upload remain in the companion at `editor.html`. The badge
still uses its native MicroPython UI and cooperative networking; a browser
frontend is not a badge executable. All live clients use the same Home HQ schema
and private household Realtime channel.

## Check original-file integrity

From this directory:

```sh
node tools/check-upstream.mjs
```

`upstream-files.json` records SHA-256 and byte counts computed from the pinned
upstream checkout, not from a modified vendor copy. The checker rejects missing,
extra, changed and non-regular files. There is no permitted patch list at this
checkpoint. Keep fixes and extensions in the adapter where practical. If a
future change genuinely requires modifying upstream, document the exact patch
and its reason before changing this rule; do not regenerate the manifest merely
to make a failure disappear. Updating to a newer upstream commit is a deliberate
dependency update with a reviewed diff and fresh source-derived hashes.

## Bootstrap constraints

The original `js/main.js` defines the required import order: icons, mock data,
core app, system alerts, slideshow, Home, Calendar, Chores, Shopping, Photos,
Home controls, Agents, ambient mode and diagnostics. Each module extends shared
`window.App`; view modules retain the original `window.DATA` object. Load the
original entry before installing synchronous adapter overrides, and preserve
that data object's identity when applying a snapshot. The live adapter intercepts
mutating actions before the prototype's closure handlers can modify local rows.
Its Undo resolves the current authoritative row by ID and sends a new desired
value, so it does not depend on preserving individual row-object identities.

The core registers `DOMContentLoaded` and starts once; an import after that event
requires explicitly starting it once. Its original startup selects the 3:18 PM
demo clock. Live setup uses the real household clock and authoritative rows.
Original generated IDs are sequential; live additions need unique IDs rather
than restarting those counters after every reload.

The original CSS order is `tokens.css`, `base.css`, then Home, Calendar, Tasks,
Shopping, Photos, Control, Agents and Ambient styles. The display scales its
1280×800 stage to the browser viewport. Browser-only additions must account for
that stage geometry; household editor styles should not override it accidentally.

## Durable state and prototype features

With a project configured, the initial Auth gate keeps the original display
hidden until the signed-in household's snapshot arrives. A missing session shows
Sign in; it does not display the mock family as if it were live. Realtime
invalidations reload the authoritative snapshot and repaint the original views.

Live people, events, chores, shopping, supported sample device states and photo
descriptors come from that snapshot. Chore and shopping completion on the
original screens use the existing versioned `homehq_set_done` RPC; Undo sends a
new desired state. Supported sample device controls use `homehq_set_device`.
Shopping additions and quantities use the existing household-scoped metadata
writes. Actions are intercepted before the prototype changes local rows, so a
failed server write cannot appear as a successful local edit.

**Edit household** opens `editor.html`, retaining the existing metadata forms,
event creation, deletion/cleanup, account setup and photo uploads. The original
Calendar's add action routes to that editor rather than creating a local-only
event. Shopping cleanup also routes there. Photo files use the private
`homehq-photos` bucket; the editor prepares a 320×240 PNG and registers its
metadata. A Storage object alone is not a photo-list entry.

Upstream is a prototype with broader example data than this backend: weather
history, weekly chore marks/stars, photo dates/favourites, blind positions,
climate settings, scenes, cameras, media and alarm examples are not all durable
Home HQ fields. In live mode, controls without corresponding providers, including
climate, cameras, media and photo favourites, are hidden. Supplemental readings
remain visibly sample or local presentation state; they must not be presented as
a connected physical home or a successful server write. Agent usage and weather
providers remain samples.
Use household editing for supported metadata and uploads rather than inventing
new backend fields just to persist every prototype interaction.

The original `App.esc` escapes `&`, `<`, `>` and double quotes, but several
prototype labels are inserted directly into HTML. Treat live text, identifiers,
colours and image URLs as untrusted at the adapter boundary. Do not assume every
original renderer escapes a field simply because neighbouring fields do.
