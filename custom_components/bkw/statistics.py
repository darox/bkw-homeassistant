"""Write the BKW meter data into the statistics of Home Assistant.

The BKW API gives the meter data of a complete day about one day late. A sensor
can show a day only when its data arrives, so the state of a sensor changes
about one day after the day of its data. This module writes the records into
the statistics of Home Assistant with the timestamp of the day of the data, so
the Energy dashboard shows each day at the day it belongs to.

Home Assistant keeps the long-term statistics of an external source as hour
values. The source of the statistics is `bkw`, so the Energy dashboard shows
them next to the sensors.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.recorder import DATA_INSTANCE
from homeassistant.util import slugify
from homeassistant.util.unit_conversion import EnergyConverter

from . import api
from .const import DAY, DOMAIN

if TYPE_CHECKING:
    from homeassistant.components.recorder import Recorder

_LOGGER = logging.getLogger(__name__)


def statistic_id(code: str) -> str:
    """Return the id of the imported statistic of one metering point."""
    return f"{DOMAIN}:{slugify(code)}"


def day_records(records: list[tuple[str, float]]) -> dict[datetime, float]:
    """Map the start of each day to the energy of that day.

    The timestamp of a record is the end of its interval, so the key of the
    result is the start of the day of that interval. A record with a bad
    timestamp is left out. A repeated day replaces the earlier value, so a
    correction of the API does not count the day two times. The result is
    sorted by time.
    """
    days: dict[datetime, float] = {}
    for stamp, value in records:
        try:
            end = api.parse_timestamp(stamp)
        except ValueError:
            continue
        days[end - DAY] = value
    return dict(sorted(days.items()))


async def async_import(
    hass: HomeAssistant, code: str, name: str, records: list[tuple[str, float]]
) -> None:
    """Write the records of a metering point into the statistics.

    Home Assistant without the recorder has no statistics. Then this function
    does nothing.
    """
    if DATA_INSTANCE not in hass.data:
        return
    days = day_records(records)
    if not days:
        return
    stat_id = statistic_id(code)
    instance = get_instance(hass)
    first = next(iter(days))
    last = next(reversed(days))
    try:
        total = await _async_last_sum(hass, instance, stat_id, first, last)
        statistics: list[StatisticData] = []
        for start, value in days.items():
            total += value
            statistics.append(StatisticData(start=start, state=value, sum=total))
        async_add_external_statistics(
            hass,
            StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=name,
                source=DOMAIN,
                statistic_id=stat_id,
                unit_class=EnergyConverter.UNIT_CLASS,
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            ),
            statistics,
        )
    except HomeAssistantError as err:
        # A wrong statistic must not stop the data poll of the sensors.
        _LOGGER.warning("Cannot write the BKW statistics of %s: %s", name, err)


async def _async_last_sum(
    hass: HomeAssistant,
    instance: Recorder,
    stat_id: str,
    first: datetime,
    last: datetime,
) -> float:
    """Return the stored sum just before the first record.

    The import window can overlap rows that are already stored. Derive the
    base sum from the earliest overlapping row, so a correction does not
    recount older data. If no row overlaps, use the newest row before the
    window. Return 0.0 when the statistic is new.
    """
    rows = await instance.async_add_executor_job(
        statistics_during_period,
        hass,
        first,
        last + DAY,
        {stat_id},
        "hour",
        None,
        {"state", "sum"},
    )
    for row in rows.get(stat_id, []):
        state = row.get("state")
        total = row.get("sum")
        if state is not None and total is not None:
            return float(total) - float(state)

    rows = await instance.async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(1970, 1, 1, tzinfo=timezone.utc),
        first,
        {stat_id},
        "hour",
        None,
        {"sum"},
    )
    for row in reversed(rows.get(stat_id, [])):
        total = row.get("sum")
        if total is not None:
            return float(total)
    return 0.0
