#!/usr/bin/env python3
"""Check public source paths and local Markdown links, without network IO."""
import argparse
from pathlib import Path
import posixpath
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
# Keep the old private dependency out of the public application and docs.
PRIVATE_SOURCE = "meech-ward/" + "select-badge"
MARKDOWN_LINK = re.compile(r"\]\(<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\)")


def check(files, label):
    failures = []
    for name, payload in files.items():
        path = Path(name)
        if ".private." in path.name or (path.name.startswith(".env") and path.name != ".env.example"):
            failures.append(name + ": private configuration must not be published")
        if any(part in ("node_modules", ".tools", ".supabase-home") for part in path.parts):
            failures.append(name + ": local dependency output must not be published")
        try:
            source = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if PRIVATE_SOURCE in source:
            failures.append(name + ": private source reference")
        if re.search(r"/(?:Users|home)/[\w.-]+/(?:Projects|\.codex)/", source):
            failures.append(name + ": machine-specific source path")
        if path.suffix != ".md":
            continue
        for target in MARKDOWN_LINK.findall(source):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = posixpath.normpath(posixpath.join(path.parent.as_posix(), unquote(parsed.path)))
            if destination not in files and not any(key.startswith(destination.rstrip("/") + "/") for key in files):
                failures.append(name + ": missing relative link " + target)
    if failures:
        raise SystemExit("\n".join(label + ": " + failure for failure in failures))
    print("PASS {}: {} files; no private source/config paths or missing relative Markdown links".format(label, len(files)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True)
    if tracked.returncode:
        parser.error("source checks require a Git checkout")
    # The whole checkout resolves links, while the check stays focused on this
    # fork's additions instead of auditing unrelated Android-frame tooling.
    files = {name: (ROOT / name).read_bytes() for name in tracked.stdout.split("\0") if name}
    prefixes = ("dashboard/", "devices/", "supabase/", "fixtures/", "tools/", "docs/homehq/")
    scoped = {name: payload if name == "README.md" or name.startswith(prefixes) else b""
              for name, payload in files.items()}
    check(scoped, "tracked checkout")


if __name__ == "__main__":
    main()
