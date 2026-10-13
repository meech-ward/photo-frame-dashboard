#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 2 ]]; then
  echo "Usage: $0 <isolated-mcu-worktree> <chromatic-programming-workspace>" >&2
  exit 2
fi
task_mcu=$(cd "$1" && pwd)
task_workspace=$(cd "$2" && pwd)
export IDF_TOOLS_PATH="${IDF_TOOLS_PATH:-$task_workspace/idf-tools}"
# ESP-IDF activates its own Python environment and compiler paths. A developer's
# Mac-specific interpreter path prevented the same source building elsewhere.
source "$task_workspace/esp-idf/export.sh"
cd "$task_mcu"
idf.py build
python - "$task_mcu/build/mcu_fw.bin" <<'PY'
import hashlib, sys
from pathlib import Path
p = Path(sys.argv[1])
b = p.read_bytes()
assert len(b) <= 0x100000, 'Image does not fit the existing application partition'
print(f'Application-only image: {len(b)} bytes; SHA256={hashlib.sha256(b).hexdigest()}')
PY
