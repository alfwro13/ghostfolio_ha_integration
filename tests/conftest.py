"""Common fixtures for Ghostfolio tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ghostfolio.const import DOMAIN

# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "portfolio_name": "Test Portfolio",
    "base_url": "http://ghostfolio.local",
    "access_token": "test-token",
    "verify_ssl": False,
    "update_interval": 15,
    "show_totals": True,
    "show_accounts": True,
    "show_holdings": True,
    "show_watchlist": True,
    "show_fundamentals": False,
}

SAMPLE_ACCOUNTS = {
    "accounts": [
        {
            "id": "acc-1",
            "name": "Brokerage",
            "currency": "USD",
            "isExcluded": False,
            "balance": 5000.0,
        }
    ],
    "user": {"baseCurrency": "USD"},
}

SAMPLE_PERFORMANCE = {
    "performance": {
        "currentValueInBaseCurrency": 12000.0,
        "currentNetWorth": 17000.0,
        "netPerformance": 2000.0,
        "netPerformancePercentage": 0.2,
        "netPerformanceWithCurrencyEffect": 1900.0,
        "netPerformancePercentageWithCurrencyEffect": 0.19,
        "totalInvestment": 10000.0,
    }
}

SAMPLE_HOLDINGS = {"holdings": []}

SAMPLE_WATCHLIST: list = []

SAMPLE_PROVIDER_HEALTH = {"code": "YAHOO", "is_active": True, "status_code": 200}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=SAMPLE_CONFIG,
        title="Test Portfolio",
        unique_id="http://ghostfolio.local_test_portfolio",
    )


@pytest.fixture
def mock_api():
    """Return a pre-configured mock GhostfolioAPI."""
    api = MagicMock()
    api.authenticate = AsyncMock(return_value="fake-auth-token")
    api.get_accounts = AsyncMock(return_value=SAMPLE_ACCOUNTS)
    api.get_portfolio_performance = AsyncMock(return_value=SAMPLE_PERFORMANCE)
    api.get_holdings = AsyncMock(return_value=SAMPLE_HOLDINGS)
    api.get_watchlist = AsyncMock(return_value=SAMPLE_WATCHLIST)
    api.get_provider_health = AsyncMock(return_value=SAMPLE_PROVIDER_HEALTH)
    api.get_activities = AsyncMock(return_value={"activities": []})
    api.get_market_data = AsyncMock(return_value={"marketData": [], "assetProfile": {}})
    api.close = AsyncMock()
    api._get_session = MagicMock(return_value=MagicMock())
    return api


@pytest.fixture
async def setup_integration(hass, mock_config_entry, mock_api):
    """Set up the Ghostfolio integration with a mocked API."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.ghostfolio.GhostfolioAPI",
            return_value=mock_api,
        ),
        patch(
            "custom_components.ghostfolio._async_update_data_yahoo",
            return_value=None,
        ),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    return mock_config_entry
