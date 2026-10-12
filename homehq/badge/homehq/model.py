"""Pure Home HQ interaction model: button decisions never own sockets or files."""

PAGES = ("today", "calendar", "chores", "shopping", "photos", "home", "agents")
TITLES = ("Today", "Calendar", "Chores", "Shopping", "Photos", "Home", "Agents")
ROUTINES = ("morning", "after", "evening")
ROUTINE_NAMES = ("Morning", "After school", "Evening")


def find(rows, row_id):
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None


def clock_text(minute):
    hour = (minute // 60) % 24
    return "{}:{:02d}".format(hour % 12 or 12, minute % 60)


def parse_minute(value):
    """The wire can carry HH:MM or a timestamp; only display uses local minutes."""
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return 0
    stamp = value.split("T")[-1]
    try:
        return int(stamp[0:2]) * 60 + int(stamp[3:5])
    except (ValueError, IndexError):
        return 0


def row_done(row):
    return bool(row.get("done", row.get("completed", False)))


def civil_date(days):
    # Gregorian conversion is integer-only so calendar labels need neither the
    # platform epoch choice nor an RTC/file/network call in the pure model.
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + (3 if mp < 10 else -9)
    return year + (1 if month <= 2 else 0), month, day


class HomeHQ:
    def __init__(self, snapshot, member_id=None):
        self.data = snapshot
        self.page = 0
        self.detail = None
        self.focus = {}
        self.viewer_person_id = self._viewer_person(snapshot)
        # A family can give each badge a preferred chore card while keeping
        # Today and the shared household intact. Normal ID alignment handles
        # a removed member; this is a navigation preference, not authorization.
        preferred = self.viewer_person_id or member_id
        if isinstance(preferred, str) and preferred:
            self.focus["chores"] = preferred
        self.minute = 15 * 60 + 18
        self.date_label = "FRI · OCT 2"
        self.routine = "after"
        self.person_id = None
        self.event_id = None
        self.device_id = None
        self.agent_id = None
        self.photo_playing = True
        self.photo_elapsed = 0
        self.notice = ""
        self.notice_until = 0
        self.status = {"state": "demo", "pending": 0}
        # Desired values survive an old snapshot until the service supplies its
        # durable overlay. A toggle would flip twice after a retry/reconnect.
        self.optimistic = {}
        self.epoch = snapshot.get("server_time")
        self._clock_elapsed = 0
        if self.epoch:
            self.set_time(self.epoch)
        self._align()

    @staticmethod
    def _viewer_person(snapshot):
        viewer = snapshot.get("viewer")
        person_id = viewer.get("person_id") if isinstance(viewer, dict) else None
        return person_id if isinstance(person_id, str) and find(snapshot.get("people") or [], person_id) else None

    def rows(self, name):
        return self.data.get(name) or []

    def people(self):
        return self.rows("people") + [{"id": "any", "name": "Anyone", "color": "#111111"}]

    def person(self, person_id):
        return find(self.people(), person_id) or {"id": "any", "name": "Family", "color": "#111111"}

    def events(self):
        if self.epoch:
            day = (self.epoch + self.offset() * 60) // 86400
            return [row for row in self.rows("events")
                    if (row.get("start", 0) + row.get("start_offset_minutes", self.offset()) * 60) // 86400 == day
                    or (row.get("all_day") and row.get("start", 0) <= self.epoch < row.get("end", 0))]
        return [row for row in self.rows("events") if row.get("day", 0) == 0]

    def offset(self):
        return (self.data.get("home") or {}).get("utc_offset_minutes", 0)

    def event_minute(self, event):
        value = event.get("start", event.get("start_min", 0))
        if isinstance(value, int) and value > 86400:
            return ((value + event.get("start_offset_minutes", self.offset()) * 60) // 60) % 1440
        return parse_minute(value)

    def time_text(self, stamp, offset=None):
        offset = self.offset() if offset is None else offset
        return clock_text(((stamp + offset * 60) // 60) % 1440) if isinstance(stamp, int) and stamp > 86400 else clock_text(parse_minute(stamp))

    def day_text(self, stamp, offset=None):
        days = (stamp + (self.offset() if offset is None else offset) * 60) // 86400
        year, month, day = civil_date(days)
        weekday = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[(days + 3) % 7]
        return "{} · {}/{}".format(weekday, month, day)

    def set_time(self, epoch):
        self.epoch = epoch
        local = epoch + self.offset() * 60
        self.minute = (local // 60) % 1440
        days = local // 86400
        year, month, day = civil_date(days)
        weekday = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[(days + 3) % 7]
        month_name = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")[month - 1]
        self.date_label = "{} · {} {}".format(weekday, month_name, day)
        hour = self.minute // 60
        self.routine = "morning" if hour < 11 else "after" if hour < 17 else "evening"

    def next_event(self):
        future = [row for row in self.events() if not row.get("all_day", row.get("allDay", False))
                  and (row.get("start", 0) >= self.epoch if self.epoch and row.get("start", 0) > 86400
                       else self.event_minute(row) >= self.minute)]
        return min(future, key=lambda row: row.get("start", 0)) if future else None

    def event_gap(self, row):
        # UTC intervals stay correct during the repeated hour when DST ends;
        # subtracting local clock labels would select/count down the wrong event.
        if self.epoch and row.get("start", 0) > 86400:
            return max(0, (row["start"] - self.epoch + 59) // 60)
        return max(0, self.event_minute(row) - self.minute)

    def chores(self, person_id=None):
        return [row for row in self.rows("chores")
                if row.get("routine", row.get("r", "after")) == self.routine
                and (person_id is None or row.get("person_id", row.get("who")) == person_id)]

    def groceries(self):
        return self.rows("groceries") or self.rows("shopping")

    def current_rows(self):
        if self.detail == "chores":
            return self.chores(self.person_id)
        if self.detail == "who":
            return self.rows("people")
        if self.detail == "routine":
            return [{"id": key, "name": ROUTINE_NAMES[index]} for index, key in enumerate(ROUTINES)]
        if self.detail:
            return []
        page = PAGES[self.page]
        if page == "calendar":
            # The snapshot contains a week. UP/DOWN can reach tomorrow without
            # introducing another physical-button mode just to choose a day.
            return self.rows("events")
        if page == "chores":
            return self.people()
        if page == "shopping":
            return self.groceries()
        if page == "photos":
            return self.rows("photos")
        if page == "home":
            rows = self.rows("devices")
            if isinstance(self.data.get("viewer"), dict):
                rows = rows + [{"id": "__account", "name": "Your account", "type": "account"}]
            return rows
        if page == "agents":
            return self.rows("agents")
        return []

    def focus_key(self):
        return (self.detail or PAGES[self.page]) + (":" + str(self.person_id) if self.detail == "chores" else "")

    def selected(self):
        rows = self.current_rows()
        return find(rows, self.focus.get(self.focus_key())) if rows else None

    def index(self):
        row_id = self.focus.get(self.focus_key())
        for index, row in enumerate(self.current_rows()):
            if row.get("id") == row_id:
                return index
        return 0

    def _align(self):
        rows = self.current_rows()
        key = self.focus_key()
        if rows and find(rows, self.focus.get(key)) is None:
            upcoming = self.next_event() if key == "calendar" else None
            self.focus[key] = upcoming.get("id") if upcoming else rows[0].get("id")

    def replace(self, snapshot):
        previous_time = self.data.get("server_time")
        self.data = snapshot
        person_id = self._viewer_person(snapshot)
        if person_id != self.viewer_person_id:
            # Only the server snapshot can identify the logged-in member.
            # Manual offline focus remains a preference, never attribution.
            self.viewer_person_id = person_id
            if person_id:
                self.focus["chores"] = person_id
        if snapshot.get("server_time") and snapshot["server_time"] != previous_time:
            routine = self.routine
            # The offline scenario starts at 3:18. Live data must replace that
            # clock so the calendar describes the owner's actual day.
            self.set_time(snapshot["server_time"])
            if self.detail in ("chores", "who", "routine"):
                self.routine = routine
        # Focus is an object identity rather than an index: a newly received row
        # above the selected chore must not redirect the next B press.
        for (table, row_id), desired in list(self.optimistic.items()):
            rows = self.groceries() if table == "shopping" else self.rows(table)
            row = find(rows, row_id)
            if row is None or row_done(row) == desired:
                del self.optimistic[(table, row_id)]
        self._align()

    def done(self, table, row):
        return self.optimistic.get((table, row.get("id")), row_done(row))

    def move(self, delta):
        rows = self.current_rows()
        if rows:
            index = max(0, min(len(rows) - 1, self.index() + delta))
            self.focus[self.focus_key()] = rows[index].get("id")

    def tick(self, elapsed_ms):
        changed = False
        self._clock_elapsed += elapsed_ms
        if self.epoch and self._clock_elapsed >= 1000:
            seconds = self._clock_elapsed // 1000
            self._clock_elapsed %= 1000
            old_minute = self.minute
            # Explicit routine choices are browsing state. Advancing the clock
            # must not drag an open chore list into another routine.
            routine = self.routine
            self.set_time(self.epoch + seconds)
            if self.detail in ("chores", "who", "routine"):
                self.routine = routine
            changed = self.minute != old_minute
        if PAGES[self.page] == "photos" and self.detail is None and self.photo_playing:
            self.photo_elapsed += elapsed_ms
            if self.photo_elapsed >= 12000:
                self.photo_elapsed = 0
                rows = self.current_rows()
                if rows:
                    self.focus[self.focus_key()] = rows[(self.index() + 1) % len(rows)].get("id")
                    return True
        return changed

    def _complete(self, table, row, by=None):
        desired = not self.done(table, row)
        self.optimistic[(table, row.get("id"))] = desired
        self.notice = "Done" if desired else "Undone"
        command = {"kind": "chore" if table == "chores" else "shopping", "id": row.get("id"),
                   "done": desired, "version": row.get("version", 1)}
        if by is not None:
            command["done_by"] = by
        return command

    def reject(self, command):
        table = {"chore": "chores", "shopping": "shopping"}.get(command.get("kind"))
        if table:
            self.optimistic.pop((table, command.get("id")), None)
        self.notice = ""

    def press(self, key):
        self.notice = ""
        if key in ("UP", "DOWN"):
            self.move(-1 if key == "UP" else 1)
            self.photo_elapsed = 0
            return None
        if self.detail:
            return self._detail_press(key)
        if key in ("A", "C"):
            self.page = (self.page + (-1 if key == "A" else 1)) % len(PAGES)
            self.photo_elapsed = 0
            self._align()
            return None
        if key != "B":
            return None
        page = PAGES[self.page]
        row = self.selected()
        if page == "today":
            event = self.next_event()
            if event:
                self.event_id, self.detail = event.get("id"), "event"
        elif page == "calendar" and row:
            self.event_id, self.detail = row.get("id"), "event"
        elif page == "chores" and row:
            self.person_id, self.detail = row.get("id"), "chores"
            self._align()
        elif page == "shopping" and row:
            return self._complete("shopping", row)
        elif page == "photos":
            self.photo_playing = not self.photo_playing
        elif page == "home" and row:
            if row.get("type") == "account":
                self.detail = "account"
            else:
                self.device_id, self.detail = row.get("id"), "device"
        elif page == "agents" and row:
            self.agent_id, self.detail = row.get("id"), "agent"
        return None

    def _detail_press(self, key):
        if key == "A":
            if self.detail in ("who", "routine"):
                self.detail = "chores"
            elif self.detail == "confirm":
                self.detail = "device"
            elif self.detail == "logout":
                self.detail = "account"
            else:
                self.detail = None
            self._align()
            return None
        if self.detail == "chores" and key == "C":
            self.detail = "routine"
            self._align()
        elif self.detail == "chores" and key == "B":
            row = self.selected()
            if row:
                if self.person_id == "any" and not self.done("chores", row):
                    if self.viewer_person_id:
                        return self._complete("chores", row, self.viewer_person_id)
                    else:
                        self.pending_chore = row.get("id")
                        self.detail = "who"
                        self._align()
                else:
                    return self._complete("chores", row)
        elif self.detail == "routine" and key == "B":
            row = self.selected()
            if row:
                self.routine = row.get("id")
                self.detail = "chores"
                self._align()
        elif self.detail == "who" and key == "B":
            row = self.selected()
            chore = find(self.rows("chores"), self.pending_chore)
            self.detail = "chores"
            self._align()
            if row and chore:
                return self._complete("chores", chore, row.get("id"))
        elif self.detail == "device" and key == "B":
            row = find(self.rows("devices"), self.device_id)
            if row:
                if row.get("type") in ("lock", "garage"):
                    self.detail = "confirm"
                else:
                    return self._device_command(row)
        elif self.detail == "confirm" and key == "B":
            row = find(self.rows("devices"), self.device_id)
            self.detail = "device"
            if row:
                return self._device_command(row)
        elif self.detail == "account" and key == "B":
            self.detail = "logout"
        elif self.detail == "logout" and key == "B":
            if not self.status.get("pending", 0):
                return {"kind": "logout"}
            self.notice = "Connect to save changes first."
        return None

    def _device_command(self, row):
        state = row.get("state")
        if isinstance(state, dict):
            state = dict(state)
        else:
            state = {"on": row.get("on", False), "locked": row.get("locked", True), "state": row.get("state", "closed")}
        if row.get("type") == "lock":
            state["locked"] = not state.get("locked", True)
        elif row.get("type") == "garage":
            state["state"] = "open" if state.get("state") == "closed" else "closed"
        else:
            state["on"] = not state.get("on", False)
        # Only the desired field crosses the wire. This keeps lamp actions from
        # accidentally overwriting an unrelated lock/level field on a retry.
        if row.get("type") == "lock":
            desired = {"locked": state["locked"]}
        elif row.get("type") == "garage":
            desired = {"state": state["state"]}
        else:
            desired = {"on": state["on"]}
        return {"kind": "device", "id": row.get("id"), "state": desired, "version": row.get("version", 1)}

    def softkeys(self):
        row = self.selected()
        if self.detail == "chores":
            label = "UNDO" if row and self.done("chores", row) else "DONE" if row else ""
            return ("BACK", label, "TIME")
        if self.detail == "who":
            return ("BACK", "USE", "")
        if self.detail == "routine":
            return ("BACK", "USE", "")
        if self.detail == "device":
            device = find(self.rows("devices"), self.device_id)
            state = (device or {}).get("state")
            if not isinstance(state, dict):
                state = device or {}
            dtype = (device or {}).get("type")
            if dtype == "lock":
                label = "UNLOCK" if state.get("locked", True) else "LOCK"
            elif dtype == "garage":
                label = "OPEN" if state.get("state", "closed") == "closed" else "CLOSE"
            else:
                label = "OFF" if state.get("on") else "ON"
            return ("BACK", label if device else "", "")
        if self.detail == "confirm":
            return ("BACK", "YES", "")
        if self.detail == "account":
            return ("BACK", "OUT", "")
        if self.detail == "logout":
            return ("BACK", "" if self.status.get("pending", 0) else "YES", "")
        if self.detail:
            return ("BACK", "", "")
        page = PAGES[self.page]
        label = "OPEN"
        if page == "today" and self.next_event() is None:
            label = ""
        elif page == "shopping":
            label = "UNDO" if row and self.done("shopping", row) else "GET" if row else ""
        elif page == "photos":
            label = ("PAUSE" if self.photo_playing else "PLAY") if row else ""
        elif page != "today" and row is None:
            label = ""
        return ("PREV", label, "NEXT")

    def debug(self):
        row = self.selected()
        return {"page": PAGES[self.page], "detail": self.detail, "focus": row.get("id") if row else None,
                "routine": self.routine, "keys": self.softkeys(), "status": self.status,
                "optimistic": len(self.optimistic), "notice": self.notice}
