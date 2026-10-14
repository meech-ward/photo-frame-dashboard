"""Readable application data flow; transport and pixels have separate owners.

1. Show cached data. 2. Join Realtime and refresh. 3. Coalesce change hints.
4. Send absolute desired values. 5. Overlay pending writes on refreshed data.
"""
import time
import os
import errno
from cache import read, write, copy, valid_snapshot, valid_pending, empty_snapshot, MAX_PENDING
from auth_client import session_record

SESSION_STORAGE_ERROR = "Session not saved. Free storage."

try:
    ticks_diff = time.ticks_diff
except AttributeError:
    def ticks_diff(later, earlier):
        return later - earlier


class Service:
    def __init__(self, app_root, transport=None, state_root="/state", config=None):
        self.app_root = app_root
        self.state_root = state_root
        self.path = state_root + "/homehq-cache.json"
        self.session_path = state_root + "/homehq-session.json"
        self._config = config if config is not None else read(state_root + "/homehq-config.json")
        session = read(self.session_path) or getattr(transport, "session", None)
        record = session_record(session)
        self._identity = record["user_id"] if record else None
        self.auth_state = "demo" if not self._config else ("signed_in" if record else "signed_out")
        self.auth_error = None
        self._auth_intent = None
        from demo import snapshot
        self._base = snapshot() if not self._config else empty_snapshot()
        self._queue = []
        saved = read(self.path, {})
        if (isinstance(saved, dict) and valid_snapshot(saved.get("snapshot"))
                and (not self._config or (self._identity and saved.get("user_id") == self._identity))):
            self._base = saved["snapshot"]
            pending = saved.get("pending")
            if isinstance(pending, list):
                # Cache format and an interrupted/manual file edit can damage
                # queue metadata independently of the useful offline snapshot.
                self._queue = [c for c in pending if valid_pending(c)][:MAX_PENDING]
        self.member_id = self._config.get("member_id") if isinstance(self._config, dict) else None
        self._state = "demo" if not self._config else ("connecting" if record else "setup")
        self._transport = transport
        self._data = copy(self._base)
        self._overlay()
        self._refresh = bool(self._config)
        self._force_snapshot = False
        self._request = None
        self._dirty_at = None
        self._now = 0
        self._retry_at = 0
        self._last_refresh = 0
        self._storage_retry_at = 0
        self._session_pending = record if record and isinstance(session, dict) and any(
            key not in ("v", "refresh_token", "user_id") for key in session) else None
        self._session_retry_at = 0
        self._sequence = max([c.get("sequence", 0) for c in self._queue] or [0])
        photos = saved.get("photos") if isinstance(saved, dict) and (not self._config or saved.get("user_id") == self._identity) else None
        slots = tuple(state_root + "/homehq-photo-" + str(slot) + extension
                      for slot in (0, 1) for extension in (".png", ".img"))
        # These two owned slots are the whole photo cache. Reject corrupt JSON
        # values before open() can raise a TypeError inside the Photos screen.
        self._photo_cache = {key: value for key, value in photos.items()
                             if isinstance(key, str) and isinstance(value, str) and value in slots} if isinstance(photos, dict) else {}
        self._photo_slot = 0
        self.last_error = None
        self.notice = None

    def snapshot(self):
        return self._data

    def status(self):
        return {"state": self._state, "pending": len(self._queue),
                "error": SESSION_STORAGE_ERROR if self._session_pending else self.last_error,
                "notice": SESSION_STORAGE_ERROR if self._session_pending else self.notice,
                "auth_state": self.auth_state, "auth_error": self.auth_error}

    def _forget_identity(self):
        self._queue = []
        self._base = empty_snapshot()
        self._data = copy(self._base)
        self._photo_cache = {}
        self.member_id = None
        self._identity = None
        self._request = self._session_pending = self._dirty_at = None
        self._refresh = self._force_snapshot = True
        # Exact app-owned files only. Shared Wi-Fi/project configuration and
        # other badge apps' state survive an account switch.
        cleared = True
        for name in ("homehq-cache.json", "homehq-session.json", "homehq-photo-0.png", "homehq-photo-1.png", "homehq-photo-0.img", "homehq-photo-1.img"):
            for suffix in ("", ".tmp"):
                try:
                    os.remove(self.state_root + "/" + name + suffix)
                except OSError as error:
                    if error.args[0] != errno.ENOENT:
                        cleared = False
        return cleared

    def start_login(self, email, password):
        if not self._config or self.auth_state not in ("signed_out", "error") or not email or not password:
            return False
        if not self._forget_identity():
            self.auth_state, self.auth_error = "error", "Session not cleared. Free storage."
            return False
        self.auth_state, self.auth_error = "signing_in", None
        self._auth_intent = ("login", email, password)
        return True

    def start_logout(self):
        if self.auth_state != "signed_in":
            return False
        if self._queue:
            self.notice = "Connect to save changes first."
            return False
        self._forget_identity()
        self.auth_state, self.auth_error = "signing_out", None
        self._auth_intent = ("logout",)
        return True

    def _save_session(self):
        if self._session_pending is None:
            return True
        try:
            write(self.session_path, self._session_pending)
        except (OSError, ValueError):
            # Refresh tokens rotate. Keep the new value in RAM and stop further
            # RPC dispatch until it is durable, rather than reset onto the old
            # token after a full/read-only FAT write raises inside update().
            self.last_error = SESSION_STORAGE_ERROR
            self.notice = SESSION_STORAGE_ERROR
            self.auth_error = SESSION_STORAGE_ERROR
            self._session_retry_at = self._now + 3000
            return False
        self._session_pending = None
        self._session_retry_at = 0
        if self.last_error == SESSION_STORAGE_ERROR:
            self.last_error = None
        if self.notice == SESSION_STORAGE_ERROR:
            self.notice = "Session saved"
        if self.auth_error == SESSION_STORAGE_ERROR:
            self.auth_error = None
        return True

    def _overlay(self):
        self._data = copy(self._base)
        for command in self._queue:
            self._apply(self._data, command)

    @staticmethod
    def _rows(data, kind):
        return data.get({"chore": "chores", "shopping": "shopping", "device": "devices"}.get(kind, ""), [])

    @classmethod
    def _apply(cls, data, command):
        for row in cls._rows(data, command["kind"]):
            if row.get("id") == command["id"]:
                if command["kind"] == "device":
                    row.update(command["state"])
                else:
                    row["done"] = command["done"]
                    if command.get("done_by"):
                        row["done_by"] = command["done_by"]
                return

    def command(self, command):
        if self._config and self.auth_state != "signed_in":
            self.notice = "Sign in to your home."
            return False
        if command.get("kind") not in ("chore", "shopping", "device") or not command.get("id"):
            raise ValueError("unknown Home HQ action")
        if command["kind"] != "device" and not isinstance(command.get("done"), bool):
            raise ValueError("checklist actions require a desired boolean")
        self._sequence += 1
        queued = copy(command)
        queued["sequence"] = self._sequence
        for index, old in enumerate(self._queue):
            if (old["kind"], old["id"]) == (queued["kind"], queued["id"]):
                # Keep the version first observed, even after several offline
                # presses. No server acknowledgement has advanced that row yet.
                queued["version"] = old["version"]
                self._queue[index] = queued
                break
        else:
            if len(self._queue) >= MAX_PENDING:
                self.notice = "Queue full. Connect to save."
                return False
            self._queue.append(queued)
        self._overlay()
        self._dirty_at = self._now if self._dirty_at is None else self._dirty_at
        if not self._config:
            # Demo writes are real local state, with no pretend cloud success.
            self._apply(self._base, queued)
            self._queue = []
            self._overlay()
        return True

    def receive_snapshot(self, snapshot):
        if not valid_snapshot(snapshot):
            raise ValueError("unsupported Home HQ data")
        self._base = copy(snapshot)
        viewer = snapshot.get("viewer")
        self.member_id = viewer.get("person_id") if isinstance(viewer, dict) else self.member_id
        home_id = snapshot["home"].get("id")
        bind = getattr(self._transport, "bind_home", None)
        if bind and home_id:
            bind(home_id)
        pending = [command for command in self._queue if any(
            row.get("id") == command["id"] for row in self._rows(self._base, command["kind"]))]
        if len(pending) != len(self._queue):
            # A companion deletion is authoritative. An obsolete outbox head
            # must not prevent a still-existing second item from reaching home.
            self.notice = "Item removed. Reloaded."
        self._queue = pending
        self._force_snapshot = False
        self._overlay()
        self._dirty_at = self._now if self._dirty_at is None else self._dirty_at
        self._last_refresh = self._now
        if self._session_pending is None:
            self.last_error = None

    def _acknowledge(self, sent, result):
        row = result.get("item")
        if result.get("status") not in ("saved", "conflict") or not isinstance(row, dict):
            raise ValueError("invalid Home HQ save response")
        for index, current in enumerate(self._rows(self._base, sent["kind"])):
            if current.get("id") == sent["id"]:
                self._rows(self._base, sent["kind"])[index] = row
                break
        for index, pending in enumerate(self._queue):
            if (pending["kind"], pending["id"]) != (sent["kind"], sent["id"]):
                continue
            if result["status"] == "conflict":
                self._queue.pop(index)
                self.notice = "Changed elsewhere. Reloaded."
            elif pending["sequence"] == sent["sequence"]:
                self._queue.pop(index)
                self.notice = "Saved"
            else:
                # A second button press while the first request was in flight
                # keeps its desired value, now based on the acknowledged version.
                pending["version"] = row.get("version", pending["version"])
            break
        self._base["revision"] = result.get("revision", self._base.get("revision", 0))
        self._overlay()
        self._dirty_at = self._now if self._dirty_at is None else self._dirty_at
        self._refresh = True

    def _start_request(self):
        if self._force_snapshot:
            name, args = "homehq_snapshot", {}
            self._refresh = False
            self._request = ("snapshot", None)
        elif self._queue:
            command = copy(self._queue[0])
            if command["kind"] == "device":
                name = "homehq_set_device"
                args = {"p_id": command["id"], "p_state": command["state"], "p_version": command["version"]}
            else:
                name = "homehq_set_done"
                args = {"p_kind": command["kind"], "p_id": command["id"],
                        "p_done": command["done"], "p_version": command["version"],
                        "p_done_by": command.get("done_by")}
            self._request = ("write", command)
        elif self._refresh:
            name, args = "homehq_snapshot", {}
            self._refresh = False
            self._request = ("snapshot", None)
        else:
            return
        self._transport.request(name, args)

    def poll(self, now_ms):
        self._now = now_ms
        changed = False
        if self._session_pending is not None and ticks_diff(now_ms, self._session_retry_at) >= 0:
            self._save_session()
            changed = True
        if (self._dirty_at is not None and ticks_diff(now_ms, self._dirty_at) >= 400
                and ticks_diff(now_ms, self._storage_retry_at) >= 0):
            self.flush()
            changed = True
        if not self._config:
            return False
        if self._transport is None:
            try:
                from transport import SupabaseTransport
                session = read(self.session_path)
                self._transport = SupabaseTransport(self._config, session)
            except Exception:
                self.last_error = "Check badge setup"
                self._state = "setup"
                return True
        if self._auth_intent:
            intent, self._auth_intent = self._auth_intent, None
            if intent[0] == "login":
                self._transport.start_login(intent[1], intent[2])
            else:
                self._transport.start_logout()
            intent = None  # Password ownership ends when the transport takes it.
        for event in self._transport.poll():
            kind = event["kind"]
            if kind in ("joined", "changed"):
                self._refresh = True
                self._state = "live"
                changed = True
            elif kind == "session":
                record = session_record(event["data"])
                if not record:
                    continue
                if self._identity and self._identity != record["user_id"]:
                    self._forget_identity()
                self._identity = record["user_id"]
                self._session_pending = record
                self._save_session()
                changed = True
            elif kind == "signed_in":
                self.auth_state = "signed_in"
                self.auth_error = SESSION_STORAGE_ERROR if self._session_pending else None
                self._state = "connecting"
                self._refresh = self._force_snapshot = True
                changed = True
            elif kind in ("signed_out", "auth_error"):
                cleared = self._forget_identity()
                self.auth_state = "signed_out" if kind == "signed_out" else "error"
                self.auth_error = (event.get("message") if kind == "auth_error" else None) if cleared else "Session not cleared. Free storage."
                self._state = "setup"
                changed = True
            elif kind == "photo":
                # An older active download can publish after a later job has
                # reserved its slot. Completion names the bytes now in that
                # file, so remove every earlier same-slot alias before caching.
                local = event["local_path"]
                self._photo_cache = {key: value for key, value in self._photo_cache.items()
                                     if value.rsplit(".", 1)[0] != local.rsplit(".", 1)[0]}
                self._photo_cache[event["path"]] = local
                self._dirty_at = self._now if self._dirty_at is None else self._dirty_at
                changed = True
            elif kind == "result":
                request, sent = self._request or (None, None)
                self._request = None
                try:
                    if request == "write":
                        self._acknowledge(sent, event["data"])
                    elif request == "snapshot":
                        self.receive_snapshot(event["data"])
                except (ValueError, KeyError, TypeError):
                    # A schema mismatch must leave the previous cached screen
                    # useful. It cannot escape update() and reset the badge.
                    self._state = "offline"
                    self._refresh = True
                    self.last_error = "Check project data"
                    self._retry_at = now_ms + 3000
                    changed = True
                    continue
                self._state = "live" if self._transport.joined else "connecting"
                changed = True
            elif kind == "removed":
                request, sent = self._request or (None, None)
                self._request = None
                if request == "write" and sent:
                    self._queue = [pending for pending in self._queue if not (
                        pending["kind"] == sent["kind"] and pending["id"] == sent["id"]
                        and pending["sequence"] == sent["sequence"])]
                    self.notice = "Item removed. Reloaded."
                    self._overlay()
                    self._dirty_at = self._now if self._dirty_at is None else self._dirty_at
                self._force_snapshot = True
                self._refresh = True
                changed = True
            elif kind == "error":
                if self._request and self._request[0] == "write":
                    self._force_snapshot = True
                self._request = None
                self._refresh = True
                self._state = "offline"
                # Raw server/transport errors can contain a URL or bearer token.
                # The product reports a recoverable state, never exception text.
                self.last_error = "Waiting for connection"
                self._retry_at = now_ms + 3000
                changed = True
        if ticks_diff(now_ms, self._last_refresh) >= 60000:
            self._refresh = True
        if (self.auth_state == "signed_in" and self._session_pending is None and self._request is None and ticks_diff(now_ms, self._retry_at) >= 0
                and getattr(self._transport, "can_request", self._transport.ready)):
            try:
                self._start_request()
            except Exception:
                self._request = None
                self._state = "offline"
                self.last_error = "Waiting for connection"
                self._retry_at = now_ms + 3000
                changed = True
        return changed

    def photo_path(self, photo):
        # New snapshots carry a smaller baseline JPEG for Tufty; the PNG path
        # remains the contract for older badges and other device decoders.
        path = photo.get("jpeg_path") or photo.get("path")
        if path:
            local = self._photo_cache.get(path)
            try:
                with open(local or "", "rb"):
                    return local
            except OSError:
                if self._transport and self._transport.ready:
                    # Two slots hold at most 640 KiB on the 1 MiB state volume.
                    # Transport validates the incoming photo before freeing
                    # this evicted slot, so its temporary file adds no peak.
                    local = self.state_root + "/homehq-photo-" + str(self._photo_slot) + ".img"
                    # Repeated frames can ask for an active/queued URI. Only a
                    # newly accepted reservation may evict another useful image
                    # or advance the round-robin slot.
                    if self._transport.photo(path, local):
                        self._photo_slot = (self._photo_slot + 1) % 2
                        self._photo_cache = {key: value for key, value in self._photo_cache.items()
                                             if value.rsplit(".", 1)[0] != local.rsplit(".", 1)[0]}
        asset = photo.get("asset") or "assets/photo-coast.png"
        if not asset.startswith("assets/") or ".." in asset:
            asset = "assets/photo-coast.png"
        return self.app_root + "/" + asset

    def flush(self):
        try:
            write(self.path, {"user_id": self._identity, "snapshot": self._base, "pending": self._queue, "photos": self._photo_cache})
        except (OSError, ValueError):
            # Full/read-only storage cannot make input throw out of update().
            # Keep the in-memory desired values and retry at a bounded cadence.
            self.notice = "Storage busy. Retrying."
            self._storage_retry_at = self._now + 3000
            return False
        self._dirty_at = None
        self._storage_retry_at = 0
        if self.notice == "Storage busy. Retrying.":
            self.notice = "Saved on badge"
        return True

    def close(self):
        self._auth_intent = None
        if self._session_pending is not None:
            self._save_session()
        if self._dirty_at is not None:
            self.flush()
        if self._transport:
            self._transport.close()


def create_service(app_root):
    return Service(app_root)
