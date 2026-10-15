"""A synthetic BKW API that follows the same contract as the real API.

The fixture serves the OAuth token endpoint and the two data endpoints:

* ``POST /token``
* ``GET /api/meteringpoint``
* ``GET /api/metering-data``

The token endpoint copies the real login server:

* It rotates the refresh token at each renewal and revokes the old token.
* A login that asks for the scope ``offline_access`` gets an offline refresh
  token. That token has a long idle life and no stated end of life
  (``refresh_expires_in`` is 0).
* Any other refresh token has a short idle life.
* A renewal keeps the offline state of the old token. The scope of the
  refresh request does not change it.
* An account without the ``offline_access`` role gets the error
  ``not_allowed`` for an offline login.
* An idle token is dead. Only a new use makes the life start again.

Tests point ``const.TOKEN_URL`` and ``const.API_BASE`` at the returned URL.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from aiohttp import web
from aiohttp.test_utils import TestServer

USERNAME = "owner@example.com"
PASSWORD = "secret"
REFRESH_TOKEN = "refresh-1"
REFRESH_IDLE = 1800.0
# The idle life of an offline refresh token. The real default is 30 days.
OFFLINE_IDLE = 30 * 24 * 3600.0
METERING_POINTS = [{"meteringPointCode": "CH0001", "description": "Home"}]
RESOLUTIONS = {"P1D", "P1M", "P1Y"}


class FixtureService:
    """A loopback stand-in for the BKW API."""

    def __init__(self) -> None:
        self._server: TestServer | None = None
        self.base = ""
        self.issued = 0
        # The newest refresh token, the number of tokens, and the end of its
        # idle life on the monotonic clock.
        self.refresh_token = REFRESH_TOKEN
        self.refresh_issued = 1
        # The idle life of the newest refresh token, and its end. An offline
        # token has the long idle life and no stated end of life.
        self.refresh_idle = REFRESH_IDLE
        self.refresh_deadline = time.monotonic() + REFRESH_IDLE
        self.refresh_offline = False
        # The account holds the `offline_access` role.
        self.allow_offline = True
        # The scope of the newest password grant.
        self.password_scope = ""
        self.rotate_refresh = True
        # Token -> expiry on the monotonic clock. An access token can expire,
        # so the tests can model the real token life.
        self.live: dict[str, float] = {}
        self.access_ttl = 300.0
        self.reject_next_access = False
        self.reject_refresh = False
        self.password_grants = 0
        self.metering_points = [dict(point) for point in METERING_POINTS]

    async def start(self) -> str:
        """Bind the fixture and return its base URL."""
        app = web.Application()
        app.router.add_post("/token", self._token)
        app.router.add_get("/api/meteringpoint", self._metering_points)
        app.router.add_get("/api/metering-data", self._metering_data)
        self._server = TestServer(app, host="127.0.0.1")
        await self._server.start_server()
        self.base = f"http://{self._server.host}:{self._server.port}"
        return self.base

    async def stop(self) -> None:
        """Release the port."""
        if self._server is not None:
            await self._server.close()
            self._server = None

    def _issue(self) -> str:
        self.issued += 1
        token = f"access-{self.issued}"
        self.live[token] = time.monotonic() + self.access_ttl
        return token

    async def _token(self, request: web.Request) -> web.Response:
        form = await request.post()
        grant = form.get("grant_type")
        if grant == "password":
            self.password_grants += 1
            self.password_scope = str(form.get("scope", ""))
            if form.get("client_id") != "mybkw-webapp":
                return web.json_response({"error": "invalid_client"}, status=401)
            if form.get("username") != USERNAME or form.get("password") != PASSWORD:
                return web.json_response({"error": "invalid_grant"}, status=400)
            offline = "offline_access" in self.password_scope
            if offline and not self.allow_offline:
                # The real server refuses the offline scope for an account
                # without the role.
                return web.json_response(
                    {
                        "error": "not_allowed",
                        "error_description": (
                            "Offline tokens not allowed for the user or client"
                        ),
                    },
                    status=400,
                )
            # A new login starts a new session, so the idle life starts again.
            return self._tokens(self.refresh_token, offline=offline)
        if grant == "refresh_token":
            idle = time.monotonic() >= self.refresh_deadline
            if (
                self.reject_refresh
                or form.get("refresh_token") != self.refresh_token
                or idle
            ):
                return web.json_response({"error": "invalid_grant"}, status=400)
            # The offline state of the old token does not change.
            return self._tokens(self._rotate(), offline=self.refresh_offline)
        return web.json_response({"error": "unsupported_grant_type"}, status=400)

    def expire_refresh(self) -> None:
        """Make the current refresh token older than its idle life."""
        self.refresh_deadline = 0.0

    def downtime(self, delta: timedelta) -> None:
        """Model a time without Home Assistant. A token can die in it."""
        self.refresh_deadline -= delta.total_seconds()

    def _rotate(self) -> str:
        """Return a new refresh token. The old token has no more value."""
        if self.rotate_refresh:
            self.refresh_issued += 1
            self.refresh_token = f"refresh-{self.refresh_issued}"
        return self.refresh_token

    def _tokens(self, refresh_token: str, offline: bool = False) -> web.Response:
        self.refresh_offline = offline
        self.refresh_idle = OFFLINE_IDLE if offline else REFRESH_IDLE
        self.refresh_deadline = time.monotonic() + self.refresh_idle
        return web.json_response(
            {
                "access_token": self._issue(),
                "expires_in": self.access_ttl,
                "refresh_token": refresh_token,
                # An offline token has no stated end of life.
                "refresh_expires_in": 0 if offline else self.refresh_idle,
            }
        )

    def _authorized(self, request: web.Request) -> web.Response | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return web.json_response({"error": "unauthorized"}, status=401)
        token = header[len("Bearer ") :]
        expiry = self.live.get(token)
        if expiry is None or expiry <= time.monotonic():
            self.live.pop(token, None)
            return web.json_response({"error": "unauthorized"}, status=401)
        if self.reject_next_access:
            self.reject_next_access = False
            self.live.pop(token, None)
            return web.json_response({"error": "unauthorized"}, status=401)
        return None

    async def _metering_points(self, request: web.Request) -> web.Response:
        denied = self._authorized(request)
        if denied is not None:
            return denied
        return web.json_response(self.metering_points)

    async def _metering_data(self, request: web.Request) -> web.Response:
        denied = self._authorized(request)
        if denied is not None:
            return denied
        query = request.query
        try:
            start = datetime.fromisoformat(query["measurementValidityStart"])
            stop = datetime.fromisoformat(query["measurementValidityStop"])
            resolution = query["resolution"]
            point = query["meteringPointCode"]
        except (KeyError, ValueError):
            return web.json_response({"error": "invalid input"}, status=400)
        if query.get("dataType") != "PRODUCTION_BKW":
            return web.json_response({"error": "invalid input"}, status=400)
        if resolution not in RESOLUTIONS or not start < stop:
            return web.json_response({"error": "invalid input"}, status=400)
        if point == "BOOM":
            return web.json_response({"error": "upstream failure"}, status=502)
        if point == "BADJSON":
            return web.Response(text="not json", content_type="application/json")
        if point == "REDIRECT":
            return web.Response(status=302, headers={"Location": self.base + "/login"})
        if point != "CH0001":
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response(
            [
                {"t": start.isoformat(), "v": 1.25},
                {"t": stop.isoformat(), "v": 2.5},
            ]
        )
