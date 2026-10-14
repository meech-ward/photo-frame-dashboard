"""Bounded REST and Realtime over the badge's proven cooperative WebSocket code.

This module is project-neutral. It uses normal Supabase Auth sessions, never the
conference's fleet token or command service. poll() advances bounded asyncio turns.
"""
import asyncio
import errno
import json
import os
import struct
import sys
import time

MAX_BODY = 32768
MAX_PHOTO = 327680


def valid_jpeg(body):
    # The companion emits one baseline 8-bit RGB scan. Header dimensions must
    # be checked before native decode allocates a full RGBA image; progressive
    # or multi-scan files have not been proved on the Tufty's JPEG decoder.
    if len(body) < 4 or not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
        return False
    offset = 2
    frame = quantization = huffman = False
    while offset < len(body) - 2:
        if body[offset] != 255:
            return False
        while offset < len(body) and body[offset] == 255:
            offset += 1
        if offset >= len(body):
            return False
        marker = body[offset]
        offset += 1
        if marker in (0, 216, 217) or 208 <= marker <= 215 or offset + 2 > len(body):
            return False
        length = struct.unpack(">H", body[offset:offset + 2])[0]
        end = offset + length
        if length < 2 or end > len(body) - 2:
            return False
        if marker == 192:
            if (frame or length != 17 or body[offset + 2] != 8
                    or struct.unpack(">HH", body[offset + 3:offset + 7]) != (240, 320)
                    or body[offset + 7] != 3):
                return False
            frame = True
        elif 193 <= marker <= 207 and marker != 196:
            return False
        elif marker == 219:
            quantization = True
        elif marker == 196:
            huffman = True
        elif marker == 218:
            if (not frame or not quantization or not huffman or length != 12 or end >= len(body) - 2
                    or body[offset + 2] != 3 or body[end - 3:end] != b"\x00\x3f\x00"):
                return False
            # C-backed find skips entropy bytes without a Python loop per pixel.
            # Escaped FF bytes and restart markers are legal; a second scan,
            # early EOI or missing EOI is an incomplete/unsupported photograph.
            cursor = end
            while cursor < len(body):
                cursor = body.find(b"\xff", cursor)
                if cursor < 0 or cursor + 1 >= len(body):
                    return False
                while cursor + 1 < len(body) and body[cursor + 1] == 255:
                    cursor += 1
                marker = body[cursor + 1]
                if marker == 217:
                    return cursor + 2 == len(body)
                if marker != 0 and not 208 <= marker <= 215:
                    return False
                cursor += 2
            return False
        offset = end
    return False


def valid_photo(body):
    if body.startswith(b"\xff\xd8"):
        return valid_jpeg(body)
    # Fixed native dimensions cap decoded memory as well as download bytes.
    # Interlaced/high-depth files are outside the companion converter contract.
    return (len(body) >= 33 and body.startswith(b"\x89PNG\r\n\x1a\n")
            and body[8:16] == b"\x00\x00\x00\rIHDR"
            and struct.unpack(">II", body[16:24]) == (320, 240)
            and body[24] == 8 and body[25] in (2, 3, 6)
            and body[26:29] == b"\x00\x00\x00")


def milliseconds():
    fn = getattr(time, "ticks_ms", None)
    return fn() if fn else int(time.monotonic() * 1000)


async def wait(awaitable, seconds=10):
    fn = getattr(asyncio, "wait_for_ms", None)
    return await fn(awaitable, seconds * 1000) if fn else await asyncio.wait_for(awaitable, seconds)


