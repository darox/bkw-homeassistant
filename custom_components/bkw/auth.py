"""BKW OAuth access and the in-memory token session.

The BKW web application uses an OAuth password grant against the Keycloak realm
`oneportal`. This module sends that grant, renews the token with the refresh
token, and falls back to the password grant when the refresh token is dead.

The session stores only a refresh token. The configuration entry keeps that
refresh token, not the password.

This module has no Home Assistant imports, so a plain test can use it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from . import const
from .api import BkwError, TRANSPORT_ERRORS

MAX_TOKEN_LENGTH = 16384


class BkwAuthError(BkwError):
    """Base error for BKW authentication."""


class BkwAuthTransient(BkwAuthError):
    """A temporary failure. Try again later."""


class BkwAuthRejected(BkwAuthError):
    """The OAuth server rejected the credentials."""

    def __init__(self, code: str, status: int) -> None:
        super().__init__(f"BKW authentication rejected: {code or status}")
        self.code = code
        self.status = status


@dataclass
class TokenSet:
    """One access token and its refresh token."""

    access: str
    refresh: str
    expires_at: datetime
    refresh_expires_at: datetime | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _post_token(session: Any, form: dict[str, str]) -> dict[str, Any]:
    try:
        async with session.post(
            const.TOKEN_URL,
            data=form,
            headers={"Accept": "application/json"},
            timeout=const.GRANT_TIMEOUT,
            allow_redirects=False,
        ) as response:
            status = response.status
            try:
                body = await response.json(content_type=None)
            except ValueError:  # a non-JSON body is an error, not a crash
                body = None
    except TRANSPORT_ERRORS as err:
        raise BkwAuthTransient(str(err)) from err
    if status < 200 or status >= 300:
        code = body.get("error") if isinstance(body, dict) else None
        # Only a real credential refusal is final. A 404 or a redirect, for
        # example, must not look like a wrong password.
        if status in (400, 401):
            raise BkwAuthRejected(code or "", status)
        raise BkwAuthTransient(f"OAuth server returned HTTP {status}")
    if not isinstance(body, dict):
        raise BkwAuthTransient("OAuth server returned an invalid response")
    return body


def _tokens(body: dict[str, Any], require_refresh: bool) -> TokenSet:
    access = body.get("access_token")
    expires_in = body.get("expires_in")
    refresh = body.get("refresh_token") or ""
    refresh_expires_in = body.get("refresh_expires_in") or 0
    valid = (
        isinstance(access, str)
        and 0 < len(access) <= MAX_TOKEN_LENGTH
        and isinstance(expires_in, (int, float))
        and expires_in > 0
        and (not require_refresh or bool(refresh))
    )
    if not valid:
        raise BkwAuthTransient("OAuth server returned an invalid token response")
    now = _now()
    refresh_expires_at = None
    if isinstance(refresh_expires_in, (int, float)) and refresh_expires_in > 0:
        refresh_expires_at = now + timedelta(seconds=refresh_expires_in)
    return TokenSet(
        access=access,
        refresh=refresh if isinstance(refresh, str) else "",
        expires_at=now + timedelta(seconds=expires_in),
        refresh_expires_at=refresh_expires_at,
    )


async def password_grant(session: Any, username: str, password: str) -> TokenSet:
    """Send the OAuth password grant and return a new token set."""
    body = await _post_token(
        session,
        {
            "grant_type": "password",
            "client_id": const.CLIENT_ID,
            "scope": const.SCOPE,
            "username": username,
            "password": password,
        },
    )
    return _tokens(body, require_refresh=True)


async def refresh_grant(session: Any, refresh_token: str) -> TokenSet:
    """Send the OAuth refresh grant and return a new token set."""
    body = await _post_token(
        session,
        {
            "grant_type": "refresh_token",
            "client_id": const.CLIENT_ID,
            "refresh_token": refresh_token,
        },
    )
    return _tokens(body, require_refresh=False)


class BkwSession:
    """Hold one account token set and renew it when necessary."""

    def __init__(
        self,
        session: Any,
        username: str,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        self.http = session
        self._username = username
        self._password = password
        self._refresh_token = refresh_token
        self._tokens: TokenSet | None = None
        self._lock = asyncio.Lock()

    @property
    def refresh_token(self) -> str | None:
        """Return the newest refresh token, or None before the first grant."""
        if self._tokens is not None and self._tokens.refresh:
            return self._tokens.refresh
        return self._refresh_token

    async def token(self) -> str:
        """Return a valid access token. Renew it if necessary."""
        # One lock for the whole session: two platforms must not start two
        # grants at the same time.
        async with self._lock:
            return await self._valid_token()

    async def _valid_token(self) -> str:
        now = _now()
        tokens = self._tokens
        if tokens and now + const.REFRESH_SKEW < tokens.expires_at:
            return tokens.access

        refresh = (tokens.refresh if tokens else "") or self._refresh_token or ""
        refresh_expires_at = tokens.refresh_expires_at if tokens else None
        if refresh and (refresh_expires_at is None or now < refresh_expires_at):
            renewed: TokenSet | None
            try:
                renewed = await refresh_grant(self.http, refresh)
            except BkwAuthTransient:
                raise
            except BkwAuthRejected:
                # A dead refresh token. The password grant can still work when
                # the caller gave a password.
                renewed = None
            if renewed is not None:
                if not renewed.refresh:
                    renewed = replace(
                        renewed,
                        refresh=refresh,
                        refresh_expires_at=refresh_expires_at,
                    )
                self._tokens = renewed
                return renewed.access
        if self._password is None:
            raise BkwAuthRejected("refresh_token_expired", 401)
        self._tokens = await password_grant(self.http, self._username, self._password)
        return self._tokens.access

    def invalidate(self) -> None:
        """Forget the access token so the next call renews it."""
        if self._tokens is not None:
            self._tokens = replace(self._tokens, access="", expires_at=_now())
