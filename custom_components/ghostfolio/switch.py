"""Switch platform for Ghostfolio integration."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import EntityCategory

from . import GhostfolioDataUpdateCoordinator
from .const import DOMAIN, CONF_PORTFOLIO_NAME


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Ghostfolio switch platform."""
    coordinator = entry.runtime_data
    
    async_add_entities([GhostfolioPauseSyncSwitch(coordinator, entry)])


class GhostfolioPauseSyncSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to temporarily pause polling from Ghostfolio."""

    _attr_has_entity_name = True
    _attr_name = "Pause Sync"
    _attr_icon = "mdi:sync-off"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry):
        """Initialize the switch."""
        super().__init__(coordinator)
        self.portfolio_name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")
        self._attr_unique_id = f"ghostfolio_pause_sync_{config_entry.entry_id}"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}")},
            "name": f"{self.portfolio_name} Portfolio",
            "manufacturer": "Ghostfolio",
            "model": "Portfolio Tracker",
        }

    @property
    def is_on(self) -> bool:
        """Return true if sync is currently paused."""
        return self.coordinator.sync_paused

    async def async_turn_on(self, **kwargs) -> None:
        """Pause the sync."""
        self.coordinator.sync_paused = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Resume the sync and immediately fetch fresh data."""
        self.coordinator.sync_paused = False
        self.async_write_ha_state()
        
        # Force a fresh update right now so you don't have to wait for the next 1-minute interval
        await self.coordinator.async_request_refresh()
