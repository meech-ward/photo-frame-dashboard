"""Supabase Realtime client: connect, join, heartbeat, token refresh, rejoin.

Layer 2 of the P6 three-layer rule. Pure asyncio over an INJECTED WebSocket
transport — no Badgeware, no BadgeLink, no aiohttp import — so it runs on any
MicroPython target and could become the `realtime` module a Supabase
MicroPython client is missing.

Transport contract. `ws_connect(url)` is awaited and must return an object with:

    await response.send_str(text)
    await response.receive()            -> object with .type (RFC 6455 opcode)
                                           and .data
    await response.close()              -> releases the transport
    await response.service_heartbeat()  -> optional WS-level ping timer

Why connecting is explicit and never happens inside `service()`. A TLS
handshake on this badge blocked one cooperative update for 735 ms (P4 pre-gate
report, 2026-08-17) from inside a C call that does not yield, so wrapping it in
a task does not hand the frame loop back. The brief's directive is to handshake
only at session start or at a scheduled tolerant moment. `service()` therefore
never opens a socket: it reports the drop, schedules the next attempt with the
injected backoff, and the caller calls `connect()` when it can afford the stall.

`service()` is the pump. It returns immediately, having read at most one frame
and run the timers, so a caller can drive it once per rendered frame. A heartbeat
deadline is the one place it reads more: before calling the socket dead it drains
the frames already in hand, bounded by `HEARTBEAT_DRAIN_ROUNDS`, because a reply
that arrived and was never looked at must not cost a live connection.

`backoff_reset` — REVIEW FINDING F4, decided by P6-L3 (2026-08-21). phoenix.js
resets the reconnect backoff when the socket OPENS, and this client shipped that
parity as `BACKOFF_RESET_ON_OPEN`; the layers 1-2 planning review left the choice
to layer 3 because it shapes a fleet, not a client. The option is additive and
the default is unchanged, so nothing that already depended on parity moved. What
layer 3 passes, and why, is written up in
`badgelink/badge/badgelink/pushlink.py`: an open socket that never joins buys a
doorbell exactly nothing, so crediting it as success turns "opens then fails to
join" into a tight retry loop at attempt-1 delay for every badge that shares the
condition — and at 800 badges the conditions that produce it (a saturated
Realtime shard, an authorization failure, a captive portal that completes the
Upgrade) are precisely the correlated ones.
"""

import asyncio

from .phoenix import (
    CHANNEL_CLOSED,
    CHANNEL_ERRORED,
    CHANNEL_JOINED,
    CHANNEL_JOINING,
    CHANNEL_LEAVING,
    EVENT_ACCESS_TOKEN,
    EVENT_BROADCAST,
    EVENT_CLOSE,
    EVENT_ERROR,
    EVENT_HEARTBEAT,
    EVENT_JOIN,
    EVENT_LEAVE,
    EVENT_REPLY,
    EVENT_SYSTEM,
    MAX_REASON_CHARACTERS,
    PHOENIX_TOPIC,
    STATUS_OK,
    VSN,
    Channel,
    ProtocolError,
    encode,
    decode,
    decode_binary,
)


try:  # MicroPython
    from time import ticks_add as _ticks_add
    from time import ticks_diff as _ticks_diff
    from time import ticks_ms as _ticks_ms
except ImportError:  # CPython, for the host test lane
    from time import monotonic as _monotonic

    def _ticks_ms():
        return int(_monotonic() * 1000)

    def _ticks_add(value, delta):
        return value + delta

    def _ticks_diff(later, earlier):
        return later - earlier


SOCKET_CLOSED = "closed"
SOCKET_OPEN = "open"

KIND_DISCONNECTED = "disconnected"
KIND_JOINED = "joined"
KIND_JOIN_ERROR = "join_error"
KIND_CHANNEL_ERROR = "channel_error"
KIND_BROADCAST = "broadcast"
KIND_SYSTEM = "system"
KIND_UNHANDLED = "unhandled"

WS_TEXT = 1
#: A vsn=2.0.0 socket carries DB-published Broadcasts in a BINARY frame, not a
#: text one. See `_handle_binary` and `phoenix.decode_binary`.
WS_BINARY = 2
WS_CLOSE = 8
WS_PING = 9
WS_PONG = 10

