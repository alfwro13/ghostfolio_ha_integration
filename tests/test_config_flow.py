"""Tests for the Ghostfolio config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ghostfolio.const import DOMAIN

from .conftest import SAMPLE_CONFIG, SAMPLE_PERFORMANCE


@pytest.fixture
def mock_api_for_flow():
    """Return a mock GhostfolioAPI suitable for config flow tests."""
    api = MagicMock()
    api.authenticate = AsyncMock(return_value="fake-token")
    api.get_portfolio_performance = AsyncMock(return_value=SAMPLE_PERFORMANCE)
    api.close = AsyncMock()
    return api


async def test_user_step_success(hass: HomeAssistant, mock_api_for_flow) -> None:
    """Happy path: valid credentials create a config entry."""
    with patch(
        "custom_components.ghostfolio.config_flow.GhostfolioAPI",
        return_value=mock_api_for_flow,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=SAMPLE_CONFIG
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["base_url"] == SAMPLE_CONFIG["base_url"]
    assert result["data"]["access_token"] == SAMPLE_CONFIG["access_token"]


async def test_user_step_cannot_connect(hass: HomeAssistant) -> None:
    """Connection error maps to 'cannot_connect' form error."""
    api = MagicMock()
    api.authenticate = AsyncMock(side_effect=Exception("connection refused"))
    api.close = AsyncMock()

    with patch(
        "custom_components.ghostfolio.config_flow.GhostfolioAPI",
        return_value=api,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=SAMPLE_CONFIG
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get("base") == "cannot_connect"


async def test_user_step_auth_failed(hass: HomeAssistant) -> None:
    """authenticate() returning None maps to 'auth_failed' form error."""
    api = MagicMock()
    api.authenticate = AsyncMock(return_value=None)
    api.close = AsyncMock()

    with patch(
        "custom_components.ghostfolio.config_flow.GhostfolioAPI",
        return_value=api,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=SAMPLE_CONFIG
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"].get("base") == "auth_failed"


async def test_user_step_invalid_url(hass: HomeAssistant) -> None:
    """URL without scheme maps to 'invalid_url' field error."""
    bad_input = {**SAMPLE_CONFIG, "base_url": "ghostfolio.local"}

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=bad_input
    )

    assert result["type"] == FlowResultType.FORM
    assert "base_url" in result["errors"]


async def test_duplicate_entry_aborts(hass: HomeAssistant, mock_api_for_flow) -> None:
    """Second setup with the same unique_id is aborted."""
    with patch(
        "custom_components.ghostfolio.config_flow.GhostfolioAPI",
        return_value=mock_api_for_flow,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=SAMPLE_CONFIG
        )
        await hass.async_block_till_done()

        # Second attempt with the same URL + portfolio name
        mock_api_for_flow.authenticate = AsyncMock(return_value="token2")
        mock_api_for_flow.get_portfolio_performance = AsyncMock(
            return_value=SAMPLE_PERFORMANCE
        )
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result2["flow_id"], user_input=SAMPLE_CONFIG
        )

    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"
