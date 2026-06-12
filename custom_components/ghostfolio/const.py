"""Constants for the Ghostfolio integration."""

DOMAIN = "ghostfolio"

# Configuration keys
CONF_BASE_URL = "base_url"
CONF_ACCESS_TOKEN = "access_token"
CONF_VERIFY_SSL = "verify_ssl"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_PORTFOLIO_NAME = "portfolio_name"
CONF_SHOW_TOTALS = "show_totals"
CONF_SHOW_ACCOUNTS = "show_accounts"
CONF_SHOW_HOLDINGS = "show_holdings"
CONF_SHOW_WATCHLIST = "show_watchlist"
CONF_SHOW_FUNDAMENTALS = "show_fundamentals"

# Default values
DEFAULT_NAME = "Ghostfolio"
DEFAULT_UPDATE_INTERVAL = 15  # minutes

# Price limit number entity configuration
PRICE_LIMIT_MAX = 900_000

# Delay between sequential Yahoo Finance API requests to avoid rate limiting (seconds)
YAHOO_REQUEST_DELAY = 0.5

# Yahoo Finance direct API
YAHOO_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
YAHOO_SESSION_URL = "https://fc.yahoo.com"
YAHOO_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
YAHOO_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary"

def portfolio_device_info(config_entry) -> dict:
    """Return the shared device_info dict for the top-level portfolio device."""
    from homeassistant.config_entries import ConfigEntry  # local import avoids circular dep
    name = config_entry.data.get(CONF_PORTFOLIO_NAME, "Ghostfolio")
    return {
        "identifiers": {(DOMAIN, f"ghostfolio_portfolio_{config_entry.entry_id}")},
        "name": f"{name} Portfolio",
        "manufacturer": "Ghostfolio",
        "model": "Portfolio Tracker",
    }


# Event fired when a price limit is crossed
EVENT_LIMIT_ALERT = "ghostfolio_limit_alert"

# Sentinel used as account_id for watchlist-scope limit entities
WATCHLIST_SCOPE = "watchlist_scope"

# Symbol used as a proxy to determine US market state
YAHOO_MARKET_PROXY = "SPY"

# Service names
SERVICE_REFRESH_FUNDAMENTALS = "refresh_fundamentals"
SERVICE_FETCH_24H_CHANGE = "fetch_24h_change"
SERVICE_FETCH_PREMARKET = "fetch_premarket_data"

# Lynch PEG ratio valuation thresholds
LYNCH_PEG_UNDERVALUED = 1.0
LYNCH_PEG_OVERPRICED = 2.0

# API client configuration
API_TIMEOUT = 30       # seconds
API_MAX_RETRIES = 3

# Data Providers to check
DATA_PROVIDERS = [
    "YAHOO",
    "COINGECKO",
    "ALPHA_VANTAGE",
    "FINANCIAL_MODELING_PREP",
    "EOD_HISTORICAL_DATA",
]
