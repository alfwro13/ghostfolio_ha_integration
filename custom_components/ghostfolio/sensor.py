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
from homeassistant.util import slugify

from . import GhostfolioDataUpdateCoordinator
from .const import (
    CONF_PORTFOLIO_NAME,
    CONF_SHOW_TOTALS,
    CONF_SHOW_ACCOUNTS,
    CONF_SHOW_HOLDINGS,
    CONF_SHOW_WATCHLIST,
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
    
    # Check configuration options
    show_totals = config_entry.data.get(CONF_SHOW_TOTALS, True)
    show_accounts = config_entry.data.get(CONF_SHOW_ACCOUNTS, True)
    show_holdings = config_entry.data.get(CONF_SHOW_HOLDINGS, True)
    show_watchlist = config_entry.data.get(CONF_SHOW_WATCHLIST, True)

    # Track created entities to prevent duplicates
    known_ids: set[str] = set()

    # 1. Add Global Portfolio Sensors (These are static, add them once)
    if show_totals:
        global_sensors = [
            GhostfolioCurrentValueSensor(coordinator, config_entry),
            GhostfolioNetPerformanceSensor(coordinator, config_entry),
            GhostfolioTimeWeightedReturnSensor(coordinator, config_entry),
            GhostfolioTotalInvestmentSensor(coordinator, config_entry),
            GhostfolioNetPerformanceWithCurrencySensor(coordinator, config_entry),
            GhostfolioTimeWeightedReturnFXSensor(coordinator, config_entry),
            GhostfolioSimpleGainPercentSensor(coordinator, config_entry),
        ]
        async_add_entities(global_sensors)
        # Mark globals as known
        for s in global_sensors:
            known_ids.add(s.unique_id)

    @callback
    def _update_sensors():
        """Check for new sensors (accounts, holdings, watchlist) and add them."""
        new_entities = []
        
        # --- ACCOUNTS & HOLDINGS ---
        accounts_data = coordinator.data.get("accounts", {}).get("accounts", [])

        for account in accounts_data:
            if account.get("isExcluded", False):
                continue

            account_id = account["id"]

            # A. Add Per-Account Sensors
            if show_accounts:
                account_sensors = [
                    GhostfolioAccountValueSensor(coordinator, config_entry, account),
                    GhostfolioAccountCostSensor(coordinator, config_entry, account),
                    GhostfolioAccountPerformanceSensor(coordinator, config_entry, account),
                    GhostfolioAccountTWRSensor(coordinator, config_entry, account),
                    GhostfolioAccountSimpleGainSensor(coordinator, config_entry, account),
                ]
                
                for sens in account_sensors:
                    if sens.unique_id not in known_ids:
                        new_entities.append(sens)
                        known_ids.add(sens.unique_id)

            # B. Add Per-Holding Sensors
            if show_holdings:
                holdings_map = coordinator.data.get("account_holdings", {})
                holdings_list = holdings_map.get(account_id, [])

                for holding in holdings_list:
                    # Ensure valid holding with quantity
                    if float(holding.get("quantity") or 0) > 0:
                        symbol = holding.get("symbol")
                        safe_symbol = slugify(symbol)
                        unique_id = f"ghostfolio_holding_{account_id}_{safe_symbol}_{config_entry.entry_id}"
                        
                        if unique_id not in known_ids:
                            sensor = GhostfolioHoldingSensor(coordinator, config_entry, account, holding)
                            new_entities.append(sensor)
                            known_ids.add(unique_id)

        # --- WATCHLIST ---
        if show_watchlist:
            watchlist_items = coordinator.data.get("watchlist", [])
            for item in watchlist_items:
                symbol = item.get("symbol")
                safe_symbol = slugify(symbol)
                unique_id = f"ghostfolio_watchlist_{safe_symbol}_{config_entry.entry_id}"
                
                if unique_id not in known_ids:
                    sensor = GhostfolioWatchlistSensor(coordinator, config_entry, item)
                    new_entities.append(sensor)
                    known_ids.add(unique_id)

        # If we found new entities, register them
        if new_entities:
            async_add_entities(new_entities)

    # 2. Register the listener
    config_entry.async_on_unload(coordinator.async_add_listener(_update_sensors))

    # 3. Run it immediately
    _update_sensors()


class GhostfolioBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Ghostfolio sensors."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GhostfolioDataUpdateCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
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
        """Dynamically return the portfolio base currency."""
        if not self.coordinator.data:
            return "EUR"

        accounts_payload = self.coordinator.data.get("accounts", {})

        # 1. Try User Settings
        user_currency = accounts_payload.get("user", {}).get("baseCurrency")
        if user_currency:
            return user_currency

        # 2. Try root level
        if "baseCurrency" in accounts_payload:
            return accounts_payload["baseCurrency"]

        # 3. Fallback to first account currency
        accounts_list = accounts_payload.get("accounts", [])
        if accounts_list and len(accounts_list) > 0:
            return accounts_list[0].get("currency", "EUR")

        return "EUR"

    @property
    def global_performance_data(self) -> dict[str, Any]:
        """Helper to get global performance data safely."""
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get("global_performance", {}).get(
            "performance", {}
        )


# --- GLOBAL SENSORS ---


class GhostfolioCurrentValueSensor(GhostfolioBaseSensor):
    """Sensor for current portfolio value."""

    _attr_name = "Portfolio Value"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_current_value_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        return self.global_performance_data.get("currentValueInBaseCurrency")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return {
            "current_net_worth": self.global_performance_data.get("currentNetWorth"),
        }


class GhostfolioNetPerformanceSensor(GhostfolioBaseSensor):
    """Sensor for net performance (Absolute Gain)."""

    _attr_name = "Portfolio Gain"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        return self.global_performance_data.get("netPerformance")


class GhostfolioTimeWeightedReturnSensor(GhostfolioBaseSensor):
    """Sensor for Time Weighted Return (Ghostfolio standard)."""

    _attr_name = "Time-Weighted Return %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_percent_{config_entry.entry_id}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        percent_value = self.global_performance_data.get("netPerformancePercentage")
        return percent_value * 100 if percent_value is not None else None


class GhostfolioTotalInvestmentSensor(GhostfolioBaseSensor):
    """Sensor for total investment."""

    _attr_name = "Portfolio Cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_total_investment_{config_entry.entry_id}"

    @property
    def native_value(self) -> float | None:
        return self.global_performance_data.get("totalInvestment")


class GhostfolioTimeWeightedReturnFXSensor(GhostfolioBaseSensor):
    """Sensor for TWR with FX effect."""

    _attr_name = "Time-Weighted Return FX %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = (
            f"ghostfolio_net_performance_percent_with_currency_{config_entry.entry_id}"
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        percent_value = self.global_performance_data.get(
            "netPerformancePercentageWithCurrencyEffect"
        )
        return percent_value * 100 if percent_value is not None else None


class GhostfolioNetPerformanceWithCurrencySensor(GhostfolioBaseSensor):
    """Sensor for net performance with currency effect (Absolute)."""

    _attr_name = "Portfolio Gain FX"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = (
            f"ghostfolio_net_performance_with_currency_{config_entry.entry_id}"
        )

    @property
    def native_value(self) -> float | None:
        return self.global_performance_data.get("netPerformanceWithCurrencyEffect")


class GhostfolioSimpleGainPercentSensor(GhostfolioBaseSensor):
    """Sensor for simple gain percentage (Money-Weighted proxy)."""

    _attr_name = "Simple Gain %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_simple_gain_percent_{config_entry.entry_id}"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        current_value = self.global_performance_data.get("currentValueInBaseCurrency")
        total_investment = self.global_performance_data.get("totalInvestment")

        if current_value is None or total_investment is None or total_investment == 0:
            return None

        return ((current_value - total_investment) / total_investment) * 100


# --- PER-ACCOUNT SENSORS ---


class GhostfolioAccountBaseSensor(GhostfolioBaseSensor):
    """Base class for Account-specific sensors."""

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry) # <--- FIXED HERE (Removed account_data)
        self.account_id = account_data["id"]
        self.account_name = account_data["name"]

    @property
    def account_performance_data(self) -> dict[str, Any]:
        """Get performance data specifically for this account."""
        if not self.coordinator.data:
            return {}

        performances = self.coordinator.data.get("account_performances", {})
        return performances.get(self.account_id, {}).get("performance", {})


class GhostfolioAccountValueSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account Value."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_value_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Value"

    @property
    def native_value(self) -> float | None:
        return self.account_performance_data.get("currentValueInBaseCurrency")


class GhostfolioAccountCostSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account Cost (Total Investment)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_cost_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Cost"

    @property
    def native_value(self) -> float | None:
        return self.account_performance_data.get("totalInvestment")


class GhostfolioAccountPerformanceSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account Performance (Absolute Gain)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_perf_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Gain"

    @property
    def native_value(self) -> float | None:
        return self.account_performance_data.get("netPerformance")


class GhostfolioAccountTWRSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account TWR (Ghostfolio default)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_perf_pct_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Time-Weighted Return %"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        percent_value = self.account_performance_data.get("netPerformancePercentage")
        return percent_value * 100 if percent_value is not None else None


class GhostfolioAccountSimpleGainSensor(GhostfolioAccountBaseSensor):
    """Sensor for specific Account Simple Gain %."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = (
            f"ghostfolio_account_simple_gain_{self.account_id}_{config_entry.entry_id}"
        )
        self._attr_name = f"{self.account_name} Simple Gain %"

    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE

    @property
    def native_value(self) -> float | None:
        current_value = self.account_performance_data.get("currentValueInBaseCurrency")
        total_investment = self.account_performance_data.get("totalInvestment")

        if current_value is None or total_investment is None or total_investment == 0:
            return None

        return ((current_value - total_investment) / total_investment) * 100


# --- PER-HOLDING SENSORS (FIXED) ---


class GhostfolioHoldingSensor(GhostfolioBaseSensor):
    """Sensor for a specific Asset/Holding."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, account_data, holding_data):
        super().__init__(coordinator, config_entry)
        self.account_id = account_data["id"]
        self.account_name = account_data["name"]
        self.symbol = holding_data.get("symbol")
        self.ticker_name = holding_data.get("name", self.symbol)

        # Unique ID
        safe_symbol = slugify(self.symbol)
        self._attr_unique_id = f"ghostfolio_holding_{self.account_id}_{safe_symbol}_{config_entry.entry_id}"

        self._attr_name = f"{self.account_name} - {self.ticker_name}"

    @property
    def holding_data(self) -> dict[str, Any] | None:
        """Find the latest data for this holding."""
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
        """State is the Total Value (Market Value in Base Currency)."""
        data = self.holding_data
        if not data:
            return None
        return data.get("valueInBaseCurrency") or data.get("value")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return detailed attributes with currency clarity."""
        data = self.holding_data
        if not data:
            return None

        # 1. Identify Currencies
        asset_currency = data.get("currency")
        base_currency = self.native_unit_of_measurement  # e.g., GBP

        # 2. Extract Raw Values
        quantity = float(data.get("quantity") or 0)
        investment_in_base = float(data.get("investment") or 0)
        current_value_in_base = float(
            data.get("valueInBaseCurrency") or data.get("value") or 0
        )
        market_price_asset = float(
            data.get("marketPrice") or 0
        )  # Price in Asset Currency

        # 3. Calculate Derived Values (Base Currency)

        # Average Buy Price (Base)
        avg_buy_price_base = investment_in_base / quantity if quantity > 0 else 0

        # Market Price (Base) -> Derived from Total Value / Quantity
        market_price_base = current_value_in_base / quantity if quantity > 0 else 0

        # Gain (Base)
        gain_value_base = current_value_in_base - investment_in_base
        gain_pct = (
            (gain_value_base / investment_in_base * 100) if investment_in_base > 0 else 0
        )

        # 4. Trend Calculation (Base vs Base comparison)
        if market_price_base > avg_buy_price_base:
            trend = "up"
        elif market_price_base < avg_buy_price_base:
            trend = "down"
        else:
            trend = "break_even"

        return {
            "ticker": self.symbol,
            "account": self.account_name,
            "number_of_shares": quantity,
            # --- Currencies ---
            "currency_asset": asset_currency,
            "currency_base": base_currency,
            # --- Prices (Asset Currency) ---
            "market_price": market_price_asset,
            "market_price_currency": asset_currency,
            # --- Prices (Base Currency - Comparable) ---
            "market_price_in_base_currency": round(market_price_base, 2),
            "average_buy_price": round(avg_buy_price_base, 2),
            "average_buy_price_currency": base_currency,
            # --- Gains (Base Currency) ---
            "gain_value": round(gain_value_base, 2),
            "gain_value_currency": base_currency,
            "gain_pct": round(gain_pct, 2),
            # --- Analysis ---
            "trend_vs_buy": trend,
            "asset_class": data.get("assetClass"),
        }


# --- WATCHLIST SENSORS ---


class GhostfolioWatchlistSensor(GhostfolioBaseSensor):
    """Sensor for a Watchlist Item."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, config_entry, item_data):
        super().__init__(coordinator, config_entry)
        self.symbol = item_data.get("symbol")
        self.data_source = item_data.get("dataSource")
        self.ticker_name = item_data.get("name", self.symbol)

        # Unique ID using "watchlist" prefix
        safe_symbol = slugify(self.symbol)
        self._attr_unique_id = f"ghostfolio_watchlist_{safe_symbol}_{config_entry.entry_id}"

        self._attr_name = f"Watchlist - {self.ticker_name}"

    @property
    def item_data(self) -> dict[str, Any] | None:
        """Find the latest data for this watchlist item."""
        if not self.coordinator.data:
            return None
        
        watchlist = self.coordinator.data.get("watchlist", [])
        for item in watchlist:
            if item.get("symbol") == self.symbol and item.get("dataSource") == self.data_source:
                return item
        return None

    @property
    def native_value(self) -> float | None:
        """State is the Market Price."""
        data = self.item_data
        if not data:
            return None
        return data.get("marketPrice")

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the currency of the asset."""
        data = self.item_data
        if not data:
            return None
        return data.get("currency")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.item_data
        if not data:
            return None
        
        return {
            "ticker": self.symbol,
            "data_source": self.data_source,
            "asset_class": data.get("assetClass"),
            "market_price": data.get("marketPrice"),
            "currency": data.get("currency"),
            "trend_50d": data.get("trend50d"),
            "trend_200d": data.get("trend200d"),
            "market_change_24h": data.get("marketChange"),
            "market_change_pct_24h": data.get("marketChangePercentage"),
        }