# What one read attempt did, since "nothing had arrived" and "the socket is
# gone" need different answers from the same call.
FRAME_NONE = 0
FRAME_HANDLED = 1
FRAME_DROPPED = 2

#: Reset the socket reconnect backoff the moment the WebSocket opens. This is
#: phoenix.js parity and the historical default.
BACKOFF_RESET_ON_OPEN = "open"
#: Reset it only once a channel has actually JOINED on this socket. Chosen by
#: P6-L3 for the 800-badge fleet; see the module note above.
BACKOFF_RESET_ON_FIRST_JOIN = "first_join"
BACKOFF_RESET_MODES = (BACKOFF_RESET_ON_OPEN, BACKOFF_RESET_ON_FIRST_JOIN)

MIN_HEARTBEAT_MS = 1000
MAX_HEARTBEAT_MS = 25000
# How many frames a heartbeat deadline may drain before it gives up and calls
# the socket dead. Bounded because the pump owes the caller a rendered frame:
# an unbounded drain would let a flooding peer own the loop.
HEARTBEAT_DRAIN_ROUNDS = 8
MIN_JOIN_TIMEOUT_MS = 1000
MAX_ACCESS_TOKEN_CHARACTERS = 4096
MAX_APIKEY_CHARACTERS = 512
# Spelled out rather than str.isalpha(): CPython would accept accented letters
# there and MicroPython would not, and the host lane must test what ships.
URL_SAFE_CHARACTERS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def _require_url_safe(value, label, maximum):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError("invalid {}".format(label))
    for character in value:
        if character not in URL_SAFE_CHARACTERS:
            raise ValueError("{} must be URL-safe".format(label))
    return value


def validate_access_token(value):
    """Reject the token shapes Realtime accepts silently and then ignores."""

    if not isinstance(value, str) or not value:
        raise ValueError("access token must be a non-empty string")
    if len(value) > MAX_ACCESS_TOKEN_CHARACTERS:
        raise ValueError("access token is implausibly long")
    for character in value:
        if ord(character) < 33 or ord(character) > 126:
            raise ValueError("access token must be printable ASCII without spaces")
    if value.startswith("sb_"):
        # Realtime ignores sb_-prefixed strings in an access_token without
        # complaining, so a publishable key passed here looks like it worked
        # and then authorizes nothing.
        raise ValueError("access token must be a JWT, not a publishable key")
    return value


class RealtimeEvent:
    def __init__(self, kind, topic=None, event=None, payload=None, reason=None):
        self.kind = kind
        self.topic = topic
        self.event = event
        self.payload = payload
        self.reason = None if reason is None else str(reason)[:MAX_REASON_CHARACTERS]

    def __repr__(self):
        return "RealtimeEvent({}, {}, {})".format(self.kind, self.topic, self.event)


