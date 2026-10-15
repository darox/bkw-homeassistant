"""Test the BKW data in the statistics of Home Assistant."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    statistics_during_period,
    valid_statistic_id,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bkw import const, statistics
from custom_components.bkw.const import DOMAIN

from . import fixture_server

API = "custom_components.bkw.api"
USERNAME = fixture_server.USERNAME
REFRESH = fixture_server.REFRESH_TOKEN
DATA = {
    "username": USERNAME,
    "metering_point": "CH0001",
    "refresh_token": REFRESH,
}
STAT_ID = "bkw:ch0001"

# The timestamp of a record is the end of its interval, so the first record
# carries the energy of 12 October and the second record the energy of
# 13 October.
RECORDS = [
    ("2026-10-13T00:00:00.000Z", 1.0),
    ("2026-10-14T00:00:00.000Z", 2.0),
]
DAY_1 = datetime(2026, 10, 12, tzinfo=timezone.utc)
DAY_2 = datetime(2026, 10, 13, tzinfo=timezone.utc)
DAY_3 = datetime(2026, 10, 14, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/bkw in every test."""
    yield


@pytest.fixture
def mock_recorder_before_hass(recorder_db_url):
    """Prepare the recorder database before Home Assistant starts."""


@pytest.fixture
async def api(socket_enabled):
    """Run the fixture API and point the integration at it."""
    service = fixture_server.FixtureService()
    base = await service.start()
    with patch.object(const, "API_BASE", base), patch.object(
        const, "TOKEN_URL", base + "/token"
    ):
        yield service
    await service.stop()


def _entry() -> MockConfigEntry:
    """Return a config entry of the metering point."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        unique_id=USERNAME,
        data=DATA,
    )


async def _async_setup(hass: HomeAssistant, records: list[tuple[str, float]]):
    """Set up the entry and let the sensor poll with the given records."""
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(f"{API}.fetch_consumption", AsyncMock(return_value=list(records))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _async_rows(hass: HomeAssistant) -> list[tuple[datetime, float, float]]:
    """Return (start, state, sum) of the stored statistics, oldest first."""
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 11, 1, tzinfo=timezone.utc),
        {STAT_ID},
        "hour",
        None,
        {"state", "sum"},
    )
    return [
        (
            datetime.fromtimestamp(row["start"], timezone.utc),
            row["state"],
            row["sum"],
        )
        for row in rows.get(STAT_ID, [])
    ]


def test_a_day_record_lands_on_the_start_of_its_day() -> None:
    """The timestamp of a record is the end of its day. A bad record is left out."""
    days = statistics.day_records(RECORDS + [("not a time", 99.0)])
    assert list(days) == [DAY_1, DAY_2]
    assert days[DAY_1] == 1.0
    assert days[DAY_2] == 2.0


def test_the_statistic_id_of_the_metering_point_is_valid() -> None:
    """Home Assistant accepts the id only in the form `bkw:slug`."""
    assert statistics.statistic_id("CH0001") == STAT_ID
    assert valid_statistic_id(STAT_ID)


async def test_the_records_become_day_statistics(
    hass: HomeAssistant, api, recorder_mock
) -> None:
    """The Energy dashboard reads the records of each day at the day itself."""
    entry = await _async_setup(hass, RECORDS)
    await recorder_mock.async_block_till_done()

    assert await _async_rows(hass) == [
        (DAY_1, 1.0, 1.0),
        (DAY_2, 2.0, 3.0),
    ]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_long_downtime_does_not_lose_the_records(
    hass: HomeAssistant, api, recorder_mock
) -> None:
    """The import reads a window of days. The sum continues the stored sum."""
    entry = await _async_setup(hass, RECORDS[:1])
    await recorder_mock.async_block_till_done()
    assert await _async_rows(hass) == [(DAY_1, 1.0, 1.0)]

    # A downtime. The next poll reads a wider window, with new records.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    wider = RECORDS + [("2026-10-15T00:00:00.000Z", 2.0)]
    entry = await _async_setup(hass, wider)
    await recorder_mock.async_block_till_done()

    assert await _async_rows(hass) == [
        (DAY_1, 1.0, 1.0),
        (DAY_2, 2.0, 3.0),
        (DAY_3, 2.0, 5.0),
    ]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_the_sum_continues_when_the_previous_day_is_missing(
    hass: HomeAssistant, recorder_mock
) -> None:
    """An overlapping row keeps its base sum, also after a missing day."""
    first_import = [
        ("2026-10-13T00:00:00.000Z", 1.0),
        ("2026-10-15T00:00:00.000Z", 2.0),
    ]
    await statistics.async_import(hass, "CH0001", "Test", first_import)
    await hass.async_block_till_done()
    await recorder_mock.async_block_till_done()
    assert await _async_rows(hass) == [
        (DAY_1, 1.0, 1.0),
        (DAY_3, 2.0, 3.0),
    ]

    second_import = [("2026-10-15T00:00:00.000Z", 2.0)]
    await statistics.async_import(hass, "CH0001", "Test", second_import)
    await hass.async_block_till_done()
    await recorder_mock.async_block_till_done()
    assert await _async_rows(hass) == [
        (DAY_1, 1.0, 1.0),
        (DAY_3, 2.0, 3.0),
    ]


async def test_a_second_poll_keeps_the_same_statistics(
    hass: HomeAssistant, api, recorder_mock
) -> None:
    """The data of the last days arrives again at each poll. No row changes."""
    entry = await _async_setup(hass, RECORDS)
    await recorder_mock.async_block_till_done()
    first = await _async_rows(hass)
    assert first == [
        (DAY_1, 1.0, 1.0),
        (DAY_2, 2.0, 3.0),
    ]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    entry = await _async_setup(hass, RECORDS)
    await recorder_mock.async_block_till_done()

    assert await _async_rows(hass) == first

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
