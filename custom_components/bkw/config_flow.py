"""Config flow for the BKW Energy integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import api
from .auth import BkwAuthRejected, BkwAuthTransient, BkwSession
from .const import CONF_METERING_POINT, CONF_PASSWORD, CONF_USERNAME, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_METERING_POINT, default=""): str,
    }
)


class BkwConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for one BKW account."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the account data and check the login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            requested = user_input.get(CONF_METERING_POINT, "").strip() or None
            session = async_get_clientsession(self.hass)
            auth = BkwSession(session, username, password)
            try:
                codes = await api.fetch_metering_points(session, auth)
            except BkwAuthRejected:
                errors["base"] = "invalid_auth"
            except (BkwAuthTransient, api.BkwError):
                errors["base"] = "cannot_connect"
            else:
                code = requested or (codes[0] if len(codes) == 1 else None)
                if code is None:
                    errors["base"] = "metering_point_required"
                elif code not in codes:
                    errors["base"] = "invalid_metering_point"
                else:
                    await self.async_set_unique_id(username.lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=username,
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_METERING_POINT: code,
                        },
                    )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
