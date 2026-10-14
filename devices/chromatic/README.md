# Home HQ on the ModRetro Chromatic

This native ESP32/LVGL port uses the same Home HQ fixture, household contract,
ordinary Auth accounts and companion editor as the badges. It adapts the seven
pages to the Chromatic's 160×144 RGB565 overlay. It is an MCU application, built
on the ModRetro MCU firmware, not a Game Boy cartridge ROM.

Development hardware has passed seven-page rendering, physical Start/Right/A,
login, live writes, Realtime reconnect, saved-session recovery, private photo
rendering and offline two-photo restoration. A maximum-size PNG completed by a
25.3-second poll; cancelling its transfer preserved navigation. The measured
minimum reconnect heap was 16,500 bytes. These results describe a bounded
acceptance run, not general timing or endurance guarantees.

The public MCU baseline below has separate build and host-test acceptance;
that exact rebuilt image has not yet been installed on hardware. Battery
endurance, abrupt physical power loss, extended soak and a complete physical
keyboard sweep remain unmeasured. Reproduce the host checks and perform the
installation checklist for your device.

## Controls

| Control | Action |
| --- | --- |
| Left / Right | Previous / next page; Right opens the routine picker inside chores |
| Up / Down | Select rows, photos or keyboard keys; browse event details |
| A | Open, complete/undo, confirm, or pause/resume |
| B | Back or cancel |
| Start | Return to Today |
| Select | Account settings, sign-in or local logout |

The native keyboard has lowercase, uppercase and symbol banks, plus Delete,
Space, Mode and Save. Passwords are masked, and case/spaces are preserved.
The four family names remain visible on Today; focused long chore titles scroll.
Home controls still change explicitly labelled sample data, not real appliances.

For architecture, memory limits and the recorded hardware investigations, see
[the development notes](DEVELOPMENT.md).

## Build an isolated MCU image

