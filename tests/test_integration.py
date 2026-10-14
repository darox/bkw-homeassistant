"""Load the integration inside a real Home Assistant test instance."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bkw import const
from custom_components.bkw.const import DOMAIN
from tests import fixture_server

API = "custom_components.bkw.api"
DATA = {
    "username": fixture_server.USERNAME,
    "password": fixture_server.PASSWORD,
    "metering_point": "CH0001",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/bkw in every test."""
    yield


async def test_config_flow_creates_one_entry(hass: HomeAssistant) -> None:
    with patch(f"{API}.fetch_metering_points", AsyncMock(return_value=["CH0001"])):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] == "form"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": fixture_server.USERNAME, "password": fixture_server.PASSWORD},
        )
    assert result["type"] == "create_entry"
    assert result["data"] == DATA
    assert result["result"].unique_id == fixture_server.USERNAME


async def test_config_flow_wrong_password(hass: HomeAssistant) -> None:
    from custom_components.bkw.auth import BkwAuthRejected

    with patch(
        f"{API}.fetch_metering_points",
        AsyncMock(side_effect=BkwAuthRejected("invalid_grant", 400)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": fixture_server.USERNAME, "password": "wrong"},
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_config_flow_rejects_ambiguous_account(hass: HomeAssistant) -> None:
    with patch(f"{API}.fetch_metering_points", AsyncMock(return_value=["A", "B"])):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": fixture_server.USERNAME, "password": fixture_server.PASSWORD},
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "metering_point_required"}


async def test_sensor_reports_latest_consumption(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=fixture_server.USERNAME,
        unique_id=fixture_server.USERNAME,
        data=DATA,
    )
    entry.add_to_hass(hass)
    with patch(
        f"{API}.fetch_consumption",
        AsyncMock(return_value=[("2026-10-14T00:00:00.000Z", 2.5)]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    states = list(hass.states.async_all("sensor"))
    assert len(states) == 1
    assert states[0].state == "2.5"
    assert states[0].attributes["unit_of_measurement"] == "kWh"
    assert states[0].attributes["state_class"] == "total"


async def test_entry_against_real_fixture_api(
    hass: HomeAssistant, socket_enabled
) -> None:
    service = fixture_server.FixtureService()
    base = await service.start()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=fixture_server.USERNAME,
        unique_id=fixture_server.USERNAME,
        data=DATA,
    )
    entry.add_to_hass(hass)
    try:
        with patch.object(const, "API_BASE", base), patch.object(
            const, "TOKEN_URL", base + "/token"
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        states = list(hass.states.async_all("sensor"))
        assert len(states) == 1
        assert states[0].state == "2.5"
    finally:
        await service.stop()
