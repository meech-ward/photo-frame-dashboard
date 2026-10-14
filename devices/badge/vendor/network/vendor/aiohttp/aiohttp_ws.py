"""Bounded MicroPython WebSocket client derived from micropython-lib aiohttp.

MIT license; Copyright (c) 2023 Carlos Gil. The original implementation was
adapted from uwebsockets and microdot. Local hardening is documented in
PROVENANCE.md next to this file.
"""

import asyncio
import binascii
import hashlib
import random
import re
import struct
import sys
from collections import namedtuple


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


GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
URL_RE = re.compile(r"^(wss|ws)://([A-Za-z0-9.-]+)(?:\:([0-9]+))?(/.*)?$")
URI = namedtuple("URI", ("protocol", "hostname", "port", "path"))
VALID_OPCODES = (0, 1, 2, 8, 9, 10)
MAX_CONTROL_PAYLOAD = 125
INHERIT_IO_TIMEOUT = ("inherit-io-timeout",)
_MICROPYTHON = getattr(sys.implementation, "name", "") == "micropython"


class WebSocketLivenessError(Exception):
    """A client-initiated ping went unanswered past its pong deadline."""


def urlparse(value):
    match = URL_RE.match(value)
    if not match:
        raise ValueError("invalid ws/wss URL")
    protocol, hostname, port, path = match.groups()
    return URI(
        protocol,
        hostname,
        int(port or (443 if protocol == "wss" else 80)),
        path or "/",
    )


async def _wait_for(awaitable, timeout_ms):
    if timeout_ms is None:
        return await awaitable
    task = asyncio.create_task(awaitable)
    wait_for_ms = getattr(asyncio, "wait_for_ms", None)
    try:
        if wait_for_ms is not None:
            return await wait_for_ms(task, int(timeout_ms))
        return await asyncio.wait_for(task, int(timeout_ms) / 1000)
    except BaseException:
        # Pinned uasyncio re-raises an EXTERNAL cancellation immediately after
        # cancelling its private runner; it does not wait for the awaitable's
        # finally blocks. Retain our own task and drive it to terminal before an
        # owner can discard the loop that still knows its I/O registration.
        if not task.done():
            task.cancel()
        try:
            await task
        except BaseException:
            pass
        raise


async def _writer_write(writer, value, timeout_ms):
    writer.write(value)
    await _wait_for(writer.drain(), timeout_ms)


# WHERE ONE ESTABLISHMENT'S MILLISECONDS WENT, for a caller that supplies a
# dict. Local addition (see PROVENANCE.md): the whole handshake is one blocking
# lump from the outside, and on MicroPython the legs inside it have wildly
# different costs -- a name resolution inside `open_connection`, a deferred TLS
# handshake carried by the first positive write, then two bounded reads.
#
# THE TRACE IS THE CALLER'S DICT AND THIS MODULE ONLY WRITES TO IT. `phase` is
# set BEFORE each leg and a span AFTER it, so a handshake cancelled mid-leg by
# `connect_timeout_ms` leaves a record naming the leg it died in with that leg's
# span still zero. Nothing in the handshake reads either back.
def _trace_phase(trace, phase):
    if trace is not None:
        trace["phase"] = phase


def _trace_span(trace, name, clock, entered):
    if trace is None:
        return
    span = _ticks_diff(clock(), entered)
    trace[name] = 0 if span < 0 else span


async def _close_writer(writer):
    if writer is None:
        return
    try:
        writer.close()
    except BaseException:
        return
    wait_closed = getattr(writer, "wait_closed", None)
    if wait_closed is not None:
        try:
            await wait_closed()
        except BaseException:
            pass


def _wait_writable(transport):
    """Yield once on the pinned uasyncio I/O queue."""

    from asyncio import core

    yield core._io_queue.queue_write(transport)


