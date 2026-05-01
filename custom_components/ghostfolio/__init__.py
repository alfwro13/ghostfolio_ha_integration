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
        """Force a refresh of Yahoo Finance caches."""
        for e in hass.config_entries.async_entries(DOMAIN):
            if hasattr(e, "runtime_data"):
                coord = e.runtime_data
                if isinstance(coord, GhostfolioDataUpdateCoordinator):
                    _LOGGER.info("Forcing on-demand refresh of Yahoo Caches")
                    coord.last_fundamentals_update = None
                    coord.last_previous_close_update = None
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
        
        self.previous_close_cache = {}
        self.last_previous_close_update = None

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

    async def _save_cache(self):
        """Save the current caches to HA storage."""
        payload = {
            "fundamentals_data": self.fundamentals_cache,
            "previous_close_data": self.previous_close_cache,
        }
        if self.last_fundamentals_update:
            payload["last_fundamentals_update"] = self.last_fundamentals_update.isoformat()
        if self.last_previous_close_update:
            payload["last_previous_close_update"] = self.last_previous_close_update.isoformat()
            
        await self._store.async_save(payload)

    async def _enrich_item_with_market_data(self, item: dict) -> dict:
        """Enrich an asset or watchlist item with 24h change using cached Previous Close."""
        symbol = item.get("symbol")
        data_source = item.get("dataSource")
        
        if symbol and data_source:
            try:
                market_data_resp = await self.api.get_market_data(data_source, symbol)
                history = market_data_resp.get("marketData", [])
                profile = market_data_resp.get("assetProfile", {})
                
                real_time_price = float(item.get("marketPrice") or 0)
                if not real_time_price and history:
                    real_time_price = float(history[-1].get("marketPrice") or 0)
                    
                change_pct = None
                prev_price = 0
                
                # 1. Primary Method: Use 24h Cached Yahoo Previous Close
                if data_source == "YAHOO" and symbol in self.previous_close_cache:
                    prev_price = self.previous_close_cache[symbol]
                    if prev_price > 0 and real_time_price > 0:
                        change_pct = ((real_time_price - prev_price) / prev_price) * 100

                # 2. Fallback Method: Strict Date Historical Array (For Crypto / Non-Yahoo)
                if change_pct is None and history:
                    today_str = dt_util.utcnow().date().isoformat()
                    latest_hist_date = history[-1].get("date", "")[:10]
                    target_date = latest_hist_date if latest_hist_date >= today_str else today_str
                            
                    for entry in reversed(history):
                        entry_date = entry.get("date", "")[:10]
                        if entry_date and entry_date < target_date:
                            prev_price = float(entry.get("marketPrice") or 0)
                            break
                            
                    if prev_price == 0:
                        prev_price = float(history[-1].get("marketPrice") or 0)

                    if prev_price > 0 and real_time_price > 0:
                        change_pct = ((real_time_price - prev_price) / prev_price) * 100

                # 3. Apply Local Math
                if change_pct is not None:
                    item["marketChangePercentage"] = change_pct
                    # Because prev_price and real_time_price are in identical units (e.g. Pence), standard math works
                    item["marketChange"] = real_time_price - prev_price

                item["marketPrice"] = real_time_price
                if history:
                    item["marketDate"] = history[-1].get("date")
                
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
                self.fundamentals_cache = stored_data.get("fundamentals_data", stored_data.get("data", {}))
                self.previous_close_cache = stored_data.get("previous_close_data", {})
                
                f_up = stored_data.get("last_fundamentals_update", stored_data.get("last_update"))
                if f_up:
                    self.last_fundamentals_update = dt_util.parse_datetime(f_up)
                    
                p_up = stored_data.get("last_previous_close_update")
                if p_up:
                    self.last_previous_close_update = dt_util.parse_datetime(p_up)

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
            raw_account_holdings = {}
            raw_watchlist_items = []
            all_yahoo_tickers = set()
            
            show_holdings = self.entry.data.get(CONF_SHOW_HOLDINGS, True)
            show_watchlist = self.entry.data.get(CONF_SHOW_WATCHLIST, True)

            # 1. GATHER RAW DATA & IDENTIFY YAHOO TICKERS
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
                        raw_account_holdings[account_id] = raw_holdings
                        
                        for h in raw_holdings:
                            if float(h.get("quantity") or 0) > 0 and h.get("symbol") and h.get("dataSource") == "YAHOO":
                                all_yahoo_tickers.add(h.get("symbol"))
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
                    
                    raw_watchlist_items = raw_items
                    for item in raw_items:
                        if item.get("symbol") and item.get("dataSource") == "YAHOO":
                            all_yahoo_tickers.add(item.get("symbol"))
                except Exception:
                    pass

            # 2. DAILY YAHOO PREVIOUS CLOSE FETCH (Once per 24h)
            now = dt_util.utcnow()
            if self.last_previous_close_update is None or (now - self.last_previous_close_update) > timedelta(hours=24):
                if all_yahoo_tickers:
                    _LOGGER.debug("Starting daily Previous Close data fetch via Yahoo")
                    try:
                        session = self.api._get_session()
                        crumb = await self._get_yahoo_crumb(session)
                        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                        
                        for ticker in all_yahoo_tickers:
                            url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=price"
                            if crumb:
                                url += f"&crumb={crumb}"
                            
                            try:
                                async with session.get(url, headers=headers) as response:
                                    if response.status == 200:
                                        resp_json = await response.json()
                                        res = resp_json.get("quoteSummary", {}).get("result", [])
                                        if res:
                                            price_data = res[0].get("price", {})
                                            prev_close = price_data.get("regularMarketPreviousClose", {}).get("raw")
                                            if prev_close is not None:
                                                self.previous_close_cache[ticker] = prev_close
                            except Exception as inner_e:
                                _LOGGER.debug(f"Failed to fetch Yahoo prev close for {ticker}: {inner_e}")
                            
                            await asyncio.sleep(0.5)
                        
                        self.last_previous_close_update = now
                        await self._save_cache()
                    except Exception as e:
                        _LOGGER.error(f"Failed Previous Close fetch process: {e}")

            # 3. ENRICH HOLDINGS & WATCHLIST WITH LOCAL MATH
            holdings_by_account = {}
            for account_id, raw_holdings in raw_account_holdings.items():
                enriched_holdings = []
                for h in raw_holdings:
                    if float(h.get("quantity") or 0) > 0:
                        enriched_holdings.append(await self._enrich_item_with_market_data(h))
                holdings_by_account[account_id] = enriched_holdings

            watchlist_items = []
            for w in raw_watchlist_items:
                watchlist_items.append(await self._enrich_item_with_market_data(w))

            # 4. PROVIDER HEALTH
            provider_results = {}
            async def _fetch_health(code):
                return await self.api.get_provider_health(code)

            health_results = await asyncio.gather(*[_fetch_health(p) for p in DATA_PROVIDERS])
            for res in health_results:
                provider_results[res["code"]] = res

            # 5. DIVIDENDS ENRICHMENT
            if self.last_dividends_update is None or not self.dividends_cache or (now - self.last_dividends_update) > timedelta(hours=24):
                _LOGGER.debug("Fetching Activities data for Dividends")
                try:
                    activities_resp = await self.api.get_activities()
                    dividend_data = {}
                    
                    act_list = []
                    if isinstance(activities_resp, list):
                        act_list = activities_resp
                    elif isinstance(activities_resp, dict):
                        act_list = activities_resp.get("activities", [])
                        
                    for act in act_list:
                        act_type = act.get("type", "").upper()
                        if act_type == "DIVIDEND":
                            acc_id = act.get("accountId")
                            
                            sym = act.get("symbol")
                            if not sym and "SymbolProfile" in act:
                                sym = act["SymbolProfile"].get("symbol")
                            
                            if acc_id and sym:
                                sym = sym.upper()
                                
                                amount = float(act.get("valueInBaseCurrency") or 0)
                                if amount == 0:
                                    amount = float(act.get("value") or 0)
                                if amount == 0:
                                    qty = float(act.get("quantity") or 0)
                                    price = float(act.get("unitPrice") or 0)
                                    amount = qty * price
                                
                                if acc_id not in dividend_data:
                                    dividend_data[acc_id] = {}
                                
                                dividend_data[acc_id][sym] = dividend_data[acc_id].get(sym, 0.0) + amount
                    
                    self.dividends_cache = dividend_data
                    self.last_dividends_update = now
                except Exception as e:
                    _LOGGER.error(f"Failed to fetch activities for dividends: {e}")

            data["dividends"] = self.dividends_cache

            # 6. YAHOO FUNDAMENTALS ENRICHMENT
            if self.entry.data.get(CONF_SHOW_FUNDAMENTALS, False):
                if self.last_fundamentals_update is None or (now - self.last_fundamentals_update) > timedelta(hours=24):
                    _LOGGER.debug("Starting daily Fundamentals data fetch via Yahoo")
                    if all_yahoo_tickers:
                        try:
                            session = self.api._get_session()
                            crumb = await self._get_yahoo_crumb(session)
                            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                            
                            for ticker in all_yahoo_tickers:
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
                                    _LOGGER.debug(f"Failed to fetch Yahoo fundamentals for {ticker}: {inner_e}")
                                
                                await asyncio.sleep(0.5)
                            
                            self.last_fundamentals_update = now
                            await self._save_cache()
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
            valid_unique_ids.add(f"ghostfolio_portfolio_dividends_{entry_id}")

        valid_unique_ids.add(f"ghostfolio_server_status_{entry_id}")
        for provider in DATA_PROVIDERS:
            valid_unique_ids.add(f"ghostfolio_provider_{provider.lower()}_{entry_id}")

        valid_unique_ids.add(f"ghostfolio_prune_button_{entry_id}")

        show_accounts = self.entry.data.get(CONF_SHOW_ACCOUNTS, True)
        accounts_list = self.data.get("accounts", {}).get("accounts", [])
