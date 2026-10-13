# Contributing Home HQ

This repository is a Git fork of
[wesbos/photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard).
Its original `dashboard/`, frame tools and README are preserved. The connected
frontend reuses 29 pinned original files, verified by
`node homehq/web/tools/check-upstream.mjs`; the Supabase integration and native
device ports are additive code under `homehq/`.

The maintained SELECT-side source is
[meech-ward/select-badge/homehq](https://github.com/meech-ward/select-badge/tree/main/homehq).
[fork-source.json](https://github.com/meech-ward/photo-frame-dashboard/blob/main/homehq/fork-source.json) records the source checkpoints mirrored into
this fork. The small Tufty dependency allowlist has its own
[provenance](https://github.com/meech-ward/photo-frame-dashboard/blob/main/homehq/vendor/tufty/provenance.json), and the Chromatic build pins public MCU
source plus a reviewed platform patch. Preserve these records when updating a
copy, rather than importing whole device repositories or build output.

## An upstream contribution

Wes's [Community builds guide](https://github.com/wesbos/photo-frame-dashboard/blob/main/docs/community-builds.md) asks for **one table
row, a link to the post, and optionally a small photograph**. That is the
smallest first contribution for this multi-device project. Open it from a branch
based on current upstream `main`, adding only the community entry and optional
photo. Link this public fork so readers can deploy the Supabase backend and
native apps without making Wes's Android-frame repository maintain them.

Suggested entry text, once the public post exists:

> Wes's family dashboard on a SELECT Tufty badge and ModRetro Chromatic, sharing
> one Supabase household with per-member sign-in, Realtime and private photos.

Use the real post URL and author attribution in the table. Check current issues
and pull requests for a duplicate before opening it. The full integration could
be offered separately if Wes wants it upstream; keep a code PR focused on the
backend/device additions and their guides, with the original frontend unchanged.
No PR or social post is created by the build tools.

## Changing this integration

Start with [HOMEHQ.md](https://github.com/meech-ward/photo-frame-dashboard/blob/main/HOMEHQ.md) and [the source/porting map](HANDOFF.md).
Use the checks for the changed surface. A web or shared fixture change runs the
quick checks in HOMEHQ.md; database changes follow the declarative migration
workflow in [the backend guide](backend-README.md#declarative-changes).
Chromatic and Tufty behavior use their platform-specific checks and acceptance
guides. Document hardware results separately from host tests.

Commit source, migrations, lockfiles and dependency provenance. Never commit
populated environment files, Wi-Fi credentials, refresh tokens, user photos,
device state, backups, toolchains or generated firmware/bytecode. Preserve vendor
license notices. The editor is the ordinary way to add household data and photos;
an operator's private project/account setup is not reusable source.
