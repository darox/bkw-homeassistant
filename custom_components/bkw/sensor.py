"""Sensor platform for the BKW Energy integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

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

from . import api, statistics
from .auth import BkwAuthRejected, BkwError
from .const import (  # noqa: F401
    CONF_QUARTER_HOUR,
    DEFAULT_RESOLUTION,
    DOMAIN,
    QUARTER_HOUR,
    QUARTER_HOUR_RESOLUTION,
    SCAN_INTERVAL,
    STATISTICS_WINDOW,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the sensors of the metering point of this entry."""
    data = entry.runtime_data
    entities: list[SensorEntity] = [BkwConsumptionSensor(entry, data)]
    if entry.options.get(CONF_QUARTER_HOUR):
        entities.append(BkwQuarterHourSensor(entry, data))
    async_add_entities(entities, True)


class BkwSensor(SensorEntity):
    """Base class for the energy sensors of one metering point."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = True

    def __init__(self, entry: ConfigEntry, data) -> None:
        self._entry = entry
        self._data = data
        self._unique = entry.unique_id or entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="BKW",
            model="Metering point",
        )

    async def _async_fetch(
        self, start: datetime, stop: datetime, resolution: str
    ) -> list[tuple[str, float]] | None:
        """Read the records. Return None when the read fails."""
        try:
            return await api.fetch_consumption(
                self._data.session,
                self._data.auth,
                start,
                stop,
                self._data.code,
                resolution,
            )
        except BkwAuthRejected as err:
            # The stored login is dead. Keep the state unknown and ask the
            # user for the password again.
            _LOGGER.warning(
                "The BKW login of %s is no longer valid: %s", self._entry.title, err
            )
            self._entry.async_start_reauth(self.hass)
        except BkwError as err:
            # A temporary failure must not remove the entity. An unknown state
            # is better than a missing sensor.
            _LOGGER.warning(
                "Cannot read the BKW data of %s: %s", self._entry.title, err
            )
        return None


class BkwConsumptionSensor(BkwSensor):
    """Energy of the last complete local day, in kWh."""

    _attr_translation_key = "consumption"

    def __init__(self, entry: ConfigEntry, data) -> None:
        super().__init__(entry, data)
        self._attr_unique_id = f"{self._unique}_{data.code}"

    async def async_update(self) -> None:
        """Read the energy of the last complete day and set the state."""
        today = dt_util.start_of_local_day()
        start = dt_util.start_of_local_day(today - timedelta(days=1))
        records = await self._async_fetch(start, today, DEFAULT_RESOLUTION)
        if records is None:
            self._attr_native_value = None
            return
        self._attr_native_value = api.latest_value(records)
        self._attr_last_reset = start


class BkwQuarterHourSensor(BkwSensor):
    """Energy of the newest BKW 15 minute interval, in kWh."""

    _attr_translation_key = "consumption_quarter"

    def __init__(self, entry: ConfigEntry, data) -> None:
        super().__init__(entry, data)
        self._attr_unique_id = f"{self._unique}_{data.code}_15min"

    async def async_update(self) -> None:
        """Read the newest 15 minute interval and set the state.

        The same records go into the statistics of Home Assistant, so the
        Energy dashboard shows the last complete day. A poll reads a window of
        some days again, so a correction of the meter data and a downtime of
        Home Assistant do not lose data.
        """
        today = dt_util.start_of_local_day()
        start = dt_util.start_of_local_day(today - STATISTICS_WINDOW)
        records = await self._async_fetch(
            start, dt_util.utcnow(), QUARTER_HOUR_RESOLUTION
        )
        if records is None:
            self._attr_native_value = None
            return
        await statistics.async_import(
            self.hass, self._data.code, f"{self._entry.title} consumption", records
        )
        record = api.latest_record(records)
        if record is None:
            self._attr_native_value = None
            return
        self._attr_native_value = record[1]
        # The timestamp of a record is the end of its interval. The total of
        # this sensor restarts at the start of the interval, so Home Assistant
        # counts each interval one time in the long-term statistics.
        self._attr_last_reset = api.parse_timestamp(record[0]) - QUARTER_HOUR
