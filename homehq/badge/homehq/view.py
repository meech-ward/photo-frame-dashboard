"""Native editorial layouts. Drawing reads state and never waits for a service."""

import ui
from model import PAGES, TITLES, ROUTINE_NAMES, ROUTINES, find, clock_text

PAPER = color.rgb(242, 238, 230)
CARD = color.rgb(251, 249, 244)
INK = color.rgb(17, 17, 17)
MUTE = color.rgb(105, 101, 93)
LINE = color.rgb(214, 207, 192)
WHITE = color.rgb(255, 255, 255)
GREEN = color.rgb(0, 163, 108)
AMBER = color.rgb(255, 176, 0)


def rgb(hex_color):
    try:
        return color.rgb(int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))
    except (TypeError, ValueError):
        return INK


class HomeView:
    def __init__(self, app_root):
        self.root = app_root
        # Bare font names search system locations, not an app's cwd. A standalone
        # export therefore supplies an explicit local outline and registers that
        # same object in Chrome's memo, avoiding a second cold font load.
        try:
            ui._FACES[ui.CHROME_FACE] = font.load(app_root + "/MonaSans-Medium.af")
        except OSError:
            pass
        self.chrome = ui.Chrome(fallback=font.smart, display_fallback=font.badgewaremax)
        self.face = self.chrome.font
        self.vector = bool(self.chrome.font_size)
        self._photo_path = None
        self._photo = None
        # Static rounded shapes are retained: a native shape allocates, and
        # reconstructing decorative geometry every frame adds no information.
        self.hero = shape.rounded_rectangle(10, 106, 294, 65, 9)
        self.row_shapes = {}
        self.icon_shapes = {}

    def clear_private_photo(self):
        # Accounts reuse the same two local slot paths. Removing their files
        # does not release a decoded image, and path equality could otherwise
        # display the previous household's pixels after a new sign-in.
        self._photo = None
        self._photo_path = None

    def text(self, value, x, y, width, height=22, size=17, ink=INK, align=None):
        screen.font = self.face
        screen.pen = ink
        screen.text(str(value), rect(x, y, width, height),
                    font_size=size if self.vector else 1,
                    overflow=image.ELLIPSES,
                    align=align or (image.LEFT, image.TOP))

    def box(self, x, y, w, h, pen=CARD, radius=7):
        key = (x, y, w, h, radius)
        obj = self.row_shapes.get(key)
        if obj is None:
            obj = shape.rounded_rectangle(x, y, w, h, radius)
            self.row_shapes[key] = obj
        screen.pen = pen
        screen.shape(obj)

    def rule(self, y):
        screen.pen = LINE
        screen.rectangle(10, y, 294, 1)

    def ring(self, x, y, done, total, accent, r=14):
        screen.pen = LINE
        screen.circle(x, y, r)
        screen.pen = PAPER
        screen.circle(x, y, r - 3)
        if total and done:
            screen.pen = accent
            screen.shape(shape.arc(x, y, r - 3, r, -90, -90 + 360 * min(done, total) / total))

    def tick(self, x, y, done, accent=GREEN):
        screen.pen = accent if done else LINE
        screen.rectangle(x, y, 17, 17)
        screen.pen = WHITE if done else CARD
        if done:
            screen.line(x + 4, y + 8, x + 7, y + 12)
            screen.line(x + 7, y + 12, x + 13, y + 4)
        else:
            screen.rectangle(x + 2, y + 2, 13, 13)

    def header(self, app):
        title = TITLES[app.page]
        if app.detail == "chores":
            title = app.person(app.person_id).get("name", "Chores")
        elif app.detail == "who":
            title = "Who did it?"
        elif app.detail == "routine":
            title = "Choose a routine"
        elif app.detail == "event":
            title = "Calendar"
        elif app.detail in ("device", "confirm"):
            title = "Home controls"
        elif app.detail == "agent":
            title = "Agent usage"
        elif app.detail in ("account", "logout"):
            title = "Your account"
        self.text(title, 10, 7, 205, 24, 21)
        state = app.status.get("state", "demo")
        pending = app.status.get("pending", 0)
        label = "SEND " + str(pending) if pending else state.upper()
        self.text(label, 235, 12, 69, 16, 12, GREEN if state == "live" else MUTE,
                  (image.RIGHT, image.TOP))
        self.rule(32)
        # A short seven-segment strip conveys section order without making a
        # second, tiny launcher rail compete with the content.
        if app.detail is None:
            for i in range(7):
                screen.pen = INK if i == app.page else LINE
                screen.rectangle(237 + i * 10, 29, 7, 2)

    def hints(self, app):
        rows = app.current_rows()
        if len(rows) > 1:
            # Chrome's white chevrons disappear on our cream pages. Keep its
            # measured physical key positions, with contrast for this surface.
            screen.pen = WHITE if PAGES[app.page] == "photos" and app.detail is None else MUTE
            x = screen.width - 5
            if app.index() > 0:
                y = self.chrome.scroll_y[0]
                screen.triangle(x - 2, y + 2, x + 2, y + 2, x, y - 2)
            if app.index() < len(rows) - 1:
                y = self.chrome.scroll_y[1]
                screen.triangle(x - 2, y - 2, x + 2, y - 2, x, y + 2)

    def icon(self, name, x, y, ink):
        if name in ("DONE", "GET", "USE", "YES"):
            name = "CHECK"
        elif name in ("ON", "OFF"):
            name = "POWER"
        key = (name, x, y)
        parts = self.icon_shapes.get(key)
        if parts is None:
            # A finite set of glyphs occupies three fixed button positions.
            # Cache native geometry on first use: reconstructing stroke paths
            # on every redraw would add garbage to an otherwise idle dashboard.
            flags = shape.ALIGN_CENTER | shape.PATH_OPEN | shape.JOIN_ROUND | shape.CAP_ROUND
            def path(points):
                return shape.custom([vec2(x + px, y + py) for px, py in points]).stroke(1.8, flags)
            if name == "PREV":
                parts = (path(((3, -6), (-3, 0), (3, 6))),)
            elif name == "NEXT":
                parts = (path(((-3, -6), (3, 0), (-3, 6))),)
            elif name == "BACK":
                parts = (path(((1, -5), (-4, 0), (1, 5))), path(((-4, 0), (7, 0))))
            elif name == "OPEN":
                parts = (path(((3, -6), (7, -6), (7, 6), (3, 6))),
                         path(((-7, 0), (2, 0))), path(((-2, -4), (2, 0), (-2, 4))))
            elif name == "OUT":
                parts = (path(((3, -6), (7, -6), (7, 6), (3, 6))),
                         path(((-6, 0), (3, 0))), path(((-2, -4), (-6, 0), (-2, 4))))
            elif name == "CHECK":
                parts = (path(((-6, 0), (-2, 4), (6, -4))),)
            elif name == "UNDO":
                parts = (path(((5, 4), (6, 1), (5, -3), (2, -5), (-2, -5), (-6, -1))),
                         path(((-6, -6), (-6, -1), (-1, -1))))
            elif name == "PLAY":
                parts = (shape.custom([vec2(x - 3, y - 6), vec2(x + 5, y), vec2(x - 3, y + 6)]),)
            elif name == "PAUSE":
                parts = (shape.rectangle(x - 5, y - 5, 3, 10), shape.rectangle(x + 2, y - 5, 3, 10))
            elif name == "TIME":
                parts = (shape.circle(x, y, 6.5).stroke(1.6, shape.ALIGN_CENTER),
                         path(((0, -4), (0, 0), (3, 2))))
            elif name == "POWER":
                parts = (shape.arc(x, y, 4.6, 6.3, -50, 230), path(((0, -7), (0, -1))))
            elif name in ("LOCK", "UNLOCK"):
                shackle = ((-3, -1), (-3, -5), (-1, -7), (2, -7), (4, -5), (4, -1)) if name == "LOCK" else ((-2, -1), (-2, -5), (0, -7), (3, -7), (5, -5), (5, -3))
                parts = (shape.rounded_rectangle(x - 5, y - 1, 10, 8, 1.5).stroke(1.5, shape.ALIGN_CENTER),
                         path(shackle))
            elif name in ("GARAGE_OPEN", "GARAGE_CLOSE"):
                direction = -1 if name == "GARAGE_OPEN" else 1
                parts = (path(((-6, 6), (-6, -6), (6, -6), (6, 6))),
                         path(((-3, 0), (0, direction * 3), (3, 0))),
                         path(((0, direction * 3), (0, -direction * 4))))
            else:
                parts = ()
            self.icon_shapes[key] = parts
        screen.pen = ink
        for part in parts:
            screen.shape(part)

    def footer(self, app):
        # Icons sit above A/B/C, not in equal-width thirds: the measured centres
        # are 56/147/253 px at HIRES. Reuse Chrome's geometry without changing
        # the shared text footer used by the rest of the badge.
        top, height = self.chrome.bar_y, self.chrome.bar_h
        screen.pen = PAPER
        screen.rectangle(0, top, screen.width, height)
        screen.pen = LINE
        screen.rectangle(10, top, 294, 1)
        labels = app.softkeys()
        y = top + height // 2
        for index, label in enumerate(labels):
            if not label:
                continue
            x = self.chrome.softkey_x[index]
            name = label
            if index == 1 and app.detail == "device":
                device = find(app.rows("devices"), app.device_id) or {}
                if device.get("type") == "garage":
                    name = "GARAGE_" + label
            ink = INK
            if index == 1:
                screen.pen = AMBER if app.detail in ("confirm", "logout") else INK
                screen.circle(x, y, 10.5)
                ink = INK if app.detail in ("confirm", "logout") else PAPER
            self.icon(name, x, y, ink)

    def draw(self, app, photo_path=None):
        screen.pen = PAPER
        screen.clear()
        if PAGES[app.page] == "photos" and app.detail is None:
            self.photos(app, photo_path)
        else:
            self.header(app)
            if app.detail == "event":
                self.event(app)
            elif app.detail == "chores":
                self.chores_detail(app)
            elif app.detail in ("who", "routine"):
                self.picker(app)
            elif app.detail in ("device", "confirm"):
                self.device(app)
            elif app.detail == "agent":
                self.agent(app)
            elif app.detail in ("account", "logout"):
                self.account(app)
            else:
                getattr(self, PAGES[app.page])(app)
            self.hints(app)
        if app.notice:
            self.box(18, 184, 283, 27, INK, 6)
            self.text(app.notice, 25, 188, 269, 21, 15, WHITE, (image.CENTER, image.TOP))
        self.footer(app)

    def today(self, app):
        # Native font bounds include the em square, not only visible capitals.
        # A 50px box clipped the bottom of a 58pt clock in the first real render.
        self.text(clock_text(app.minute), 8, 25, 178, 64, 62)
        self.text("PM" if app.minute >= 720 else "AM", 166, 49, 27, 20, 15)
        self.text(app.date_label, 12, 87, 187, 18, 15, MUTE)
        weather = app.data.get("weather") or {}
        self.text(str(weather.get("temp", "--")) + "°", 214, 37, 90, 38, 38,
                  align=(image.RIGHT, image.TOP))
        if weather.get("sample"):
            self.text("SAMPLE", 205, 73, 100, 12, 10, MUTE, (image.RIGHT, image.TOP))
        self.text(weather.get("summary", "Weather sample"), 205, 86, 100, 18, 13, MUTE,
                  (image.RIGHT, image.TOP))
        ev = app.next_event()
        person = app.person((ev.get("people") or ["any"])[0]) if ev else app.person("any")
        accent = rgb(person.get("color", "#111111"))
        light = person.get("color") == "#FFB000"
        ink = INK if light else WHITE
        screen.pen = accent
        screen.shape(self.hero)
        if ev:
            mins = app.event_gap(ev)
            self.text("NEXT · " + person.get("name", "Family").upper(), 20, 112, 202, 14, 12, ink)
            self.text(ev.get("title", "Next event"), 20, 124, 205, 29, 28, ink)
            travel = ev.get("travel", 0)
            leave = max(0, mins - travel)
            sub = "Leave now" if travel and not leave else "Leave in {} min".format(leave) if travel else app.time_text(ev.get("start", 0), ev.get("start_offset_minutes"))
            self.text(sub, 20, 152, 212, 17, 13, ink)
            # Morning events can be hundreds of minutes away; the narrow hero
            # must show the complete count instead of an ellipsis.
            size = 39 if mins < 100 else 30 if mins < 1000 else 22
            # The native outline needs its full em height: a 32px box cropped
            # the bottom of 39pt "75" on glass. Start higher to keep MIN clear.
            self.text(str(mins), 239, 108, 56, 42, size, ink, (image.RIGHT, image.TOP))
            self.text("MIN", 251, 147, 42, 14, 12, ink, (image.RIGHT, image.TOP))
        else:
            self.text("Enjoy the quiet.", 21, 117, 270, 35, 28, WHITE)
            self.text("Nothing else scheduled today", 21, 149, 270, 16, 14, WHITE)
        for i, p in enumerate(app.rows("people")[:4]):
            x = 12 + i * 74
            self.text(p.get("name", ""), x, 174, 71, 20, 15)
            status = "Home" if p.get("home") else "ETA {}m".format(p["eta"]) if p.get("eta") else "Away"
            self.text(status, x, 193, 71, 16, 13, MUTE)
            screen.pen = rgb(p.get("color", "#111111"))
            screen.rectangle(x, 210, 62, 3)

    def row_window(self, app, height=37, top=62, count=4):
        rows, index = app.current_rows(), app.index()
        start = min(max(0, index - count + 1), max(0, len(rows) - count))
        return [(row, top + (i - start) * height, i == index) for i, row in enumerate(rows[start:start + count], start)]

    def focused_row(self, y, h, selected):
        if selected:
            self.box(9, y - 2, 295, h, INK)
            self.box(11, y, 291, h - 4, CARD, 5)
        else:
            self.box(11, y, 291, h - 4)

    def calendar(self, app):
        selected = app.selected()
        day = app.day_text(selected["start"], selected.get("start_offset_minutes")) if selected else app.date_label
        self.text(day + " · WEEK AHEAD", 12, 41, 287, 18, 14, MUTE)
        for row, y, selected in self.row_window(app):
            self.focused_row(y, 37, selected)
            p = app.person((row.get("people") or ["any"])[0])
            screen.pen = rgb(p.get("color", "#111111"))
            screen.rectangle(16, y + 5, 3, 24)
            at = "DAY" if row.get("all_day") else app.time_text(row.get("start", 0), row.get("start_offset_minutes"))
            self.text(at, 23, y + 6, 53, 24, 16)
            self.text(row.get("title", ""), 82, y + 1, 207, 22, 18)
            self.text(app.day_text(row.get("start", 0), row.get("start_offset_minutes")) + " · " + " + ".join(app.person(pid).get("name", "") for pid in row.get("people", [])),
                      82, y + 19, 208, 14, 12, MUTE)
        if not app.current_rows():
            self.empty("A clear calendar.", "Nothing scheduled this week.")

    def event(self, app):
        row = find(app.rows("events"), app.event_id)
        if not row:
            self.empty("Event removed", "Your calendar has changed.")
            return
        p = app.person((row.get("people") or ["any"])[0])
        accent = rgb(p.get("color", "#111111"))
        screen.pen = accent
        screen.rectangle(12, 45, 5, 47)
        self.text(row.get("title", ""), 26, 44, 275, 52, 28)
        at = "All day" if row.get("all_day") else app.time_text(row.get("start", 0), row.get("start_offset_minutes")) + " – " + app.time_text(row.get("end", 0), row.get("end_offset_minutes"))
        self.text(app.day_text(row.get("start", 0), row.get("start_offset_minutes")) + " · " + at, 15, 101, 285, 23, 15)
        self.text(" + ".join(app.person(pid).get("name", "") for pid in row.get("people", [])), 15, 127, 285, 22, 17, MUTE)
        self.text(row.get("loc", ""), 15, 153, 284, 21, 17)
        self.rule(178)
        self.text(row.get("notes", "No extra notes."), 15, 185, 285, 29, 14, MUTE)

    def chores(self, app):
        self.text(ROUTINE_NAMES[ROUTINES.index(app.routine)], 12, 40, 220, 21, 18, MUTE)
        rows = app.chores()
        done = sum(1 for c in rows if app.done("chores", c))
        self.text("{}/{}".format(done, len(rows)), 240, 40, 59, 21, 18, INK, (image.RIGHT, image.TOP))
        for person, y, selected in self.row_window(app, 29, 65, 5):
            self.focused_row(y, 29, selected)
            accent = rgb(person.get("color", "#111111"))
            rows = app.chores(person.get("id"))
            done = sum(1 for c in rows if app.done("chores", c))
            self.ring(30, y + 12, done, len(rows), accent, 10)
            self.text(person.get("name", ""), 47, y + 3, 190, 23, 18)
            self.text("{}/{}".format(done, len(rows)), 244, y + 3, 45, 22, 17, MUTE, (image.RIGHT, image.TOP))

    def chores_detail(self, app):
        person = app.person(app.person_id)
        accent = rgb(person.get("color", "#111111"))
        self.text(ROUTINE_NAMES[ROUTINES.index(app.routine)], 12, 41, 246, 19, 15, MUTE)
        rows = app.current_rows()
        done = sum(1 for row in rows if app.done("chores", row))
        self.text("{}/{}".format(done, len(rows)), 256, 39, 44, 23, 18, accent, (image.RIGHT, image.TOP))
        for row, y, selected in self.row_window(app, 36, 67, 4):
            self.focused_row(y, 36, selected)
            self.tick(19, y + 7, app.done("chores", row), accent)
            stars = row.get("stars", 0)
            self.text(row.get("title", ""), 47, y + 5, 210 if stars else 233, 24, 18)
            if stars:
                screen.pen = accent
                screen.shape(shape.star(269, y + 17, 5, 5, 2.2))
                self.text(stars, 280, y + 8, 15, 20, 14, MUTE)
        if not rows:
            self.empty("All clear.", "No chores in this routine.")

    def picker(self, app):
        for row, y, selected in self.row_window(app, 33, 58, 4):
            self.focused_row(y, 33, selected)
            self.text(row.get("name", ""), 23, y + 5, 271, 23, 20)

    def shopping(self, app):
        items = app.groceries()
        left = sum(1 for row in items if not app.done("shopping", row))
        self.text("{} things to pick up".format(left), 12, 41, 286, 19, 15, MUTE)
        for row, y, selected in self.row_window(app, 36, 64, 4):
            self.focused_row(y, 36, selected)
            self.tick(19, y + 8, app.done("shopping", row), INK)
            self.text(row.get("name", ""), 46, y + 1, 213, 22, 18)
            qty = row.get("quantity", row.get("qty", 1))
            self.text("×" + str(qty), 266, y + 4, 27, 19, 15, MUTE, (image.RIGHT, image.TOP))
            sub = row.get("store", "") + " · " + row.get("category", row.get("cat", ""))
            self.text(sub, 46, y + 18, 230, 14, 13, MUTE)
        if not items:
            self.empty("Nothing to buy.", "Your shopping list is clear.")

    def photos(self, app, photo_path):
        row = app.selected()
        if not row:
            self.header(app)
            self.empty("Your next memory.", "Add a photo in the companion.")
            return
        path = photo_path or (self.root + "/" + row.get("asset", "assets/photo-coast.png"))
        if path != self._photo_path:
            self._photo_path = path
            self._photo = None
            try:
                self._photo = image.load(path)
            except (OSError, ValueError):
                pass
        if self._photo:
            # File decode is paid only on a photo change. The runtime resamples
            # this native blit; Python never loops over screen pixels.
            # The persistent bar covers the lowest 26px; preserve the photo's
            # 320x240 aspect instead of squeezing it into the remaining height.
            screen.blit(self._photo, rect(0, 0, 320, 240))
        else:
            screen.pen = color.rgb(25, 64, 64)
            screen.rectangle(0, 0, 320, 214)
            self.text("Photo unavailable", 19, 76, 286, 35, 26, WHITE)
            self.text("Other screens still work.", 19, 115, 286, 25, 17, WHITE)
        screen.pen = color.rgb(17, 17, 17, 170)
        screen.rectangle(0, 169, 320, 45)
        self.text(row.get("caption", "A family memory"), 13, 174, 252, 17, 13, WHITE)
        self.text(row.get("place", ""), 13, 191, 274, 24, 20, WHITE)
        self.text(str(app.index() + 1) + "/" + str(len(app.current_rows())), 252, 12, 53, 19, 14, WHITE,
                  (image.RIGHT, image.TOP))
        if path.startswith(self.root + "/"):
            self.box(10, 10, 106, 24, color.rgb(17, 17, 17, 170), 4)
            self.text("SAMPLE ART", 17, 12, 92, 20, 15, WHITE)
        self.hints(app)

    def home(self, app):
        status = app.data.get("home_status") or {}
        self.text("SAMPLE HOME", 12, 40, 184, 18, 13, MUTE)
        self.text(str(status.get("temperature", 20.5)) + "° inside", 12, 59, 285, 30, 30)
        for row, y, selected in self.row_window(app, 30, 94, 4):
            self.focused_row(y, 30, selected)
            self.text(row.get("name", ""), 21, y + 4, 214, 23, 17)
            if row.get("type") == "account":
                self.text("Open", 235, y + 5, 60, 21, 15, MUTE, (image.RIGHT, image.TOP))
                continue
            state = row.get("state") or row
            if not isinstance(state, dict):
                state = row
            dtype = row.get("type")
            value = "Locked" if state.get("locked", True) else "Open" if dtype == "lock" else ""
            if dtype == "garage":
                value = "Closed" if state.get("state", "closed") == "closed" else "Open"
            elif dtype != "lock":
                value = "On" if state.get("on", False) else "Off"
            self.text(value, 235, y + 5, 60, 21, 15, GREEN if value in ("On", "Locked", "Closed") else MUTE,
                      (image.RIGHT, image.TOP))
        if not app.current_rows():
            self.text("{} lights on".format(status.get("lights_on", 0)), 14, 105, 284, 30, 25)
            self.text("All locked" if status.get("locked") else "Check the doors", 14, 146, 284, 29, 23)

    def device(self, app):
        row = find(app.rows("devices"), app.device_id)
        if not row:
            self.empty("Device removed", "Your home list has changed.")
            return
        self.text("SAMPLE · " + row.get("room", "Home").upper(), 13, 42, 285, 20, 14, MUTE)
        self.text(row.get("name", ""), 13, 70, 284, 62, 32)
        state = row.get("state") or row
        if not isinstance(state, dict):
            state = row
        dtype = row.get("type")
        if dtype == "lock":
            current = "Locked" if state.get("locked", True) else "Unlocked"
            action = "Unlock" if state.get("locked", True) else "Lock"
        elif dtype == "garage":
            current = "Closed" if state.get("state", "closed") == "closed" else "Open"
            action = "Open" if state.get("state", "closed") == "closed" else "Close"
        else:
            current = "On" if state.get("on", False) else "Off"
            action = "Switch off" if state.get("on", False) else "Switch on"
        self.text("Currently " + current.lower(), 14, 126, 284, 21, 15, MUTE)
        if app.detail == "confirm":
            self.box(12, 151, 290, 54, INK)
            self.text(action + " " + row.get("name", "this device").lower() + "?", 23, 158, 269, 25, 20, WHITE)
            # A critical confirmation names its operation and physical keys in
            # the content; an icon-only footer must not make consent ambiguous.
            self.text("B confirms · A cancels", 23, 183, 269, 17, 14, WHITE)
        else:
            self.text(action, 14, 156, 284, 29, 23)
            self.text("Sample state syncs to your project.", 14, 186, 284, 23, 14, MUTE)

    def account(self, app):
        viewer = app.data.get("viewer") or {}
        person = find(app.rows("people"), viewer.get("person_id")) or {}
        self.text("SIGNED IN", 14, 44, 286, 20, 13, MUTE)
        self.text(person.get("name", "Home owner"), 14, 76, 286, 45, 33)
        if app.detail == "logout":
            self.box(12, 145, 290, 60, INK)
            pending = app.status.get("pending", 0)
            self.text("Save changes first." if pending else "Sign out of Home HQ?", 23, 153, 269, 26, 21, WHITE)
            self.text("Connect to save " + str(pending) + " pending edits." if pending else "B signs out · A cancels", 23, 181, 269, 20, 14, WHITE)
        else:
            self.text("Your household stays in sync.", 14, 133, 286, 25, 17, MUTE)
            self.text("Sign out to use another account.", 14, 176, 286, 24, 17)

    def agents(self, app):
        self.text("SAMPLE USAGE · % USED", 12, 40, 286, 18, 13, MUTE)
        for row, y, selected in self.row_window(app, 35, 64, 4):
            self.focused_row(y, 35, selected)
            accent = rgb(row.get("color", "#111111"))
            self.text(row.get("name", ""), 20, y + 4, 113, 25, 19)
            meters = row.get("meters") or []
            used = meters[0].get("used", 0) if meters else 0
            screen.pen = LINE
            screen.rectangle(138, y + 13, 109, 6)
            screen.pen = accent
            screen.rectangle(138, y + 13, int(109 * max(0, min(used, 100)) / 100), 6)
            self.text(str(used) + "%", 252, y + 5, 44, 22, 17, INK, (image.RIGHT, image.TOP))
        if not app.current_rows():
            self.empty("A little breathing room.", "No usage cards configured.")

    def agent(self, app):
        row = find(app.rows("agents"), app.agent_id)
        if not row:
            self.empty("Usage card removed", "Your project has changed.")
            return
        accent = rgb(row.get("color", "#111111"))
        self.text(row.get("name", ""), 13, 42, 211, 38, 32)
        self.text("SAMPLE", 236, 52, 66, 18, 12, MUTE, (image.RIGHT, image.TOP))
        for i, meter in enumerate((row.get("meters") or [])[:2]):
            y = 84 + i * 55
            used = max(0, min(meter.get("used", 0), 100))
            self.text(meter.get("label", "Usage"), 14, y, 213, 23, 17)
            self.text(str(used) + "%", 250, y, 51, 26, 24, accent, (image.RIGHT, image.TOP))
            screen.pen = LINE
            screen.rectangle(15, y + 25, 285, 7)
            screen.pen = accent
            screen.rectangle(15, y + 25, int(285 * used / 100), 7)
            mins = meter.get("reset_minutes", meter.get("left", 0))
            reset = "{}m".format(mins) if mins < 60 else "{}h {}m".format(mins // 60, mins % 60) if mins < 1440 else "{}d {}h".format(mins // 1440, (mins % 1440) // 60)
            self.text("Reset in " + reset, 15, y + 37, 284, 17, 13, MUTE)
        values = row.get("week") or []
        if values:
            peak = max(max(values), 0.01)
            screen.pen = accent
            for i, value in enumerate(values[:7]):
                h = max(2, int(value / peak * 17))
                screen.rectangle(15 + i * 19, 211 - h, 13, h)
            self.text("7 DAYS", 173, 197, 124, 16, 12, MUTE, (image.RIGHT, image.TOP))

    def empty(self, title, subtitle):
        self.text(title, 14, 81, 285, 55, 30)
        self.text(subtitle, 15, 145, 283, 39, 17, MUTE)
