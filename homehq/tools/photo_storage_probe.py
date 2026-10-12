"""USB-fed, offline storage/decoder proof for the explicitly selected Tufty.

Exec from a fresh raw REPL after installing the current compiled Home HQ export.
No real HTTP, credentials, cache edits, Wi-Fi workarounds or file contents output.
"""
import asyncio
import binascii
import builtins
import errno
import gc
import hashlib
import json
import machine
import os
import struct
import sys
import time

ROOT = "/system/apps/homehq"
STATE = "/state"
TARGET = "6d9430717fc47ddf"
OTHER_PICO = "e7e7d70437b93611"
RUNTIME_MPY = 7942
CAP = 327680
OTHER_STATE_MIN = 103 * 1024
RGB = b"\x2d\x76\xae"
SMALL_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAUAAAADwCAIAAAD+Tyo8AAACD0lEQVR42u3TQQkAAAgEwStkPWOZ0Q7+hIFJsLCpHuCpSAAGBgwMGBgMDBgYMDBgYDAwYGDAwGBgwMCAgQEDg4EBAwMGBgwMBgYMDBgYDAwYGDAwYGAwMGBgwMCAgcHAgIEBA4OBAQMDBgYMDAYGDAwYGAysAhgYMDBgYDAwYGDAwICBwcCAgQEDg4EBAwMGBgwMBgYMDBgYMDAYGDAwYGAwMGBgwMCAgcHAgIEBAwMGBgMDBgYMDAYGDAwYGDAwGBgwMGBgMDBgYMDAgIHBwICBAQMDBgYDAwYGDAwGBgwMGBgwMBgYMDBgYMDAYGDAwICBwcCAgQEDAwYGAwMGBgwMGBgMDBgYMDAYGDAwYGDAwGBgwMCAgcHAgIEBAwMGBgMDBgYMDBgYDAwYGDAwGBgwMGBgwMBgYMDAgIEBA4OBAQMDBgYDAwYGDAwYGAwMGBgwMBhYBTAwYGDAwGBgwMCAgQEDg4EBAwMGBgMDBgYMDBgYDAwYGDAwYGAwMGBgwMBgYMDAgIEBA4OBAQMDBgYMDAYGDAwYGAwMGBgwMGBgMDBgYMDAYGDAwICBAQODgQEDAwYGDAwGBgwMGBgMDBgYMDBgYDAwYGDAwICBwcCAgQEDg4EBAwMGBgwMBgYMDBgYMDAYGDAwYGAwMGBgwMCAgcHAgIEBA4OBAQMDBgYMDAYGDAwYGDAwGBgwMHC3JqMDJr5tvNMAAAAASUVORK5CYII="
)
_watchdog = None


def feed():
    if _watchdog is not None:
        _watchdog.feed()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def free_bytes():
    values = os.statvfs(STATE)
    return values[1] * values[3]


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError as error:
        if error.args[0] != errno.ENOENT:
            raise
        return False


def digest_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            part = source.read(4096)
            if not part:
                break
            digest.update(part)
            feed()
    return digest.digest()


def state_hashes(excluded):
    # Hashes remain private in RAM, including Auth/Wi-Fi files. The only public
    # integrity result is equality and file/byte counts, never credential hashes.
    result = {}
    stack = [STATE]
    while stack:
        directory = stack.pop()
        for entry in os.ilistdir(directory):
            path = directory + "/" + entry[0]
            if path in excluded:
                continue
            if entry[1] & 0x4000:
                stack.append(path)
            else:
                result[path] = (os.stat(path)[6], digest_file(path))
            feed()
    return result


def gate():
    uid = binascii.hexlify(machine.unique_id()).decode().lower()
    require(uid == TARGET and uid != OTHER_PICO, "Refusing another device")
    require(sys.implementation._mpy == RUNTIME_MPY, "Unexpected bytecode ABI")
    require("transport" not in sys.modules and "view" not in sys.modules,
            "Use a fresh raw REPL")
    for name in ("transport", "view", "model"):
        require(not exists(ROOT + "/" + name + ".py"), "Source shadows installed bytecode")
        with open(ROOT + "/" + name + ".mpy", "rb") as source:
            header = source.read(4)
        require(len(header) == 4 and header[0] == 77 and header[1] == 6
                and not header[2] >> 2 and header[3] <= 31, "Incompatible installed bytecode")
    return {"uid": uid, "runtime_mpy": sys.implementation._mpy}


