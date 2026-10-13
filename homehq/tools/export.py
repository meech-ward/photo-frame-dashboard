#!/usr/bin/env python3
"""Export a reproducible public starter; Git allowlists keep local secrets out."""
import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import re
import subprocess
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HOMEHQ = ROOT / "homehq"
APP_REPOSITORY = "https://github.com/meech-ward/photo-frame-dashboard"
SELECT_REPOSITORY = "https://github.com/supabase-community/select-2026-badge"

README = """# Home HQ starter

A Supabase extension of Wes Bos's original web dashboard, with native
Tufty and ModRetro Chromatic clients:
https://github.com/wesbos/photo-frame-dashboard
Public fork: https://github.com/meech-ward/photo-frame-dashboard

This bundle contains the authored schema/config, companion, native source,
tests, local tools and the compiled self-contained badge app. It has no project
credentials, Wi-Fi password, Auth session, cached household or firmware image.

From this extracted directory (Node 22.12+, Python 3.9+, supported native host):

```
python3 homehq/tools/local.py start
python3 homehq/tools/local.py reset
python3 homehq/tools/local.py test
python3 homehq/tools/check_live.py
npm --prefix homehq/web ci
python3 homehq/tools/companion.py
```

Open http://127.0.0.1:5173. The configured editor connects to Supabase automatically.
Sign up in Settings to initialize a private local home, or sign in to restore it.
Saved sessions restore automatically; configured projects never fall back to a
local demo. Reset is for disposable local data; omit it
when keeping edits. A supported native host needs no Docker. Supabase CLI is
pinned and checksum-verified; its download needs internet access.

Start at homehq/HANDOFF.md for the source/output map, setup and porting
seams. Read homehq/README.md, backend-README.md and BUILD.md for the authored source,
ordinary member Auth, hosted deployment and direct on-badge email/password login.
Create/link family logins in Settings as the household owner. Each badge keeps its
own refresh token; passwords and access JWTs never enter durable app state.
The badge network engine retains its cooperative implementation, with Auth/RPC
interfaces matching https://github.com/meech-ward/supabase-micro at aa30dc4e.
The Chromatic's public MCU source, minimal platform patch and build recipe are
documented in homehq/chromatic/README.md. This bundle includes its native source
and tests, not an ESP32 firmware binary. Tufty shared dependencies are copied
under homehq/vendor/tufty with source attribution and individual SHA-256 hashes.
SELECT setup, firmware and current source links are maintained at:
https://badge.select/guides

badge/mpy/homehq is the compiled app (format6, pure bytecode, small-int31).
badge/manifest.json records the pinned toolchain and reproducible build hashes.
Its runtime_verification field records optional simulator checks when supplied;
null means those checks were not run. The API/compiler baseline is Badgeware
3.0.2. Install compatible firmware before copying the app, then verify sign-in,
Realtime and photos on the target device. A successful build alone does not
verify hardware behavior.

Source and infrastructure are portable; the compiled artifact contains no
personalization. The weather, appliance controls and usage meters are samples.
"""


def export(target):
    paths = subprocess.check_output(["git", "ls-files", "-z", "--", "homehq"], cwd=ROOT).split(b"\0")
    files = {}
    for raw in paths:
        if not raw:
            continue
        path = raw.decode()
        if any(part in ("build", ".tools", ".supabase-home", "node_modules", "dist") for part in Path(path).parts) or ".private." in Path(path).name:
            raise ValueError("private/generated path entered Git: " + path)
        if Path(path).name.startswith(".env") and not path.endswith(".env.example"):
            raise ValueError("private environment file entered Git")
        payload = (ROOT / path).read_bytes()
        if path.endswith(".md"):
            parent = Path(path).parent
            def outside_guide(match):
                target = match.group(1)
                if ":" in target or not target.startswith("../"):
                    return match.group(0)
                link = urlsplit(target)
                resolved = posixpath.normpath((parent / unquote(link.path)).as_posix())
                if resolved.startswith("homehq/"):
                    return match.group(0)
                if resolved.startswith("../") or not (ROOT / resolved).exists():
                    raise ValueError("documentation link leaves the public source tree: " + path + ": " + target)
                suffix = ("?" + link.query if link.query else "") + ("#" + link.fragment if link.fragment else "")
                return "](" + APP_REPOSITORY + "/blob/main/" + resolved + suffix + ")"
            # The ZIP contains homehq/, while the public fork also contains Wes's
            # guides. Link to those existing files rather than inventing a target.
            payload = re.sub(r"\]\(([^)]+)\)", outside_guide, payload.decode()).encode()
        files[path] = payload
    # Keep shared source in one explicit vendored subtree. A cold fork has none
    # of the SELECT repository's sibling apps; the builder's fallback uses this
    # same layout without importing conference applications or their credentials.
    from build import inputs
    sources, assets = inputs()
    vendored = {}
    for source in list(sources.values()) + list(assets.values()):
        relative = source.relative_to(ROOT)
        if relative.parts[0] == "homehq":
            if relative.parts[:3] != ("homehq", "vendor", "tufty"):
                continue
            relative = Path(*relative.parts[3:])
        payload = source.read_bytes()
        vendored[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
        files["homehq/vendor/tufty/" + relative.as_posix()] = payload
    # Attribution is authored and verified against the public SELECT export.
    # An app commit is not a valid replacement for those dependencies' origin.
    existing = HOMEHQ / "vendor" / "tufty" / "provenance.json"
    if not existing.is_file():
        raise ValueError("public dependency provenance is missing")
    provenance = json.loads(existing.read_text())
    if provenance.get("repository") != SELECT_REPOSITORY:
        raise ValueError("dependency provenance must reference the public SELECT source")
    additional = provenance.get("additional_sources", {})
    if any(source.get("repository") != APP_REPOSITORY for source in additional.values()):
        raise ValueError("local attribution notes must reference the public application source")
    if set(provenance.get("source_paths", {})) | set(additional) != set(vendored):
        raise ValueError("dependency provenance must account for every exported file")
    if provenance["files"] != vendored:
        raise ValueError("vendored dependency hashes differ from provenance")
    files["homehq/vendor/tufty/provenance.json"] = (json.dumps(provenance, indent=2) + "\n").encode()
    artifact = HOMEHQ / "build" / "standalone"
    manifest = json.loads((artifact / "manifest.json").read_text())
    if not manifest.get("reproducible"):
        raise ValueError("create a reproducible build before exporting a shareable starter")
    for relative, expected in manifest["files"].items():
        payload = (artifact / relative).read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("compiled export changed after verification: " + relative)
        files["badge/" + relative] = payload
    files["badge/manifest.json"] = (artifact / "manifest.json").read_bytes()
    files["README.md"] = README.encode()
    # Check generated content too: a rewritten link or generated README can
    # reintroduce an inaccessible dependency even when tracked docs are clean.
    from check_public import check
    check(files, "starter contents")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, (2026, 10, 11, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name])
    print("Public starter: {} files, {} bytes; no private runtime/state files.".format(len(files), target.stat().st_size))
    print(target.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HOMEHQ / "artifacts" / "homehq-starter.zip")
    args = parser.parse_args()
    export(args.out)
