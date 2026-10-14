"""Sensor platform for the BKW Energy integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import api
from .auth import BkwAuthError, BkwSession
from .const import (
    CONF_METERING_POINT,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_RESOLUTION,
    DOMAIN,
    SCAN_INTERVAL,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one sensor for the metering point of this entry."""
    session = async_get_clientsession(hass)
    auth = BkwSession(
        session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )
    code = entry.data.get(CONF_METERING_POINT)
    if not code:
        try:
            codes = await api.fetch_metering_points(session, auth)
        except (api.BkwError, BkwAuthError) as err:
            raise ConfigEntryNotReady(str(err)) from err
        if len(codes) != 1:
            raise ConfigEntryNotReady("the metering point is ambiguous")
        code = codes[0]
    async_add_entities([BkwConsumptionSensor(session, auth, entry, code)], True)


class BkwConsumptionSensor(SensorEntity):
    """Energy that the meter measured since local midnight, in kWh."""

    _attr_has_entity_name = True
    _attr_translation_key = "consumption"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = True

    def __init__(self, session, auth, entry: ConfigEntry, code: str) -> None:
        self._session = session
        self._auth = auth
        self._code = code
        self._attr_unique_id = f"{entry.entry_id}_{code}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="BKW",
            model="Metering point",
        )

    async def async_update(self) -> None:
        """Read the consumption of today and set the state."""
        now = dt_util.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now <= start:
            return
        records = await api.fetch_consumption(
            self._session, self._auth, start, now, self._code, DEFAULT_RESOLUTION
        )
        self._attr_native_value = api.latest_value(records)
        self._attr_last_reset = start