class HTTP:
    def __init__(self, host, port, context, connect_host=None):
        self.host, self.port, self.context = host, port, context
        self.connect_host = connect_host
        self.reader = self.writer = None
        self.owner = None
        self.buffer = b""
        self.limit = MAX_BODY

    async def open(self):
        from aiohttp.aiohttp_ws import WebSocketClient, _open_connection_owned
        self.owner = WebSocketClient(connect_timeout_ms=10000)
        self.reader, self.writer = await wait(_open_connection_owned(
            self.owner, self.connect_host or self.host, self.port,
            ssl=self.context, server_hostname=self.host if self.context else None))

    async def line(self):
        # Bulk reads preserve the Upgrade fix: one await per block, not per byte.
        while b"\r\n" not in self.buffer:
            block = await wait(self.reader.read(512))
            if not block:
                raise OSError("truncated response")
            self.buffer += block
            if b"\r\n" not in self.buffer and len(self.buffer) > 4096:
                raise ValueError("header exceeds cap")
        result, self.buffer = self.buffer.split(b"\r\n", 1)
        if len(result) > 4096:
            raise ValueError("header exceeds cap")
        return result

    async def exact(self, length):
        if length < 0 or length > self.limit:
            raise ValueError("response exceeds cap")
        result = bytearray()
        while len(result) < length:
            if self.buffer:
                size = min(length - len(result), len(self.buffer))
                result.extend(self.buffer[:size])
                self.buffer = self.buffer[size:]
            else:
                block = await wait(self.reader.read(min(2048, length - len(result))))
                if not block:
                    raise OSError("truncated response")
                result.extend(block)
            # No single ready HTTP response consumes an entire interactive frame.
            await asyncio.sleep(0)
        return bytes(result)

    async def request(self, path, headers, body=None, method="POST", max_bytes=MAX_BODY):
        self.limit = max_bytes
        if self.writer is None:
            await self.open()
        payload = b"" if body is None else json.dumps(body).encode()
        host = self.host if self.port in (80, 443) else self.host + ":" + str(self.port)
        lines = [method + " " + path + " HTTP/1.1", "Host: " + host,
                 "Connection: keep-alive", "Accept-Encoding: identity",
                 "Content-Length: " + str(len(payload))]
        for name, value in headers.items():
            if "\r" in str(value) or "\n" in str(value):
                raise ValueError("invalid header")
            lines.append(name + ": " + str(value))
        try:
            self.writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + payload)
            await wait(self.writer.drain())
            first = await self.line()
            status = int(first.split(b" ")[1])
            response_headers = {}
            count = 0
            while True:
                line = await self.line()
                count += len(line)
                if count > 4096:
                    raise ValueError("header exceeds cap")
                if not line:
                    break
                key, value = line.split(b":", 1)
                response_headers[key.decode().lower()] = value.decode().strip()
            if "chunked" in response_headers.get("transfer-encoding", "").lower():
                result = bytearray()
                while True:
                    length = int((await self.line()).split(b";", 1)[0], 16)
                    if not length:
                        # Trailers are headers too. Without this shared bound a
                        # zero-byte body could still consume an endless stream.
                        trailer_bytes = 0
                        while True:
                            trailer = await self.line()
                            trailer_bytes += len(trailer) + 2
                            if trailer_bytes > 4096:
                                raise ValueError("header exceeds cap")
                            if not trailer:
                                break
                        break
                    if len(result) + length > self.limit:
                        raise ValueError("response exceeds cap")
                    result.extend(await self.exact(length))
                    if await self.exact(2) != b"\r\n":
                        raise ValueError("invalid chunk")
                data = bytes(result)
            elif status in (204, 304):
                data = b""
            elif "content-length" in response_headers:
                data = await self.exact(int(response_headers["content-length"]))
            else:
                raise ValueError("unbounded response")
            if response_headers.get("connection", "").lower() == "close":
                await self.close()
            return status, data
        except BaseException:
            await self.close()
            raise

    async def close(self):
        from aiohttp.aiohttp_ws import _close_writer
        await _close_writer(self.writer)
        if self.owner:
            self.owner._close_opening_transport()
            self.owner._close_owned_raw()
        self.reader = self.writer = self.owner = None
        self.buffer = b""


