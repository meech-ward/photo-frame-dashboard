"""Bounded live JPEG acceptance for an explicitly selected installed Tufty.

Uses existing photos and Auth; no cloud writes, account switch or photo fixtures.
The host owns USB selection/installation and injects HOMEHQ_JPEG_PROBE_OPTIONS.
Records contain only measurements, never tokens, paths or household content.
"""
import binascii
import builtins
import gc
import hashlib
import json
import machine
import time
import sys
import badgeware

ROOT = "/system/apps/homehq"
TARGETS = ("6d9430717fc47ddf", "03bfbc20532aa948")


class QuietButtons:
    # Physical keys must not change focus or enqueue writes during serial proof.
    def __init__(self, original):
        self.original = original
    def __getattr__(self, name):
        return getattr(self.original, name)
    @property
    def default_clear(self):
        return self.original.default_clear
    @default_clear.setter
    def default_clear(self, value):
        self.original.default_clear = value
    def pressed(self, *args):
        return False
    def held(self, *args):
        return False


def main(options):
    uid = binascii.hexlify(machine.unique_id()).decode().lower()
    if uid not in TARGETS or options.get("uid") != uid or sys.implementation._mpy != 7942:
        raise RuntimeError("JPEG probe requires the explicitly selected compatible Tufty")
    if ROOT in sys.modules:
        raise RuntimeError("JPEG probe requires a fresh REPL")
    timeout = min(45000, max(1000, int(options.get("timeout_ms", 30000))))
    # Stable boot's watchdog survives raw REPL; the temporary loop must feed it.
    watchdog = machine.WDT(timeout=16000)
    real_run, real_badge, real_fatal = run, badge, badgeware.fatal_error
    old_mode, old_clear = badge.mode(), badge.default_clear
    finished = [False]
    maximum = [0]

    def record(phase, **values):
        watchdog.feed()
        values["phase"] = phase
        print("HOMEHQ_JPEG_PROBE " + json.dumps(values))

    def frame(product):
        watchdog.feed()
        started = time.ticks_us()
        product.update()
        maximum[0] = max(maximum[0], time.ticks_diff(time.ticks_us(), started))
        display.update()
        badge.poll()
        watchdog.feed()

    def until(product, condition):
        started = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), started) < timeout:
            frame(product)
            if condition():
                return time.ticks_diff(time.ticks_ms(), started)
            time.sleep_ms(5)
        raise RuntimeError("Bounded JPEG acceptance timed out")

    def bounded(update):
        product = sys.modules[ROOT]
        if update != product.update:
            raise RuntimeError("Unexpected installed app seam")
        service = product._service
        identity = service._identity
        original_poll = service.poll
        record("installed", selected_tufty=True, runtime_mpy=7942,
               cached_revision=service._base["revision"],
               cached_jpegs=sum(path.endswith(".jpg") for path in service._photo_cache))
        if options.get("offline_cache"):
            # A restored photo must render before networking starts; otherwise
            # a successful HTTP retry could hide a missing flash checkpoint.
            service.poll = lambda now: False
            elapsed = 0
        else:
            try:
                elapsed = until(product, lambda: service.status()["state"] == "live"
                                and service._transport.joined and service._last_refresh != 0)
            except RuntimeError:
                import network
                wlan = network.WLAN(network.STA_IF)
                record("connection", state=service.status()["state"],
                       auth_state=service.auth_state, wifi_connected=wlan.isconnected(),
                       wifi_status=wlan.status())
                raise
        if not identity or service._identity != identity or service.status()["pending"]:
            raise RuntimeError("JPEG acceptance requires the existing identity and empty outbox")
        record("offline_cache" if options.get("offline_cache") else "live",
               elapsed_ms=elapsed, preserved_identity=True,
               revision=service._base["revision"], pending=0)
        rows = [row for row in service.snapshot()["photos"] if row.get("jpeg_path")]
        if len(rows) < 2:
            raise RuntimeError("JPEG acceptance requires two existing uploaded photos")
        transport = service._transport
        original_download = transport.download_photo if transport else None
        downloads = {}

        async def counted(path, local):
            downloads[path] = downloads.get(path, 0) + 1
            return await original_download(path, local)

        if transport:
            transport.download_photo = counted
        try:
            for index, row in enumerate(rows[:2]):
                source = row["jpeg_path"]
                was_cached = source in service._photo_cache
                if options.get("require_cached") and not was_cached:
                    raise RuntimeError("Expected post-restart JPEG cache missing")
                product._app.page = 4
                product._app.detail = None
                product._app.focus["photos"] = row["id"]
                product._app.photo_playing = False
                product._dirty = True
                elapsed = until(product, lambda: service._photo_cache.get(source)
                                and product._view._photo_source == source
                                and product._view._photo_path == service._photo_cache[source]
                                and product._view._photo is not None)
                local = service._photo_cache[source]
                if not local.endswith(".img"):
                    raise RuntimeError("JPEG cache filename differs")
                digest, length = hashlib.sha256(), 0
                with open(local, "rb") as photo:
                    signature = photo.read(2)
                    digest.update(signature)
                    length += 2
                    while True:
                        data = photo.read(4096)
                        if not data:
                            break
                        digest.update(data)
                        length += len(data)
                        watchdog.feed()
                if (signature != b"\xff\xd8" or length > 327680
                        or binascii.hexlify(digest.digest()).decode() != source.rsplit("/", 1)[-1][:-4]
                        or product._view._photo.width != 320 or product._view._photo.height != 240
                        or (not was_cached and downloads.get(source) != 1)):
                    raise RuntimeError("Downloaded JPEG/native decode differs")
                if not service.flush():
                    raise RuntimeError("Photo checkpoint could not be saved")
                # Reconstruct without a transport or poll: cache usability must
                # not depend on a second HTTP request or another decoded image.
                from service import Service
                restored = Service(ROOT, state_root=service.state_root, config=service._config)
                if restored.photo_path(row) != local:
                    raise RuntimeError("Offline photo cache was not restored")
                record("photo", index=index, bytes=length, elapsed_ms=elapsed,
                       downloaded=not was_cached, download_count=downloads.get(source, 0),
                       native_width=320, native_height=240, checkpoint_restored=True)
            finished[0] = True
            record("summary", ok=True, photos=2, max_update_us=maximum[0],
                   free_heap=gc.mem_free(), physical_switches="not exercised")
        finally:
            if transport:
                transport.download_photo = original_download
            service.poll = original_poll

    def fail_fast(*args):
        raise RuntimeError("Installed app launch failed")

    # The normal fatal screen waits for a hardware key indefinitely. Restore
    # these hooks even after a bounded failure so the next app opens normally.
    try:
        builtins.run = bounded
        builtins.badge = QuietButtons(real_badge)
        badgeware.fatal_error = fail_fast
        badgeware.launch(ROOT)
        if not finished[0]:
            raise RuntimeError("Installed entry did not complete JPEG acceptance")
    except Exception as error:
        record("failure", ok=False, error_type=type(error).__name__)
        raise RuntimeError("JPEG acceptance failed; see safe records")
    finally:
        builtins.run = real_run
        builtins.badge = real_badge
        badgeware.fatal_error = real_fatal
        badge.default_clear = old_clear
        badge.mode(old_mode)


main(globals().get("HOMEHQ_JPEG_PROBE_OPTIONS", {}))
