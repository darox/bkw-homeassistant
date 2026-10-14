"""The BKW Energy integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from . import api
from .auth import BkwAuthError, BkwAuthRejected, BkwAuthTransient, BkwSession
from .const import (
    CONF_METERING_POINT,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    LOGIN_RENEWAL_FIRST,
    LOGIN_RENEWAL_MAXIMUM,
    LOGIN_RENEWAL_MINIMUM,
    LOGIN_RENEWAL_RETRY,
    LOGIN_RENEWAL_SHARE,
)

PLATFORMS = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


@dataclass
class BkwData:
    """The runtime data of one BKW Energy config entry."""

    session: Any
    auth: BkwSession
    code: str


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BKW Energy from a config entry."""
    session = async_get_clientsession(hass)

    def store_refresh_token(refresh_token: str) -> None:
        """Write the newest refresh token into the config entry."""
        if entry.data.get(CONF_REFRESH_TOKEN) == refresh_token:
            return
        data = {key: value for key, value in entry.data.items() if key != CONF_PASSWORD}
        data[CONF_REFRESH_TOKEN] = refresh_token
        hass.config_entries.async_update_entry(entry, data=data)
        _LOGGER.debug("The stored login of %s is renewed", entry.title)

    auth = BkwSession(
        session,
        entry.data[CONF_USERNAME],
        entry.data.get(CONF_PASSWORD),
        entry.data.get(CONF_REFRESH_TOKEN),
        on_refresh_token=store_refresh_token,
    )

    code = entry.data.get(CONF_METERING_POINT)
    if not code:
        # Home Assistant retries the setup only for an error that this module
        # raises before the platform forward. A raise in the platform has no
        # retry.
        try:
            codes = await api.fetch_metering_points(session, auth)
        except BkwAuthRejected as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (BkwAuthTransient, api.BkwError) as err:
            raise ConfigEntryNotReady(str(err)) from err
        if len(codes) != 1:
            raise ConfigEntryNotReady("the account has no single metering point")
        code = codes[0]

    entry.runtime_data = BkwData(session=session, auth=auth, code=code)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if CONF_PASSWORD in entry.data:
        # An older entry keeps the password. Replace it with a refresh token
        # after the first login. This is best effort, so an offline start does
        # not fail.
        entry.async_create_background_task(
            hass,
            _async_login_with_the_password(entry, auth),
            "bkw replace the stored password",
            eager_start=True,
        )

    _LoginRenewal(hass, entry, auth).start()
    return True


async def _async_login_with_the_password(entry: ConfigEntry, auth: BkwSession) -> None:
    """Log in with the stored password of an older entry one time.

    The session reports the new refresh token. The configuration entry then
    drops the password and keeps that token.
    """
    try:
        await auth.token()
    except BkwAuthError as err:
        _LOGGER.debug(
            "Cannot replace the stored password of %s yet: %s", entry.title, err
        )


class _LoginRenewal:
    """Renew the BKW login before the refresh token dies.

    The login server rotates the refresh token and gives it a short life (the
    response field `refresh_expires_in`, about 30 minutes). The sensor reads
    the meter data every 6 hours. Without a renewal the login dies between two
    polls, and Home Assistant asks for the password again at the next start.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, auth: BkwSession
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._auth = auth
        self._cancel: CALLBACK_TYPE | None = None
        self._stopped = False

    def start(self) -> None:
        """Plan the first renewal. Stop the plan when the entry unloads."""
        self._entry.async_on_unload(self._stop)
        self._schedule(LOGIN_RENEWAL_FIRST)

    @callback
    def _stop(self) -> None:
        """Stop the renewal. The entry unloads."""
        self._stopped = True
        self._cancel_timer()

    @callback
    def _cancel_timer(self) -> None:
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    @callback
    def _schedule(self, delay: timedelta) -> None:
        """Plan the next renewal of the login."""
        self._cancel_timer()
        if self._stopped:
            return
        # Home Assistant cancels a job with cancel_on_shutdown at a stop, so
        # the renewal cannot start during the close stage.
        job = HassJob(self._renew, "bkw renew the login", cancel_on_shutdown=True)
        loop = self._hass.loop
        self._cancel = loop.call_at(
            loop.time() + delay.total_seconds(), self._renew, job
        ).cancel

    @callback
    def _renew(self, _job: HassJob) -> None:
        self._cancel = None
        self._entry.async_create_task(
            self._hass, self._async_renew(), "bkw renew the login"
        )

    async def _async_renew(self) -> None:
        """Renew the login and plan the next renewal."""
        if self._stopped:
            return
        delay = LOGIN_RENEWAL_RETRY
        try:
            await self._auth.token(force=True)
        except BkwAuthRejected as err:
            # The stored login is dead. Keep the state unknown and ask the
            # user for the password again.
            _LOGGER.warning(
                "The BKW login of %s is no longer valid: %s", self._entry.title, err
            )
            self._entry.async_start_reauth(self._hass)
            return
        except BkwAuthError as err:
            _LOGGER.debug(
                "Cannot renew the BKW login of %s: %s", self._entry.title, err
            )
        else:
            delay = _renewal_delay(self._auth)
        self._schedule(delay)


def _renewal_delay(auth: BkwSession) -> timedelta:
    """Return the delay before the next renewal of the login."""
    expires = auth.refresh_expires_at
    if expires is None:
        # The login server did not state a life. Renew the login two times
        # each day.
        return LOGIN_RENEWAL_MAXIMUM
    remaining = (expires - dt_util.utcnow()) / LOGIN_RENEWAL_SHARE
    return min(max(remaining, LOGIN_RENEWAL_MINIMUM), LOGIN_RENEWAL_MAXIMUM)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a BKW Energy config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
