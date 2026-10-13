"""Phoenix v2 framing and channel state for Supabase Realtime.

Pure data and state: no sockets, no asyncio, no Badgeware, no BadgeLink. Every
wire shape here is from the Supabase Realtime protocol reference (fetched
2026-08-17), not inferred from a client library.

A v2 frame is a five-element array::

    [join_ref, ref, topic, event, payload]

`decode()` treats that array as untrusted input, because it is: it arrives from
the network before anything has authorized it.

A v2 socket also carries a SECOND framing, and missing it cost the whole D9
doorbell gate. See `decode_binary()`.
"""

import json


VSN = "2.0.0"
PHOENIX_TOPIC = "phoenix"
TOPIC_PREFIX = "realtime:"

EVENT_JOIN = "phx_join"
EVENT_LEAVE = "phx_leave"
EVENT_REPLY = "phx_reply"
EVENT_CLOSE = "phx_close"
EVENT_ERROR = "phx_error"
EVENT_HEARTBEAT = "heartbeat"
EVENT_ACCESS_TOKEN = "access_token"
EVENT_BROADCAST = "broadcast"
EVENT_SYSTEM = "system"
EVENT_PRESENCE_STATE = "presence_state"
EVENT_PRESENCE_DIFF = "presence_diff"
EVENT_POSTGRES_CHANGES = "postgres_changes"

STATUS_OK = "ok"
STATUS_ERROR = "error"

CHANNEL_CLOSED = "closed"
CHANNEL_JOINING = "joining"
CHANNEL_JOINED = "joined"
CHANNEL_ERRORED = "errored"
CHANNEL_LEAVING = "leaving"

MAX_TOPIC_CHARACTERS = 128
MAX_EVENT_CHARACTERS = 64
MAX_REF_CHARACTERS = 32
MAX_REASON_CHARACTERS = 120

#: The binary frame kinds a vsn=2.0.0 Supabase socket can carry. Only
#: `BINARY_KIND_USER_BROADCAST` is ever pushed to a subscriber that has not itself
#: sent a binary payload, and it is the framing every DB-published Broadcast
#: arrives in. See `decode_binary()`.
BINARY_KIND_USER_BROADCAST = 4
#: How the user payload inside a UserBroadcast frame is encoded.
BINARY_ENCODING_RAW = 0
BINARY_ENCODING_JSON = 1
#: kind, topic length, event length, metadata length, payload encoding.
BINARY_HEADER_BYTES = 5


class ProtocolError(Exception):
    """The peer sent something that is not a valid Phoenix v2 message."""


def _check_ref(value, label):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_REF_CHARACTERS:
        raise ProtocolError("invalid Phoenix {}".format(label))
    return value


def _decode_utf8(raw, label="Phoenix frame"):
    try:
        return bytes(raw).decode("utf-8")
    except (UnicodeError, ValueError):
        raise ProtocolError("{} was not UTF-8 text".format(label))


def _load_json(text, label="Phoenix frame"):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        raise ProtocolError("{} was not JSON".format(label))


def _check_token(value, label, maximum):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ProtocolError("invalid Phoenix {}".format(label))
    for character in value:
        if ord(character) < 32 or ord(character) == 127:
            raise ProtocolError("invalid Phoenix {}".format(label))
    return value


class Message:
    def __init__(self, join_ref, ref, topic, event, payload):
        self.join_ref = join_ref
        self.ref = ref
        self.topic = topic
        self.event = event
        self.payload = payload

    def status(self):
        """The reply status, or None when this is not a reply we understand."""

        if self.event != EVENT_REPLY:
            return None
        value = self.payload.get("status")
        return value if isinstance(value, str) else None

    def reason(self):
        """A bounded, human-readable failure reason; never assumed to be present."""

        response = self.payload.get("response")
        if isinstance(response, dict):
            value = response.get("reason") or response.get("message")
            if isinstance(value, str):
                return value[:MAX_REASON_CHARACTERS]
        value = self.payload.get("message")
        if isinstance(value, str):
            return value[:MAX_REASON_CHARACTERS]
        return None

    def __repr__(self):
        return "Message({}, {}, {}, {})".format(
            self.join_ref, self.ref, self.topic, self.event
        )


def encode(join_ref, ref, topic, event, payload=None):
    return json.dumps([join_ref, ref, topic, event, payload if payload is not None else {}])


