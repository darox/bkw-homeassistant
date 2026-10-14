"""Client for the BKW energy API.

The client sends the OAuth access token of a `auth.BkwSession`, reads the
metering points, and reads the consumption records. The client renews the
token one time when the API answers HTTP 401.

The module has no Home Assistant imports, so a plain test can use it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import aiohttp

from . import const

# Transport failures. A bad answer is not one of these, so it stays visible.
TRANSPORT_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError, OSError)


class BkwError(Exception):
    """Base error for the BKW client."""


class BkwCannotConnect(BkwError):
    """The API is unreachable, busy, or rejected the request."""

    def __init__(self, status: int | None = None, message: str = "") -> None:
        super().__init__(message or (f"HTTP {status}" if status else "unreachable"))
        self.status = status


class BkwUnauthorized(BkwCannotConnect):
    """The API rejected the access token. Renew it and try again."""

    def __init__(self) -> None:
        super().__init__(status=401, message="HTTP 401")


class BkwInvalidResponse(BkwError):
    """The API returned data that does not match its contract."""


def timestamp(value: datetime) -> str:
    """Format a datetime as the UTC string that the API requires."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_timestamp(value: str) -> datetime:
    """Parse an API timestamp. A missing UTC offset means UTC."""
    stamp = value.strip()
    if stamp.endswith(("Z", "z")):
        stamp = stamp[:-1] + "+00:00"
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def _get_json(
    session: Any, path: str, params: dict[str, str], token: str
) -> Any:
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    try:
        async with session.get(
            const.API_BASE + path,
            params=params,
            headers=headers,
            timeout=const.REQUEST_TIMEOUT,
            # The bearer token must not go to the target of a redirect.
            allow_redirects=False,
        ) as response:
            if response.status == 401:
                raise BkwUnauthorized()
            if response.status != 200:
                raise BkwCannotConnect(response.status)
            try:
                return await response.json(content_type=None)
            except ValueError as err:
                raise BkwInvalidResponse("the API response body is not JSON") from err
    except BkwError:
        raise
    except TRANSPORT_ERRORS as err:
        raise BkwCannotConnect(message=str(err)) from err


async def _request(
    session: Any, auth: Any, path: str, params: dict[str, str]
) -> Any:
    """Call the API. Renew the token one time after HTTP 401."""
    token = await auth.token()
    try:
        return await _get_json(session, path, params, token)
    except BkwUnauthorized as err:
        auth.invalidate()
        token = await auth.token()
        try:
            return await _get_json(session, path, params, token)
        except BkwUnauthorized:
            raise BkwCannotConnect(401, "BKW API rejected the credentials") from err


async def fetch_metering_points(session: Any, auth: Any) -> list[str]:
    """Return the metering point codes of the account."""
    data = await _request(session, auth, const.METERING_POINTS_PATH, {})
    if not isinstance(data, list):
        raise BkwInvalidResponse("metering points is not a list")
    codes: list[str] = []
    for point in data:
        code = point.get("meteringPointCode") if isinstance(point, dict) else None
        if not isinstance(code, str) or not code:
            raise BkwInvalidResponse("metering point without a code")
        codes.append(code)
    return codes


async def fetch_consumption(
    session: Any,
    auth: Any,
    start: datetime,
    stop: datetime,
    metering_point: str,
    resolution: str = const.DEFAULT_RESOLUTION,
) -> list[tuple[str, float]]:
    """Return (timestamp, kWh) records for the time range."""
    if resolution not in const.RESOLUTIONS:
        raise BkwInvalidResponse(f"unknown resolution {resolution}")
    if not start < stop:
        raise BkwInvalidResponse("start must be before stop")
    params = {
        "resolution": resolution,
        "measurementValidityStart": timestamp(start),
        "measurementValidityStop": timestamp(stop),
        "dataType": const.DATA_TYPE,
        "meteringPointCode": metering_point,
    }
    data = await _request(session, auth, const.METERING_DATA_PATH, params)
    if not isinstance(data, list):
        raise BkwInvalidResponse("consumption is not a list")
    records: list[tuple[str, float]] = []
    for record in data:
        stamp = record.get("t") if isinstance(record, dict) else None
        value = record.get("v") if isinstance(record, dict) else None
        if not isinstance(stamp, str) or not isinstance(value, (int, float)):
            raise BkwInvalidResponse("invalid consumption record")
        records.append((stamp, float(value)))
    return records


def latest_value(records: list[tuple[str, float]]) -> float | None:
    """Return the value of the newest record, or None when there is no data."""
    if not records:
        return None

    def sort_key(record: tuple[str, float]) -> tuple[datetime, str]:
        try:
            return (parse_timestamp(record[0]), record[0])
        except ValueError:
            return (datetime.min.replace(tzinfo=timezone.utc), record[0])

    return max(records, key=sort_key)[1]