class RealtimeClient:
    def __init__(
        self,
        url,
        apikey,
        ws_connect,
        access_token=None,
        clock=None,
        heartbeat_ms=20000,
        heartbeat_timeout_ms=10000,
        join_timeout_ms=10000,
        backoff_factory=None,
        allow_plaintext=False,
        backoff_reset=BACKOFF_RESET_ON_OPEN,
    ):
        if not isinstance(url, str) or not url:
            raise ValueError("Realtime URL is required")
        if url.startswith("ws://"):
            if not allow_plaintext:
                # A bearer token over an unverified transport is a stolen token.
                raise ValueError("plaintext ws:// needs allow_plaintext (fixtures only)")
        elif not url.startswith("wss://"):
            raise ValueError("Realtime URL must be wss://")
        if "?" in url:
            raise ValueError("pass the socket URL without a query string")
        if not callable(ws_connect):
            raise ValueError("ws_connect must be an awaitable factory")
        self.url = url
        self.apikey = _require_url_safe(apikey, "apikey", MAX_APIKEY_CHARACTERS)
        self.access_token = None if access_token is None else validate_access_token(
            access_token
        )
        self.heartbeat_ms = int(heartbeat_ms)
        self.heartbeat_timeout_ms = int(heartbeat_timeout_ms)
        self.join_timeout_ms = int(join_timeout_ms)
        if self.heartbeat_ms < MIN_HEARTBEAT_MS or self.heartbeat_ms > MAX_HEARTBEAT_MS:
            # Realtime drops a socket that has not sent a heartbeat recently
            # enough; 25 s is the documented ceiling, not a suggestion.
            raise ValueError(
                "heartbeat must be {}..{} ms".format(MIN_HEARTBEAT_MS, MAX_HEARTBEAT_MS)
            )
        if self.heartbeat_timeout_ms < 1 or self.heartbeat_timeout_ms > self.heartbeat_ms:
            raise ValueError("heartbeat timeout must be positive and at most the interval")
        if self.join_timeout_ms < MIN_JOIN_TIMEOUT_MS:
            raise ValueError("join timeout must be at least {} ms".format(MIN_JOIN_TIMEOUT_MS))
        if backoff_reset not in BACKOFF_RESET_MODES:
            raise ValueError("backoff_reset must be one of {}".format(BACKOFF_RESET_MODES))
        self.backoff_reset = backoff_reset
        self._ws_connect = ws_connect
        self._clock = clock or _ticks_ms
        self._backoff_factory = backoff_factory
        self._backoff = None if backoff_factory is None else backoff_factory()
        self.socket_state = SOCKET_CLOSED
        self._response = None
        self._receive_task = None
        self._transport_heartbeat = None
        self._channels = {}
        self._rejoin_at_ms = {}
        self._channel_backoff = {}
        self._join_token = {}
        self._ref = 0
        self._heartbeat_ref = None
        self._heartbeat_due_ms = None
        self._heartbeat_deadline_ms = None
        self._reconnect_at_ms = None
        # Has any channel joined on the CURRENT socket? Only meaningful for
        # BACKOFF_RESET_ON_FIRST_JOIN, and reset by every connect().
        self._session_joined = False
        self.connects = 0
        self.disconnects = 0
        self.joins = 0
        self.join_errors = 0
        self.heartbeats_sent = 0
        self.heartbeat_timeouts = 0
        self.messages_received = 0
        self.broadcasts_received = 0
        self.protocol_errors = 0
        # Binary frames this build has no decoder for. Non-zero means the server
        # is pushing a framing we skipped rather than a session we lost; see
        # `_handle_binary`.
        self.binary_frames_ignored = 0
        self.unknown_topic_messages = 0
        self.last_error = None

    # ---------------------------------------------------------------- setup

    def socket_url(self):
        """The full connect URL. It carries the apikey; never log it."""

        return "{}?apikey={}&vsn={}".format(self.url, self.apikey, VSN)

    def safe_url(self):
        """The same URL with the key redacted, for logs and reports."""

        return "{}?apikey=<redacted>&vsn={}".format(self.url, VSN)

    def channel(self, topic, private=True, replay_since_ms=None, replay_limit=None):
        """Register a topic: joined by the next connect(), or the next service().

        Registering on a live socket used to promise an immediate join and hand
        back a channel that stayed CLOSED forever, because `_run_timers` joins a
        closed channel only when it has a due deadline. Due-now is that deadline.
        This stays synchronous on purpose: joining is a send, and the sends belong
        to the pump the caller drives, not to a registration call.
        """

        if topic in self._channels:
            raise ValueError("channel {} is already registered".format(topic))
        channel = Channel(
            topic,
            private=private,
            replay_since_ms=replay_since_ms,
            replay_limit=replay_limit,
        )
        self._channels[topic] = channel
        if self._backoff_factory is not None:
            self._channel_backoff[topic] = self._backoff_factory()
        self._rejoin_at_ms[topic] = (
            self._clock() if self.socket_state == SOCKET_OPEN else None
        )
        self._join_token[topic] = None
        return channel

    def channels(self):
        return tuple(self._channels.values())

    # ----------------------------------------------------------- connection

    async def connect(self):
        """Open the socket and (re)join every registered channel.

        Explicit by design: callers either await the whole operation at the
        legacy tolerant seam or retain this coroutine as NB-0's held task.  This
        method itself adds no scheduler or hidden lifetime.
        """

        if self.socket_state == SOCKET_OPEN:
            raise ValueError("already connected")
        self._reconnect_at_ms = None
        self._clear_reconnect_delay_draw()
        try:
            response = await self._ws_connect(self.socket_url())
        except Exception as exc:
            self._note_error(exc)
            self._schedule_reconnect()
            raise
        self._response = response
        try:
            # Everything after response ownership is one partial-state region.
            # Attribute setup, channel reset and task allocation can all raise
            # after the Upgrade opened a socket; no such raise may escape while
            # this object still owns the response.
            self._transport_heartbeat = getattr(
                response, "service_heartbeat", None)
            self.socket_state = SOCKET_OPEN
            self.connects += 1
            self.last_error = None
            self._ref = 0
            now = self._clock()
            self._heartbeat_ref = None
            self._heartbeat_due_ms = _ticks_add(now, self.heartbeat_ms)
            self._heartbeat_deadline_ms = None
            self._session_joined = False
            if (
                self._backoff is not None
                and self.backoff_reset == BACKOFF_RESET_ON_OPEN
            ):
                # See BACKOFF_RESET_ON_FIRST_JOIN: an open socket that never
                # joins is worth nothing to a doorbell, so P6-L3 does not credit
                # it.
                self._backoff.reset()
            for channel in self._channels.values():
                channel.reset()
                self._rejoin_at_ms[channel.topic] = None
                backoff = self._channel_backoff.get(channel.topic)
                if backoff is not None:
                    backoff.reset()
            # Own the unscheduled receive coroutine explicitly. At a low-memory
            # task-allocation failure the upgraded socket is closed below, and
            # its generator frame must be released at the same edge rather than
            # left for GC while the heap is already under pressure.
            receiver = response.receive()
            try:
                self._receive_task = asyncio.create_task(receiver)
            except BaseException:
                closer = getattr(receiver, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except BaseException:
                        pass
                raise
            for channel in self._channels.values():
                await self._join(channel, now)
        except Exception as exc:
            await self._drop(exc)
            raise
        except BaseException:
            # A held NB-0 establishment can be cancelled after the Upgrade has
            # installed the response and receive task but before every join SEND
            # finishes.  That is an administrative abort, not a failed session:
            # release every partial owner without scheduling transport backoff,
            # then preserve the cancellation for PushLink to consume.
            await self.abort_connect(retry=False)
            raise
        return True

    def reconnect_delay_ms(self, now_ms=None):
        """Milliseconds until the next connect() is due, or None if not scheduled."""

        if self.socket_state == SOCKET_OPEN or self._reconnect_at_ms is None:
            return None
        now = self._clock() if now_ms is None else now_ms
        return max(0, _ticks_diff(self._reconnect_at_ms, now))

    def reconnect_due(self, now_ms=None):
        delay = self.reconnect_delay_ms(now_ms)
        return delay is not None and delay <= 0

    async def close(self):
        """Leave joined channels politely, then release the transport."""

        if self.socket_state != SOCKET_OPEN:
            return False
        response = self._response
        for channel in self._channels.values():
            if channel.state == CHANNEL_JOINED:
                try:
                    await self._send(
                        channel.join_ref,
                        self._next_ref(),
                        channel.topic,
                        EVENT_LEAVE,
                        channel.start_leave(),
                    )
                except Exception:
                    break
        await self._release(response)
        self._reconnect_at_ms = None
        self._clear_reconnect_delay_draw()
        return True

    async def close_transport(self):
        """Drop the socket without the close handshake.  Same teardown.

        `close()` above leaves every joined channel and then lets layer 1 send a
        WebSocket CLOSE frame. Both are WRITES, and a write on this transport
        drains under `io_timeout_ms` -- 5,000 ms since owner ruling #21 -- so
        against a peer that cannot answer, being polite costs the deadline once
        per leave plus once for the CLOSE.

        This exists for BadgeLink paths whose rendered frame may not pay those
        courtesy writes: the radio `wifi_lost` edge (Lane H), plus NB-0's held
        cadence and administrative releases. It reuses `_release`, so the
        receive task is still cancelled, the channels are still reset, the
        rejoin and join-token maps are still cleared and `socket_state` still
        ends CLOSED. The ONLY difference is the frames that are not sent.

        `_reconnect_at_ms` is cleared exactly as `close()` clears it: this is a
        deliberate release, not a drop the backoff should ration.
        """

        if self.socket_state != SOCKET_OPEN:
            return False
        await self._release(self._response, polite=False)
        self._reconnect_at_ms = None
        self._clear_reconnect_delay_draw()
        return True

    async def abort_connect(self, retry=False):
        """Release a partial or complete establishment without courtesies.

        A held BadgeLink attempt may own transport state before its caller can
        call it a session.  Cleanup therefore keys off the actual response/task
        owners, not only ``socket_state``.  ``retry`` is typed policy from the
        owner (for example a Wi-Fi edge); repeated cleanup never consumes a
        second backoff rung.
        """

        had_owner = (
            self._response is not None
            or self._receive_task is not None
            or self.socket_state == SOCKET_OPEN
        )
        await self._release(self._response, polite=False)
        if retry:
            if self._reconnect_at_ms is None:
                self._schedule_reconnect()
        else:
            self._reconnect_at_ms = None
            self._clear_reconnect_delay_draw()
        return had_owner

    def rebase_reconnect(self, now_ms=None):
        """Move one already-drawn retry delay to a fresh owner tick."""

        if self._reconnect_at_ms is None:
            return False
        delay = getattr(self, "_reconnect_delay_draw_ms", None)
        if delay is None:
            return False
        now = self._clock() if now_ms is None else now_ms
        self._reconnect_at_ms = _ticks_add(now, delay)
        return True

    # ---------------------------------------------------------------- pump

    async def service(self):
        """One non-blocking step: at most one frame in, plus the timers.

        An overdue heartbeat is the exception: it drains what has already
        arrived rather than dropping a socket whose reply was merely unread.
        """

        events = []
        if self.socket_state != SOCKET_OPEN:
            return events
        if await self._take_frame(events) == FRAME_DROPPED:
            return events
        try:
            await self._run_timers(events)
        except Exception as exc:
            events.append(await self._drop(exc))
        return events

    async def set_access_token(self, token):
        """Refresh the JWT in place; joined channels keep their subscriptions.

        A channel that is still JOINING has nothing to tell yet, so it is caught
        up from `_dispatch_reply` the moment its join is answered. Re-supplying
        the token already in use is a no-op: an ``access_token`` frame with the
        same JWT does not create a fresh private-channel authorization boundary,
        so sending one would be both wire work and a misleading signal to layer
        3's revocation meter.
        """

        token = validate_access_token(token)
        if token == self.access_token:
            return False
        self.access_token = token
        if self.socket_state != SOCKET_OPEN:
            return False
        for channel in self._channels.values():
            if channel.state == CHANNEL_JOINED:
                await self._push_access_token(channel)
        return True

    def snapshot(self):
        """Counters only: no URL, no apikey, no token, no payload content."""

        return {
            "socket_state": self.socket_state,
            "connects": self.connects,
            "disconnects": self.disconnects,
            "joins": self.joins,
            "join_errors": self.join_errors,
            "heartbeats_sent": self.heartbeats_sent,
            "heartbeat_timeouts": self.heartbeat_timeouts,
            "messages_received": self.messages_received,
            "broadcasts_received": self.broadcasts_received,
            "protocol_errors": self.protocol_errors,
            "binary_frames_ignored": self.binary_frames_ignored,
            "unknown_topic_messages": self.unknown_topic_messages,
            "last_error": self.last_error,
            "channels": [channel.snapshot() for channel in self._channels.values()],
        }

    # ------------------------------------------------------------ internals

    def _next_ref(self):
        self._ref += 1
        return str(self._ref)

    async def _send(self, join_ref, ref, topic, event, payload):
        await self._response.send_str(encode(join_ref, ref, topic, event, payload))

    async def _join(self, channel, now_ms):
        join_ref = self._next_ref()
        payload = channel.start_join(join_ref, now_ms, access_token=self.access_token)
        self._rejoin_at_ms[channel.topic] = None
        # Which JWT this join is carrying, so a refresh that lands while the
        # join is still in flight can be reconciled when the reply arrives.
        self._join_token[channel.topic] = self.access_token
        await self._send(join_ref, join_ref, channel.topic, EVENT_JOIN, payload)

    async def _push_access_token(self, channel):
        """Tell one joined channel to authorize with the client's current JWT."""

        await self._send(
            channel.join_ref,
            self._next_ref(),
            channel.topic,
            EVENT_ACCESS_TOKEN,
            {"access_token": self.access_token},
        )
        self._join_token[channel.topic] = self.access_token

    async def _send_heartbeat(self, now_ms):
        ref = self._next_ref()
        self._heartbeat_ref = ref
        self._heartbeat_deadline_ms = _ticks_add(now_ms, self.heartbeat_timeout_ms)
        self._heartbeat_due_ms = _ticks_add(now_ms, self.heartbeat_ms)
        await self._send(None, ref, PHOENIX_TOPIC, EVENT_HEARTBEAT, {})
        self.heartbeats_sent += 1

    async def _run_timers(self, events):
        now = self._clock()
        if self._transport_heartbeat is not None:
            await self._transport_heartbeat()
        if (
            self._heartbeat_ref is not None
            and _ticks_diff(now, self._heartbeat_deadline_ms) >= 0
        ):
            # The reply may already be queued behind another frame; count it
            # before declaring the socket dead.
            if await self._drain_for_heartbeat_reply(events):
                return
        if self._heartbeat_ref is not None:
            if _ticks_diff(now, self._heartbeat_deadline_ms) >= 0:
                self.heartbeat_timeouts += 1
                events.append(await self._drop("heartbeat reply timed out"))
                return
        elif _ticks_diff(now, self._heartbeat_due_ms) >= 0:
            await self._send_heartbeat(now)
        for channel in self._channels.values():
            if (
                channel.state == CHANNEL_JOINING
                and channel.join_sent_ms is not None
                and _ticks_diff(now, channel.join_sent_ms) >= self.join_timeout_ms
            ):
                channel.join_failed("join timed out")
                self.join_errors += 1
                self._schedule_rejoin(channel, now)
                events.append(
                    RealtimeEvent(
                        KIND_CHANNEL_ERROR, topic=channel.topic, reason="join timed out"
                    )
                )
            elif channel.state in (CHANNEL_CLOSED, CHANNEL_ERRORED):
                due = self._rejoin_at_ms.get(channel.topic)
                if due is not None and _ticks_diff(now, due) >= 0:
                    await self._join(channel, now)

    async def _take_frame(self, events):
        """Handle one frame if one has already arrived; never wait for the network.

        FRAME_NONE when nothing was in hand, FRAME_HANDLED when a frame was
        processed, FRAME_DROPPED when the read or the frame ended the session.
        """

        if self._receive_task is None or not self._receive_task.done():
            return FRAME_NONE
        try:
            message = await self._receive_task
        except Exception as exc:
            self._receive_task = None
            events.append(await self._drop(exc))
            return FRAME_DROPPED
        self._receive_task = asyncio.create_task(self._response.receive())
        if await self._handle_frame(message, events):
            return FRAME_DROPPED
        return FRAME_HANDLED

    async def _drain_for_heartbeat_reply(self, events):
        """Empty the frames already in hand before believing a heartbeat timeout.

        `service()` reads one frame per call so the caller keeps its frame
        budget, which also means a starved pump can reach the heartbeat deadline
        with the reply sitting behind another frame — a healthy socket dropped
        because nobody looked. Returns True when the socket dropped in here; a
        reply that genuinely never arrived still leaves `_heartbeat_ref` set and
        times out in the same `service()` call.
        """

        for _ in range(HEARTBEAT_DRAIN_ROUNDS):
            if self._heartbeat_ref is None:
                return False
            outcome = await self._take_frame(events)
            if outcome == FRAME_DROPPED:
                return True
            if outcome == FRAME_NONE:
                # Hand the loop one turn so a read whose bytes are already here
                # can finish. This is a yield, not a wait for the network.
                await asyncio.sleep(0)
        return False

    async def _handle_frame(self, message, events):
        """Return True when the socket was dropped handling this frame."""

        kind = getattr(message, "type", None)
        if kind in (WS_PING, WS_PONG):
            return False
        if kind == WS_CLOSE:
            events.append(await self._drop("server closed the WebSocket"))
            return True
        if kind == WS_BINARY:
            return await self._handle_binary(message.data, events)
        if kind != WS_TEXT:
            self.protocol_errors += 1
            events.append(await self._drop("Phoenix frames must be text or binary"))
            return True
        try:
            frame = decode(message.data)
        except ProtocolError as exc:
            self.protocol_errors += 1
            events.append(await self._drop(exc))
            return True
        return await self._deliver(frame, events)

    async def _handle_binary(self, data, events):
        """A binary frame is a Supabase Broadcast, and it must not cost the socket.

        THE D9 FIX (2026-08-22). This branch used to be the `kind != WS_TEXT`
        fall-through below: a protocol error and an immediate drop. That is what a
        DB-published Broadcast is -- `realtime.send()` reaches a vsn=2.0.0
        subscriber as an OPCODE-2 binary `UserBroadcast` frame -- so on the real
        hosted project three published `command_status` messages produced ZERO
        doorbells and a session that ended and rejoined, on a channel that had
        joined healthily. `phoenix.decode_binary` has the wire layout and the
        pinned server source.

        An UNDECODABLE binary frame is counted and SKIPPED rather than dropped,
        and the asymmetry with text is deliberate. A frame layer 2 cannot read is
        worth at most one missed doorbell: polling is the correctness path and
        applies the effect regardless. Dropping the socket costs the session AND
        the 735 ms blocking TLS handshake that re-opens it, and at 800 badges a
        server-side framing change nobody shipped a decoder for would turn into a
        fleet-wide reconnect storm. A malformed TEXT frame keeps its fail-fast
        behaviour because it means the two peers disagree about Phoenix itself.
        """

        try:
            frame = decode_binary(data)
        except ProtocolError:
            self.binary_frames_ignored += 1
            return False
        return await self._deliver(frame, events)

    async def _deliver(self, frame, events):
        """Count a decoded frame and dispatch it. True when the socket dropped."""

        self.messages_received += 1
        try:
            await self._dispatch(frame, events)
        except Exception as exc:
            # Dispatch answers some frames on the wire (a mid-join token
            # refresh), and a send that fails means the socket is already gone.
            events.append(await self._drop(exc))
            return True
        return False

    async def _dispatch(self, frame, events):
        now = self._clock()
        if frame.topic == PHOENIX_TOPIC:
            if frame.event == EVENT_REPLY and frame.ref == self._heartbeat_ref:
                self._heartbeat_ref = None
                self._heartbeat_deadline_ms = None
            return
        channel = self._channels.get(frame.topic)
        if channel is None:
            self.unknown_topic_messages += 1
            return
        if frame.event == EVENT_REPLY:
            await self._dispatch_reply(channel, frame, events, now)
        elif frame.event in (EVENT_ERROR, EVENT_CLOSE):
            self._fail_channel(channel, frame, events, now)
        elif frame.event == EVENT_BROADCAST:
            self.broadcasts_received += 1
            events.append(
                RealtimeEvent(
                    KIND_BROADCAST,
                    topic=frame.topic,
                    event=frame.payload.get("event"),
                    payload=frame.payload.get("payload"),
                )
            )
        elif frame.event == EVENT_SYSTEM:
            events.append(
                RealtimeEvent(
                    KIND_SYSTEM,
                    topic=frame.topic,
                    event=frame.payload.get("status"),
                    payload=frame.payload,
                    reason=frame.payload.get("message"),
                )
            )
        else:
            events.append(
                RealtimeEvent(KIND_UNHANDLED, topic=frame.topic, event=frame.event, payload=frame.payload)
            )

    async def _dispatch_reply(self, channel, frame, events, now):
        if channel.state != CHANNEL_JOINING or frame.ref != channel.join_ref:
            if channel.state == CHANNEL_LEAVING and frame.status() == STATUS_OK:
                channel.reset("left")
            return
        if frame.status() == STATUS_OK:
            channel.join_succeeded()
            self.joins += 1
            if (
                self._backoff is not None
                and self.backoff_reset == BACKOFF_RESET_ON_FIRST_JOIN
                and not self._session_joined
            ):
                self._backoff.reset()
            self._session_joined = True
            backoff = self._channel_backoff.get(channel.topic)
            if backoff is not None:
                backoff.reset()
            events.append(RealtimeEvent(KIND_JOINED, topic=channel.topic))
            if (
                self.access_token is not None
                and self.access_token != self._join_token.get(channel.topic)
            ):
                # A refresh arrived while this join was in flight.
                # `set_access_token()` only reaches channels that are already
                # JOINED, so without this catch-up the channel would stay
                # subscribed on the token it joined with until the next rejoin,
                # and Realtime would tear it down when that token expired.
                await self._push_access_token(channel)
            return
        reason = frame.reason() or "join refused"
        channel.join_failed(reason)
        self.join_errors += 1
        self._schedule_rejoin(channel, now)
        events.append(RealtimeEvent(KIND_JOIN_ERROR, topic=channel.topic, reason=reason))

    def _fail_channel(self, channel, frame, events, now):
        reason = frame.reason() or frame.event
        channel.channel_failed(reason)
        self._schedule_rejoin(channel, now)
        events.append(RealtimeEvent(KIND_CHANNEL_ERROR, topic=channel.topic, reason=reason))

    def _schedule_rejoin(self, channel, now_ms):
        backoff = self._channel_backoff.get(channel.topic)
        if backoff is None:
            self._rejoin_at_ms[channel.topic] = None
            return
        self._rejoin_at_ms[channel.topic] = _ticks_add(now_ms, backoff.next_delay_ms())

    def _schedule_reconnect(self):
        if self._backoff is None:
            self._reconnect_at_ms = None
            self._clear_reconnect_delay_draw()
            return
        # Keep the DRAW beside its due tick. NB-0 may reap a completed connect
        # several rendered frames later; rebasing the same draw at handoff must
        # not consume a second fleet-backoff rung or inherit an already-expired
        # deadline from the child terminal frame. Materialise it only after a
        # retry exists so the build-time-OFF healthy path retains its old heap.
        delay = self._backoff.next_delay_ms()
        self._reconnect_delay_draw_ms = delay
        self._reconnect_at_ms = _ticks_add(self._clock(), delay)

    def _clear_reconnect_delay_draw(self):
        """Forget NB-0 retry metadata without materialising it in cold OFF."""

        # A class default or `= None` in __init__ costs every healthy OFF client
        # one instance slot even though only a failed held attempt needs rebase.
        # Deleting after use restores that exact lazy-heap property.
        if hasattr(self, "_reconnect_delay_draw_ms"):
            del self._reconnect_delay_draw_ms

    def _note_error(self, error):
        if isinstance(error, str):
            self.last_error = error[:MAX_REASON_CHARACTERS]
        else:
            self.last_error = "{}: {}".format(
                error.__class__.__name__, str(error)[:MAX_REASON_CHARACTERS]
            )

    async def _release(self, response, polite=True):
        if self._receive_task is not None:
            if not self._receive_task.done():
                self._receive_task.cancel()
            try:
                await self._receive_task
            except BaseException:
                pass
            self._receive_task = None
        if response is not None:
            try:
                # `polite=False` skips the CLOSE frame and releases the transport
                # directly -- see `close_transport`. Duck-typed, so a response
                # object without it (a scripted stand-in, or a vendored client
                # older than the seam) closes politely rather than not at all.
                abrupt = (getattr(response, "close_transport", None)
                          if not polite else None)
                if callable(abrupt):
                    await abrupt()
                else:
                    await response.close()
            except BaseException:
                pass
        self._response = None
        self._transport_heartbeat = None
        self.socket_state = SOCKET_CLOSED
        self._heartbeat_ref = None
        self._heartbeat_due_ms = None
        self._heartbeat_deadline_ms = None
        for channel in self._channels.values():
            channel.reset()
            self._rejoin_at_ms[channel.topic] = None
            self._join_token[channel.topic] = None

    async def _drop(self, error):
        """Tear the socket down, schedule the next attempt, describe the loss."""

        self._note_error(error)
        self.disconnects += 1
        await self._release(self._response)
        self._schedule_reconnect()
        return RealtimeEvent(KIND_DISCONNECTED, reason=self.last_error)
