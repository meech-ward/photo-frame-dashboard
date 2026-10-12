#!/usr/bin/env python3
"""Prove Home HQ against an isolated local stack without printing credentials.

Creates fresh ordinary Auth owners, uses the publishable key and their sessions,
and drives the actual badge SupabaseTransport on CPython. Never uses an admin key.
"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import secrets
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib


class ProbeFailure(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # A metadata typo cannot redirect a local probe's Auth headers to cloud.
        raise ProbeFailure("local API attempted a redirect")


class API:
    def __init__(self, url, key):
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.scheme not in ("http", "https"):
            raise ProbeFailure("probe requires a loopback local project URL")
        if parsed.path not in ("", "/") or parsed.username or parsed.password:
            raise ProbeFailure("local project URL must be a bare origin")
        if key.startswith("sb_secret_"):
            raise ProbeFailure("probe requires a publishable key")
        self.url, self.key = url.rstrip("/"), key
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, session=None, body=None, method="POST", headers=None):
        request_headers = {"apikey": self.key}
        if session:
            request_headers["Authorization"] = "Bearer " + session["access_token"]
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(self.url + path, data=body, headers=request_headers, method=method)
        try:
            with self.opener.open(request, timeout=15) as response:
                return response.status, response.read(262145)
        except urllib.error.HTTPError as error:
            return error.code, error.read(65536)
        except urllib.error.URLError as error:
            raise ProbeFailure("local request failed: {} errno {}".format(
                type(error.reason).__name__, getattr(error.reason, "errno", None))) from None

    def json(self, path, session=None, body=None, method="POST", headers=None):
        status, raw = self.request(path, session, body, method, headers)
        try:
            value = json.loads(raw) if raw else None
        except (UnicodeError, ValueError):
            raise ProbeFailure("API returned a non-JSON response") from None
        return status, value, len(raw)

    def rpc(self, name, session, body=None):
        status, value, size = self.json("/rest/v1/rpc/" + name, session, body or {})
        if status != 200:
            raise ProbeFailure("RPC {} returned HTTP {}".format(name, status))
        return value, size


def check(condition, label):
    if not condition:
        raise ProbeFailure(label)
    print("PASS " + label, flush=True)


def boundary_png():
    # Browser canvases may encode opaque photos as RGBA. This deterministic
    # valid 320x240 PNG is above 256 KiB and below the shared 320 KiB cap, so
    # native downloading proves the real boundary rather than a tiny sample.
    rng = random.Random(123)
    rows = bytearray()
    for _ in range(240):
        rows.append(0)
        for _ in range(320):
            rows.extend((rng.randrange(256), rng.randrange(256), rng.randrange(256), 255))

    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 320, 240, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def account(api):
    email = "homehq-live-" + uuid.uuid4().hex + "@example.test"
    password = secrets.token_urlsafe(24)
    status, data, _ = api.json("/auth/v1/signup", body={"email": email, "password": password})
    if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
        raise ProbeFailure("ordinary local Auth signup did not create a session")
    return email, password, data


def signin(api, email, password):
    status, data, _ = api.json("/auth/v1/token?grant_type=password", body={"email": email, "password": password})
    if status != 200 or not isinstance(data, dict) or not data.get("refresh_token"):
        raise ProbeFailure("ordinary local Auth sign-in did not create a session")
    return data


def native_transport(homehq_root, api, session, household_id=None):
    repository = homehq_root.parent
    for path in (repository / "network" / "vendor", repository / "badgelink" / "badge",
                 repository / "network" / "badge", homehq_root / "badge" / "homehq"):
        sys.path.insert(0, str(path))
    source = homehq_root / "badge" / "homehq" / "transport.py"
    spec = importlib.util.spec_from_file_location("homehq_live_transport", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    transport = module.SupabaseTransport(
        {"url": api.url, "publishable_key": api.key, "allow_local_http": True},
        {"user_id": session["user"]["id"], "access_token": session["access_token"],
         "refresh_token": session["refresh_token"], "expires_at": session["expires_at"]},
    )
    # An Auth UUID identifies the actor, not the shared household. Resolve the
    # authorized snapshot first so a member never joins their own empty topic.
    if household_id is None:
        snapshot, _ = api.rpc("homehq_snapshot", session)
        household_id = snapshot["home"]["id"]
    transport.bind_home(household_id)
    return transport


def pump(transport, predicate, label, timeout=25):
    deadline = time.monotonic() + timeout
    events = []
    while time.monotonic() < deadline:
        events.extend(transport.poll())
        if predicate(events):
            return events
        time.sleep(0.005)
    # Session events contain credentials. Only the static phase name is exposed.
    raise ProbeFailure("native transport timed out: " + label)


def run(homehq_root, metadata):
    data = json.loads(metadata.read_text())
    env = data["env"]
    api = API(env["API_URL"], env["PUBLISHABLE_KEY"])
    accounts = []
    blob_paths = []
    transport = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        email, password, owner = account(api)
        accounts.append(owner)
        _, _, other = account(api)
        accounts.append(other)
        badge_session = signin(api, email, password)
        accounts.append(badge_session)
        check(owner["user"]["id"] != other["user"]["id"]
              and owner["refresh_token"] != badge_session["refresh_token"],
              "ordinary Auth signup and separate badge session")

        snapshot, size = api.rpc("homehq_seed_demo", owner)
        api.rpc("homehq_seed_demo", other)
        check(size <= 32768 and snapshot["schema_version"] == 1
              and {key: len(snapshot[key]) for key in ("people", "events", "chores", "shopping", "photos", "agents", "devices")}
              == {"people": 4, "events": 38, "chores": 33, "shopping": 24, "photos": 20, "agents": 5, "devices": 5},
              "REST seed delivers the full bounded sample")
        check(all(isinstance(event.get("start_offset_minutes"), int)
                  and isinstance(event.get("end_offset_minutes"), int) for event in snapshot["events"]),
              "REST agenda delivers timezone offsets for each event endpoint")

        owner_id = owner["user"]["id"]
        status, rows, _ = api.json("/rest/v1/homehq_people?owner_id=eq." + owner_id, other, method="GET")
        check(status == 200 and rows == [], "other-owner REST reads return no rows")
        status, rows, _ = api.json("/rest/v1/homehq_people?owner_id=eq." + owner_id, other,
                                  {"name": "Cross-owner probe"}, method="PATCH", headers={"Prefer": "return=representation"})
        check(status == 200 and rows == [], "other-owner REST writes change no rows")
        status, _, _ = api.json("/rest/v1/homehq_people", method="GET")
        check(status in (401, 403), "anonymous REST read is denied")
        status, _, _ = api.json("/rest/v1/rpc/homehq_snapshot", body={})
        check(status in (401, 403), "anonymous snapshot RPC is denied")

        saved, _ = api.rpc("homehq_set_done", owner,
                           {"p_kind": "shopping", "p_id": "g1", "p_done": True, "p_version": 1})
        replay, _ = api.rpc("homehq_set_done", owner,
                            {"p_kind": "shopping", "p_id": "g1", "p_done": True, "p_version": 1})
        conflict, _ = api.rpc("homehq_set_done", owner,
                              {"p_kind": "shopping", "p_id": "g1", "p_done": False, "p_version": 1})
        check(saved["status"] == replay["status"] == "saved"
              and saved["item"]["version"] == replay["item"]["version"] == 2
              and saved["revision"] == replay["revision"] and conflict["status"] == "conflict",
              "REST lost-response replay is idempotent and stale contradiction conflicts")

        def level(value):
            return api.rpc("homehq_set_device", owner,
                           {"p_id": "kitchen-light", "p_state": {"level": value}, "p_version": 1})[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(level, (20, 30)))
        winner = first if first["status"] == "saved" else second
        check(sorted((first["status"], second["status"])) == ["conflict", "saved"]
              and first["item"]["version"] == second["item"]["version"] == 2,
              "simultaneous REST device writes have one winner")
        replay, _ = api.rpc("homehq_set_device", owner,
                            {"p_id": "kitchen-light", "p_state": {"level": winner["item"]["level"]}, "p_version": 1})
        check(replay["status"] == "saved" and replay["item"]["version"] == 2
              and replay["revision"] == winner["revision"], "device retry does not advance its version or revision")

        png = (homehq_root / "badge" / "homehq" / "assets" / "photo-coast.png").read_bytes()
        digest = hashlib.sha256(png).hexdigest()
        blob_path = owner_id + "/" + digest + ".png"
        blob_paths.append(blob_path)
        object_url = "/storage/v1/object/homehq-photos/" + blob_path
        authenticated_url = "/storage/v1/object/authenticated/homehq-photos/" + blob_path
        status, _ = api.request(object_url, owner, png, headers={"Content-Type": "image/png"})
        check(status in (200, 201), "private Storage upload accepts an owner PNG")
        status, downloaded = api.request(authenticated_url, owner, method="GET")
        check(status == 200 and hashlib.sha256(downloaded).hexdigest() == digest, "private Storage owner read matches uploaded bytes")
        status, denied = api.request(authenticated_url, other, method="GET")
        check(status in (400, 401, 403, 404) and not denied.startswith(b"\x89PNG"), "private Storage other-owner read is denied")
        status, _ = api.request(object_url, other, png, headers={"Content-Type": "image/png", "x-upsert": "true"})
        check(status in (400, 401, 403, 404), "private Storage other-owner replacement is denied")

        transport = native_transport(homehq_root, api, badge_session)
        original_refresh = transport.session["refresh_token"]
        pump(transport, lambda _: transport.joined and transport.can_request, "private channel join")
        check(transport.joined and transport.session["refresh_token"] != original_refresh,
              "native transport refreshes its own Auth session and joins the private channel")
        transport.request("homehq_snapshot", {})
        events = pump(transport, lambda rows: any(row["kind"] == "result" for row in rows), "initial snapshot")
        result = next(row["data"] for row in events if row["kind"] == "result")
        check(result["schema_version"] == 1 and len(result["chores"]) == 33, "native transport receives the real REST snapshot")

        changed, _ = api.rpc("homehq_set_done", owner,
                             {"p_kind": "shopping", "p_id": "g2", "p_done": True, "p_version": 1})
        events = pump(transport, lambda rows: any(row["kind"] == "changed" for row in rows), "database Broadcast delivery")
        check(any(row["kind"] == "changed" for row in events), "native transport receives the database private Broadcast")
        pump(transport, lambda _: transport.can_request, "snapshot request slot")
        transport.request("homehq_snapshot", {})
        events = pump(transport, lambda rows: any(row["kind"] == "result" for row in rows), "updated snapshot")
        result = next(row["data"] for row in events if row["kind"] == "result")
        check(next(row for row in result["shopping"] if row["id"] == "g2")["done"]
              and result["revision"] >= changed["revision"], "Broadcast-triggered native snapshot catches up to durable state")

        pump(transport, lambda _: transport.can_request, "refresh request slot")
        previous_refresh = transport.session["refresh_token"]
        transport.refresh_at = 0
        events = pump(transport, lambda rows: any(row["kind"] == "session" for row in rows) and transport.can_request,
                      "second session refresh")
        check(transport.session["refresh_token"] != previous_refresh
              and any(row["kind"] == "session" for row in events), "native transport rotates and emits the refreshed session")
        transport.request("homehq_snapshot", {})
        events = pump(transport, lambda rows: any(row["kind"] == "result" for row in rows), "post-refresh snapshot")
        check(any(row["kind"] == "result" for row in events), "native REST remains authorized after refresh")
        with tempfile.TemporaryDirectory(prefix="homehq-live-photo-") as directory:
            target = Path(directory) / "homehq-photo-0.png"
            transport.photo(blob_path, str(target))
            events = pump(transport, lambda rows: any(row["kind"] == "photo" for row in rows), "private photo download")
            check(target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest
                  and any(row["kind"] == "photo" for row in events),
                  "native transport downloads the private PNG byte-for-byte")
            large_png = boundary_png()
            check(262144 < len(large_png) <= 327680, "valid RGBA photo crosses the former 256 KiB boundary")
            large_hash = hashlib.sha256(large_png).hexdigest()
            large_path = owner_id + "/" + large_hash + ".png"
            blob_paths.append(large_path)
            status, _ = api.request("/storage/v1/object/homehq-photos/" + large_path, owner,
                                    large_png, headers={"Content-Type": "image/png"})
            check(status in (200, 201), "private Storage accepts the bounded high-entropy PNG")
            large_target = Path(directory) / "homehq-photo-1.png"
            transport.photo(large_path, str(large_target))
            pump(transport, lambda rows: any(row["kind"] == "photo" for row in rows), "boundary photo download")
            check(large_target.exists() and hashlib.sha256(large_target.read_bytes()).hexdigest() == large_hash,
                  "native transport downloads a photo above 256 KiB without truncation")

        # A companion deletion must not keep an absent row at the badge's queue
        # head. Drive the actual Service and Transport, rather than simulating
        # the RPC404, and prove the next independent action still saves.
        from service import Service
        base, _ = api.rpc("homehq_snapshot", owner)
        with tempfile.TemporaryDirectory(prefix="homehq-live-outbox-") as directory:
            service = Service(str(homehq_root / "badge" / "homehq"), transport=transport,
                              state_root=directory, config={"url": api.url})
            service.receive_snapshot(base)
            for item_id in ("g1", "g2"):
                item = next(row for row in base["shopping"] if row["id"] == item_id)
                service.command({"kind": "shopping", "id": item_id, "done": False, "version": item["version"]})
            status, _ = api.request("/rest/v1/homehq_checklist?owner_id=eq." + owner_id
                                    + "&kind=eq.shopping&id=eq.g1", owner, method="DELETE")
            check(status in (200, 204), "companion can delete its own queued shopping item")
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                service.poll(int(time.monotonic() * 1000))
                current = service.snapshot()["shopping"]
                if (service.status()["pending"] == 0 and not any(row["id"] == "g1" for row in current)
                        and next(row for row in current if row["id"] == "g2")["done"] is False):
                    break
                time.sleep(0.005)
            current, _ = api.rpc("homehq_snapshot", owner)
            check(service.status()["pending"] == 0 and not any(row["id"] == "g1" for row in current["shopping"])
                  and next(row for row in current["shopping"] if row["id"] == "g2")["done"] is False,
                  "native outbox discards a deleted item and durably saves the next action")
        print("PASS Home HQ live local integration: Auth, REST, concurrency, private Storage, badge transport and database Broadcast", flush=True)
    finally:
        if transport:
            transport.close()
        # Only fresh probe-owned data is removed. Auth users are deliberately not
        # admin-deleted; their random local accounts vanish with this dev stack.
        if accounts and blob_paths:
            try:
                api.request("/storage/v1/object/homehq-photos", accounts[0], {"prefixes": blob_paths}, method="DELETE")
            except Exception:
                pass
        seen = set()
        for session in accounts:
            owner_id = session["user"]["id"]
            try:
                if owner_id not in seen:
                    api.request("/rest/v1/homehq_homes?owner_id=eq." + owner_id, session, method="DELETE")
                    seen.add(owner_id)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homehq-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()
    metadata = args.metadata or args.homehq_root / ".local.private.json"
    try:
        run(args.homehq_root, metadata)
    except ProbeFailure as error:
        print("FAIL " + str(error), file=sys.stderr)
        return 1
    except Exception as error:
        # An Auth/HTTP exception can contain tokens or a password-bearing URL.
        print("FAIL live local probe: " + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