async def _open_micropython_connection(
    owner,
    host,
    port,
    ssl,
    server_hostname,
    socket_module,
    stream_factory,
    wait_writable,
):
    """Pinned ``open_connection`` with ownership from raw creation onward.

    This intentionally mirrors firmware commit ``b29530ab``.  Its helper holds
    the raw socket only in a local before several operations that can raise and
    before the first I/O yield.  NB-0 must be able to abort every such state
    without waiting for GC, so both raw and wrapped transports are published to
    the caller as soon as each exists.
    """

    import errno

    pending = (
        errno.EINPROGRESS,
        getattr(errno, "EALREADY", errno.EINPROGRESS),
        getattr(errno, "EWOULDBLOCK", errno.EINPROGRESS),
    )
    ai = socket_module.getaddrinfo(host, port, 0, socket_module.SOCK_STREAM)[0]
    raw = socket_module.socket(ai[0], ai[1], ai[2])
    owner._raw_socket = raw
    transport = raw
    try:
        raw.setblocking(False)
        try:
            raw.connect(ai[-1])
        except OSError as exc:
            if getattr(exc, "errno", None) not in pending:
                raise
        if ssl:
            if ssl is True:
                import ssl as ssl_module

                ssl = ssl_module.SSLContext(ssl_module.PROTOCOL_TLS_CLIENT)
            if not server_hostname:
                server_hostname = host
            transport = ssl.wrap_socket(
                raw,
                server_hostname=server_hostname,
                do_handshake_on_connect=False,
            )
            owner._opening_transport = transport
            transport.setblocking(False)
        await wait_writable(transport)
        stream = stream_factory(transport)
        owner._opening_transport = None
        if not ssl:
            owner._handoff_owned_raw()
        return stream, stream
    except BaseException:
        owner._close_opening_transport()
        # When ``transport`` is the raw socket this is its one close.  For TLS,
        # wrapper close normally delegates and this second close is deliberately
        # idempotent; it is also the fallback if mbedTLS detached the raw owner.
        owner._close_owned_raw()
        raise


async def _open_connection_owned(owner, host, port, ssl=None, server_hostname=None):
    """Use the owned pinned path on MicroPython; keep CPython's public API."""

    if not _MICROPYTHON:
        options = {"ssl": ssl}
        if server_hostname is not None:
            options["server_hostname"] = server_hostname
        return await asyncio.open_connection(host, port, **options)

    import socket

    def stream_factory(transport):
        # Pinned ``StreamReader`` and ``StreamWriter`` are aliases for the same
        # allocation-saving Stream class, exactly as in upstream stream.py.
        return asyncio.StreamReader(transport, {})

    return await _open_micropython_connection(
        owner,
        host,
        port,
        ssl,
        server_hostname,
        socket,
        stream_factory,
        _wait_writable,
    )


#: HOW MUCH ONE Upgrade read MAY ASK FOR AT A TIME. Bounds the transient
#: allocation, not the total: `max_header_size` still caps the whole head. 512
#: because a real HTTP/1.1 101 response is ~180-350 bytes, so a normal handshake
#: is one await either way, and because MicroPython's stream `read(n)` sizes its
#: buffer from `n` -- asking for the full 8 KB cap would put a large transient in
#: a rendered frame on a ~520 KB heap for no benefit.
UPGRADE_READ_CHUNK = 512


