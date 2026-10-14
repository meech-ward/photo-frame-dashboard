# Native two-photo cache

The cache has host checks and a development hardware acceptance run covering
private photos, offline restoration, restart and logout. The [platform guide](README.md)
states the tested baseline and remaining limits. Host tests never open a device
or write physical flash.

## Runtime data boundary

The [build/install guide](README.md) describes application-only **firmware deployment**:
write the selected application image at `0x10000`, preserving bootloader,
partition table, PHY, factory settings, FPGA, cartridge and eFuses. Runtime
Home HQ already stores its own configuration/session/cache in NVS. The requested
badge photo-cache parity uses these app-owned runtime data ranges:

| Slot | Start | Exclusive end | Capacity |
| --- | --- | --- | --- |
| 0 | `0x110000` | `0x115000` | 20,480 bytes |
| 1 | `0x115000` | `0x11a000` | 20,480 bytes |
| Staging metadata | `0x11a000` | `0x11b000` | 4,096 bytes |
| Staging PNG payload | `0x11b000` | `0x16b000` | 327,680 bytes |
| PNG staging | `0x11a000` | `0x16b000` | 331,776 bytes |

Staging has one 4 KiB header sector and at most 320 KiB of PNG payload. The
combined thumbnail/staging range is 364 KiB; it lies entirely within the
original backup's verified blank tail and does not overlap a declared partition.

USB firmware deployment still writes only the application at `0x10000`.
Each helper stays within its own fixed range. Neither alters/registers partitions
or uses a filesystem. Both keep the SDK dangerous-write guard enabled.

The expected 4 MiB flash layout declares only NVS `0x9000/0x6000`, PHY
`0xf000/0x1000`, and factory `0x10000/0x100000`. Before first installation,
retain a full backup and verify the proposed cache/staging range is unused.
The development device's range was blank before Home HQ; a different device's
contents must be checked independently.

Each cache operation refuses unexpected flash size, enabled flash encryption,
any partition-layout change or overlap. Before first ownership is recorded,
both complete slots must be blank or have this module's valid fixed header.
Unknown bytes cause refusal without erasure. A tiny `hqphotos/claimed` NVS flag
is committed before the first erase. It permits recovery of our own torn write
after restart, when the payload exists but its final header does not. Logout
retains this ownership flag; it contains no identity or photo fields.

## Format and failure behavior

Each slot holds a 256-byte header followed by exactly 18,432 bytes of canonical
128×72 RGB565 little-endian pixels. The header binds the full bounded Auth user
ID and exact household UUID/SHA-256 PNG path, dimensions, format, length,
sequence, pixel CRC32 and header CRC32. It contains no credentials. Load requires
an exact user/path match and validates the payload CRC before returning success.

Save receives an already validated decoded frame owned by the worker. It reads
both prior headers successfully before choosing an invalid or older slot. It
erases only that slot, writes the pixels, reads them back to verify their CRC,
writes the header body, then writes the final four-byte commit magic. It verifies
the committed header too. Interrupted erase/payload/header writes cannot present
an incomplete image; replacement preserves the other prior slot. A failure
after a complete commit can leave a valid new slot even though Save reports
failure, which is safe to rediscover after restart.

Drop invalidates both exact headers and verifies their invalidation. Pixel bytes
remain inaccessible to cache loads until a later slot erase; no other account's
data, settings or firmware are erased. Drop failure must be retried/reported by
the service rather than acknowledged as successful clearing.

The module uses the already linked IDF flash APIs and ROM CRC32. Its isolated
Xtensa `-Os` object measured 2,720 bytes of text and one byte of BSS. Save's own
stack frame measured 848 bytes, with up to 304 additional bytes in its ownership
check, before SDK/callback frames. It allocates no image or payload copy; NVS
uses its ordinary small namespace bookkeeping. The final linked image and
physical erase latency remain integration checks.

## Worker integration contract

The public API in `src/homehq_photo_cache.h` is worker-only:

```c
bool HQ_PhotoCacheLoad(user, path, pixels, guard, context);
bool HQ_PhotoCacheSave(user, path, pixels, guard, context);
bool HQ_PhotoCacheDrop(void);
```

