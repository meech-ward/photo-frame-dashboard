#!/usr/bin/env python3
"""Back up the selected MCU, then write only Home HQ's factory app region."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--python", required=True, help="Python interpreter with esptool 4.12.0")
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Write the application after a successful fresh backup")
    args = parser.parse_args()
    image = args.image.resolve().read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    if digest != args.sha256 or not 0 < len(image) <= 0x100000:
        raise SystemExit("Image digest/1 MiB factory partition gate failed")
    if b"0.13.4-homehq1" not in image:
        raise SystemExit("Expected the Home HQ application version")
    # A generic serial port may be another device. Require the stable Linux
    # ModRetro path or a deliberately selected Mac Chromatic USB serial path.
    if "usb-ModRetro_Chromatic" not in args.port and not args.port.startswith("/dev/cu.usbmodem"):
        raise SystemExit("Select the enumerated Chromatic MCU port explicitly")
    print(f"Home HQ application: {len(image)} bytes, SHA256 {digest}")
    if not args.apply:
        print("Inspection only. No serial port opened.")
        return
    target = args.backup_root.resolve() / datetime.now(timezone.utc).strftime("homehq-%Y%m%dT%H%M%SZ")
    target.mkdir(parents=True, exist_ok=False)
    command = [args.python, "-m", "esptool", "--chip", "esp32", "--port", args.port, "--baud", "460800"]
    backup = target / "before-homehq.bin"
    # Preserve the currently installed experiment and its NVS before replacing
    # any byte. A successful backup is a hard prerequisite for this app write.
    subprocess.run(command + ["read_flash", "0", "ALL", str(backup)], check=True)
    original = backup.read_bytes()
    if len(original) != 0x400000:
        raise SystemExit("Expected the documented 4 MiB ESP32; no application written")
    before = hashlib.sha256(original).hexdigest()
    (target / "before-application.bin").write_bytes(original[0x10000:0x110000])
    record = {"image_sha256": digest, "image_bytes": len(image), "backup_sha256": before,
              "backup_bytes": len(original), "port": args.port, "offset": "0x10000", "write": "not-started"}
    metadata = target / "deployment.private.json"
    metadata.write_text(json.dumps(record, indent=2) + "\n")
    record["write"] = "started"
    metadata.write_text(json.dumps(record, indent=2) + "\n")
    try:
        subprocess.run(command + ["--after", "hard_reset", "write_flash", "0x10000", str(args.image.resolve())], check=True)
    except subprocess.CalledProcessError:
        record["write"] = "unverified"
        metadata.write_text(json.dumps(record, indent=2) + "\n")
        raise
    record["write"] = "esptool-verified"
    metadata.write_text(json.dumps(record, indent=2) + "\n")
    print("Application write verified. Open Home HQ and perform the hardware acceptance checks.")


if __name__ == "__main__":
    main()