def maximum_photo():
    # USB carries only a 584-byte compressed RGB PNG. Its legal tEXt padding is
    # constructed in RAM: an on-flash fixture would falsely add a third photo.
    base = binascii.a2b_base64(SMALL_PNG)
    prefix = base[:-12]
    body = bytearray(CAP)
    body[:len(prefix)] = prefix
    offset = len(prefix)
    length = CAP - len(base) - 12
    body[offset:offset + 4] = struct.pack(">I", length)
    body[offset + 4:offset + 8] = b"tEXt"
    start = offset + 8
    body[start:start + 8] = b"Comment\0"
    end = start + length
    block = b"x" * 4096
    for index in range(start + 8, end, 4096):
        count = min(4096, end - index)
        body[index:index + count] = memoryview(block)[:count]
        feed()
    body[end:end + 4] = struct.pack(">I", binascii.crc32(memoryview(body)[offset + 4:end]) & 0xffffffff)
    body[-12:] = base[-12:]
    return body, offset, end


def variant(body, offset, end, value):
    body[end - 1] = value
    body[end:end + 4] = struct.pack(">I", binascii.crc32(memoryview(body)[offset + 4:end]) & 0xffffffff)
    feed()


class FakeHTTP:
    def __init__(self, body):
        self.body = body
        self.status = 200
        self.requests = 0

    async def request(self, path, headers, method, max_bytes):
        require(path.startswith("/storage/v1/object/authenticated/homehq-photos/probe/"), "Unexpected offline HTTP path")
        require(method == "GET" and max_bytes == CAP, "Unexpected photo budget")
        self.requests += 1
        feed()
        await asyncio.sleep(0)
        return self.status, bytes(self.body)


class FilesystemMonitor:
    def __init__(self, real_os, real_open, slots, records):
        self.real_os = real_os
        self.real_open = real_open
        self.slots = slots
        self.records = records
        self.peak_photo_bytes = 0
        self.minimum_free = free_bytes()
        self.minimum_heap = gc.mem_free()
        self.fail_after = None

    def sample(self):
        total = 0
        for slot in self.slots:
            for path in (slot, slot + ".tmp"):
                if exists(path):
                    total += self.real_os.stat(path)[6]
        self.peak_photo_bytes = max(self.peak_photo_bytes, total)
        self.minimum_free = min(self.minimum_free, free_bytes())
        self.minimum_heap = min(self.minimum_heap, gc.mem_free())
        require(total <= 2 * CAP, "Photo storage exceeded two capped slots")
        feed()

    def remove(self, path):
        require(path in self.slots or path in [slot + ".tmp" for slot in self.slots], "Unowned deletion attempted")
        self.real_os.remove(path)
        self.sample()

    def rename(self, old, new):
        require(new in self.slots and old == new + ".tmp", "Unowned rename attempted")
        self.real_os.rename(old, new)
        self.sample()

    def open(self, path, mode):
        require(path in [slot + ".tmp" for slot in self.slots] and mode == "wb", "Unowned write attempted")
        handle = self.real_open(path, mode)
        monitor = self
        file_bytes = [0]

        class Target:
            def __enter__(self):
                return self

            def __exit__(self, kind, value, traceback):
                handle.close()
                monitor.sample()
                return False

            def write(self, body):
                # Instrumented writes use the actual MicroPython filesystem.
                # 4 KiB chunks allow watchdog feeding and peak/headroom samples;
                # timings include instrumentation and are not a product benchmark.
                # The failure budget spans every write call, including the
                # product's yielded chunks; it describes one partial file.
                limit = len(body) if monitor.fail_after is None else min(
                    len(body), max(0, monitor.fail_after - file_bytes[0]))
                written = 0
                while written < limit:
                    count = min(4096, limit - written)
                    feed()
                    actual = handle.write(memoryview(body)[written:written + count])
                    if actual is None:
                        raise OSError("filesystem did not return a write count")
                    written += actual
                    file_bytes[0] += actual
                    monitor.sample()
                    if actual != count:
                        break
                return written

        return Target()


