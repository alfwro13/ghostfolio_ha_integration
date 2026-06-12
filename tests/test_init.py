"""Tests for integration setup, unload, and one entity per platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ghostfolio.const import DOMAIN

from .conftest import SAMPLE_CONFIG, SAMPLE_ACCOUNTS, SAMPLE_PERFORMANCE, SAMPLE_PROVIDER_HEALTH


@pytest.fixture
def mock_api_full():
    """Full mock API for integration-level setup tests."""
    api = MagicMock()
    api.authenticate = AsyncMock(return_value="token")
    api.get_accounts = AsyncMock(return_value=SAMPLE_ACCOUNTS)
    api.get_portfolio_performance = AsyncMock(return_value=SAMPLE_PERFORMANCE)
    api.get_holdings = AsyncMock(return_value={"holdings": []})
    api.get_watchlist = AsyncMock(return_value=[])
    api.get_provider_health = AsyncMock(return_value=SAMPLE_PROVIDER_HEALTH)
    api.get_activities = AsyncMock(return_value={"activities": []})
    api.get_market_data = AsyncMock(return_value={"marketData": [], "assetProfile": {}})
    api.close = AsyncMock()
    api._get_session = MagicMock(return_value=MagicMock())
    return api


async def _setup(hass: HomeAssistant, api) -> MockConfigEntry:
    """Helper: add a config entry and set up the integration."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=SAMPLE_CONFIG,
        title="Test Portfolio",
        unique_id="http://ghostfolio.local_test_portfolio",
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.ghostfolio.GhostfolioAPI", return_value=api),
        patch(
            "custom_components.ghostfolio.GhostfolioDataUpdateCoordinator._get_yahoo_crumb",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.ghostfolio.GhostfolioDataUpdateCoordinator._async_check_us_market_state",
            AsyncMock(return_value=None),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_setup_and_unload(hass: HomeAssistant, mock_api_full) -> None:
    """Integration loads successfully and unloads cleanly."""
    entry = await _setup(hass, mock_api_full)

    assert entry.state.value == "loaded"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state.value == "not_loaded"
    mock_api_full.close.assert_called_once()


async def test_sensor_entity_created(hass: HomeAssistant, mock_api_full) -> None:
    """At least one sensor entity is registered after setup."""
    entry = await _setup(hass, mock_api_full)
    registry = er.async_get(hass)
    sensors = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "sensor"
    ]
    assert len(sensors) > 0


async def test_binary_sensor_entity_created(hass: HomeAssistant, mock_api_full) -> None:
    """At least one binary_sensor entity (server connectivity) is registered."""
    entry = await _setup(hass, mock_api_full)
    registry = er.async_get(hass)
    binary_sensors = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "binary_sensor"
    ]
    assert len(binary_sensors) > 0


async def test_button_entity_created(hass: HomeAssistant, mock_api_full) -> None:
    """Prune button entity is registered after setup."""
    entry = await _setup(hass, mock_api_full)
    registry = er.async_get(hass)
    buttons = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "button"
    ]
    assert len(buttons) > 0


async def test_switch_entity_created(hass: HomeAssistant, mock_api_full) -> None:
    """Pause sync switch is registered after setup."""
    entry = await _setup(hass, mock_api_full)
    registry = er.async_get(hass)
    switches = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "switch"
    ]
    assert len(switches) > 0


async def test_portfolio_value_sensor_state(hass: HomeAssistant, mock_api_full) -> None:
    """Portfolio Value sensor reports the expected state from the mock API."""
    entry = await _setup(hass, mock_api_full)
    registry = er.async_get(hass)

    portfolio_value_entity = next(
        (
            e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.unique_id == f"ghostfolio_current_value_{entry.entry_id}"
        ),
        None,
    )
    assert portfolio_value_entity is not None

    state = hass.states.get(portfolio_value_entity.entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(12000.0)


async def test_server_binary_sensor_state(hass: HomeAssistant, mock_api_full) -> None:
    """Server connectivity sensor reports 'on' when API succeeds."""
    entry = await _setup(hass, mock_api_full)
    registry = er.async_get(hass)

    server_entity = next(
        (
            e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.unique_id == f"ghostfolio_server_status_{entry.entry_id}"
        ),
        None,
    )
    assert server_entity is not None

    state = hass.states.get(server_entity.entity_id)
    assert state is not None
    assert state.state == "on"
