"""Config flow for the BKW Energy integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import api
from .auth import BkwAuthRejected, BkwAuthTransient, BkwSession
from .const import (
    CONF_METERING_POINT,
    CONF_PASSWORD,
    CONF_QUARTER_HOUR,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_METERING_POINT, default=""): str,
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)

STEP_RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_METERING_POINT): str,
        vol.Optional(CONF_QUARTER_HOUR, default=False): BooleanSelector(),
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
                if not codes:
                    return self.async_abort(reason="no_metering_point")
                code = requested or (codes[0] if len(codes) == 1 else None)
                if code is None:
                    errors["base"] = "metering_point_required"
                elif code not in codes:
                    errors["base"] = "invalid_metering_point"
                else:
                    refresh_token = auth.refresh_token
                    if not refresh_token:
                        errors["base"] = "cannot_connect"
                    else:
                        await self.async_set_unique_id(username.lower())
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title=username,
                            data={
                                CONF_USERNAME: username,
                                CONF_METERING_POINT: code,
                                CONF_REFRESH_TOKEN: refresh_token,
                            },
                        )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start the re-authentication after a rejected login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again and store a new refresh token."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            auth = BkwSession(
                session, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            try:
                await auth.token()
            except BkwAuthRejected:
                errors["base"] = "invalid_auth"
            except (BkwAuthTransient, api.BkwError):
                errors["base"] = "cannot_connect"
            else:
                refresh_token = auth.refresh_token
                if not refresh_token:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_USERNAME: entry.data[CONF_USERNAME],
                            CONF_REFRESH_TOKEN: refresh_token,
                        },
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={
                "username": str(entry.data.get(CONF_USERNAME, entry.title))
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the metering point code and the extra data of an entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            requested = user_input[CONF_METERING_POINT].strip()
            quarter_hour = bool(user_input.get(CONF_QUARTER_HOUR, False))
            session = async_get_clientsession(self.hass)
            auth = BkwSession(
                session,
                entry.data[CONF_USERNAME],
                entry.data.get(CONF_PASSWORD),
                entry.data.get(CONF_REFRESH_TOKEN),
            )
            try:
                codes = await api.fetch_metering_points(session, auth)
            except BkwAuthRejected:
                return self.async_abort(reason="reauth_required")
            except (BkwAuthTransient, api.BkwError):
                errors["base"] = "cannot_connect"
            else:
                if requested not in codes:
                    errors["base"] = "invalid_metering_point"
                else:
                    data_updates = {CONF_METERING_POINT: requested}
                    if auth.refresh_token:
                        # The login server rotated the refresh token and the
                        # entry must keep the new one, or the entry cannot log
                        # in again.
                        data_updates[CONF_REFRESH_TOKEN] = auth.refresh_token
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates=data_updates,
                        options={CONF_QUARTER_HOUR: quarter_hour},
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_RECONFIGURE_SCHEMA,
                {
                    CONF_METERING_POINT: entry.data.get(CONF_METERING_POINT, ""),
                    CONF_QUARTER_HOUR: entry.options.get(CONF_QUARTER_HOUR, False),
                },
            ),
            errors=errors,
        )
