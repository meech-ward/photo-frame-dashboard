"""Interaction and convergence properties that matter on an offline badge."""

import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

APP = Path(__file__).resolve().parents[1] / "badge" / "homehq"
sys.path.insert(0, str(APP))
from model import HomeHQ, PAGES, civil_date
from demo import snapshot


class HomeModelTests(unittest.TestCase):
    def test_next_event_survives_the_repeated_dst_hour(self):
        now = int(datetime(2026, 11, 1, 5, 50, tzinfo=timezone.utc).timestamp())
        later = now + 30 * 60
        data = snapshot()
        data['server_time'] = now
        data['home']['utc_offset_minutes'] = -240
        event = {'id': 'dst', 'start': later, 'end': later + 600, 'start_offset_minutes': -300,
                 'end_offset_minutes': -300, 'title': 'Sunday event', 'people': ['alex'], 'all_day': False}
        data['events'] = [event]
        app = HomeHQ(data)
        self.assertEqual(app.minute, 110)
        self.assertEqual(app.event_minute(event), 80)
        self.assertEqual(app.next_event()['id'], 'dst')
        self.assertEqual(app.event_gap(event), 30)

    def test_event_date_and_time_use_its_endpoint_offset(self):
        app = HomeHQ(snapshot())
        stamp = int(datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc).timestamp())
        self.assertEqual(app.day_text(stamp, -300), 'SUN · 11/1')
        self.assertEqual(app.time_text(stamp, -300), '11:30')

    def setUp(self):
        self.data = snapshot()
        self.app = HomeHQ(self.data)

    def page(self, name):
        self.app.page = PAGES.index(name)
        self.app._align()

    def test_sample_clock_and_owner_names(self):
        self.assertEqual(self.app.minute, 15 * 60 + 18)
        self.assertEqual([p["name"] for p in self.app.rows("people")], ["Wes", "Claudia", "Buzzsaw", "Skidmark"])
        self.assertEqual(self.app.next_event()["title"], "Piano lesson")

    def test_four_family_badges_prefer_distinct_chore_cards(self):
        for person in self.data["people"]:
            app = HomeHQ(copy.deepcopy(self.data), person["id"])
            self.assertEqual(app.page, 0)
            self.assertEqual(len(app.rows("people")), 4)
            app.page = PAGES.index("chores")
            app._align()
            self.assertEqual(app.selected()["id"], person["id"])
            app.press("B")
            self.assertEqual(app.person_id, person["id"])

    def test_removed_preferred_member_falls_back_without_changing_household(self):
        app = HomeHQ(copy.deepcopy(self.data), "removed-member")
        app.page = PAGES.index("chores")
        app._align()
        self.assertEqual(app.selected()["id"], self.data["people"][0]["id"])
        self.assertEqual(app.rows("people"), self.data["people"])

    def test_all_seven_pages_wrap_with_labelled_buttons(self):
        for i in range(7):
            self.assertEqual(self.app.page, i)
            self.assertEqual(self.app.softkeys()[0], "PREV")
            self.assertEqual(self.app.softkeys()[2], "NEXT")
            self.app.press("C")
        self.assertEqual(self.app.page, 0)
        self.app.press("A")
        self.assertEqual(self.app.page, 6)

    def test_live_snapshot_replaces_demo_clock(self):
        changed = copy.deepcopy(self.data)
        changed["server_time"] += 86400
        self.app.replace(changed)
        self.assertEqual(self.app.epoch, changed["server_time"])
        self.assertEqual(self.app.date_label, "MON · OCT 12")

    def test_calendar_can_reach_tomorrow(self):
        self.page("calendar")
        self.assertEqual(len(self.app.current_rows()), 38)
        self.app.move(10)
        self.assertGreater(self.app.selected()["start"], self.app.epoch)

    def test_navigation_never_returns_a_write_command(self):
        for key in ("C", "DOWN", "UP", "A"):
            self.assertIsNone(self.app.press(key))
        self.assertEqual(self.app.optimistic, {})

    def test_event_details_have_a_back_path(self):
        self.app.press("B")
        self.assertEqual(self.app.detail, "event")
        self.assertEqual(self.app.softkeys(), ("BACK", "", ""))
        self.assertIsNone(self.app.press("A"))
        self.assertIsNone(self.app.detail)

    def test_row_identity_survives_snapshot_insertion_and_reorder(self):
        self.page("shopping")
        self.app.move(4)
        selected = self.app.selected()["id"]
        changed = copy.deepcopy(self.data)
        changed["shopping"].reverse()
        changed["shopping"].insert(0, {"id": "new", "name": "Strawberries", "done": False})
        self.app.replace(changed)
        self.assertEqual(self.app.selected()["id"], selected)
        command = self.app.press("B")
        self.assertEqual(command["id"], selected)

    def test_removed_selection_falls_back_to_existing_row(self):
        self.page("shopping")
        removed = self.app.selected()["id"]
        changed = copy.deepcopy(self.data)
        changed["shopping"] = [r for r in changed["shopping"] if r["id"] != removed]
        self.app.replace(changed)
        self.assertNotEqual(self.app.selected()["id"], removed)
        self.assertIn(self.app.press("B")["id"], [r["id"] for r in changed["shopping"]])

    def test_shopping_command_is_desired_value_with_version(self):
        self.page("shopping")
        row = self.app.selected()
        row["version"] = 7
        command = self.app.press("B")
        self.assertEqual(command, {"kind": "shopping", "id": row["id"], "done": True, "version": 7})
        self.assertTrue(self.app.done("shopping", row))
        self.assertEqual(self.app.softkeys()[1], "UNDO")

    def test_old_snapshot_does_not_erase_optimistic_choice(self):
        self.page("shopping")
        row_id = self.app.selected()["id"]
        self.app.press("B")
        self.app.replace(copy.deepcopy(self.data))
        self.assertEqual(self.app.selected()["id"], row_id)
        self.assertTrue(self.app.done("shopping", self.app.selected()))

    def test_matching_snapshot_retires_optimistic_choice(self):
        self.page("shopping")
        row_id = self.app.selected()["id"]
        self.app.press("B")
        changed = copy.deepcopy(self.data)
        row = next(r for r in changed["shopping"] if r["id"] == row_id)
        row["done"] = True
        row["version"] += 1
        self.app.replace(changed)
        self.assertEqual(self.app.optimistic, {})
        command = self.app.press("B")
        self.assertFalse(command["done"])
        self.assertEqual(command["version"], row["version"])

    def test_undo_before_ack_sends_false_not_a_toggle(self):
        self.page("shopping")
        first = self.app.press("B")
        second = self.app.press("B")
        self.assertTrue(first["done"])
        self.assertFalse(second["done"])
        self.assertEqual(first["id"], second["id"])

    def test_explicit_rejection_removes_unaccepted_checkmark(self):
        self.page("shopping")
        command = self.app.press("B")
        self.assertTrue(self.app.done("shopping", self.app.selected()))
        self.app.reject(command)
        self.assertFalse(self.app.done("shopping", self.app.selected()))
        self.assertEqual(self.app.softkeys()[1], "GET")

    def test_empty_lists_have_no_write_action(self):
        self.app.replace({"people": [], "events": [], "chores": [], "shopping": [], "devices": [], "agents": [], "photos": []})
        for name in ("today", "calendar", "shopping", "home", "agents"):
            self.page(name)
            self.assertIsNone(self.app.press("B"))
            self.assertEqual(self.app.softkeys()[1], "")

    def test_chore_person_detail_and_routine_picker(self):
        self.page("chores")
        self.app.press("B")
        self.assertEqual(self.app.detail, "chores")
        self.assertEqual(self.app.person_id, "alex")
        self.app.press("C")
        self.assertEqual(self.app.detail, "routine")
        self.app.press("B")
        self.assertEqual(self.app.routine, "morning")
        self.assertEqual(self.app.detail, "chores")
        self.app.press("A")
        self.assertIsNone(self.app.detail)

    def test_anyone_chore_requires_visible_person_choice(self):
        self.page("chores")
        self.app.move(4)
        self.app.press("B")
        self.assertEqual(self.app.person_id, "any")
        self.assertIsNone(self.app.press("B"))
        self.assertEqual(self.app.detail, "who")
        self.app.move(2)
        command = self.app.press("B")
        self.assertEqual(command["kind"], "chore")
        self.assertEqual(command["done_by"], "maya")
        self.assertEqual(self.app.detail, "chores")

    def test_personal_chore_command_does_not_invent_attribution(self):
        self.page("chores")
        self.app.move(2)
        self.app.press("B")
        row = self.app.selected()
        command = self.app.press("B")
        self.assertEqual(command["kind"], "chore")
        self.assertNotIn("done_by", command)
        self.assertEqual(command["done"], not row["done"])

    def test_device_confirmation_replaces_hold_gesture(self):
        self.data["devices"] = [{"id": "door", "name": "Back door", "type": "lock", "locked": True, "version": 3}]
        self.page("home")
        self.app.press("B")
        self.assertEqual(self.app.softkeys()[1], "UNLOCK")
        self.assertIsNone(self.app.press("B"))
        self.assertEqual(self.app.detail, "confirm")
        self.app.press("A")
        self.assertEqual(self.app.detail, "device")
        self.app.press("B")
        command = self.app.press("B")
        self.assertEqual(command, {"kind": "device", "id": "door", "state": {"locked": False}, "version": 3})

    def test_lamp_command_cannot_overwrite_brightness(self):
        self.data["devices"] = [{"id": "lamp", "type": "light", "on": True, "level": 80, "version": 4}]
        self.page("home")
        self.app.press("B")
        self.assertEqual(self.app.softkeys()[1], "OFF")
        self.assertEqual(self.app.press("B"), {"kind": "device", "id": "lamp", "state": {"on": False}, "version": 4})

    def test_unlocked_device_offers_lock_instead_of_unlock(self):
        self.data["devices"] = [{"id": "door", "name": "Front door", "type": "lock", "locked": False, "version": 3}]
        self.page("home")
        self.app.press("B")
        self.assertEqual(self.app.softkeys()[1], "LOCK")
        self.app.press("B")
        self.assertEqual(self.app.press("B")["state"], {"locked": True})

    def test_photo_slideshow_is_paused_by_primary_button(self):
        self.page("photos")
        first = self.app.selected()["id"]
        self.assertTrue(self.app.tick(12000))
        self.assertNotEqual(self.app.selected()["id"], first)
        self.app.press("B")
        paused = self.app.selected()["id"]
        self.app.tick(12000)
        self.assertEqual(self.app.selected()["id"], paused)
        self.assertEqual(self.app.softkeys()[1], "PLAY")

    def test_scroll_bounds_do_not_wrap_to_unseen_content(self):
        self.page("shopping")
        self.app.move(-100)
        self.assertEqual(self.app.index(), 0)
        self.app.move(100)
        self.assertEqual(self.app.index(), len(self.app.groceries()) - 1)

    def test_civil_date_and_offset_cross_midnight(self):
        self.assertEqual(civil_date(0), (1970, 1, 1))
        self.data["home"]["utc_offset_minutes"] = -240
        self.app.set_time(1791766800)  # Oct 12 01:00 UTC -> Oct 11 21:00 Toronto
        self.assertEqual(self.app.minute, 21 * 60)
        self.assertIn("OCT 11", self.app.date_label)

    def test_clock_tick_does_not_replace_explicit_open_routine(self):
        self.page("chores")
        self.app.press("B")
        self.app.routine = "morning"
        self.app.tick(60000)
        self.assertEqual(self.app.routine, "morning")


if __name__ == "__main__":
    unittest.main()
