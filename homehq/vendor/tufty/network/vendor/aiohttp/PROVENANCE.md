# Vendored MicroPython aiohttp WebSocket client

This directory carries the WebSocket portion of `micropython-lib`'s `aiohttp`
package, pinned from commit `220ca9de9af63589cf5f372dcd12d7c272e54584`
(`aiohttp` 0.0.8 candidate, MIT license).

The local patch set is deliberately generic and contains no BadgeLink or Supabase
logic. It adds:

- a whole-handshake deadline and per-read/write deadlines;
- exact HTTP Upgrade and `Sec-WebSocket-Accept` validation;
- bounded header, frame, fragmented-message and outgoing-message sizes;
- RFC 6455 control-frame, mask, RSV, opcode and fragmentation checks;
- observable PING/PONG controls with automatic PONG replies;
- a client-initiated ping timer with a pong deadline;
- a separate idle deadline for the wait between frames;
- an awaitable `ws_connect()` whose CPython `__await__` and MicroPython
  iterator protocols both reach the same coroutine, and whose `close()`
  releases the transport;
- an optional `connect_host=` on `ws_connect()`/`connect()`: the socket goes to
  a pre-resolved address while `server_hostname` keeps SNI and certificate
  verification on the URL's own hostname, and the `Host:`/`Origin:` headers are
  unchanged. On MicroPython the name lookup happens *inside*
  `asyncio.open_connection`, it is blocking, it takes no timeout argument at any
  version, and `connect_timeout_ms` cannot interrupt it because `_wait_for`
  cannot interrupt a blocking C call — so a caller that already resolved the
  endpoint had no way to say so. It is passed to `open_connection` only when it
  differs from the hostname *and* the transport is TLS, because CPython rejects
  `server_hostname` without `ssl` and a plaintext connect-by-address wants no
  SNI. Generic and carries no BadgeLink or Supabase logic; and
- an optional `trace=` dict on `ws_connect()`/`connect()`/`_handshake()`, which
  the handshake writes its own leg spans into — `tcp_ms` (the whole
  `asyncio.open_connection`, name resolution included), `ws_tls_ms` (the one
  request write) and `upgrade_ms` (the status line and header reads) — plus the
  `phase` it is currently in;
- a BULK, bounded read of the Upgrade response head (`_read_upgrade_head`) plus a
  small leftover buffer (`_pull_exact`) for bytes a pipelining peer sends in the
  same record as the blank line; and
- deterministic transport cleanup from the async context manager.

NB-0 adds one more pinned-runtime correction at the connection boundary.  The
MicroPython `asyncio.open_connection` at firmware commit `b29530ab` creates a
non-blocking raw socket, calls `setblocking`/`connect`, wraps it, and then yields
for writability without a `try/finally`. An immediate connect error leaks before
an SSL-context proxy can see the raw socket; cancelling the writable wait loses
both otherwise-local owners. The local helper therefore mirrors those pinned
lines and publishes the raw and TLS wrapper to `WebSocketClient` as each is
created. Its cleanup catches `BaseException`, so MicroPython's `CancelledError`
closes both deterministically. The raw owner stays through the deferred TLS
write because the pinned mbedTLS binding detaches its raw socket before raising
a fatal handshake error; closing the TLS wrapper alone can then no longer reach
the PCB. The extra raw owner is dropped only after the first request write
completes. CPython still uses its public `asyncio.open_connection` and the public
aiohttp surface is unchanged.

The local timeout wrapper also retains and awaits the concrete child task on
every exceptional exit. This is not redundant on the pinned scheduler:
externally cancelling `wait_for_ms` cancels its private runner and re-raises
before that runner has driven the socket coroutine's cleanup. Driving the known
child to terminal is what makes service teardown safe before a new event loop
replaces the global I/O queue.

Why `trace=` cannot be done outside this file, since that is the test every
local patch has to pass. From the outside a handshake is one `await` and one
number, and on MicroPython the legs inside it are not comparable costs: the
name lookup happens *inside* `open_connection`; the transport is wrapped with
`do_handshake_on_connect=False`, so the **first positive write carries the
entire TLS handshake** (measured on this hardware as a single CPU-bound
820–903 ms certificate-verify flight); and the Upgrade reads are two bounded
round trips. A caller can bracket `ws_connect()` and learn the sum, which is
what the badge had — one `push_moment ms=2413` line for a 2,252–2,436 ms
rendered frame — and no amount of caller-side timing can split it.

⚠ **"THE UPGRADE READS ARE TWO BOUNDED ROUND TRIPS" WAS FALSE UNTIL 2026-08-26,
and believing it is how the defect below survived review.** The head was read one
byte at a time (`_readline_bounded`), each byte in its own `_wait_for`, so a
~300-byte 101 response was ~300 `create_task`s and ~300 forced scheduler yields.
MicroPython's `Stream.read` yields to the I/O queue on every call whether or not
the bytes are already buffered, so the count is a property of the loop and not of
the network.

