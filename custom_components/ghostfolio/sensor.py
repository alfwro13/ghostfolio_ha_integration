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
            GhostfolioTimeWeightedReturnSensor(coordinator, config_entry),
            GhostfolioTotalInvestmentSensor(coordinator, config_entry),
            GhostfolioNetPerformanceWithCurrencySensor(coordinator, config_entry),
            GhostfolioTimeWeightedReturnFXSensor(coordinator, config_entry),
            GhostfolioSimpleGainPercentSensor(coordinator, config_entry),
        ]
        async_add_entities(global_sensors)
        for s in global_sensors:
            known_ids.add(s.unique_id)

    @callback
    def _update_sensors():
        new_entities = []
        accounts_data = coordinator.data.get("accounts", {}).get("accounts", [])

        for account in accounts_data:
            if account.get("isExcluded", False):
                continue
            account_id = account["id"]
            account_name = account["name"]

            if show_accounts:
                account_sensors = [
                    GhostfolioAccountValueSensor(coordinator, config_entry, account),
                    GhostfolioAccountNetWorthSensor(coordinator, config_entry, account),
                    GhostfolioAccountCostSensor(coordinator, config_entry, account),
                    GhostfolioAccountPerformanceSensor(coordinator, config_entry, account),
                    GhostfolioAccountTWRSensor(coordinator, config_entry, account),
                    GhostfolioAccountSimpleGainSensor(coordinator, config_entry, account),
                ]
                for sens in account_sensors:
                    if sens.unique_id not in known_ids:
                        new_entities.append(sens)
                        known_ids.add(sens.unique_id)

            if show_holdings:
                holdings_map = coordinator.data.get("account_holdings", {})
                holdings_list = holdings_map.get(account_id, [])
                for holding in holdings_list:
                    if float(holding.get("quantity") or 0) > 0:
                        symbol = holding.get("symbol")
                        safe_symbol = slugify(symbol)
                        unique_id = f"ghostfolio_holding_{account_id}_{safe_symbol}_{config_entry.entry_id}"
                        if unique_id not in known_ids:
                            new_entities.append(GhostfolioHoldingSensor(coordinator, config_entry, account_id, account_name, holding))
                            known_ids.add(unique_id)

        if show_watchlist:
            watchlist_items = coordinator.data.get("watchlist", [])
            for item in watchlist_items:
                symbol = item.get("symbol")
                safe_symbol = slugify(symbol)
                unique_id = f"ghostfolio_watchlist_{safe_symbol}_{config_entry.entry_id}"
                if unique_id not in known_ids:
                    new_entities.append(GhostfolioWatchlistSensor(coordinator, config_entry, item))
                    known_ids.add(unique_id)

        # --- FUNDAMENTALS ---
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
        if not self.coordinator.data: return "EUR"
        payload = self.coordinator.data.get("accounts", {})
        user_currency = payload.get("user", {}).get("baseCurrency")
        if user_currency: return user_currency
        if "baseCurrency" in payload: return payload["baseCurrency"]
        accounts_list = payload.get("accounts", [])
        if accounts_list: return accounts_list[0].get("currency", "EUR")
        return "EUR"

    @property
    def global_performance_data(self) -> dict[str, Any]:
        if not self.coordinator.data: return {}
        return self.coordinator.data.get("global_performance", {}).get("performance", {})

    def _is_provider_down(self, data_source: str | None) -> bool:
        if not data_source or not self.coordinator.data: return False
        providers = self.coordinator.data.get("providers", {})
        info = providers.get(data_source)
        return info and not info.get("is_active", True)

    @property
    def is_portfolio_healthy(self) -> bool:
        if not self.coordinator.data: return True
        all_holdings = self.coordinator.data.get("account_holdings", {})
        for holdings in all_holdings.values():
            for h in holdings:
                if float(h.get("quantity") or 0) > 0:
                     if self._is_provider_down(h.get("dataSource")): return False
        return True


# --- GLOBAL SENSORS ---

class GhostfolioCurrentValueSensor(GhostfolioBaseSensor):
    _attr_name = "Portfolio Value"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_current_value_{config_entry.entry_id}"
    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy: return None
        return self.global_performance_data.get("currentValueInBaseCurrency")
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data: return None
        return {"current_net_worth": self.global_performance_data.get("currentNetWorth")}

class GhostfolioNetPerformanceSensor(GhostfolioBaseSensor):
    _attr_name = "Portfolio Gain"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_{config_entry.entry_id}"
    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy: return None
        return self.global_performance_data.get("netPerformance")

class GhostfolioTimeWeightedReturnSensor(GhostfolioBaseSensor):
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
        if not self.is_portfolio_healthy: return None
        percent_value = self.global_performance_data.get("netPerformancePercentage")
        return round(percent_value * 100, 2) if percent_value is not None else None

class GhostfolioTotalInvestmentSensor(GhostfolioBaseSensor):
    _attr_name = "Portfolio Cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_total_investment_{config_entry.entry_id}"
    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy: return None
        return self.global_performance_data.get("totalInvestment")