def decode(text):
    if isinstance(text, (bytes, bytearray)):
        text = _decode_utf8(text)
    if not isinstance(text, str):
        raise ProtocolError("Phoenix frames arrive as text")
    value = _load_json(text)
    if not isinstance(value, list) or len(value) != 5:
        raise ProtocolError("Phoenix v2 frames are five-element arrays")
    join_ref, ref, topic, event, payload = value
    join_ref = _check_ref(join_ref, "join_ref")
    ref = _check_ref(ref, "ref")
    topic = _check_token(topic, "topic", MAX_TOPIC_CHARACTERS)
    event = _check_token(event, "event", MAX_EVENT_CHARACTERS)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ProtocolError("Phoenix payloads are objects")
    return Message(join_ref, ref, topic, event, payload)


def decode_binary(data):
    """Decode the server's binary `UserBroadcast` frame into a v2 `Message`.

    THE D9 ROOT CAUSE, and the reason this function has to exist. A Broadcast
    published FROM THE DATABASE -- `realtime.send()`, which is the only publisher
    BadgeLink has (`grants.broadcast_command_status()`) -- does NOT arrive as a
    Phoenix v2 text array. The tenant's replication connection reads the
    `realtime.messages` row and turns it into a `%UserBroadcast{}` struct, and the
    vsn=2.0.0 serializer fastlanes that struct as an OPCODE-2 BINARY frame::

        <<4, topic_len, event_len, meta_len, encoding, topic, event, meta, body>>

    Every length is a BYTE count over UTF-8, so a multi-byte event name is
    measured correctly. `encoding` is 1 for a JSON body and 0 for raw bytes.

    Only the vsn=1.0.0 serializer converts the struct back into a JSON array, so
    a client that speaks 2.0.0 cannot ask for text and MUST decode this. Source:
    supabase/realtime @ 897bd97 --
    `lib/realtime/tenants/replication_connection.ex:406-441` (the struct),
    `lib/realtime_web/socket/v2_serializer.ex:19-45` (the framing),
    `lib/realtime_web/channels/realtime_channel/message_dispatcher.ex:134-170`
    (the fastlane, and the vsn=1-only JSON conversion).

    The `Message` produced here is deliberately identical to the one `decode()`
    builds for a client-published Broadcast, and to what `@supabase/realtime-js`
    2.112.3 hands its `on("broadcast", ...)` callback
    (`src/lib/serializer.ts:162-202`) -- the listener the P5 web evidence came
    from. So nothing above this line can tell a database Broadcast from any
    other, and the outer event is `broadcast` with the publisher's own event name
    nested at `payload["event"]`.
    """

    if not isinstance(data, (bytes, bytearray)):
        raise ProtocolError("binary Phoenix frames arrive as bytes")
    data = bytes(data)
    if len(data) < BINARY_HEADER_BYTES:
        raise ProtocolError("binary Phoenix frame is shorter than its header")
    kind = data[0]
    if kind != BINARY_KIND_USER_BROADCAST:
        raise ProtocolError("unsupported binary frame kind {}".format(kind))
    topic_size = data[1]
    event_size = data[2]
    meta_size = data[3]
    encoding = data[4]
    offset = BINARY_HEADER_BYTES
    if offset + topic_size + event_size + meta_size > len(data):
        raise ProtocolError("binary Phoenix frame header overruns the frame")
    topic = _check_token(
        _decode_utf8(data[offset:offset + topic_size], "binary Phoenix topic"),
        "topic",
        MAX_TOPIC_CHARACTERS,
    )
    offset += topic_size
    user_event = _check_token(
        _decode_utf8(data[offset:offset + event_size], "binary Phoenix event"),
        "event",
        MAX_EVENT_CHARACTERS,
    )
    offset += event_size
    raw_meta = data[offset:offset + meta_size]
    offset += meta_size
    body = data[offset:]
    if encoding == BINARY_ENCODING_JSON:
        # Any JSON value is legal here; a doorbell never reads it, and inventing
        # a stricter rule than the server's would drop real messages.
        value = _load_json(
            _decode_utf8(body, "binary Phoenix payload"), "binary Phoenix payload"
        )
    elif encoding == BINARY_ENCODING_RAW:
        value = body
    else:
        raise ProtocolError("unknown binary payload encoding {}".format(encoding))
    payload = {"type": EVENT_BROADCAST, "event": user_event, "payload": value}
    if meta_size:
        meta = _load_json(
            _decode_utf8(raw_meta, "binary Phoenix metadata"), "binary Phoenix metadata"
        )
        if not isinstance(meta, dict):
            raise ProtocolError("binary Phoenix metadata is not an object")
        payload["meta"] = meta
    return Message(None, None, topic, EVENT_BROADCAST, payload)


