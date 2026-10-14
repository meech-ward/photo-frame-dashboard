"""Offline persistence, request ordering and convergent desired-state writes."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import cache
from demo import snapshot
from service import Service


class FakeTransport:
    def __init__(self):
        self.session = {"v": 1, "user_id": "owner", "refresh_token": "refresh"}
        self.ready = True
        self.joined = True
        self.busy = False
        self.events = []
        self.requests = []
        self.photos = []
        self.closed = False

    @property
    def can_request(self):
        return self.ready and not self.busy

    def poll(self):
        events, self.events = self.events, []
        if any(e["kind"] in ("result", "error") for e in events):
            self.busy = False
        return events

    def request(self, name, args):
        if self.busy:
            raise RuntimeError("one HTTP request at a time")
        self.busy = True
        self.requests.append((name, copy.deepcopy(args)))

    def photo(self, path, local):
        self.photos.append((path, local))
        return True

    def close(self):
        self.closed = True


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.transport = FakeTransport()
        self.config = {"url": "https://example.invalid", "publishable_key": "sb_publishable_test"}
        cache.write(self.directory.name + "/homehq-cache.json", {"user_id": "owner", "snapshot": snapshot(), "pending": []})
        self.service = Service("/app", self.transport, self.directory.name, self.config)

    def row(self, data=None, kind="shopping", row_id="g1"):
        data = data if data is not None else self.service.snapshot()
        table = {"shopping": "shopping", "chore": "chores", "device": "devices"}[kind]
        return next(r for r in data[table] if r["id"] == row_id)

    def check(self, desired=True, row_id="g1", version=1):
        return {"kind": "shopping", "id": row_id, "done": desired, "version": version}

    def receive(self, data, now=1):
        self.transport.events.append({"kind": "result", "data": data})
        return self.service.poll(now)

    def ack(self, desired, version, status="saved", now=10):
        row = dict(self.row())
        row.update(done=desired, version=version)
        self.receive({"status": status, "item": row, "revision": version}, now)

    def test_offline_check_then_undo_coalesces_one_desired_value(self):
        self.transport.ready = False
        self.service.command(self.check(True))
        self.service.command(self.check(False))
        self.assertEqual(self.service.status()["pending"], 1)
        self.assertFalse(self.row()["done"])
        self.transport.ready = True
        self.service.poll(10)
        name, args = self.transport.requests[0]
        self.assertEqual(name, "homehq_set_done")
        self.assertFalse(args["p_done"])
        self.assertEqual(args["p_version"], 1)

    def test_first_version_remains_anchor_across_offline_presses(self):
        self.service.command(self.check(True, version=3))
        self.service.command(self.check(False, version=19))
        self.assertEqual(self.service._queue[0]["version"], 3)

    def test_pending_values_survive_checkpoint_and_restart(self):
        self.transport.ready = False
        self.service.command(self.check())
        self.service.poll(400)
        restarted = Service("/app", FakeTransport(), self.directory.name, self.config)
        self.assertEqual(restarted.status()["pending"], 1)
        self.assertTrue(self.row(restarted.snapshot())["done"])
        restarted.poll(0)
        self.assertTrue(restarted._transport.requests[0][1]["p_done"])

    def test_received_snapshot_is_overlaid_with_pending_choice(self):
        self.service.command(self.check())
        incoming = snapshot()
        self.assertFalse(self.row(incoming)["done"])
        self.service.receive_snapshot(incoming)
        self.assertTrue(self.row()["done"])
        self.assertFalse(self.row(self.service._base)["done"])

    def test_second_click_during_first_request_uses_acknowledged_version(self):
        self.service.command(self.check(True))
        self.service.poll(0)
        self.service.command(self.check(False))
        self.ack(True, 2)
        self.assertEqual(self.service.status()["pending"], 1)
        self.assertFalse(self.row()["done"])
        args = self.transport.requests[-1][1]
        self.assertFalse(args["p_done"])
        self.assertEqual(args["p_version"], 2)
        self.ack(False, 3, now=20)
        self.assertEqual(self.service.status()["pending"], 0)
        self.assertFalse(self.row()["done"])
        self.assertEqual(self.row()["version"], 3)

    def test_acknowledged_write_schedules_authoritative_snapshot(self):
        self.service.command(self.check())
        self.service.poll(0)
        self.ack(True, 2)
        self.assertEqual(self.transport.requests[-1], ("homehq_snapshot", {}))
        self.assertEqual(self.service.status()["pending"], 0)

    def test_conflict_discards_stale_choice_and_reports_reloaded_row(self):
        self.service.command(self.check())
        self.service.poll(0)
        self.ack(False, 8, "conflict")
        self.assertFalse(self.row()["done"])
        self.assertEqual(self.row()["version"], 8)
        self.assertEqual(self.service.status()["pending"], 0)
        self.assertIn("Changed elsewhere", self.service.status()["notice"])

    def test_several_broadcast_hints_coalesce_one_snapshot_fetch(self):
        self.service.poll(0)
        self.receive(snapshot())
        count = len(self.transport.requests)
        self.transport.events.extend([{"kind": "changed"}] * 5)
        self.service.poll(10)
        self.assertEqual(len(self.transport.requests), count + 1)
        self.assertEqual(self.transport.requests[-1][0], "homehq_snapshot")

    def test_rejoin_always_refreshes_even_when_no_change_hint_arrives(self):
        self.service.poll(0)
        self.receive(snapshot())
        count = len(self.transport.requests)
        self.transport.events.append({"kind": "joined"})
        self.service.poll(20)
        self.assertEqual(len(self.transport.requests), count + 1)
        self.assertEqual(self.transport.requests[-1][0], "homehq_snapshot")

    def test_deleted_outbox_head_is_removed_then_second_item_drains(self):
        self.service.command(self.check(row_id="g1"))
        self.service.command(self.check(row_id="g2"))
        self.service.poll(0)
        self.transport.events.append({"kind": "removed"})
        self.transport.busy = False
        self.service.poll(10)
        self.assertEqual(self.transport.requests[-1][0], "homehq_snapshot")
        incoming = snapshot()
        incoming["shopping"] = [row for row in incoming["shopping"] if row["id"] != "g1"]
        self.receive(incoming, 11)
        self.assertEqual(self.transport.requests[-1][1]["p_id"], "g2")
        row = dict(self.row(row_id="g2"), done=True, version=2)
        self.receive({"status": "saved", "item": row, "revision": 2}, 12)
        self.assertEqual(self.service.status()["pending"], 0)
        self.assertTrue(self.row(row_id="g2")["done"])

    def test_authoritative_snapshot_prunes_items_deleted_while_offline(self):
        self.service.command(self.check(row_id="g1"))
        self.service.command(self.check(row_id="g2"))
        incoming = snapshot()
        incoming["shopping"] = [row for row in incoming["shopping"] if row["id"] != "g1"]
        self.service.receive_snapshot(incoming)
        self.service.poll(0)
        self.assertEqual(self.service.status()["pending"], 1)
        self.assertEqual(self.transport.requests[-1][1]["p_id"], "g2")
        self.assertEqual(self.service.status()["notice"], "Item removed. Reloaded.")

    def test_failed_write_refreshes_before_retrying_old_version(self):
        self.service.command(self.check())
        self.service.poll(0)
        self.transport.events.append({"kind": "error"})
        self.service.poll(10)
        self.service.poll(3010)
        self.assertEqual(self.transport.requests[-1][0], "homehq_snapshot")
        self.receive(snapshot(), 3011)
        self.assertEqual(self.transport.requests[-1][0], "homehq_set_done")

    def test_connection_error_preserves_queue_for_delayed_retry(self):
        self.service.command(self.check())
        self.service.poll(0)
        self.transport.events.append({"kind": "error", "detail": "Bearer secret-should-not-be-in-ui"})
        self.service.poll(10)
        self.assertEqual(self.service.status()["state"], "offline")
        self.assertEqual(self.service.status()["pending"], 1)
        self.assertNotIn("secret", self.service.status()["error"])
        count = len(self.transport.requests)
        self.service.poll(3009)
        self.assertEqual(len(self.transport.requests), count)
        self.service.poll(3010)
        self.assertEqual(len(self.transport.requests), count + 1)

    def test_busy_auth_or_photo_task_does_not_start_rpc(self):
        self.transport.busy = True
        self.service.poll(0)
        self.assertEqual(self.transport.requests, [])
        self.transport.busy = False
        self.service.poll(1)
        self.assertEqual(self.transport.requests, [("homehq_snapshot", {})])

    def test_invalid_remote_snapshot_keeps_previous_usable_data(self):
        self.service.poll(0)
        before = copy.deepcopy(self.service.snapshot())
        self.receive({"schema_version": 99})
        self.assertEqual(self.service.snapshot(), before)
        self.assertEqual(self.service.status()["state"], "offline")

    def test_cache_invalid_pending_shape_keeps_valid_snapshot(self):
        data = snapshot()
        data["home"]["title"] = "Recovered house"
        cache.write(self.service.path, {"user_id": "owner", "snapshot": data, "pending": "corrupt"})
        restarted = Service("/app", FakeTransport(), self.directory.name, self.config)
        self.assertEqual(restarted.snapshot()["home"]["title"], "Recovered house")
        self.assertEqual(restarted.status()["pending"], 0)

    def test_corrupt_pending_entries_are_dropped_without_losing_good_ones(self):
        good = dict(self.check(), sequence=1)
        cache.write(self.service.path, {"user_id": "owner", "snapshot": snapshot(), "pending": [None, {}, "bad", good]})
        restarted = Service("/app", FakeTransport(), self.directory.name, self.config)
        self.assertEqual(restarted.status()["pending"], 1)
        self.assertTrue(self.row(restarted.snapshot())["done"])

    def test_demo_actions_are_local_persistent_state(self):
        demo = Service("/app", state_root=self.directory.name, config=None)
        demo.command(self.check())
        self.assertEqual(demo.status(), {"state": "demo", "pending": 0, "error": None, "notice": None, "auth_state": "demo", "auth_error": None})
        demo.close()
        restarted = Service("/app", state_root=self.directory.name, config=None)
        self.assertTrue(self.row(restarted.snapshot())["done"])

    def test_device_rpc_sends_only_desired_partial_state(self):
        self.service.command({"kind": "device", "id": "kitchen-light", "state": {"on": False}, "version": 1})
        self.assertFalse(self.row(kind="device", row_id="kitchen-light")["on"])
        self.service.poll(0)
        self.assertEqual(self.transport.requests[0], ("homehq_set_device", {"p_id": "kitchen-light", "p_state": {"on": False}, "p_version": 1}))

    def test_queue_full_is_bounded_and_existing_rows_can_still_coalesce(self):
        for i in range(cache.MAX_PENDING):
            self.service.command(self.check(row_id="item-" + str(i)))
        self.assertFalse(self.service.command(self.check(row_id="extra")))
        self.assertEqual(self.service.status()["pending"], cache.MAX_PENDING)
        self.assertTrue(self.service.command(self.check(False, "item-0")))
        self.assertEqual(self.service.status()["pending"], cache.MAX_PENDING)

    def test_rejected_full_queue_action_can_roll_back_native_optimism(self):
        from model import HomeHQ, PAGES
        for row in self.service.snapshot()["chores"][:cache.MAX_PENDING]:
            self.service.command({"kind": "chore", "id": row["id"], "done": not row["done"], "version": row["version"]})
        app = HomeHQ(self.service.snapshot())
        app.page = PAGES.index("shopping")
        app._align()
        command = app.press("B")
        accepted = self.service.command(command)
        self.assertFalse(accepted)
        app.reject(command)
        app.replace(self.service.snapshot())
        self.assertFalse(app.done("shopping", app.selected()))

    def test_private_photo_is_queued_and_falls_back_to_bundled_art(self):
        path = self.service.photo_path({"id": "p1", "path": "owner/photo.png", "asset": "../../bad"})
        self.assertEqual(path, "/app/assets/photo-coast.png")
        self.assertEqual(len(self.transport.photos), 1)

    def test_jpeg_variant_is_preferred_and_uses_a_format_neutral_cache_slot(self):
        photo = {"id": "p1", "path": "owner/photo.png", "jpeg_path": "owner/photo.jpg"}
        self.assertEqual(self.service.photo_path(photo), "/app/assets/photo-coast.png")
        self.assertEqual(self.transport.photos, [("owner/photo.jpg", self.directory.name + "/homehq-photo-0.img")])

    def test_existing_png_cache_and_new_jpeg_cache_both_survive_restart(self):
        old, new = self.directory.name + "/homehq-photo-0.png", self.directory.name + "/homehq-photo-1.img"
        Path(old).write_bytes(b"previous-png")
        Path(new).write_bytes(b"new-jpeg")
        cache.write(self.service.path, {"user_id": "owner", "snapshot": snapshot(), "pending": [],
                    "photos": {"owner/old.png": old, "owner/new.jpg": new}})
        transport = FakeTransport()
        restarted = Service("/app", transport, self.directory.name, self.config)
        self.assertEqual(restarted.photo_path({"path": "owner/old.png"}), old)
        self.assertEqual(restarted.photo_path({"path": "owner/new.png", "jpeg_path": "owner/new.jpg"}), new)
        self.assertEqual(transport.photos, [])

    def test_completed_img_slot_removes_legacy_png_alias_for_the_same_slot(self):
        legacy, local = self.directory.name + "/homehq-photo-0.png", self.directory.name + "/homehq-photo-0.img"
        self.service._photo_cache = {"owner/old.png": legacy}
        Path(local).write_bytes(b"new-jpeg")
        self.transport.events.append({"kind": "photo", "path": "owner/new.jpg", "local_path": local})
        self.service.poll(0)
        self.assertEqual(self.service._photo_cache, {"owner/new.jpg": local})

    def test_corrupt_photo_cache_metadata_falls_back_and_queues_download(self):
        cache.write(self.service.path, {"user_id": "owner", "snapshot": snapshot(), "pending": [], "photos": {
            "owner/integer.png": 7, "owner/object.png": {}, "owner/elsewhere.png": "/wrong/place.png",
            "owner/valid.png": self.directory.name + "/homehq-photo-0.png"}})
        transport = FakeTransport()
        restarted = Service("/app", transport, self.directory.name, self.config)
        self.assertEqual(restarted._photo_cache, {"owner/valid.png": self.directory.name + "/homehq-photo-0.png"})
        path = restarted.photo_path({"id": "p1", "path": "owner/integer.png", "asset": "assets/photo-coast.png"})
        self.assertEqual(path, "/app/assets/photo-coast.png")
        self.assertEqual(transport.photos[0][0], "owner/integer.png")

    def test_duplicate_photo_uri_does_not_rotate_slots_or_evict_completed_mapping(self):
        from transport import SupabaseTransport

        class QueuedTransport(FakeTransport):
            photo = SupabaseTransport.photo

        transport = QueuedTransport()
        transport.session = {"user_id": "owner"}
        transport.home_id = "owner"
        transport._photo_active = "owner/active.png"
        transport._photos = []
        self.service._transport = transport
        slot0 = self.directory.name + "/homehq-photo-0.img"
        slot1 = self.directory.name + "/homehq-photo-1.img"
        self.service._photo_slot = 1
        self.service._photo_cache = {"owner/previous.png": slot1}
        Path(slot1).write_bytes(b"previous-picture")
        photo = {"id": "new", "path": "owner/new.png", "asset": "assets/photo-coast.png"}
        self.service.photo_path(photo)
        self.assertEqual(transport._photos, [(photo["path"], slot1)])
        self.assertEqual(self.service._photo_slot, 0)
        self.assertEqual(self.service._photo_cache, {})
        self.service.photo_path(photo)
        self.assertEqual(transport._photos, [(photo["path"], slot1)])
        self.assertEqual(self.service._photo_slot, 0)
        # The old active download completes while this new URI is still queued.
        # Repeated rendering must preserve its now-useful mapping in slot 0.
        Path(slot0).write_bytes(b"completed-active-picture")
        transport._photo_active = None
        transport.events.append({"kind": "photo", "path": "owner/active.png", "local_path": slot0})
        self.service.poll(0)
        self.service.photo_path(photo)
        self.assertEqual(transport._photos, [(photo["path"], slot1)])
        self.assertEqual(self.service._photo_slot, 0)
        self.assertEqual(self.service._photo_cache, {"owner/active.png": slot0})
        self.assertEqual(Path(slot0).read_bytes(), b"completed-active-picture")

    def test_later_photo_completion_removes_same_slot_mapping_added_after_reservation(self):
        from transport import SupabaseTransport

        class QueuedTransport(FakeTransport):
            photo = SupabaseTransport.photo

        transport = QueuedTransport()
        transport.session = {"user_id": "owner"}
        transport.home_id = "owner"
        transport._photo_active = "owner/active.png"
        transport._photos = []
        self.service._transport = transport
        self.service._photo_slot = 1
        slot0 = self.directory.name + "/homehq-photo-0.img"
        slot1 = self.directory.name + "/homehq-photo-1.img"
        for name in ("new1", "new2"):
            self.service.photo_path({"id": name, "path": "owner/" + name + ".png"})
        self.assertEqual(transport._photos, [("owner/new1.png", slot1), ("owner/new2.png", slot0)])
        # The active write finishes after new2 already reserved its slot; queue
        # acceptance therefore cannot be the final authority for slot mappings.
        for tick, path, slot, body in ((0, "owner/active.png", slot0, b"active-photo"),
                                      (100, "owner/new1.png", slot1, b"new-one"),
                                      (200, "owner/new2.png", slot0, b"new-two")):
            Path(slot).write_bytes(body)
            transport.events.append({"kind": "photo", "path": path, "local_path": slot})
            self.service.poll(tick)
        self.assertEqual(self.service._photo_cache, {"owner/new1.png": slot1, "owner/new2.png": slot0})
        self.assertEqual(self.service.photo_path({"id": "active", "path": "owner/active.png"}),
                         "/app/assets/photo-coast.png")
        self.assertEqual(Path(slot0).read_bytes(), b"new-two")

    def test_rotated_session_token_is_checkpointed(self):
        session = {"v": 1, "refresh_token": "rotated", "user_id": "owner"}
        self.transport.events.append({"kind": "session", "data": session})
        self.service.poll(0)
        self.assertEqual(cache.read(self.service.session_path), session)

    def test_failed_rotated_session_checkpoint_blocks_rpc_until_durable(self):
        session = {"v": 1, "refresh_token": "rotated", "user_id": "owner"}
        self.service.command(self.check())
        self.transport.events.append({"kind": "session", "data": session})
        original_write = cache.write
        stored = []

        def save(path, value):
            if path == self.service.session_path:
                stored.append(dict(value))
                raise OSError("read only")
            original_write(path, value)

        with patch("service.write", side_effect=save):
            self.service.poll(0)
            self.assertEqual(self.service._session_pending, session)
            self.assertEqual(self.service.status()["error"], "Session not saved. Free storage.")
            self.assertEqual(self.transport.requests, [])
            self.service.poll(2999)
            self.assertEqual(len(stored), 1)
            self.service.poll(3000)
            self.assertEqual(len(stored), 2)
            self.assertEqual(self.transport.requests, [])

        order = []
        request = self.transport.request

        def save_ok(path, value):
            original_write(path, value)
            if path == self.service.session_path:
                order.append("session stored")

        def dispatch(name, args):
            self.assertEqual(cache.read(self.service.session_path), session)
            order.append("rpc sent")
            request(name, args)

        self.transport.request = dispatch
        with patch("service.write", side_effect=save_ok):
            self.service.poll(6000)
        self.assertEqual(order, ["session stored", "rpc sent"])
        self.assertIsNone(self.service._session_pending)
        self.assertEqual(self.transport.requests[-1][0], "homehq_set_done")

    def test_joined_and_snapshot_events_do_not_hide_unsaved_session(self):
        session = {"v": 1, "refresh_token": "rotated", "user_id": "owner"}
        self.service.poll(0)  # Snapshot was already in flight before rotation.
        self.transport.events.extend([{"kind": "session", "data": session}, {"kind": "joined"},
                                      {"kind": "result", "data": snapshot()}])
        with patch("service.write", side_effect=OSError("full")):
            self.service.poll(1)
        self.assertEqual(self.service.last_error, "Session not saved. Free storage.")
        self.assertEqual(self.service.status()["notice"], "Session not saved. Free storage.")
        self.assertEqual(len(self.transport.requests), 1)

    def test_close_retries_unsaved_session_without_raising(self):
        session = {"v": 1, "refresh_token": "rotated", "user_id": "owner"}
        self.transport.events.append({"kind": "session", "data": session})
        with patch("service.write", side_effect=OSError("read only")) as save:
            self.service.poll(0)
            self.service.close()
            self.assertEqual(save.call_count, 2)
        self.assertEqual(self.service._session_pending, session)
        self.assertTrue(self.transport.closed)

    def test_close_flushes_and_releases_transport(self):
        self.service.command(self.check())
        self.service.close()
        self.assertTrue(self.transport.closed)
        self.assertTrue(cache.read(self.service.path)["pending"])

    def test_storage_failure_keeps_input_usable_and_retries_at_bounded_cadence(self):
        self.transport.ready = False
        self.service.command(self.check())
        with patch("service.write", side_effect=OSError("read only")) as save:
            self.service.poll(400)
            self.assertTrue(self.row()["done"])
            self.assertEqual(self.service.status()["pending"], 1)
            self.assertIn("Storage busy", self.service.status()["notice"])
            self.service.command(self.check(False))
            self.assertFalse(self.row()["done"])
            self.service.poll(1000)
            self.assertEqual(save.call_count, 1)
            self.service.poll(3400)
            self.assertEqual(save.call_count, 2)
        self.service.poll(6400)
        self.assertIsNone(self.service._dirty_at)
        self.assertEqual(self.service.status()["notice"], "Saved on badge")
        self.assertFalse(cache.read(self.service.path)["pending"][0]["done"])

    def test_close_cannot_raise_on_full_storage(self):
        self.service.command(self.check())
        with patch("service.write", side_effect=OSError("full")):
            self.service.close()
        self.assertTrue(self.transport.closed)
        self.assertEqual(self.service.status()["pending"], 1)
        self.assertIsNotNone(self.service._dirty_at)


class CacheTests(unittest.TestCase):
    def test_non_object_rows_and_bad_ids_are_rejected(self):
        for row in (None, "broken", {}, {"id": ""}, {"id": 7}):
            data = snapshot()
            data["shopping"] = [row]
            self.assertFalse(cache.valid_snapshot(data))

    def test_present_home_offset_must_be_bounded_integer(self):
        for value in (None, True, "-240", 10000):
            data = snapshot()
            data["home"]["utc_offset_minutes"] = value
            self.assertFalse(cache.valid_snapshot(data))
        data = snapshot()
        del data["home"]["utc_offset_minutes"]
        self.assertTrue(cache.valid_snapshot(data))

    def test_atomic_rename_failure_preserves_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            path = d + "/cache.json"
            cache.write(path, {"old": True})
            with patch.object(cache.os, "rename", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    cache.write(path, {"new": True})
            self.assertEqual(cache.read(path), {"old": True})

    def test_truncated_and_oversize_json_fall_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "cache.json"
            path.write_text('{"bad":')
            self.assertEqual(cache.read(str(path), "fallback"), "fallback")
            path.write_text("x" * (cache.MAX_BYTES + 1))
            self.assertEqual(cache.read(str(path), "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
