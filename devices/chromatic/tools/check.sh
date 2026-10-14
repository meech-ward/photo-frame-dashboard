#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 3 ]]; then
  echo "Usage: $0 <prepared-mcu-worktree> <chromatic-programming-workspace> <host-output-directory>" >&2
  exit 2
fi
task_mcu=$(cd "$1" && pwd)
task_workspace=$(cd "$2" && pwd)
task_host_output="$3"
python3 devices/chromatic/tools/prepare.py --mcu "$task_mcu"
cmake -S devices/chromatic/tests -B "$task_host_output" -G Ninja \
  -DMCU_ROOT="$task_mcu" -DIDF_ROOT="$task_workspace/esp-idf"
cmake --build "$task_host_output"
ctest --test-dir "$task_host_output" --output-on-failure
python3 -m unittest discover -s devices/chromatic/tests -p 'test_*.py'
HQ_PHOTO_SANITIZE=1 UBSAN_OPTIONS=halt_on_error=1 python3 devices/chromatic/tests/test_photo_mailbox.py
bash devices/chromatic/tools/build.sh "$task_mcu" "$task_workspace"
git diff --check