A caller that awaits the whole handshake inside one `run_until_complete` absorbs
that — it measured **1,322–1,619 ms** on real hardware, which reads as a slow
network and was scheduler churn. A caller that PARKS the handshake as a task a
rendered frame advances a bounded number of steps at a time cannot: on three
hardware boots the parked path recorded `upgrade_ms=0` and never sent a
`phx_join`, and given a 20,000 ms deadline instead of 5,000 one sat in this leg
for **14,651 ms** and finished nothing. Same badge, same AP, same server, minutes
apart from four blocking-path boots that joined.

`_read_upgrade_head` reads the head in bulk instead: one `read` per arriving
record, bounded by `max_header_size`, so the cost tracks records rather than
bytes. Each ask is capped at `UPGRADE_READ_CHUNK` (512 B) — MicroPython's stream
`read(n)` sizes its buffer from `n`, so asking for the whole 8 KB cap would put a
large transient allocation in a rendered frame where the per-byte loop asked for
one byte. A real 101 response is ~180–350 bytes, so a normal handshake is still
one await; the cumulative bound is unchanged. **The reason is contiguity, not
size:** this badge measures ~8 MB free, and on it a 384,768 B allocation has
failed with 7,265,280 B free (`docs/engineering-findings.md`), so the cost of a
repeated multi-KB transient is what it does to the largest available block over
thousands of handshakes.

**The de-wrapping that is NOT the fix, recorded because it is the tempting one.**
Hoisting `_wait_for` out of the per-byte loop cuts ~3 run-queue hops per byte to
~1 and changes nothing that matters: pinned `Stream.readexactly` yields
`core._io_queue.queue_read` on EVERY call, buffered or not, so the read still
costs about one rendered frame per byte and still loses to a 5,000 ms
`connect_timeout_ms`. The arm would look identical (`upgrade_ms=0`,
`phase=upgrade`, `TimeoutError`) and the lane would conclude the mechanism was
refuted. The yield COUNT is the defect, so only a bulk read fixes it. The unbounded-`readline` hazard the per-byte loop existed to prevent is
still prevented — nothing past the cap is read into memory, and a peer that never
sends the blank line is refused. Generic, no BadgeLink or Supabase logic, and
reducible upstream on its own merits: it is faster on every path, and it is the
only shape a cooperatively-pumped client can use at all.

One consequence worth stating because a bulk read can get it wrong where a
per-byte read could not: bytes after the blank line belong to the FRAME reader.
`_read_upgrade_head` returns them and `_pull_exact` serves them before touching
the stream, so a pipelining peer's first frame is not corrupted.

The patch is deliberately generic: the dict is the **caller's**, this module
only ever writes those four keys and never reads one back, no branch anywhere
depends on it, and `trace=None` is byte-identical to the code before it. The
`phase` is set *before* each leg and the span *after* it, so a handshake that
`connect_timeout_ms` cancels mid-leg leaves a record naming the leg it died in
with that leg's span still zero — a partial record rather than no record, which
is the property an operator reading one line needs. A fixed shape (every key
present from the start) is the caller's job, not this module's.

Two notes on the ping timer, because both are deliberate departures:

- **The caller drives it.** `service_heartbeat()` sends a ping when one is due
  and raises `WebSocketLivenessError` when a pong is overdue; there is no
  background task. CPython aiohttp's `heartbeat=` argument schedules its own
  callbacks, which on a badge would be an invisible per-frame cost with an
  invisible lifetime. The equivalent upstream commit would keep the same state
  machine and add the task only where an event loop owns the client.
- **Control frames are bounded by RFC 6455's 125 bytes, not by
  `max_frame_size`.** That cap is an application-payload bound; applying it to
  control frames left a client with a small cap unable to answer a legal server
  PING, which is a defect rather than hardening.

`idle_timeout_ms` splits the deadline for the first two bytes of a frame from
`io_timeout_ms`, which still governs the rest of it. One `io_timeout_ms` for
both made a subscription's normal silence indistinguishable from a stalled peer,
so an idle client tore its own connection down. It defaults to `io_timeout_ms`
(no behavior change for existing callers); `None` waits indefinitely and leaves
liveness to the ping timer.

`ws_connect()` is now awaitable as well as an async context manager, matching
CPython aiohttp: an event-driven client cannot scope its socket to a `with`
block. Its `close()` now releases the transport too, again as CPython aiohttp
does, so the awaitable form has one honest teardown call.

The pinned MicroPython runtime does not invoke ``__await__`` on the context
manager wrapper and exposes its native coroutine as a generator with
``__next__`` but no visible ``__await__``. The wrapper therefore implements
``__iter__`` and returns that generator directly on MicroPython, while retaining
the ordinary coroutine ``__await__`` delegation on CPython. Without the iterator
arm, the first physical Realtime open fails before DNS or TLS with
``TypeError: '_WSRequestContextManager' object isn't iterable``; the polling
baseline remains healthy, which is why fixture-only integration did not expose
the half-working install.

Reconnect policy is deliberately NOT here: `network/badge/ws_backoff.py` holds
it, because a retry schedule is not part of an aiohttp WebSocket session and
would not reduce into an upstream commit.

The public `ClientSession().ws_connect(...)` and `ClientWebSocketResponse` shape is
kept so the changes can be reduced into upstream reviewable commits. The vendored
copy intentionally contains only the WebSocket client surface used by the badge;
HTTP request helpers remain in the separately pinned upstream dependency.
