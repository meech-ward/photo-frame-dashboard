# Home HQ data contract

Version 1 with additive household fields. `owner_id` remains the stable household
UUID, preserving existing rows and photo paths. `homehq_members` maps an ordinary
Auth `user_id` to one household and `person_id`. Only the owner-authorized
`homehq_link_member(p_email,p_person_id)` RPC changes this mapping. Each browser
or badge signs in separately; there are no custom minted device JWTs.

`homehq_snapshot()` is an authenticated, SECURITY INVOKER RPC. Its complete
response is bounded to 32 KiB, with a seven-day agenda and at most 64 events.
All timestamps are Unix seconds; text ids preserve Wes's example ids.

```json
{
  "schema_version": 1,
  "revision": 1,
  "server_time": 1791746280,
  "home": {"id":"HOUSEHOLD_UUID", "title":"Home HQ", "timezone":"America/Toronto", "utc_offset_minutes":-240, "demo":true},
  "viewer": {"user_id":"AUTH_USER_UUID", "person_id":"alex", "is_owner":true},
  "members": [{"user_id":"AUTH_USER_UUID", "person_id":"alex"}],
  "people": [{"id":"alex", "name":"Wes", "color":"#2D5BFF", "home":false, "status":"Driving home", "eta":12}],
  "events": [{"id":"e7", "start":1791747900, "end":1791750600, "title":"Piano lesson", "people":["otto"], "travel":12, "loc":"Ms. Park's Studio", "notes":"Bring the blue theory book.", "all_day":false}],
  "chores": [{"id":"c1", "who":"otto", "routine":"after", "title":"Practice piano", "stars":2, "done":false, "done_by":null, "version":1}],
  "shopping": [{"id":"g1", "name":"Bananas", "category":"Produce", "store":"FreshCo", "quantity":1, "note":"", "done":false, "version":1}],
  "photos": [{"id":"p1", "path":null, "asset":"assets/photo-coast.png", "caption":"On this day", "place":"Tofino, BC"}],
  "weather": {"temp":15, "label":"Overcast", "high":17, "low":8, "summary":"Rain from 4 PM", "sample":true},
  "home_status": {"temperature":20.5, "lights_on":5, "locked":true, "sample":true},
  "agents": [{"id":"codex", "name":"Codex", "color":"#10A37F", "sample":true, "meters":[{"label":"Session", "used":88, "reset_minutes":38},{"label":"Weekly", "used":57, "reset_minutes":7320}], "week":[3.1,2.4,5.2,4,2.2,1.1,4.6]}]
}
```

People retain ids alex/jordan/maya/otto and labels Wes/Claudia/Buzzsaw/Skidmark.
Colours are blue/pink/green/amber from the original. Routine ids are morning,
after, evening. A chore whose `who` is `any` requires `done_by` on completion.
Data is bounded before it reaches a badge; the UI never interprets provider code.

`homehq_set_done(p_kind, p_id, p_done, p_version, p_done_by DEFAULT NULL)` uses
`p_kind = 'chore' | 'shopping'`. It sets the desired boolean, never toggles it.
Return `{status:'saved'|'conflict', item:<authoritative row>, revision:<integer>}`.
An already matching desired state is converged success, including a retry after
the response was lost. A stale contradictory version is a conflict, not an overwrite.

Private Broadcast topic `homehq:<home.id>`, event `changed`, payload
`{section:'chores', revision:2}`. Browser uses normal supabase-js channels; badge
uses the existing generic Realtime client. Join/rejoin and invalidation schedule
a snapshot fetch. Several hints coalesce; durable tables remain authoritative.
No client Broadcast send privilege is needed. Membership also authorizes private
Storage reads/uploads in the existing household folder. An unrelated Auth account
cannot access the household, topic or photos. `homehq_seed_demo(false)` returns
the existing shared home for members; only its owner can explicitly reset it.

Checklist rows additionally carry nullable `created_by_user_id` and
`completed_by_user_id`. A trigger derives these from `auth.uid()` for both RPCs
and direct Data API edits; caller-supplied attribution is overwritten. Matching
desired-state retries retain the original completion actor, metadata edits cannot
claim it, and undo clears it. `done_by` remains the person credited with chore
stars; it can differ from the Auth account that actually helped.

The private Storage bucket is `homehq-photos`. Objects are 320x240 non-interlaced
PNG with paths `<owner UUID>/<content hash>.png`. Bundled sample artwork keeps
the offline first launch complete. Uploading a photo replaces the sample metadata.
The prepared PNG is at most 327,680 bytes, exactly 320×240, 8-bit RGB/indexed/RGBA
and non-interlaced. Native downloads validate IHDR before passing it to the codec.

Events may include `start_offset_minutes` and `end_offset_minutes`, computed
from the home's IANA timezone at each endpoint. The badge uses those optional
offsets to render a week crossing daylight-saving time; elapsed countdowns use
UTC timestamps. Older fixtures fall back to the snapshot's current home offset.

Native service seam: `snapshot() -> dict`, `status() -> {state,pending}`,
`command(dict)`, `poll(now_ms) -> changed`. Commands use
`{kind:'chore'|'shopping', id, done, version, done_by?}`. `photo_path(photo)` returns
the safe local/bundled image path. Drawing and button handling do no network I/O.

`homehq_seed_demo(p_replace boolean DEFAULT false)` populates the owner's sample
rows and returns a snapshot. Ordinary initialization preserves existing rows.
Sample cards (weather, home, agent usage) remain labelled as sample data.

The snapshot also includes `devices`, sample light/lock/garage rows with
`id,name,room,type,version,sample:true` and typed state (`on,level`, `locked`, or
`state:'open'|'closed'`). `homehq_set_device(p_id,p_state,p_version)` returns the
same saved/conflict envelope as checklist writes. The native command is
`{kind:'device',id,state:{on:true},version:1}`. This controls simulated devices in
Supabase; a future real provider must report observed state before claiming the
physical device changed. No simulated data is presented as a real home reading.
