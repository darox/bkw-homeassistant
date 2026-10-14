"""BKW OAuth access and the in-memory token session.

The BKW web application uses an OAuth password grant against the Keycloak realm
`oneportal`. This module sends that grant, renews the token with the refresh
token, and falls back to the password grant when the refresh token is dead.

This module has no Home Assistant imports, so a plain test can use it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from . import const
from .api import BkwError

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
            except Exception:  # noqa: BLE001 - a non-JSON body is an error
                body = None
    except Exception as err:  # noqa: BLE001 - any transport error is transient
        raise BkwAuthTransient(str(err)) from err
    if status < 200 or status >= 300:
        code = body.get("error") if isinstance(body, dict) else None
        if status in (408, 429) or status >= 500:
            raise BkwAuthTransient(f"OAuth server returned HTTP {status}")
        raise BkwAuthRejected(code or "", status)
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

    def __init__(self, session: Any, username: str, password: str) -> None:
        self.http = session
        self._username = username
        self._password = password
        self._tokens: TokenSet | None = None

    async def token(self) -> str:
        """Return a valid access token. Renew it if necessary."""
        now = _now()
        tokens = self._tokens
        if tokens and now + const.REFRESH_SKEW < tokens.expires_at:
            return tokens.access
        if tokens and tokens.refresh and (
            tokens.refresh_expires_at is None or now < tokens.refresh_expires_at
        ):
            try:
                renewed = await refresh_grant(self.http, tokens.refresh)
            except BkwAuthTransient:
                raise
            except BkwAuthRejected:
                pass
            else:
                if not renewed.refresh:
                    renewed = replace(
                        renewed,
                        refresh=tokens.refresh,
                        refresh_expires_at=tokens.refresh_expires_at,
                    )
                self._tokens = renewed
                return renewed.access
        self._tokens = await password_grant(self.http, self._username, self._password)
        return self._tokens.access

    def invalidate(self) -> None:
        """Forget the access token so the next call renews it."""
        if self._tokens is not None:
            self._tokens = replace(self._tokens, access="", expires_at=_now())
