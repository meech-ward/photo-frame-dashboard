#!/usr/bin/env python3
"""Check public source/starter paths and local Markdown links, without network IO."""
import argparse
from pathlib import Path
import posixpath
import re
import subprocess
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[2]
# Keep the old private dependency out of generated bundles as well as the docs.
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
    parser.add_argument("--starter", type=Path, help="also check a generated starter ZIP")
    args = parser.parse_args()
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    # Use all tracked paths for link resolution, while reporting only this fork's
    # additions. Wes's unrelated tooling and historical guides are unchanged.
    files = {name: (ROOT / name).read_bytes() for name in names if name}
    scoped = {name: payload for name, payload in files.items() if name == "HOMEHQ.md" or name.startswith("homehq/")}
    # Outside guides can be relative in a checkout; their presence still counts.
    scoped.update({name: b"" for name in files if name not in scoped})
    check(scoped, "tracked checkout")
    if args.starter:
        with zipfile.ZipFile(args.starter) as archive:
            check({name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}, "starter ZIP")


if __name__ == "__main__":
    main()