class GhostfolioTimeWeightedReturnFXSensor(GhostfolioBaseSensor):
    _attr_name = "Time-Weighted Return FX %"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_percent_with_currency_{config_entry.entry_id}"
    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE
    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy: return None
        percent_value = self.global_performance_data.get("netPerformancePercentageWithCurrencyEffect")
        return round(percent_value * 100, 2) if percent_value is not None else None

class GhostfolioNetPerformanceWithCurrencySensor(GhostfolioBaseSensor):
    _attr_name = "Portfolio Gain FX"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"ghostfolio_net_performance_with_currency_{config_entry.entry_id}"
    @property
    def native_value(self) -> float | None:
        if not self.is_portfolio_healthy: return None
        return self.global_performance_data.get("netPerformanceWithCurrencyEffect")

class GhostfolioSimpleGainPercentSensor(GhostfolioBaseSensor):
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
        if not self.is_portfolio_healthy: return None
        current_value = self.global_performance_data.get("currentValueInBaseCurrency")
        total_investment = self.global_performance_data.get("totalInvestment")
        if current_value is None or total_investment is None or total_investment == 0: return None
        return round(((current_value - total_investment) / total_investment) * 100, 2)

# --- PER-ACCOUNT SENSORS ---

class GhostfolioAccountBaseSensor(GhostfolioBaseSensor):
    def __init__(self, coordinator, config_entry, account_data):
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
        if not self.coordinator.data: return {}
        performances = self.coordinator.data.get("account_performances", {})
        return performances.get(self.account_id, {}).get("performance", {})
    @property
    def is_account_healthy(self) -> bool:
        if not self.coordinator.data: return True
        all_holdings = self.coordinator.data.get("account_holdings", {})
        account_holdings = all_holdings.get(self.account_id, [])
        for h in account_holdings:
            if float(h.get("quantity") or 0) > 0:
                 if self._is_provider_down(h.get("dataSource")): return False
        return True

