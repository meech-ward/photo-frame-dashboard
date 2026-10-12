"""Real framing and transport configuration with in-memory streams, no network."""

import asyncio
import binascii
import errno
import json
from pathlib import Path
import ssl
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "network" / "vendor"))
sys.path.insert(0, str(ROOT / "badgelink" / "badge"))
sys.path.insert(0, str(ROOT / "network" / "badge"))
sys.path.insert(0, str(ROOT / "homehq" / "badge" / "homehq"))
from transport import HTTP, MAX_BODY, MAX_PHOTO, SupabaseTransport, valid_photo, milliseconds


class Reader:
    def __init__(self, data, block=None):
        self.data = bytearray(data)
        self.block = block
        self.read_sizes = []

    async def read(self, size):
        self.read_sizes.append(size)
        n = min(size, len(self.data), self.block if self.block is not None else size)
        result = bytes(self.data[:n])
        del self.data[:n]
        return result


class Writer:
    def __init__(self):
        self.sent = []
        self.closed = False

    def write(self, block):
        self.sent.append(block)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


def response(body=b"{}", status=200, headers=None):
    headers = headers if headers is not None else {"Content-Length": str(len(body))}
    head = "HTTP/1.1 {} OK\r\n".format(status)
    head += "".join(k + ": " + v + "\r\n" for k, v in headers.items())
    return head.encode() + b"\r\n" + body


def png(width=320, height=240, depth=8, kind=2, interlace=0):
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", binascii.crc32(name + data) & 0xffffffff)
    header = struct.pack(">IIBBBBB", width, height, depth, kind, 0, 0, interlace)
    rows = (b"\0" + b"\0" * (width * 3)) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def maximum_photo():
    # A legal ancillary chunk reaches the download cap without corrupting PNG
    # pixels; testing tiny compressed fixtures would miss the real disk budget.
    body = png()
    text = b"Comment\0" + b"x" * (MAX_PHOTO - len(body) - 12 - 8)
    chunk = struct.pack(">I", len(text)) + b"tEXt" + text
    chunk += struct.pack(">I", binascii.crc32(b"tEXt" + text) & 0xffffffff)
    return body[:-12] + chunk + body[-12:]


class QuotaFilesystem:
    """Byte-accounted writes: a third capped photo cannot fit on this volume."""

    def __init__(self, files, capacity=1024 * 1024):
        self.files = dict(files)
        self.capacity = capacity
        self.operations = []
        self.fail_after = None
        self.short_write = False
        self.fail_rename = False
        self.max_photo_bytes = self.photo_bytes()

    def photo_bytes(self):
        return sum(len(body) for path, body in self.files.items() if "/homehq-photo-" in path)

    def open(self, path, mode):
        assert mode == "wb"
        self.operations.append(("open", path))
        self.files[path] = b""
        filesystem = self

        class Target:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def write(self, body):
                available = filesystem.capacity - sum(map(len, filesystem.files.values()))
                size = min(len(body), available)
                if filesystem.fail_after is not None:
                    size = min(size, filesystem.fail_after)
                filesystem.files[path] += bytes(body[:size])
                filesystem.max_photo_bytes = max(filesystem.max_photo_bytes, filesystem.photo_bytes())
                filesystem.operations.append(("write", path, size))
                if size != len(body) and not filesystem.short_write:
                    raise OSError(errno.ENOSPC, "simulated full disk")
                return size

        return Target()

    def remove(self, path):
        self.operations.append(("remove", path))
        if path not in self.files:
            raise OSError(errno.ENOENT, "not found")
        del self.files[path]

    def rename(self, old, new):
        self.operations.append(("rename", old, new))
        if self.fail_rename:
            raise OSError(errno.EIO, "simulated rename failure")
        assert new not in self.files
        self.files[new] = self.files.pop(old)


