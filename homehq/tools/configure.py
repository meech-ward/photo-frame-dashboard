#!/usr/bin/env python3
"""Create a separate badge Auth session; write private files, never print tokens."""
import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def public_key(value):
    if value.startswith("sb_publishable_"):
        return value
    try:
        encoded = value.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if claims.get("role") == "anon":
            return value
    except (ValueError, IndexError, TypeError):
        pass
    raise ValueError("Use a publishable key or legacy anon key")


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(str(path), 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(data, out, separators=(",", ":"))


def project(local, url=None, key_file=None):
    if local:
        env = json.loads((ROOT / ".local.private.json").read_text())["env"]
        return env["API_URL"].rstrip("/"), public_key(env["PUBLISHABLE_KEY"])
    url = (url or "").rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.username or parsed.query:
        raise ValueError("Use the HTTPS project base URL")
    key = Path(key_file).read_text().strip() if key_file else os.getenv("HOMEHQ_PUBLISHABLE_KEY", "")
    return url, public_key(key)


def validate_member(snapshot, member_id):
    people = snapshot.get("people", []) if isinstance(snapshot, dict) else []
    matches = [row for row in people if isinstance(row, dict) and row.get("id") == member_id]
    if not matches:
        matches = [row for row in people if isinstance(row, dict)
                   and str(row.get("name", "")).casefold() == member_id.casefold()]
    if len(matches) != 1:
        raise ValueError("Choose an unambiguous family member name or id from this home.")
    return matches[0]["id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--key-file")
    parser.add_argument("--email", help="Email/password sign-in on the computer; omit with --no-login")
    parser.add_argument("--no-login", action="store_true", help="Save project/Wi-Fi configuration only; sign in on the badge screen")
    parser.add_argument("--wifi", action="store_true")
    parser.add_argument("--member", "--member-id", dest="member_id", help="Family member name or id for the Chores card")
    parser.add_argument("--output-dir", type=Path, help="Private state directory for this badge")
    args = parser.parse_args()
    if args.no_login and (args.member_id or args.email):
        parser.error("--no-login does not accept --email or --member; the logged-in account supplies its family perspective")
    if not args.no_login and not args.email:
        parser.error("provide --email, or --no-login to sign in on the badge")
    url, key = project(args.local, args.url, args.key_file)
    config = {"url": url, "publishable_key": key}
    if args.local:
        config["allow_local_http"] = True
    if args.wifi:
        config["wifi_ssid"] = input("Wi-Fi SSID: ")
        config["wifi_password"] = getpass.getpass("Wi-Fi password: ")
    target = args.output_dir or ROOT / "build" / "private" / "state"
    if args.no_login:
        private_write(target / "homehq-config.json", config)
        print("Project configuration saved privately. Sign in with email/password on the badge.")
        return
    password = getpass.getpass("Home HQ account password (not saved): ")
    request = urllib.request.Request(url + "/auth/v1/token?grant_type=password",
        data=json.dumps({"email": args.email, "password": password}).encode(),
        headers={"apikey": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit("Sign-in failed (HTTP {}). Check account/email confirmation.".format(error.code))
    # The native Auth adapter obtains a fresh access JWT at boot. Only the
    # rotating renewal credential and identity belong in durable flash state.
    password = None
    session = {"v": 1, "refresh_token": result["refresh_token"], "user_id": result["user"]["id"]}
    if args.member_id:
        # Four badges share one owner's rows but need independent refresh
        # tokens. Member selection changes only the initial Chores focus.
        request = urllib.request.Request(url + "/rest/v1/rpc/homehq_snapshot", data=b"{}",
            headers={"apikey": key, "Authorization": "Bearer " + result["access_token"],
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                config["member_id"] = validate_member(json.load(response), args.member_id)
        except urllib.error.HTTPError as error:
            raise SystemExit("Family lookup failed (HTTP {}). Open your seeded home in the companion first.".format(error.code))
    private_write(target / "homehq-config.json", config)
    private_write(target / "homehq-session.json", session)
    print("Separate badge session saved in the selected private state directory (mode 0600).")
    print("Keep these files private. Local HTTP is for host tests; use hosted HTTPS for a badge.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, FileNotFoundError) as error:
        raise SystemExit(str(error))