`guard` is mandatory and checks the captured service generation plus requested
photo epoch. User/path arguments are copied worker-owned values; they must not
borrow mutable UI rows. The helper checks the guard around reads, erasure,
payload writing, final commit and completion. A generation change after the
final guard can still race the final flash operation: account clearing must be
serialized on this same worker and generation must be checked again before
mailbox publication. Exact identity/path binding prevents another account from
loading such a late prior-account commit.

The photo module implements `HQ_PhotoRestore` and `HQ_PhotoDownload` with a
combined service-generation/photo-epoch guard. It keeps the image descriptor and
mailbox owned by LVGL. `HQ_PhotoRetireUnused(selected)` may release a mismatched
active frame only after the prior image widget has been deleted; it preserves a
matching pending result. Leaving Photos cancels the epoch before hydration while
keeping the displayed frame until successful widget deletion, so failed page
hydration retains valid pixels. `HQ_PhotoIsFallback` marks bundled sample art
even when metadata names an uncached private photo.

1. Consume a photo request on the worker even when Wi-Fi is unavailable, after
   validating it against the durable current identity and cached household.
   Allocate the existing 18 KiB destination only after the UI's Photos projection
   has released the larger page graph. Try Load before creating HTTPS/TLS/PNG
   resources. Park Realtime but retain both permanent wire slots. Recheck
   identity/epoch before ordinary photo mailbox publication.
2. On a cache miss, request consecutive ranges of at most 4 KiB, reusing one
   verified HTTPS client while responses remain complete and healthy. Validate
   206, exact Content-Range, fixed bounded total, byte count, SDK completion and
   consistent optional strong ETag. Write each fully drained response to staging
   with its retained TLS connection idle. A failed response or
   `Connection: close` destroys the client; a transient failure gets one fresh-client retry
   at the same offset. Close the final client before verifying the complete
   staged CRC/commit and allocating the frame or decoder. Read staged bytes
   into the strict PNG decoder, destroy its
   context after full PNG completion, then save canonical pixels before any
   `LV_COLOR_16_SWAP` conversion and before transferring ownership to LVGL.
   A storage failure may still display the freshly downloaded RAM frame.
3. Logout/account replacement immediately invokes existing photo epoch/RAM
   cancellation, then queues Drop on the worker ahead of another identity's
   cache work, including offline. Keep a failed clearing request pending across
   retries. Never erase flash or change an LVGL descriptor from the other core.
4. Add `bootloader_support` to the prepared main component's `REQUIRES` so the
   encryption-gate header is available. Other flash/partition/NVS/ROM CRC APIs
   are already linked. No change to deployment offsets is required.

The download API also receives the service's inactive wire-slot pointer and
capacity. Both 32 KiB wire slots remain permanently allocated: the authoritative
slot stays untouched, and only the sole network worker borrows the inactive slot
as the PNG inflate dictionary while no household HTTP operation can overlap.
Decoder cleanup never frees that borrowed memory, including errors/cancellation.
Legacy owned decoder constructors remain available for host callers.

This shape follows a physical cache miss that left 111,432 bytes free but a
largest block of 31,744 bytes, too small to re-reserve a 32,769-byte HTTP slot.
The current staged pipeline borrows that dictionary only after HTTPS cleanup.
It reserves its per-request 18 KiB destination before the approximately 11 KiB
decoder context. There is no permanent image allocation. The allocator mock
asserts neither allocation exists during HTTP transfer and injects destination
failure after cleanup; borrowed-buffer canaries and ASan detect any erroneous
free/overrun.

Account clearing is durable: Home HQ's own NVS `photo_clear` u64 is committed
with session erasure and restored on boot. The worker invalidates and verifies
all thumbnail/staging headers before committing that flag back to zero. A failed
clear remains pending across restarts/retries, disables private photo restoration/publication,
and leaves household/Auth RPCs available. The `hqphotos/claimed` region ownership
flag remains separate and intentionally survives clearing.

## Bounded PNG staging

