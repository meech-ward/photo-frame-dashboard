"""Bounded installed-bytecode Auth acceptance on the explicitly selected Tufty.

The root serial controller injects HOMEHQ_AUTH_PROBE_OPTIONS privately before
exec(source). This script neither discovers USB nor installs anything. Ordinary
email/password values are transient and never enter records or debug output.
"""
import binascii
import builtins
import gc
import json
import os
import sys
import time
import machine

ROOT = "/system/apps/homehq"
# The host chooses a device explicitly; never discover or infer the target.
TARGET = globals().get("HOMEHQ_PROBE_TARGET")
RUNTIME_MPY = 7942
MODULE_COUNT = 20
_watchdog = None


def feed():
    if _watchdog is not None:
        _watchdog.feed()


def gate():
    uid = binascii.hexlify(machine.unique_id()).decode().lower()
    if not TARGET or uid != TARGET:
        raise RuntimeError("Auth probe refuses this device")
    if "tufty" not in os.uname().machine.lower():
        raise RuntimeError("A Tufty badge is required")
    if sys.implementation._mpy != RUNTIME_MPY or ROOT in sys.modules:
        raise RuntimeError("Auth probe requires matching firmware and a fresh REPL")
    count = 0
    directories = [ROOT]
    while directories:
        directory = directories.pop()
        for entry in os.ilistdir(directory):
            feed()
            path = directory + "/" + entry[0]
            if entry[1] & 0x4000:
                directories.append(path)
            elif path.endswith(".py"):
                raise RuntimeError("Source shadows installed bytecode")
            elif path.endswith(".mpy"):
                with open(path, "rb") as source:
                    header = source.read(4)
                if len(header) != 4 or header[0] != 77 or header[1] != 6 or header[2] >> 2 or header[3] > 31:
                    raise RuntimeError("Installed bytecode ABI mismatch")
                count += 1
    if count != MODULE_COUNT:
        raise RuntimeError("Installed Auth module count mismatch")
    return {"selected_tufty": True, "runtime_mpy": RUNTIME_MPY, "modules": count}


def read_private(path):
    try:
        with open(path) as source:
            return json.load(source)
    except (OSError, ValueError):
        return None


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def durable_session(service, user_id):
    saved = read_private(service.session_path)
    active = service._transport.session
    return (isinstance(saved, dict) and set(saved) == {"v", "refresh_token", "user_id"}
            and saved.get("v") == 1 and saved.get("user_id") == user_id
            and saved.get("refresh_token") == active.get("refresh_token")
            and isinstance(saved.get("refresh_token"), str) and bool(saved["refresh_token"])
            and service._session_pending is None)


