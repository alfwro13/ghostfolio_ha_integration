"""Diagnostics support for the Ghostfolio integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import GhostfolioConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: GhostfolioConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    # --- Config (access token redacted) ---
    config = {k: v for k, v in entry.data.items() if k != "access_token"}
    config["access_token"] = "**REDACTED**"

    # --- Coordinator state ---
    coord_state: dict[str, Any] = {
        "last_update_success": coordinator.last_update_success,
        "sync_paused": coordinator.sync_paused,
        "us_market_open": coordinator.us_market_open,
        "last_fundamentals_update": (
            coordinator.last_fundamentals_update.isoformat()
            if coordinator.last_fundamentals_update else None
        ),
        "last_previous_close_update": (
            coordinator.last_previous_close_update.isoformat()
            if coordinator.last_previous_close_update else None
        ),
        "last_dividends_update": (
            coordinator.last_dividends_update.isoformat()
            if coordinator.last_dividends_update else None
        ),
        "fundamentals_tickers": sorted(coordinator.fundamentals_cache.keys()),
        "previous_close_tickers": sorted(coordinator.previous_close_cache.keys()),
        "premarket_tickers": sorted(coordinator.premarket_cache.keys()),
    }

    # --- Data summary (no personal values, just shape/health) ---
    data = coordinator.data or {}
    account_holdings = data.get("account_holdings", {})
    providers = data.get("providers", {})

    data_summary: dict[str, Any] = {
        "server_online": data.get("server_online", False),
        "account_count": len(account_holdings),
        "holdings_per_account": {
            acc_id: len(holdings)
            for acc_id, holdings in account_holdings.items()
        },
        "watchlist_count": len(data.get("watchlist", [])),
        "providers": {
            code: info.get("is_active")
            for code, info in providers.items()
        },
    }

    # --- Entity registry summary ---
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    entity_summary: dict[str, Any] = {
        "total": len(entries),
        "by_platform": {},
        "disabled_count": sum(1 for e in entries if e.disabled_by is not None),
    }
    for entity_entry in entries:
        platform = entity_entry.domain
        entity_summary["by_platform"][platform] = entity_summary["by_platform"].get(platform, 0) + 1

    return {
        "integration_version": "0.10.1",
        "config": config,
        "coordinator": coord_state,
        "data_summary": data_summary,
        "entities": entity_summary,
    }
