"""Tests for GhostfolioDataUpdateCoordinator."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ghostfolio import GhostfolioDataUpdateCoordinator
from custom_components.ghostfolio.api import GhostfolioAPI
from custom_components.ghostfolio.const import DOMAIN

from .conftest import (
    SAMPLE_ACCOUNTS,
    SAMPLE_CONFIG,
    SAMPLE_HOLDINGS,
    SAMPLE_PERFORMANCE,
    SAMPLE_PROVIDER_HEALTH,
    SAMPLE_WATCHLIST,
)


@pytest.fixture
def coordinator(hass: HomeAssistant, mock_api) -> GhostfolioDataUpdateCoordinator:
    """Return a coordinator wired to the mock API (not yet refreshed)."""
    entry = MockConfigEntry(domain=DOMAIN, data=SAMPLE_CONFIG)
    entry.add_to_hass(hass)
    return GhostfolioDataUpdateCoordinator(hass, mock_api, 15, entry)


async def test_successful_update(
    hass: HomeAssistant, coordinator: GhostfolioDataUpdateCoordinator, mock_api
) -> None:
    """A clean API response produces server_online=True and expected keys."""
    with patch.object(
        coordinator, "_get_yahoo_crumb", AsyncMock(return_value=None)
    ), patch.object(
        coordinator, "_async_check_us_market_state", AsyncMock(return_value=None)
    ):
        await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    data = coordinator.data
    assert data is not None
    assert data["server_online"] is True
    assert "acc-1" in data["account_holdings"]
    assert data["global_performance"] == SAMPLE_PERFORMANCE


async def test_update_failed_on_api_error(
    hass: HomeAssistant, coordinator: GhostfolioDataUpdateCoordinator, mock_api
) -> None:
    """API failure raises UpdateFailed and leaves last_update_success False."""
    mock_api.get_accounts = AsyncMock(side_effect=Exception("timeout"))

    with patch.object(
        coordinator, "_get_yahoo_crumb", AsyncMock(return_value=None)
    ), patch.object(
        coordinator, "_async_check_us_market_state", AsyncMock(return_value=None)
    ):
        await coordinator.async_refresh()

    assert coordinator.last_update_success is False


async def test_sync_paused_returns_cached_data(
    hass: HomeAssistant, coordinator: GhostfolioDataUpdateCoordinator, mock_api
) -> None:
    """When sync is paused, the coordinator returns its last-known data unchanged."""
    # Prime with a successful update first
    with patch.object(
        coordinator, "_get_yahoo_crumb", AsyncMock(return_value=None)
    ), patch.object(
        coordinator, "_async_check_us_market_state", AsyncMock(return_value=None)
    ):
        await coordinator.async_refresh()

    first_data = coordinator.data
    assert first_data is not None

    # Pause sync and change the API response — coordinator should NOT call the API
    await coordinator.async_set_sync_paused(True)
    mock_api.get_accounts = AsyncMock(return_value={"accounts": []})

    await coordinator.async_refresh()

    # Data must be identical (same object, not re-fetched)
    assert coordinator.data is first_data
