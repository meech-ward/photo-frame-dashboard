#!/usr/bin/env python3
"""Replay short Home HQ controls and retain only safe queued view/status replies."""
import argparse
import json
import re
import time
from pathlib import Path

BUTTONS = {"left", "right", "up", "down", "a", "b", "start", "select"}
PAGES = {"today", "calendar", "chores", "shopping", "photos", "home", "agents"}
DETAILS = {"none", "event", "chores", "who", "routine", "device", "confirm", "agent", "account", "logout", "keyboard"}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
VIEW = re.compile(r"HQ view page=([a-z]+) detail=([a-z]+) focus=(-?\d+) revision=(\d+) viewer=([A-Za-z0-9_.-]{1,48}) minheap=(\d+)")
STATUS = re.compile(r"HQ state=([A-Za-z0-9 .,_-]{1,48}) pending=(\d+) heap=(\d+) largest=(\d+)")
DIAGNOSTICS = re.compile(r"HQ diagnostics configured=([01]) authenticated=([01]) session_saved=([01]) pending=(\d+) revision=(\d+)(?: radio_paused=([01]))?(?: clock_ready=([01]))?(?: realtime_joined=([01]))?")
WIFI = re.compile(r"HQ wifi enabled=([01]) connected=([01]) reason=(-?\d+)")
CLOCK = re.compile(r"clock ([0-9]{10})")
CLOCK_REPLY = re.compile(r"HQ clock=(accepted|rejected)")
RADIO_REPLY = re.compile(r"HQ radio=(off|on|rejected)")
PHOTO = re.compile(r"HQ photo download_ok=(\d+) download_failed=(\d+) stage=(\d+) http_status=(\d+) cache_hits=(\d+) cache_misses=(\d+) cache_saved=(\d+) cache_save_failed=(\d+) cache_clear_failed=(\d+)(?: tls_error=(-?\d+) transport_error=(-?\d+))?")
PHOTO_FIELDS = ("download_ok", "download_failed", "stage", "http_status", "cache_hits", "cache_misses",
                "cache_saved", "cache_save_failed", "cache_clear_failed")