async def _read_upgrade_head(reader, limit, timeout_ms):
    """Read the whole Upgrade response head in BULK. Bounded, and few awaits.

    Returns ``(status_line, header_lines, leftover)`` with every line still
    carrying its ``\r\n``, and ``leftover`` holding any bytes that arrived after
    the blank line -- those belong to the caller's frame reader and must not be
    dropped.

    ⚠ **THIS WAS ONE ``_wait_for(reader.readexactly(1), ...)`` PER BYTE UNTIL
    2026-08-26, AND THAT SHAPE IS WHAT KEPT A COOPERATIVELY-PUMPED CLIENT FROM
    EVER COMPLETING A HANDSHAKE.** The old loop was written to avoid an unbounded
    ``Stream.readline`` allocation, which is a real hazard and is still bounded
    here -- but its cost per byte was a ``create_task`` plus a ``wait_for_ms``
    plus at least one scheduler round trip, and MicroPython's ``Stream.read``
    yields to the I/O queue on every call whether or not the bytes are already
    buffered. A ~300-byte HTTP/1.1 101 response therefore cost ~300 forced
    yields.

    That is survivable when one caller awaits the whole handshake inside a single
    ``run_until_complete``: it measured **1,322-1,619 ms** on real hardware, which
    looked like a slow network and was actually scheduler churn. It is FATAL when
    the handshake runs as a parked task that a rendered frame advances a bounded
    number of steps at a time: the same read then needs hundreds of frames, so
    the whole-handshake ``connect_timeout_ms`` always wins. Measured: three
    hardware boots on the parked path recorded ``upgrade_ms=0`` and never sent a
    ``phx_join``; given a 20,000 ms cap instead of 5,000 one sat in this leg for
    **14,651 ms** and still finished nothing.

    Reading in bulk turns ~300 awaits into one or two -- the response arrives in
    one or two TLS records -- and it is a strict improvement on the blocking path
    too. The BOUND IS UNCHANGED in the only way that matters: nothing is ever
    read past ``limit`` bytes, so a peer that never sends the terminating blank
    line is refused rather than allowed to allocate.
    """

    if limit < 4:
        raise ValueError("WebSocket Upgrade headers exceeded limit")
    buffer = bytearray()
    while True:
        end = buffer.find(b"\r\n\r\n")
        if end >= 0:
            break
        remaining = limit - len(buffer)
        if remaining <= 0:
            raise ValueError("WebSocket Upgrade headers exceeded limit")
        # ONE await per record, bounded by what is still allowed. `read` returns
        # what has arrived rather than waiting for a full buffer, so the loop
        # runs once per TLS record and not once per byte.
        #
        # THE ASK IS CHUNKED, and the reason is FRAGMENTATION rather than size.
        # MicroPython's stream `read(n)` sizes its buffer from `n`, so asking for
        # the whole `max_header_size` would put an ~8 KB transient allocation in
        # a rendered frame where the per-byte loop it replaces asked for one
        # byte. The heap is NOT the argument -- this badge measures ~8 MB free
        # (8 MB PSRAM), so 8 KB is ~0.1% of it. The argument is contiguity: on
        # this exact hardware a 384,768 B allocation FAILED with 7,265,280 B free
        # (`docs/engineering-findings.md`), so what a repeated multi-KB transient
        # costs is the largest available block over thousands of handshakes, not
        # the free total. A real 101 response is ~180-350 bytes, so one chunk
        # still covers it in a single await and the cumulative `limit` is
        # unchanged: this bounds the ALLOCATION, not the total.
        ask = remaining if remaining < UPGRADE_READ_CHUNK else UPGRADE_READ_CHUNK
        chunk = await _wait_for(reader.read(ask), timeout_ms)
        if not chunk:
            raise ConnectionError("peer closed during WebSocket Upgrade")
        buffer.extend(chunk)
    head = bytes(buffer[:end + 2])
    leftover = bytes(buffer[end + 4:])
    lines = head.split(b"\r\n")
    status_line = lines[0] + b"\r\n"
    header_lines = [line + b"\r\n" for line in lines[1:] if line]
    if len(header_lines) > 64:
        raise ValueError("WebSocket Upgrade had too many headers")
    return status_line, header_lines, leftover


def _header_tokens(value):
    return tuple(piece.strip().lower() for piece in value.split(b",") if piece.strip())


def _printable_ascii(raw, limit=40):
    """``bytes`` -> a short printable-ASCII string, for an error message only.

    Anything outside 0x20-0x7E becomes ``?``. A refusal's status line is the one
    piece of SERVER text this module puts in an exception, and that exception is
    rendered onto a serial console -- so a control character or a UTF-8 sequence
    in it is a peer choosing what an operator's terminal does.
    """

    try:
        text = bytes(raw)[:limit].decode("ascii")
    except Exception:
        return "?"
    return "".join(
        character if 32 <= ord(character) < 127 else "?" for character in text)


