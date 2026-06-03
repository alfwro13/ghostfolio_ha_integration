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

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SWITCH]


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

    # --- Register Custom Services for Manual Fetches ---
    async def refresh_fundamentals(call):
        for e in hass.config_entries.async_entries(DOMAIN):
            if hasattr(e, "runtime_data"):
                coord = e.runtime_data
                if isinstance(coord, GhostfolioDataUpdateCoordinator):
                    await coord.async_fetch_fundamentals()
                    await coord.async_request_refresh()

    async def fetch_24h_change(call):
        for e in hass.config_entries.async_entries(DOMAIN):
            if hasattr(e, "runtime_data"):
                coord = e.runtime_data
                if isinstance(coord, GhostfolioDataUpdateCoordinator):
                    await coord.async_fetch_24h_change()
                    await coord.async_request_refresh()

    async def fetch_premarket_data(call):
        for e in hass.config_entries.async_entries(DOMAIN):
            if hasattr(e, "runtime_data"):
                coord = e.runtime_data
                if isinstance(coord, GhostfolioDataUpdateCoordinator):
                    await coord.async_fetch_premarket()
                    await coord.async_request_refresh()

    if not hass.services.has_service(DOMAIN, "refresh_fundamentals"):
        hass.services.async_register(DOMAIN, "refresh_fundamentals", refresh_fundamentals)
    if not hass.services.has_service(DOMAIN, "fetch_24h_change"):
        hass.services.async_register(DOMAIN, "fetch_24h_change", fetch_24h_change)
    if not hass.services.has_service(DOMAIN, "fetch_premarket_data"):
        hass.services.async_register(DOMAIN, "fetch_premarket_data", fetch_premarket_data)

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

        self.premarket_cache = {}
        self.us_market_open: bool | None = None

        self.dividends_cache = {}
        self.last_dividends_update = None

        self._cache_loaded = False
        self._yahoo_crumb = None
        self.sync_paused = False

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

    def _get_active_yahoo_symbols(self, us_only=False) -> list[str]:
        """Extract all Yahoo symbols currently tracked in the coordinator's data."""
        tickers = set()
        if not self.data:
            return []
            
        holdings = self.data.get("account_holdings", {})
        for acc_holdings in holdings.values():
            for h in acc_holdings:
                if float(h.get("quantity") or 0) > 0 and h.get("dataSource") == "YAHOO":
                    sym = h.get("symbol")
                    if sym:
                        if us_only and "." in sym:
                            continue
                        tickers.add(sym)
                        
        for w in self.data.get("watchlist", []):
            if w.get("dataSource") == "YAHOO":
                sym = w.get("symbol")
                if sym:
                    if us_only and "." in sym:
                        continue
                    tickers.add(sym)
                    
        return list(tickers)

    async def _async_check_us_market_state(self, session, crumb) -> bool | None:
        """Check if US market is open using SPY as a universal proxy."""
        url = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=SPY"
        if crumb:
            url += f"&crumb={crumb}"
            
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    res = data.get("quoteResponse", {}).get("result", [])
                    if res:
                        state = res[0].get("marketState", "")
                        return state == "REGULAR"
        except Exception as e:
            _LOGGER.debug(f"Failed to check US market state: {e}")
        return None

    async def async_fetch_premarket(self):
        """Manually fetch Pre-market data for US stocks using bulk API."""
        _LOGGER.info("Manually fetching Pre-Market data from Yahoo")
        session = self.api._get_session()
        crumb = await self._get_yahoo_crumb(session)
        
        # 1. Update the Market State Sensor
        is_open = await self._async_check_us_market_state(session, crumb)
        if is_open is not None:
            self.us_market_open = is_open
            
        # 2. Smart Purge: If the market is open, wipe cache and abort fetch
        if self.us_market_open:
            _LOGGER.debug("US Market is open. Skipping pre-market fetch and clearing cache.")
            self.premarket_cache.clear()
            return
            
        # 3. If market closed, proceed with fetch
        tickers = self._get_active_yahoo_symbols(us_only=True)
        if not tickers:
            return
            
        symbol_string = ",".join(tickers)
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol_string}"
        
        try:
            if crumb:
                url += f"&crumb={crumb}"
                
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    resp_json = await response.json()
                    results = resp_json.get("quoteResponse", {}).get("result", [])
                    for res in results:
                        sym = res.get("symbol")
                        state = res.get("marketState", "")
                        price = None
                        
                        if "PRE" in state:
                            price = res.get("preMarketPrice")
                        elif "POST" in state or state == "CLOSED":
                            price = res.get("postMarketPrice") or res.get("regularMarketPrice")
                            
                        if price is not None and sym:
                            self.premarket_cache[sym] = float(price)
        except Exception as e:
            _LOGGER.error(f"Failed pre-market fetch process: {e}")

    async def async_fetch_24h_change(self):
        """Manually fetch previous close using sequential API calls."""
        _LOGGER.info("Manually fetching 24h Change (Previous Close) from Yahoo")
        tickers = self._get_active_yahoo_symbols()
        if not tickers: 
            return
            
        try:
            session = self.api._get_session()
            crumb = await self._get_yahoo_crumb(session)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            
            for ticker in tickers:
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
                except Exception as e:
                    _LOGGER.debug(f"Failed to fetch previous close for {ticker}: {e}")
                    
                await asyncio.sleep(0.5)
                
            self.last_previous_close_update = dt_util.utcnow()
            await self._save_cache()
        except Exception as e:
            _LOGGER.error(f"Failed 24h change fetch process: {e}")

    async def async_fetch_fundamentals(self):
        """Manually fetch deep fundamentals using sequential API calls."""
        _LOGGER.info("Manually fetching Fundamentals from Yahoo")
        tickers = self._get_active_yahoo_symbols()
        if not tickers: 
            return
            
        try:
            session = self.api._get_session()
            crumb = await self._get_yahoo_crumb(session)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            
            for ticker in tickers:
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
                except Exception as e:
                    _LOGGER.debug(f"Failed to fetch fundamentals for {ticker}: {e}")
                    
                await asyncio.sleep(0.5)
                
            self.last_fundamentals_update = dt_util.utcnow()
            await self._save_cache()
        except Exception as e:
            _LOGGER.error(f"Failed fundamentals fetch process: {e}")

    async def _enrich_item_with_market_data(self, item: dict) -> dict:
        """Enrich an asset or watchlist item."""
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

                # --- 1. EXTRACT PRE-MARKET OVERRIDE ---
                # Check ephemeral cache. No timers needed, cache is managed by market state.
                premarket_price = None
                if data_source == "YAHOO" and symbol in self.premarket_cache:
                    premarket_price = self.premarket_cache[symbol]
                    
                change_pct = None
                prev_price = 0
                
                # --- 2. PRIMARY METHOD: CACHED PREVIOUS CLOSE ---
                if data_source == "YAHOO" and symbol in self.previous_close_cache:
                    prev_price = self.previous_close_cache[symbol]
                    if prev_price > 0 and real_time_price > 0:
                        change_pct = ((real_time_price - prev_price) / prev_price) * 100

                # --- 3. FALLBACK METHOD: GHOSTFOLIO HISTORY ---
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

                # --- 4. APPLY STANDARD DATA ---
                if change_pct is not None:
                    item["marketChangePercentage"] = change_pct
                    item["marketChange"] = real_time_price - prev_price

              
                # SAFEGUARD: Override ONLY runs if pre-market price is explicitly loaded, valid, and different
                if premarket_price is not None and float(premarket_price) > 0 and float(premarket_price) != real_time_price:
                    premarket_price = float(premarket_price)
                    quantity = float(item.get("quantity") or 0)
                    original_value_base = float(item.get("valueInBaseCurrency") or item.get("value") or 0)
                    
                    if real_time_price > 0 and quantity > 0:
                        # 1. Extract the exact currency conversion rate Ghostfolio natively used
                        implied_fx_rate = original_value_base / (real_time_price * quantity)
                        
                        # 2. Calculate the updated holding values based on the premarket price
                        new_value_asset_currency = premarket_price * quantity
                        new_value_base_currency = new_value_asset_currency * implied_fx_rate
                        
                        # 3. Override the main dictionary keys. HA sensors use these automatically.
                        item["marketPrice"] = premarket_price
                        item["value"] = new_value_asset_currency
                        item["valueInBaseCurrency"] = new_value_base_currency
                        
                        # 4. Optional: Recalculate 24h change so the % matches the pre-market movement
                        if prev_price > 0:
                            item["marketChangePercentage"] = ((premarket_price - prev_price) / prev_price) * 100
                            item["marketChange"] = premarket_price - prev_price
                            
                        item["is_premarket"] = True
                        _LOGGER.debug(f"[{symbol}] State overridden with premarket price: {premarket_price}")
                else:
                    # Regular market hours: Ensure standard pricing is set and no native values are touched
                    item["marketPrice"] = real_time_price
                    item["is_premarket"] = False
                # ==========================================

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

        if getattr(self, "sync_paused", False) and self.data is not None:
            _LOGGER.debug("Ghostfolio sync is paused. Returning last known data.")
            return self.data
        
        # Load long-term cache exactly once on boot
        if not self._cache_loaded:
            stored_data = await self._store.async_load()
            if stored_data:
                self.fundamentals_cache = stored_data.get("fundamentals_data", stored_data.get("data", {}))
                self.previous_close_cache = stored_data.get("previous_close_data", {})
                
                f_up = stored_data.get("last_fundamentals_update", stored_data.get("last_update"))
                if f_up: self.last_fundamentals_update = dt_util.parse_datetime(f_up)
                    
                p_up = stored_data.get("last_previous_close_update")
                if p_up: self.last_previous_close_update = dt_util.parse_datetime(p_up)

            self._cache_loaded = True

        # --- UPDATE US MARKET STATE SENSOR ---
        try:
            session = self.api._get_session()
            crumb = await self._get_yahoo_crumb(session)
            is_open = await self._async_check_us_market_state(session, crumb)
            if is_open is not None:
                self.us_market_open = is_open
        except Exception:
            pass

        # Smart Purge: Guarantee the cache is empty if the market is open
        if self.us_market_open:
            self.premarket_cache.clear()

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
            
            show_watchlist = self.entry.data.get(CONF_SHOW_WATCHLIST, True)

            # 1. GATHER RAW DATA
            for account in accounts_list:
                if account.get("isExcluded"):
                    continue
                account_id = account["id"]
                
                try:
                    perf_data = await self.api.get_portfolio_performance(account_id=account_id)
                    account_performances[account_id] = perf_data
                except Exception:
                    pass

                # ALWAYS fetch holdings because Global/Account Gain sensors now require them to calculate P&L
                try:
                    holdings_data = await self.api.get_holdings(account_id=account_id)
                    raw_account_holdings[account_id] = holdings_data.get("holdings", [])
                except Exception:
                    pass

            if show_watchlist:
                try:
                    wl_response = await self.api.get_watchlist()
                    if isinstance(wl_response, list):
                        raw_watchlist_items = wl_response
                    elif isinstance(wl_response, dict):
                        raw_watchlist_items = wl_response.get("watchlist", []) or wl_response.get("items", [])
                except Exception:
                    pass

            # 2. PROVIDER HEALTH
            provider_results = {}
            async def _fetch_health(code):
                return await self.api.get_provider_health(code)

            health_results = await asyncio.gather(*[_fetch_health(p) for p in DATA_PROVIDERS])
            for res in health_results:
                provider_results[res["code"]] = res

            # 3. DIVIDENDS ENRICHMENT (Local Ghostfolio API)
            now = dt_util.utcnow()
            if self.last_dividends_update is None or not self.dividends_cache or now.date() > self.last_dividends_update.date():
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
                                if amount == 0: amount = float(act.get("value") or 0)
                                if amount == 0: amount = float(act.get("quantity") or 0) * float(act.get("unitPrice") or 0)
                                
                                if acc_id not in dividend_data:
                                    dividend_data[acc_id] = {}
                                dividend_data[acc_id][sym] = dividend_data[acc_id].get(sym, 0.0) + amount
                    
                    self.dividends_cache = dividend_data
                    self.last_dividends_update = now
                except Exception as e:
                    _LOGGER.error(f"Failed to fetch activities for dividends: {e}")

            data["dividends"] = self.dividends_cache

            # 4. ENRICH HOLDINGS & WATCHLIST WITH LIVE & CACHED DATA
            holdings_by_account = {}
            for account_id, raw_holdings in raw_account_holdings.items():
                enriched_holdings = []
                for h in raw_holdings:
                    # --- FIX FOR GHOSTFOLIO 3.7.0 ---
                    # Restore removed attributes from the nested SymbolProfile
                    if "SymbolProfile" in h:
                        sp = h["SymbolProfile"]
                        for attr in ["symbol", "dataSource", "currency", "assetClass", "name", "assetSubClass"]:
                            if not h.get(attr) and sp.get(attr):
                                h[attr] = sp.get(attr)
                    # --------------------------------

                    if float(h.get("quantity") or 0) > 0:
                        # Only enrich non-cash assets to save API calls
                        if h.get("assetClass") == "LIQUIDITY":
                            enriched_holdings.append(h)
                        else:
                            enriched_holdings.append(await self._enrich_item_with_market_data(h))
                holdings_by_account[account_id] = enriched_holdings

            watchlist_items = []
            for w in raw_watchlist_items:
                # --- FIX FOR GHOSTFOLIO 3.7.0 ---
                if "SymbolProfile" in w:
                    sp = w["SymbolProfile"]
                    for attr in ["symbol", "dataSource", "currency", "assetClass", "name", "assetSubClass"]:
                        if not w.get(attr) and sp.get(attr):
                            w[attr] = sp.get(attr)
                # --------------------------------
                watchlist_items.append(await self._enrich_item_with_market_data(w))

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
            valid_unique_ids.add(f"ghostfolio_unrealized_pnl_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_net_performance_percent_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_total_investment_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_net_performance_percent_with_currency_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_net_performance_with_currency_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_simple_gain_percent_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_unrealized_pnl_percent_{entry_id}")
            valid_unique_ids.add(f"ghostfolio_portfolio_dividends_{entry_id}")

        valid_unique_ids.add(f"ghostfolio_server_status_{entry_id}")
        valid_unique_ids.add(f"ghostfolio_us_market_{entry_id}")
        
        for provider in DATA_PROVIDERS:
            valid_unique_ids.add(f"ghostfolio_provider_{provider.lower()}_{entry_id}")

        valid_unique_ids.add(f"ghostfolio_prune_button_{entry_id}")
        valid_unique_ids.add(f"ghostfolio_pause_sync_{entry_id}")

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
                valid_unique_ids.add(f"ghostfolio_account_unrealized_pnl_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_perf_pct_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_simple_gain_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_unrealized_pnl_percent_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_dividends_{account_id}_{entry_id}")
                valid_unique_ids.add(f"ghostfolio_account_cash_balance_{account_id}_{entry_id}")

        if self.entry.data.get(CONF_SHOW_HOLDINGS, True):
            all_holdings = self.data.get("account_holdings", {})
            for account in accounts_list:
                if account.get("isExcluded"):
                    continue
                account_id = account["id"]
                holdings = all_holdings.get(account_id, [])
                for h in holdings:
                    if float(h.get("quantity") or 0) > 0:
                        # Skip adding to valid ids if it's cash, we don't want a holding sensor for it
                        if h.get("assetClass") == "LIQUIDITY":
                            continue
                            
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
