#!/usr/bin/env python3
"""Export a reproducible public starter; Git allowlists keep local secrets out."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HOMEHQ = ROOT / "homehq"

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
The full SELECT repository's optional browser simulator and firmware instructions are:
https://github.com/meech-ward/select-badge/tree/main/playground
https://github.com/meech-ward/select-badge/blob/main/docs/deploy.md

badge/mpy/homehq is the compiled app (format6, pure bytecode, small-int31).
badge/manifest.json records the pinned toolchain and verified imports/render.
Its API/compiler baseline is the documented Badgeware3.0.2 runtime; the same
compiled modules were also accepted by the selected Tufty bw-1.29.0-gc runtime
(ABI7942). Arbitrary badge firmware needs matching bytecode. A physical install is a separate deliberate development test;
it must not change the stable production release. The selected development
Tufty has native HTTPS/private Realtime, photo decode, Auth rotation and radio
recovery evidence; read the dated record linked from homehq/README.md for measured
latency and limits. Other devices need their own acceptance. Battery life,
physical switches and optical glass appearance have not been measured.

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
            import re
            parent = Path(path).parent
            def outside_guide(match):
                target = match.group(1)
                if ":" in target or not target.startswith("../"):
                    return match.group(0)
                import posixpath
                resolved = posixpath.normpath((parent / target).as_posix())
                if resolved.startswith("homehq/"):
                    return match.group(0)
                return "](https://github.com/meech-ward/select-badge/blob/main/" + resolved + ")"
            # Preserve in-bundle relative guides; route full-repository references
            # to canonical source so an extracted starter has no broken links.
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
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    provenance = {"repository": "https://github.com/meech-ward/select-badge",
                  "checkpoint": revision, "files": vendored}
    # An already-vendored public fork retains its original dependency provenance;
    # its HEAD identifies the application snapshot, not the shared source origin.
    existing = HOMEHQ / "vendor" / "tufty" / "provenance.json"
    if existing.is_file():
        provenance = json.loads(existing.read_text())
        if provenance["files"] != vendored:
            raise ValueError("vendored dependency hashes differ from provenance")
    files["homehq/vendor/tufty/provenance.json"] = (json.dumps(provenance, indent=2) + "\n").encode()
    files["homehq/vendor/tufty/README.md"] = b"""# Tufty build dependencies

These generic source, font and public certificate files are copied unchanged
from the SELECT source repository. Original relative paths and SHA-256 hashes
are in [provenance.json](provenance.json). Font licensing and aiohttp attribution
remain beside their source. No account, device state or compiled file is included.

The builder uses canonical paths in SELECT and this subtree in a standalone
fork or starter. Edit app source under `homehq/badge/homehq/`; shared dependency
changes belong in their source repository. See [BUILD.md](../../BUILD.md).
"""
    artifact = HOMEHQ / "build" / "standalone"
    manifest = json.loads((artifact / "manifest.json").read_text())
    if not manifest.get("reproducible") or not manifest.get("runtime_verification"):
        raise ValueError("build with --verify-runtime before exporting a shareable starter")
    for relative, expected in manifest["files"].items():
        payload = (artifact / relative).read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("compiled export changed after verification: " + relative)
        files["badge/" + relative] = payload
    files["badge/manifest.json"] = (artifact / "manifest.json").read_bytes()
    files["README.md"] = README.encode()
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