Later corrected-header physical attempts reached HTTP200 but failed a body read:
one recorded TLS `0x7200` invalid-record observation remains causally unproved;
a subsequent TLS `0x7f00` allocation-failed observation confirmed an allocation
failure, with the final recorded minimum heap 10,812 bytes. Their causal ordering
is not established. A transport-only whole-body probe also failed at
235,880/327,680 bytes with `0x7200`, so staging alone was insufficient. Bounded
range requests separate transport lifetimes from decoding without weakening
certificate/hostname checks or changing global TLS buffers.

`homehq_photo_stage.h` exposes worker-only Begin, Write, Finish, Read and Drop.
Begin binds an exact guard/context transaction. Before first erase, the whole
staging region must be blank or have our recognized valid header; a durable
`hqphotos/staged` ownership flag is committed first. Unknown unclaimed bytes
cause refusal without erasure. Each data sector is erased lazily in 4 KiB units
as bytes arrive, with a task yield after each erase. There is no large RAM buffer.

Finish requires nonempty bounded input, rereads its payload CRC, writes a fixed
64-byte length/CRC/version header body, writes the final magic last, and verifies
that header. Read requires this live completed transaction, the identical
guard/context and bounds within its immutable length. A reboot cannot reuse a
finished staging transaction. Drop invalidates the RAM transaction and verifies
zero commit magic; account clearing invalidates both thumbnail and staging
headers under the existing durable `photo_clear` intent.

Download receives each HTTPS range into the first 4 KiB of the permanent
inactive wire slot, with one overflow byte available, before allocating any
frame, decoder context or inflate state. A healthy client remains connected
across ranges; each complete, validated response reaches flash while TLS is
idle and no response body remains unread. After all ranges, the final client
is closed and cleaned up before verified Finish, the 18 KiB frame allocation
and borrowed-dictionary decoder allocation. The decoder receives 1 KiB readback
chunks. Only full strict PNG completion allows thumbnail Save and
mailbox publication. Every phase uses the service-generation/photo-epoch guard.
Cleanup invalidates the RAM transaction and attempts verified header Drop after
success or failure; durable account clearing retries until both header ranges
are verified invalid. Encoded bytes are temporary scratch, never a reboot photo
source; invalidation does not claim secure erasure of all prior pixel bytes.

The range protocol accepts only 206 with exact `bytes start-end/total`. Total
must be positive, at most 327,680 and fixed after discovery; the final endpoint
is `min(requested_end,total-1)`. The declared HTTP length, when present, must
match that range, and received count plus the SDK complete-body indication must
agree. A 200 response, gaps/overlap, changed total, short/extra/incomplete body,
compressed encoding, duplicate/missing/oversized Content-Range or malformed
ETag aborts before that response reaches staging. The SDK ignores header-event
return values, so invalid metadata is explicitly latched and checked afterward.

A first strong quoted ASCII ETag, if present, is retained and sent as If-Match
on later ranges. Presence/absence and value remain consistent; changed or
missing validators fail closed. Each offset gets at most two attempts. Failed
or incompletely consumed responses are never reused; a transient failure retries
the same offset on a fresh verified client. A complete response carrying
`Connection: close` also retires its client before the next range. Failed
responses have not reached flash, so retry cannot append the same range twice.
There is no decoder/image allocation during these transfers, and the sole
worker does no household HTTP concurrently. Staging writes can overlap an idle
retained TLS connection, but never an unread range body. Final TLS cleanup
precedes staged CRC verification, readback and decoding on every completion,
error or cancellation path.

A completed marker binds the requested photo epoch and path when pixels enter
the mailbox. A duplicate queued request for that completed epoch returns without
another cache read, allocation or HTTP transfer. This marker uses worker-owned
request state rather than reading LVGL's active pixel pointer; path changes and
epoch cancellation invalidate it.

Private slideshow rows wait up to five minutes for matching pixels before a
12-second fallback dwell. Matching private pixels start a fresh 12-second dwell
when rendered, so an 80-request transfer is not canceled by the old timer.
Bundled/sample rows retain 12 seconds; A, manual selection and page controls
remain available. Row ID plus exact path bind this timing, and departing Photos
cancels the epoch before destination hydration while retaining valid old widgets
through a failed hydration. An accepted photo request sets the worker-busy flag
until TLS, decoder, staging and temporary pixels have been cleaned up. Reset
cancels the epoch immediately but does not clear that flag. Destination graph
hydration and snapshot polling wait for the worker to become idle, retaining the
old model and pixels without allocating projected JSON during cleanup. Up to 16
button codes are queued in order and replayed after successful hydration, so a
quick Start/Right/A sequence survives the wait without increasing the blocked
input counter. Queue overflow increments that counter rather than allocating
an unbounded input history.