class GhostfolioAccountValueSensor(GhostfolioAccountBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_value_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Value"
    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy: return None
        return self.account_performance_data.get("currentValueInBaseCurrency")

class GhostfolioAccountNetWorthSensor(GhostfolioAccountBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_net_worth_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Net Worth"
    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy: return None
        return self.account_performance_data.get("currentNetWorth")

class GhostfolioAccountCostSensor(GhostfolioAccountBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_cost_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Cost"
    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy: return None
        return self.account_performance_data.get("totalInvestment")

class GhostfolioAccountPerformanceSensor(GhostfolioAccountBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_perf_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Gain"
    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy: return None
        return self.account_performance_data.get("netPerformance")

class GhostfolioAccountTWRSensor(GhostfolioAccountBaseSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_perf_pct_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Time-Weighted Return %"
    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE
    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy: return None
        percent_value = self.account_performance_data.get("netPerformancePercentage")
        return round(percent_value * 100, 2) if percent_value is not None else None

class GhostfolioAccountSimpleGainSensor(GhostfolioAccountBaseSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry, account_data):
        super().__init__(coordinator, config_entry, account_data)
        self._attr_unique_id = f"ghostfolio_account_simple_gain_{self.account_id}_{config_entry.entry_id}"
        self._attr_name = f"{self.account_name} Simple Gain %"
    @property
    def native_unit_of_measurement(self) -> str | None:
        return PERCENTAGE
    @property
    def native_value(self) -> float | None:
        if not self.is_account_healthy: return None
        current_value = self.account_performance_data.get("currentValueInBaseCurrency")
        total_investment = self.account_performance_data.get("totalInvestment")
        if current_value is None or total_investment is None or total_investment == 0: return None
        return round(((current_value - total_investment) / total_investment) * 100, 2)

# --- PER-HOLDING SENSORS ---

class GhostfolioHoldingSensor(GhostfolioBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry, account_id, account_name, holding_data):
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
        self._check_and_fire_events()
        super()._handle_coordinator_update()

    async def async_update(self) -> None:
        self._check_and_fire_events()

    @property
    def holding_data(self) -> dict[str, Any] | None:
        if not self.coordinator.data: return None
        holdings_map = self.coordinator.data.get("account_holdings", {})
        holdings_list = holdings_map.get(self.account_id, [])
        for h in holdings_list:
            if h.get("symbol") == self.symbol: return h
        return None

    @property
    def native_value(self) -> float | None:
        data = self.holding_data
        if not data: return None
        if self._is_provider_down(data.get("dataSource")): return None
        return data.get("valueInBaseCurrency") or data.get("value")

    def _get_limit_state(self, limit_type: str, current_value: float, compare_op):
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
                                if compare_op(current_value, limit_val): is_reached = True
                except ValueError:
                    pass
        return limit_display, is_reached, limit_val

    def _check_and_fire_events(self):
        data = self.holding_data
        if not data: return
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
        data = self.holding_data
        if not data: return None
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
        if market_price_base > avg_buy_price_base: trend = "up"
        elif market_price_base < avg_buy_price_base: trend = "down"

        low_val, low_reached, _ = self._get_limit_state("low", market_price_asset, lambda val, limit: val <= limit)
        high_val, high_reached, _ = self._get_limit_state("high", market_price_asset, lambda val, limit: val >= limit)

        # --- Extract Dividends ---
        dividends_map = self.coordinator.data.get("dividends", {})
        account_dividends = dividends_map.get(self.account_id, {})
        
        # Ensure we uppercase the symbol to match the safe dictionary mapping
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
            "accumulated_dividends_currency": "GBP" if is_gbp_conversion else asset_currency,
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
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    def __init__(self, coordinator, config_entry, item_data):
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
        self._check_and_fire_events()
        super()._handle_coordinator_update()
    async def async_update(self) -> None:
        self._check_and_fire_events()
    @property
    def item_data(self) -> dict[str, Any] | None:
        if not self.coordinator.data: return None
        watchlist = self.coordinator.data.get("watchlist", [])
        for item in watchlist:
            if item.get("symbol") == self.symbol and item.get("dataSource") == self.data_source: return item
        return None
    @property
    def native_value(self) -> float | None:
        data = self.item_data
        if not data: return None
        if self._is_provider_down(self.data_source): return None
        val = data.get("marketPrice")
        if data.get("currency") == "GBp" and val is not None: return val / 100
        return val
    @property
    def native_unit_of_measurement(self) -> str | None:
        data = self.item_data
        if not data: return None
        if data.get("currency") == "GBp": return "GBP"
        return data.get("currency")

    def _get_limit_state(self, limit_type: str, current_value: float, compare_op):
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
                                if compare_op(current_value, limit_val): is_reached = True
                except ValueError:
                    pass
        return limit_display, is_reached, limit_val

    def _check_and_fire_events(self):
        data = self.item_data
        if not data: return
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
        data = self.item_data
        if not data: return None
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

# --- ENRICHMENT SENSORS ---

def _extract_yahoo_raw(data):
    """Recursively flatten Yahoo Finance dicts to grab the 'raw' float value."""
    out = {}
    if not isinstance(data, dict): return out
    for k, v in data.items():
        if isinstance(v, dict):
            if "raw" in v: out[k] = v["raw"]
            elif "fmt" in v: out[k] = v["fmt"]
        else: out[k] = v
    return out

def _calculate_lynch_peg(data):
    """Calculate the Lynch PEG Ratio using 1y forward growth and dividend yield."""
    try:
        currency = data.get("summaryDetail", {}).get("currency") or data.get("financialData", {}).get("currency")
        is_gbp = (currency == "GBp")
        
        # 1. ALWAYS prefer summaryDetail for P/E as Yahoo usually corrects the Pence Glitch natively here
        fwd_pe = data.get("summaryDetail", {}).get("forwardPE", {}).get("raw")
        
        # 2. Fallback to defaultKeyStatistics, but apply the 100x Pence fix if it's a UK stock
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
        _LOGGER.debug(f"Error calculating Lynch PEG: {e}")
    return None

class GhostfolioFundamentalsSensor(GhostfolioBaseSensor):
    """Sensor for Yahoo Finance Fundamental Enrichment Data."""
    _attr_icon = "mdi:finance"
    
    @property
    def native_unit_of_measurement(self) -> str | None: return None

    def __init__(self, coordinator, config_entry, symbol):
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
        return self.symbol

    @property
    def extra_state_attributes(self) -> dict | None:
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

        # --- 1. Valuation & Lynch Logic ---
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
            
        # --- 2. Top-Level Requested Attributes ---
        attrs["standard_peg_ratio"] = data.get("defaultKeyStatistics", {}).get("pegRatio", {}).get("raw")
        
        # Prefer summaryDetail for the explicitly exposed forward_pe attribute
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

        # --- 3. Rest of Yahoo Payload ---
        stats = _extract_yahoo_raw(data.get("defaultKeyStatistics", {}))
        fin = _extract_yahoo_raw(data.get("financialData", {}))
        summary = _extract_yahoo_raw(data.get("summaryDetail", {}))
        
        # FIX: The "Dumb" module (defaultKeyStatistics) always inflates Price-based ratios for GBp stocks.
        if is_gbp:
            for key in ["forwardPE", "trailingPE", "priceToBook"]:
                if key in stats and stats[key] is not None:
                    stats[key] = round(stats[key] / 100.0, 4)
        
        attrs.update(stats)
        
        # Adding summary AFTER stats is intentional. If both modules provide 'forwardPE', 
        # the "Smart" summaryDetail module will overwrite the "Dumb" defaultKeyStatistics module.
        attrs.update(summary) 
        attrs.update(fin)
        
        return {k: v for k, v in attrs.items() if not isinstance(v, (dict, list))}
