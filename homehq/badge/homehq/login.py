"""Native credentials are transient; the service owns Auth and durable sessions."""

import kbqwerty_board as board
import identity_keyboard as keyboard

SAFE_ERRORS = ("Check email and password.", "Sign in again.",
               "Unable to connect. Try again.", "Session not saved. Free storage.",
               "Session not cleared. Free storage.")


class CredentialKeyboard(board.PlaneModel):
    def __init__(self, text="", limit=254):
        board.PlaneModel.__init__(self, text=text, limit=limit,
                                  rows=board.LOWER_ROWS, opens_at=(0, 0))

    def _retarget(self, plane, upper):
        board.PlaneModel._retarget(self, plane, upper)
        if plane == board.SYMBOLS:
            # The reference iOS board's bullet is not needed for credentials;
            # backtick completes printable ASCII without forking its navigation.
            self.rows = tuple(tuple("`" if cell == "•" else cell for cell in row)
                              for row in self.rows)


class SignIn:
    detail = None
    def __init__(self):
        self.email = ""
        self.password = ""
        self.focus = 0
        self.editing = None
        self.keyboard = None
        self.auth_state = "demo"
        self.error = ""
        self.waiting_home = False
        self.phase = 0
        self._elapsed = 0

    def clear(self):
        if self.keyboard is not None:
            self.keyboard.text = ""
        self.email = self.password = ""
        self.editing = None
        self.keyboard = None

    def synchronize(self, status, snapshot):
        previous = (self.auth_state, self.error, self.waiting_home)
        self.auth_state = status.get("auth_state", "demo")
        # Only authored error messages reach pixels. Raw exception/server text
        # can contain request data and has no place on a credentials screen.
        error = status.get("auth_error")
        if error:
            self.error = error if error in SAFE_ERRORS else "Unable to connect. Try again."
            if self.auth_state in ("error", "signed_out") and previous[0] == "signing_in":
                self.focus = 0
        elif self.auth_state not in ("error", "signed_out"):
            self.error = ""
        viewer = snapshot.get("viewer") or {}
        home = snapshot.get("home") or {}
        self.waiting_home = (self.auth_state == "signed_in"
                             and not (isinstance(viewer, dict) and viewer.get("user_id")
                                      and isinstance(home, dict) and home.get("id")))
        if self.auth_state in ("demo", "signed_in", "signing_out"):
            self.clear()
        return previous != (self.auth_state, self.error, self.waiting_home)

    def active(self):
        return self.auth_state in ("signed_out", "error", "signing_in", "signing_out") or self.waiting_home

    def busy(self):
        return self.auth_state in ("signing_in", "signing_out") or self.waiting_home

    def tick(self, elapsed):
        if not self.busy():
            return False
        self._elapsed += elapsed
        if self._elapsed < 400:
            return False
        self._elapsed %= 400
        self.phase = (self.phase + 1) % 3
        return True

    def press(self, key, service):
        if self.busy():
            return False
        model = self.keyboard
        if model is not None:
            if key in ("A", "C"):
                model.move_column(-1 if key == "A" else 1)
            elif key in ("UP", "DOWN"):
                model.move_row(-1 if key == "UP" else 1)
            elif key == "B":
                outcome = model.press()
                if outcome in (keyboard.COMMITTED, keyboard.ABANDONED):
                    if outcome == keyboard.COMMITTED:
                        value = model.text
                        if self.editing == "email":
                            self.email = value
                            self.focus = 1
                        else:
                            self.password = value
                            self.focus = 2
                    model.text = ""
                    self.keyboard = None
                    self.editing = None
            return True
        if key in ("UP", "DOWN"):
            self.focus = max(0, min(2, self.focus + (-1 if key == "UP" else 1)))
            return True
        if key != "B":
            return False
        if self.focus < 2:
            self.error = ""
            self.editing = "email" if self.focus == 0 else "password"
            value = self.email if self.focus == 0 else self.password
            self.keyboard = CredentialKeyboard(value, 254 if self.focus == 0 else 128)
            return True
        email = self.email.strip()
        before, separator, after = email.partition("@")
        # The badge's ASCII keyboard does not need CPython-only str.isspace().
        if not before or not separator or not after or "@" in after or any(c in " \t\n\r\v\f" for c in email):
            self.error = "Check your email address."
            self.focus = 0
            return True
        if not self.password:
            self.error = "Enter your password."
            self.focus = 1
            return True
        if service.start_login(email, self.password):
            # Network work is queued, never awaited here. Drop UI references
            # immediately; the adapter releases its transient request on finish.
            self.clear()
            self.auth_state = "signing_in"
            self.error = ""
        else:
            self.error = "Unable to connect. Try again."
        return True

    def debug(self):
        # Values never enter virtual probes, logs or persisted debug state.
        return {"auth_state": self.auth_state, "editing": self.editing,
                "focus": self.focus, "busy": self.busy(),
                "typed_length": len(self.keyboard.text) if self.keyboard else 0}

    def softkeys(self):
        return ("", "", "") if self.busy() else ("PREV", "USE", "NEXT") if self.keyboard else ("", "OPEN", "")