def validate_upgrade_response(status_line, header_lines, key):
    """Validate an RFC 6455 server Upgrade response and return normalized headers."""

    status_parts = status_line.rstrip(b"\r\n").split(b" ", 2)
    if len(status_parts) < 2 or status_parts[:2] != [b"HTTP/1.1", b"101"]:
        # THE STATUS GOES IN THE MESSAGE, and it is the difference between a
        # diagnosable refusal and the single word `ValueError`. A caller renders
        # this through `"{}: {}".format(exc.__class__.__name__, str(exc))`, so
        # without the code a 403, a 429 and a malformed 200 all reach the log
        # identically -- and at the venue nobody is attaching a probe to read the
        # wire the information was already on.
        #
        # BOUNDED AND SANITISED, because this is server text on a path that ends
        # at a serial console: the first two tokens only (protocol and code),
        # each capped, so a peer cannot push a long or control-character-laden
        # reason phrase through it. The REASON PHRASE IS DROPPED -- it is free
        # text and the code is the part that means something.
        detail = b" ".join(part[:16] for part in status_parts[:2])
        raise ValueError(
            "WebSocket server did not return HTTP/1.1 status 101: {}".format(
                _printable_ascii(detail)))
    values = {}
    for raw in header_lines:
        line = raw.rstrip(b"\r\n")
        if not line or b":" not in line:
            raise ValueError("malformed WebSocket Upgrade header")
        name, value = line.split(b":", 1)
        name = name.strip().lower()
        value = value.strip()
        if not name or any(character < 33 or character > 126 for character in name):
            raise ValueError("malformed WebSocket Upgrade header name")
        values.setdefault(name, []).append(value)
    upgrades = values.get(b"upgrade", ())
    if len(upgrades) != 1 or upgrades[0].lower() != b"websocket":
        raise ValueError("invalid WebSocket Upgrade header")
    connection_tokens = ()
    for connection in values.get(b"connection", ()):
        connection_tokens += _header_tokens(connection)
    if b"upgrade" not in connection_tokens:
        raise ValueError("invalid WebSocket Connection header")
    accepts = values.get(b"sec-websocket-accept", ())
    if len(accepts) != 1:
        raise ValueError("WebSocket Upgrade needs one Sec-WebSocket-Accept")
    supplied = accepts[0]
    expected = binascii.b2a_base64(hashlib.sha1(key + GUID).digest()).strip()
    if supplied != expected:
        raise ValueError("invalid Sec-WebSocket-Accept")
    return dict((name, b", ".join(items)) for name, items in values.items())


class WSMsgType:
    TEXT = 1
    BINARY = 2
    CLOSE = 8
    PING = 9
    PONG = 10
    ERROR = 258


class WebSocketMessage:
    def __init__(self, opcode, data):
        self.type = opcode
        self.data = data


