#!/usr/bin/env python3
"""Send a private Home HQ configuration through bounded UART console lines."""
import argparse
import base64
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--config", type=Path, required=True, help="Private JSON; never commit this file")
    args = parser.parse_args()
    import serial
    data = json.loads(args.config.read_text())
    fields = ("wifi_ssid", "wifi_password", "url", "key", "email", "password")
    if set(data) != set(fields) or any(not isinstance(data[key], str) for key in fields):
        raise SystemExit("Private config must contain exactly the six documented string fields")
    if not data["url"].startswith("https://") or not data["key"].startswith("sb_publishable_"):
        raise SystemExit("Use HTTPS and the ordinary project publishable key")
    wire = base64.b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    if len(wire) >= 4096:
        raise SystemExit("Configuration exceeds the native provisioning buffer")
    commands = ["hq config-begin"] + ["hq config-part " + wire[i:i+64] for i in range(0, len(wire), 64)] + ["hq config-save"]
    with serial.Serial(args.port, 115200, timeout=0.2, dsrdtr=False) as connection:
        time.sleep(1)
        connection.reset_input_buffer()
        for command in commands:
            connection.write((command + "\r\n").encode())
            time.sleep(0.18)
            # Linenoise echoes input, including this private transport. Discard
            # it locally; never relay it to a terminal transcript or log file.
            reply = connection.read(8192)
        if b"HQ provision=queued" not in reply:
            raise SystemExit("Provisioning reply not confirmed; use safe hq status, do not dump raw UART input")
    print("Private configuration queued. Inspect hq status and the physical Home HQ screen.")


if __name__ == "__main__":
    main()
