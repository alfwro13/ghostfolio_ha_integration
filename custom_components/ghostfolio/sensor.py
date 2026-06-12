"""Sensor platform for Ghostfolio integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from . import GhostfolioDataUpdateCoordinator
from .const import (
    CONF_PORTFOLIO_NAME,
    CONF_SHOW_TOTALS,
    CONF_SHOW_ACCOUNTS,
    CONF_SHOW_HOLDINGS,
    CONF_SHOW_WATCHLIST,
    CONF_SHOW_FUNDAMENTALS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ghostfolio sensor platform."""
    coordinator = config_entry.runtime_data
    
    show_totals = config_entry.data.get(CONF_SHOW_TOTALS, True)
    show_accounts = config_entry.data.get(CONF_SHOW_ACCOUNTS, True)
    show_holdings = config_entry.data.get(CONF_SHOW_HOLDINGS, True)
    show_watchlist = config_entry.data.get(CONF_SHOW_WATCHLIST, True)
    show_fundamentals = config_entry.data.get(CONF_SHOW_FUNDAMENTALS, False)

    known_ids: set[str] = set()

    if show_totals:
        global_sensors = [
            GhostfolioCurrentValueSensor(coordinator, config_entry),
            GhostfolioNetPerformanceSensor(coordinator, config_entry),
            GhostfolioUnrealizedPnLSensor(coordinator, config_entry),
            GhostfolioTimeWeightedReturnSensor(coordinator, config_entry),
            GhostfolioTotalInvestmentSensor(coordinator, config_entry),
            GhostfolioNetPerformanceWithCurrencySensor(coordinator, config_entry),
            GhostfolioTimeWeightedReturnFXSensor(coordinator, config_entry),
            GhostfolioSimpleGainPercentSensor(coordinator, config_entry),
            GhostfolioUnrealizedPnLPercentSensor(coordinator, config_entry),
            GhostfolioPortfolioDividendSensor(coordinator, config_entry),
        ]
        async_add_entities(global_sensors)
        for s in global_sensors:
            known_ids.add(s.unique_id)

    @callback
    def _update_sensors():
        """Dynamically add or update sensors when data changes."""
        if not coordinator.data:
            return
        new_entities = []
        accounts_data = coordinator.data.get("accounts", {}).get("accounts", [])

        for account in accounts_data:
            if account.get("isExcluded", False):
                continue
                
            account_id = account.get("id")
            account_name = account.get("name", "Unknown Account")
            if not account_id:
                continue

            # Process Per-Account Sensors
            if show_accounts:
                account_sensors = [
                    GhostfolioAccountValueSensor(coordinator, config_entry, account),
                    GhostfolioAccountNetWorthSensor(coordinator, config_entry, account),
                    GhostfolioAccountCostSensor(coordinator, config_entry, account),
                    GhostfolioAccountPerformanceSensor(coordinator, config_entry, account),
                    GhostfolioAccountUnrealizedPnLSensor(coordinator, config_entry, account),
                    GhostfolioAccountTWRSensor(coordinator, config_entry, account),
                    GhostfolioAccountSimpleGainSensor(coordinator, config_entry, account),
                    GhostfolioAccountUnrealizedPnLPercentSensor(coordinator, config_entry, account),
                    GhostfolioAccountDividendSensor(coordinator, config_entry, account),
                    GhostfolioAccountCashBalanceSensor(coordinator, config_entry, account),
                ]
                for sens in account_sensors:
                    if sens.unique_id not in known_ids:
                        new_entities.append(sens)
                        known_ids.add(sens.unique_id)

            # Process Per-Holding Sensors
            if show_holdings:
                holdings_map = coordinator.data.get("account_holdings", {})
                holdings_list = holdings_map.get(account_id, [])
                for holding in holdings_list:
                    if float(holding.get("quantity") or 0) > 0:
                        # FILTER OUT CASH FROM HOLDINGS
                        if holding.get("assetClass") == "LIQUIDITY":
                            continue
                            
                        symbol = holding.get("symbol")
                        safe_symbol = slugify(symbol)
                        unique_id = f"ghostfolio_holding_{account_id}_{safe_symbol}_{config_entry.entry_id}"
                        
                        if unique_id not in known_ids:
                            new_entities.append(
                                GhostfolioHoldingSensor(
                                    coordinator, config_entry, account_id, account_name, holding
                                )
                            )
                            known_ids.add(unique_id)

        # Process Watchlist Sensors
        if show_watchlist:
            watchlist_items = coordinator.data.get("watchlist", [])
            for item in watchlist_items:
                symbol = item.get("symbol")
                safe_symbol = slugify(symbol)
                unique_id = f"ghostfolio_watchlist_{safe_symbol}_{config_entry.entry_id}"
                
                if unique_id not in known_ids:
                    new_entities.append(GhostfolioWatchlistSensor(coordinator, config_entry, item))
                    known_ids.add(unique_id)

        # Process Fundamentals Sensors
        if show_fundamentals:
            fund_payload = coordinator.data.get("fundamentals_data", {})
            for symbol in fund_payload.keys():
                safe_symbol = slugify(symbol)
                fund_id = f"ghostfolio_fundamentals_{safe_symbol}_{config_entry.entry_id}"
                
                if fund_id not in known_ids:
                    new_entities.append(GhostfolioFundamentalsSensor(coordinator, config_entry, symbol))
                    known_ids.add(fund_id)

        if new_entities:
            async_add_entities(new_entities)

    config_entry.async_on_unload(coordinator.async_add_listener(_update_sensors))
    _update_sensors()


class GhostfolioBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Ghostfolio sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the base sensor."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.portfolio_name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")
        device_id = f"ghostfolio_portfolio_{config_entry.entry_id}"
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"{self.portfolio_name} Portfolio",
            "manufacturer": "Ghostfolio",
            "model": "Portfolio Tracker",
        }

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Determine the base currency dynamically."""
        if not self.coordinator.data: 
            return "EUR"
            
        payload = self.coordinator.data.get("accounts", {})
        user_currency = payload.get("user", {}).get("baseCurrency")
        
        if user_currency: 
            return user_currency
        if "baseCurrency" in payload: 
            return payload["baseCurrency"]
            
        accounts_list = payload.get("accounts", [])
        if accounts_list: 
            return accounts_list[0].get("currency", "EUR")
            
        return "EUR"

    @property
    def global_performance_data(self) -> dict[str, Any]:
        """Fetch the performance payload."""
        if not self.coordinator.data: 
            return {}
        return self.coordinator.data.get("global_performance", {}).get("performance", {})

    def _is_provider_down(self, data_source: str | None) -> bool:
        """Check if an upstream data provider is down."""
        if not data_source or not self.coordinator.data: 
            return False
            
        providers = self.coordinator.data.get("providers", {})
        info = providers.get(data_source)
        return info and not info.get("is_active", True)

    @property
    def is_portfolio_healthy(self) -> bool:
        """Check if all assets in the portfolio are returning valid data."""
        if not self.coordinator.data: 
            return True
            
        all_holdings = self.coordinator.data.get("account_holdings", {})
        for holdings in all_holdings.values():
            for h in holdings:
                if float(h.get("quantity") or 0) > 0 and h.get("assetClass") != "LIQUIDITY":
                    if self._is_provider_down(h.get("dataSource")): 
                        return False
                     
                    val = float(h.get("valueInBaseCurrency") or h.get("value") or 0)
                    price = float(h.get("marketPrice") or 0)
                    if val <= 0 or price <= 0: 
                        return False
                     
        return True

    def _calculate_unrealized_pnl(self, target_account_id: str | None = None) -> tuple[float, float]:
        """Helper to safely calculate true unrealized P&L strictly from active equities."""
        if not self.coordinator.data:
            return 0.0, 0.0

        holdings_map = self.coordinator.data.get("account_holdings", {})
        total_pnl = 0.0
        total_cost = 0.0

        accounts_to_scan = [target_account_id] if target_account_id else list(holdings_map.keys())

        for acc_id in accounts_to_scan:
            holdings_list = holdings_map.get(acc_id)
            if not holdings_list:
                continue
                
            for data in holdings_list:
                # FILTER OUT CASH to ensure it doesn't inflate your active investment cost
                if data.get("assetClass") == "LIQUIDITY":
                    continue
                    
                try:
                    quantity = float(data.get("quantity") or 0)
                    if quantity > 0:
                        cost = float(data.get("investment") or 0)
                        val = float(data.get("valueInBaseCurrency") or data.get("value") or 0)
                        total_pnl += (val - cost)
                        total_cost += cost
                except (ValueError, TypeError):
                    continue

        return total_pnl, total_cost


# ==========================================
# GLOBAL SENSORS
# ==========================================

class GhostfolioCurrentValueSensor(GhostfolioBaseSensor):
    """Sensor tracking the overall portfolio value."""

    _attr_name = "Portfolio Value"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the global value sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_current_value_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        """Return the native value."""
        if not self.is_portfolio_healthy: 
            return None
        return self.global_performance_data.get("currentValueInBaseCurrency")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Provide net worth as an attribute."""
        if not self.coordinator.data: 
            return None
        return {"current_net_worth": self.global_performance_data.get("currentNetWorth")}


