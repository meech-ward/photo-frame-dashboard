#!/usr/bin/env python3
"""Send a private Home HQ configuration through bounded UART console lines."""
import argparse
import base64
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from physical_probe import wait_ready, execute

FIELDS = ("wifi_ssid", "wifi_password", "url", "key", "email", "password")
ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")


def commands_for(data):
    if not isinstance(data, dict) or set(data) != set(FIELDS) or any(not isinstance(data[key], str) for key in FIELDS):
        raise ValueError("Private config must contain exactly the six documented string fields")
    if any("\x00" in data[key] for key in FIELDS):
        raise ValueError("Private configuration fields cannot contain NUL characters")
    bounds = {"wifi_ssid": (1, 32), "wifi_password": (0, 63), "email": (1, 320), "password": (1, 512)}
    for key, (minimum, maximum) in bounds.items():
        if not minimum <= len(data[key].encode("utf-8")) <= maximum:
            raise ValueError("Private configuration field exceeds its native byte bound: " + key)
    try:
        origin = urlsplit(data["url"])
        port = origin.port
        valid_origin = (origin.scheme == "https" and bool(origin.hostname) and
                        origin.username is None and origin.password is None and
                        not origin.path and not origin.query and not origin.fragment and
                        (port is None or 1 <= port <= 65535) and len(data["url"]) <= 240 and
                        re.fullmatch(r"[A-Za-z0-9.:-]+", origin.netloc))
    except ValueError:
        valid_origin = False
    if not valid_origin or not re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", data["key"]) or len(data["key"]) >= 2048:
        raise ValueError("Use an HTTPS base origin and the ordinary project publishable key")
    wire = base64.b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    if len(wire) >= 4096:
        raise ValueError("Configuration exceeds the native provisioning buffer")
    commands = ["hq config-begin"] + ["hq config-part " + wire[i:i+64] for i in range(0, len(wire), 64)] + ["hq config-save"]
    return [(command + "\r\n").encode("ascii") for command in commands]


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Private configuration contains a duplicate field")
        result[key] = value
    return result


class Confirmation:
    def __init__(self):
        self.buffer = bytearray()
        self.discard = False

    def clear(self):
        for index in range(len(self.buffer)):
            self.buffer[index] = 0
        self.buffer.clear()

    def feed(self, data):
        for byte in data:
            if byte == 10:
                line = ANSI.sub(b"", bytes(self.buffer)).strip(b"\r") if not self.discard else b""
                self.clear()
                self.discard = False
                if line.startswith(b"mcu>"):
                    line = line[4:].lstrip(b" \t")
                if line == b"HQ provision=queued":
                    return True
                if line == b"HQ provision=rejected":
                    return False
            elif not self.discard:
                if len(self.buffer) >= 512:
                    self.clear()
                    self.discard = True
                else:
                    self.buffer.append(byte)
        return None

    def flush_idle(self):
        line = ANSI.sub(b"", bytes(self.buffer)).strip(b"\r") if not self.discard else b""
        if line.startswith(b"mcu>"):
            line = line[4:].lstrip(b" \t")
        if line in (b"HQ provision=queued", b"HQ provision=rejected"):
            self.clear()
            return line == b"HQ provision=queued"
        return None


