# Private setup for the new free DevRel Home HQ project

`tools/hosted.py` and `tools/check_hosted.py` accept only a root-verified new
project in the free DevRel organization `yuueonycfgiwijatkqyv`. They cannot
create a project, change a plan, discover devices or select another organization.
Use the pinned project-local Supabase CLI **2.120.0** and the existing default
management login. No checkout is linked: every management call carries the exact
verified project reference and an explicit Home HQ work directory.

The operator creates a regular **0600** `.hosted.private.json`, containing:

```json
{
  "project_ref": "THE_NEW_PROJECT_REF",
  "organization_id": "yuueonycfgiwijatkqyv",
  "project_name": "Home HQ",
  "plan": "free",
  "verified_new_project": true
}
```

Record those assertions only after checking the newly created project's actual
organization and plan. `database_password` is an optional private field when
needed by CLI database operations; `publishable_key` is populated by the `keys`
command or supplied privately by the operator. The HTTPS URL is derived from the
ref; a URL in metadata cannot redirect requests to another project.

From `homehq/`, with the same new ref and metadata path for every command:

```sh
python3 tools/hosted.py config-diff --metadata .hosted.private.json --project-ref NEW_REF
python3 tools/hosted.py config-push --metadata .hosted.private.json --project-ref NEW_REF
python3 tools/hosted.py db-plan --metadata .hosted.private.json --project-ref NEW_REF
python3 tools/hosted.py db-apply --metadata .hosted.private.json --project-ref NEW_REF
python3 tools/hosted.py keys --metadata .hosted.private.json --project-ref NEW_REF
python3 tools/hosted.py owner --metadata .hosted.private.json --project-ref NEW_REF
python3 tools/check_hosted.py --metadata .hosted.private.json --project-ref NEW_REF
```

Add `--homehq-root /absolute/path/to/homehq` when running candidate scripts from
another checkout. This must point to the parent source with its generated and
locally verified migrations. The local runtime helper's isolated `SUPABASE_HOME`
is deliberately removed for hosted CLI calls so its empty login store cannot
override the existing management login.

Preview commands save raw CLI output and source hashes to ignored, **0600**
`.hosted.review.private.json`. Review the relevant preview before applying it.
Apply refuses when the config/migration/seed hashes differ from the preview.
Config push uses the source declarations; database push includes the idempotent
private-bucket seed and skips Vault. No DB password is passed on the command line,
no debug output is forwarded, and no privileged project key is requested with
`--reveal`, retained by these scripts or used by a client.

The existing config intentionally keeps the companion's local origin on port
5173 and disables email confirmations for this private demo. Change its Site URL,
redirects and signup/email settings deliberately before publicly hosting the
companion. [Configuration push](https://supabase.com/docs/reference/cli/supabase-config-push)
and [database dry runs](https://supabase.com/docs/reference/cli/supabase-db-push)
are separate steps: configuration alone does not deploy SQL migrations.

`owner` generates one ordinary password Auth account and calls its invoker
`homehq_seed_demo()` RPC. It saves `.hosted.owner.private.json` (**0600**) with
`project_ref`, `url`, `publishable_key`, `email`, `password`, `user_id`,
`owner_session` and `badge_session`. A retry signs in with the saved credentials
instead of creating another account. The badge session comes from a separate
password sign-in for the same owner, so browser refresh rotation cannot consume
the badge's token. The generated email is for this private demo; it is not a
recovery inbox. No Auth admin endpoint or service-role key is used.

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

## Verified deployment

On 2026-10-12, the new Home HQ project `cicgysjddsjsbgofpxwr` was created in the
verified Free DevRel organization, using default compute with no size or high
availability flags. Its six generated migrations and private-bucket seed were
applied after preview review. An exact-ref database read confirmed eight RLS
tables, all exposed RPCs as invokers, no authenticated `TRUNCATE` or direct home
revision update, and the private 2 MiB bucket.

The separate candidate native stack passed 73 SQL checks and 26 live assertions
after a clean reset, including the correction for Supabase's inherited default
authenticated table privileges. The hosted native smoke passed 15 assertions,
including real TLS REST, private database Broadcast, owner Auth rotation,
anonymous denial, desired-value retry and a private PNG above 256 KiB. Cleanup
restored the checklist edit and deleted its uniquely hashed upload. Badge config
and the separate session were prepared privately with no Wi-Fi fields; physical
hardware validation remains a separate gate.
