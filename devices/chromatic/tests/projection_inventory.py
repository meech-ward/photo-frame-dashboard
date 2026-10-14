"""Normative native UI field/page inventory; reports counts, never household values.

The native in-place projector implements this inventory. Projection consistency
tests compare its output against this model for every page. Footprint estimates
remain a planning aid; native heap-stage measurements establish actual budgets.
"""
import argparse
import json
from pathlib import Path

FIELDS = {
    "home": {"id", "utc_offset_minutes", "demo"},
    "viewer": {"user_id", "person_id"},
    "people": {"id", "name", "color", "home", "eta"},
    "events": {"id", "start", "end", "start_offset_minutes", "end_offset_minutes",
               "all_day", "title", "people", "travel", "loc", "notes"},
    "chores": {"id", "who", "person_id", "routine", "title", "stars", "done", "version"},
    "shopping": {"id", "name", "category", "store", "quantity", "done", "version"},
    "photos": {"id", "path", "asset", "caption", "place"},
    "weather": {"temp", "label", "sample"},
    "home_status": {"temperature", "sample"},
    "agents": {"id", "name", "color", "meters", "week"},
    "devices": {"id", "name", "room", "type", "version", "on", "locked", "state"},
}
COLLECTIONS = {"people", "events", "chores", "shopping", "photos", "agents", "devices"}
PAGES = {
    "today": {"events", "weather"}, "calendar": {"events"}, "chores": {"chores"},
    "shopping": {"shopping"}, "photos": {"photos"}, "home": {"devices", "home_status"},
    "agents": {"agents"},
}
BASE = {"schema_version", "revision", "server_time", "home", "viewer", "people"}


def project(snapshot, page=None):
    """UI semantics retain every row; inactive collections become empty arrays."""
    result = {}
    for key, value in snapshot.items():
        if key not in BASE | set(FIELDS):
            continue
        if page and key not in BASE | PAGES[page]:
            if key in COLLECTIONS:
                result[key] = []
            continue
        if key in FIELDS:
            def row(source):
                item = {k: v for k, v in source.items() if k in FIELDS[key]}
                if key == "agents":
                    item["meters"] = [{k: v for k, v in meter.items()
                                       if k in {"label", "used", "reset_minutes"}}
                                      for meter in item.get("meters", [])]
                if key == "devices" and isinstance(item.get("state"), dict):
                    item["state"] = {k: v for k, v in item["state"].items()
                                     if k in {"on", "locked", "state"}}
                return item
            value = [row(item) for item in value] if isinstance(value, list) else row(value)
        result[key] = value
    return result


def footprint(value, key=None):
    """Xtensa estimate: cJSON node 40B + 8B heap block; 4B string alignment.

    Estimate is comparative, not a replacement for native heap-stage evidence.
    Demo estimate 88,460 B is 5% above measured 84,244 B on the real MCU.
    """
    def string_cost(text):
        return ((len(text.encode()) + 1 + 3) // 4) * 4 + 8
    nodes, allocated = 1, 48 + (string_cost(key) if key is not None else 0)
    children = value.items() if isinstance(value, dict) else (
        ((None, child) for child in value) if isinstance(value, list) else [])
    for child_key, child in children:
        child_nodes, child_bytes = footprint(child, child_key)
        nodes += child_nodes
        allocated += child_bytes
    if isinstance(value, str):
        allocated += string_cost(value)
    return nodes, allocated


def report(label, snapshot):
    variants = [("canonical", snapshot), ("fields", project(snapshot))]
    variants += [(page, project(snapshot, page)) for page in PAGES]
    for name, value in variants:
        nodes, allocation = footprint(value)
        compact = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
        print(f"{label:9} {name:10} nodes={nodes:4} wire={compact:5} graph_estimate={allocation:6}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshots", nargs="*", type=Path)
    args = parser.parse_args()
    paths = args.snapshots or [Path(__file__).resolve().parents[3] / "fixtures/demo.json"]
    for index, path in enumerate(paths):
        report(f"input{index + 1}", json.loads(path.read_text()))