class FramingTests(unittest.IsolatedAsyncioTestCase):
    def http(self, data, block=None):
        http = HTTP("project.supabase.co", 443, object())
        http.reader, http.writer = Reader(data, block), Writer()
        return http

    async def test_content_length_and_fragmented_headers(self):
        body = b'{"revision":7}'
        http = self.http(response(body), block=3)
        status, received = await http.request("/rest/v1/rpc/homehq_snapshot", {"apikey": "public"}, {})
        self.assertEqual((status, received), (200, body))
        self.assertIn(b"Accept-Encoding: identity", http.writer.sent[0])
        self.assertIn(b"Content-Length: 2", http.writer.sent[0])

    async def test_chunked_extensions_and_trailers(self):
        chunks = b"3;foo=bar\r\nabc\r\n2\r\nde\r\n0\r\nX-Trace: value\r\n\r\n"
        http = self.http(response(chunks, headers={"Transfer-Encoding": "chunked"}), block=5)
        self.assertEqual(await http.request("/rpc", {}), (200, b"abcde"))

    async def test_chunked_encoding_value_is_case_insensitive(self):
        http = self.http(response(b"2\r\n{}\r\n0\r\n\r\n", headers={"Transfer-Encoding": "Chunked"}))
        self.assertEqual(await http.request("/rpc", {}), (200, b"{}"))

    async def test_keepalive_preserves_next_response_already_in_buffer(self):
        http = self.http(response(b"first") + response(b"second"))
        self.assertEqual((await http.request("/first", {}))[1], b"first")
        self.assertEqual((await http.request("/second", {}))[1], b"second")

    async def test_oversize_content_length_fails_before_body_allocation(self):
        http = self.http(response(b"", headers={"Content-Length": str(MAX_BODY + 1)}))
        writer = http.writer
        with self.assertRaises(ValueError):
            await http.request("/rpc", {})
        self.assertTrue(writer.closed)
        self.assertIsNone(http.writer)

    async def test_oversize_cumulative_chunked_body_is_rejected(self):
        chunks = b"4000\r\n" + b"a" * 16384 + b"\r\n4001\r\n" + b"b" * 16385 + b"\r\n0\r\n\r\n"
        http = self.http(response(chunks, headers={"Transfer-Encoding": "chunked"}))
        with self.assertRaises(ValueError):
            await http.request("/rpc", {})

    async def test_photo_budget_is_separate_from_json_budget(self):
        body = b"p" * (MAX_BODY + 1024)
        http = self.http(response(body))
        self.assertEqual((await http.request("/photo", {}, method="GET", max_bytes=MAX_PHOTO))[1], body)
        http = self.http(response(body))
        with self.assertRaises(ValueError):
            await http.request("/rpc", {})

    async def test_negative_content_length_is_rejected(self):
        http = self.http(response(b"", headers={"Content-Length": "-1"}))
        with self.assertRaises(ValueError):
            await http.request("/rpc", {})

    async def test_truncated_body_closes_owned_stream(self):
        http = self.http(response(b"a", headers={"Content-Length": "8"}))
        writer = http.writer
        with self.assertRaises(OSError):
            await http.request("/rpc", {})
        self.assertTrue(writer.closed)
        self.assertIsNone(http.reader)

    async def test_missing_length_is_not_read_until_unbounded_eof(self):
        http = self.http(response(b"arbitrary", headers={}))
        with self.assertRaises(ValueError):
            await http.request("/rpc", {})

    async def test_header_budget_is_bounded(self):
        http = self.http(response(b"", headers={"X-Large": "x" * 4097, "Content-Length": "0"}))
        with self.assertRaises(ValueError):
            await http.request("/rpc", {})

    async def test_chunk_trailers_share_header_budget(self):
        chunks = b"0\r\n" + b"X-Long: " + b"x" * 4097 + b"\r\n\r\n"
        http = self.http(response(chunks, headers={"Transfer-Encoding": "chunked"}))
        with self.assertRaises(ValueError):
            await http.request("/rpc", {})

    async def test_bad_chunk_separator_is_rejected(self):
        http = self.http(response(b"2\r\n{}XX0\r\n\r\n", headers={"Transfer-Encoding": "chunked"}))
        with self.assertRaises(ValueError):
            await http.request("/rpc", {})

    async def test_no_content_does_not_require_body_length(self):
        http = self.http(response(b"", status=204, headers={}))
        self.assertEqual(await http.request("/rpc", {}), (204, b""))

    async def test_connection_close_releases_stream_after_success(self):
        http = self.http(response(b"{}", headers={"Content-Length": "2", "Connection": "close"}))
        writer = http.writer
        self.assertEqual(await http.request("/rpc", {}), (200, b"{}"))
        self.assertTrue(writer.closed)
        self.assertIsNone(http.writer)

    async def test_header_value_cannot_inject_bearer_or_request_lines(self):
        http = self.http(response())
        with self.assertRaises(ValueError):
            await http.request("/rpc", {"Authorization": "Bearer token\r\nExtra: injected"})
        self.assertEqual(http.writer.sent, [])

    async def test_bulk_body_reads_never_request_one_byte_at_a_time(self):
        http = self.http(response(b"x" * 10000))
        reader = http.reader
        await http.request("/rpc", {})
        self.assertLess(len(reader.read_sizes), 10)
        self.assertGreater(max(reader.read_sizes), 1000)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.addCleanup(self.loop.close)
        self.session = {"user_id": "owner", "refresh_token": "refresh", "access_token": "access"}
        self.config = {"url": "https://project.supabase.co", "publishable_key": "sb_publishable_test", "home_id": "family"}

    def test_default_https_uses_certificate_and_hostname_verification(self):
        transport = SupabaseTransport(self.config, self.session)
        self.assertEqual(transport.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(transport.context.check_hostname)
        self.assertEqual(transport.host, "project.supabase.co")
        self.assertEqual(transport.port, 443)

    def test_subscription_idle_wait_does_not_replace_connection_or_frame_budgets(self):
        from aiohttp.aiohttp_ws import WebSocketClient
        transport = SupabaseTransport(self.config, self.session)
        client = WebSocketClient(**transport.ws.options)
        self.assertEqual(client.connect_timeout_ms, 10000)
        self.assertEqual(client.io_timeout_ms, 3000)
        self.assertIsNone(client.idle_timeout_ms)
        self.assertEqual(transport.realtime.heartbeat_ms, 20000)
        self.assertEqual(transport.realtime.heartbeat_timeout_ms, 10000)

    def test_plaintext_is_rejected_without_explicit_local_override(self):
        self.config["url"] = "http://localhost:54321"
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            SupabaseTransport(self.config, self.session)

    def test_local_test_override_is_explicit_and_sets_no_tls_context(self):
        self.config.update(url="http://localhost:54321", allow_local_http=True)
        transport = SupabaseTransport(self.config, self.session)
        self.assertIsNone(transport.context)
        self.assertEqual(transport.port, 54321)

    def test_missing_auth_session_opens_the_login_state(self):
        for session in (None, {}, {"user_id": "owner"}):
            transport = SupabaseTransport(self.config, session)
            self.assertEqual(transport.auth_state, "signed_out")
            self.assertFalse(transport.can_request)

    def test_secret_key_is_rejected(self):
        self.config["publishable_key"] = "sb_secret_cannot_ship"
        with self.assertRaisesRegex(ValueError, "secret"):
            SupabaseTransport(self.config, self.session)

    def test_project_url_path_is_rejected(self):
        self.config["url"] += "/wrong/project"
        with self.assertRaisesRegex(ValueError, "path"):
            SupabaseTransport(self.config, self.session)

    def test_private_broadcast_topic_matches_household_not_auth_identity(self):
        transport = SupabaseTransport(self.config, self.session)
        channels = transport.realtime.channels()
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].topic, "realtime:homehq:family")
        self.assertTrue(channels[0].private)

    def test_authenticated_transport_with_active_photo_is_not_rpc_ready(self):
        transport = SupabaseTransport(self.config, self.session)
        transport.ready = True
        self.assertTrue(transport.can_request)
        transport.task = object()
        self.assertFalse(transport.can_request)

    def test_private_photo_paths_cannot_escape_owner_prefix(self):
        transport = SupabaseTransport(self.config, self.session)
        transport.photo("another-owner/image.png", "/tmp/photo.png")
        transport.photo("family/../secret.png", "/tmp/photo.png")
        self.assertEqual(transport._photos, [])
        transport.photo("family/hash.png", "/tmp/photo.png")
        transport.photo("family/hash.png", "/tmp/photo.png")
        self.assertEqual(transport._photos, [("family/hash.png", "/tmp/photo.png")])

    def test_photo_uri_is_queued_once_across_slots_while_another_photo_is_active(self):
        transport = SupabaseTransport(self.config, self.session)
        transport._photo_active = "family/active.png"
        self.assertTrue(transport.photo("family/new.png", "/state/homehq-photo-0.png"))
        self.assertFalse(transport.photo("family/new.png", "/state/homehq-photo-1.png"))
        self.assertFalse(transport.photo("family/active.png", "/state/homehq-photo-1.png"))
        self.assertFalse(transport.photo("other-owner/new.png", "/state/homehq-photo-1.png"))
        self.assertEqual(transport._photos, [("family/new.png", "/state/homehq-photo-0.png")])
        self.assertEqual(transport._photo_active, "family/active.png")

    def test_failed_photo_can_be_requested_again_after_reconnection(self):
        transport = SupabaseTransport(self.config, self.session)
        transport._photo_active = "family/hash.png"

        async def failed_download():
            raise OSError("Wi-Fi dropped")

        self.loop.run_until_complete(transport.contain(failed_download()))
        transport.photo("family/hash.png", "/tmp/photo.png")
        self.assertEqual(transport._photos, [("family/hash.png", "/tmp/photo.png")])

    def test_channel_error_schedules_rejoin_and_preserves_frame_pump(self):
        from realtime.phoenix import Message
        transport = SupabaseTransport(self.config, self.session)
        client = transport.realtime
        channel = client.channels()[0]
        channel.start_join("1", 0, "access")
        channel.join_succeeded()
        events = []
        client._fail_channel(channel, Message("1", "2", channel.topic, "phx_error", {}), events, 0)

        class Socket:
            sent = []
            async def send_str(self, value):
                self.sent.append(value)

        client._response = Socket()
        client._clock = lambda: 10000
        client._heartbeat_due_ms = 1000000
        self.loop.run_until_complete(client._run_timers([]))
        self.assertEqual(channel.state, "joining")
        self.assertEqual(len(client._response.sent), 1)

    def test_realtime_reconnect_is_not_started_before_its_backoff_due_tick(self):
        transport = SupabaseTransport(self.config, self.session)
        transport.ready = True
        transport.refresh_at = milliseconds() + 100000
        transport.realtime._reconnect_at_ms = milliseconds() + 20000
        started = []

        async def connect():
            started.append(True)

        transport.realtime.connect = connect
        self.loop.run_until_complete(transport.turn())
        self.assertEqual(started, [])

    def test_failed_token_push_does_not_block_draining_dead_receive(self):
        transport = SupabaseTransport(self.config, self.session)
        client = transport.realtime
        channel = client.channels()[0]
        channel.start_join("1", 0, "access")
        channel.join_succeeded()
        client.socket_state = "open"
        transport.ready = transport.joined = True

        class AuthHTTP:
            calls = 0

            async def request(self, *args, **kwargs):
                self.calls += 1
                return 200, json.dumps({"access_token": "updated-access-" + str(self.calls),
                    "refresh_token": "updated-refresh-" + str(self.calls),
                    "expires_at": 3600, "expires_in": 3600}).encode()

        class DeadSocket:
            closed = False

            async def send_str(self, message):
                raise OSError("existing radio connection died")

            async def receive(self):
                raise OSError("existing radio connection died")

            async def close(self):
                self.closed = True

        dead = DeadSocket()
        client._response = dead
        transport.http = AuthHTTP()

        async def recovery():
            client._receive_task = asyncio.create_task(dead.receive())
            await asyncio.sleep(0)
            try:
                await transport.contain(transport.refresh_session())
                self.assertFalse(transport.ready)
                self.assertIs(client._response, dead)
                transport.retry_at = 0
                await transport.turn()
                await asyncio.sleep(0)
                self.assertTrue(dead.closed, "Auth readiness cannot suppress dead-socket cleanup")
                self.assertIsNone(client._response)
                self.assertIsNone(client._receive_task)
                self.assertIsNotNone(client.reconnect_delay_ms())
                self.assertFalse(transport.joined)
                self.assertTrue(transport.ready, "new Auth refresh must recover on a released socket")
            finally:
                await client.close()

        self.loop.run_until_complete(recovery())

    def test_sql_missing_item_code_is_terminal_removed_event(self):
        transport = SupabaseTransport(self.config, self.session)

        class FakeHTTP:
            async def request(self, *args, **kwargs):
                return 404, b'{"code":"PT404"}'

        transport.http = FakeHTTP()
        transport.request("homehq_set_done", {})
        self.loop.run_until_complete(transport.task)
        self.assertEqual(transport.events, [{"kind": "removed"}])

    def test_generic_missing_rpc_endpoint_is_not_an_item_deletion(self):
        transport = SupabaseTransport(self.config, self.session)

        class FakeHTTP:
            async def request(self, *args, **kwargs):
                return 404, b'{"code":"PGRST202"}'

        transport.http = FakeHTTP()
        transport.request("homehq_set_done", {})
        self.loop.run_until_complete(transport.task)
        self.assertEqual(transport.events, [{"kind": "error"}])


