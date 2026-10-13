# Home HQ on the ModRetro Chromatic

This native ESP32/LVGL port uses the same Home HQ fixture, household contract,
ordinary Auth accounts and companion editor as the badges. It adapts the seven
pages to the Chromatic's 160×144 RGB565 overlay. It is an MCU application, built
on the ModRetro MCU firmware, not a Game Boy cartridge ROM.

Current validation: the final 1,039,216-byte application is installed on the
physical Chromatic, connected to the configured Wi-Fi and signed in to the live
household at revision 253. Seven USB-rendered pages, owner-confirmed physical
Start/Right/A, live writes/reconnect/reboot recovery, private Realtime, full
320 KiB private photo rendering, replacement, offline two-frame restoration,
cache restart and sign-out clearing are recorded. The final maximum-size photo
completed by the 25.3-second poll; canceling a transfer preserved navigation with
zero blocked inputs. Final reconnect minimum heap was 16,500 bytes. All six
CTests and 50 Python tests pass with the actual hosted fixture, plus photo
ASan/UBSan in both byte orders; the post-rebase build matches the installed SHA.
Temporary server photos were removed and original paths restored. Battery
endurance, abrupt physical power loss, extended soak and a complete physical
keyboard sweep remain unmeasured. See the [evidence record](https://github.com/meech-ward/select-badge/blob/main/benchmark/results/reports/2026-10-12-homehq-chromatic.md).

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

## Source and runtime

`src/homehq_ui.c` owns widgets, navigation and the display snapshot. The sole
LVGL task reads physical button edges and consumes semantic diagnostic inputs.
`src/homehq_service.c` runs HTTPS and Wi-Fi in a separate FreeRTOS worker. It
retains the canonical snapshot as JSON bytes, persists a coalesced 32-command
desired-value outbox, and checkpoints rotated refresh tokens before RPC work.
`src/homehq_projection.c` compacts an owned wire copy without allocations before
the UI parses it. The single decoded graph keeps core household/viewer/people
metadata and every row used by the active page; navigation hydrates another page
from the canonical stored snapshot. The old graph is released before decoding
its replacement. A failed decode retains the last useful view, blocks stale
actions and retries hydration.

The display uses a 16-row RGB565 DMA stripe: 5,120 bytes instead of a 46,080-byte
full framebuffer, saving 40,960 bytes of RAM. The authenticated revision-238 cold
boot measured 94,868 bytes free, a 90,112-byte largest block and a 92,572-byte
minimum free heap, with hydration ready and zero blocked inputs. These are cold
boot measurements; sustained private-photo/network peaks are recorded separately
in the final acceptance above.

The two CPU tasks share the ESP32 heap. Concurrent Realtime and HTTPS initially
reached a 104-byte minimum free heap. Dynamic TLS buffers and discarding the
verified peer certificate after the handshake improved the observed minimum to
35,680 bytes, while certificate/hostname verification remained enabled. Total
free memory still did not guarantee a sufficiently large allocation: a
23,552-byte largest block could not hold the actual 25,482-byte HTTP snapshot.

The latest implementation reserves two 32 KiB wire slots before radio startup:
one canonical snapshot and one inactive HTTP candidate. It validates and swaps
slots instead of growing/copying a complete response. The mailbox is a dirty
flag; polling and page changes allocate only the exact projected view, typically
about 8.6 KiB for Today or 2.6 KiB for Photos. Cache compression uses at most
8 KiB scratch on the inactive candidate outside the UI mutex. Slot installation,
queue overlay and NVS durability checks keep their bounded mutex scopes. The
reserved-buffer correction passed the recorded native refresh/recovery window,
with minimum free heap 15,480 bytes (15,064 in a later reboot observation). This
is a bounded run, not continuous wire capture or a longer stress result. An earlier
320 KiB private-photo attempt failed decode and produced no downloaded frame;
the following buffer/header corrections preceded the final acceptance above.

Both wire slots now remain allocated during photo work. The sole worker lends
the inactive slot to the PNG decoder's 32 KiB dictionary while household
snapshot/RPC HTTP is idle; the decoder never frees that borrowed memory.
Realtime is parked for private photo work. This follows a native cache miss
that left 111,432 bytes free but only a 31,744-byte largest block, preventing the
freed HTTP slot from being rebuilt before any PNG attempt. Photos and Start
remained responsive with zero blocked inputs. The subsequent header correction
and final private-photo acceptance follow that negative run.

The borrowed-slot image reached photo header fetch, then failed at stage 6 with
HTTP status zero. Source inspection confirmed the current 512-byte photo TX
buffer cannot hold the observed 994-byte Authorization header; the SDK can mark
that incomplete request successful. Both clients now size TX from the actual
token/key lengths with a bounded shared helper. Actual-SDK synthetic tests pin
the old stall and complete headers at 970, 4,096 and 8,192 bytes in both insertion
orders. The final private-photo acceptance passes with that sizing. No SSL
error was proved, and TLS
certificate/hostname verification remains enabled.

`src/homehq_realtime.c` joins the private `homehq:<household UUID>` topic with
the ordinary access token. Join/rejoin and changed hints fetch the authoritative
snapshot. A 60-second periodic refresh remains; while the subscription is down,
the service falls back to three-second polling. TLS verifies the server through
ESP-IDF's certificate bundle using a validated clock. Trusted USB setup and an
app-owned NVS clock checkpoint allow HTTPS to start on networks that block NTP;
SNTP remains enabled, and authenticated snapshot times refresh the checkpoint.

The existing factory NVS partition is only 24 KiB. `homehq_pack.c` compresses
the full bounded snapshot without altering its wire format. An incompressible
snapshot above the 8 KiB cache budget remains usable live and reports cache
full; session/outbox storage takes precedence. NVS write failures reject an edit
or retain a pending queue with visible status. Abrupt power loss and NVS wear
still need physical validation.

The photo decoder streams at most 320 KiB of the same 320×240 private PNGs
accepted by the badges, preserving aspect ratio in a 128×72 card. It retains
only the prior and incoming native-size pixel buffers plus decoder state.
Decoded pixels have a two-slot runtime flash cache in an exact app-owned 40 KiB
tail range, with account/path binding, CRC/readback and a final commit marker.
Firmware deployment still writes only the application at `0x10000`; it leaves
the partition table intact and adds no filesystem. Durable cached identity can
restore a matching frame before Wi-Fi, UTC or token refresh. Logout/account
replacement persists a clearing intent and blocks private cache work until
verified invalidation completes. See the [cache contract](PHOTO-CACHE.md).
The first cache-enabled run recorded misses without a downloaded frame; the
final run above verifies replacement, offline restoration, restart and clearing.

Photo replacement retires the old 18 KiB frame after deleting its LVGL widget
and before requesting the next path. A matching pending download is preserved.
Leaving Photos cancels the worker epoch before destination hydration, while an
allocation failure keeps the old widget/pixels valid until a successful redraw.
Bundled fallback art is labelled SAMPLE ART even for a pending or failed private
path. Host tests exercise these ownership and cancellation boundaries.

Installation backs up the existing MCU before replacing its application.
Retain that private backup for recovery. The cartridge, FPGA configuration,
bootloader, partition table and factory settings are outside this app write.

## Build an isolated MCU image

Use a fresh checkout of the public
[ModRetro MCU source](https://github.com/ModRetro/oss-chromatic-console-mcu) at
`6c94613da72420f6a364e0024681401bd69184ba`. `prepare.py` verifies its required
files and applies the checked-in [platform patch](tools/mcu-baseline.patch)
before copying the Home HQ overlay. The patch supplies the display/startup and
button/FPGA seams previously inherited from the local SAM13 tree; it contains
no camera/bloom application or private inputs. Its exact source and checksums
are in [mcu-baseline.json](tools/mcu-baseline.json), with the upstream
[GPL-3.0 license](tools/mcu-baseline-LICENSE).

The earlier physical acceptance used local SAM13 commit `b05819b`; that custom
commit is not required for this public build. The fresh public-source build also
passes: 1,039,216 bytes, with 9,360 bytes free in the factory app partition. Its
SHA-256 is `1ce73fd7c0d33f286b7877a7fdfccbed3416edcb62b88b62f7fc8f506733e7df`.
That image has build/host acceptance; the physical results above belong to the
previously installed image. Keep the dependency checkout
separate from the Home HQ source. From the Home HQ repository or extracted
starter root, choose an empty workspace path without spaces:

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
  homehq/chromatic/tools/prepare.py --mcu "$CHROMATIC_WORKSPACE/mcu"
bash homehq/chromatic/tools/build.sh "$CHROMATIC_WORKSPACE/mcu" \
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
cmake -S homehq/chromatic/tests -B "$CHROMATIC_WORKSPACE/host-tests" -G Ninja \
  -DMCU_ROOT="$CHROMATIC_WORKSPACE/mcu" \
  -DIDF_ROOT="$CHROMATIC_WORKSPACE/esp-idf"
cmake --build "$CHROMATIC_WORKSPACE/host-tests"
ctest --test-dir "$CHROMATIC_WORKSPACE/host-tests" --output-on-failure
python3 homehq/chromatic/tests/test_photo_decode.py
python3 homehq/chromatic/tests/test_wire.py
python3 homehq/chromatic/tests/test_projection.py
python3 homehq/chromatic/tests/test_physical_probe.py
python3 homehq/chromatic/tests/test_provision.py
HQ_PHOTO_SANITIZE=1 UBSAN_OPTIONS=halt_on_error=1 \
  python3 homehq/chromatic/tests/test_photo_mailbox.py
```

The real LVGL navigation lane writes native PPM screenshots. Service and Realtime
tests mock hardware/network boundaries and exercise actual implementation code.
They establish host behavior, not ESP32 radio, physical buttons, battery life or
power-loss durability.

## Application-only installation and private setup

Power the Chromatic on normally with its cartridge inserted. Identify the actual
ModRetro USB MCU port. When using the documented Deck, keep it awake and online
through Tailscale. Keep one process in charge of serial access.

Transfer the exact size-checked binary and compare SHA-256 on the programming
host. `tools/deploy.py` verifies its version/digest, makes a fresh full MCU backup,
then writes **only `0x10000`**. It requires esptool 4.12.0 and an explicit port:

```sh
python3 homehq/chromatic/tools/deploy.py \
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
python3 homehq/chromatic/tools/provision.py --port SELECTED_MCU_PORT --config PRIVATE_CONFIG_JSON
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
python3 homehq/chromatic/tools/physical_probe.py --port SELECTED_MCU_PORT \
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
