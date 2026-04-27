"""The Ghostfolio integration."""
from __future__ import annotations

import logging
import asyncio
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .api import GhostfolioAPI
from .const import (
    CONF_UPDATE_INTERVAL, 
    DEFAULT_UPDATE_INTERVAL, 
    CONF_SHOW_TOTALS,
    CONF_SHOW_ACCOUNTS,
    CONF_SHOW_HOLDINGS,
    CONF_SHOW_WATCHLIST,
    CONF_SHOW_FUNDAMENTALS,
    DOMAIN,
    DATA_PROVIDERS
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ghostfolio from a config entry."""
    api = GhostfolioAPI(
        base_url=entry.data["base_url"],
        access_token=entry.data["access_token"],
        verify_ssl=entry.data.get("verify_ssl", True),
    )

    update_interval = entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    coordinator = GhostfolioDataUpdateCoordinator(hass, api, update_interval, entry)
    
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- Register Custom Service for On-Demand Refresh ---
    async def refresh_fundamentals(call):
        """Force a refresh of Yahoo Finance fundamentals."""
        for e in hass.config_entries.async_entries(DOMAIN):
            if hasattr(e, "runtime_data"):
                coord = e.runtime_data
                if isinstance(coord, GhostfolioDataUpdateCoordinator):
                    _LOGGER.info("Forcing on-demand refresh of Yahoo Fundamentals")
                    coord.last_fundamentals_update = None  # Reset the 24h timer
                    await coord.async_request_refresh()

    if not hass.services.has_service(DOMAIN, "refresh_fundamentals"):
        hass.services.async_register(DOMAIN, "refresh_fundamentals", refresh_fundamentals)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class GhostfolioDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Ghostfolio data."""

    def __init__(self, hass: HomeAssistant, api: GhostfolioAPI, update_interval_minutes: int, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval_minutes),
        )
        self.api = api
        self.entry = entry
        
        self._store = Store(hass, 1, f"{DOMAIN}_fundamentals_cache_{entry.entry_id}")
        self.fundamentals_cache = {}
        self.last_fundamentals_update = None

        # Bumped to v2 to force a fresh pull of activities on next boot
        self._dividends_store = Store(hass, 1, f"{DOMAIN}_dividends_cache_v2_{entry.entry_id}")
        self.dividends_cache = {}
        self.last_dividends_update = None

        self._cache_loaded = False
        self._yahoo_crumb = None

    async def _get_yahoo_crumb(self, session):
        """Fetch Yahoo Finance crumb to bypass API restrictions."""
        if self._yahoo_crumb:
            return self._yahoo_crumb
            
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            async with session.get("https://fc.yahoo.com", headers=headers, allow_redirects=True) as resp:
                pass
            async with session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", headers=headers) as resp:
                if resp.status == 200:
                    self._yahoo_crumb = await resp.text()
                    return self._yahoo_crumb
        except Exception as e:
            _LOGGER.debug(f"Yahoo crumb fetch failed: {e}")
        return None

    async def _enrich_item_with_market_data(self, item: dict) -> dict:
        """Fetch market data to calculate 24h change and enrich an asset or watchlist item."""
        symbol = item.get("symbol")
        data_source = item.get("dataSource")
        
        if symbol and data_source:
            try:
                market_data_resp = await self.api.get_market_data(data_source, symbol)
                history = market_data_resp.get("marketData", [])
                
                if history and isinstance(history, list) and len(history) > 0:
                    latest_idx = -1
                    max_lookback = 5
                    lookback_count = 0
                    
                    current_entry = history[latest_idx]
                    current_price = float(current_entry.get("marketPrice") or 0)

                    while lookback_count < max_lookback and abs(latest_idx) < len(history):
                        prev_idx = latest_idx - 1
                        prev_entry = history[prev_idx]
                        prev_price = float(prev_entry.get("marketPrice") or 0)
                        if current_price != prev_price:
                            break
                        latest_idx -= 1
                        lookback_count += 1
                        current_entry = history[latest_idx]

                    if abs(latest_idx - 1) <= len(history):
                        prev_entry = history[latest_idx - 1]
                        prev_price = float(prev_entry.get("marketPrice") or 0)
                        if prev_price > 0:
                            change_val = current_price - prev_price
                            change_pct = (change_val / prev_price) * 100
                            item["marketChange"] = change_val
                            item["marketChangePercentage"] = change_pct
                    
                    if "marketPrice" not in item or not item["marketPrice"]:
                        item["marketPrice"] = current_price
                    item["marketDate"] = current_entry.get("date")
                
                profile = market_data_resp.get("assetProfile", {})
                if not item.get("currency"):
                    item["currency"] = profile.get("currency")
                if not item.get("assetClass"):
                    item["assetClass"] = profile.get("assetClass")
                    
            except Exception as err:
                _LOGGER.debug(f"Failed to enrich item {symbol}: {err}")
                
        return item

    async def _async_update_data(self):
        """Fetch data from Ghostfolio API."""
        
        if not self._cache_loaded:
            stored_data = await self._store.async_load()
            if stored_data:
                self.fundamentals_cache = stored_data.get("data", {})
                last_update_str = stored_data.get("last_update")
                if last_update_str:
                    self.last_fundamentals_update = dt_util.parse_datetime(last_update_str)

            stored_div_data = await self._dividends_store.async_load()
            if stored_div_data:
                self.dividends_cache = stored_div_data.get("data", {})
                last_div_update_str = stored_div_data.get("last_update")
                if last_div_update_str:
                    self.last_dividends_update = dt_util.parse_datetime(last_div_update_str)

            self._cache_loaded = True

        data = {
            "server_online": False,
            "accounts": {},
            "global_performance": {},
            "account_performances": {},
            "account_holdings": {},
            "watchlist": [],
            "providers": {},
            "fundamentals_data": self.fundamentals_cache,
            "dividends": self.dividends_cache
        }

        try:
            accounts_data = await self.api.get_accounts()
            accounts_list = accounts_data.get("accounts", [])
            global_performance = await self.api.get_portfolio_performance()
            
            account_performances = {}
            holdings_by_account = {}
            watchlist_items = []
            
            show_holdings = self.entry.data.get(CONF_SHOW_HOLDINGS, True)
            show_watchlist = self.entry.data.get(CONF_SHOW_WATCHLIST, True)

            for account in accounts_list:
                if account.get("isExcluded"):
                    continue
                account_id = account["id"]
                
                try:
                    perf_data = await self.api.get_portfolio_performance(account_id=account_id)
                    account_performances[account_id] = perf_data
                except Exception:
                    pass

                if show_holdings:
                    try:
                        holdings_data = await self.api.get_holdings(account_id=account_id)
                        raw_holdings = holdings_data.get("holdings", [])
                        enriched_holdings = []
                        for h in raw_holdings:
                            if float(h.get("quantity") or 0) > 0:
                                h = await self._enrich_item_with_market_data(h)
                            enriched_holdings.append(h)
                        holdings_by_account[account_id] = enriched_holdings
                    except Exception:
                        pass

            if show_watchlist:
                try:
                    wl_response = await self.api.get_watchlist()
                    raw_items = []
                    if isinstance(wl_response, list):
                        raw_items = wl_response
                    elif isinstance(wl_response, dict):
                        raw_items = wl_response.get("watchlist", []) or wl_response.get("items", [])
                    
                    for item in raw_items:
                        enriched_item = await self._enrich_item_with_market_data(item)
                        watchlist_items.append(enriched_item)
                except Exception:
                    pass

            provider_results = {}
            async def _fetch_health(code):
                return await self.api.get_provider_health(code)

            health_results = await asyncio.gather(*[_fetch_health(p) for p in DATA_PROVIDERS])
            for res in health_results:
                provider_results[res["code"]] = res

            # --- Dividends Enrichment (Once a Day) ---
            now = dt_util.utcnow()
            if show_holdings:
                if self.last_dividends_update is None or not self.dividends_cache or (now - self.last_dividends_update) > timedelta(hours=24):
                    _LOGGER.debug("Starting daily Activities data fetch for Dividends")
                    try:
                        activities_resp = await self.api.get_activities()
                        dividend_data = {}
                        for act in activities_resp.get("activities", []):
                            if act.get("type") == "DIVIDEND":
                                acc_id = act.get("accountId")
                                sym = act.get("symbol")
                                
                                if acc_id and sym:
                                    # Fix: Pull the exact cash value of the dividend first.
                                    amount = float(act.get("value") or 0)
                                    
                                    # Fallback in case value is zero but quantity/price exist
                                    if amount == 0:
                                        qty = float(act.get("quantity") or 0)
                                        price = float(act.get("unitPrice") or 0)
                                        amount = qty * price
                                    
                                    if acc_id not in dividend_data:
                                        dividend_data[acc_id] = {}
                                    
                                    dividend_data[acc_id][sym] = dividend_data[acc_id].get(sym, 0.0) + amount
                        
                        self.dividends_cache = dividend_data
                        self.last_dividends_update = now
                        await self._dividends_store.async_save({
                            "data": self.dividends_cache,
                            "last_update": now.isoformat()
                        })
                    except Exception as e:
                        _LOGGER.warning(f"Failed to fetch activities for dividends: {e}")

            data["dividends"] = self.dividends_cache

            # --- Yahoo Finance Fundamentals Enrichment ---
            if self.entry.data.get(CONF_SHOW_FUNDAMENTALS, False):
                if self.last_fundamentals_update is None or (now - self.last_fundamentals_update) > timedelta(hours=24):
                    _LOGGER.debug("Starting daily Fundamentals data fetch via Yahoo")
                    all_tickers = set()

                    for acc_holdings in holdings_by_account.values():
                        for h in acc_holdings:
                            if float(h.get("quantity") or 0) > 0 and h.get("symbol"):
                                all_tickers.add(h.get("symbol"))

                    for w in watchlist_items:
                        if w.get("symbol"):
                            all_tickers.add(w.get("symbol"))

                    if all_tickers:
                        try:
                            session = self.api._get_session()
                            crumb = await self._get_yahoo_crumb(session)
                            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                            
                            for ticker in all_tickers:
                                url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=defaultKeyStatistics,financialData,summaryDetail,earningsTrend"
                                if crumb:
                                    url += f"&crumb={crumb}"
                                
                                try:
                                    async with session.get(url, headers=headers) as response:
                                        if response.status == 200:
                                            resp_json = await response.json()
                                            res = resp_json.get("quoteSummary", {}).get("result", [])
                                            if res:
                                                self.fundamentals_cache[ticker] = res[0]
                                except Exception as inner_e:
                                    _LOGGER.debug(f"Failed to fetch Yahoo data for {ticker}: {inner_e}")
                                
                                await asyncio.sleep(0.5)
                            
                            self.last_fundamentals_update = now
                            await self._store.async_save({
                                "data": self.fundamentals_cache,
                                "last_update": now.isoformat()
                            })
                        except Exception as e:
                            _LOGGER.error(f"Failed Fundamentals enrichment process: {e}")

            data["server_online"] = True
            data["accounts"] = accounts_data
            data["global_performance"] = global_performance
            data["account_performances"] = account_performances
            data["account_holdings"] = holdings_by_account
            data["watchlist"] = watchlist_items
            data["providers"] = provider_results
            data["fundamentals_data"] = self.fundamentals_cache
            
            return data

        except Exception as err:
            _LOGGER.warning(f"Ghostfolio API update failed: {err}")
            return data

    async def async_prune_orphans(self) -> None:
        """Remove entities that no longer exist in Ghostfolio."""
        if not self.data or not self.data.get("server_online", False):
            return

        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(entity_registry, self.entry.entry_id)
        
        valid_unique_ids = set()
        entry_id = self.entry.entry_id
        
        if self.entry.data.get(CONF_SHOW_TOTALS, True):
            valid_unique_ids.add(f"ghostfolio_current_value_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_net_performance_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_net_performance_percent_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_total_investment_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_net_performance_percent_with_currency_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_net_performance_with_currency_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_simple_gain_percent_{entry_id}")

        valid_unique_ids.add(f"ghostfolio_server_status_{entry_id}")
        for provider in DATA_PROVIDERS:
            valid_unique_ids.add(f"ghostfolio_provider_{provider.lower()}_{entry_id}")

        valid_unique_ids.add(f"ghostfolio_prune_button_{entry_id}")

        show_accounts = self.entry.data.get(CONF_SHOW_ACCOUNTS, True)
        accounts_list = self.data.get("accounts", {}).get("accounts", [])
        
        for account in accounts_list:
            if account.get("isExcluded"):
                continue
            account_id = account["id"]
            if show_accounts:
                valid_unique_ids.add(f"ghostfolio_account_value_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_net_worth_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_cost_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_perf_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_perf_pct_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_simple_gain_{account_id}_{entry_id}")

        if self.entry.data.get(CONF_SHOW_HOLDINGS, True):
            all_holdings = self.data.get("account_holdings", {})
            for account in accounts_list:
                if account.get("isExcluded"):
                    continue
                account_id = account["id"]
                holdings = all_holdings.get(account_id, [])
                for h in holdings:
                    if float(h.get("quantity") or 0) > 0:
                        symbol = h.get("symbol")
                        safe_symbol = slugify(symbol)
                        valid_unique_ids.add(f"ghostfolio_holding_{account_id}_{safe_symbol}_{entry_id}")
                        valid_unique_ids.add(f"ghostfolio_limit_low_{account_id}_{safe_symbol}_{entry_id}")
                        valid_unique_ids.add(f"ghostfolio_limit_high_{account_id}_{safe_symbol}_{entry_id}")

        if self.entry.data.get(CONF_SHOW_WATCHLIST, True):
            watchlist = self.data.get("watchlist", [])
            for item in watchlist:
                symbol = item.get("symbol")
                safe_symbol = slugify(symbol)
                valid_unique_ids.add(f"ghostfolio_watchlist_{safe_symbol}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_watchlist_limit_low_{safe_symbol}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_watchlist_limit_high_{safe_symbol}_{entry_id}")

        if self.entry.data.get(CONF_SHOW_FUNDAMENTALS, False):
            fund_payload = self.data.get("fundamentals_data", {})
            for symbol in fund_payload.keys():
                safe_symbol = slugify(symbol)
                valid_unique_ids.add(f"ghostfolio_fundamentals_{safe_symbol}_{entry_id}")

        for entity_entry in entries:
            if entity_entry.unique_id not in valid_unique_ids:
                entity_registry.async_remove(entity_entry.entity_id)
