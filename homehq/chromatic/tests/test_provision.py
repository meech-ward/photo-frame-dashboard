#!/usr/bin/env python3
import base64
import importlib.util
import json
import pathlib
import sys
import unittest
from unittest.mock import patch
import contextlib
import io
import tempfile

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
try:
    SPEC = importlib.util.spec_from_file_location("homehq_provision", TOOLS / "provision.py")
    PROVISION = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(PROVISION)
finally:
    sys.path.pop(0)


def config():
    return {"wifi_ssid": "Home", "wifi_password": "wifi secret", "url": "https://project.supabase.co",
            "key": "sb_publishable_public", "email": "Person@example.invalid", "password": " CaseSensitive secret "}


class Clock:
    value = 0
    def now(self): return self.value
    def sleep(self, seconds): self.value += seconds


class Connection:
    def __init__(self, clock, confirmation=b"queued", clock_accepted=True):
        self.clock = clock
        self.confirmation = confirmation
        self.writes = []
        self.reply = []
        self.ready = False
        self.clock_accepted = clock_accepted
    def reset_input_buffer(self): self.reply = []
    def flush(self): pass
    def write(self, command):
        self.writes.append((self.clock.now(), command))
        if command != b"\r\n":
            assert self.ready
        if command == b"hq config-save\r\n":
            if self.confirmation:
                response = b"mcu> hq config-save\r\nmcu>  HQ provision=" + self.confirmation
                self.reply = [response[i:i+7] for i in range(0, len(response), 7)]
        elif command.startswith(b"hq clock "):
            self.reply = [b"HQ clock=accepted\r\n" if self.clock_accepted else b"HQ clock=rejected\r\n"]
        elif command != b"\r\n":
            self.reply = [b"mcu> " + command]
    def read(self, capacity):
        if not self.ready:
            if self.clock.now() >= 5:
                self.ready = True
                return b"mcu> "
            return b"Booting\r\n"
        return self.reply.pop(0) if self.reply else b""


