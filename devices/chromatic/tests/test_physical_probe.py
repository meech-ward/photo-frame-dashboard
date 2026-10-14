#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[1] / "tools/physical_probe.py"
SPEC = importlib.util.spec_from_file_location("physical_probe", PATH)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class ProbeTest(unittest.TestCase):
    def test_uart_echo_credentials_and_unbounded_lines_are_discarded(self):
        capture = PROBE.SafeCapture()
        raw = (b"mcu> hq config-part private-password-and-token\r\n"
               b"Auth reply {access_token: SECRET}\n"
               + b"X" * 1024 + b"\n"
               b"\x1b[0mHQ view page=photos detail=none focus=2 revision=17 viewer=Wes minheap=40320\r\n")
        replies = []
        for offset in range(0, len(raw), 7):
            replies.extend(capture.feed(raw[offset:offset + 7]))
        self.assertEqual(replies, [{"kind": "view", "page": "photos", "detail": "none",
                                  "focus": 2, "revision": 17, "viewer": "Wes", "minheap": 40320}])
        self.assertEqual(capture.buffer, bytearray())

    def test_status_is_structured_and_view_labels_are_allowlisted(self):
        reply = PROBE.safe_reply("HQ state=Offline. Retrying. pending=2 heap=44000 largest=31000")
        self.assertEqual(reply["pending"], 2)
        for unsafe in ("HQ view page=secret detail=none focus=0 revision=1 viewer=Wes minheap=1",
                       "HQ view page=today detail=none focus=0 revision=1 viewer=Wes@example.com minheap=1",
                       "hq config-part HQ state=Connected pending=0 heap=1 largest=1"):
            self.assertIsNone(PROBE.safe_reply(unsafe))

    def test_fixed_scalar_diagnostics_and_wifi_are_safe_records(self):
        capture = PROBE.SafeCapture()
        replies = capture.feed(b"mcu> HQ diagnostics configured=1 authenticated=0 session_saved=0 pending=2 revision=17\r\n"
                               b"HQ wifi enabled=1 connected=0 reason=201\r\n")
        self.assertEqual(replies, [{"kind": "diagnostics", "configured": 1, "authenticated": 0,
                                   "session_saved": 0, "pending": 2, "revision": 17},
                                  {"kind": "wifi", "enabled": 1, "connected": 0, "reason": 201}])
        self.assertEqual(PROBE.command_for("diagnostics"), b"hq diagnostics\r\n")
        self.assertIsNone(PROBE.safe_reply("HQ wifi enabled=1 connected=0 reason=201 ssid=PRIVATE"))
        latest = PROBE.safe_reply("HQ diagnostics configured=1 authenticated=1 session_saved=1 pending=0 revision=17 radio_paused=0 clock_ready=1 realtime_joined=1")
        self.assertEqual((latest["radio_paused"], latest["clock_ready"], latest["realtime_joined"]), (0, 1, 1))
        self.assertIsNone(PROBE.safe_reply("HQ diagnostics configured=1 authenticated=1 session_saved=1 pending=0 revision=17 realtime_joined=2"))

    def test_button_json_accepts_only_exact_public_scalar_schema(self):
        fields = {key: 0 for key in PROBE.PHYSICAL_FIELDS}
        fields.update(held_buttons=65535, blocked_inputs=4294967295, snapshot_waiting=False,
                      hydrated_page="photos")
        self.assertEqual(PROBE.safe_reply("mcu> HQ buttons " + json.dumps(fields)), {"kind": "buttons", **fields})
        unsafe = []
        for key, value in (("physical_a", True), ("physical_b", -1), ("physical_up", 4294967296),
                           ("held_buttons", 65536), ("blocked_inputs", 1.0),
                           ("snapshot_waiting", 0), ("hydrated_page", "private@example.com"),
                           ("hydrated_page", ["photos"]), ("physical_start", {"token": "SECRET"})):
            unsafe.append(json.dumps({**fields, key: value}))
        unsafe.extend((json.dumps({**fields, "password": "SECRET"}),
                       json.dumps({key: value for key, value in fields.items() if key != "physical_a"}),
                       json.dumps(fields)[:-1] + ',"physical_a":1}', "[]", "null", "{}"))
        for payload in unsafe:
            with self.subTest(payload=payload):
                self.assertIsNone(PROBE.safe_reply("HQ buttons " + payload))

    def test_clock_and_radio_commands_are_exact_and_bounded(self):
        self.assertEqual(PROBE.command_for("clock 1704067200"), b"hq clock 1704067200\r\n")
        self.assertEqual(PROBE.command_for("clock 4102444800"), b"hq clock 4102444800\r\n")
        self.assertEqual(PROBE.command_for("radio off"), b"hq radio off\r\n")
        self.assertEqual(PROBE.safe_reply("mcu> HQ clock=accepted"), {"kind": "clock", "accepted": True})
        self.assertEqual(PROBE.safe_reply("HQ radio=on"), {"kind": "radio", "state": "on"})
        for unsafe in ("clock 1704067199", "clock 4102444801", "clock -1791795200",
                       "clock 1791795200\r\nhq config-save", "radio erase"):
            with self.assertRaises(ValueError): PROBE.command_for(unsafe)

    def test_photo_counters_and_failure_stages_are_safe_scalars(self):
        line = "HQ photo download_ok=1 download_failed=2 stage=6 http_status=403 cache_hits=3 cache_misses=4 cache_saved=1 cache_save_failed=0 cache_clear_failed=0"
        reply = PROBE.safe_reply("mcu> " + line)
        self.assertEqual((reply["kind"], reply["stage"], reply["http_status"], reply["cache_hits"]), ("photo", 6, 403, 3))
        latest = PROBE.safe_reply(line + " tls_error=-32512 transport_error=32774")
        self.assertEqual((latest["tls_error"], latest["transport_error"]), (-32512, 32774))
        self.assertIsNone(PROBE.safe_reply(line + " tls_error=-32512 transport_error=PRIVATE"))
        self.assertIsNone(PROBE.safe_reply(line + " tls_error=2147483648 transport_error=0"))
        for unsafe in (line + " path=PRIVATE", line.replace("stage=6", "stage=17"),
                       line.replace("http_status=403", "http_status=1000"),
                       line.replace("cache_hits=3", "cache_hits=-1"),
                       line.replace("download_ok=1", "download_ok=4294967296"),
                       line.replace("http_status=403", "http_status=private@example.com")):
            self.assertIsNone(PROBE.safe_reply(unsafe))

    def test_prompt_prefixed_unterminated_view_matches_observed_bridge_output(self):
        capture = PROBE.SafeCapture()
        reply = b"mcu>  HQ view page=today detail=none focus=0 revision=1 viewer=none minheap=38728"
        self.assertEqual(capture.feed(reply), [])
        self.assertEqual(capture.flush_idle()[0]["minheap"], 38728)
        self.assertIsNone(PROBE.safe_reply("private echo mcu> HQ state=Demo pending=0 heap=1 largest=1"))

    def test_initial_prompt_gates_actions_despite_five_second_bridge_restart(self):
        class Clock:
            value = 0
            def now(self): return self.value
            def sleep(self, seconds): self.value += seconds
        clock = Clock()
        class Connection:
            writes = []
            def write(self, command): self.writes.append((clock.now(), command))
            def flush(self): pass
            def read(self, capacity): return b"mcu>  " if clock.now() >= 5 else b"Booting\r\n"
        connection = Connection()
        PROBE.wait_ready(connection, clock=clock.now, sleep=clock.sleep)
        self.assertGreaterEqual(clock.now(), 5)
        self.assertTrue(all(command == b"\r\n" for _, command in connection.writes))

    def test_short_control_allowlist_rejects_config_and_arbitrary_commands(self):
        self.assertEqual(PROBE.command_for("right"), b"hq input right\r\n")
        for step in PROBE.BUTTONS | {"view", "status", "refresh"}:
            self.assertLess(len(PROBE.command_for(step)), 96)
        for step in ("config-save", "config-part SECRET", "view\r\nreset", "flash", ""):
            with self.assertRaises(ValueError):
                PROBE.command_for(step)

    def test_replay_waits_for_queued_view_and_asserts_semantics(self):
        class Clock:
            value = 0
            def now(self): return self.value
            def sleep(self, seconds): self.value += seconds
        class Connection:
            commands = []
            response = b""
            def write(self, command):
                self.commands.append(command)
                self.response = (b"mcu> " + command +
                    (b"HQ view page=chores detail=routine focus=1 revision=12 viewer=Wes minheap=40000\n"
                     if command == b"hq view\r\n" else b""))
            def flush(self): pass
            def read(self, capacity):
                reply, self.response = self.response[:capacity], self.response[capacity:]
                return reply
        clock, connection = Clock(), Connection()
        records = PROBE.execute(connection, ["right", "a", "view"], clock=clock.now, sleep=clock.sleep)
        PROBE.assert_view(records, {"page": "chores", "detail": "routine", "focus": 1, "viewer": "Wes"})
        self.assertEqual(len(records), 1)
        with self.assertRaises(AssertionError):
            PROBE.assert_view(records, {"page": "today"})

    def test_replay_drains_fragmented_button_line_after_view(self):
        fields = {key: 1 for key in PROBE.PHYSICAL_FIELDS}
        fields.update(held_buttons=0, blocked_inputs=2, snapshot_waiting=False, hydrated_page="today")
        class Clock:
            value = 0
            def now(self): return self.value
            def sleep(self, seconds): self.value += seconds
        class Connection:
            response = b""
            def write(self, command):
                self.response += (b"HQ view page=today detail=none focus=0 revision=18 viewer=Wes minheap=40000\n"
                                  + b"HQ buttons " + json.dumps(fields).encode("ascii") + b"\n")
            def flush(self): pass
            def read(self, capacity):
                reply, self.response = self.response[:7], self.response[7:]
                return reply
        clock = Clock()
        records = PROBE.execute(Connection(), ["view"], clock=clock.now, sleep=clock.sleep)
        self.assertEqual([record["kind"] for record in records], ["view", "buttons"])
        self.assertEqual(records[1]["blocked_inputs"], 2)
        self.assertEqual(records[1]["step"], "view")


if __name__ == "__main__":
    unittest.main()
