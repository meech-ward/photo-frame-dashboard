"""Bounded acceptance probe for the INSTALLED Home HQ bytecode, not a deploy.

Run through mpremote on the explicitly selected Tufty. Optional settings are
supplied as HOMEHQ_PROBE_OPTIONS in the same interpreter before exec(source).
No credentials, cache contents, event titles or raw exception text are printed.
"""
import binascii
import builtins
import gc
import hashlib
import json
import os
import sys
import time
import machine

ROOT = "/system/apps/homehq"
TARGET = "6d9430717fc47ddf"
OTHER_PICO = "e7e7d70437b93611"
RUNTIME_MPY = 7942
PAGES = ("today", "calendar", "chores", "shopping", "photos", "home", "agents")
CAPTURE = "/state/homehq-probe.rgba"
MODULES = ("model", "demo", "cache", "service", "transport", "auth_client", "login",
           "kb_shell", "identity_keyboard", "kbqwerty_board", "ui", "view",
           "verified_tls", "ws_backoff", "realtime", "realtime.client",
           "realtime.phoenix", "aiohttp", "aiohttp.aiohttp_ws")
_watchdog = None


def feed():
    if _watchdog is not None:
        _watchdog.feed()


def tagged(phase, values):
    values["phase"] = phase
    return values


def gate():
    uid = binascii.hexlify(machine.unique_id()).decode().lower()
    if uid == OTHER_PICO or uid != TARGET:
        raise RuntimeError("Refusing a device other than the selected Tufty")
    if sys.implementation._mpy != RUNTIME_MPY:
        raise RuntimeError("Unexpected firmware bytecode ABI")
    if ROOT in sys.modules:
        raise RuntimeError("Home HQ already imported; use a fresh raw REPL")
    count = 0
    stack = [ROOT]
    while stack:
        directory = stack.pop()
        for entry in os.ilistdir(directory):
            path = directory + "/" + entry[0]
            if entry[1] & 0x4000:
                stack.append(path)
            elif path.endswith(".py"):
                # MicroPython prefers source to bytecode without warning. A
                # successful source launch cannot prove the installed export.
                raise RuntimeError("Source shadows installed Home HQ bytecode")
            elif path.endswith(".mpy"):
                with open(path, "rb") as source:
                    header = source.read(4)
                if (len(header) != 4 or header[0] != 77 or header[1] != 6
                        or header[2] >> 2 or header[3] > 31):
                    raise RuntimeError("Incompatible installed Home HQ bytecode")
                count += 1
    if count != len(MODULES) + 1:
        raise RuntimeError("Installed Home HQ module count differs from the compiled probe contract")
    return {"uid": uid, "runtime_mpy": sys.implementation._mpy, "modules": count}


def capture(page, mode):
    # screen is a view of the physical display buffer. Writing its memoryview
    # avoids retaining another 307,200-byte RGBA allocation beside photo decode.
    pixels = memoryview(screen)
    if screen.width != 320 or screen.height != 240 or len(pixels) != 307200:
        raise RuntimeError("Unexpected physical framebuffer geometry")
    if mode == "file":
        with open(CAPTURE, "wb") as target:
            for start in range(0, len(pixels), 4096):
                feed()
                part = pixels[start:start + 4096]
                if target.write(part) != len(part):
                    raise OSError("Short owned capture write")
        return {"page": page, "path": CAPTURE, "bytes": len(pixels), "format": "RGBA"}
    if mode == "stream":
        # Serial output is outside timed frames. Streaming all seven avoids
        # storing >2 MiB of captures on the badge's 1 MiB state volume.
        print("HOMEHQ_RGBA_BEGIN " + json.dumps({"page": page, "width": 320,
                                                "height": 240, "format": "RGBA"}))
        for start in range(0, len(pixels), 3072):
            feed()
            encoded = binascii.b2a_base64(pixels[start:start + 3072]).decode().strip()
            print("HOMEHQ_RGBA_DATA " + encoded)
        print("HOMEHQ_RGBA_END " + page)
        return {"page": page, "bytes": len(pixels), "format": "RGBA", "streamed": True}
    return None