class RPC:
    """The personal SDK's client.rpc(name, params).execute_async() seam."""
    def __init__(self, client, name, params):
        self.client, self.name, self.params = client, name, params

    async def execute_async(self):
        client = self.client
        try:
            status, body = await client.http.request("/rest/v1/rpc/" + self.name,
                {"apikey": client.key, "Authorization": "Bearer " + client.session.get("access_token", client.key),
                 "Content-Type": "application/json"}, self.params)
        except Exception:
            return {"error": {"message": "Unable to connect"}, "status_code": 500}
        try:
            data = json.loads(body) if body else None
        except (ValueError, UnicodeError):
            return {"error": {"message": "Invalid project response"}, "error_type": "decode", "status_code": status}
        if 200 <= status < 300:
            return {"data": data, "status_code": status}
        return {"error": data if isinstance(data, dict) else {"message": "Request rejected"}, "status_code": status}


class SupabaseTransport:
    def __init__(self, config, session):
        self.config = config
        from auth_client import AuthClient, session_record
        self.session = dict(session) if session_record(session) else {}
        from aiohttp.aiohttp_ws import urlparse
        url = config["url"].rstrip("/")
        self.secure = url.startswith("https://")
        if not self.secure and not config.get("allow_local_http", False):
            raise ValueError("HTTPS required")
        uri = urlparse(("wss" if self.secure else "ws") + url[url.index(":"):])
        if uri.path != "/":
            raise ValueError("project URL must not have a path")
        self.host, self.port = uri.hostname, uri.port
        self.key = config["publishable_key"]
        if self.key.startswith("sb_secret_"):
            raise ValueError("secret key cannot be installed on a badge")
        self.context = None
        if self.secure:
            import ssl
            if getattr(sys.implementation, "name", "") == "micropython":
                from verified_tls import VerifiedTLSShim
                root = config.get("app_root", "/system/apps/homehq")
                paths = tuple(root + "/ca/" + name for name in
                              ("gts-we1.der", "gts-root-r4.der", "gts-root-r1.der"))
                shim = VerifiedTLSShim(ssl, paths)
                self.context = shim.SSLContext(shim.PROTOCOL_TLS_CLIENT)
            else:
                self.context = ssl.create_default_context()
        self.connect_host = config.get("connect_host")
        self.http = HTTP(self.host, self.port, self.context, self.connect_host)
        from aiohttp import ClientSession
        from realtime.client import RealtimeClient
        from ws_backoff import BackoffPolicy
        # Realtime may stay silent until the 20-second Phoenix heartbeat. A
        # 3-second idle deadline drops healthy subscriptions; keep that bound
        # only for incomplete frames and let the heartbeat own peer liveness.
        self.ws = ClientSession(connect_timeout_ms=10000, io_timeout_ms=3000,
                                idle_timeout_ms=None, max_frame_size=8192, max_message_size=8192)

        async def connect(url):
            return await self.ws.ws_connect(url, ssl=self.context, connect_host=self.connect_host)

        def new_realtime():
            return RealtimeClient(
                ("wss" if self.secure else "ws") + "://" + self.host + ":" + str(self.port) + "/realtime/v1/websocket",
                self.key, connect, access_token=self.session.get("access_token"), allow_plaintext=not self.secure,
                backoff_factory=BackoffPolicy, backoff_reset="first_join")
        self._new_realtime = new_realtime
        self.realtime = new_realtime()
        # Household identity comes from the authorized snapshot, never the Auth
        # user id: several ordinary accounts can share one private channel.
        self.home_id = config.get("home_id")
        if self.home_id:
            self.realtime.channel("realtime:homehq:" + self.home_id, private=True)
        self._bind_pending = None
        self.auth = AuthClient(self)
        self.auth_state = "signed_in" if self.session else "signed_out"
        self.auth_error = None
        self.loop = asyncio.get_event_loop()
        self.task = None
        self.connect_task = None
        self.events = []
        self.ready = False
        self.joined = False
        self.refresh_at = milliseconds()
        self.expires_at_ms = None
        self.retry_at = 0
        self._photos = []
        self._photo_active = None
        self._wlan = None
        self._wifi_attempt = 0
        self._wifi_connected = False
        self._wifi_error = False

    @staticmethod
    def clock():
        return milliseconds()

    def bind_home(self, home_id):
        if not isinstance(home_id, str) or not home_id or home_id == self.home_id:
            return
        self._bind_pending = home_id

    async def _bind_home(self):
        await self.realtime.close_transport()
        self.realtime = self._new_realtime()
        self.home_id, self._bind_pending = self._bind_pending, None
        self.realtime.channel("realtime:homehq:" + self.home_id, private=True)
        self.joined = False

    def _start_auth(self, state, action):
        old = [task for task in (self.task, self.connect_task) if task and not task.done()]
        for task in old:
            task.cancel()
        self.auth_state, self.auth_error = state, None
        self.ready = self.joined = False
        self.connect_task = None
        self._photos = []
        self._photo_active = None
        self.events = []

        async def perform_auth():
            # Drain canceled owners before reusing HTTP response framing. Input
            # only queues this work; it never runs DNS/TLS inside a button press.
            for task in old:
                try:
                    await task
                except BaseException:
                    pass
            await self.http.close()
            await self.realtime.close_transport()
            self.home_id = self._bind_pending = None
            self.realtime = self._new_realtime()
            result = await action()
            if state == "signing_out":
                self.auth_state = "signed_out"
                self.events.append({"kind": "signed_out"})
            elif "error" in result:
                self.auth_state = "error"
                self.auth_error = "Check email and password." if result.get("status_code") in (400, 401, 422) else "Unable to connect. Try again."
                self.events.append({"kind": "auth_error", "message": self.auth_error})
            else:
                self.auth_state = "signed_in"
        async def perform():
            try:
                await perform_auth()
            except Exception:
                # A failed socket teardown/token push is a recoverable login
                # outcome, not an unobserved detached-task error or stuck form.
                self.auth.clear_session()
                self.auth_state = "error"
                self.auth_error = "Unable to connect. Try again."
                self.events.append({"kind": "auth_error", "message": self.auth_error})
        self.task = self.loop.create_task(perform())
        return True

    def start_login(self, email, password):
        if self.auth_state in ("signing_in", "signing_out"):
            return False
        async def action():
            return await self.auth.sign_in_with_password_async(email, password)
        return self._start_auth("signing_in", action)

    def start_logout(self):
        if self.auth_state in ("signing_in", "signing_out"):
            return False
        return self._start_auth("signing_out", lambda: self.auth.sign_out_async("local"))

    def wifi_ready(self):
        if getattr(sys.implementation, "name", "") != "micropython":
            return True
        import network
        if self._wlan is None:
            self._wlan = network.WLAN(network.STA_IF)
        if self._wlan.isconnected():
            self._wifi_connected = True
            self._wifi_error = False
            return True
        now = milliseconds()
        if now >= self._wifi_attempt and self.config.get("wifi_ssid"):
            self._wlan.active(True)
            self._wlan.connect(self.config["wifi_ssid"], self.config.get("wifi_password", ""))
            self._wifi_attempt = now + 15000
            self._wifi_error = False
        # poll() cannot advance the transport while Wi-Fi is missing. Without
        # this one hint per failed attempt, NO_AP stays Connecting forever and
        # a radio loss leaves stale Live status. Initial joining (status 1) is
        # still healthy progress; short roams do not discard the Realtime
        # socket/channel, which its own heartbeat and recovery already own.
        if (self._wlan.status() < 0 or self._wifi_connected) and not self._wifi_error:
            self.events.append({"kind": "error"})
            self._wifi_error = True
        self._wifi_connected = False
        return False

    async def refresh_session(self):
        result = await self.auth.refresh_session_async()
        if result.get("error_type") == "session_lost":
            self.auth.clear_session()
            await self.realtime.close_transport()
            self._photos = []
            self._photo_active = None
            self.auth_state = "signed_out"
            self.events.append({"kind": "auth_error", "message": "Sign in again."})
            return
        if "error" in result:
            raise OSError("session refresh failed")

    def request(self, name, args):
        if self.task is not None:
            raise RuntimeError("one HTTP request at a time")

        async def action():
            result = await self.rpc(name, args).execute_async()
            status = result["status_code"]
            if status == 401:
                self.refresh_at = 0
            if status == 404:
                data = result.get("error")
                if isinstance(data, dict) and data.get("code") == "PT404":
                    # This SQL code means the authenticated target row vanished.
                    # A generic endpoint/storage 404 remains a connection error.
                    self.events.append({"kind": "removed"})
                    return
            if "error" in result or status != 200:
                raise OSError("request rejected")
            self.events.append({"kind": "result", "data": result["data"]})
        self.task = self.loop.create_task(self.contain(action()))

    def rpc(self, func_name, params=None):
        # MicroPython ports omit str.isalnum(); explicit ASCII keeps the real
        # compiled RPC body usable instead of passing CPython-only tests.
        if not isinstance(func_name, str) or not func_name or any(
                not ("a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9" or c == "_") for c in func_name):
            raise ValueError("invalid RPC name")
        return RPC(self, func_name, {} if params is None else params)

    @property
    def can_request(self):
        # Authentication readiness does not mean the shared HTTP stream is free:
        # a refresh or photo download may still own its response framing.
        return self.auth_state == "signed_in" and self.ready and self.task is None

    async def contain(self, coroutine):
        try:
            await coroutine
        except Exception:
            self.ready = False
            # A failed download no longer owns its path. Keeping the active
            # marker would suppress that photograph forever after reconnection.
            self._photo_active = None
            self.retry_at = milliseconds() + 3000
            self.refresh_at = 0
            self.events.append({"kind": "error"})

    def photo(self, path, local_path):
        if not self.home_id or ".." in path or not path.startswith(self.home_id + "/"):
            return False
        # Rendering can request one URI through different candidate slots while
        # another download is active. The URI owns the job, not its slot tuple.
        if self._photo_active == path or any(queued[0] == path for queued in self._photos):
            return False
        self._photos = self._photos[-1:]
        self._photos.append((path, local_path))
        return True

    async def download_photo(self, path, local_path):
        # Service owns exactly these two cache files. Never let its deletion
        # path expand to credentials, another app's files, or a third slot.
        if (not isinstance(local_path, str) or ".." in local_path
                or local_path.rsplit("/", 1)[-1] not in ("homehq-photo-0.png", "homehq-photo-1.png", "homehq-photo-0.img", "homehq-photo-1.img")):
            raise ValueError("invalid photo slot")
        status, body = await self.http.request("/storage/v1/object/authenticated/homehq-photos/" + path,
            {"apikey": self.key, "Authorization": "Bearer " + self.session["access_token"]}, method="GET", max_bytes=MAX_PHOTO)
        if (status != 200 or len(body) > MAX_PHOTO or not valid_photo(body)
                or (local_path.endswith(".png") and not body.startswith(b"\x89PNG\r\n\x1a\n"))):
            raise ValueError("invalid photo")
        # The actual Tufty /state volume is 1 MiB: two 320 KiB photos plus
        # another temporary photo and ~103 KiB of existing/cache/Auth state do
        # not fit. Keep the old slot through HTTP/image validation, then release
        # only that evicted slot before writing: peak photo storage is 640 KiB.
        # Native image.load dispatches by magic, so .img holds either codec.
        # Retire the paired legacy PNG and either interrupted temporary file;
        # the format transition must still occupy exactly two logical slots.
        base = local_path.rsplit(".", 1)[0]
        paired = base + (".png" if local_path.endswith(".img") else ".img")
        for owned in (local_path, paired):
            for suffix in ("", ".tmp"):
                try:
                    os.remove(owned + suffix)
                except OSError as error:
                    if error.args[0] != errno.ENOENT:
                        raise
        temporary = local_path + ".tmp"
        try:
            view = memoryview(body)
            with open(temporary, "wb") as target:
                # Filesystem writes block even inside an async function. Small
                # writes return to input/rendering between chunks; memoryview
                # avoids another photo-sized copy while the body stays in RAM.
                for offset in range(0, len(body), 4096):
                    block = view[offset:offset + 4096]
                    if target.write(block) != len(block):
                        raise OSError("incomplete photo write")
                    await asyncio.sleep(0)
            os.rename(temporary, local_path)
        except BaseException:
            # A partial file cannot be presented as a cached photo or consume
            # the next retry's space. After power loss, wb truncates a leftover
            # owned temporary file before the next complete write.
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise
        self._photo_active = None
        self.events.append({"kind": "photo", "path": path, "local_path": local_path})

    async def turn(self):
        if self.task and self.task.done():
            self.task = None
        if self.connect_task and self.connect_task.done():
            self.connect_task = None
        now = milliseconds()
        if self._bind_pending and self.task is None and self.connect_task is None:
            await self._bind_home()
        if now < self.retry_at:
            await asyncio.sleep(0)
            return
        if self.auth_state == "signed_in" and self.task is None and now >= self.refresh_at:
            self.task = self.loop.create_task(self.contain(self.refresh_session()))
        delay = self.realtime.reconnect_delay_ms(now)
        # The generic client schedules reconnect and channel rejoin separately.
        # Respect its due tick while the UI keeps rendering; a socket that has
        # not successfully joined must not reset recovery to a tight loop.
        if (self.ready and self.home_id and self.connect_task is None and self.realtime.socket_state != "open"
                and (delay is None or delay <= 0)):
            self.connect_task = self.loop.create_task(self.contain(self.realtime.connect()))
        # Token refresh can fail while sending to a dead existing socket. Auth
        # readiness must not stop draining that socket's completed receive, or
        # every subsequent refresh sends into the same unreleased connection.
        for event in await self.realtime.service():
            if event.kind == "joined":
                self.joined = True
                self.events.append({"kind": "joined"})
            elif event.kind == "broadcast" and event.event == "changed":
                self.events.append({"kind": "changed"})
            elif event.kind in ("disconnected", "join_error", "channel_error"):
                self.joined = False
                self.events.append({"kind": "error"})
        if self.ready and self.task is None and self._photos:
            path, local_path = self._photos.pop(0)
            self._photo_active = path
            self.task = self.loop.create_task(self.contain(self.download_photo(path, local_path)))
        await asyncio.sleep(0)

    def poll(self):
        if self.wifi_ready():
            # A capped photo took 56 s on Tufty: ready HTTP/write stages each
            # waited for another rendered-loop turn. Photo work may use up to
            # four turns, with a 4 ms budget checked between them. Atomic native
            # TLS/VFS calls can still overrun it; idle work keeps one turn.
            photo_work = bool(self._photo_active or self._photos)
            turns = 4 if photo_work else 1
            began = milliseconds() if photo_work else 0
            diff = getattr(time, "ticks_diff", None)
            for _ in range(turns):
                self.loop.run_until_complete(self.turn())
                # Service must receive typed events before another job starts,
                # especially to persist a rotated Auth refresh token first.
                if self.events or not (self._photo_active or self._photos):
                    break
                now = milliseconds()
                elapsed = diff(now, began) if diff else now - began
                if elapsed >= 4:
                    break
        result, self.events = self.events, []
        return result

    def close(self):
        for task in (self.task, self.connect_task):
            if task and not task.done():
                task.cancel()
        self.loop.run_until_complete(self.http.close())
        self.loop.run_until_complete(self.realtime.close())
