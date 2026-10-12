#!/usr/bin/env python3
"""Check four real hosted protocol clients using the canonical badge transport.

Only the verified new DevRel Free Home HQ project is accepted. Four fresh normal
sign-ins share its private household channel; --member-files checks four distinct
linked accounts. Saved badge/browser sessions are never consumed. The temporary
g2 desired-state edits are versioned/restored in default mode; member mode uses
and deletes its own unique shopping fixture so existing task attribution stays.
This exercises four TLS/Realtime clients on CPython, not four physical boards.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import uuid

from hosted import API, HostedFailure, private_read, signin, verified


PROJECT_REF = "cicgysjddsjsbgofpxwr"
SECTIONS = ("people", "events", "chores", "shopping", "photos", "agents", "devices")


def require(condition, label):
    if not condition:
        raise HostedFailure(label)


def item(snapshot, item_id="g2"):
    found = [row for row in snapshot["shopping"] if row["id"] == item_id]
    require(len(found) == 1, "the acceptance shopping item is missing")
    return found[0]


class Family:
    def __init__(self, root, api, harness, sessions, item_id="g2"):
        self.root, self.api, self.harness, self.sessions = root, api, harness, sessions
        self.item_id = item_id
        self.clients = []
        for session in sessions:
            self.clients.append({"transport": harness.native_transport(root, api, session),
                                 "alive": True, "hints": 0, "joins": 0, "errors": 0,
                                 "results": 0, "snapshot": None, "pending": None,
                                 "result": None, "hint_at": None})

    def sync_session(self, index):
        # The transport rotates only its independently signed-in session. Keep
        # its latest access token in memory so local sign-out targets that session.
        self.sessions[index].update(self.clients[index]["transport"].session)

    def drive(self):
        for index, client in enumerate(self.clients):
            if not client["alive"]:
                continue
            for event in client["transport"].poll():
                now = time.monotonic()
                kind = event.get("kind")
                if kind == "changed":
                    client["hints"] += 1
                    client["hint_at"] = now
                elif kind == "joined":
                    client["joins"] += 1
                elif kind == "error":
                    client["errors"] += 1
                elif kind == "result":
                    require(client["pending"] is not None, "native client returned an untracked RPC")
                    name, phase = client["pending"]
                    client["result"] = {"name": name, "phase": phase, "data": event["data"], "at": now}
                    client["pending"] = None
                    client["results"] += 1
                    if name == "homehq_snapshot":
                        require(event["data"].get("schema_version") == 1
                                and len(json.dumps(event["data"]).encode()) <= 32768,
                                "native client received an invalid or oversized snapshot")
                        client["snapshot"] = event["data"]
                elif kind == "session":
                    self.sync_session(index)

    def pump(self, predicate, label, timeout=45, after_drive=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.drive()
            if after_drive:
                after_drive()
            if predicate():
                return
            time.sleep(0.005)
        raise HostedFailure("four-client native phase timed out: " + label)

    def idle(self, seconds=0.15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.drive()
            time.sleep(0.005)

    def slots(self, indices):
        self.pump(lambda: all(self.clients[i]["transport"].can_request
                             and self.clients[i]["pending"] is None for i in indices), "request slots")

    def request(self, index, name, args, phase):
        client = self.clients[index]
        require(client["pending"] is None and client["transport"].can_request,
                "native request slot is not ready")
        client["pending"] = (name, phase)
        client["transport"].request(name, args)

    def snapshots(self, indices, phase):
        self.slots(indices)
        for index in indices:
            self.request(index, "homehq_snapshot", {}, phase)
        self.pump(lambda: all(self.clients[i]["result"] is not None
                             and self.clients[i]["result"]["phase"] == phase for i in indices), phase)

    def fanout(self, desired, indices, phase, edit):
        self.slots(indices)
        self.idle()
        actor = indices[0]
        current = item(self.clients[actor]["snapshot"], self.item_id)
        require(current["version"] == edit["owned_version"], "sample item changed concurrently")
        require(current["done"] is not desired, "probe edit must change the current absolute value")
        before = {i: self.clients[i]["hints"] for i in indices}
        hints, sent, snapshots = {}, set(), {}
        started = time.monotonic()
        edit["pending"] = {"from_version": current["version"], "done": desired}
        self.request(actor, "homehq_set_done", {"p_kind": "shopping", "p_id": self.item_id,
                                               "p_done": desired, "p_version": current["version"]}, phase + ":edit")
        saved = None

        def advance():
            nonlocal saved
            result = self.clients[actor]["result"]
            if saved is None and result and result["phase"] == phase + ":edit":
                saved = result
                value = saved["data"]
                require(value.get("status") == "saved" and value["item"]["done"] is desired
                        and value["item"]["version"] == current["version"] + 1,
                        "sample desired-state edit conflicted or returned an invalid version")
                edit.update({"owned_version": value["item"]["version"], "last_done": desired, "pending": None})
            for i in indices:
                client = self.clients[i]
                if i not in hints and client["hints"] > before[i]:
                    hints[i] = client["hint_at"]
                # A private hint triggers the authoritative RPC. No timer or
                # manually supplied snapshot can satisfy this fan-out assertion.
                if i in hints and i not in sent and client["pending"] is None and client["transport"].can_request:
                    self.request(i, "homehq_snapshot", {}, phase + ":snapshot")
                    sent.add(i)
                result = client["result"]
                if result and result["phase"] == phase + ":snapshot":
                    snapshots[i] = result

        def caught_up():
            if saved is None or len(snapshots) != len(indices):
                return False
            for result in snapshots.values():
                row = item(result["data"], self.item_id)
                require(row["done"] is desired and row["version"] == saved["data"]["item"]["version"]
                        and result["data"]["revision"] >= saved["data"]["revision"],
                        "hint-triggered snapshot is not the authoritative saved value")
            return True

        self.pump(caught_up, phase, after_drive=advance)
        return {"phase": phase, "rpc_ms": round((saved["at"] - started) * 1000, 1),
                "revision": saved["data"]["revision"], "item_version": saved["data"]["item"]["version"],
                "clients": [{"client": i + 1, "hint_ms": round((hints[i] - started) * 1000, 1),
                             "hint_to_snapshot_ms": round((snapshots[i]["at"] - hints[i]) * 1000, 1),
                             "mutation_to_snapshot_ms": round((snapshots[i]["at"] - started) * 1000, 1)}
                            for i in indices]}

    def close(self):
        failed = False
        for index, client in enumerate(self.clients):
            self.sync_session(index)
            if client["alive"]:
                try:
                    client["transport"].close()
                except Exception:
                    failed = True
                client["alive"] = False
        return failed


def run(root, metadata, owner_file, report_path=None, member_files=None):
    data = verified(metadata, PROJECT_REF)
    owner = private_read(owner_file)
    require(owner.get("project_ref") == PROJECT_REF and owner.get("url") == data["url"],
            "ordinary demo owner belongs to another project")
    records = [owner] * 4
    if member_files:
        require(len(member_files) == 3, "provide exactly three private member account files")
        records = [owner] + [private_read(path) for path in member_files]
        require(all(record.get("project_ref") == PROJECT_REF
                    and record.get("url", data["url"]) == data["url"]
                    and isinstance(record.get("email"), str) and isinstance(record.get("password"), str)
                    and record["email"] and record["password"] for record in records),
                "every member credential belongs to the verified Home HQ project")
    api = API(data)
    spec = importlib.util.spec_from_file_location("homehq_family_harness", root / "tools" / "check_live.py")
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    sessions, family, edit = [], None, None
    probe_id, probe_home = "g2", None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    report = {"schema_version": 1, "kind": "four_hosted_protocol_clients", "physical_badges": 0,
              "project_ref": PROJECT_REF, "transport_sha256": hashlib.sha256(
                  (root / "badge" / "homehq" / "transport.py").read_bytes()).hexdigest(), "phases": []}
    cleanup_failed = False
    try:
        for record in records:
            session = signin(api, record["email"], record["password"])
            sessions.append(session)
            require(session["user"]["id"] == record.get("user_id", session["user"]["id"])
                    and session["user"].get("role") == "authenticated"
                    and session["user"].get("is_anonymous") is False,
                    "probe sign-in must be the expected ordinary nonanonymous account")
        auth_users = len({session["user"]["id"] for session in sessions})
        require(auth_users == (4 if member_files else 1),
                "distinct-member proof needs four different Auth identities")
        require(len({session["refresh_token"] for session in sessions}) == 4,
                "four clients need four independent newly signed-in sessions")
        saved_tokens = {record.get("refresh_token") for record in records}
        saved_tokens.update(value.get("refresh_token") for record in records for value in record.values()
                            if isinstance(value, dict))
        require(not any(session["refresh_token"] in saved_tokens for session in sessions),
                "saved owner or badge refresh tokens must never be consumed")
        if member_files:
            # Existing tasks may already be completed with meaningful actor
            # attribution. A unique owned fixture proves sync without rewriting it.
            snapshot, _ = api.rpc("homehq_snapshot", sessions[0])
            require(len(snapshot["shopping"]) < 64 and len(json.dumps(snapshot).encode()) < 32000,
                    "household has no bounded snapshot space for the acceptance fixture")
            probe_home = snapshot["home"]["id"]
            probe_id = "sync_probe_" + uuid.uuid4().hex
            status, created, _ = api.json("/rest/v1/homehq_checklist", sessions[0],
                {"owner_id": probe_home, "kind": "shopping", "id": probe_id,
                 "title": "Temporary sync check", "category": "Sync check"},
                headers={"Prefer": "return=representation"})
            require(status == 201 and len(created) == 1
                    and created[0].get("created_by_user_id") == sessions[0]["user"]["id"],
                    "ordinary owner could not create its private acceptance fixture")
        family = Family(root, api, harness, sessions, item_id=probe_id)
        began = time.monotonic()
        family.pump(lambda: all(client["transport"].joined and client["transport"].can_request
                                for client in family.clients), "four private channel joins")
        report["all_joined_ms"] = round((time.monotonic() - began) * 1000, 1)
        family.snapshots(list(range(4)), "initial snapshots")
        originals = [item(client["snapshot"], probe_id) for client in family.clients]
        require(all(row["version"] == originals[0]["version"] and row["done"] == originals[0]["done"]
                    for row in originals), "four initial authoritative snapshots disagree")
        baseline = family.clients[0]["snapshot"]
        require(all(client["snapshot"]["home"].get("id") == baseline["home"].get("id")
                    and client["snapshot"].get("viewer", {}).get("user_id") == sessions[index]["user"]["id"]
                    for index, client in enumerate(family.clients)),
                "four identities must resolve the same authorized household")
        require(baseline["home"].get("demo") is True, "four-client acceptance requires the sample home")
        report["snapshot_counts"] = {key: len(baseline[key]) for key in SECTIONS}
        report["initial_revision"] = baseline["revision"]
        report["initial_item_version"] = originals[0]["version"]
        edit = {"original": originals[0]["done"], "owned_version": originals[0]["version"],
                "last_done": originals[0]["done"], "pending": None}
        report.update({"auth_users": auth_users, "households": 1})
        print("PASS 4 independent ordinary clients joined one private household and read snapshots.", flush=True)
        edit_indices = [1, 0, 2, 3] if member_files else list(range(4))
        report["phases"].append(family.fanout(not edit["original"], edit_indices, "all_online_edit", edit))
        if member_files:
            expected_actor = sessions[1]["user"]["id"] if not edit["original"] else None
            require(all(item(client["snapshot"], probe_id).get("completed_by_user_id") == expected_actor
                        for client in family.clients), "native member edit must preserve database-derived attribution")
            print("PASS member edit attribution matches its actual Auth identity on all 4 clients.", flush=True)
        print("PASS one versioned client edit reached the other 3 via hint -> authoritative snapshot.", flush=True)
        restore_indices = [2, 0, 1, 3] if member_files else list(range(4))
        report["phases"].append(family.fanout(edit["original"], restore_indices, "online_restore", edit))

        dropped = family.clients[3]
        offline_version = item(dropped["snapshot"], probe_id)["version"]
        family.sync_session(3)
        dropped["transport"].close()
        dropped["alive"] = False
        report["phases"].append(family.fanout(not edit["original"], [1, 0, 2] if member_files else [0, 1, 2], "offline_edit", edit))
        require(item(dropped["snapshot"], probe_id)["version"] == offline_version,
                "disconnected client must retain its prior cached snapshot")
        rejoined_at = time.monotonic()
        dropped["transport"] = harness.native_transport(root, api, sessions[3])
        dropped["alive"] = True
        family.pump(lambda: dropped["transport"].joined and dropped["transport"].can_request,
                    "disconnected client rejoin")
        join_ms = round((time.monotonic() - rejoined_at) * 1000, 1)
        # The missed Broadcast is gone. Join explicitly requests durable state,
        # as Service does on badge startup/rejoin, instead of waiting for a hint.
        family.snapshots([3], "durable offline catchup")
        caught = dropped["snapshot"]
        require(item(caught, probe_id)["done"] is not edit["original"]
                and item(caught, probe_id)["version"] == edit["owned_version"]
                and caught["revision"] >= report["phases"][-1]["revision"],
                "rejoined client did not catch the mutation missed while offline")
        report["offline_catchup"] = {"client": 4, "join_ms": join_ms,
                                     "rejoin_to_snapshot_ms": round((time.monotonic() - rejoined_at) * 1000, 1),
                                     "before_version": offline_version, "after_version": item(caught, probe_id)["version"],
                                     "revision": caught["revision"]}
        print("PASS disconnected client rejoined and read the durable edit it missed offline.", flush=True)
        report["phases"].append(family.fanout(edit["original"], list(range(4)), "final_restore", edit))
        require(all(item(client["snapshot"], probe_id)["done"] is edit["original"] for client in family.clients),
                "four final native snapshots did not restore the original desired value")
        report["final_revision"] = family.clients[0]["snapshot"]["revision"]
        report["final_item_version"] = edit["owned_version"]
        report["client_counts"] = [{"client": index + 1, **{key: client[key] for key in
                                   ("joins", "hints", "results", "errors")}}
                                  for index, client in enumerate(family.clients)]
    finally:
        if family:
            cleanup_failed |= family.close()
        if sessions and edit and not member_files:
            try:
                latest, _ = api.rpc("homehq_snapshot", sessions[0])
                current = item(latest, probe_id)
                if current["done"] is not edit["original"]:
                    pending = edit["pending"]
                    owned = (current["version"] == edit["owned_version"] and current["done"] is edit["last_done"])
                    owned |= (pending is not None and current["version"] == pending["from_version"] + 1
                              and current["done"] is pending["done"])
                    # Never overwrite a concurrent companion edit on cleanup.
                    require(owned, "temporary sample restoration needs review after a concurrent edit")
                    saved, _ = api.rpc("homehq_set_done", sessions[0], {"p_kind": "shopping", "p_id": probe_id,
                                      "p_done": edit["original"], "p_version": current["version"]})
                    require(saved.get("status") == "saved" and saved["item"]["done"] is edit["original"],
                            "temporary sample desired value restoration failed")
                restored, _ = api.rpc("homehq_snapshot", sessions[0])
                require(item(restored, probe_id)["done"] is edit["original"], "original sample desired value was not restored")
            except Exception:
                cleanup_failed = True
        if member_files and sessions and probe_home and probe_id != "g2":
            try:
                path = ("/rest/v1/homehq_checklist?owner_id=eq." + probe_home
                        + "&kind=eq.shopping&id=eq." + probe_id)
                status, rows, _ = api.json(path, sessions[0], method="GET")
                require(status == 200 and (not rows or (len(rows) == 1
                        and rows[0].get("created_by_user_id") == sessions[0]["user"]["id"]
                        and rows[0].get("category") == "Sync check")),
                        "acceptance fixture ownership could not be verified")
                if rows:
                    status, _ = api.request(path, sessions[0], method="DELETE")
                    require(status in (200, 204), "owned acceptance fixture deletion failed")
                status, rows, _ = api.json(path, sessions[0], method="GET")
                require(status == 200 and rows == [], "owned acceptance fixture remains after cleanup")
            except Exception:
                cleanup_failed = True
        signed_out = 0
        for session in sessions:
            try:
                status, _ = api.request("/auth/v1/logout?scope=local", session, body={})
                signed_out += status in (200, 204)
            except Exception:
                pass
        cleanup_failed |= signed_out != len(sessions)
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        loop.close()
        asyncio.set_event_loop(None)
        if cleanup_failed:
            raise HostedFailure("four-client probe cleanup needs review; no saved sessions were changed")
    report.update({"passed": True, "restored": True, "owned_fixture_deleted": bool(member_files), "signed_out_sessions": 4})
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("PASS original sample value restored; all 4 independent probe sessions signed out.", flush=True)
    print(json.dumps(report, sort_keys=True), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homehq-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--project-ref", required=True, choices=(PROJECT_REF,))
    parser.add_argument("--owner-file", type=Path)
    parser.add_argument("--member-files", type=Path, nargs=3,
                        help="Three mode-0600 records for existing linked member email/password accounts")
    parser.add_argument("--report", type=Path, help="credential-free counts and latency JSON")
    args = parser.parse_args()
    try:
        run(args.homehq_root.resolve(), args.metadata,
            args.owner_file or args.metadata.parent / ".hosted.owner.private.json", args.report, args.member_files)
        return 0
    except HostedFailure as error:
        print("FAIL " + str(error), file=sys.stderr)
    except Exception as error:
        # Socket/Auth exceptions can carry token-bearing URLs. Expose only type.
        print("FAIL four-client probe: " + type(error).__name__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