class GhostfolioNetPerformanceSensor(GhostfolioBaseSensor):
    """Sensor tracking Total Gain (Native Ghostfolio Math)."""

    _attr_name = "Portfolio Gain"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the global gain sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        """Return the native net performance."""
        if not self.is_portfolio_healthy: 
            return None
        return self.global_performance_data.get("netPerformance")


class GhostfolioUnrealizedPnLSensor(GhostfolioBaseSensor):
    """Sensor tracking true global Unrealized P&L."""

    _attr_name = "Portfolio Unrealized P&L"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the global unrealized pnl sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_unrealized_pnl_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        """Return the calculated P&L value."""
        if not self.coordinator.data or not self.coordinator.data.get("server_online", False):
            return None
        pnl, _ = self._calculate_unrealized_pnl()
        return round(pnl, 2)


class GhostfolioTimeWeightedReturnSensor(GhostfolioBaseSensor):
    """Sensor tracking strategy TWR %."""

    _attr_name = "Time-Weighted Return %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the global TWR sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_percent_{config_entry.entry_id}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Force percentage as the unit."""
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Return the calculated TWR percentage."""
        if not self.is_portfolio_healthy: 
            return None
        percent_value = self.global_performance_data.get("netPerformancePercentage")
        return round(percent_value * 100, 2) if percent_value is not None else None


class GhostfolioTotalInvestmentSensor(GhostfolioBaseSensor):
    """Sensor tracking the portfolio total cost."""

    _attr_name = "Portfolio Cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the global cost sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_total_investment_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        """Return the total investment amount."""
        if not self.is_portfolio_healthy: 
            return None
        return self.global_performance_data.get("totalInvestment")


class GhostfolioTimeWeightedReturnFXSensor(GhostfolioBaseSensor):
    """Sensor tracking TWR % including FX effects."""

    _attr_name = "Time-Weighted Return FX %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the global FX TWR sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_percent_with_currency_{config_entry.entry_id}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Force percentage as the unit."""
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Return the FX TWR percentage."""
        if not self.is_portfolio_healthy: 
            return None
        percent_value = self.global_performance_data.get("netPerformancePercentageWithCurrencyEffect")
        return round(percent_value * 100, 2) if percent_value is not None else None


class GhostfolioNetPerformanceWithCurrencySensor(GhostfolioBaseSensor):
    """Sensor tracking global gain including FX effects."""

    _attr_name = "Portfolio Gain FX"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the global FX gain sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_with_currency_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        """Return the FX gain value."""
        if not self.is_portfolio_healthy: 
            return None
        return self.global_performance_data.get("netPerformanceWithCurrencyEffect")


class GhostfolioSimpleGainPercentSensor(GhostfolioBaseSensor):
    """Sensor tracking true simple return %."""

    _attr_name = "Simple Gain %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the simple return sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_simple_gain_percent_{config_entry.entry_id}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Force percentage as the unit."""
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Calculate Simple Gain % based on Native Gain logic."""
        if not self.is_portfolio_healthy: 
            return None
        pnl = self.global_performance_data.get("netPerformance")
        cost = self.global_performance_data.get("totalInvestment")
        if pnl is not None and cost and cost > 0: 
            return round((pnl / cost) * 100, 2)
        return 0.0


class GhostfolioUnrealizedPnLPercentSensor(GhostfolioBaseSensor):
    """Sensor tracking true global Unrealized Gain %."""

    _attr_name = "Unrealized Gain %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the global unrealized return sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_unrealized_pnl_percent_{config_entry.entry_id}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Force percentage as the unit."""
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Calculate Unrealized Gain %."""
        if not self.coordinator.data or not self.coordinator.data.get("server_online", False):
            return None
        pnl, cost = self._calculate_unrealized_pnl()
        if cost <= 0:
            return 0.0
        return round((pnl / cost) * 100, 2)


class GhostfolioPortfolioDividendSensor(GhostfolioBaseSensor):
    """Sensor tracking total global dividends."""

    _attr_name = "Portfolio Total Dividend"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        """Initialize the global dividend sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_portfolio_dividends_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        """Return the total accumulated dividends."""
        if not self.is_portfolio_healthy: 
            return None
        if not self.coordinator.data: 
            return None
            
        dividends = self.coordinator.data.get("dividends", {})
        
        total = 0.0
        for acc_divs in dividends.values():
            total += sum(acc_divs.values())
            
        return total


# ==========================================
# PER-ACCOUNT SENSORS
# ==========================================