def offline_transport(module, http):
    # Bind the installed product methods without constructing its Auth/socket
    # runtime. This tests real eviction/write/retry code with no network access.
    class ProbeTransport:
        download_photo = module.SupabaseTransport.download_photo
        contain = module.SupabaseTransport.contain
        photo = module.SupabaseTransport.photo

    result = ProbeTransport()
    result.http = http
    result.key = "offline-probe"
    result.session = {"user_id": "probe", "access_token": "offline-probe"}
    result._photo_active = None
    result._photos = []
    result.events = []
    result.ready = True
    return result


async def downloads(module, monitor, slots, body, offset, end, records):
    http = FakeHTTP(body)
    transport = offline_transport(module, http)
    digests = {}
    for index, slot in enumerate((slots[0], slots[1], slots[0])):
        variant(body, offset, end, 65 + index)
        wanted = hashlib.sha256(body).digest()
        before = time.ticks_ms()
        await transport.download_photo("probe/{}.png".format(index), slot)
        require(os.stat(slot)[6] == CAP and digest_file(slot) == wanted, "Photo bytes differ after write")
        require(not exists(slot + ".tmp") and transport.events[-1]["kind"] == "photo", "Photo was not published atomically")
        digests[slot] = wanted
        records.append({"phase": "download", "index": index + 1, "bytes": CAP,
                        "elapsed_ms": time.ticks_diff(time.ticks_ms(), before),
                        "free_bytes": free_bytes(), "heap_free": gc.mem_free()})
    # A rejected response must leave the destination intact, before any unlink.
    http.status = 403
    rejected = False
    try:
        await transport.download_photo("probe/rejected.png", slots[0])
    except ValueError:
        rejected = True
    require(rejected and digest_file(slots[0]) == digests[slots[0]], "Rejected HTTP changed old slot")
    records.append({"phase": "rejected_response", "old_slot_preserved": True})
    http.status = 200
    variant(body, offset, end, 68)
    monitor.fail_after = 32768
    transport._photo_active = "probe/retry.png"
    await transport.contain(transport.download_photo("probe/retry.png", slots[0]))
    require(not exists(slots[0]) and not exists(slots[0] + ".tmp"), "Partial write survived cleanup")
    require(digest_file(slots[1]) == digests[slots[1]], "Failure changed other slot")
    require(transport._photo_active is None and transport.events[-1]["kind"] == "error", "Failure blocks the next retry")
    records.append({"phase": "partial_write", "real_bytes_written": 32768,
                    "temporary_removed": True, "other_slot_preserved": True})
    monitor.fail_after = None
    transport.photo("probe/retry.png", slots[0])
    require(len(transport._photos) == 1, "Same photo did not requeue")
    path, slot = transport._photos.pop()
    await transport.download_photo(path, slot)
    require(os.stat(slot)[6] == CAP and digest_file(slot) == hashlib.sha256(body).digest(), "Full retry did not save")
    require(not exists(slot + ".tmp"), "Retry retained temporary file")
    records.append({"phase": "retry", "bytes": CAP, "ok": True})


def draw_photo(slot):
    from model import HomeHQ
    from view import HomeView
    app = HomeHQ({"schema_version": 1, "revision": 1,
                  "photos": [{"id": "probe", "caption": "Storage probe", "place": "USB-fed offline fixture"}]})
    app.page = 4
    app._align()
    app.photo_playing = False
    view = HomeView(ROOT)
    badge.mode(HIRES | VSYNC)
    feed()
    before = time.ticks_ms()
    view.draw(app, slot)
    require(view._photo is not None and view._photo.width == 320 and view._photo.height == 240,
            "Native PNG decode fell back")
    pixels = memoryview(screen)
    position = (90 * 320 + 160) * 4
    require(bytes(pixels[position:position + 3]) == RGB, "Native photo pixel differs")
    display.update()
    feed()
    record = {"phase": "native_photo", "decoded": True, "drawn": True,
              "width": 320, "height": 240, "pixel_verified": True,
              "decode_draw_present_ms": time.ticks_diff(time.ticks_ms(), before),
              "heap_free": gc.mem_free()}
    view._photo = None
    gc.collect()
    return record


