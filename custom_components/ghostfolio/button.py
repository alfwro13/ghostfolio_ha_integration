"""Button platform for Ghostfolio integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.const import EntityCategory

from . import GhostfolioDataUpdateCoordinator, GhostfolioConfigEntry
from .const import DOMAIN, portfolio_device_info

async def async_setup_entry(
    hass: HomeAssistant,
    entry: GhostfolioConfigEntry,
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
    _attr_icon = "mdi:broom"

    def __init__(self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry):
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"ghostfolio_prune_button_{config_entry.entry_id}"
        self._attr_device_info = portfolio_device_info(config_entry)

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
        self._attr_icon = "mdi:eye-off-outline"
        self._attr_device_info = portfolio_device_info(config_entry)

    async def async_press(self) -> None:
        """Disable all watchlist limit entities of this type in the entity registry."""
        registry = er.async_get(self.hass)
        pattern = f"ghostfolio_watchlist_limit_{self.limit_type}_"

        for entity_entry in er.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            if entity_entry.disabled_by is not None:
                continue
            if entity_entry.domain == "number" and pattern in entity_entry.unique_id:
                registry.async_update_entity(
                    entity_entry.entity_id,
                    disabled_by=er.RegistryEntryDisabler.USER,
                )
