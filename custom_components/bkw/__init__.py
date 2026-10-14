"""The BKW Energy integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import api
from .auth import BkwAuthError, BkwAuthRejected, BkwAuthTransient, BkwSession
from .const import CONF_METERING_POINT, CONF_PASSWORD, CONF_REFRESH_TOKEN, CONF_USERNAME

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
    auth = BkwSession(
        session,
        entry.data[CONF_USERNAME],
        entry.data.get(CONF_PASSWORD),
        entry.data.get(CONF_REFRESH_TOKEN),
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
            _async_drop_password(hass, entry, auth),
            "bkw replace the stored password",
            eager_start=True,
        )
    return True


async def _async_drop_password(
    hass: HomeAssistant, entry: ConfigEntry, auth: BkwSession
) -> None:
    """Store a refresh token and remove the password from an older entry."""
    try:
        await auth.token()
    except BkwAuthError as err:
        _LOGGER.debug("Cannot replace the stored password yet: %s", err)
        return
    refresh_token = auth.refresh_token
    if not refresh_token:
        return
    data = {key: value for key, value in entry.data.items() if key != CONF_PASSWORD}
    data[CONF_REFRESH_TOKEN] = refresh_token
    hass.config_entries.async_update_entry(entry, data=data)
    _LOGGER.debug(
        "The stored password of %s is replaced by a refresh token", entry.title
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a BKW Energy config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
