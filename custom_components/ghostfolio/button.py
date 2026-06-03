"""Button platform for Ghostfolio integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.const import EntityCategory

from . import GhostfolioDataUpdateCoordinator
from .const import DOMAIN, CONF_PORTFOLIO_NAME

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Ghostfolio button platform."""
    coordinator = entry.runtime_data

    async_add_entities([
        GhostfolioPruneButton(coordinator, entry),
        GhostfolioClearWatchlistLimitsButton(coordinator, entry, "high"),
        GhostfolioClearWatchlistLimitsButton(coordinator, entry, "low"),
    ])

class GhostfolioPruneButton(CoordinatorEntity, ButtonEntity):
    """Button to prune orphaned entities."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "prune_orphans"

    def __init__(self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry):
        """Initialize the button."""
        super().__init__(coordinator)
        self.portfolio_name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")
        self._attr_unique_id = f"ghostfolio_prune_button_{config_entry.entry_id}"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}")},
            "name": f"{self.portfolio_name} Portfolio",
            "manufacturer": "Ghostfolio",
            "model": "Portfolio Tracker",
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_prune_orphans()


class GhostfolioClearWatchlistLimitsButton(CoordinatorEntity, ButtonEntity):
    """Button to clear all watchlist high or low price limits."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry, limit_type: str):
        """Initialize the button."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.limit_type = limit_type
        self._attr_unique_id = f"ghostfolio_clear_watchlist_{limit_type}_limits_{config_entry.entry_id}"
        self._attr_translation_key = f"clear_watchlist_{limit_type}_limits"
        self._attr_icon = "mdi:arrow-up-circle-outline" if limit_type == "high" else "mdi:arrow-down-circle-outline"

        portfolio_name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}")},
            "name": f"{portfolio_name} Portfolio",
            "manufacturer": "Ghostfolio",
            "model": "Portfolio Tracker",
        }

    async def async_press(self) -> None:
        """Set all watchlist limits of this type to 0 (no limit)."""
        registry = er.async_get(self.hass)
        pattern = f"ghostfolio_watchlist_limit_{self.limit_type}_"

        for entity_entry in er.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            if entity_entry.disabled_by is not None:
                continue
            if entity_entry.domain == "number" and pattern in entity_entry.unique_id:
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": entity_entry.entity_id, "value": 0},
                    blocking=True,
                )
