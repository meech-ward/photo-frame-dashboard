#!/usr/bin/env python3
"""Deploy only the root-verified new, free DevRel Home HQ project.

This tool never creates, upgrades, links, or lists projects. Management commands
use the existing CLI login, while the demo uses ordinary password Auth only.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

VERSION = "2.120.0"
DEVREL = "yuueonycfgiwijatkqyv"


class HostedFailure(Exception):
    pass


def private_read(path):
    # Refuse symlinks and group/world-readable credentials, including files the
    # caller may have copied outside the repository's ignored private directory.
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise HostedFailure("private metadata must be a regular file with mode 0600")
    return json.loads(path.read_text())


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise HostedFailure("refusing a symlink for private output")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(data, out, separators=(",", ":"))


def verified(path, project_ref):
    data = private_read(path)
    if not re.fullmatch(r"[a-z]{20}", project_ref or "") or data.get("project_ref") != project_ref:
        raise HostedFailure("explicit project reference must match verified metadata")
    if (data.get("organization_id") != DEVREL or data.get("plan") != "free"
            or data.get("verified_new_project") is not True or data.get("project_name") != "Home HQ"):
        raise HostedFailure("target must be the verified new free DevRel Home HQ project")
    data["url"] = "https://" + project_ref + ".supabase.co"
    return data


def public_key(value):
    if isinstance(value, str) and value.startswith("sb_publishable_"):
        return value
    try:
        part = value.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        if claims.get("role") == "anon":
            return value
    except (ValueError, IndexError, TypeError, AttributeError):
        pass
    raise HostedFailure("only a publishable key or legacy anon key is accepted")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        raise HostedFailure("verified project API attempted a redirect")


class API:
    def __init__(self, data):
        self.url = data["url"]
        self.key = public_key(data.get("publishable_key"))
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, session=None, body=None, method="POST", headers=None):
        if not path.startswith("/") or "\r" in path or "\n" in path:
            raise HostedFailure("invalid project API path")
        supplied = {"apikey": self.key}
        if session:
            supplied["Authorization"] = "Bearer " + session["access_token"]
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            supplied["Content-Type"] = "application/json"
        if headers:
            supplied.update(headers)
        request = urllib.request.Request(self.url + path, data=body, headers=supplied, method=method)
        try:
            with self.opener.open(request, timeout=25) as response:
                result = response.read(327681)
                if len(result) > 327680:
                    raise HostedFailure("project API response exceeds probe bound")
                return response.status, result
        except urllib.error.HTTPError as error:
            return error.code, error.read(65536)
        except urllib.error.URLError:
            raise HostedFailure("verified project HTTPS request failed") from None

    def json(self, path, session=None, body=None, method="POST", headers=None):
        status, raw = self.request(path, session, body, method, headers)
        try:
            return status, json.loads(raw) if raw else None, len(raw)
        except (ValueError, UnicodeError):
            raise HostedFailure("project API returned a non-JSON response") from None

    def rpc(self, name, session, body=None):
        status, value, size = self.json("/rest/v1/rpc/" + name, session, body or {})
        if status != 200:
            raise HostedFailure("RPC {} returned HTTP {}".format(name, status))
        return value, size


def signin(api, email, password):
    status, value, _ = api.json("/auth/v1/token?grant_type=password", body={"email": email, "password": password})
    if status != 200 or not isinstance(value, dict) or not value.get("refresh_token"):
        raise HostedFailure("ordinary owner sign-in returned HTTP {}".format(status))
    value["expires_at"] = value.get("expires_at", int(time.time()) + value["expires_in"])
    return value


def badge_session(value):
    return {"user_id": value["user"]["id"], "access_token": value["access_token"],
            "refresh_token": value["refresh_token"], "expires_at": value["expires_at"]}


def hashes(root, config=False):
    paths = [root / "supabase" / "config.toml"] if config else sorted((root / "supabase" / "migrations").glob("*.sql")) + [root / "supabase" / "seed.sql"]
    if not paths:
        raise HostedFailure("no generated migrations found")
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def cli(root, command, data, accepted=(0,)):
    binary = root / ".tools" / "supabase"
    env = os.environ.copy()
    # local.py isolates native services in SUPABASE_HOME. Hosted management uses
    # the existing default login; explicit refs make linked checkout state moot.
    env.pop("SUPABASE_HOME", None)
    env.pop("SUPABASE_EXPERIMENTAL_STACK", None)
    if data.get("database_password"):
        env["SUPABASE_DB_PASSWORD"] = data["database_password"]
    version = subprocess.run([str(binary), "--version"], env=env, capture_output=True, text=True)
    if version.returncode or version.stdout.strip() != VERSION:
        raise HostedFailure("install the pinned project-local Supabase CLI " + VERSION)
    result = subprocess.run([str(binary), "--workdir", str(root)] + command,
                            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if result.returncode not in accepted:
        private_write(root / ".hosted.error.private.json", {"project_ref": data["project_ref"],
                      "command": command, "exit_code": result.returncode,
                      "stdout": result.stdout, "stderr": result.stderr})
        # Errors and CLI diagnostics can contain database passwords or Auth
        # tokens. Never forward raw output into the conversation or terminal.
        raise HostedFailure("hosted CLI command failed (exit {}); private diagnostic saved".format(result.returncode))
    return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}


def provision(api, data, output):
    if output.exists():
        owner = private_read(output)
        if owner.get("project_ref") != data["project_ref"]:
            raise HostedFailure("existing owner credentials belong to another project")
        session = signin(api, owner["email"], owner["password"])
    else:
        owner = {"project_ref": data["project_ref"], "email": "homehq-demo-" + uuid.uuid4().hex + "@example.com",
                 "password": secrets.token_urlsafe(32)}
        # Save before signup: a lost response must not create another account on
        # retry, and failed setup must leave the new account recoverable.
        private_write(output, owner)
        status, session, _ = api.json("/auth/v1/signup", body={"email": owner["email"], "password": owner["password"]})
        if status != 200 or not isinstance(session, dict) or not session.get("access_token"):
            raise HostedFailure("owner signup did not return a session; review email-confirmation setting (HTTP {})".format(status))
        session["expires_at"] = session.get("expires_at", int(time.time()) + session["expires_in"])
    owner.update({"url": data["url"], "publishable_key": api.key, "owner_session": session,
                  "user_id": session["user"]["id"]})
    private_write(output, owner)
    snapshot, size = api.rpc("homehq_seed_demo", session)
    if size > 32768 or snapshot.get("schema_version") != 1:
        raise HostedFailure("owner seed violated the bounded snapshot contract")
    badge = signin(api, owner["email"], owner["password"])
    if badge["refresh_token"] == session["refresh_token"] or badge["user"]["id"] != owner["user_id"]:
        raise HostedFailure("badge needs a separate session for the same owner")
    owner["badge_session"] = badge_session(badge)
    private_write(output, owner)
    print("Ordinary demo owner initialized; credentials and separate badge session saved privately.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("config-diff", "config-push", "db-plan", "db-apply", "keys", "owner"))
    parser.add_argument("--homehq-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--owner-file", type=Path)
    args = parser.parse_args()
    try:
        root = args.homehq_root.resolve()
        data = verified(args.metadata, args.project_ref)
        ref = data["project_ref"]
        review_path = args.metadata.parent / ".hosted.review.private.json"
        if args.command == "owner":
            provision(API(data), data, args.owner_file or args.metadata.parent / ".hosted.owner.private.json")
        elif args.command == "keys":
            raw = cli(root, ["projects", "api-keys", "--project-ref", ref, "--output", "json"], data)
            entries = json.loads(raw["stdout"])
            if isinstance(entries, dict):
                entries = entries.get("keys", entries.get("api_keys", []))
            candidates = [entry.get("api_key", entry.get("key", "")) for entry in entries if isinstance(entry, dict)]
            key = next((item for item in candidates if item.startswith("sb_publishable_")), None)
            if key is None:
                for item in candidates:
                    try:
                        key = public_key(item)
                        break
                    except HostedFailure:
                        pass
            data["publishable_key"] = public_key(key)
            private_write(args.metadata, data)
            print("Publishable project key saved privately; no secret keys revealed or retained.")
        else:
            is_config = args.command.startswith("config")
            fingerprint = hashes(root, config=is_config)
            review = private_read(review_path) if review_path.exists() else {"project_ref": ref}
            if review.get("project_ref") != ref:
                raise HostedFailure("review record belongs to another project")
            group = "config" if is_config else "db"
            if args.command in ("config-push", "db-apply"):
                if review.get(group, {}).get("hashes") != fingerprint:
                    raise HostedFailure("run the matching preview against these exact source files first")
                command = (["config", "push", "--project-ref", ref, "--yes"] if is_config else
                           ["db", "push", "--project-ref", ref, "--skip-vault", "--include-seed", "--yes"])
                cli(root, command, data)
                print("Hosted {} applied to the verified Home HQ project.".format(group))
            else:
                command = (["config", "diff", "--project-ref", ref, "--exit-code"] if is_config else
                           ["db", "push", "--project-ref", ref, "--skip-vault", "--include-seed", "--dry-run"])
                result = cli(root, command, data, accepted=(0, 2) if is_config else (0,))
                review[group] = {"hashes": fingerprint, "preview": result}
                private_write(review_path, review)
                print("Hosted {} preview saved privately; no changes applied.".format(group))
        return 0
    except HostedFailure as error:
        print("FAIL " + str(error), file=sys.stderr)
    except Exception as error:
        print("FAIL hosted setup: " + type(error).__name__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
