#!/usr/bin/env bash
# Checks before pushing a triage branch. Read-only. Exit status 1 if anything needs attention.
#   checks.sh [base]     base defaults to origin/main
# Conflict markers, broken links and anchors, Python/shell syntax, the kiosk build (if the Android
# SDK is installed), and a privacy sweep of everything the branch adds compared with base.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
BASE=${1:-origin/main}
status=0

echo "== Conflict markers"
if git grep -n -E '^(<<<<<<<|>>>>>>>)( |$)|^=======$' -- '*.md' '*.py' '*.sh' '*.java' '*.xml' '*.in' '*.cmd'; then
  status=1
else echo "none"; fi

echo "== Links and anchors"
python3 -I - <<'PY' || status=1
import re, sys
from pathlib import Path
def slug(h): return re.sub(r"[^\w\- ]", "", h.strip().lower().replace("`", "")).replace(" ", "-")
files = [Path("README.md")] + [p for p in Path(".").rglob("*.md") if not any(x in p.parts for x in (".git", "node_modules", "diagnostics", "backups", ".claude"))]
bad = 0
for q in set(files):
    txt = q.read_text(errors="replace")
    for link in re.findall(r'\]\(([^)\s]+)\)', txt) + re.findall(r'src="([^"]+)"', txt):
        if link.startswith(("http", "mailto")) or "$" in link or "<" in link: continue
        f, _, a = link.partition("#"); tgt = (q.parent / f) if f else q
        if not tgt.exists(): print(f"MISSING  {q}: {link}"); bad += 1; continue
        if a and tgt.is_file() and tgt.suffix == ".md":
            if a not in {slug(h) for h in re.findall(r"^#+ (.+)$", tgt.read_text(errors="replace"), re.M)}:
                print(f"ANCHOR   {q}: {link}"); bad += 1
print(f"{bad} broken"); sys.exit(1 if bad else 0)
PY

echo "== Syntax"
n=0
for f in $(git ls-files '*.py'); do python3 -m py_compile "$f" 2>/dev/null || { echo "python: $f"; n=1; }; done
for f in $(git ls-files '*.sh'); do bash -n "$f" 2>/dev/null || { echo "shell: $f"; n=1; }; done
find . -name __pycache__ -not -path './.git/*' -prune -exec rm -rf {} + 2>/dev/null
[ $n = 0 ] && echo "ok" || status=1

echo "== Kiosk build"
SDK=${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}
if [ -d "$SDK/build-tools/34.0.0" ] && git diff --quiet "$BASE" HEAD -- dashboard/kiosk; then
  echo "kiosk unchanged; skipped"
elif [ -d "$SDK/build-tools/34.0.0" ]; then
  ANDROID_HOME=$SDK bash dashboard/kiosk/build.sh >/dev/null 2>&1 && echo "ok" || { echo "kiosk build FAILED"; status=1; }
else
  echo "Android SDK not found; build the kiosk by hand if dashboard/kiosk changed"
fi

echo "== Privacy and hidden text in what this branch adds (vs $BASE)"
git diff --numstat "$BASE" HEAD | awk '$1=="-"{print "binary (look at it): "$3}'
git diff "$BASE" HEAD | python3 -I -c '
import re, sys
add = [l[1:] for l in sys.stdin.read().splitlines() if l.startswith("+") and not l.startswith("+++")]
found = False
def report(name, items):
    global found
    items = sorted(set(items))
    if items: found = True; print(f"{name}: {items[:20]}")
mac = r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b"
report("MAC-like", [m for l in add for m in re.findall(mac, l) if m.lower() not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff")])
priv = re.compile(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|127\.|0\.|255\.|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|8\.8\.8\.8|1\.1\.1\.1|224\.)")
report("public IPv4", [m for l in add for m in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", l) if not priv.match(m) and all(int(x) < 256 for x in m.split("."))])
report("email", [m for l in add for m in re.findall(r"\b[\w.+-]+@[\w-]+\.[A-Za-z]{2,}\b", l) if "noreply" not in m and not m.startswith("git@")])
report("secret-like", [l.strip()[:120] for l in add if re.search(r"(api[_-]?key|secret|token|passwd|password)\s*[:=]\s*[\"\x27]?[A-Za-z0-9/+_\-]{12,}|BEGIN [A-Z ]*PRIVATE KEY", l, re.I)])
report("hidden or bidi characters", [repr(l[:80]) for l in add if re.search("[​-‏‪-‮⁦-⁩﻿]", l)])
report("HTML comments (check each)", [l.strip()[:100] for l in add if "<!--" in l])
hashes = sorted({m for l in add for m in re.findall(r"\b[0-9a-f]{64}\b", l)})
if hashes: print(f"64-hex hashes added: {len(hashes)} (make sure none is a whole-disk hash)")
sys.exit(1 if found else 0)
' || { echo "-> review the items above"; status=1; }

exit $status
