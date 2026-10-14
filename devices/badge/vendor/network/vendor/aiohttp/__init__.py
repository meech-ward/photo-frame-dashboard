"""Bounded WebSocket-only subset of micropython-lib aiohttp.

Based on micropython-lib aiohttp at commit
220ca9de9af63589cf5f372dcd12d7c272e54584 (MIT).
"""

from .aiohttp_ws import (
    ClientSession,
    ClientWebSocketResponse,
    WebSocketLivenessError,
    WSMsgType,
)

__all__ = (
    "ClientSession",
    "ClientWebSocketResponse",
    "WebSocketLivenessError",
    "WSMsgType",
)
