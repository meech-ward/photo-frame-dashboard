"""Home HQ: a native seven-page dashboard with an optional Supabase service."""

import sys
import time
import gc

_gc_threshold = getattr(gc, "threshold", None)
_gc_before = _gc_threshold() if callable(_gc_threshold) else None
if _gc_before is not None:
    # The frame pump creates short-lived asyncio Tasks; a native long run
    # reached 20,128 B uncollected free heap. Collect after 256 KiB allocated
    # rather than wait for exhaustion, retaining any tighter existing policy.
    # This is an app-lifetime setting and must not leak into the next app.
    _gc_threshold(min(_gc_before, 262144) if _gc_before > 0 else 262144)

APP_ROOT = (__name__ if __name__.startswith("/system/apps/")
            else "/system/apps/" + __name__)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

# The canvas must exist before Chrome sizes its physical button labels. This
# text-and-photo app uses 320x240; games retain their own LORES entry seams.
badge.mode(HIRES | VSYNC)
screen.pen = color.rgb(242, 238, 230)
screen.clear()
display.update()

import ui
from model import HomeHQ, PAGES
from view import HomeView
from login import SignIn, SignInView, SAFE_ERRORS

try:
    from service import create_service
except ImportError:
    # A standalone app install is useful before its optional networking files
    # arrive. Missing credentials are handled by the service's own demo path.
    from demo import DemoService
    create_service = DemoService

_service = create_service(APP_ROOT)
_app = HomeHQ(_service.snapshot(), getattr(_service, "member_id", None))
_app.status = _service.status()
_view = HomeView(APP_ROOT)
_login = SignIn()
_login.synchronize(_app.status, _service.snapshot())
_login_view = SignInView(_view)
_axis = ui.Axis(BUTTON_UP, BUTTON_DOWN)
_last_tick = time.ticks_ms()
_last_status = (_app.status.get("state"), _app.status.get("pending", 0),
                _app.status.get("notice"), _app.status.get("error"),
                _app.status.get("auth_state"), _app.status.get("auth_error"))
_dirty = True
_first_frame = True
_notice_deadline = None
_default_clear = badge.default_clear

# Badgeware clears after every present by default. A dashboard owns its opaque
# frame and retains it between changes; otherwise an idle update would erase
# the last useful screen, and it would have to rerasterize text every frame.
badge.default_clear = None


def debug_snapshot():
    state = _app.debug()
    if _login.active():
        state["login"] = _login.debug()
    return state


def _replace_snapshot(snapshot):
    global _app
    before = (_app.data.get("viewer") or {}).get("user_id")
    after = (snapshot.get("viewer") or {}).get("user_id")
    if before != after:
        # A fresh identity must never inherit the previous account's open
        # logout dialog, checkbox optimism, or focus. Same-user refreshes keep
        # stable row selection through the ordinary model replacement path.
        _app = HomeHQ(snapshot, getattr(_service, "member_id", None))
        _view.clear_private_photo()
        _axis.suppress()
    else:
        _app.replace(snapshot)


def on_exit():
    try:
        badge.default_clear = _default_clear
        _login.clear()
        _view.clear_private_photo()
        close = getattr(_service, "close", None)
        if close:
            close()
    finally:
        if _gc_before is not None:
            _gc_threshold(_gc_before)


def update():
    global _last_tick, _last_status, _dirty, _first_frame, _notice_deadline
    now = time.ticks_ms()
    elapsed = max(0, time.ticks_diff(now, _last_tick))
    _last_tick = now
    _dirty = (_login.tick(elapsed) if _login.active() else _app.tick(elapsed)) or _dirty

    for button, key in ((BUTTON_A, "A"), (BUTTON_B, "B"), (BUTTON_C, "C")):
        if badge.pressed(button):
            if _login.active():
                before = _login.editing
                _dirty = _login.press(key, _service) or _dirty
                if before != _login.editing:
                    _axis.suppress()
                break
            before = (_app.page, _app.detail)
            command = _app.press(key)
            if command:
                # command() queues a desired value. The service owns durable
                # storage and bounded network work; input never opens a socket.
                if command.get("kind") == "logout":
                    accepted = _service.start_logout()
                    if accepted is False:
                        error = _service.status().get("auth_error")
                        _app.notice = error if error in SAFE_ERRORS else "Connect to save changes first."
                else:
                    accepted = _service.command(command)
                if accepted is False and command.get("kind") != "logout":
                    # A full durable queue did not accept this action. The badge
                    # must not retain a checkmark which the service cannot save.
                    _app.reject(command)
                _replace_snapshot(_service.snapshot())
                _notice_deadline = time.ticks_add(now, 1800)
            if before != (_app.page, _app.detail):
                _axis.suppress()
            _dirty = True
            break
    delta = _axis.delta(now)
    if delta:
        key = "UP" if delta < 0 else "DOWN"
        if _login.active():
            _login.press(key, _service)
        else:
            _app.press(key)
        _dirty = True

    if _notice_deadline is not None and time.ticks_diff(now, _notice_deadline) >= 0:
        _notice_deadline = None
        _app.notice = ""
        _dirty = True

    # Paint a complete useful offline frame before the optional service gets
    # its first chance to connect. A connection cannot hold first paint hostage.
    if not _first_frame and _service.poll(now):
        _replace_snapshot(_service.snapshot())
        _dirty = True
    _app.status = _service.status()
    _dirty = _login.synchronize(_app.status, _service.snapshot()) or _dirty
    status = (_app.status.get("state"), _app.status.get("pending", 0),
              _app.status.get("notice"), _app.status.get("error"),
              _app.status.get("auth_state"), _app.status.get("auth_error"))
    if status != _last_status:
        notice = _app.status.get("notice")
        if notice and notice != _last_status[2]:
            # A server conflict is a visible correction, not a successful local
            # checkmark. Show the authoritative outcome when it arrives.
            _app.notice = notice
            _notice_deadline = time.ticks_add(now, 2400)
        _last_status = status
        _dirty = True

    if _dirty:
        if _login.active():
            _login_view.draw(_login)
        else:
            path = None
            if PAGES[_app.page] == "photos" and _app.detail is None and _app.selected():
                path = _service.photo_path(_app.selected())
            _view.draw(_app, path)
        _dirty = False
    _first_frame = False


run(update)