def clamp_replay_since_ms(since_ms, ceiling_ms):
    """Keep a broadcast-replay `since` from landing in the server's future.

    Realtime discards a replay window whose start is beyond `now + 1 minute`, so
    a badge whose clock runs AHEAD of UTC silently gets nothing back. Clamping
    to a known-past ceiling (the event start, say) turns a silent no-op into a
    slightly wider catch-up window.
    """

    return min(int(since_ms), int(ceiling_ms))


def join_payload(
    access_token=None, private=True, replay_since_ms=None, replay_limit=None
):
    """The phx_join payload for a badge's private broadcast channel.

    Presence is off and postgres_changes is empty deliberately, not by omission:
    presence fans an O(N) diff out to every subscriber on every join or leave —
    800 rebooting badges would make each reboot an 800-message event — and
    Postgres Changes has no replay and evaluates RLS per subscriber.
    """

    broadcast = {"ack": False, "self": False}
    if replay_since_ms is not None:
        if replay_limit is None:
            raise ValueError("broadcast replay needs both a since and a limit")
        since = int(replay_since_ms)
        limit = int(replay_limit)
        if since < 0:
            raise ValueError("broadcast replay since must not be negative")
        if limit < 1:
            raise ValueError("broadcast replay limit must be positive")
        broadcast["replay"] = {"since": since, "limit": limit}
    payload = {
        "config": {
            "broadcast": broadcast,
            "presence": {"enabled": False},
            "postgres_changes": [],
            "private": bool(private),
        }
    }
    if access_token is not None:
        payload["access_token"] = access_token
    return payload


class Channel:
    """One Realtime topic and the state machine that keeps it joined.

    Clock-free: the owner passes `now_ms` in, so join timeouts are testable
    without sleeping and the same code runs against `time.ticks_ms()`.
    """

    def __init__(self, topic, private=True, replay_since_ms=None, replay_limit=None):
        self.topic = _check_token(topic, "topic", MAX_TOPIC_CHARACTERS)
        if not topic.startswith(TOPIC_PREFIX):
            raise ValueError("Realtime topics start with '{}'".format(TOPIC_PREFIX))
        if len(topic) <= len(TOPIC_PREFIX):
            raise ValueError("Realtime topic needs a name after the prefix")
        self.private = bool(private)
        self.replay_since_ms = replay_since_ms
        self.replay_limit = replay_limit
        self.state = CHANNEL_CLOSED
        self.join_ref = None
        self.join_sent_ms = None
        self.joins = 0
        self.join_errors = 0
        self.last_reason = None

    def start_join(self, join_ref, now_ms, access_token=None):
        """Move to JOINING and return the payload to send."""

        if self.state in (CHANNEL_JOINING, CHANNEL_JOINED):
            raise ValueError("channel {} is already {}".format(self.topic, self.state))
        self.state = CHANNEL_JOINING
        self.join_ref = _check_ref(join_ref, "join_ref")
        self.join_sent_ms = now_ms
        self.last_reason = None
        return join_payload(
            access_token=access_token,
            private=self.private,
            replay_since_ms=self.replay_since_ms,
            replay_limit=self.replay_limit,
        )

    def join_succeeded(self):
        if self.state != CHANNEL_JOINING:
            raise ValueError("channel {} was not joining".format(self.topic))
        self.state = CHANNEL_JOINED
        self.joins += 1
        self.join_sent_ms = None

    def join_failed(self, reason=None):
        self.state = CHANNEL_ERRORED
        self.join_errors += 1
        self.join_sent_ms = None
        self.last_reason = None if reason is None else str(reason)[:MAX_REASON_CHARACTERS]

    def channel_failed(self, reason=None):
        """The server ended a joined channel (phx_error, phx_close, or a drop)."""

        self.state = CHANNEL_ERRORED
        self.join_sent_ms = None
        self.last_reason = None if reason is None else str(reason)[:MAX_REASON_CHARACTERS]

    def start_leave(self):
        self.state = CHANNEL_LEAVING
        return {}

    def reset(self, reason=None):
        """Forget the socket-bound state: refs do not survive a new connection."""

        self.state = CHANNEL_CLOSED
        self.join_ref = None
        self.join_sent_ms = None
        if reason is not None:
            self.last_reason = str(reason)[:MAX_REASON_CHARACTERS]

    def snapshot(self):
        return {
            "topic": self.topic,
            "state": self.state,
            "joins": self.joins,
            "join_errors": self.join_errors,
            "last_reason": self.last_reason,
        }
