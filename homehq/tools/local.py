#!/usr/bin/env python3
"""Run the pinned local Supabase CLI without printing its generated credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.120.0"
CLI = ROOT / ".tools" / "supabase"


def environment():
    env = os.environ.copy()
    env["SUPABASE_HOME"] = str(ROOT / ".supabase-home")
    env["SUPABASE_EXPERIMENTAL_STACK"] = "1"
    return env


def install():
    if CLI.exists():
        version = subprocess.run([str(CLI), "--version"], env=environment(),
                                 capture_output=True, text=True, check=True).stdout.strip()
        if version == VERSION:
            return
        raise RuntimeError("project-local CLI does not match the pinned version")
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    if not machine or not system:
        raise RuntimeError("unsupported CLI platform")
    name = "supabase_{}_{}_{}.tar.gz".format(VERSION, system, machine)
    base = "https://github.com/supabase/cli/releases/download/v{}/".format(VERSION)
    CLI.parent.mkdir(parents=True, exist_ok=True)
    archive = CLI.parent / name
    checksums = urllib.request.urlopen(base + "checksums.txt", timeout=60).read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines()
                    if line.split()[-1] == name)
    with urllib.request.urlopen(base + name, timeout=120) as source, archive.open("wb") as out:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            out.write(block)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        archive.unlink()
        raise RuntimeError("official CLI checksum mismatch")
    with tarfile.open(archive) as source:
        member = next(m for m in source.getmembers() if m.name in ("supabase", "supabase.exe"))
        source.extract(member, CLI.parent)
    archive.unlink()


def run(args, reveal=False):
    install()
    result = subprocess.run([str(CLI), "--workdir", str(ROOT)] + args,
                            env=environment(), capture_output=True, text=True)
    if result.returncode:
        # CLI errors can include generated keys. Keep raw output in memory;
        # expose only a diagnostic whose line has no credential-like field.
        safe = [line for line in result.stderr.splitlines()
                if not any(word in line.lower() for word in
                           ("key", "token", "password", "secret", "authorization"))]
        print("\n".join(safe[-15:]))
        raise SystemExit(result.returncode)
    if reveal:
        return result.stdout
    print("Local Supabase command completed: {}".format(" ".join(args)))


def status():
    raw = run(["stack", "status", "--output-format", "json"], reveal=True)
    data = json.loads(raw)
    target = ROOT / ".local.private.json"
    descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(str(target), 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(data, handle)
    print("Local runtime metadata saved privately; generated API keys were not printed.")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "start", "stop", "status", "sync", "reset", "test"))
    args = parser.parse_args()
    if args.command == "install":
        install()
        print("Pinned Supabase CLI {} ready.".format(VERSION))
    elif args.command == "start":
        run(["start", "--runtime", "native", "--eager"])
        status()
    elif args.command == "status":
        status()
    elif args.command == "sync":
        run(["db", "schema", "declarative", "sync", "--name", "homehq", "--no-apply", "--strict-coverage"])
    elif args.command == "reset":
        run(["db", "reset", "--local"])
    elif args.command == "test":
        run(["test", "db"])
    else:
        run(["stop"])


if __name__ == "__main__":
    main()
