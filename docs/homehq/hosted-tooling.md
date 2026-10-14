# Optional hosted deployment helpers

The ordinary [Supabase CLI setup](backend.md#deploy-to-your-own-supabase-project)
is the default deployment path. `tools/hosted.py` adds saved previews and explicit
target checks for developers running hosted acceptance. It never creates,
upgrades or chooses a project. Every command requires `--project-ref` to match
the supplied metadata; the HTTPS endpoint is derived from that reference.

Use the pinned project-local Supabase CLI **2.120.0** with your management login.
Create an ignored, regular mode-0600 `.hosted.private.json` containing:

```json
{"project_ref": "YOUR_PROJECT_REF"}
```

`database_password` is optional when needed by CLI database operations.
`publishable_key` is populated by the `keys` command or supplied in the file.
Keep all populated metadata, reviews and account files out of Git and exports.

From the repository root, with the same project reference and metadata path for every command:

```sh
python3 tools/hosted.py config-diff --metadata .hosted.private.json --project-ref YOUR_PROJECT_REF
python3 tools/hosted.py config-push --metadata .hosted.private.json --project-ref YOUR_PROJECT_REF
python3 tools/hosted.py db-plan --metadata .hosted.private.json --project-ref YOUR_PROJECT_REF
python3 tools/hosted.py db-apply --metadata .hosted.private.json --project-ref YOUR_PROJECT_REF
python3 tools/hosted.py keys --metadata .hosted.private.json --project-ref YOUR_PROJECT_REF
python3 tools/hosted.py owner --metadata .hosted.private.json --project-ref YOUR_PROJECT_REF
python3 tools/check_hosted.py --metadata .hosted.private.json --project-ref YOUR_PROJECT_REF
```

Add `--homehq-root /absolute/path/to/homehq` when running candidate scripts from
another checkout. This must point to this project's source directory with its
generated and locally verified migrations. The local runtime helper's isolated `SUPABASE_HOME`
is deliberately removed for hosted CLI calls so its empty login store cannot
override the existing management login.

Preview commands save raw CLI output and source hashes to ignored, **0600**
`.hosted.review.private.json`. Review the relevant preview before applying it.
Apply refuses when the config/migration/seed hashes differ from the preview.
Config push uses the source declarations; database push includes the idempotent
private-bucket seed and skips Vault. No DB password is passed on the command line,
no debug output is forwarded, and no privileged project key is requested with
`--reveal`, retained by these scripts or used by a client.

The existing config intentionally keeps the dashboard's local origin on port
5173 and disables email confirmations for local demo setup. Change its Site URL,
redirects and signup/email settings deliberately before publicly hosting the
dashboard. [Configuration push](https://supabase.com/docs/reference/cli/supabase-config-push)
and [database dry runs](https://supabase.com/docs/reference/cli/supabase-db-push)
are separate steps: configuration alone does not deploy SQL migrations.

`owner` generates one ordinary password Auth account and calls its invoker
`homehq_seed_demo()` RPC. It saves `.hosted.owner.private.json` (**0600**) with
`project_ref`, `url`, `publishable_key`, `email`, `password`, `user_id`,
`owner_session` and `badge_session`. A retry signs in with the saved credentials
instead of creating another account. The badge session comes from a separate
password sign-in for the same owner, so browser refresh rotation cannot consume
the badge's token. The generated email is for a disposable acceptance account;
it is not a recovery inbox. Create ordinary household accounts through the editor
for normal use. No Auth admin endpoint or service-role key is used.

The hosted probe signs in two temporary sessions for that existing demo owner.
It drives the **actual native transport on CPython over hosted TLS**, verifies a
private Broadcast after a real mutation, reads the durable snapshot, rotates its
own Auth session and uploads/downloads a valid private PNG larger than 256 KiB.
Anonymous RPC and Storage reads must be denied. It restores the temporary
checklist state using its returned version and deletes only its uniquely hashed
PNG; a competing change makes cleanup fail rather than overwriting new state.
It does not reset a home, create more users or consume the saved badge session.
The prior local SQL/cross-owner tests remain the full authorization gate; this
hosted smoke probe does not claim physical badge performance or certificate proof
on MicroPython.

Offline guard tests need no project or network:

```sh
python3 -B tools/test_hosted_safety.py
```
