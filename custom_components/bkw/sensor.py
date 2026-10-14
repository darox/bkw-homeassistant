"""Sensor platform for the BKW Energy integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import api
from .auth import BkwAuthRejected, BkwError
from .const import DEFAULT_RESOLUTION, DOMAIN, SCAN_INTERVAL  # noqa: F401

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one sensor for the metering point of this entry."""
    data = entry.runtime_data
    async_add_entities([BkwConsumptionSensor(entry, data)], True)


class BkwConsumptionSensor(SensorEntity):
    """Energy of the last complete local day, in kWh."""

    _attr_has_entity_name = True
    _attr_translation_key = "consumption"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = True

    def __init__(self, entry: ConfigEntry, data) -> None:
        self._entry = entry
        self._data = data
        unique = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique}_{data.code}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="BKW",
            model="Metering point",
        )

    async def async_update(self) -> None:
        """Read the energy of the last complete day and set the state."""
        today = dt_util.start_of_local_day()
        start = dt_util.start_of_local_day(today - timedelta(days=1))
        try:
            records = await api.fetch_consumption(
                self._data.session,
                self._data.auth,
                start,
                today,
                self._data.code,
                DEFAULT_RESOLUTION,
            )
        except BkwAuthRejected as err:
            # The stored login is dead. Keep the state unknown and ask the
            # user for the password again.
            _LOGGER.warning(
                "The BKW login of %s is no longer valid: %s", self._entry.title, err
            )
            self._attr_native_value = None
            self._entry.async_start_reauth(self.hass)
            return
        except BkwError as err:
            # A temporary failure must not remove the entity. An unknown state
            # is better than a missing sensor.
            _LOGGER.warning(
                "Cannot read the BKW data of %s: %s", self._entry.title, err
            )
            self._attr_native_value = None
            return
        self._attr_native_value = api.latest_value(records)
        self._attr_last_reset = start
