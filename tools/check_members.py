#!/usr/bin/env python3
"""Prove four different Auth users share one home on an isolated local stack.

Only loopback metadata and ordinary signup/password sessions are used. The
canonical badge transport delivers actual private Broadcasts; SQL alone cannot
prove WebSocket authorization. No cloud target or admin key is accepted.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

from check_family import Family, item
from check_live import API, ProbeFailure, account, check, native_transport
from hosted import HostedFailure


def run(root, metadata, report_path=None):
    data = json.loads(metadata.read_text())["env"]
    api = API(data["API_URL"], data["PUBLISHABLE_KEY"])
    sessions, family, home_id, object_path = [], None, None, None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    report = {"schema_version": 1, "kind": "four_distinct_local_auth_users", "physical_badges": 0,
              "transport_sha256": hashlib.sha256((root / "devices/badge/transport.py").read_bytes()).hexdigest(),
              "phases": []}
    cleanup_failed = False
    try:
        accounts = []
        for _ in range(5):
            accounts.append(account(api))
            sessions.append(accounts[-1][2])
        owner, outsider = sessions[0], sessions[4]
        check(len({session["user"]["id"] for session in sessions[:4]}) == 4,
              "four independently signed-up Auth identities")
        snapshot, _ = api.rpc("homehq_seed_demo", owner)
        home_id = snapshot["home"]["id"]
        for index, person_id in enumerate(("alex", "jordan", "maya", "otto")):
            linked, _ = api.rpc("homehq_link_member", owner,
                                {"p_email": accounts[index][0], "p_person_id": person_id})
            check(linked["home_id"] == home_id and linked["user_id"] == sessions[index]["user"]["id"],
                  "owner-linked account {} has the shared home".format(index + 1))
            opened, _ = api.rpc("homehq_seed_demo", sessions[index])
            check(opened["home"]["id"] == home_id and opened["viewer"]["person_id"] == person_id
                  and opened["viewer"]["is_owner"] is (index == 0) and len(opened["members"]) == index + 1,
                  "account {} initializes the existing family home".format(index + 1))
        status, denied, _ = api.json("/rest/v1/rpc/homehq_link_member", sessions[1],
                                   {"p_email": accounts[4][0], "p_person_id": "alex"})
        check(status == 403 and denied.get("code") == "42501", "member cannot grant account membership")
        status, rows, _ = api.json("/rest/v1/homehq_people?owner_id=eq." + home_id, outsider, method="GET")
        check(status == 200 and rows == [], "unrelated Auth account cannot read family rows")
        status, _, _ = api.json("/rest/v1/homehq_members", outsider,
                               {"user_id": outsider["user"]["id"], "owner_id": home_id, "person_id": "alex"})
        check(status == 403, "unrelated account cannot insert its own membership")

        actor = sessions[1]["user"]["id"]
        status, created, _ = api.json("/rest/v1/homehq_checklist", sessions[1],
            {"owner_id": home_id, "kind": "chore", "id": "family-proof", "title": "Shared family task",
             "person_id": "maya", "routine": "after", "created_by_user_id": owner["user"]["id"],
             "completed_by_user_id": owner["user"]["id"]}, headers={"Prefer": "return=representation"})
        check(status == 201 and created[0]["created_by_user_id"] == actor
              and created[0]["completed_by_user_id"] is None and created[0]["person_id"] == "maya",
              "new task stores household, assignment and database-derived creator")
        completed, _ = api.rpc("homehq_set_done", sessions[2],
                               {"p_kind": "chore", "p_id": "family-proof", "p_done": True, "p_version": 1})
        check(completed["item"]["completed_by_user_id"] == sessions[2]["user"]["id"]
              and completed["item"]["created_by_user_id"] == actor,
              "assigned member completion stores its real Auth identity")
        replay, _ = api.rpc("homehq_set_done", sessions[3],
                           {"p_kind": "chore", "p_id": "family-proof", "p_done": True, "p_version": 1})
        check(replay["status"] == "saved" and replay["item"]["completed_by_user_id"] == sessions[2]["user"]["id"],
              "same-state replay from another account preserves original completer")

        blob = (root / "devices/badge/assets/photo-coast.png").read_bytes()
        object_path = home_id + "/" + hashlib.sha256(blob).hexdigest() + ".png"
        status, _ = api.request("/storage/v1/object/homehq-photos/" + object_path, sessions[1], blob,
                                headers={"Content-Type": "image/png"})
        check(status in (200, 201), "member uploads to the existing household private photo folder")
        status, received = api.request("/storage/v1/object/authenticated/homehq-photos/" + object_path,
                                       sessions[2], method="GET")
        check(status == 200 and received == blob, "another family account downloads the same private photo")
        status, _ = api.request("/storage/v1/object/authenticated/homehq-photos/" + object_path,
                               outsider, method="GET")
        check(status != 200, "unrelated account cannot download the shared private photo")

        # Family's harness accepts separate sessions; each channel must bind to
        # the authorized home rather than that client's different Auth UUID.
        import check_live as harness
        family = Family(root, api, harness, sessions[:4])
        started = time.monotonic()
        family.pump(lambda: all(client["transport"].joined and client["transport"].can_request
                               for client in family.clients), "four distinct-account private joins")
        report["all_joined_ms"] = round((time.monotonic() - started) * 1000, 1)
        family.snapshots(list(range(4)), "member initial snapshots")
        check(all(client["snapshot"]["home"]["id"] == home_id for client in family.clients),
              "four canonical badge clients join one household topic")
        original = item(family.clients[0]["snapshot"])
        edit = {"original": original["done"], "owned_version": original["version"],
                "last_done": original["done"], "pending": None}
        report["phases"].append(family.fanout(not edit["original"], [1, 0, 2, 3], "member_native_edit", edit))
        check(all(item(client["snapshot"])["completed_by_user_id"] == sessions[1]["user"]["id"]
                  for client in family.clients), "native member edit broadcasts to all accounts with actual actor")
        report["phases"].append(family.fanout(edit["original"], [2, 0, 1, 3], "another_member_undo", edit))
        check(all(item(client["snapshot"])["completed_by_user_id"] is None for client in family.clients),
              "another member undo clears completion on all four clients")

        dropped = family.clients[3]
        old_version = item(dropped["snapshot"])["version"]
        family.sync_session(3)
        dropped["transport"].close()
        dropped["alive"] = False
        report["phases"].append(family.fanout(not edit["original"], [1, 0, 2], "member_offline_edit", edit))
        resumed = time.monotonic()
        dropped["transport"] = native_transport(root, api, sessions[3], household_id=home_id)
        dropped["alive"] = True
        family.pump(lambda: dropped["transport"].joined and dropped["transport"].can_request, "member rejoin")
        family.snapshots([3], "member durable catchup")
        check(item(dropped["snapshot"])["version"] > old_version
              and item(dropped["snapshot"])["done"] is not edit["original"],
              "offline member rejoins and reads the missed durable edit")
        report["offline_catchup_ms"] = round((time.monotonic() - resumed) * 1000, 1)
        report["phases"].append(family.fanout(edit["original"], list(range(4)), "member_final_restore", edit))
        check(all(client["errors"] == 0 for client in family.clients), "four native transports finish without errors")
        report.update({"auth_users": 4, "households": 1, "snapshot_bytes": len(json.dumps(
            family.clients[0]["snapshot"]).encode()), "passed": True})
    finally:
        if family:
            cleanup_failed |= family.close()
        if object_path and sessions:
            status, _ = api.request("/storage/v1/object/homehq-photos", sessions[0], {"prefixes": [object_path]}, method="DELETE")
            cleanup_failed |= status not in (200, 204)
        if home_id and sessions:
            status, _ = api.request("/rest/v1/homehq_homes?owner_id=eq." + home_id, sessions[0], method="DELETE")
            cleanup_failed |= status not in (200, 204)
        for session in sessions:
            try:
                status, _ = api.request("/auth/v1/logout?scope=local", session, body={})
                cleanup_failed |= status not in (200, 204)
            except Exception:
                cleanup_failed = True
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        loop.close()
        asyncio.set_event_loop(None)
        if cleanup_failed:
            raise ProbeFailure("local member proof cleanup needs review")
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homehq-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        run(args.homehq_root, args.metadata or args.homehq_root / ".local.private.json", args.report)
        return 0
    except (ProbeFailure, HostedFailure) as error:
        print("FAIL " + str(error), file=sys.stderr)
    except Exception as error:
        # Auth/session errors may contain credentials; only expose exception type.
        print("FAIL local membership proof: " + type(error).__name__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
