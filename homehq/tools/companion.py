#!/usr/bin/env python3
"""Configure and run the loopback companion for a local or hosted project."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from configure import project

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="5173")
    parser.add_argument("--url", help="Hosted HTTPS project URL; otherwise use the local stack")
    parser.add_argument("--key-file", help="File containing only the hosted publishable/anon key")
    args = parser.parse_args()
    if args.key_file and not args.url:
        parser.error("--key-file requires --url")
    url, key = project(not bool(args.url), args.url, args.key_file)
    values = {"VITE_SUPABASE_URL": url, "VITE_SUPABASE_PUBLISHABLE_KEY": key}
    # JSON string syntax is also valid dotenv quoting, including escaped values.
    path = ROOT / "web" / ".env.local"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write("\n".join(name + "=" + json.dumps(value) for name, value in values.items()) + "\n")
    print("Companion configured with URL + publishable key only.", flush=True)
    raise SystemExit(subprocess.call(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", args.port, "--strictPort"], cwd=ROOT / "web"))


if __name__ == "__main__":
    main()
