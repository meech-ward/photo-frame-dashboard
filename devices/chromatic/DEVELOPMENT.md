# Chromatic implementation and measurements

Build and install instructions are in [README.md](README.md). This record explains
the memory, networking and flash constraints behind the implementation.

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
full framebuffer, saving 40,960 bytes of RAM. A development cold boot measured 94,868 bytes free, a 90,112-byte largest block and a 92,572-byte
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
