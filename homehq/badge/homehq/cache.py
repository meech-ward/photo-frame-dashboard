"""One bounded atomic checkpoint for cached data and desired-value writes."""
import json
import os

MAX_BYTES = 65536
MAX_PENDING = 32


def empty_snapshot():
    # A configured signed-out app cannot reveal the previous person's family
    # cache or disguise an unconnected sample as that person's household.
    return {"schema_version": 1, "revision": 0, "home": {"title": "Home HQ", "timezone": "UTC"},
            "viewer": {"user_id": None, "person_id": None}, "people": [], "events": [],
            "chores": [], "shopping": [], "photos": [], "agents": [], "devices": []}


def read(path, default=None):
    try:
        if os.stat(path)[6] > MAX_BYTES:
            return default
        with open(path) as source:
            return json.load(source)
    except (OSError, ValueError, TypeError):
        return default


def write(path, value):
    payload = json.dumps(value)
    if len(payload.encode()) > MAX_BYTES:
        raise ValueError("Home HQ checkpoint exceeds its memory/storage budget")
    parent = path.rsplit("/", 1)[0]
    try:
        os.stat(parent)
    except OSError:
        # A fresh simulator/drop-in install has no /state until its first save.
        # The app owns this directory, unlike the read-only /system payload.
        os.mkdir(parent)
    # The old file remains intact until the complete replacement is closed.
    # A cut power supply must never turn a useful offline screen into half JSON.
    temporary = path + ".tmp"
    with open(temporary, "w") as target:
        target.write(payload)
    os.rename(temporary, path)


def copy(value):
    return json.loads(json.dumps(value))


def valid_snapshot(value):
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or not isinstance(value.get("home"), dict)):
        return False
    home = value["home"]
    if "utc_offset_minutes" in home:
        offset = home["utc_offset_minutes"]
        if type(offset) is not int or not -840 <= offset <= 840:
            return False
    for key in ("people", "events", "chores", "shopping", "photos", "agents"):
        rows = value.get(key)
        if not isinstance(rows, list):
            return False
        if any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in rows):
            return False
    if "devices" in value:
        rows = value["devices"]
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in rows):
            return False
    return True


def valid_pending(value):
    if not isinstance(value, dict) or value.get("kind") not in ("chore", "shopping", "device"):
        return False
    if not isinstance(value.get("id"), str) or not value["id"]:
        return False
    for key in ("version", "sequence"):
        if type(value.get(key)) is not int or value[key] < 1:
            return False
    if value["kind"] == "device":
        state = value.get("state")
        if not isinstance(state, dict) or not state:
            return False
        for key, field in state.items():
            if key in ("on", "locked"):
                if not isinstance(field, bool):
                    return False
            elif key == "state":
                if field not in ("open", "closed"):
                    return False
            else:
                return False
        return True
    return isinstance(value.get("done"), bool)
