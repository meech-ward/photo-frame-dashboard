# Contributing Home HQ

This repository is a Git fork of
[wesbos/photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard).
Its original `dashboard/` and frame tools are preserved; the root README adds a
Home HQ entry note above the original frame instructions. The connected
frontend reuses 29 pinned original files, verified by
`node homehq/web/tools/check-upstream.mjs`; the Supabase integration and native
device ports are additive code under `homehq/`.

Develop and submit Home HQ changes in this public fork.
[fork-source.json](fork-source.json) records the original dashboard and device
dependencies. The small Tufty dependency allowlist has its own
[provenance](vendor/tufty/provenance.json), and the Chromatic build pins public MCU
source plus a reviewed platform patch. Preserve these records and license
notices when updating a dependency. [badge.select/guides](https://badge.select/guides)
is the stable entry point for SELECT setup and source downloads.

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

Start with [HOMEHQ.md](../HOMEHQ.md) and [the source/porting map](HANDOFF.md).
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

Run `python3 homehq/tools/check_public.py` before sharing changes. It checks
tracked files for private source/config paths and missing relative Markdown
links. Add `--starter path/to/homehq-starter.zip` to check a generated bundle
too. This offline check complements review of dependency URLs and credentials;
it does not verify remote availability or establish that arbitrary files are safe.

## License notices

Keep the component-specific notices with their source: ModRetro's MCU baseline
and patch use GPL-3.0, pngle and the upstream aiohttp client identify MIT, and
Mona Sans includes its OFL notice. The referenced `supabase-micro` SDK is MIT.
At the revisions recorded in this fork, Wes's dashboard repository and the
public SELECT source do not include a repository-wide license. This fork does
not assign a new blanket license to their code; that remains an upstream
clarification for broader reuse.