class QuietButtons:
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
    global _watchdog
    records = [tagged("gate", gate())]
    # The stable boot installs BadgeLink's 16-second hardware watchdog, which
    # remains armed across raw-REPL soft resets. Our bounded run replaces its
    # normal managed loop, so the probe must feed it during frames and capture.
    _watchdog = machine.WDT(timeout=16000)
    feed()
    online = bool(options.get("online", False))
    roundtrip = bool(options.get("roundtrip", False))
    await_change = bool(options.get("await_change", False))
    capture_mode = options.get("capture", "none")
    capture_page = options.get("page", "today")
    if capture_mode not in ("none", "file", "stream") or capture_page not in PAGES:
        raise ValueError("Unsupported probe capture option")
    if (roundtrip or await_change) and not online:
        raise ValueError("Online options require online=True")
    timeout_ms = min(60000, max(1000, int(options.get("timeout_ms", 30000))))
    repeats = min(5, max(1, int(options.get("repeats", 3))))

    # Firmware hoists these names into a special builtins override dictionary;
    # bare lookup works, whereas getattr(builtins, 'run') can miss the original.
    import badgeware
    real_run = run
    real_badge = badge
    entry_mode = badge.mode()
    entry_clear = badge.default_clear
    entry_cwd = os.getcwd()
    entry_path = list(sys.path)
    entry_modules = list(sys.modules)
    real_fatal = badgeware.fatal_error
    minimum_heap = [gc.mem_free()]
    started = [0]
    completed = [False]

    def frame(product):
        feed()
        badge.clear()
        before = time.ticks_us()
        product.update()
        after_draw = time.ticks_us()
        display.update()
        after_present = time.ticks_us()
        badge.poll()
        feed()
        minimum_heap[0] = min(minimum_heap[0], gc.mem_free())
        return (time.ticks_diff(after_draw, before),
                time.ticks_diff(after_present, after_draw))

    def press(product, key, dispatch=False):
        command = product._app.press(key)
        if command:
            if dispatch:
                accepted = product._service.command(command)
                if accepted is False:
                    product._app.reject(command)
                product._app.replace(product._service.snapshot())
            else:
                # The default smoke can inspect a real B-produced desired value
                # without modifying a configured household's shopping list.
                product._app.reject(command)
                product._app.replace(product._service.snapshot())
        product._dirty = True
        return command

    def wait_for(product, condition, limit=None):
        beginning = time.ticks_ms()
        maximum = 0
        while time.ticks_diff(time.ticks_ms(), beginning) < (limit or timeout_ms):
            draw, present = frame(product)
            maximum = max(maximum, draw)
            if condition():
                return {"ok": True, "elapsed_ms": time.ticks_diff(time.ticks_ms(), beginning),
                        "max_update_us": maximum}
            time.sleep_ms(5)
        return {"ok": False, "elapsed_ms": time.ticks_diff(time.ticks_ms(), beginning),
                "max_update_us": maximum}

    def bounded(update):
        product = sys.modules[ROOT]
        if update != product.update:
            raise RuntimeError("Unexpected installed app run seam")
        service = product._service
        expected_cache = options.get("expected_cache_revision")
        if expected_cache is not None and service._base["revision"] < expected_cache:
            raise RuntimeError("Expected durable cache was not restored")
        records.append({"phase": "initial_cache", "revision": service._base["revision"],
                        "expected_revision_restored": expected_cache is None or service._base["revision"] >= expected_cache})
        real_poll = service.poll
        real_photo_path = service.photo_path
        if options.get("private_photo_path"):
            # The baseline page walk must not prefetch an older cached
            # descriptor before the separately timed, disposable HTTPS photo.
            service.photo_path = lambda photo: None
        if not online:
            service.poll = lambda now: False
        try:
            draw, present = frame(product)
            first_ms = time.ticks_diff(time.ticks_us(), started[0]) // 1000
            if (product.debug_snapshot()["page"] != "today" or not product._view.vector
                    or screen.width != 320 or screen.height != 240):
                raise RuntimeError("First useful Today frame missing")
            threshold = getattr(gc, "threshold", None)
            records.append({"phase": "gc_policy", "active_threshold": threshold() if callable(threshold) else None})
            records.append({"phase": "first_paint", "launch_to_present_ms": first_ms,
                            "update_us": draw, "present_us": present,
                            "heap_free": gc.mem_free(), "font": "bundled_outline",
                            "target_1000ms": first_ms <= 1000,
                            "filesystem": "warm after bytecode gate"})
            for name in MODULES:
                feed()
                __import__(name)
            records.append({"phase": "compiled_imports", "ok": True, "modules": len(MODULES) + 1})
            product._app.photo_playing = False
            for page in PAGES:
                if product.debug_snapshot()["page"] != page or product._app.detail is not None:
                    raise RuntimeError("A/C page walk diverged")
                samples = []
                presents = []
                for _ in range(repeats):
                    product._dirty = True
                    draw, present = frame(product)
                    samples.append(draw)
                    presents.append(present)
                records.append({"phase": "page", "page": page, "update_us": samples,
                                "present_us": presents, "heap_free": gc.mem_free(),
                                "target_100ms": max(samples) <= 100000})
                if capture_mode == "stream" or (capture_mode == "file" and page == capture_page):
                    records.append(tagged("capture", capture(page, capture_mode)))
                press(product, "DOWN")
                frame(product)
                press(product, "UP")
                frame(product)
                command = press(product, "B")
                frame(product)
                detail = product._app.detail
                if detail:
                    press(product, "A")
                    frame(product)
                    if product._app.detail is not None:
                        raise RuntimeError("Detail BACK did not return to the page")
                if page == "photos":
                    product._app.photo_playing = False
                records.append({"phase": "buttons", "page": page, "detail": detail,
                                "desired_value_preview": bool(command), "physical": False})
                press(product, "C")
            # A also crosses a domain boundary, not only the detail BACK seam.
            press(product, "A")
            if product.debug_snapshot()["page"] != "agents":
                raise RuntimeError("PREV did not wrap to Agents")
            press(product, "C")
            frame(product)

            if online:
                refreshed = service._last_refresh
                service._refresh = True
                live = wait_for(product, lambda: service.status()["state"] == "live"
                                and service._last_refresh != refreshed)
                records.append(tagged("realtime_snapshot", live))
                if not live["ok"]:
                    raise RuntimeError("Live joined snapshot timed out")
                idle_ms = min(90000, max(0, int(options.get("idle_ms", 0))))
                if idle_ms:
                    realtime = service._transport.realtime
                    response = realtime._response
                    connects, disconnects = realtime.connects, realtime.disconnects
                    heartbeats = realtime.heartbeats_sent
                    began = time.ticks_ms()
                    maximum = 0
                    while time.ticks_diff(time.ticks_ms(), began) < idle_ms:
                        draw, _ = frame(product)
                        maximum = max(maximum, draw)
                        time.sleep_ms(5)
                    stable = (realtime._response is response and service.status()["state"] == "live"
                              and realtime.connects == connects and realtime.disconnects == disconnects
                              and realtime.heartbeats_sent - heartbeats >= 2)
                    gc.collect()
                    records.append({"phase": "quiet_subscription", "ok": stable,
                                    "elapsed_ms": time.ticks_diff(time.ticks_ms(), began),
                                    "heartbeats": realtime.heartbeats_sent - heartbeats,
                                    "new_connections": realtime.connects - connects,
                                    "disconnects": realtime.disconnects - disconnects,
                                    "max_update_us": maximum, "heap_after_gc": gc.mem_free()})
                    if not stable:
                        raise RuntimeError("Quiet subscription did not retain its socket")
                if await_change:
                    if service.status()["pending"]:
                        raise RuntimeError("Existing outbox must drain before Realtime observation")
                    revision = service._base["revision"]
                    service._refresh = False
                    # Observe a companion edit within 30s of this fresh snapshot.
                    # The fallback refresh is 60s, so a new authoritative revision
                    # here exercises the actual Realtime hint -> snapshot path.
                    print("HOMEHQ_PROBE_SIGNAL " + json.dumps({"phase": "await_change_ready"}))
                    pushed = wait_for(product, lambda: service._base["revision"] > revision,
                                      min(timeout_ms, 30000))
                    records.append(tagged("realtime_companion_change", pushed))
                    if not pushed["ok"]:
                        raise RuntimeError("Companion change not observed in Realtime window")
                if roundtrip:
                    if service.status()["pending"]:
                        raise RuntimeError("Existing outbox must drain before roundtrip")
                    for _ in range(3):
                        press(product, "C")
                    item = product._app.selected()
                    if not item:
                        raise RuntimeError("Roundtrip needs a sample shopping item")
                    item_id, original, version = item["id"], bool(item.get("done")), item["version"]
                    def authoritative(desired):
                        return not service.status()["pending"] and any(
                            row["id"] == item_id and bool(row.get("done")) == desired
                            and row["version"] > version for row in service._base["shopping"])
                    press(product, "B", True)
                    changed = wait_for(product, lambda: authoritative(not original))
                    records.append(tagged("rpc_toggle", changed))
                    if not changed["ok"]:
                        raise RuntimeError("Roundtrip toggle unacknowledged; inspect owned outbox")
                    hold_ms = min(15000, max(0, int(options.get("hold_after_toggle_ms", 0))))
                    if hold_ms:
                        print("HOMEHQ_PROBE_SIGNAL " + json.dumps({"phase": "rpc_toggle_ready"}))
                        began = time.ticks_ms()
                        while time.ticks_diff(time.ticks_ms(), began) < hold_ms:
                            frame(product)
                            time.sleep_ms(5)
                    # Stable-id focus must keep this item selected after its done
                    # grouping changes; restoration uses the newly observed version.
                    if product._app.selected()["id"] != item_id:
                        raise RuntimeError("Stable-id focus changed after shopping acknowledgement")
                    press(product, "B", True)
                    restored = wait_for(product, lambda: authoritative(original))
                    records.append(tagged("rpc_restore", restored))
                    if not restored["ok"]:
                        raise RuntimeError("Roundtrip restore unacknowledged; inspect owned outbox")

                photo_path = options.get("private_photo_path")
                if photo_path:
                    # Use only an explicitly prepared disposable owner photo. The
                    # expected digest proves HTTPS bytes, not bundled fallback art.
                    photo = next((row for row in service._base["photos"] if row.get("path") == photo_path), None)
                    if photo is None:
                        raise RuntimeError("Prepared private photo descriptor missing")
                    product._app.page, product._app.detail = 4, None
                    product._app.focus["photos"] = photo["id"]
                    product._app.photo_playing = False
                    product._dirty = True
                    service.photo_path = real_photo_path
                    transport = service._transport
                    real_download = transport.download_photo
                    photo_starts = [0]
                    async def counted_download(path, local_path):
                        if path == photo_path:
                            photo_starts[0] += 1
                        await real_download(path, local_path)
                    transport.download_photo = counted_download
                    def photo_ready():
                        local = service._photo_cache.get(photo_path)
                        return bool(local and product._view._photo_path == local and product._view._photo is not None)
                    downloaded = wait_for(product, photo_ready)
                    if not downloaded["ok"]:
                        raise RuntimeError("Private native photo did not download/decode")
                    local = service._photo_cache[photo_path]
                    digest = hashlib.sha256()
                    with open(local, "rb") as source:
                        while True:
                            part = source.read(4096)
                            if not part:
                                break
                            digest.update(part)
                            feed()
                    same = binascii.hexlify(digest.digest()).decode() == options.get("private_photo_sha256")
                    pixel = (90 * 320 + 160) * 4
                    rgb = binascii.hexlify(memoryview(screen)[pixel:pixel + 3]).decode()
                    good = (same and photo_starts[0] == 1 and os.stat(local)[6] == 327680 and rgb == "2d76ae"
                            and product._view._photo.width == 320 and product._view._photo.height == 240)
                    records.append({"phase": "private_https_photo", "ok": good,
                                    "elapsed_ms": downloaded["elapsed_ms"], "bytes": os.stat(local)[6],
                                    "max_update_us": downloaded["max_update_us"], "download_starts": photo_starts[0],
                                    "digest_verified": same, "native_pixel_verified": rgb == "2d76ae"})
                    if not good:
                        raise RuntimeError("Private native photo bytes/pixel mismatch")
                    before_gc = gc.mem_free()
                    began_gc = time.ticks_us()
                    gc.collect()
                    records.append({"phase": "photo_heap_checkpoint", "before_gc": before_gc,
                                    "after_gc": gc.mem_free(), "collect_us": time.ticks_diff(time.ticks_us(), began_gc)})
                if options.get("radio_recovery"):
                    transport = service._transport
                    refreshed = service._last_refresh
                    # disconnect() can race an immediate automatic rejoin, so
                    # hold this badge's radio off briefly to observe real loss.
                    transport._wlan.active(False)
                    transport._wifi_attempt = time.ticks_ms() + 1500
                    lost = wait_for(product, lambda: not transport._wlan.isconnected()
                                    and service.status()["state"] == "offline", 1500)
                    offline = lost["ok"]
                    recovered = wait_for(product, lambda: transport._wlan.isconnected()
                                         and service.status()["state"] == "live"
                                         and service._last_refresh != refreshed)
                    recovered["offline_visible"] = offline
                    counters = transport.realtime.snapshot()
                    records.append({"phase": "radio_transport_counters",
                                    "wlan_connected": transport._wlan.isconnected(),
                                    "wlan_status": transport._wlan.status(),
                                    "auth_ready": transport.ready, "joined": transport.joined,
                                    "socket_state": counters["socket_state"],
                                    "connects": counters["connects"], "disconnects": counters["disconnects"],
                                    "joins": counters["joins"], "heartbeat_timeouts": counters["heartbeat_timeouts"],
                                    "http_task_done": transport.task is not None and transport.task.done(),
                                    "receiver_done": transport.realtime._receive_task is not None
                                    and transport.realtime._receive_task.done()})
                    records.append(tagged("radio_recovery", recovered))
                    if not recovered["ok"] or not offline:
                        raise RuntimeError("Radio loss/recovery did not reconcile")
                if options.get("auth_refresh"):
                    transport = service._transport
                    previous = transport.session["refresh_token"]
                    transport.refresh_at = 0
                    def session_saved():
                        if previous == transport.session["refresh_token"] or service._session_pending is not None:
                            return False
                        with open(service.session_path) as saved:
                            persisted = json.load(saved)
                        return persisted["refresh_token"] == transport.session["refresh_token"] and transport.ready
                    rotated = wait_for(product, session_saved)
                    records.append(tagged("auth_rotated_and_persisted", rotated))
                    if not rotated["ok"]:
                        raise RuntimeError("Native rotated session was not persisted")
                    if photo_path and photo_starts[0] != 1:
                        raise RuntimeError("Private photo was downloaded more than once")
                    before_gc = gc.mem_free()
                    began_gc = time.ticks_us()
                    gc.collect()
                    records.append({"phase": "auth_heap_checkpoint", "before_gc": before_gc,
                                    "after_gc": gc.mem_free(), "collect_us": time.ticks_diff(time.ticks_us(), began_gc)})

            # Persist the same authoritative snapshot rather than a synthetic
            # record; never fold an existing optimistic outbox into server data.
            if not service.status()["pending"]:
                service.receive_snapshot(service._base)
            service.close()
            feed()
            with open(service.path) as saved:
                checkpoint = json.load(saved)
            persisted = (service._dirty_at is None and service._session_pending is None
                         and checkpoint.get("snapshot", {}).get("revision") == service._base["revision"]
                         and len(checkpoint.get("pending", [])) == service.status()["pending"])
            records.append({"phase": "owned_cache_close", "ok": persisted,
                            "pending": service.status()["pending"]})
            if not persisted:
                raise RuntimeError("Owned Home HQ cache checkpoint did not persist")
            records.append({"phase": "summary", "ok": True, "pages": 7,
                            "min_heap_free": minimum_heap[0],
                            "target_heap_512KiB": minimum_heap[0] >= 524288,
                            "physical_buttons": "not exercised", "online": online})
            completed[0] = True
            feed()
        finally:
            service.poll = real_poll
            service.photo_path = real_photo_path

    def fail_fast(*args):
        # Badgeware's normal fatal screen waits for a physical button forever;
        # a serial acceptance probe needs a bounded, non-secret failure instead.
        raise RuntimeError("Badgeware launch failed")

    failure = None
    try:
        builtins.run = bounded
        builtins.badge = QuietButtons(real_badge)
        badgeware.fatal_error = fail_fast
        gc.collect()
        started[0] = time.ticks_us()
        badgeware.launch(ROOT)
        if not completed[0]:
            raise RuntimeError("Installed entry did not invoke bounded run")
    except Exception as error:
        failure = type(error).__name__
    finally:
        builtins.run = real_run
        builtins.badge = real_badge
        badgeware.fatal_error = real_fatal
        badge.default_clear = entry_clear
        os.chdir(entry_cwd)
        sys.path[:] = entry_path
        for name in list(sys.modules):
            if name not in entry_modules:
                sys.modules.pop(name, None)
        badge.mode(entry_mode)
        gc.collect()
    for record in records:
        feed()
        print("HOMEHQ_PROBE " + json.dumps(record))
    if failure:
        print("HOMEHQ_PROBE " + json.dumps({"phase": "failure", "error_type": failure, "ok": False}))
        raise RuntimeError("Home HQ acceptance failed; see safe probe records")


main(globals().get("HOMEHQ_PROBE_OPTIONS", {}))
