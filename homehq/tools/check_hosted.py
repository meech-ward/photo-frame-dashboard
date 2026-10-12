#!/usr/bin/env python3
"""Exercise only the verified new Home HQ project's ordinary demo owner.

No admin key, signup, project discovery, home reset, or other owner's writes.
The probe restores its temporary checklist edit and deletes its uploaded PNG.
"""
import argparse
import asyncio
import hashlib
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import uuid
import zlib

from hosted import API, HostedFailure, private_read, signin, verified


def check(condition, label):
    if not condition:
        raise HostedFailure(label)
    print("PASS " + label, flush=True)


def run(root, metadata, project_ref, owner_file):
    data = verified(metadata, project_ref)
    owner = private_read(owner_file)
    if owner.get("project_ref") != project_ref:
        raise HostedFailure("demo owner belongs to another project")
    api = API(data)
    # Reuse the locally proven native harness, including its repository import
    # paths. A second transport implementation would miss badge-specific faults.
    spec = importlib.util.spec_from_file_location("homehq_hosted_harness", root / "tools" / "check_live.py")
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    sessions = []
    transport = None
    edit = None
    blob = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        companion = signin(api, owner["email"], owner["password"])
        sessions.append(companion)
        badge = signin(api, owner["email"], owner["password"])
        sessions.append(badge)
        check(companion["user"]["id"] == badge["user"]["id"] == owner["user_id"]
              and companion["refresh_token"] != badge["refresh_token"],
              "ordinary hosted owner uses independent companion and probe sessions")
        base, size = api.rpc("homehq_snapshot", companion)
        check(size <= 32768 and base["schema_version"] == 1 and base["home"].get("demo") is True
              and len(base["people"]) == 4 and len(base["chores"]) == 33
              and len(base["shopping"]) == 24 and len(base["photos"]) == 20 and len(base["devices"]) == 5,
              "hosted REST serves the full bounded owner sample")
        status, _, _ = api.json("/rest/v1/rpc/homehq_snapshot", body={})
        check(status in (401, 403), "hosted anonymous snapshot is denied")
        status, _, _ = api.json("/rest/v1/homehq_homes?owner_id=eq." + owner["user_id"], companion,
                                {"revision": 999}, method="PATCH")
        check(status in (401, 403), "hosted owner cannot directly replace the server revision")

        transport = harness.native_transport(root, api, badge)
        previous = transport.session["refresh_token"]
        harness.pump(transport, lambda _: transport.joined and transport.can_request, "hosted private channel join", timeout=40)
        check(transport.joined and transport.session["refresh_token"] != previous,
              "actual native transport refreshes Auth and joins hosted private Broadcast over TLS")
        transport.request("homehq_snapshot", {})
        events = harness.pump(transport, lambda rows: any(row["kind"] == "result" for row in rows), "hosted native snapshot")
        snapshot = next(row["data"] for row in events if row["kind"] == "result")
        check(snapshot["schema_version"] == 1 and len(snapshot["people"]) == 4,
              "actual native transport receives the hosted HTTPS snapshot")

        item = next(row for row in base["shopping"] if row["id"] == "g2")
        desired = not item["done"]
        result, _ = api.rpc("homehq_set_done", companion,
                            {"p_kind": "shopping", "p_id": item["id"], "p_done": desired, "p_version": item["version"]})
        if result["status"] != "saved":
            raise HostedFailure("hosted sample changed concurrently; probe stopped")
        edit = {"id": item["id"], "done": item["done"], "version": result["item"]["version"]}
        retry, _ = api.rpc("homehq_set_done", companion,
                           {"p_kind": "shopping", "p_id": item["id"], "p_done": desired, "p_version": item["version"]})
        check(retry["status"] == "saved" and retry["item"]["version"] == result["item"]["version"]
              and retry["revision"] == result["revision"], "hosted desired-value retry is idempotent")
        events = harness.pump(transport, lambda rows: any(row["kind"] == "changed" for row in rows), "hosted database Broadcast")
        check(any(row["kind"] == "changed" for row in events), "hosted database private Broadcast reaches the native transport")
        harness.pump(transport, lambda _: transport.can_request, "hosted snapshot slot")
        transport.request("homehq_snapshot", {})
        events = harness.pump(transport, lambda rows: any(row["kind"] == "result" for row in rows), "hosted updated snapshot")
        snapshot = next(row["data"] for row in events if row["kind"] == "result")
        check(next(row for row in snapshot["shopping"] if row["id"] == item["id"])["done"] is desired
              and snapshot["revision"] >= result["revision"], "hosted native snapshot catches up to the durable mutation")

        # A unique legal ancillary chunk creates a probe-owned hash/path. We must
        # never delete a coincidentally existing user upload during cleanup.
        png = harness.boundary_png()
        text = b"probe\x00" + uuid.uuid4().hex.encode()
        chunk = struct.pack(">I", len(text)) + b"tEXt" + text + struct.pack(">I", zlib.crc32(b"tEXt" + text))
        png = png[:-12] + chunk + png[-12:]
        check(262144 < len(png) <= 327680, "hosted photo probe uses a valid PNG above 256 KiB")
        digest = hashlib.sha256(png).hexdigest()
        blob = owner["user_id"] + "/" + digest + ".png"
        status, _ = api.request("/storage/v1/object/homehq-photos/" + blob, companion, png,
                                headers={"Content-Type": "image/png"})
        check(status in (200, 201), "hosted private Storage accepts the owner's bounded PNG")
        status, denied = api.request("/storage/v1/object/authenticated/homehq-photos/" + blob, method="GET")
        check(status in (400, 401, 403, 404) and not denied.startswith(b"\x89PNG"),
              "hosted private Storage denies an anonymous download")
        with tempfile.TemporaryDirectory(prefix="homehq-hosted-photo-") as directory:
            target = Path(directory) / "homehq-photo-0.png"
            transport.photo(blob, str(target))
            harness.pump(transport, lambda rows: any(row["kind"] == "photo" for row in rows), "hosted private photo")
            check(target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest,
                  "actual native transport downloads the private hosted PNG byte-for-byte")

        harness.pump(transport, lambda _: transport.can_request, "hosted refresh slot")
        previous = transport.session["refresh_token"]
        transport.refresh_at = 0
        events = harness.pump(transport, lambda rows: any(row["kind"] == "session" for row in rows) and transport.can_request,
                              "hosted second Auth refresh")
        check(transport.session["refresh_token"] != previous,
              "hosted native Auth refresh rotates the probe session")
        transport.request("homehq_snapshot", {})
        events = harness.pump(transport, lambda rows: any(row["kind"] == "result" for row in rows), "hosted post-refresh snapshot")
        check(any(row["kind"] == "result" for row in events), "hosted native REST remains authorized after refresh")
    finally:
        cleanup_failed = False
        if sessions and edit:
            try:
                restored, _ = api.rpc("homehq_set_done", sessions[0],
                                      {"p_kind": "shopping", "p_id": edit["id"], "p_done": edit["done"], "p_version": edit["version"]})
                cleanup_failed |= restored["status"] != "saved"
            except Exception:
                cleanup_failed = True
        if sessions and blob:
            try:
                status, _ = api.request("/storage/v1/object/homehq-photos", sessions[0], {"prefixes": [blob]}, method="DELETE")
                cleanup_failed |= status not in (200, 204)
            except Exception:
                cleanup_failed = True
        if transport:
            sessions[-1]["access_token"] = transport.session["access_token"]
            transport.close()
        for session in sessions:
            try:
                api.request("/auth/v1/logout?scope=local", session, body={})
            except Exception:
                pass
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        asyncio.set_event_loop(None)
        if cleanup_failed:
            raise HostedFailure("hosted probe cleanup needs review; no concurrent state was overwritten")
    print("PASS hosted native integration; temporary checklist state restored and probe PNG deleted.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homehq-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--owner-file", type=Path)
    args = parser.parse_args()
    try:
        run(args.homehq_root.resolve(), args.metadata, args.project_ref,
            args.owner_file or args.metadata.parent / ".hosted.owner.private.json")
        return 0
    except HostedFailure as error:
        print("FAIL " + str(error), file=sys.stderr)
    except Exception as error:
        # TLS/Auth/WebSocket exceptions may embed credentials. Static type only.
        print("FAIL hosted probe: " + type(error).__name__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
