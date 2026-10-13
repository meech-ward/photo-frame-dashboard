"""Portable Supabase Realtime (Phoenix v2) client.

Layer 2 of the BadgeLink P6 three-layer rule: the WebSocket transport below it
is injected, and nothing above it — Badgeware, BadgeLink, the supervisor — is
imported here. `badgelink/tests/test_realtime_boundary.py` enforces that.
"""

from .client import (
    BACKOFF_RESET_MODES,
    BACKOFF_RESET_ON_FIRST_JOIN,
    BACKOFF_RESET_ON_OPEN,
    KIND_BROADCAST,
    KIND_CHANNEL_ERROR,
    KIND_DISCONNECTED,
    KIND_JOIN_ERROR,
    KIND_JOINED,
    KIND_SYSTEM,
    KIND_UNHANDLED,
    SOCKET_CLOSED,
    SOCKET_OPEN,
    RealtimeClient,
    RealtimeEvent,
    validate_access_token,
)
from .phoenix import (
    CHANNEL_CLOSED,
    CHANNEL_ERRORED,
    CHANNEL_JOINED,
    CHANNEL_JOINING,
    CHANNEL_LEAVING,
    PHOENIX_TOPIC,
    VSN,
    Channel,
    ProtocolError,
    clamp_replay_since_ms,
    decode,
    encode,
    join_payload,
)

__all__ = (
    "BACKOFF_RESET_MODES",
    "BACKOFF_RESET_ON_FIRST_JOIN",
    "BACKOFF_RESET_ON_OPEN",
    "Channel",
    "ProtocolError",
    "RealtimeClient",
    "RealtimeEvent",
    "clamp_replay_since_ms",
    "decode",
    "encode",
    "join_payload",
    "validate_access_token",
)