class PollSchedulingTests(unittest.TestCase):
    def harness(self, active=None, queued=False, cost=0, finish=False, connected=True):
        clock = SimpleNamespace(now=0)
        harness = SimpleNamespace(_photo_active=active, _photos=[("family/queued.png", "slot")] if queued else [],
                                  events=[], wifi_ready=lambda: connected)

        async def turn():
            pass

        class Loop:
            calls = 0

            def run_until_complete(self, coroutine):
                coroutine.close()
                self.calls += 1
                clock.now = (clock.now + cost) % (1 << 30)
                if finish:
                    harness._photo_active = None
                    harness._photos = []
                    harness.events.append({"kind": "photo"})

        harness.turn = turn
        harness.loop = Loop()
        return harness, clock

    def test_idle_keeps_one_turn(self):
        harness, clock = self.harness()
        with patch("transport.milliseconds", lambda: clock.now):
            self.assertEqual(SupabaseTransport.poll(harness), [])
        self.assertEqual(harness.loop.calls, 1)

    def test_active_or_queued_photo_gets_at_most_four_ready_turns(self):
        for active, queued in (("family/active.png", False), (None, True)):
            harness, clock = self.harness(active=active, queued=queued)
            with patch("transport.milliseconds", lambda: clock.now):
                SupabaseTransport.poll(harness)
            self.assertEqual(harness.loop.calls, 4)

    def test_four_ms_budget_stops_after_two_two_ms_turns(self):
        harness, clock = self.harness(active="family/active.png", cost=2)
        with patch("transport.milliseconds", lambda: clock.now):
            SupabaseTransport.poll(harness)
        self.assertEqual(harness.loop.calls, 2)
        self.assertEqual(clock.now, 4)

    def test_atomic_slow_turn_gets_no_additional_turn(self):
        harness, clock = self.harness(active="family/active.png", cost=12)
        with patch("transport.milliseconds", lambda: clock.now):
            SupabaseTransport.poll(harness)
        self.assertEqual(harness.loop.calls, 1)

    def test_budget_uses_wrapping_native_ticks(self):
        harness, clock = self.harness(active="family/active.png", cost=2)
        clock.now = (1 << 30) - 2
        native_diff = lambda later, earlier: ((later - earlier + (1 << 29)) % (1 << 30)) - (1 << 29)
        with patch("transport.milliseconds", lambda: clock.now), \
                patch.object(sys.modules["transport"].time, "ticks_diff", native_diff, create=True):
            SupabaseTransport.poll(harness)
        self.assertEqual(harness.loop.calls, 2)

    def test_completion_returns_event_and_stops_without_extra_turn(self):
        harness, clock = self.harness(active="family/active.png", finish=True)
        with patch("transport.milliseconds", lambda: clock.now):
            events = SupabaseTransport.poll(harness)
        self.assertEqual(harness.loop.calls, 1)
        self.assertEqual(events, [{"kind": "photo"}])
        self.assertEqual(harness.events, [])

    def test_missing_wifi_does_not_pump(self):
        harness, clock = self.harness(active="family/active.png", connected=False)
        harness.events.append({"kind": "error"})
        self.assertEqual(SupabaseTransport.poll(harness), [{"kind": "error"}])
        self.assertEqual(harness.loop.calls, 0)

    def test_any_typed_event_hands_off_before_another_ready_turn(self):
        for kind in ("session", "result", "changed", "error", "joined"):
            with self.subTest(kind=kind):
                harness, clock = self.harness(queued=True)
                queued = list(harness._photos)
                original = harness.loop.run_until_complete

                def first_turn(coroutine):
                    original(coroutine)
                    harness.events.append({"kind": kind})

                harness.loop.run_until_complete = first_turn
                with patch("transport.milliseconds", lambda: clock.now):
                    events = SupabaseTransport.poll(harness)
                self.assertEqual(harness.loop.calls, 1)
                self.assertEqual(events, [{"kind": kind}])
                self.assertEqual(harness._photos, queued)
                self.assertEqual(harness.events, [])

    def test_rotated_auth_is_handed_off_before_queued_photo_starts(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        transport = SupabaseTransport({"url": "http://localhost:54321", "allow_local_http": True,
            "publishable_key": "sb_publishable_test", "home_id": "family"},
            {"user_id": "owner", "refresh_token": "old-refresh", "access_token": "old-access"})
        transport.wifi_ready = lambda: True
        transport.realtime._reconnect_at_ms = transport.realtime._clock() + 1000000
        transport.photo("family/new.png", "/state/homehq-photo-0.png")
        persisted = []
        started = []

        class AuthHTTP:
            async def request(self, *args, **kwargs):
                return 200, json.dumps({"access_token": "new-access", "refresh_token": "new-refresh",
                    "expires_at": 3600, "expires_in": 3600}).encode()

            async def close(self):
                pass

        async def download(path, local_path):
            started.append(path)
            self.assertEqual(persisted, ["new-refresh"], "Auth checkpoint must precede next HTTP job")
            transport._photo_active = None
            transport.events.append({"kind": "photo", "path": path, "local_path": local_path})

        transport.http = AuthHTTP()
        transport.download_photo = download
        try:
            events = transport.poll()
            self.assertEqual([event["kind"] for event in events], ["session"])
            self.assertEqual(started, [])
            self.assertEqual(transport._photos, [("family/new.png", "/state/homehq-photo-0.png")])
            # This is the Service handoff point: rotated credentials are saved
            # before a later poll can clear the completed Auth task/start photo.
            persisted.append(events[0]["data"]["refresh_token"])
            events = transport.poll()
            self.assertEqual(started, ["family/new.png"])
            self.assertEqual([event["kind"] for event in events], ["photo"])
        finally:
            transport.close()
            loop.close()
            asyncio.set_event_loop(None)

    def test_real_http_and_file_scheduler_model_uses_fewer_rendered_polls(self):
        body = maximum_photo()

        def model(burst):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            reader = Reader(body)

            class ImmediatePhotoHTTP(HTTP):
                async def request(self, path, headers, method, max_bytes):
                    self.limit = max_bytes
                    return 200, await self.exact(len(body))

            transport = SupabaseTransport({"url": "http://localhost:54321", "allow_local_http": True,
                "publishable_key": "sb_publishable_model", "home_id": "family"},
                {"user_id": "owner", "refresh_token": "refresh", "access_token": "access"})
            transport.ready = True
            transport.refresh_at = milliseconds() + 1000000
            transport.realtime._reconnect_at_ms = transport.realtime._clock() + 1000000
            transport.http = ImmediatePhotoHTTP("not-a-network-target", 80, None)
            transport.http.reader = reader
            try:
                with tempfile.TemporaryDirectory(prefix="homehq-scheduler-model-") as temporary:
                    target = Path(temporary) / "homehq-photo-0.png"
                    transport._photo_active = "family/model.png"
                    transport.task = loop.create_task(transport.contain(
                        transport.download_photo(transport._photo_active, str(target))))
                    polls = 0
                    events = []
                    # Fix only the artificial budget clock: this models ready
                    # scheduler stages, not network/native elapsed time.
                    with patch("transport.milliseconds", lambda: 0):
                        while not any(event["kind"] == "photo" for event in events):
                            polls += 1
                            self.assertLess(polls, 2000)
                            if burst:
                                events.extend(transport.poll())
                            else:
                                loop.run_until_complete(transport.turn())
                                events.extend(transport.events)
                                transport.events = []
                    self.assertEqual(target.read_bytes(), body)
                    self.assertFalse(Path(str(target) + ".tmp").exists())
                    self.assertEqual(sum(event["kind"] == "photo" for event in events), 1)
                transport.close()
                self.assertEqual(len(asyncio.all_tasks(loop)), 0)
                return polls, len(reader.read_sizes)
            finally:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()
                asyncio.set_event_loop(None)

        baseline, baseline_reads = model(False)
        candidate, candidate_reads = model(True)
        self.assertEqual(baseline_reads, candidate_reads)
        self.assertEqual(candidate_reads, 160)
        self.assertLess(candidate, baseline)
        print("SCHEDULER_MODEL_ONLY polls=" + str(baseline) + "->" + str(candidate)
              + " bytes=" + str(len(body)) + "; no native/network timing claim", flush=True)


class PhotoTests(unittest.IsolatedAsyncioTestCase):
    def transport(self, body=None, status=200):
        session = {"user_id": "owner", "refresh_token": "refresh", "access_token": "access"}
        transport = SupabaseTransport({"url": "https://project.supabase.co", "publishable_key": "sb_publishable_test", "home_id": "family"}, session)

        class FakeHTTP:
            async def request(self, *args, **kwargs):
                self.limit = kwargs["max_bytes"]
                return status, body if body is not None else png()

        transport.http = FakeHTTP()
        return transport

    def filesystem_patches(self, filesystem):
        return (patch("transport.open", filesystem.open, create=True),
                patch("transport.os.remove", filesystem.remove),
                patch("transport.os.rename", filesystem.rename))

    def test_ihdr_validation_covers_size_depth_colour_and_interlace(self):
        self.assertTrue(valid_photo(png()))
        for body in (png(width=640), png(height=480), png(depth=16), png(kind=0), png(interlace=1), b"\x89PNG\r\n\x1a\n"):
            self.assertFalse(valid_photo(body))

    async def test_valid_photo_is_atomically_saved_with_content_path_event(self):
        session = {"user_id": "owner", "refresh_token": "refresh", "access_token": "access"}
        transport = SupabaseTransport({"url": "https://project.supabase.co", "publishable_key": "sb_publishable_test", "home_id": "family"}, session)
        body = png()

        class FakeHTTP:
            async def request(self, *args, **kwargs):
                self.limit = kwargs["max_bytes"]
                return 200, body

        transport.http = FakeHTTP()
        with tempfile.TemporaryDirectory() as directory:
            local = directory + "/homehq-photo-0.png"
            await transport.download_photo("family/hash.png", local)
            self.assertEqual(Path(local).read_bytes(), body)
            self.assertEqual(transport.http.limit, 327680)
            self.assertEqual(transport.events[-1], {"kind": "photo", "path": "family/hash.png", "local_path": local})

    async def test_unsupported_png_does_not_replace_an_existing_picture(self):
        session = {"user_id": "owner", "refresh_token": "refresh", "access_token": "access"}
        transport = SupabaseTransport({"url": "https://project.supabase.co", "publishable_key": "sb_publishable_test", "home_id": "family"}, session)

        class FakeHTTP:
            async def request(self, *args, **kwargs):
                return 200, png(width=640)

        transport.http = FakeHTTP()
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "homehq-photo-0.png"
            local.write_bytes(b"previous-picture")
            with self.assertRaises(ValueError):
                await transport.download_photo("family/hash.png", str(local))
            self.assertEqual(local.read_bytes(), b"previous-picture")

    async def test_maximum_photo_evicts_only_destination_before_quota_write(self):
        body = maximum_photo()
        self.assertEqual(len(body), MAX_PHOTO)
        self.assertTrue(valid_photo(body))
        local, other = "/state/homehq-photo-0.png", "/state/homehq-photo-1.png"
        state = b"s" * (103 * 1024)
        filesystem = QuotaFilesystem({local: body, other: body, "/state/unrelated-and-auth": state})
        # This proves the previous 2 slots + temporary design cannot fit.
        self.assertGreater(3 * len(body) + len(state), filesystem.capacity)
        transport = self.transport(body)
        patches = self.filesystem_patches(filesystem)
        with patches[0], patches[1], patches[2]:
            await transport.download_photo("family/new.png", local)
        self.assertEqual(filesystem.operations[0:2], [("remove", local), ("open", local + ".tmp")])
        self.assertEqual(filesystem.files, {local: body, other: body, "/state/unrelated-and-auth": state})
        self.assertEqual(filesystem.max_photo_bytes, 2 * MAX_PHOTO)
        self.assertNotIn(local + ".tmp", filesystem.files)
        self.assertTrue(all(operation[2] <= 4096 for operation in filesystem.operations if operation[0] == "write"))
        self.assertEqual(transport.events, [{"kind": "photo", "path": "family/new.png", "local_path": local}])

    async def test_other_ready_task_observes_photo_write_before_publication(self):
        body = maximum_photo()
        transport = self.transport(body)
        observed_sizes = []
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "homehq-photo-0.png"
            temporary = Path(str(local) + ".tmp")

            async def observer():
                while not transport.events:
                    if temporary.exists():
                        size = temporary.stat().st_size
                        if 0 < size < len(body):
                            observed_sizes.append(size)
                            self.assertFalse(local.exists())
                    await asyncio.sleep(0)

            ready_task = asyncio.create_task(observer())
            await transport.download_photo("family/new.png", str(local))
            await ready_task
            self.assertTrue(observed_sizes, "another ready task must run before saving completes")
            self.assertEqual(local.read_bytes(), body)
            self.assertFalse(temporary.exists())
            self.assertEqual(transport.events, [{"kind": "photo", "path": "family/new.png", "local_path": str(local)}])

    async def test_cancellation_between_chunks_cleans_unpublished_photo(self):
        transport = self.transport(maximum_photo())
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "homehq-photo-0.png"
            temporary = Path(str(local) + ".tmp")
            task = asyncio.create_task(transport.download_photo("family/new.png", str(local)))
            await asyncio.sleep(0)
            self.assertTrue(temporary.exists())
            self.assertFalse(local.exists())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(temporary.exists())
            self.assertFalse(local.exists())
            self.assertEqual(transport.events, [])

    async def test_http_or_png_rejection_retains_old_slot_without_disk_writes(self):
        local = "/state/homehq-photo-0.png"
        for status, body in ((403, png()), (200, png(width=640)), (200, maximum_photo() + b"x")):
            with self.subTest(status=status, length=len(body)):
                filesystem = QuotaFilesystem({local: b"old-photo"})
                transport = self.transport(body, status)
                patches = self.filesystem_patches(filesystem)
                with patches[0], patches[1], patches[2], self.assertRaises(ValueError):
                    await transport.download_photo("family/new.png", local)
                self.assertEqual(filesystem.files, {local: b"old-photo"})
                self.assertEqual(filesystem.operations, [])
                self.assertEqual(transport.events, [])

    async def test_partial_write_is_cleaned_and_next_retry_saves_photo(self):
        body = maximum_photo()
        local, other = "/state/homehq-photo-0.png", "/state/homehq-photo-1.png"
        filesystem = QuotaFilesystem({local: body, other: body})
        filesystem.fail_after = 127
        transport = self.transport(body)
        transport._photo_active = "family/new.png"
        patches = self.filesystem_patches(filesystem)
        with patches[0], patches[1], patches[2]:
            await transport.contain(transport.download_photo("family/new.png", local))
            self.assertEqual(filesystem.files, {other: body})
            self.assertEqual(transport.events, [{"kind": "error"}])
            self.assertIsNone(transport._photo_active)
            transport.photo("family/new.png", local)
            self.assertEqual(transport._photos, [("family/new.png", local)])
            filesystem.fail_after = None
            path, destination = transport._photos.pop()
            await transport.download_photo(path, destination)
        self.assertEqual(filesystem.files, {local: body, other: body})
        self.assertLessEqual(filesystem.max_photo_bytes, 2 * MAX_PHOTO)
        self.assertEqual(transport.events[-1], {"kind": "photo", "path": "family/new.png", "local_path": local})

    async def test_short_write_cannot_be_renamed_or_published(self):
        local = "/state/homehq-photo-0.png"
        filesystem = QuotaFilesystem({local: b"old-photo"})
        filesystem.fail_after, filesystem.short_write = 127, True
        transport = self.transport(maximum_photo())
        patches = self.filesystem_patches(filesystem)
        with patches[0], patches[1], patches[2], self.assertRaises(OSError):
            await transport.download_photo("family/new.png", local)
        self.assertEqual(filesystem.files, {})
        self.assertFalse(any(operation[0] == "rename" for operation in filesystem.operations))
        self.assertEqual(transport.events, [])

    async def test_failed_rename_cleans_complete_temporary_file(self):
        local = "/state/homehq-photo-0.png"
        filesystem = QuotaFilesystem({local: b"old-photo"})
        filesystem.fail_rename = True
        transport = self.transport()
        patches = self.filesystem_patches(filesystem)
        with patches[0], patches[1], patches[2], self.assertRaises(OSError):
            await transport.download_photo("family/new.png", local)
        self.assertEqual(filesystem.files, {})
        self.assertEqual(transport.events, [])

    async def test_leftover_temporary_file_is_truncated_on_next_retry(self):
        body = maximum_photo()
        local, other = "/state/homehq-photo-0.png", "/state/homehq-photo-1.png"
        filesystem = QuotaFilesystem({local + ".tmp": body, other: body})
        transport = self.transport(body)
        patches = self.filesystem_patches(filesystem)
        with patches[0], patches[1], patches[2]:
            await transport.download_photo("family/new.png", local)
        self.assertEqual(filesystem.files, {local: body, other: body})
        self.assertEqual(filesystem.max_photo_bytes, 2 * MAX_PHOTO)
        self.assertEqual(transport.events[-1]["kind"], "photo")

    async def test_unowned_destination_cannot_delete_an_existing_file(self):
        for local in ("/state/homehq-session.json", "/state/homehq-photo-2.png", "/state/../homehq-photo-0.png"):
            filesystem = QuotaFilesystem({local: b"keep"})
            transport = self.transport()
            patches = self.filesystem_patches(filesystem)
            with patches[0], patches[1], patches[2], self.assertRaises(ValueError):
                await transport.download_photo("family/new.png", local)
            self.assertEqual(filesystem.files, {local: b"keep"})
            self.assertEqual(filesystem.operations, [])


class WiFiStatusTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.addCleanup(self.loop.close)
        self.now = 0
        self.turns = []
        self.transport = SupabaseTransport({"url": "http://localhost:54321", "allow_local_http": True,
            "publishable_key": "sb_publishable_test", "home_id": "family", "wifi_ssid": "test-network"},
            {"user_id": "owner", "refresh_token": "refresh", "access_token": "access"})

        class FakeWLAN:
            def __init__(self):
                self.connected = False
                self.status_code = 1
                self.attempts = 0

            def isconnected(self):
                return self.connected

            def status(self):
                return self.status_code

            def active(self, value):
                pass

            def connect(self, ssid, password):
                self.attempts += 1
                self.status_code = 1  # Joining begins before NO_AP is known.

        self.wlan = FakeWLAN()

        async def turn():
            self.turns.append(True)

        self.transport.turn = turn
        fake_network = SimpleNamespace(STA_IF=0, WLAN=lambda interface: self.wlan)
        patches = (patch("transport.sys", SimpleNamespace(implementation=SimpleNamespace(name="micropython"))),
                   patch.dict(sys.modules, {"network": fake_network}),
                   patch("transport.milliseconds", lambda: self.now))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_initial_joining_is_not_reported_as_failure(self):
        self.assertEqual(self.transport.poll(), [])
        self.assertEqual(self.wlan.attempts, 1)
        self.assertEqual(self.turns, [])
        self.now = 1000
        self.assertEqual(self.transport.poll(), [])

    def test_no_ap_emits_one_safe_error_without_poll_flood(self):
        self.transport.poll()
        self.wlan.status_code = -2
        self.now = 1000
        self.assertEqual(self.transport.poll(), [{"kind": "error"}])
        for tick in (1100, 1200, 5000, 14000):
            self.now = tick
            self.assertEqual(self.transport.poll(), [])
        self.assertEqual(self.wlan.attempts, 1)
        self.assertEqual(self.turns, [])

    def test_no_ap_moves_service_from_connecting_to_safe_offline_state(self):
        from service import Service
        with tempfile.TemporaryDirectory() as directory:
            service = Service("/app", transport=self.transport, state_root=directory, config=self.transport.config)
            service.poll(0)
            self.assertEqual(service.status()["state"], "connecting")
            self.wlan.status_code = -2
            self.now = 1000
            service.poll(self.now)
            self.assertEqual(service.status()["state"], "offline")
            self.assertEqual(service.status()["error"], "Waiting for connection")
            self.assertTrue(service._refresh)

    def test_retry_resets_error_latch_and_failed_attempt_reports_once(self):
        self.transport.poll()
        self.wlan.status_code = -2
        self.now = 1000
        self.assertEqual(self.transport.poll(), [{"kind": "error"}])
        self.now = 15000
        self.assertEqual(self.transport.poll(), [])
        self.assertEqual(self.wlan.attempts, 2)
        self.assertFalse(self.transport._wifi_error)
        self.wlan.status_code = -2
        self.now = 16000
        self.assertEqual(self.transport.poll(), [{"kind": "error"}])
        self.assertEqual(self.transport.poll(), [])

    def test_recovery_resumes_loop_and_rearms_next_loss(self):
        self.transport.poll()
        self.wlan.status_code = -2
        self.assertEqual(self.transport.poll(), [{"kind": "error"}])
        self.wlan.connected, self.wlan.status_code = True, 3
        self.assertEqual(self.transport.poll(), [])
        self.assertEqual(self.turns, [True])
        self.assertFalse(self.transport._wifi_error)
        self.wlan.connected, self.wlan.status_code = False, 1
        self.assertEqual(self.transport.poll(), [{"kind": "error"}])
        self.assertEqual(self.transport.poll(), [])

    def test_connected_radio_loss_preserves_healthy_realtime_channel(self):
        self.wlan.connected, self.wlan.status_code = True, 3
        self.transport.ready = self.transport.joined = True
        self.transport.realtime.socket_state = "open"
        self.transport.poll()
        self.wlan.connected, self.wlan.status_code = False, 0
        self.now = 1000
        self.assertEqual(self.transport.poll(), [{"kind": "error"}])
        for tick in (1100, 1200, 14000):
            self.now = tick
            self.assertEqual(self.transport.poll(), [])
        self.assertTrue(self.transport.ready)
        self.assertTrue(self.transport.joined)
        self.assertEqual(self.transport.realtime.socket_state, "open")
        self.assertEqual(self.turns, [True])


if __name__ == "__main__":
    unittest.main()
