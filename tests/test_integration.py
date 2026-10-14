"""Load the integration inside a real Home Assistant test instance."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bkw import const
from custom_components.bkw.const import DOMAIN
from tests import fixture_server

API = "custom_components.bkw.api"
USERNAME = fixture_server.USERNAME
PASSWORD = fixture_server.PASSWORD
REFRESH = fixture_server.REFRESH_TOKEN
DATA = {
    "username": USERNAME,
    "metering_point": "CH0001",
    "refresh_token": REFRESH,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/bkw in every test."""
    yield


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


def _entry(data: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        unique_id=USERNAME,
        data=DATA if data is None else data,
    )


def _flow_sources(hass: HomeAssistant) -> list[str]:
    return [
        flow["context"]["source"] for flow in hass.config_entries.flow.async_progress()
    ]


async def test_config_flow_creates_one_entry(hass: HomeAssistant, api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": USERNAME, "password": PASSWORD}
    )
    assert result["type"] == "create_entry"
    assert result["data"] == DATA
    assert result["result"].unique_id == USERNAME


async def test_config_flow_stores_no_password(hass: HomeAssistant, api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": USERNAME, "password": PASSWORD}
    )
    assert "password" not in result["data"]


async def test_config_flow_wrong_password(hass: HomeAssistant, api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": USERNAME, "password": "wrong"}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_config_flow_rejects_ambiguous_account(hass: HomeAssistant, api) -> None:
    api.metering_points = [
        {"meteringPointCode": "A", "description": "One"},
        {"meteringPointCode": "B", "description": "Two"},
    ]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": USERNAME, "password": PASSWORD}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "metering_point_required"}


async def test_config_flow_aborts_on_an_empty_account(
    hass: HomeAssistant, api
) -> None:
    api.metering_points = []
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": USERNAME, "password": PASSWORD}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "no_metering_point"


async def test_config_flow_cannot_connect(hass: HomeAssistant, api) -> None:
    with patch.object(const, "API_BASE", "http://127.0.0.1:1"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": USERNAME, "password": PASSWORD}
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_sensor_reports_latest_consumption(hass: HomeAssistant, api) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    states = list(hass.states.async_all("sensor"))
    assert len(states) == 1
    assert states[0].state == "2.5"
    assert states[0].attributes["unit_of_measurement"] == "kWh"
    assert states[0].attributes["state_class"] == "total"


async def test_entity_unique_id_is_stable(hass: HomeAssistant, api) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    states = list(hass.states.async_all("sensor"))
    registry = er.async_get(hass)
    assert registry.async_get(states[0].entity_id).unique_id == f"{USERNAME}_CH0001"


async def test_sensor_state_is_unknown_when_a_poll_fails(
    hass: HomeAssistant, api
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch.object(const, "API_BASE", "http://127.0.0.1:1"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    states = list(hass.states.async_all("sensor"))
    assert len(states) == 1
    assert states[0].state == "unknown"


async def test_sensor_starts_reauth_when_the_login_is_dead(
    hass: HomeAssistant, api
) -> None:
    entry = _entry({**DATA, "refresh_token": "dead"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    states = list(hass.states.async_all("sensor"))
    assert len(states) == 1
    assert states[0].state == "unknown"
    assert SOURCE_REAUTH in _flow_sources(hass)


async def test_setup_without_a_metering_point_retries_on_a_transient_failure(
    hass: HomeAssistant, api
) -> None:
    entry = _entry({"username": USERNAME, "refresh_token": REFRESH})
    entry.add_to_hass(hass)
    with patch.object(const, "API_BASE", "http://127.0.0.1:1"):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state.name == "SETUP_RETRY"


async def test_reauth_flow_stores_a_new_refresh_token(
    hass: HomeAssistant, api
) -> None:
    entry = _entry({**DATA, "refresh_token": "dead"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": PASSWORD}
    )
    assert result["type"] == "abort"
    assert entry.data["refresh_token"] == REFRESH
    assert "password" not in entry.data


async def test_reconfigure_flow_changes_the_metering_point(
    hass: HomeAssistant, api
) -> None:
    api.metering_points = [{"meteringPointCode": "CH0002", "description": "New"}]
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"metering_point": "CH0002"}
    )
    assert result["type"] == "abort"
    assert entry.data["metering_point"] == "CH0002"


async def test_legacy_password_entry_is_upgraded(hass: HomeAssistant, api) -> None:
    entry = _entry(
        {"username": USERNAME, "password": PASSWORD, "metering_point": "CH0001"}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data["refresh_token"] == REFRESH
    assert "password" not in entry.data


async def test_sensor_reads_the_last_complete_day(hass: HomeAssistant, api) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    mock = AsyncMock(return_value=[("2026-10-13T00:00:00.000Z", 2.5)])
    with patch(f"{API}.fetch_consumption", mock):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    _session, _auth, start, stop, code, _resolution = mock.await_args.args
    assert stop == dt_util.start_of_local_day()
    assert start == dt_util.start_of_local_day(stop - timedelta(days=1))
    assert code == "CH0001"
    states = list(hass.states.async_all("sensor"))
    assert len(states) == 1
    assert states[0].state == "2.5"


async def test_sensor_state_is_unknown_without_records(
    hass: HomeAssistant, api
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(f"{API}.fetch_consumption", AsyncMock(return_value=[])):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    states = list(hass.states.async_all("sensor"))
    assert len(states) == 1
    assert states[0].state == "unknown"