The fixed stage diagnostics add 13 staging Begin, 14 staging Write, 15 verified
Finish and 16 readback. Flash-mock tests cover the complete 320 KiB boundary,
unknown bytes in every sector, claims/NVS faults, address canaries, lazy erasure
and yields, partial/silent erase/writes, CRC/header faults, cold/torn restart,
exact guard/context binding and clearing. Mailbox allocator assertions prove no
frame/context allocation before HTTP cleanup in both LVGL byte orders.

Safe `HQ photo` diagnostics contain only fixed unsigned counters and numeric
failure stages: 0 success, 1 invalid request, 2 decoder reservation, 3 auth header
buffer, 4 HTTP client/header setup, 5 verified TLS open, 6 response headers/status,
7 destination allocation/attachment, 8 body read, 9 PNG validation, 10 complete
HTTP body, 11 canceled request, 12 mailbox/late identity cancellation. They also
report the bounded HTTP status and cache hit/miss/save/save-failure/clear-failure
counts. Optional signed `tls_error`/`transport_error` fields capture the exact
SDK error handle during HTTP error/disconnect events, before cleanup, without
enabling global logs. The parser accepts exactly this scalar schema and never
records user, photo path, project or provider response text.

The Photo HTTP TX width uses the shared bounded header policy:
`max(1024, bearer_length + 32, apikey_length + 16)`. IDF 5.3 emits complete header
lines; a physical 970-byte JWT created a 994-byte Authorization line that TX512
could not emit. The SDK stopped with an unterminated request while `open()`
reported success, so header fetch timed out with no HTTP status. Dummy
970/4096/8192-byte credential tests verify fitting buffers without logging any
values; the real pinned SDK header-generator regression checks terminators and
canaries. This correction leaves TLS verification and allocation order unchanged.

## Host verification

```sh
python3 devices/chromatic/tests/test_photo_cache.py
HQ_CACHE_SANITIZE=1 UBSAN_OPTIONS=halt_on_error=1 python3 devices/chromatic/tests/test_photo_cache.py
python3 devices/chromatic/tests/test_photo_stage.py
HQ_STAGE_SANITIZE=1 UBSAN_OPTIONS=halt_on_error=1 python3 devices/chromatic/tests/test_photo_stage.py
HQ_RANGE_SANITIZE=1 UBSAN_OPTIONS=halt_on_error=1 python3 devices/chromatic/tests/test_photo_range.py
```

The cache mocks enforce the 40 KiB thumbnail range; staging mocks independently
enforce its 324 KiB metadata/payload range. Both model NOR
one-to-zero writes. Tests cover cold boot, two-slot eviction, exact account/path
binding, malformed metadata/payload CRCs, unknown first-use data, layout/security
rejection, NVS ownership failures, read failures, silent write failures, partial
erase/payload/header/commit at 44 fault points, generation cancellation and
logout invalidation. Bytes outside the app-owned range are checked unchanged.


Range helpers cover 80 full chunks, small/final responses, exact endpoints,
changed totals, overflow, malformed separators and bounded strong ETags under
ASan/UBSan. The real photo mailbox covers actual 59,737-byte, synthetic 1,500-byte
and exact 327,680-byte PNGs, two-attempt transient recovery, short/extra bodies,
duplicate/range/encoding/ETag failures and epoch cancellation. A healthy 80-range
transfer uses one client; a stale connection retries with a fresh client, and
`Connection: close` creates 80 clients. Tests require complete responses before
staging writes and final TLS teardown before Finish/decoding, and verify that
completed-epoch duplicates perform no allocation, HTTP or cache read. Both LVGL
byte orders pass. Native UI host tests preserve the old model/pixels, forbid
View/Poll projection allocation while the worker is busy and replay physical
Start/Right/A into Calendar/event without increasing blocked inputs. These are
host checks; the report owns native outcomes and remaining physical
cache/latency gates.
