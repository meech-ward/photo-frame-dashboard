# Distinct account acceptance

`check_members.py` checks the schema and canonical badge transport against an
isolated local Supabase stack. It accepts only loopback API metadata and uses
fresh ordinary Auth signup sessions, never a privileged API key. It creates an
owner and three members, links each to one existing demo person through the
owner RPC, and adds an unrelated account for deny cases.

From the repository root:

```sh
python3 homehq/tools/local.py start
python3 homehq/tools/local.py reset
python3 homehq/tools/local.py test
python3 homehq/tools/check_members.py --report /private/tmp/homehq-members-result.json
```

The 23 wire assertions cover four distinct identities in one household, owner-only
membership linking, assignment and database-stamped creator/completer fields,
replay preserving the original completer, private photo sharing and unrelated
account denials. Four actual native-transport clients join one authorized private
Broadcast topic. A member's edit must trigger hints and fresh snapshots on all
four clients. A different member undoes it. A disconnected member then rejoins
and reads the edit missed while offline from durable database state.

The probe deletes only its freshly created household/photo and signs out its
fresh sessions with local scope. Random local Auth accounts remain until the
isolated development stack is destroyed. Credentials stay in memory; the report
contains only counts, source hash, revisions and timing.

The local run on 2026-10-12 passed all 23 assertions, 121 SQL tests and the prior
26 wire assertions. The complete four-member snapshot was 28,213 bytes under the
32 KiB badge bound. Local private joins took 79.5 ms, the first member edit reached
all four authoritative snapshots in 79.2–96.3 ms, and offline catchup took 144.9 ms.
These are one local host run, not cloud or MicroPython latency guarantees.

For an explicitly configured hosted project and existing member credentials, use the
[`check_family.py --member-files` procedure](FAMILY-CHECK.md). Four protocol clients
prove real Auth/Realtime/Storage behavior, not four physical badges' radios,
screen appearance, flash durability or button handling.