def capture(label):
    pixels = memoryview(screen)
    if screen.width != 320 or screen.height != 240 or len(pixels) != 307200:
        raise RuntimeError("Auth framebuffer dimensions differ")
    print("HOMEHQ_RGBA_BEGIN " + json.dumps({"page": label, "width": 320, "height": 240, "format": "RGBA"}))
    for offset in range(0, len(pixels), 3072):
        feed()
        print("HOMEHQ_RGBA_DATA " + binascii.b2a_base64(pixels[offset:offset + 3072]).decode().strip())
    print("HOMEHQ_RGBA_END " + label)


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
    gate_record = gate()
    # Stable boot's armed watchdog survives raw-REPL resets. Feed it while this
    # probe temporarily replaces the normal Badgeware loop and serial capture.
    _watchdog = machine.WDT(timeout=16000)
    feed()
    phase = ["gate"]
    records = []
    def record(name, **values):
        phase[0] = name
        values["phase"] = name
        records.append(values)
        feed()
        print("HOMEHQ_AUTH_PROBE " + json.dumps(values))
    record("gate", **gate_record)
    mode = options.get("mode", "switch")
    if mode not in ("switch", "restore") or options.get("capture", "none") not in ("none", "stream"):
        raise ValueError("Unsupported Auth probe option")
    timeout = min(60000, max(1000, int(options.get("timeout_ms", 45000))))
    expected_user = options.get("expected_user_id")
    expected_home = options.get("expected_home_id")
    expected_person = options.get("expected_person_id")
    if not isinstance(expected_user, str) or not expected_user or not isinstance(expected_home, str) or not expected_home:
        raise ValueError("Auth probe requires expected identity and household")
    if mode == "switch" and (not isinstance(options.get("email"), str) or not options.get("email")
                              or not isinstance(options.get("password"), str) or not options.get("password")):
        raise ValueError("Auth switch requires privately supplied credentials")

    initial = read_private("/state/homehq-session.json")
    initial_user = initial.get("user_id") if isinstance(initial, dict) else None
    if not initial_user or not initial.get("refresh_token"):
        raise RuntimeError("Auth probe requires a saved starting session")
    was_legacy = "access_token" in initial
    initial = None
    import badgeware
    real_run = run
    real_badge = badge
    real_fatal = badgeware.fatal_error
    old_mode, old_clear = badge.mode(), badge.default_clear
    old_path, old_modules, old_cwd = list(sys.path), list(sys.modules), os.getcwd()
    finished = [False]
    min_heap = [gc.mem_free()]

    def frame(product):
        feed()
        began = time.ticks_us()
        product.update()
        display.update()
        badge.poll()
        feed()
        min_heap[0] = min(min_heap[0], gc.mem_free())
        return time.ticks_diff(time.ticks_us(), began)

    def wait_for(product, name, condition, limit=None):
        phase[0] = name
        start, maximum = time.ticks_ms(), 0
        while time.ticks_diff(time.ticks_ms(), start) < (timeout if limit is None else limit):
            maximum = max(maximum, frame(product))
            if condition():
                record(name, ok=True, elapsed_ms=time.ticks_diff(time.ticks_ms(), start), max_frame_us=maximum)
                return
            time.sleep_ms(5)
        record(name, ok=False, elapsed_ms=time.ticks_diff(time.ticks_ms(), start), max_frame_us=maximum)
        raise RuntimeError("Bounded Auth phase timed out")

    def bounded(update):
        product = sys.modules[ROOT]
        if update != product.update:
            raise RuntimeError("Installed Auth entry seam differs")
        service = product._service
        def live_as(user_id, person_id, require_person):
            data = service.snapshot()
            viewer = data.get("viewer") or {}
            home = data.get("home") or {}
            return (service.auth_state == "signed_in" and service.status()["state"] == "live"
                    and service._transport.joined and service._last_refresh != 0
                    and viewer.get("user_id") == user_id and home.get("id") == expected_home
                    and (not require_person or viewer.get("person_id") == person_id)
                    and durable_session(service, user_id))

        wait_for(product, "initial_saved_session_restore", lambda: live_as(
            expected_user if mode == "restore" else initial_user, expected_person, mode == "restore"))
        record("starting_session", legacy_migrated=was_legacy, refresh_only_durable=True, pending=service.status()["pending"])
        if service.status()["pending"]:
            raise RuntimeError("Auth switch cannot discard an existing outbox")
        if mode == "restore" and options.get("sync_item_id"):
            item_id = options["sync_item_id"]
            def row():
                return next((item for item in service._base["shopping"] if item.get("id") == item_id), None)
            wait_for(product, "peer_sync_baseline", lambda: service._request is None and service._transport.can_request)
            item = row()
            if not item or item.get("created_by_user_id") != expected_home or item.get("done") is not False:
                raise RuntimeError("Peer sync requires the prepared owner-created unchecked fixture")
            transport, original_poll, hints = service._transport, service._transport.poll, [0]
            def observed_poll():
                events = original_poll()
                hints[0] += sum(event.get("kind") == "changed" for event in events)
                return events
            transport.poll = observed_poll
            try:
                service._refresh = False
                service._last_refresh = time.ticks_ms()
                record("peer_sync_ready", ok=True)
                # A 25-second observation cannot reach the 60-second fallback;
                # require a changed hint as well as the authoritative row value.
                wait_for(product, "owner_to_member_realtime", lambda: hints[0] > 0 and row() is not None
                         and row().get("done") is True, min(timeout, 25000))
                product._app.page, product._app.detail = 3, None
                product._app.focus["shopping"] = item_id
                product._app._align()
                for desired, label in ((False, "member_native_undo"), (True, "member_native_complete")):
                    command = product._app.press("B")
                    if not command or command.get("id") != item_id or command.get("done") is not desired or not service.command(command):
                        raise RuntimeError("Native fixture Shopping action refused")
                    product._app.replace(service.snapshot())
                    product._dirty = True
                    wait_for(product, label, lambda: not service.status()["pending"] and row() is not None
                             and row().get("done") is desired)
                actor = row().get("completed_by_user_id") == expected_user
                record("cross_account_sync", ok=actor, changed_hints=hints[0], owner_created=True,
                       native_undo=True, native_complete=True, completion_actor_matches=actor)
                if not actor:
                    raise RuntimeError("Native completion actor differs from the signed-in member")
            finally:
                transport.poll = original_poll
        if mode == "switch":
            phase[0] = "local_logout_submit"
            if not service.start_logout():
                raise RuntimeError("Local logout refused")
            wait_for(product, "local_logout", lambda: service.auth_state == "signed_out" and product._login.active())
            private_names = ("homehq-session.json", "homehq-cache.json", "homehq-photo-0.png", "homehq-photo-1.png")
            login_blank = not product._login.email and not product._login.password
            photos_cleared = product._view._photo is None and product._view._photo_path is None
            files_cleared = not any(exists("/state/" + name + suffix) for name in private_names for suffix in ("", ".tmp"))
            cleared = (not service.status()["pending"] and not service._photo_cache
                       and not service.snapshot().get("people") and login_blank and photos_cleared and files_cleared)
            record("signed_out_isolation", ok=cleared, private_files_cleared=files_cleared,
                   decoded_photo_cleared=photos_cleared, login_blank=login_blank)
            if not cleared:
                raise RuntimeError("Signed-out identity cleanup incomplete")
            product._dirty = True
            frame(product)
            if options.get("capture") == "stream":
                capture("auth_signed_out")
            phase[0] = "native_signin_submit"
            login = product._login
            login.email, login.password = options.pop("email"), options.pop("password")
            login.focus = 2
            accepted = login.press("B", service)
            secret_cleared = not login.email and not login.password and login.keyboard is None and service.auth_state == "signing_in"
            record("native_signin_submit", ok=bool(accepted and secret_cleared), credentials_cleared=secret_cleared)
            if not accepted or not secret_cleared:
                raise RuntimeError("Native sign-in did not clear its transient form")
            product._dirty = True
            wait_for(product, "member_signed_in_live", lambda: live_as(expected_user, expected_person, True))
            member_focus = expected_person is None or product._app.focus.get("chores") == expected_person
            record("member_perspective", ok=member_focus, auth_identity_matches=True, household_matches=True, person_matches=True)
            if not member_focus:
                raise RuntimeError("Viewer's Chores card was not selected")
            if options.get("capture") == "stream":
                for page, label in ((2, "auth_member_chores"), (0, "auth_member_today")):
                    product._app.page, product._app.detail = page, None
                    product._app._align()
                    product._dirty = True
                    frame(product)
                    capture(label)
            phase[0] = "force_auth_refresh"
            transport = service._transport
            previous = transport.session["refresh_token"]
            transport.refresh_at = 0
            wait_for(product, "rotated_session_durable", lambda: transport.session.get("refresh_token") != previous
                     and transport.ready and durable_session(service, expected_user))
            previous = None
        service.receive_snapshot(service._base)
        service.close()
        saved = read_private(service.path)
        checkpoint = (isinstance(saved, dict) and saved.get("user_id") == expected_user
                      and not saved.get("pending") and (saved.get("snapshot", {}).get("viewer") or {}).get("user_id") == expected_user
                      and durable_session(service, expected_user))
        saved = None
        record("checkpoint", ok=checkpoint, refresh_only_durable=True, pending=service.status()["pending"])
        if not checkpoint:
            raise RuntimeError("Auth restore checkpoint was not durable")
        record("summary", ok=True, restore_only=mode == "restore", min_heap_free=min_heap[0], physical_buttons=False)
        finished[0] = True

    def fail_fast(*args):
        raise RuntimeError("Installed Auth launch failed")
    failure = False
    try:
        builtins.run, builtins.badge = bounded, QuietButtons(real_badge)
        badgeware.fatal_error = fail_fast
        gc.collect()
        badgeware.launch(ROOT)
        if not finished[0]:
            raise RuntimeError("Installed Auth entry did not run")
    except Exception:
        failure = True
    finally:
        # Clear credentials even after a timeout/canceled phase; root resumes
        # the normal app separately rather than leaving a synthetic run loop.
        options.pop("email", None)
        options.pop("password", None)
        builtins.run, builtins.badge = real_run, real_badge
        badgeware.fatal_error = real_fatal
        badge.default_clear = old_clear
        os.chdir(old_cwd)
        sys.path[:] = old_path
        for name in list(sys.modules):
            if name not in old_modules:
                sys.modules.pop(name, None)
        badge.mode(old_mode)
        gc.collect()
        feed()
    if failure:
        failed_phase = phase[0]
        record("failure", ok=False, failed_phase=failed_phase)
        raise RuntimeError("Installed Auth acceptance failed; inspect safe phase records")


main(globals().pop("HOMEHQ_AUTH_PROBE_OPTIONS", {}))