class WebSocketClient:
    CONT = 0
    TEXT = 1
    BINARY = 2
    CLOSE = 8
    PING = 9
    PONG = 10

    def __init__(
        self,
        headers=None,
        connect_timeout_ms=10000,
        io_timeout_ms=10000,
        max_header_size=8192,
        max_frame_size=4096,
        max_message_size=4096,
        ping_interval_ms=None,
        pong_timeout_ms=None,
        idle_timeout_ms=INHERIT_IO_TIMEOUT,
        clock=None,
    ):
        self.params = dict(headers or {})
        self.connect_timeout_ms = int(connect_timeout_ms)
        self.io_timeout_ms = int(io_timeout_ms)
        self.max_header_size = int(max_header_size)
        self.max_frame_size = int(max_frame_size)
        self.max_message_size = int(max_message_size)
        if self.connect_timeout_ms < 1 or self.io_timeout_ms < 1:
            raise ValueError("WebSocket timeouts must be positive")
        if self.max_header_size < 128 or self.max_frame_size < 1:
            raise ValueError("WebSocket bounds are too small")
        if self.max_message_size < self.max_frame_size:
            raise ValueError("message cap must be at least frame cap")
        # The deadline for the FIRST two bytes of a frame is separate from the
        # deadline for the rest of it: silence between frames is normal on a
        # subscription, while a stall mid-frame is a broken peer. None waits
        # indefinitely and leaves liveness to the ping timer.
        if idle_timeout_ms is INHERIT_IO_TIMEOUT:
            self.idle_timeout_ms = self.io_timeout_ms
        elif idle_timeout_ms is None:
            self.idle_timeout_ms = None
        else:
            self.idle_timeout_ms = int(idle_timeout_ms)
            if self.idle_timeout_ms < 1:
                raise ValueError("idle timeout must be positive")
        self.ping_interval_ms = None if ping_interval_ms is None else int(ping_interval_ms)
        if self.ping_interval_ms is None:
            self.pong_timeout_ms = None
        else:
            if self.ping_interval_ms < 1:
                raise ValueError("ping interval must be positive")
            if pong_timeout_ms is None:
                pong_timeout_ms = max(1, self.ping_interval_ms // 2)
            self.pong_timeout_ms = int(pong_timeout_ms)
            if self.pong_timeout_ms < 1 or self.pong_timeout_ms > self.ping_interval_ms:
                raise ValueError("pong timeout must be positive and at most the interval")
        self.clock = clock or _ticks_ms
        self.closed = False
        self.reader = None
        self.writer = None
        # Retained separately until deferred TLS succeeds.  The pinned mbedTLS
        # binding detaches the raw socket before raising a fatal handshake
        # error, so closing only the TLS writer can otherwise leak a PCB.
        self._raw_socket = None
        self._opening_transport = None
        self.pings_sent = 0
        self.pongs_matched = 0
        self._ping_sequence = 0
        self._ping_due_ms = None
        self._pending_ping = None
        self._pong_deadline_ms = None
        self._fragment_opcode = None
        self._fragment = bytearray()
        #: Bytes the bulk Upgrade read took that belong to the FRAME reader, or
        #: ``b""``. See :meth:`_pull_exact`. Set on every handshake, so a reused
        #: client cannot carry one session's tail into the next.
        self._prebuffer = b""

    async def connect(self, value, ssl=None, connect_host=None, trace=None):
        uri = urlparse(value)
        if uri.protocol == "wss" and ssl is None:
            ssl = True
        try:
            await _wait_for(self._handshake(uri, ssl, connect_host, trace),
                            self.connect_timeout_ms)
        except BaseException:
            try:
                await _close_writer(self.writer)
            finally:
                self.reader = None
                self.writer = None
                self._close_opening_transport()
                self._close_owned_raw()
            raise
        self._note_activity()
        return self

    async def _handshake(self, uri, ssl, connect_host=None, trace=None):
        # CONNECT BY ADDRESS, VERIFY BY NAME. `connect_host` lets a caller that
        # has already resolved the endpoint hand the address in, because on
        # MicroPython the name lookup happens INSIDE `open_connection` -- it is
        # blocking, it takes no timeout at any version, and `connect_timeout_ms`
        # cannot interrupt it because `_wait_for` cannot interrupt a blocking C
        # call. `server_hostname` keeps SNI and certificate verification on the
        # URL's own hostname, so this is a routing shortcut and never a trust
        # one, and the `Host:`/`Origin:` headers below are unchanged.
        #
        # Only passed when it actually differs AND the transport is TLS: CPython's
        # `open_connection` rejects `server_hostname` without `ssl`, and a plain
        # `ws://` connect by address wants no SNI anyway.
        #
        # ``trace``: the whole name resolution is INSIDE this call on
        # MicroPython, so ``tcp_ms`` necessarily contains a cold ``getaddrinfo``
        # when ``connect_host`` is not supplied.
        _trace_phase(trace, "tcp")
        entered = self.clock()
        if connect_host and connect_host != uri.hostname and ssl:
            self.reader, self.writer = await _open_connection_owned(
                self,
                connect_host, uri.port, ssl=ssl, server_hostname=uri.hostname
            )
        else:
            self.reader, self.writer = await _open_connection_owned(
                self,
                connect_host or uri.hostname, uri.port, ssl=ssl
            )
        _trace_span(trace, "tcp_ms", self.clock, entered)
        key = binascii.b2a_base64(
            bytes(random.getrandbits(8) for _ in range(16))
        ).strip()
        headers = dict(self.params)
        headers.update(
            {
                "Host": "{}:{}".format(uri.hostname, uri.port),
                "Connection": "Upgrade",
                "Upgrade": "websocket",
                "Sec-WebSocket-Key": key.decode(),
                "Sec-WebSocket-Version": "13",
                "Origin": "{}://{}:{}".format(
                    "https" if uri.protocol == "wss" else "http",
                    uri.hostname,
                    uri.port,
                ),
            }
        )
        request = "GET {} HTTP/1.1\r\n{}\r\n\r\n".format(
            uri.path,
            "\r\n".join("{}: {}".format(name, value) for name, value in headers.items()),
        ).encode()
        if len(request) > self.max_header_size:
            raise ValueError("WebSocket request headers exceeded limit")
        # ``trace``: ONE WRITE, and on a TLS transport it carries the ENTIRE
        # deferred handshake as well as this flush -- MicroPython's
        # ``open_connection`` wraps with ``do_handshake_on_connect=False``, so
        # the first positive write is what drives it.
        _trace_phase(trace, "ws_tls")
        entered = self.clock()
        await _writer_write(self.writer, request, self.io_timeout_ms)
        # The first positive write drove deferred TLS to completion.  The
        # stream is now the sole transport owner; until this line, fatal TLS
        # cleanup also needs the separate raw reference above.
        self._handoff_owned_raw()
        _trace_span(trace, "ws_tls_ms", self.clock, entered)

        _trace_phase(trace, "upgrade")
        entered = self.clock()
        status_line, response_headers, leftover = await _read_upgrade_head(
            self.reader, self.max_header_size, self.io_timeout_ms
        )
        # BYTES AFTER THE BLANK LINE ARE THE FRAME READER'S, and dropping them
        # would corrupt the first frame. Normally empty -- the server has nothing
        # to say until we send `phx_join` -- but a pipelining peer is legal and
        # the bulk read cannot un-read what it took.
        self._prebuffer = leftover
        validate_upgrade_response(status_line, response_headers, key)
        _trace_span(trace, "upgrade_ms", self.clock, entered)
        _trace_phase(trace, "upgraded")

    @classmethod
    def _encode_websocket_frame(cls, opcode, payload):
        if isinstance(payload, str):
            payload = payload.encode()
        else:
            payload = bytes(payload)
        length = len(payload)
        first = 0x80 | opcode
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        mask = struct.pack("!I", random.getrandbits(32))
        masked = bytes(value ^ mask[index & 3] for index, value in enumerate(payload))
        return header + mask + masked

    def _note_activity(self):
        """Any inbound frame proves the peer is alive, so defer the next ping."""

        if self.ping_interval_ms is not None:
            self._ping_due_ms = _ticks_add(self.clock(), self.ping_interval_ms)

    def _match_pong(self, payload):
        if self._pending_ping is not None and payload == self._pending_ping:
            self._pending_ping = None
            self._pong_deadline_ms = None
            self.pongs_matched += 1

    async def service_heartbeat(self):
        """Send a client ping when one is due; raise when a pong is overdue.

        The caller drives this from its own loop instead of the client owning a
        background task: a badge pumps asyncio once per rendered frame, and a
        hidden task there is an invisible frame cost and an invisible lifetime.
        """

        if self.ping_interval_ms is None or self.closed or self.writer is None:
            return False
        now = self.clock()
        if self._pending_ping is not None:
            if _ticks_diff(now, self._pong_deadline_ms) >= 0:
                raise WebSocketLivenessError("WebSocket peer missed the pong deadline")
            return False
        if self._ping_due_ms is None:
            self._ping_due_ms = _ticks_add(now, self.ping_interval_ms)
            return False
        if _ticks_diff(now, self._ping_due_ms) < 0:
            return False
        self._ping_sequence = (self._ping_sequence + 1) & 0xFFFFFF
        payload = b"pt" + str(self._ping_sequence).encode()
        self._pending_ping = payload
        self._pong_deadline_ms = _ticks_add(now, self.pong_timeout_ms)
        self._ping_due_ms = _ticks_add(now, self.ping_interval_ms)
        await self.send(payload, self.PING)
        self.pings_sent += 1
        return True

    async def _pull_exact(self, size, timeout_ms):
        """``readexactly``, but serving any post-handshake leftover first.

        The Upgrade head is read in bulk (see :func:`_read_upgrade_head`), so a
        pipelining peer's first frame bytes can arrive in the same record as the
        blank line. This is the one place that difference is absorbed; every
        frame read goes through it, so no caller has to know.
        """

        pre = self._prebuffer
        if not pre:
            return await _wait_for(self.reader.readexactly(size), timeout_ms)
        if len(pre) >= size:
            self._prebuffer = pre[size:]
            return pre[:size]
        self._prebuffer = b""
        return pre + await _wait_for(
            self.reader.readexactly(size - len(pre)), timeout_ms)

    async def _read_exact(self, size):
        return await self._pull_exact(size, self.io_timeout_ms)

    async def _read_frame(self):
        first, second = await self._pull_exact(2, self.idle_timeout_ms)
        if first & 0x70:
            raise ValueError("WebSocket server set unsupported RSV bits")
        final = bool(first & 0x80)
        opcode = first & 0x0F
        if opcode not in VALID_OPCODES:
            raise ValueError("invalid WebSocket opcode")
        if second & 0x80:
            raise ValueError("server WebSocket frames must not be masked")
        length_code = second & 0x7F
        if length_code == 126:
            (length,) = struct.unpack("!H", await self._read_exact(2))
            if length < 126:
                raise ValueError("non-canonical WebSocket frame length")
        elif length_code == 127:
            raw = await self._read_exact(8)
            if raw[0] & 0x80:
                raise ValueError("invalid 64-bit WebSocket frame length")
            (length,) = struct.unpack("!Q", raw)
            if length < 65536:
                raise ValueError("non-canonical WebSocket frame length")
        else:
            length = length_code
        control = opcode >= self.CLOSE
        if control and (not final or length > MAX_CONTROL_PAYLOAD):
            raise ValueError("invalid WebSocket control frame")
        # RFC 6455 already bounds control payloads at 125 bytes. max_frame_size
        # is an application-payload cap, so applying it to control frames only
        # made a small cap unable to answer a legal server PING.
        if not control and length > self.max_frame_size:
            raise ValueError("incoming WebSocket frame exceeds cap")
        payload = await self._read_exact(length) if length else b""
        self._note_activity()
        return opcode, payload, final

    @staticmethod
    def _decode_payload(opcode, payload):
        if opcode == WebSocketClient.TEXT:
            return payload.decode("utf-8")
        return payload

    async def receive(self):
        while True:
            opcode, payload, final = await self._read_frame()
            if opcode >= self.CLOSE:
                if opcode == self.PING:
                    await self.send(payload, self.PONG)
                elif opcode == self.PONG:
                    self._match_pong(payload)
                elif opcode == self.CLOSE:
                    if len(payload) == 1:
                        raise ValueError("invalid WebSocket close payload")
                    if not self.closed:
                        await self.send(payload, self.CLOSE)
                    self.closed = True
                return opcode, payload

            if opcode == self.CONT:
                if self._fragment_opcode is None:
                    raise ValueError("unexpected WebSocket continuation")
            else:
                if self._fragment_opcode is not None:
                    raise ValueError("new WebSocket message during fragmentation")
                if final:
                    if len(payload) > self.max_message_size:
                        raise ValueError("incoming WebSocket message exceeds cap")
                    return opcode, self._decode_payload(opcode, payload)
                self._fragment_opcode = opcode

            if len(self._fragment) + len(payload) > self.max_message_size:
                raise ValueError("incoming fragmented WebSocket message exceeds cap")
            self._fragment.extend(payload)
            if final:
                complete_opcode = self._fragment_opcode
                complete = bytes(self._fragment)
                self._fragment_opcode = None
                self._fragment = bytearray()
                return complete_opcode, self._decode_payload(complete_opcode, complete)

    async def send(self, data, opcode=None):
        if self.closed:
            raise ConnectionError("WebSocket is closed")
        if opcode is None:
            opcode = self.TEXT if isinstance(data, str) else self.BINARY
        if opcode not in (self.TEXT, self.BINARY, self.CLOSE, self.PING, self.PONG):
            raise ValueError("invalid outgoing WebSocket opcode")
        payload_length = len(data.encode() if isinstance(data, str) else data)
        if opcode >= self.CLOSE:
            if payload_length > MAX_CONTROL_PAYLOAD:
                raise ValueError("outgoing WebSocket message exceeds cap")
        elif payload_length > self.max_message_size or payload_length > self.max_frame_size:
            raise ValueError("outgoing WebSocket message exceeds cap")
        await _writer_write(
            self.writer,
            self._encode_websocket_frame(opcode, data),
            self.io_timeout_ms,
        )

    async def close(self):
        if not self.closed and self.writer is not None:
            try:
                await self.send(b"", self.CLOSE)
            finally:
                self.closed = True

    async def close_transport(self):
        try:
            await _close_writer(self.writer)
        finally:
            self.reader = None
            self.writer = None
            self._close_opening_transport()
            self._close_owned_raw()

    def _close_opening_transport(self):
        transport = self._opening_transport
        self._opening_transport = None
        if transport is None:
            return
        try:
            transport.close()
        except BaseException:
            pass

    def _handoff_owned_raw(self):
        self._raw_socket = None

    def _close_owned_raw(self):
        raw = self._raw_socket
        self._raw_socket = None
        if raw is None:
            return
        try:
            raw.close()
        except BaseException:
            pass


class ClientWebSocketResponse:
    def __init__(self, client):
        self.ws = client

    async def close(self):
        """Send the close frame and release the transport, as CPython aiohttp does."""

        try:
            await self.ws.close()
        finally:
            await self.ws.close_transport()

    async def close_transport(self):
        """Release the transport WITHOUT sending a close frame.

        The client half of `close()` was already reachable on the inner object
        (`__aexit__` uses it); this is the same call named on the response, so a
        caller holding only the response can take it. It exists for a peer that
        is known unreachable -- sending a CLOSE frame there is a `drain()` under
        `io_timeout_ms` for a courtesy nobody will read. Marks the socket closed
        so a later `send` raises rather than writing into a released writer.
        """

        self.ws.closed = True
        await self.ws.close_transport()

    async def send_str(self, data):
        if not isinstance(data, str):
            raise TypeError("data argument must be str")
        await self.ws.send(data)

    async def send_bytes(self, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data argument must be bytes-like")
        await self.ws.send(data)

    async def ping(self, data=b""):
        await self.ws.send(data, self.ws.PING)

    async def service_heartbeat(self):
        return await self.ws.service_heartbeat()

    async def receive(self):
        return WebSocketMessage(*(await self.ws.receive()))

    async def receive_str(self):
        opcode, data = await self.ws.receive()
        if opcode != self.ws.TEXT:
            raise TypeError("received non-text WebSocket message")
        return data


class _WSRequestContextManager:
    def __init__(self, coroutine):
        self.coroutine = coroutine
        self.response = None

    def _await_iterator(self):
        """The runtime's iterator for one native coroutine.

        CPython coroutine objects expose ``__await__``. The pinned MicroPython
        runtime represents an ``async def`` call as a generator with ``__next__``
        and no visible ``__await__``/``__iter__`` attributes. Returning that
        generator directly is its await protocol; calling a missing
        ``__await__`` was the device-only failure this compatibility class must
        hide.
        """

        method = getattr(self.coroutine, "__await__", None)
        return method() if method is not None else self.coroutine

    def __await__(self):
        """Allow `await session.ws_connect(...)` as CPython aiohttp does.

        An event-driven client cannot scope its socket to a `with` block, so it
        needs the awaitable form and then owns `close()` itself.
        """

        return self._await_iterator()

    def __iter__(self):
        """MicroPython's await protocol asks the wrapper for an iterator."""

        return self._await_iterator()

    async def __aenter__(self):
        self.response = await self.coroutine
        return self.response

    async def __aexit__(self, *args):
        if self.response is not None:
            try:
                await self.response.close()
            except Exception:
                pass
            await self.response.ws.close_transport()
        return False


class ClientSession:
    def __init__(
        self,
        headers=None,
        connect_timeout_ms=10000,
        io_timeout_ms=10000,
        max_header_size=8192,
        max_frame_size=4096,
        max_message_size=4096,
        ping_interval_ms=None,
        pong_timeout_ms=None,
        idle_timeout_ms=INHERIT_IO_TIMEOUT,
        clock=None,
    ):
        self.headers = dict(headers or {})
        self.options = {
            "connect_timeout_ms": connect_timeout_ms,
            "io_timeout_ms": io_timeout_ms,
            "max_header_size": max_header_size,
            "max_frame_size": max_frame_size,
            "max_message_size": max_message_size,
            "ping_interval_ms": ping_interval_ms,
            "pong_timeout_ms": pong_timeout_ms,
            "idle_timeout_ms": idle_timeout_ms,
            "clock": clock,
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def _ws_connect(self, url, ssl=None, connect_host=None, trace=None):
        client = WebSocketClient(self.headers, **self.options)
        await client.connect(url, ssl=ssl, connect_host=connect_host,
                             trace=trace)
        return ClientWebSocketResponse(client)

    def ws_connect(self, url, ssl=None, connect_host=None, trace=None):
        """Open one WebSocket session.

        ``connect_host`` is a pre-resolved address for the URL's host: the socket
        goes there and SNI/verification stay on the hostname. ``None`` resolves
        the name inside ``open_connection`` as before. See :meth:`WebSocketClient._handshake`.

        ``trace`` is an optional caller-owned dict this handshake writes its own
        leg spans into (``tcp_ms``/``ws_tls_ms``/``upgrade_ms``) plus the
        ``phase`` it is in. Diagnostics only: nothing here reads it back, and
        omitting it is byte-identical to the call before it existed.
        """
        return _WSRequestContextManager(
            self._ws_connect(url, ssl=ssl, connect_host=connect_host,
                             trace=trace))