Use a fresh checkout of the public
[ModRetro MCU source](https://github.com/ModRetro/oss-chromatic-console-mcu) at
`6c94613da72420f6a364e0024681401bd69184ba`. `prepare.py` verifies its required
files and applies the checked-in [platform patch](tools/mcu-baseline.patch)
before copying the Home HQ overlay. The patch supplies the display/startup and
button/FPGA integration; it contains
no camera/bloom application or private inputs. Its exact source and checksums
are in [mcu-baseline.json](tools/mcu-baseline.json), with the upstream
[GPL-3.0 license](tools/mcu-baseline-LICENSE).

The fresh public-source build passes: 1,039,216 bytes, with 9,360 bytes free in the factory app partition. Its
SHA-256 is `1ce73fd7c0d33f286b7877a7fdfccbed3416edcb62b88b62f7fc8f506733e7df`.
That image has build/host acceptance; the physical results above belong to the
previously installed image. Keep the dependency checkout
separate from the Home HQ source. From the repository root, choose an empty workspace path without spaces:

```sh
export CHROMATIC_WORKSPACE=/absolute/path/to/chromatic-homehq
mkdir -p "$CHROMATIC_WORKSPACE"
git clone https://github.com/ModRetro/oss-chromatic-console-mcu.git \
  "$CHROMATIC_WORKSPACE/mcu"
git -C "$CHROMATIC_WORKSPACE/mcu" checkout --detach \
  6c94613da72420f6a364e0024681401bd69184ba
git clone --branch v5.3 --recursive https://github.com/espressif/esp-idf.git \
  "$CHROMATIC_WORKSPACE/esp-idf"
export IDF_TOOLS_PATH="$CHROMATIC_WORKSPACE/idf-tools"
"$CHROMATIC_WORKSPACE/esp-idf/install.sh" esp32
python3 -m venv "$CHROMATIC_WORKSPACE/prepare-python"
"$CHROMATIC_WORKSPACE/prepare-python/bin/python" -m pip install Pillow
"$CHROMATIC_WORKSPACE/prepare-python/bin/python" \
  devices/chromatic/tools/prepare.py --mcu "$CHROMATIC_WORKSPACE/mcu"
bash devices/chromatic/tools/build.sh "$CHROMATIC_WORKSPACE/mcu" \
  "$CHROMATIC_WORKSPACE"
```

Install the normal Git, Python, CMake and Ninja host prerequisites using
[Espressif's ESP-IDF v5.3 setup guide](https://docs.espressif.com/projects/esp-idf/en/v5.3/esp32/get-started/linux-macos-setup.html).
The preparation environment uses Pillow for the shared demo and three sample
images. ESP-IDF activates its own Python/compiler environment; the wrapper also
respects an existing `IDF_TOOLS_PATH`. The MCU's tracked `dependencies.lock`
pins LVGL 8.4.0, which the IDF component manager downloads during the build.
There is no need to copy another machine's `managed_components` directory.

The build uses exact ESP-IDF v5.3 and must pass the original 1 MiB app partition
gate. `prepare.py` excludes camera/server assets,
uses client-only TLS and app-authored styles, and fixes the LVGL timer's
microseconds/milliseconds mismatch. The 16-row DMA draw stripe is allocated once
in internal RAM; the original full-frame zero-initialized DMA array is excluded
from the flash image.
ESP32 ROM nano formatting reduces unused formatter code; this app uses standard
floating formats and 32-bit integers.

Generated C assets, build images, snapshots, backup dumps and private provisioning
files are outputs, not canonical sources. No password or access JWT belongs in
the image. The PNG dependency's pin, license and local fix are in
[`src/vendor/pngle/UPSTREAM.md`](src/vendor/pngle/UPSTREAM.md).

## Focused host checks

```sh
cmake -S devices/chromatic/tests -B "$CHROMATIC_WORKSPACE/host-tests" -G Ninja \
  -DMCU_ROOT="$CHROMATIC_WORKSPACE/mcu" \
  -DIDF_ROOT="$CHROMATIC_WORKSPACE/esp-idf"
cmake --build "$CHROMATIC_WORKSPACE/host-tests"
ctest --test-dir "$CHROMATIC_WORKSPACE/host-tests" --output-on-failure
python3 devices/chromatic/tests/test_photo_decode.py
python3 devices/chromatic/tests/test_wire.py
python3 devices/chromatic/tests/test_projection.py
python3 devices/chromatic/tests/test_physical_probe.py
python3 devices/chromatic/tests/test_provision.py
HQ_PHOTO_SANITIZE=1 UBSAN_OPTIONS=halt_on_error=1 \
  python3 devices/chromatic/tests/test_photo_mailbox.py
```

The real LVGL navigation lane writes native PPM screenshots. Service and Realtime
tests mock hardware/network boundaries and exercise actual implementation code.
They establish host behavior, not ESP32 radio, physical buttons, battery life or
power-loss durability.

## Application-only installation and private setup

Power the Chromatic on normally with its cartridge inserted. Identify the actual
ModRetro USB MCU port on your programming computer. Keep one process in charge
of serial access.

Transfer the exact size-checked binary and compare SHA-256 on the programming
host. `tools/deploy.py` verifies its version/digest, makes a fresh full MCU backup,
then writes **only `0x10000`**. It requires esptool 4.12.0 and an explicit port:

```sh
python3 devices/chromatic/tools/deploy.py \
  --image "$CHROMATIC_WORKSPACE/mcu/build/mcu_fw.bin" --sha256 VERIFIED_DIGEST \
  --port SELECTED_MCU_PORT --python /absolute/path/to/python-with-esptool \
  --backup-root /private/path/to/chromatic-backups --apply
```

This is not generic `idf.py flash`. A failed/uncertain write is investigated
before retrying. Preserve the fresh private backup and recovery application.
Successful esptool hash verification is an install claim only.

Prepare a private JSON file containing exactly `wifi_ssid`, `wifi_password`,
`url`, `key` (project publishable key), `email` and `password`. Use the existing
household's ordinary member login; do not reuse another device's Auth session.
With the programmer's Python/pyserial, send it using:

```sh
python3 devices/chromatic/tools/provision.py --port SELECTED_MCU_PORT --config PRIVATE_CONFIG_JSON
```

Add `--wait-connected --connected-timeout 120` to keep that same serial session
open until a durable ordinary Auth session and its household snapshot reach the
UI. This avoids reopening the bridge before the first login has completed.
The default confirms queued setup only; an uncertain setup is never resent.

The helper waits for the MCU console prompt, sends the trusted programmer's UTC
seconds through `hq clock`, confirms acceptance, then sends short UART chunks and
discards console input echoes. Opening this USB CDC bridge can restart the MCU
even with DTR/RTS held low; the bounded prompt wait covers that startup. It
recognizes fragmented queued/rejected replies and never automatically resends
an uncertain setup. Queued setup still needs the device's Connected state.
The validated clock is stored separately in app-owned NVS and restored on cold
boot; ordinary NTP remains enabled and HTTPS certificate verification stays
enabled. An authenticated snapshot refreshes that checkpoint, with normal
checkpoint writes limited to once per hour. Wi-Fi/project
configuration persists; Auth passwords and access tokens remain transient, and only refresh/user data
is saved for the session. Later sign-in is available on the device. `hq status`
prints safe state, pending count and heap metrics. `hq input left|right|up|down|a|b|start|select`
replays navigation through the LVGL task; it does not prove physical button wiring.

`hq view` also queues its snapshot read on the LVGL task. It reports page, detail,
focus, revision, a safe person label and minimum free heap, followed by fixed
button counters, held mask, blocked-input count and hydration state. For a bounded serial
check from the repository root:

```sh
python3 devices/chromatic/tools/physical_probe.py --port SELECTED_MCU_PORT \
  --steps diagnostics,status,view --expect-page today --expect-detail none \
  --output /private/tmp/homehq-safe-view.json
```

The probe waits for the console prompt and retains only recognized Home HQ
status/view fields, including prompt-prefixed replies. Its allowlisted steps
also include `diagnostics`, which reports Auth/session flags, revision, Realtime join and Wi-Fi
connection/reason numbers without private connection or account strings. The steps
accept bounded public `clock <UTCseconds>` and explicit `radio off` / `radio on`
controls for offline/recovery checks; radio controls retain the saved setup.
`hq radio off` pauses reconnection while preserving cached data and pending
edits; `hq radio on` resumes the saved connection. Inspect `clock_ready`,
`radio_paused`, `authenticated`, revision and hydration flags before interpreting
a stalled view or ignored button as a hardware fault.
Button sequences such as `right,view` and their assertions check the resulting
view. It cannot send private provisioning data or retain raw console echoes.

After installation, verify cold boot/overlay, every physical control, all pages
and details, fresh login, refresh/restart, companion fanout, checklist retries and
conflicts, Wi-Fi interruption/recovery, private images, logout clearing, minimum
heap, and battery-only operation. Record actual screen captures and server
convergence separately from host checks.