class SignInView:
    def __init__(self, view):
        self.view = view
        self.cells = {}

    def draw(self, login):
        from view import PAPER, CARD, INK, MUTE, AMBER, WHITE
        view = self.view
        screen.pen = PAPER
        screen.clear()
        view.text("Home HQ", 12, 7, 220, 24, 21)
        view.text("SIGN IN", 238, 12, 66, 16, 12, MUTE, (image.RIGHT, image.TOP))
        view.rule(32)
        if login.busy():
            title = "Signing out…" if login.auth_state == "signing_out" else "Opening your home…" if login.waiting_home else "Signing in…"
            view.text(title, 14, 72, 290, 48, 30)
            subtitle = login.error or ("Clearing this badge's session." if login.auth_state == "signing_out" else "Connecting to your household.")
            view.text(subtitle, 15, 123, 286, 32, 17, MUTE)
            for index in range(3):
                screen.pen = AMBER if index == login.phase else color.rgb(214, 207, 192)
                screen.circle(27 + index * 17, 163, 4)
            view.footer(login)
            return
        if login.keyboard is not None:
            self.keyboard(login)
            view.footer(login)
            return
        view.text("Welcome home.", 13, 43, 290, 35, 29)
        view.text(login.error or "Use your household account.", 14, 78, 289, 17, 12, MUTE)
        for index, (label, value) in enumerate((("EMAIL", login.email), ("PASSWORD", login.password))):
            y = 99 + index * 41
            if login.focus == index:
                view.box(12, y, 291, 36, INK)
                view.box(14, y + 2, 287, 32, CARD, 5)
            else:
                view.box(12, y, 291, 36, CARD)
            view.text(label, 23, y + 3, 260, 13, 10, MUTE)
            if index and value:
                self.mask(value, 24, y + 24)
            else:
                view.text(value or ("you@example.com" if not index else "Enter password"),
                          23, y + 13, 263, 21, 17, INK if value else MUTE)
        selected = login.focus == 2
        view.box(12, 184, 291, 27, INK if selected else CARD)
        view.text("Sign in", 24, 186, 254, 23, 18, WHITE if selected else INK)
        view.footer(login)

    def mask(self, value, x, y):
        from view import INK
        screen.pen = INK
        for index in range(min(len(value), 32)):
            screen.circle(x + index * 7, y, 2)

    def keyboard(self, login):
        from view import PAPER, CARD, INK, MUTE, AMBER
        view = self.view
        model = login.keyboard
        board.publish(model.plane, model.upper)
        view.text("Email" if login.editing == "email" else "Password", 13, 43, 230, 27, 23)
        view.text(str(len(model.text)) + "/" + str(model.limit), 244, 48, 57, 17, 12, MUTE, (image.RIGHT, image.TOP))
        view.box(12, 78, 291, 31, CARD, 6)
        if login.editing == "password":
            self.mask(model.text, 24, 94)
        else:
            # Email remains recognizable while a long value stays within its
            # field. Password text never reaches this unmasked draw branch.
            view.text(model.text[-32:] or "Your email address", 23, 82, 271, 24, 18, INK if model.text else MUTE)
        layout = board.plane_layout(model.plane)
        cells = self.cells.get(model.plane)
        if cells is None:
            cells = tuple(tuple(((x * 320 + 10) // 20, ((x + w) * 320 + 10) // 20 - (x * 320 + 10) // 20) for x, w in row) for row in layout)
            self.cells[model.plane] = cells
        for row_index, row in enumerate(model.rows):
            y = 119 + row_index * 23
            for column, cell in enumerate(row):
                x, width = cells[row_index][column]
                selected = model.row == row_index and model.column == column
                view.box(x + 2, y, width - 4, 21, AMBER if selected else CARD, 3)
                view.text(board.label(cell), x + 2, y + 1, width - 4, 21, 14 if len(cell) > 1 else 18,
                          INK, (image.CENTER, image.TOP))
