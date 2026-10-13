"""Credential lifecycle and real keyboard reachability, without networking."""
import json
from pathlib import Path
import string
import sys
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "homehq/tools"))
from dependencies import add_import_paths
add_import_paths(REPO)
import kbqwerty_board as board
import identity_keyboard as keyboard
from login import SignIn, CredentialKeyboard
from model import HomeHQ, PAGES
from demo import snapshot


class QueuedAuth:
    def __init__(self):
        self.calls = []
    def start_login(self, email, password):
        self.calls.append((email, password))
        return True


def choose(model, token):
    position = model.find(token)
    if position is None:
        raise AssertionError("key not on visible plane")
    row, column = position
    model.move_row(row - model.row)
    model.move_column(column - model.column)


class NativeLoginTests(unittest.TestCase):
    def setUp(self):
        self.auth = QueuedAuth()
        self.form = SignIn()
        self.form.synchronize({"auth_state": "signed_out"}, {})

    def test_printable_password_bank_including_email_symbols_and_case(self):
        model = CredentialKeyboard(limit=128)
        found = set()
        for plane, upper in ((board.LETTERS, False), (board.LETTERS, True), (board.NUMBERS, False), (board.SYMBOLS, False)):
            model._retarget(plane, upper)
            for row in model.rows:
                for token in row:
                    if len(token) == 1 or token == keyboard.SPACE:
                        choose(model, token)
                        model.text = ""
                        self.assertEqual(model.press(), keyboard.TYPED)
                        found.add(model.text)
        self.assertTrue(set(string.ascii_letters + string.digits + string.punctuation + " ").issubset(found))

    def test_commit_then_abandon_editor_drops_transient_text(self):
        self.form.press("B", self.auth)
        model = self.form.keyboard
        model.text = "person+badge@example.invalid"
        choose(model, keyboard.DONE)
        self.form.press("B", self.auth)
        self.assertEqual(self.form.email, "person+badge@example.invalid")
        self.assertEqual(model.text, "")
        self.assertEqual(self.form.focus, 1)
        self.form.press("B", self.auth)
        model = self.form.keyboard
        model.text = "discard this entry"
        choose(model, keyboard.BACK)
        self.form.press("B", self.auth)
        self.assertEqual(model.text, "")
        self.assertEqual(self.form.password, "")

    def test_submit_preserves_password_case_spaces_and_clears_ui(self):
        self.form.email = " person+badge@example.invalid "
        self.form.password = " SpEcial+`/@! "
        self.form.focus = 2
        self.form.press("B", self.auth)
        self.assertEqual(self.auth.calls, [("person+badge@example.invalid", " SpEcial+`/@! ")])
        self.assertEqual((self.form.email, self.form.password), ("", ""))
        self.assertTrue(self.form.busy())
        self.form.press("B", self.auth)
        self.assertEqual(len(self.auth.calls), 1)

    def test_validation_does_not_start_request_or_clear_editable_values(self):
        self.form.email = "wrong address"
        self.form.password = "a"
        self.form.focus = 2
        self.form.press("B", self.auth)
        self.assertEqual(self.auth.calls, [])
        self.assertEqual(self.form.focus, 0)
        self.form.email = "ok@example.invalid"
        self.form.password = ""
        self.form.focus = 2
        self.form.press("B", self.auth)
        self.assertEqual(self.form.focus, 1)

    def test_empty_auth_waits_for_scoped_snapshot_and_demo_never_signs_in(self):
        self.form.synchronize({"auth_state": "signed_in"}, {})
        self.assertTrue(self.form.active())
        data = snapshot()
        data["viewer"] = {"user_id": "test-user", "person_id": "maya"}
        data["home"]["id"] = "test-home"
        self.form.synchronize({"auth_state": "signed_in"}, data)
        self.assertFalse(self.form.active())
        self.form.synchronize({"auth_state": "demo"}, snapshot())
        self.assertFalse(self.form.active())

    def test_debug_and_error_never_echo_entered_values(self):
        self.form.email = "private@example.invalid"
        self.form.password = "not-for-display"
        self.form.focus = 1
        self.form.press("B", self.auth)
        self.form.keyboard.text = "not-for-display"
        encoded = json.dumps(self.form.debug())
        self.assertNotIn(self.form.password, encoded)
        self.assertNotIn(self.form.email, encoded)
        self.form.synchronize({"auth_state": "error", "auth_error": self.form.password}, {})
        self.assertEqual(self.form.error, "Unable to connect. Try again.")
        self.form.clear()
        self.assertIsNone(self.form.keyboard)
        self.assertEqual((self.form.email, self.form.password), ("", ""))

    def test_verified_viewer_overrides_local_focus_and_attributes_anyone(self):
        data = snapshot()
        data["viewer"] = {"user_id": "test-user", "person_id": "maya"}
        app = HomeHQ(data, "alex")
        app.page = PAGES.index("chores")
        app._align()
        self.assertEqual(app.selected()["id"], "maya")
        app.focus["chores"] = "any"
        app.press("B")
        command = app.press("B")
        self.assertEqual(command["done_by"], "maya")
        self.assertEqual(app.detail, "chores")
        self.assertEqual(len(app.rows("people")), 4)

    def test_unverified_local_focus_keeps_anyone_picker_and_account_exit_is_confirmed(self):
        app = HomeHQ(snapshot(), "maya")
        app.page = PAGES.index("chores")
        app.focus["chores"] = "any"
        app.press("B")
        self.assertIsNone(app.press("B"))
        self.assertEqual(app.detail, "who")
        data = snapshot()
        data["viewer"] = {"user_id": "test-user", "person_id": "maya"}
        app = HomeHQ(data)
        app.page = PAGES.index("home")
        app.focus["home"] = "__account"
        app.press("B")
        self.assertEqual(app.detail, "account")
        self.assertIsNone(app.press("B"))
        self.assertEqual(app.detail, "logout")
        self.assertEqual(app.press("B"), {"kind": "logout"})
        app.press("A")
        self.assertEqual(app.detail, "account")


if __name__ == "__main__":
    unittest.main()