EPOCH_MIN, EPOCH_MAX = 1704067200, 4102444800
PHYSICAL_FIELDS = {"physical_" + button for button in BUTTONS}
INPUT_FIELDS = PHYSICAL_FIELDS | {"held_buttons", "blocked_inputs", "snapshot_waiting", "hydrated_page"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate diagnostic field")
        result[key] = value
    return result


def safe_buttons(payload):
    # The source is still raw UART. Admit exactly the public counters emitted
    # on the LVGL task, never an arbitrary JSON object from an auth response.
    try:
        fields = json.loads(payload, object_pairs_hook=unique_object)
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(fields, dict) or set(fields) != INPUT_FIELDS:
        return None
    for key in PHYSICAL_FIELDS | {"blocked_inputs", "held_buttons"}:
        maximum = 65535 if key == "held_buttons" else 4294967295
        if type(fields[key]) is not int or not 0 <= fields[key] <= maximum:
            return None
    if type(fields["snapshot_waiting"]) is not bool:
        return None
    if type(fields["hydrated_page"]) is not str or fields["hydrated_page"] not in PAGES:
        return None
    return {"kind": "buttons", **fields}


def command_for(step):
    if step in BUTTONS:
        command = "hq input " + step
    elif step in {"status", "view", "refresh", "diagnostics"}:
        command = "hq " + step
    elif CLOCK.fullmatch(step) and EPOCH_MIN <= int(CLOCK.fullmatch(step)[1]) <= EPOCH_MAX:
        command = "hq " + step
    elif step in {"radio off", "radio on"}:
        command = "hq " + step
    else:
        raise ValueError("A probe step must be a documented button, status, view, diagnostics or refresh")
    # The UART has lost console input above 96 bytes. This allowlist also makes
    # it impossible for a probe to echo a provisioning chunk or a credential.
    if len(command.encode("ascii")) >= 96:
        raise ValueError("Probe command exceeds the short-line transport bound")
    return (command + "\r\n").encode("ascii")


def safe_reply(line):
    line = ANSI.sub("", line).strip("\r")
    if line.startswith("mcu>"):
        line = line[4:].lstrip(" \t")
    match = VIEW.fullmatch(line)
    if match and match[1] in PAGES and match[2] in DETAILS:
        return {"kind": "view", "page": match[1], "detail": match[2], "focus": int(match[3]),
                "revision": int(match[4]), "viewer": match[5], "minheap": int(match[6])}
    match = STATUS.fullmatch(line)
    if match:
        return {"kind": "status", "state": match[1], "pending": int(match[2]),
                "heap": int(match[3]), "largest": int(match[4])}
    match = DIAGNOSTICS.fullmatch(line)
    if match:
        reply = {"kind": "diagnostics", "configured": int(match[1]), "authenticated": int(match[2]),
                 "session_saved": int(match[3]), "pending": int(match[4]), "revision": int(match[5])}
        if match[6] is not None:
            reply["radio_paused"] = int(match[6])
        if match[7] is not None:
            reply["clock_ready"] = int(match[7])
        if match[8] is not None:
            reply["realtime_joined"] = int(match[8])
        return reply
    match = WIFI.fullmatch(line)
    if match:
        return {"kind": "wifi", "enabled": int(match[1]), "connected": int(match[2]), "reason": int(match[3])}
    match = CLOCK_REPLY.fullmatch(line)
    if match:
        return {"kind": "clock", "accepted": match[1] == "accepted"}
    match = RADIO_REPLY.fullmatch(line)
    if match:
        return {"kind": "radio", "state": match[1]}
    match = PHOTO.fullmatch(line)
    if match:
        fields = dict(zip(PHOTO_FIELDS, map(int, match.groups()[:9])))
        if all(value <= 4294967295 for value in fields.values()) and fields["stage"] <= 16 and fields["http_status"] <= 999:
            if match[10] is not None:
                codes = (int(match[10]), int(match[11]))
                if not all(-2147483648 <= code <= 2147483647 for code in codes): return None
                fields.update(tls_error=codes[0], transport_error=codes[1])
            return {"kind": "photo", **fields}
    if line.startswith("HQ buttons "):
        return safe_buttons(line[len("HQ buttons "):])
    return None


class SafeCapture:
    def __init__(self):
        self.buffer = bytearray()
        self.discard = False

    def clear(self):
        for index in range(len(self.buffer)):
            self.buffer[index] = 0
        self.buffer.clear()

    def feed(self, data):
        replies = []
        for byte in data:
            if byte == 10:
                if not self.discard:
                    try:
                        reply = safe_reply(self.buffer.decode("ascii"))
                    except UnicodeDecodeError:
                        reply = None
                    if reply:
                        replies.append(reply)
                self.clear()
                self.discard = False
            elif not self.discard:
                if len(self.buffer) >= 512:
                    self.clear()
                    self.discard = True
                else:
                    self.buffer.append(byte)
        return replies

    def flush_idle(self):
        if self.discard:
            return []
        try:
            reply = safe_reply(self.buffer.decode("ascii"))
        except UnicodeDecodeError:
            reply = None
        if reply:
            self.clear()
            return [reply]
        return []


def wait_ready(connection, timeout=10.0, clock=time.monotonic, sleep=time.sleep):
    # This USB CDC bridge resets the MCU even with DTR/RTS pre-set low. A
    # completed REPL prompt, rather than a fixed sleep, gates all private data.
    started = clock()
    prompt = re.compile(rb"(?:^|[\r\n])mcu>[ \t]*$")
    buffer = bytearray()
    next_blank = started
    try:
        while clock() - started < timeout:
            if clock() >= next_blank:
                connection.write(b"\r\n")
                connection.flush()
                next_blank = clock() + 0.5
            data = connection.read(2048)
            buffer.extend(data)
            if len(buffer) > 512:
                del buffer[:-512]
            if prompt.search(ANSI.sub("", bytes(buffer).decode("ascii", "ignore")).encode("ascii")):
                return
            sleep(0.02)
    finally:
        for index in range(len(buffer)):
            buffer[index] = 0
    raise TimeoutError("Home HQ console did not become ready; no private data or button action sent")


def execute(connection, steps, settle=0.25, timeout=3.0, clock=time.monotonic, sleep=time.sleep):
    commands = [(step, command_for(step)) for step in steps]
    capture = SafeCapture()
    records = []
    for step, command in commands:
        connection.write(command)
        connection.flush()
        started = clock()
        required = step if step in {"status", "view", "diagnostics"} else "clock" if CLOCK.fullmatch(step) else "radio" if step in {"radio off", "radio on"} else None
        confirmed = required is None
        last_data = started
        while clock() - started < timeout:
            data = connection.read(2048)
            if data:
                last_data = clock()
            replies = capture.feed(data)
            if not data and clock() - last_data >= 0.1:
                replies.extend(capture.flush_idle())
            for reply in replies:
                records.append({"step": step, **reply})
                if reply["kind"] == required:
                    confirmed = True
            # Queued view metadata is followed by button counters. Drain until
            # idle so a fragmented second safe line belongs to the same step.
            if confirmed and clock() - started >= settle and clock() - last_data >= 0.1:
                break
            sleep(0.02)
        if not confirmed:
            capture.clear()
            raise TimeoutError("No safe Home HQ " + required + " reply; raw UART input was discarded")
    capture.clear()
    return records


def assert_view(records, expected):
    if not expected:
        return
    views = [record for record in records if record["kind"] == "view"]
    if not views:
        raise ValueError("A view step is required for semantic assertions")
    for key, value in expected.items():
        if views[-1][key] != value:
            raise AssertionError("Home HQ view did not match expected " + key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Explicit Chromatic MCU serial port; the caller owns it")
    parser.add_argument("--steps", default="status,view", help="Comma-separated allowlisted controls, for example right,view")
    parser.add_argument("--settle", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--expect-page", choices=sorted(PAGES))
    parser.add_argument("--expect-detail", choices=sorted(DETAILS))
    parser.add_argument("--expect-focus", type=int)
    parser.add_argument("--expect-viewer")
    parser.add_argument("--expect-revision", type=int)
    parser.add_argument("--output", type=Path, help="Optional JSON of safe diagnostic fields, never raw UART")
    args = parser.parse_args()
    steps = [step.strip() for step in args.steps.split(",") if step.strip()]
    if not steps or not 0.02 <= args.settle <= args.timeout <= 60:
        parser.error("Use at least one step and 0.02 <= settle <= timeout <= 60 seconds")
    try:
        for step in steps:
            command_for(step)
    except ValueError as error:
        parser.error(str(error))
    import serial
    # Set line states before opening: console probes should not intentionally
    # reset the MCU. The port is explicit and never opened by unit tests.
    connection = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1,
                               dsrdtr=False, rtscts=False)
    connection.dtr = False
    connection.rts = False
    connection.port = args.port
    try:
        connection.open()
        connection.reset_input_buffer()
        wait_ready(connection)
        records = execute(connection, steps, args.settle, args.timeout)
    finally:
        connection.close()
    expected = {key: value for key, value in {
        "page": args.expect_page, "detail": args.expect_detail, "focus": args.expect_focus,
        "viewer": args.expect_viewer, "revision": args.expect_revision}.items() if value is not None}
    assert_view(records, expected)
    result = {"steps": steps, "records": records, "assertions": expected}
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