def main():
    global _watchdog
    records = []
    stage = "gate"
    failure = None
    owned = []
    baseline = None
    entry_path = list(sys.path)
    entry_modules = list(sys.modules)
    entry_mode = None
    module = None
    original_os = original_open = None
    try:
        records.append(dict(gate(), phase="gate"))
        _watchdog = machine.WDT(timeout=16000)
        feed()
        slots = (STATE + "/homehq-photo-0.png", STATE + "/homehq-photo-1.png")
        reserve = STATE + "/homehq-photo-probe-reserve.bin"
        candidates = list(slots) + [slot + ".tmp" for slot in slots] + [reserve]
        require(not any(exists(path) for path in candidates), "Existing photo slots or probe file; refusing overwrite")
        baseline = state_hashes(candidates)
        other_bytes = sum(row[0] for row in baseline.values())
        needed = max(0, OTHER_STATE_MIN - other_bytes)
        require(free_bytes() >= 2 * CAP + needed + 32768, "Insufficient starting flash headroom")
        # Ownership starts only after every destination has been checked absent.
        # Any failure afterward cleans these paths and no existing app state.
        owned = candidates
        if needed:
            with open(reserve, "wb") as target:
                block = b"s" * 4096
                for index in range(0, needed, 4096):
                    count = min(4096, needed - index)
                    require(target.write(memoryview(block)[:count]) == count, "Reserve write incomplete")
                    feed()
        records.append({"phase": "state_budget", "volume_bytes": os.statvfs(STATE)[0] * os.statvfs(STATE)[2],
                        "other_state_bytes": other_bytes, "reserve_bytes": needed,
                        "other_and_reserve_bytes": other_bytes + needed, "free_bytes": free_bytes()})
        stage = "fixture"
        body, offset, end = maximum_photo()
        sys.path.insert(0, ROOT)
        import transport
        module = transport
        require(module.MAX_PHOTO == CAP and module.valid_photo(body), "Installed photo budget mismatch")
        original_os = module.os
        original_open = getattr(module, "open", None)
        monitor = FilesystemMonitor(os, open, slots, records)
        module.os = monitor
        module.open = monitor.open
        stage = "downloads"
        asyncio.run(downloads(module, monitor, slots, body, offset, end, records))
        module.os = original_os
        if original_open is None:
            del module.open
        else:
            module.open = original_open
        original_os = None
        records.append({"phase": "flash_peak", "peak_photo_bytes": monitor.peak_photo_bytes,
                        "maximum_photo_bytes": 2 * CAP, "minimum_free_bytes": monitor.minimum_free,
                        "minimum_heap_free": monitor.minimum_heap})
        require(monitor.peak_photo_bytes == 2 * CAP and monitor.minimum_free > 0, "Flash budget not proven")
        stage = "decoder"
        body = None
        gc.collect()
        entry_mode = badge.mode()
        records.append(draw_photo(slots[0]))
        stage = "integrity"
        require(state_hashes(candidates) == baseline, "Existing state hashes changed")
        records.append({"phase": "integrity", "existing_files": len(baseline), "unchanged": True})
    except Exception as error:
        failure = {"phase": "failure", "stage": stage, "error_type": type(error).__name__, "ok": False}
    finally:
        if module is not None and original_os is not None:
            module.os = original_os
            if original_open is None:
                del module.open
            else:
                module.open = original_open
        for path in owned:
            try:
                if exists(path):
                    os.remove(path)
            except Exception:
                failure = {"phase": "failure", "stage": "cleanup", "error_type": "OwnedFileCleanup", "ok": False}
            feed()
        if baseline is not None and owned:
            try:
                require(state_hashes(owned) == baseline, "Existing state changed during cleanup")
                require(not any(exists(path) for path in owned), "Owned test file remains")
                records.append({"phase": "cleanup", "owned_files_removed": True, "existing_state_unchanged": True})
            except Exception as error:
                failure = {"phase": "failure", "stage": "cleanup_integrity", "error_type": type(error).__name__, "ok": False}
        if entry_mode is not None:
            badge.mode(entry_mode)
        sys.path[:] = entry_path
        for name in list(sys.modules):
            if name not in entry_modules:
                sys.modules.pop(name, None)
        gc.collect()
    for record in records:
        feed()
        print("HOMEHQ_PHOTO_PROBE " + json.dumps(record))
    if failure:
        print("HOMEHQ_PHOTO_PROBE " + json.dumps(failure))
        raise RuntimeError("Offline photo storage probe failed; see safe records")
    print("HOMEHQ_PHOTO_PROBE " + json.dumps({"phase": "summary", "ok": True,
          "network": "simulated HTTP; no HTTPS claim", "successful_capped_downloads": 4,
          "credential_and_other_state_hashes_unchanged": True}))


if globals().get("HOMEHQ_PHOTO_PROBE_RUN", True):
    main()