class ProvisionTest(unittest.TestCase):
    def test_short_lines_roundtrip_preserves_password_case_and_spaces(self):
        data = config()
        commands = PROVISION.commands_for(data)
        self.assertEqual(commands[0], b"hq config-begin\r\n")
        self.assertEqual(commands[-1], b"hq config-save\r\n")
        self.assertTrue(all(len(command) < 96 for command in commands))
        parts = [command[len(b"hq config-part "):-2] for command in commands[1:-1]]
        self.assertTrue(all(len(part) <= 64 for part in parts))
        self.assertEqual(json.loads(base64.b64decode(b"".join(parts))), data)

    def test_configuration_bounds_and_ordinary_origin_are_checked_before_serial(self):
        changes = [{"key": "sb_secret_wrong"}, {"url": "https://user:secret@project.supabase.co"},
                   {"url": "https://project.supabase.co/path"}, {"url": "https://project.supabase.co:443oops"},
                   {"wifi_ssid": "é" * 17}, {"password": ""}, {"password": "x\x00secret"}]
        for change in changes:
            with self.subTest(fields=list(change)):
                with self.assertRaises(ValueError): PROVISION.commands_for(dict(config(), **change))
        with self.assertRaises(ValueError): PROVISION.commands_for(dict(config(), extra="ignored"))
        with self.assertRaises(ValueError): PROVISION.unique_fields([("password", "one"), ("password", "two")])

    def test_line_states_are_low_before_the_port_opens(self):
        class SerialModule:
            @staticmethod
            def Serial(**options):
                class Port:
                    dtr = rts = True
                    def open(self):
                        assert not self.dtr and not self.rts and self.port == "selected-port"
                self.assertIsNone(options["port"])
                self.assertFalse(options["dsrdtr"] or options["rtscts"])
                return Port()
        connection = PROVISION.open_port(SerialModule, "selected-port")
        self.assertFalse(connection.dtr or connection.rts)

    def test_private_chunks_wait_for_ready_and_fragmented_confirmation(self):
        clock = Clock();connection = Connection(clock)
        self.assertTrue(PROVISION.transmit(connection, PROVISION.commands_for(config()), clock=clock.now, sleep=clock.sleep))
        self.assertTrue(all(when >= 5 for when, command in connection.writes if command != b"\r\n"))
        self.assertEqual(sum(command == b"hq config-save\r\n" for _, command in connection.writes), 1)
        clock_index = next(i for i, (_, command) in enumerate(connection.writes) if command.startswith(b"hq clock "))
        config_index = next(i for i, (_, command) in enumerate(connection.writes) if command == b"hq config-begin\r\n")
        self.assertLess(clock_index, config_index)

    def test_rejected_clock_never_sends_private_configuration(self):
        clock = Clock();connection = Connection(clock, clock_accepted=False)
        with self.assertRaises(RuntimeError):
            PROVISION.transmit(connection, PROVISION.commands_for(config()), utc_epoch=1791795200,
                               clock=clock.now, sleep=clock.sleep)
        self.assertTrue(all(command == b"\r\n" or command.startswith(b"hq clock ") for _, command in connection.writes))

    def test_rejected_and_unconfirmed_configuration_are_never_resent(self):
        for confirmation in (b"rejected", b""):
            clock = Clock();connection = Connection(clock, confirmation)
            if confirmation:
                self.assertFalse(PROVISION.transmit(connection, PROVISION.commands_for(config()), clock=clock.now, sleep=clock.sleep))
            else:
                with self.assertRaises(TimeoutError):
                    PROVISION.transmit(connection, PROVISION.commands_for(config()), confirmation_timeout=0.2, clock=clock.now, sleep=clock.sleep)
            self.assertEqual(sum(command == b"hq config-save\r\n" for _, command in connection.writes), 1)

    def test_credential_echo_and_false_marker_do_not_confirm_setup(self):
        capture = PROVISION.Confirmation()
        self.assertIsNone(capture.feed(b"mcu> hq config-part SECRET HQ provision=queued\r\n"))
        self.assertIsNone(capture.feed(b"arbitrary prefix HQ provision=queued\r\n"))
        self.assertTrue(capture.feed(b"\x1b[0mHQ provision=queued\r\n"))

    def test_wait_connected_needs_durable_auth_snapshot_and_matching_display(self):
        clock = Clock()
        class PollingConnection:
            response = b""
            polls = 0
            commands = []
            def write(self, command):
                self.commands.append(command)
                if command == b"hq diagnostics\r\n":
                    self.polls += 1
                    auth, revision = (0, 0) if self.polls == 1 else (1, 17)
                    self.response += (f"mcu> HQ diagnostics configured=1 authenticated={auth} session_saved={auth} pending=0 revision={revision}\n"
                                      "HQ wifi enabled=1 connected=1 reason=0\n").encode()
                else:
                    revision = 0 if self.polls == 1 else 16 if self.polls == 2 else 17
                    self.response += f"mcu> HQ view page=today detail=none focus=0 revision={revision} viewer=none minheap=80000\n".encode()
            def flush(self): pass
            def read(self, capacity):
                result, self.response = self.response[:7], self.response[7:]
                return result
        connection = PollingConnection()
        result = PROVISION.wait_connected(connection, timeout=10, clock=clock.now, sleep=clock.sleep)
        self.assertEqual(connection.polls, 3)
        self.assertEqual(result["view"]["revision"], 17)
        self.assertTrue(all(command in {b"hq diagnostics\r\n", b"hq view\r\n"} for command in connection.commands))

    def test_wait_connected_rejects_auth_or_session_storage_failure(self):
        for auth, saved in ((0, 1), (1, 0)):
            clock = Clock()
            class Connection:
                response = b""
                def write(self, command):
                    self.response = (f"HQ diagnostics configured=1 authenticated={auth} session_saved={saved} pending=0 revision=17\n".encode()
                                     if command == b"hq diagnostics\r\n" else
                                     b"HQ view page=today detail=none focus=0 revision=17 viewer=Wes minheap=80000\n")
                def flush(self): pass
                def read(self, capacity): result, self.response = self.response, b""; return result
            with self.assertRaises(TimeoutError):
                PROVISION.wait_connected(Connection(), timeout=1, clock=clock.now, sleep=clock.sleep)

    def test_queue_only_remains_the_cli_default(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "configuration.json"
            source.write_text(json.dumps(config()))
            class Port:
                closed = False
                def close(self): self.closed = True
            port = Port()
            output = io.StringIO()
            with patch.object(sys, "argv", ["provision.py", "--port", "mock", "--config", str(source)]), \
                 patch.dict(sys.modules, {"serial": object()}), \
                 patch.object(PROVISION, "open_port", return_value=port), \
                 patch.object(PROVISION, "transmit", return_value=True), \
                 patch.object(PROVISION, "wait_connected", side_effect=AssertionError("Unexpected connected wait")), \
                 contextlib.redirect_stdout(output):
                PROVISION.main()
            self.assertTrue(port.closed)
            self.assertIn("configuration queued", output.getvalue())
            self.assertNotIn(config()["password"], output.getvalue())


if __name__ == "__main__":
    unittest.main()
