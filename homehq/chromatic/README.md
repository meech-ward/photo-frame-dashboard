# Home HQ on the ModRetro Chromatic

This native ESP32/LVGL port uses the same Home HQ fixture, household contract,
ordinary Auth accounts and companion editor as the badges. It adapts the seven
pages to the Chromatic's 160×144 RGB565 overlay. It is an MCU application, built
on Sam's custom SAM13 firmware, not a Game Boy cartridge ROM.

Current validation: host navigation, Auth/outbox, private Realtime and streamed
photo checks pass; the native image fits the original 1 MiB app partition.
**Physical installation and radio/display acceptance are
still pending.** The owner reported the connected Chromatic powered off; the
documented programming Deck was offline and this Mac had no Chromatic USB serial
port at the last check. See the [evidence record](https://github.com/meech-ward/select-badge/blob/main/benchmark/results/reports/2026-10-12-homehq-chromatic.md).

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
transfers whole snapshots, persists a coalesced 32-command desired-value outbox,
and checkpoints rotated refresh tokens before RPC work.

`src/homehq_realtime.c` joins the private `homehq:<household UUID>` topic with
the ordinary access token. Join/rejoin and changed hints fetch the authoritative
snapshot. A 60-second periodic refresh remains; while the subscription is down,
the service falls back to three-second polling. TLS verifies the server through
ESP-IDF's certificate bundle after SNTP sets the clock.

The existing factory NVS partition is only 24 KiB. `homehq_pack.c` compresses
the full bounded snapshot without altering its wire format. An incompressible
snapshot above the 8 KiB cache budget remains usable live and reports cache
full; session/outbox storage takes precedence. NVS write failures reject an edit
or retain a pending queue with visible status. Abrupt power loss and NVS wear
still need physical validation.

The photo decoder streams at most 320 KiB of the same 320×240 private PNGs
accepted by the badges, preserving aspect ratio in a 128×72 card. It retains
only the prior and incoming native-size pixel buffers plus decoder state.
Downloaded photo pixels live in RAM; bundled samples cover restart/offline
fallback. This target has no badge-sized photo filesystem. Native radio/TLS
peak heap and sustained private photo transfer remain hardware gates.

The camera/bloom application is replaced in this build. Its existing source and
binary recovery copies remain available. The cartridge, FPGA configuration,
bootloader, partition table and factory settings are outside this app write.

## Build an isolated MCU image

Read the owner's [programming guide](/Users/supa-sam/Projects/chromatic-programming/mcu/PROGRAMMING.md)
for the exact toolchain, app boundary and recovery route. Start from MCU commit
`b05819b` (documented SAM13 baseline); do not edit the persistent MCU checkout.
Use an isolated worktree and copy its installed LVGL 8.4 managed dependency:

```sh
git -C /Users/supa-sam/Projects/chromatic-programming/mcu worktree add \
  /private/tmp/homehq-mcu -b codex/homehq-mcu b05819b
cp -R /Users/supa-sam/Projects/chromatic-programming/mcu/managed_components \
  /private/tmp/homehq-mcu/managed_components
python3 homehq/chromatic/tools/prepare.py --mcu /private/tmp/homehq-mcu
bash homehq/chromatic/tools/build.sh /private/tmp/homehq-mcu \
  /Users/supa-sam/Projects/chromatic-programming
```

Python needs Pillow for regenerating the shared demo and three sample images.
The build uses exact ESP-IDF v5.3 and existing isolated tools. It must pass the
original 1 MiB app partition gate. `prepare.py` excludes camera/server assets,
uses client-only TLS and app-authored styles, and fixes the LVGL timer's
microseconds/milliseconds mismatch. The DMA draw buffer is allocated once in
internal RAM; this removes 46,080 zero-initialization bytes from the flash image.
ESP32 ROM nano formatting reduces unused formatter code; this app uses standard
floating formats and 32-bit integers.

Generated C assets, build images, snapshots, backup dumps and private provisioning
files are outputs, not canonical sources. No password or access JWT belongs in
the image. The PNG dependency's pin, license and local fix are in
[`src/vendor/pngle/UPSTREAM.md`](src/vendor/pngle/UPSTREAM.md).

## Focused host checks

```sh
cmake -S homehq/chromatic/tests -B /private/tmp/homehq-host -G Ninja \
  -DMCU_ROOT=/private/tmp/homehq-mcu \
  -DIDF_ROOT=/Users/supa-sam/Projects/chromatic-programming/esp-idf
cmake --build /private/tmp/homehq-host
ctest --test-dir /private/tmp/homehq-host --output-on-failure
python3 homehq/chromatic/tests/test_photo_decode.py
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
python3 tools/deploy.py --image mcu_fw.bin --sha256 VERIFIED_DIGEST \
  --port /dev/serial/by-id/usb-ModRetro_Chromatic_-_Player_01_012345678-if02 \
  --python /home/sam/chromatic-programming/tools/bin/python \
  --backup-root /home/sam/chromatic-programming/backups --apply
```

This is not generic `idf.py flash`. A failed/uncertain write is investigated
before retrying. Preserve the fresh private backup and recovery application.
Successful esptool hash verification is an install claim only.

Prepare a private JSON file containing exactly `wifi_ssid`, `wifi_password`,
`url`, `key` (project publishable key), `email` and `password`. Use the existing
household's ordinary member login; do not reuse another device's Auth session.
With the programmer's Python/pyserial, send it using:

```sh
python3 tools/provision.py --port SELECTED_MCU_PORT --config PRIVATE_CONFIG_JSON
```

The helper uses short UART chunks and discards console input echoes. It prints
only whether configuration was queued. Wi-Fi/project configuration persists;
Auth passwords and access tokens remain transient, and only refresh/user data
is saved for the session. Later sign-in is available on the device. `hq status`
prints safe state, pending count and heap metrics. `hq input left|right|up|down|a|b|start|select`
replays navigation through the LVGL task; it does not prove physical button wiring.

After installation, verify cold boot/overlay, every physical control, all pages
and details, fresh login, refresh/restart, companion fanout, checklist retries and
conflicts, Wi-Fi interruption/recovery, private images, logout clearing, minimum
heap, and battery-only operation. Record actual screen captures and server
convergence separately from host checks.