class GhostfolioAccountBaseSensor(GhostfolioBaseSensor):
    """Base logic specifically for individual account sensors."""

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account base sensor."""
        super().__init__(coordinator, config_entry)
        self.account_id = account_data["id"]
        self.account_name = account_data["name"]
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_account_{self.account_id}_{config_entry.entry_id}")},
            "name": self.account_name, 
            "manufacturer": "Ghostfolio",
            "model": "Account Portfolio",
            "via_device": (DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}"),
        }

    @property
    def account_performance_data(self) -> dict[str, Any]:
        """Fetch the performance data tied strictly to this account."""
        if not self.coordinator.data: 
            return {}
        performances = self.coordinator.data.get("account_performances", {})
        return performances.get(self.account_id, {}).get("performance", {})

    @property
    def is_account_healthy(self) -> bool:
        """Ensure no assets within this specific account are offline."""
        if not self.coordinator.data: 
            return True
            
        all_holdings = self.coordinator.data.get("account_holdings", {})
        account_holdings = all_holdings.get(self.account_id, [])
        for h in account_holdings:
            if float(h.get("quantity") or 0) > 0 and h.get("assetClass") != "LIQUIDITY":
                if self._is_provider_down(h.get("dataSource")): 
                    return False
                 
                val = float(h.get("valueInBaseCurrency") or h.get("value") or 0)
                price = float(h.get("marketPrice") or 0)
                if val <= 0 or price <= 0: 
                    return False
                 
        return True


class GhostfolioAccountValueSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking account market value."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account value sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_value_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Value"

    @property
    def native_value(self) -> float | None:
        """Return the account value."""
        if not self.is_account_healthy: 
            return None
        return self.account_performance_data.get("currentValueInBaseCurrency")


class GhostfolioAccountNetWorthSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking account net worth (includes cash)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account net worth sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_net_worth_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Net Worth"

    @property
    def native_value(self) -> float | None:
        """Return the account net worth."""
        if not self.is_account_healthy: 
            return None
        return self.account_performance_data.get("currentNetWorth")


class GhostfolioAccountCostSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking account total investment."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account cost sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_cost_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Cost"

    @property
    def native_value(self) -> float | None:
        """Return the account cost."""
        if not self.is_account_healthy: 
            return None
        return self.account_performance_data.get("totalInvestment")


class GhostfolioAccountPerformanceSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking Total Gain per account."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account gain sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_perf_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Gain"

    @property
    def native_value(self) -> float | None:
        """Return the native Ghostfolio net performance specific to this account."""
        if not self.is_account_healthy: 
            return None
        return self.account_performance_data.get("netPerformance")


class GhostfolioAccountUnrealizedPnLSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking true per-account Unrealized Gain."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account unrealized gain sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_unrealized_pnl_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Unrealized P&L"

    @property
    def native_value(self) -> float | None:
        """Return the calculated Unrealized P&L specific to this account."""
        if not self.coordinator.data or not self.coordinator.data.get("server_online", False):
            return None
        pnl, _ = self._calculate_unrealized_pnl(self.account_id)
        return round(pnl, 2)


class GhostfolioAccountTWRSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking account TWR %."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account TWR sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_perf_pct_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Time-Weighted Return %"

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Force percentage as the unit."""
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Return the TWR % for the account."""
        if not self.is_account_healthy: 
            return None
        percent_value = self.account_performance_data.get("netPerformancePercentage")
        return round(percent_value * 100, 2) if percent_value is not None else None


class GhostfolioAccountSimpleGainSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking true simple return % for the account."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account simple return sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_simple_gain_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Simple Gain %"

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Force percentage as the unit."""
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Calculate Simple Gain % based on Native Gain specific to this account."""
        if not self.is_account_healthy: 
            return None
        pnl = self.account_performance_data.get("netPerformance")
        cost = self.account_performance_data.get("totalInvestment")
        if pnl is not None and cost and cost > 0: 
            return round((pnl / cost) * 100, 2)
        return 0.0


class GhostfolioAccountUnrealizedPnLPercentSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking true Unrealized Gain % for the account."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account unrealized simple return sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_unrealized_pnl_percent_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Unrealized Gain %"

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Force percentage as the unit."""
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Calculate Unrealized Gain % specific to this account."""
        if not self.coordinator.data or not self.coordinator.data.get("server_online", False):
            return None
        pnl, cost = self._calculate_unrealized_pnl(self.account_id)
        if cost <= 0:
            return 0.0
        return round((pnl / cost) * 100, 2)


class GhostfolioAccountDividendSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking total account dividends."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account dividend sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_dividends_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Total Dividends"

    @property
    def native_value(self) -> float | None:
        """Return the total accumulated dividends for the account."""
        if not self.is_account_healthy: 
            return None
        if not self.coordinator.data: 
            return None
            
        dividends = self.coordinator.data.get("dividends", {})
        acc_divs = dividends.get(self.account_id, {})
        
        return sum(acc_divs.values())


class GhostfolioAccountCashBalanceSensor(GhostfolioAccountBaseSensor):
    """Sensor tracking uninvested cash explicitly."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        """Initialize the account cash balance sensor."""
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_cash_balance_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Cash Balance"

    @property
    def native_value(self) -> float | None:
        """Sum the value of any LIQUIDITY assets found within this account."""
        if not self.coordinator.data or not self.coordinator.data.get("server_online", False):
            return None
            
        holdings_map = self.coordinator.data.get("account_holdings", {})
        holdings = holdings_map.get(self.account_id, [])
        
        cash_total = 0.0
        for h in holdings:
            if h.get("assetClass") == "LIQUIDITY":
                cash_total += float(h.get("valueInBaseCurrency") or h.get("value") or 0)
                
        return cash_total


# ==========================================
# PER-HOLDING SENSORS
# ==========================================

class GhostfolioHoldingSensor(GhostfolioBaseSensor):
    """Sensor representing an individual holding."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_id, account_name, holding_data):
        """Initialize the individual holding sensor."""
        super().__init__(coordinator, config_entry)
        self.account_id = account_id
        self.account_name = account_name
        self.symbol = holding_data.get("symbol")
        self.ticker_name = holding_data.get("name", self.symbol)

        safe_symbol = slugify(self.symbol)
        self._attr_unique_id = f"ghostfolio_holding_{self.account_id}_{safe_symbol}_{config_entry.entry_id}"
        self._attr_name = self.ticker_name

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_account_{self.account_id}_{config_entry.entry_id}")},
            "name": self.account_name, 
            "manufacturer": "Ghostfolio",
            "model": "Account Portfolio",
            "via_device": (DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}"),
        }
        self._prev_low_reached = False
        self._prev_high_reached = False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data updates."""
        self._check_and_fire_events()
        super()._handle_coordinator_update()

    async def async_update(self) -> None:
        """Handle manual data updates."""
        self._check_and_fire_events()

    @property
    def holding_data(self) -> dict[str, Any] | None:
        """Fetch the exact data blob for this holding."""
        if not self.coordinator.data: 
            return None
            
        holdings_map = self.coordinator.data.get("account_holdings", {})
        holdings_list = holdings_map.get(self.account_id, [])
        for h in holdings_list:
            if h.get("symbol") == self.symbol: 
                return h
                
        return None

    @property
    def native_value(self) -> float | None:
        """Return the holding's current market value."""
        data = self.holding_data
        if not data: 
            return None
        if self._is_provider_down(data.get("dataSource")): 
            return None
        
        val = data.get("valueInBaseCurrency") or data.get("value")
        price = float(data.get("marketPrice") or 0)
        
        if val is None or float(val) <= 0 or price <= 0: 
            return None
            
        return float(val)

    def _get_limit_state(self, limit_type: str, current_value: float, compare_op):
        """Helper to get the current limit thresholds."""
        registry = er.async_get(self.hass)
        safe_symbol = slugify(self.symbol)
        entry_id = self.config_entry.entry_id
        num_unique_id = f"ghostfolio_limit_{limit_type}_{self.account_id}_{safe_symbol}_{entry_id}"
        entity_id = registry.async_get_entity_id("number", DOMAIN, num_unique_id)
        
        limit_display = False 
        is_reached = False
        limit_val = 0.0
        
        if entity_id:
            state_obj = self.hass.states.get(entity_id)
            if state_obj and state_obj.state not in [None, "unknown", "unavailable"]:
                try:
                    limit_val = float(state_obj.state)
                    if limit_val > 0:
                        limit_display = limit_val
                        if current_value > 0: 
                            if compare_op(current_value, limit_val): 
                                is_reached = True
                except ValueError:
                    pass
                    
        return limit_display, is_reached, limit_val

    def _check_and_fire_events(self):
        """Check price limits and fire events if triggered."""
        data = self.holding_data
        if not data: 
            return
            
        current_price = float(data.get("marketPrice") or 0)
        currency_asset = data.get("currency")
        
        low_disp, low_reached, low_val = self._get_limit_state("low", current_price, lambda val, limit: val <= limit)
        if low_reached and not self._prev_low_reached:
            self.hass.bus.async_fire("ghostfolio_limit_alert", {"ticker": self.symbol, "account": self.account_name, "limit_type": "low", "limit_value": low_val, "current_value": current_price, "currency": currency_asset})
        self._prev_low_reached = low_reached

        high_disp, high_reached, high_val = self._get_limit_state("high", current_price, lambda val, limit: val >= limit)
        if high_reached and not self._prev_high_reached:
            self.hass.bus.async_fire("ghostfolio_limit_alert", {"ticker": self.symbol, "account": self.account_name, "limit_type": "high", "limit_value": high_val, "current_value": current_price, "currency": currency_asset})
        self._prev_high_reached = high_reached

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the vast array of holding attributes."""
        data = self.holding_data
        if not data: 
            return None
            
        asset_currency = data.get("currency")
        base_currency = self.native_unit_of_measurement
        quantity = float(data.get("quantity") or 0)
        investment_in_base = float(data.get("investment") or 0)
        current_value_in_base = float(data.get("valueInBaseCurrency") or data.get("value") or 0)
        market_price_asset = float(data.get("marketPrice") or 0)

        is_gbp_conversion = (asset_currency == "GBp")
        raw_change = data.get("marketChange")
        market_change = (raw_change / 100) if (is_gbp_conversion and raw_change is not None) else raw_change
        market_change_pct = data.get("marketChangePercentage")

        avg_buy_price_base = investment_in_base / quantity if quantity > 0 else 0
        market_price_base = current_value_in_base / quantity if quantity > 0 else 0
        gain_value_base = current_value_in_base - investment_in_base
        gain_pct = (gain_value_base / investment_in_base * 100) if investment_in_base > 0 else 0

        trend = "break_even"
        if market_price_base > avg_buy_price_base: 
            trend = "up"
        elif market_price_base < avg_buy_price_base: 
            trend = "down"

        low_val, low_reached, _ = self._get_limit_state("low", market_price_asset, lambda val, limit: val <= limit)
        high_val, high_reached, _ = self._get_limit_state("high", market_price_asset, lambda val, limit: val >= limit)

        dividends_map = self.coordinator.data.get("dividends", {})
        account_dividends = dividends_map.get(self.account_id, {})
        
        accumulated_dividends = 0.0
        if self.symbol is not None:
            accumulated_dividends = account_dividends.get(self.symbol.upper(), 0.0)

        return {
            "ticker": self.symbol,
            "account": self.account_name,
            "number_of_shares": quantity,
            "currency_asset": "GBP" if is_gbp_conversion else asset_currency,
            "currency_base": base_currency,
            "market_price": (market_price_asset / 100) if is_gbp_conversion else market_price_asset,
            "market_price_currency": "GBP" if is_gbp_conversion else asset_currency,
            "market_price_in_base_currency": round(market_price_base, 2),
            "average_buy_price": round(avg_buy_price_base, 2),
            "average_buy_price_currency": base_currency,
            "gain_value": round(gain_value_base, 2),
            "gain_value_currency": base_currency,
            "gain_pct": round(gain_pct, 2),
            "accumulated_dividends": round(accumulated_dividends, 2) if accumulated_dividends > 0 else 0.0,
            "accumulated_dividends_currency": base_currency,
            "trend_vs_buy": trend,
            "asset_class": data.get("assetClass"),
            "data_source": data.get("dataSource"),
            "market_change_24h": market_change,                      
            "market_change_pct_24h": market_change_pct,              
            "low_limit_set": low_val,
            "low_limit_reached": low_reached,
            "high_limit_set": high_val,
            "high_limit_reached": high_reached,
        }


class GhostfolioWatchlistSensor(GhostfolioBaseSensor):
    """Sensor tracking an item on the watchlist."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, item_data):
        """Initialize the watchlist sensor."""
        super().__init__(coordinator, config_entry)
        self.symbol = item_data.get("symbol")
        self.data_source = item_data.get("dataSource")
        self.ticker_name = item_data.get("name", self.symbol)
        safe_symbol = slugify(self.symbol)
        self._attr_unique_id = f"ghostfolio_watchlist_{safe_symbol}_{config_entry.entry_id}"
        self._attr_name = self.ticker_name

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_account_watchlist_scope_{config_entry.entry_id}")},
            "name": "Watchlist", 
            "manufacturer": "Ghostfolio",
            "model": "Account Portfolio",
            "via_device": (DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}"),
        }
        self._prev_low_reached = False
        self._prev_high_reached = False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data updates."""
        self._check_and_fire_events()
        super()._handle_coordinator_update()

    async def async_update(self) -> None:
        """Handle manual data updates."""
        self._check_and_fire_events()

    @property
    def item_data(self) -> dict[str, Any] | None:
        """Fetch the exact data blob for this watchlist item."""
        if not self.coordinator.data: 
            return None
            
        watchlist = self.coordinator.data.get("watchlist", [])
        for item in watchlist:
            if item.get("symbol") == self.symbol and item.get("dataSource") == self.data_source: 
                return item
                
        return None

    @property
    def native_value(self) -> float | None:
        """Return the current market price."""
        data = self.item_data
        if not data: 
            return None
        if self._is_provider_down(self.data_source): 
            return None
        
        val = data.get("marketPrice")
        if val is None or float(val) <= 0: 
            return None
            
        if data.get("currency") == "GBp": 
            return val / 100
            
        return val
        
    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the currency of the watchlist item."""
        data = self.item_data
        if not data: 
            return None
        if data.get("currency") == "GBp": 
            return "GBP"
        return data.get("currency")

    def _get_limit_state(self, limit_type: str, current_value: float, compare_op):
        """Helper to get the current limit thresholds."""
        registry = er.async_get(self.hass)
        safe_symbol = slugify(self.symbol)
        entry_id = self.config_entry.entry_id
        num_unique_id = f"ghostfolio_watchlist_limit_{limit_type}_{safe_symbol}_{entry_id}"
        entity_id = registry.async_get_entity_id("number", DOMAIN, num_unique_id)
        
        limit_display = False 
        is_reached = False
        limit_val = 0.0
        
        if entity_id:
            state_obj = self.hass.states.get(entity_id)
            if state_obj and state_obj.state not in [None, "unknown", "unavailable"]:
                try:
                    limit_val = float(state_obj.state)
                    if limit_val > 0:
                        limit_display = limit_val
                        if current_value > 0: 
                            if compare_op(current_value, limit_val): 
                                is_reached = True
                except ValueError:
                    pass
                    
        return limit_display, is_reached, limit_val

    def _check_and_fire_events(self):
        """Check price limits and fire events if triggered."""
        data = self.item_data
        if not data: 
            return
            
        is_gbp_conversion = (data.get("currency") == "GBp")
        raw_price = data.get("marketPrice") or 0
        current_price = (raw_price / 100) if is_gbp_conversion else raw_price
        currency = "GBP" if is_gbp_conversion else data.get("currency")

        low_disp, low_reached, low_val = self._get_limit_state("low", current_price, lambda val, limit: val <= limit)
        if low_reached and not self._prev_low_reached:
            self.hass.bus.async_fire("ghostfolio_limit_alert", {"ticker": self.symbol, "account": "Watchlist", "limit_type": "low", "limit_value": low_val, "current_value": current_price, "currency": currency})
        self._prev_low_reached = low_reached

        high_disp, high_reached, high_val = self._get_limit_state("high", current_price, lambda val, limit: val >= limit)
        if high_reached and not self._prev_high_reached:
            self.hass.bus.async_fire("ghostfolio_limit_alert", {"ticker": self.symbol, "account": "Watchlist", "limit_type": "high", "limit_value": high_val, "current_value": current_price, "currency": currency})
        self._prev_high_reached = high_reached

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the watchlist attributes."""
        data = self.item_data
        if not data: 
            return None
            
        is_gbp_conversion = (data.get("currency") == "GBp")
        raw_price = data.get("marketPrice") or 0
        current_price = (raw_price / 100) if is_gbp_conversion else raw_price
        raw_change = data.get("marketChange")
        market_change = (raw_change / 100) if (is_gbp_conversion and raw_change is not None) else raw_change
        
        low_val, low_reached, _ = self._get_limit_state("low", current_price, lambda val, limit: val <= limit)
        high_val, high_reached, _ = self._get_limit_state("high", current_price, lambda val, limit: val >= limit)
        
        return {
            "ticker": self.symbol,
            "data_source": self.data_source,
            "asset_class": data.get("assetClass"),
            "market_price": current_price,
            "currency": "GBP" if is_gbp_conversion else data.get("currency"),
            "trend_50d": data.get("trend50d"),
            "trend_200d": data.get("trend200d"),
            "market_change_24h": market_change,
            "market_change_pct_24h": data.get("marketChangePercentage"),
            "low_limit_set": low_val,
            "low_limit_reached": low_reached,
            "high_limit_set": high_val,
            "high_limit_reached": high_reached,
        }


# ==========================================
# ENRICHMENT SENSORS
# ==========================================

def _extract_yahoo_raw(data):
    """Recursively flatten Yahoo Finance dicts to grab the 'raw' float value."""
    out = {}
    if not isinstance(data, dict): 
        return out
        
    for k, v in data.items():
        if isinstance(v, dict):
            if "raw" in v: 
                out[k] = v["raw"]
            elif "fmt" in v: 
                out[k] = v["fmt"]
        else: 
            out[k] = v
            
    return out

def _calculate_lynch_peg(data):
    """Calculate the Lynch PEG Ratio using 1y forward growth and dividend yield."""
    try:
        currency = data.get("summaryDetail", {}).get("currency") or data.get("financialData", {}).get("currency")
        is_gbp = (currency == "GBp")
        
        fwd_pe = data.get("summaryDetail", {}).get("forwardPE", {}).get("raw")
        if fwd_pe is None:
            fwd_pe = data.get("defaultKeyStatistics", {}).get("forwardPE", {}).get("raw")
            if is_gbp and fwd_pe is not None:
                fwd_pe = fwd_pe / 100.0
                
        div_yield = data.get("summaryDetail", {}).get("dividendYield", {}).get("raw") or 0
        
        trends = data.get("earningsTrend", {}).get("trend", [])
        next_year_growth = None
        for t in trends:
            if t.get("period") in ["+1y", "1y", "0y", "+5y"]:
                val = t.get("growth", {}).get("raw")
                if val is not None:
                    next_year_growth = val
                    break
        
        if fwd_pe is not None and next_year_growth is not None:
            denominator = (next_year_growth * 100) + (div_yield * 100)
            if denominator > 0:
                return round(fwd_pe / denominator, 2)
    except Exception as e:
        _LOGGER.debug("Error calculating Lynch PEG: %s", e)
        
    return None

class GhostfolioFundamentalsSensor(GhostfolioBaseSensor):
    """Sensor tracking Yahoo Finance Fundamental Enrichment Data."""
    
    _attr_icon = "mdi:finance"
    
    @property
    def native_unit_of_measurement(self) -> str | None: 
        return None

    def __init__(self, coordinator, config_entry, symbol):
        """Initialize the fundamental sensor."""
        super().__init__(coordinator, config_entry)
        self.symbol = symbol
        safe_symbol = slugify(self.symbol)
        
        self._attr_unique_id = f"ghostfolio_fundamentals_{safe_symbol}_{config_entry.entry_id}"
        self._attr_name = f"{self.symbol} Fundamentals"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"ghostfolio_device_fundamentals_{config_entry.entry_id}")},
            "name": "Fundamentals", 
            "manufacturer": "Yahoo Finance",
            "model": "Fundamental Tracking",
            "via_device": (DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}"),
        }

    @property
    def native_value(self) -> str:
        """Return the ticker symbol as the state."""
        return self.symbol

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the deep fundamental metrics."""
        data_cache = self.coordinator.data.get("fundamentals_data", {})
        data = data_cache.get(self.symbol, {})
        last_update = self.coordinator.last_fundamentals_update
        
        attrs = {
            "ticker": self.symbol,
            "data_pulled_at": last_update.isoformat() if last_update else None,
        }
        
        if not data:
            return attrs
            
        currency = data.get("summaryDetail", {}).get("currency") or data.get("financialData", {}).get("currency")
        is_gbp = (currency == "GBp")

        lynch_peg = _calculate_lynch_peg(data)
        attrs["lynch_peg_ratio"] = lynch_peg
        
        if lynch_peg is None:
            attrs["valuation"] = "unknown"
        elif lynch_peg < 1.0:
            attrs["valuation"] = "undervalued"
        elif lynch_peg > 2.0:
            attrs["valuation"] = "overpriced"
        else:
            attrs["valuation"] = "fairly_valued"
            
        attrs["standard_peg_ratio"] = data.get("defaultKeyStatistics", {}).get("pegRatio", {}).get("raw")
        
        fwd_pe = data.get("summaryDetail", {}).get("forwardPE", {}).get("raw")
        if fwd_pe is None:
            fwd_pe = data.get("defaultKeyStatistics", {}).get("forwardPE", {}).get("raw")
            if is_gbp and fwd_pe is not None:
                fwd_pe = fwd_pe / 100.0
                
        if fwd_pe is not None:
            attrs["forward_pe"] = round(fwd_pe, 4)
        
        attrs["dividend_yield"] = data.get("summaryDetail", {}).get("dividendYield", {}).get("raw")
        
        trends = data.get("earningsTrend", {}).get("trend", [])
        for t in trends:
            if t.get("period") in ["+1y", "1y", "0y", "+5y"]:
                val = t.get("growth", {}).get("raw")
                if val is not None:
                    attrs["projected_1y_growth"] = val
                    break

        stats = _extract_yahoo_raw(data.get("defaultKeyStatistics", {}))
        fin = _extract_yahoo_raw(data.get("financialData", {}))
        summary = _extract_yahoo_raw(data.get("summaryDetail", {}))
        
        if is_gbp:
            for key in ["forwardPE", "trailingPE", "priceToBook"]:
                if key in stats and stats[key] is not None:
                    stats[key] = round(stats[key] / 100.0, 4)
        
        attrs.update(stats)
        attrs.update(summary) 
        attrs.update(fin)
        
        return {k: v for k, v in attrs.items() if not isinstance(v, (dict, list))}
