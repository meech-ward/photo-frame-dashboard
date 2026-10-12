"""Supabase Auth API on the badge's existing cooperative HTTP implementation.

The public method/result shapes match meech-ward/supabase-micro aa30dc4e.
Only this app's required subset is implemented; transport/TLS stay badge-owned.
"""
import json

_LOST = ("refresh_token_not_found", "refresh_token_already_used", "session_not_found", "session_expired")


def session_record(session):
    """Flash keeps renewal credentials, never a cached access JWT or password."""
    if not isinstance(session, dict) or any(not isinstance(session.get(key), str) or not session[key]
                                            for key in ("refresh_token", "user_id")):
        return None
    return {"v": 1, "refresh_token": session["refresh_token"], "user_id": session["user_id"]}


class AuthClient:
    def __init__(self, transport):
        self._transport = transport

    def get_session(self):
        current = self._transport.session
        session = None
        if current.get("access_token"):
            session = {"access_token": current["access_token"], "refresh_token": current.get("refresh_token"),
                       "expires_at": current.get("expires_at"), "user": current.get("user") or {"id": current.get("user_id")}}
        return {"data": {"session": session}, "status_code": 200}

    async def _request(self, path, body=None):
        transport = self._transport
        headers = {"apikey": transport.key, "Content-Type": "application/json",
                   "X-Supabase-Api-Version": "2024-01-01"}
        headers["Authorization"] = "Bearer " + (transport.session.get("access_token") or transport.key)
        try:
            status, raw = await transport.http.request("/auth/v1" + path, headers, body)
            try:
                data = json.loads(raw) if raw else {}
            except (ValueError, UnicodeError):
                return {"error": {"message": "Invalid Auth response"}, "error_type": "decode", "status_code": status}
            if not isinstance(data, dict):
                return {"error": {"message": "Invalid Auth response"}, "error_type": "decode", "status_code": status}
            if not 200 <= status < 300:
                code = data.get("code") or data.get("error_code")
                # Product errors must never echo raw provider/transport text,
                # which could include credentials or a token-bearing URL.
                result = {"error": {"code": code, "message": "Authentication failed"}, "status_code": status}
                if status == 400 and code in _LOST:
                    result["error_type"] = "session_lost"
                return result
            return {"data": data, "status_code": status}
        except Exception:
            return {"error": {"message": "Unable to connect"}, "status_code": 500}

    async def _install(self, result, sign_in=False):
        if "error" in result:
            return result
        data = result["data"]
        token, refresh = data.get("access_token"), data.get("refresh_token")
        user = data.get("user")
        user_id = user.get("id") if isinstance(user, dict) else (None if sign_in else self._transport.session.get("user_id"))
        expires_in = data.get("expires_in", 3600)
        if (not all(isinstance(value, str) and value for value in (token, refresh, user_id))
                or any(c <= " " or c > "~" for c in token) or type(expires_in) is not int or expires_in < 1):
            return {"error": {"message": "Invalid Auth session"}, "error_type": "decode", "status_code": result["status_code"]}
        transport = self._transport
        transport.session = {"access_token": token, "refresh_token": refresh, "user_id": user_id,
                             "expires_at": data.get("expires_at"), "user": user or {"id": user_id}}
        transport.events.append({"kind": "session", "data": session_record(transport.session)})
        # The Service receives this typed event before another network job;
        # its storage barrier makes each rotated token durable before RPCs.
        await transport.realtime.set_access_token(token)
        transport.refresh_at = transport.clock() + max(60, expires_in - 120) * 1000
        transport.expires_at_ms = transport.clock() + expires_in * 1000
        transport.ready = True
        transport.auth_state = "signed_in"
        if sign_in:
            transport.events.append({"kind": "signed_in"})
        return result

    async def sign_in_with_password_async(self, email, password):
        result = await self._request("/token?grant_type=password", {"email": email, "password": password, "grant_type": "password"})
        return await self._install(result, True)

    async def refresh_session_async(self, refresh_token=None):
        token = refresh_token or self._transport.session.get("refresh_token")
        if not token:
            return {"error": {"message": "No refresh token available"}, "status_code": 400}
        return await self._install(await self._request("/token?grant_type=refresh_token", {"refresh_token": token}))

    def should_refresh_token(self, threshold_seconds=300):
        transport = self._transport
        deadline = transport.expires_at_ms
        if not transport.session.get("access_token") or deadline is None:
            return {"data": {"should_refresh": False}, "status_code": 200}
        seconds = (deadline - transport.clock()) / 1000
        return {"data": {"should_refresh": seconds < threshold_seconds, "expires_in": max(0, seconds)}, "status_code": 200}

    async def refresh_if_needed_async(self, threshold_seconds=300):
        transport = self._transport
        # The network handoff uses a monotonic deadline after a server refresh,
        # so a late RTC correction cannot suppress renewal.
        if self.should_refresh_token(threshold_seconds)["data"]["should_refresh"]:
            result = await self.refresh_session_async()
            if "error" in result:
                return result
            refreshed = True
        else:
            refreshed = False
        return {"data": {"refreshed": refreshed, "session": self.get_session()["data"]["session"]}, "status_code": 200}

    def clear_session(self):
        self._transport.session = {}
        self._transport.ready = False
        self._transport.auth_state = "signed_out"
        return self.get_session()

    async def sign_out_async(self, scope=None):
        if scope not in (None, "global", "local", "others"):
            raise ValueError("scope must be None, global, local or others")
        path = "/logout" + ("?scope=" + scope if scope else "")
        transport = self._transport
        refreshed = None
        if transport.session.get("refresh_token") and (not transport.session.get("access_token")
                or self.should_refresh_token(10)["data"]["should_refresh"]):
            # A rejected expired JWT would leave its renewal credential valid
            # remotely. Match the public SDK's near-expiry refresh before logout.
            refreshed = await self.refresh_session_async()
        result = await self._request(path) if self._transport.session.get("access_token") else (
            refreshed if refreshed and "error" in refreshed else {"data": None, "status_code": 204})
        if scope != "others":
            self.clear_session()
            # The badge's low-level client deliberately accepts only a real
            # JWT. Closing/replacing it clears authorization without weakening
            # that shared validator or putting another identity on its socket.
            await self._transport.realtime.close_transport()
            self._transport.realtime = self._transport._new_realtime()
            self._transport.home_id = None
        return result
