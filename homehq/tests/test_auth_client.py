"""Native Supabase Auth API shape on cooperative HTTP, with no network."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "network/vendor", ROOT / "badgelink/badge", ROOT / "network/badge", ROOT / "homehq/badge/homehq"):
    sys.path.insert(0, str(path))
from transport import SupabaseTransport
from auth_client import session_record
from service import Service
import cache
from demo import snapshot

CONFIG = {"url": "http://localhost:54321", "allow_local_http": True, "publishable_key": "sb_publishable_test"}
TOKENS = {"access_token": "new-access", "refresh_token": "new-refresh", "expires_at": 3600,
          "expires_in": 3600, "user": {"id": "person-auth", "email": "person@example.test"}}


class FakeHTTP:
    def __init__(self, status=200, response=None):
        self.status = status
        self.response = TOKENS if response is None else response
        self.requests = []

    async def request(self, path, headers, body=None, **kwargs):
        self.requests.append((path, headers, body))
        await asyncio.sleep(0)
        return self.status, json.dumps(self.response).encode()

    async def close(self):
        pass


class NativeAuthTests(unittest.IsolatedAsyncioTestCase):
    def transport(self, session=None, status=200, response=None):
        t = SupabaseTransport(CONFIG, session)
        t.http = FakeHTTP(status, response)
        return t

    async def test_password_signin_matches_public_async_method_and_result_shape(self):
        t = self.transport()
        result = await t.auth.sign_in_with_password_async("person@example.test", "private-password")
        self.assertEqual(result, {"data": TOKENS, "status_code": 200})
        path, headers, body = t.http.requests[0]
        self.assertEqual(path, "/auth/v1/token?grant_type=password")
        self.assertEqual(body, {"email": "person@example.test", "password": "private-password", "grant_type": "password"})
        self.assertEqual(headers["apikey"], CONFIG["publishable_key"])
        self.assertEqual(headers["X-Supabase-Api-Version"], "2024-01-01")
        session = t.auth.get_session()["data"]["session"]
        self.assertEqual(session["user"]["id"], "person-auth")
        self.assertEqual(session["access_token"], "new-access")
        self.assertEqual(t.events[0], {"kind": "session", "data": {"v": 1, "refresh_token": "new-refresh", "user_id": "person-auth"}})
        self.assertEqual(t.events[1], {"kind": "signed_in"})

    async def test_rpc_builder_matches_personal_sdk_public_api_and_result_shape(self):
        t = self.transport({"access_token": "user-jwt", "refresh_token": "r", "user_id": "person-auth"},
                           response={"home": {"id": "family-id"}, "viewer": {"user_id": "person-auth"}})
        result = await t.rpc("homehq_snapshot").execute_async()
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["data"]["home"]["id"], "family-id")
        path, headers, body = t.http.requests[0]
        self.assertEqual(path, "/rest/v1/rpc/homehq_snapshot")
        self.assertEqual(headers["Authorization"], "Bearer user-jwt")
        self.assertEqual(body, {})
        t.http.status = 404
        t.http.response = {"code": "PT404", "message": "Item removed"}
        result = await t.rpc("homehq_set_done", {"p_id": "removed"}).execute_async()
        self.assertEqual(result, {"error": {"code": "PT404", "message": "Item removed"}, "status_code": 404})

    async def test_bad_auth_response_never_replaces_the_session(self):
        previous = {"access_token": "old-access", "refresh_token": "old-refresh", "user_id": "old-user"}
        for bad in ({}, {"access_token": "bad\nheader", "refresh_token": "r", "user": {"id": "id"}}, {"access_token": "x", "refresh_token": "r"}):
            t = self.transport(previous, response=bad)
            # Without user on password login, do not adopt a previous identity.
            result = await t.auth.sign_in_with_password_async("e", "p")
            self.assertIn("error", result)
            self.assertEqual(t.session, previous)
            self.assertEqual(t.events, [])

    async def test_refreshed_access_token_is_only_in_memory(self):
        t = self.transport({"v": 1, "refresh_token": "old-refresh", "user_id": "person-auth"})
        result = await t.auth.refresh_session_async()
        self.assertNotIn("error", result)
        self.assertEqual(t.http.requests[0][2], {"refresh_token": "old-refresh"})
        self.assertEqual(session_record(t.session), {"v": 1, "refresh_token": "new-refresh", "user_id": "person-auth"})
        self.assertNotIn("access_token", t.events[0]["data"])

    async def test_local_logout_does_not_revoke_other_boards_sessions(self):
        t = self.transport({"access_token": "old-access", "refresh_token": "old-refresh", "user_id": "person-auth"}, response={})
        t.http.status = 204
        result = await t.auth.sign_out_async("local")
        self.assertEqual(result["status_code"], 204)
        self.assertEqual(t.http.requests[0][0], "/auth/v1/logout?scope=local")
        self.assertIsNone(t.auth.get_session()["data"]["session"])

    async def test_empty_session_refresh_helper_matches_sdk_without_network(self):
        t = self.transport()
        self.assertEqual(await t.auth.refresh_if_needed_async(),
                         {"data": {"refreshed": False, "session": None}, "status_code": 200})
        self.assertEqual(t.http.requests, [])

    async def test_near_expiry_local_logout_refreshes_then_revokes_fresh_session(self):
        t = self.transport({"access_token": "old-access", "refresh_token": "old-refresh", "user_id": "person-auth"})
        t.expires_at_ms = t.clock() + 1000
        class LogoutHTTP(FakeHTTP):
            async def request(self, path, headers, body=None, **kwargs):
                self.requests.append((path, headers, body))
                if "grant_type=refresh_token" in path:
                    return 200, json.dumps(TOKENS).encode()
                return 204, b""
        t.http = LogoutHTTP()
        result = await t.auth.sign_out_async("local")
        self.assertEqual(result["status_code"], 204)
        self.assertEqual([call[0] for call in t.http.requests],
                         ["/auth/v1/token?grant_type=refresh_token", "/auth/v1/logout?scope=local"])
        self.assertEqual(t.http.requests[1][1]["Authorization"], "Bearer new-access")
        self.assertIsNone(t.auth.get_session()["data"]["session"])

    async def test_failed_logout_revocation_returns_error_but_clears_badge_session(self):
        t = self.transport({"access_token": "old-access", "refresh_token": "old-refresh", "user_id": "person-auth"},
                           status=500, response={"message": "network error"})
        result = await t.auth.sign_out_async("local")
        self.assertIn("error", result)
        self.assertIsNone(t.auth.get_session()["data"]["session"])

    async def test_dead_refresh_session_stops_retries_and_requests_login(self):
        t = self.transport({"refresh_token": "dead", "user_id": "person-auth"}, status=400,
                           response={"code": "refresh_token_not_found", "message": "Bearer should-not-display"})
        await t.refresh_session()
        self.assertEqual(t.auth_state, "signed_out")
        self.assertFalse(t.ready)
        self.assertEqual(t.events, [{"kind": "auth_error", "message": "Sign in again."}])
        await t.turn()
        self.assertIsNone(t.task)
        self.assertEqual(len(t.http.requests), 1)

    async def test_household_topic_and_photo_prefix_are_independent_of_person(self):
        t = self.transport({"refresh_token": "r", "user_id": "person-auth"})
        t.bind_home("family-id")
        await t.turn()
        # No actual network task survives this test's local binding phase.
        if t.task:
            t.task.cancel()
            try:
                await t.task
            except asyncio.CancelledError:
                pass
        self.assertEqual(t.realtime.channels()[0].topic, "realtime:homehq:family-id")
        self.assertFalse(t.photo("person-auth/image.png", "/state/homehq-photo-0.png"))
        self.assertTrue(t.photo("family-id/image.png", "/state/homehq-photo-0.png"))


class LoginServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.addCleanup(self.loop.close)
        self.addCleanup(lambda: asyncio.set_event_loop(None))

    def service(self):
        transport = SupabaseTransport(CONFIG, None)
        transport.http = FakeHTTP()
        return Service("/app", transport, self.directory.name, CONFIG), transport

    def test_login_submission_is_immediate_and_session_saves_only_renewal_identity(self):
        s, t = self.service()
        self.assertEqual(s.auth_state, "signed_out")
        self.assertEqual(s.snapshot()["people"], [])
        self.assertTrue(s.start_login("person@example.test", "secret"))
        self.assertEqual(t.http.requests, [], "a key press must not execute network work")
        self.assertEqual(s.auth_state, "signing_in")
        for now in range(10):
            s.poll(now)
            if s.auth_state == "signed_in":
                break
        self.assertEqual(s.auth_state, "signed_in")
        self.assertIsNone(s._auth_intent)
        self.assertEqual(cache.read(s.session_path), {"v": 1, "refresh_token": "new-refresh", "user_id": "person-auth"})
        s.close()

    def test_wrong_password_reports_static_error_and_never_persists_credentials(self):
        s, t = self.service()
        t.http.status = 400
        t.http.response = {"code": "invalid_credentials", "message": "secret-password private-token"}
        self.assertTrue(s.start_login("person@example.test", "secret-password"))
        for now in range(10):
            s.poll(now)
            if s.auth_state == "error":
                break
        self.assertEqual(s.auth_error, "Check email and password.")
        self.assertIsNone(s._auth_intent)
        self.assertFalse(Path(s.session_path).exists())
        self.assertEqual(s.snapshot()["people"], [])
        s.close()

    def test_failed_private_cleanup_refuses_to_install_another_identity(self):
        s, t = self.service()
        with patch("service.os.remove", side_effect=PermissionError(13, "read-only")):
            self.assertFalse(s.start_login("another@example.test", "new-password"))
        self.assertEqual(s.auth_state, "error")
        self.assertEqual(s.auth_error, "Session not cleared. Free storage.")
        self.assertIsNone(s._auth_intent)
        self.assertEqual(t.http.requests, [])

    def test_saved_cache_is_never_restored_into_a_different_auth_identity(self):
        cache.write(self.directory.name + "/homehq-cache.json", {"user_id": "someone-else", "snapshot": snapshot(),
                    "pending": [{"kind": "shopping", "id": "g1", "done": True, "version": 1, "sequence": 1}],
                    "photos": {"old/image.png": self.directory.name + "/homehq-photo-0.png"}})
        cache.write(self.directory.name + "/homehq-session.json", {"v": 1, "refresh_token": "refresh", "user_id": "person-auth"})
        s = Service("/app", state_root=self.directory.name, config=CONFIG)
        self.assertEqual(s.snapshot()["people"], [])
        self.assertEqual(s.status()["pending"], 0)
        self.assertEqual(s._photo_cache, {})

    def test_logout_clears_private_identity_but_preserves_project_and_wifi(self):
        s, t = self.service()
        s.auth_state = "signed_in"
        s._identity = "person-auth"
        for name in ("homehq-cache.json", "homehq-session.json", "homehq-photo-0.png", "homehq-photo-1.png", "homehq-photo-0.png.tmp"):
            Path(self.directory.name, name).write_text("old-private-data")
        keep = Path(self.directory.name, "homehq-config.json")
        keep.write_text("private-wifi-config")
        self.assertTrue(s.start_logout())
        self.assertEqual(s.snapshot()["people"], [])
        self.assertEqual(s._photo_cache, {})
        self.assertEqual(s.status()["pending"], 0)
        self.assertEqual(keep.read_text(), "private-wifi-config")
        self.assertEqual(sorted(p.name for p in Path(self.directory.name).iterdir()), ["homehq-config.json"])
        self.assertEqual(t.http.requests, [])
        s.close()

    def test_logout_refuses_to_lose_unsynced_changes(self):
        s, t = self.service()
        s.auth_state = "signed_in"
        s._queue = [{"kind": "shopping", "id": "g1", "done": True, "version": 1, "sequence": 1}]
        self.assertFalse(s.start_logout())
        self.assertEqual(s.notice, "Connect to save changes first.")
        self.assertEqual(len(s._queue), 1)
        s.close()

    def test_legacy_access_session_is_rewritten_before_any_network_dispatch(self):
        cache.write(self.directory.name + "/homehq-session.json", {"access_token": "old-jwt", "expires_at": 123,
                    "refresh_token": "renew", "user_id": "person-auth"})
        s = Service("/app", state_root=self.directory.name, config=CONFIG)
        class NoNetwork:
            ready = False
            session = {}
            def poll(self):
                return []
        s._transport = NoNetwork()
        s.poll(0)
        self.assertEqual(cache.read(s.session_path), {"v": 1, "refresh_token": "renew", "user_id": "person-auth"})


if __name__ == "__main__":
    unittest.main()