def transmit(connection, commands, delay=0.18, confirmation_timeout=10.0, clock=time.monotonic, sleep=time.sleep, utc_epoch=None):
    connection.reset_input_buffer()
    wait_ready(connection, clock=clock, sleep=sleep)
    # Verified HTTPS needs a valid date even where UDP NTP is blocked. The
    # trusted programmer sends only public UTC seconds, never a certificate
    # bypass; the native service validates and persists this clock separately.
    epoch = int(time.time()) if utc_epoch is None else utc_epoch
    replies = execute(connection, ["clock " + str(epoch)], settle=delay,
                      timeout=confirmation_timeout, clock=clock, sleep=sleep)
    if not any(reply["kind"] == "clock" and reply["accepted"] for reply in replies):
        raise RuntimeError("Trusted programmer clock rejected; private configuration was not sent")
    for command in commands[:-1]:
        connection.write(command)
        connection.flush()
        sleep(delay)
        # Console input echoes include private base64. Drain locally without
        # printing, saving or attaching any raw UART bytes to an exception.
        connection.read(2048)
    connection.reset_input_buffer()
    connection.write(commands[-1])
    connection.flush()
    capture = Confirmation()
    deadline = clock() + confirmation_timeout
    last_data = clock()
    try:
        while clock() < deadline:
            data = connection.read(2048)
            if data:
                last_data = clock()
            result = capture.feed(data)
            if result is None and not data and clock() - last_data >= 0.1:
                result = capture.flush_idle()
            if result is not None:
                return result
            sleep(0.02)
    finally:
        capture.clear()
    # A lost acknowledgment can follow a saved setup. Do not submit it again
    # automatically; hq status distinguishes that outcome without credentials.
    raise TimeoutError("Provisioning reply not confirmed; inspect safe hq status before retrying")


def open_port(serial_module, port):
    connection = serial_module.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1,
                                      dsrdtr=False, rtscts=False)
    connection.dtr = False
    connection.rts = False
    connection.port = port
    connection.open()
    return connection


def wait_connected(connection, timeout=120.0, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while clock() < deadline:
        remaining = deadline - clock()
        try:
            records = execute(connection, ["diagnostics", "view"], timeout=min(3.0, remaining),
                              settle=min(0.25, remaining), clock=clock, sleep=sleep)
        except TimeoutError:
            records = []
        diagnostics = next((record for record in reversed(records) if record["kind"] == "diagnostics"), None)
        view = next((record for record in reversed(records) if record["kind"] == "view"), None)
        # Fresh provisioning clears identity/cache to revision zero. A saved
        # ordinary Auth session plus positive authoritative revision and its
        # queued UI view proves the snapshot arrived before this bridge closes.
        if (diagnostics and view and diagnostics["configured"] == 1 and
                diagnostics["authenticated"] == 1 and diagnostics["session_saved"] == 1 and
                diagnostics["revision"] > 0 and view["revision"] >= diagnostics["revision"]):
            return {"diagnostics": diagnostics, "view": view}
        sleep(min(1.0, max(0, deadline - clock())))
    raise TimeoutError("Configuration queued, but an authenticated displayed snapshot was not confirmed before timeout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--config", type=Path, required=True, help="Private JSON; never commit this file")
    parser.add_argument("--confirm-timeout", type=float, default=10.0)
    parser.add_argument("--wait-connected", action="store_true", help="Keep this serial session open until an authenticated household snapshot reaches the UI")
    parser.add_argument("--connected-timeout", type=float, default=120.0)
    args = parser.parse_args()
    if not 0.1 <= args.confirm_timeout <= 60:
        parser.error("Confirmation timeout must be between 0.1 and 60 seconds")
    if not 1 <= args.connected_timeout <= 600:
        parser.error("Connected timeout must be between 1 and 600 seconds")
    try:
        data = json.loads(args.config.read_text(), object_pairs_hook=unique_fields)
        commands = commands_for(data)
    except (ValueError, UnicodeError):
        raise SystemExit("Private configuration is invalid or exceeds the documented native bounds") from None
    import serial
    connection = open_port(serial, args.port)
    try:
        try:
            queued = transmit(connection, commands, confirmation_timeout=args.confirm_timeout)
        except (TimeoutError, RuntimeError) as error:
            raise SystemExit(str(error)) from None
        if not queued:
            raise SystemExit("Private configuration rejected; inspect safe hq status")
        if args.wait_connected:
            try:
                result = wait_connected(connection, args.connected_timeout)
            except TimeoutError as error:
                raise SystemExit(str(error)) from None
    finally:
        connection.close()
    if args.wait_connected:
        print("Authenticated household snapshot revision " + str(result["view"]["revision"]) + " reached the UI.")
    else:
        print("Private configuration queued. Inspect hq status and the physical Home HQ screen.")


if __name__ == "__main__":
    main()
