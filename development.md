# Development Guide

This document provides guidance for developers who want to contribute to or modify the Ghostfolio Home Assistant integration.

## Prerequisites

- Python 3.12 or higher (3.12+ required for `type` alias syntax used in `GhostfolioConfigEntry`)
- Home Assistant Core 2025.6.0 or higher
- A running Ghostfolio instance for testing
- Git for version control

## Development Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd ghostfolio_ha_integration
```

### 2. Set up Home Assistant Development Environment

You can develop this integration using one of these approaches:

#### Option A: Home Assistant Container Development

1. Create a `config` directory in the project root
2. Copy the `custom_components/ghostfolio` directory to `config/custom_components/ghostfolio`
3. Run Home Assistant in a container with the config directory mounted

```bash
docker run -d \
  --name homeassistant \
  --privileged \
  --restart=unless-stopped \
  -e TZ=YOUR_TIME_ZONE \
  -v $(pwd)/config:/config \
  -p 8123:8123 \
  ghcr.io/home-assistant/home-assistant:stable
```

#### Option B: Home Assistant Core Development

1. Install Home Assistant Core in a virtual environment
2. Symlink the integration to your Home Assistant config directory

```bash
python3 -m venv venv
source venv/bin/activate
pip install homeassistant
ln -s $(pwd)/custom_components/ghostfolio ~/.homeassistant/custom_components/ghostfolio
```

### 3. Configure the Integration

1. Start Home Assistant
2. Go to Settings > Devices & Services > Add Integration
3. Search for "Ghostfolio" and configure it with your Ghostfolio instance details

## Project Structure

```
ghostfolio_ha_integration/
├── custom_components/ghostfolio/
│   ├── __init__.py          # Integration setup, coordinator, services, GhostfolioConfigEntry
│   ├── api.py               # Ghostfolio API client with retry logic and auth lock
│   ├── binary_sensor.py     # Server, US Market, and Data Provider sensors
│   ├── button.py            # Prune and watchlist limit disable buttons
│   ├── config_flow.py       # Configuration and reconfigure flows
│   ├── const.py             # All constants (keys, URLs, delays, limits, portfolio_device_info)
│   ├── diagnostics.py       # HA diagnostics platform (Download Diagnostics button)
│   ├── manifest.json        # Integration metadata
│   ├── number.py            # Price limit number entities (High/Low per asset)
│   ├── sensor.py            # All sensor entities (global, account, holding, watchlist, fundamentals)
│   ├── services.yaml        # Custom service definitions (with config_entry_id field)
│   ├── strings.json         # Base translation strings (source of truth)
│   ├── switch.py            # Pause Sync switch
│   └── translations/
│       ├── de.json          # German translations
│       ├── en.json          # English translations
│       └── fr.json          # French translations
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared fixtures and sample data
│   ├── test_config_flow.py  # Config flow happy path and error cases
│   ├── test_coordinator.py  # Coordinator update, UpdateFailed, sync-paused tests
│   └── test_init.py         # Setup/unload lifecycle and one entity per platform
├── .github/workflows/
│   ├── hassfest.yaml        # Validates manifest and integration structure
│   ├── validate.yml         # HACS validation
│   └── release.yml          # Automated release on version bump
├── assets/                  # Example automations and dashboard configs
├── docker-compose.yml       # Local Ghostfolio instance for testing
├── hacs.json                # HACS metadata
├── pytest.ini               # Test runner configuration
└── requirements_test.txt    # Test dependencies
```

## Key Components

### Coordinator (`__init__.py`)

The `GhostfolioDataUpdateCoordinator` is the heart of the integration. It extends HA's `DataUpdateCoordinator` and manages all data fetching.

**Data sources:**
- Ghostfolio API — accounts, holdings, watchlist, performance, activities, provider health
- Yahoo Finance (direct) — crumb-based auth, pre-market/post-market prices, previous close, fundamentals

**Caching:**
- Fundamentals data, previous close prices, and `sync_paused` state are persisted to HA storage (`Store`) and survive restarts.
- Cache key: `ghostfolio_fundamentals_cache_{entry_id}`

**Pause Sync:**
- `sync_paused` flag prevents API calls and cancels the update timer when `True`.
- State is saved to the store and restored on startup.
- `_schedule_refresh()` is overridden to suppress timer scheduling while paused.
- Use `async_set_sync_paused(True/False)` — do not set the attribute directly.

**Failure semantics:** `_async_update_data()` raises `UpdateFailed` on any top-level API error. The coordinator retains the last-good `data` dict and sets `last_update_success = False`, causing all `CoordinatorEntity`-based entities to become unavailable automatically. Per-account soft failures (individual account fetch errors) are logged at DEBUG and do not abort the whole update.

**Key methods:**
- `_async_update_data()` — main coordinator update, raises `UpdateFailed` on API failure
- `async_set_sync_paused(paused)` — pause/resume with persistence and timer control
- `async_fetch_premarket()` — fetches Yahoo pre/post-market prices for US symbols
- `async_fetch_24h_change()` — fetches previous close prices from Yahoo
- `async_fetch_fundamentals()` — fetches PEG, margins, earnings data from Yahoo
- `_yahoo_quote_summary_fetch_all(modules, label)` — shared loop used by both fetch methods above; handles crumb expiry, per-ticker errors, and rate-limit sleep
- `_flatten_symbol_profile(item)` — promotes Ghostfolio 3.7.0 nested `symbolProfile` fields to the top level (mutates in place)
- `_enrich_item_with_market_data()` — enriches a holding/watchlist item with live prices and history
- `async_prune_orphans()` — removes entities no longer present in Ghostfolio

**Custom services registered:**
- `ghostfolio.refresh_fundamentals`
- `ghostfolio.fetch_24h_change`
- `ghostfolio.fetch_premarket_data`

All three services accept an optional `config_entry_id` field; when present, only the matching entry is acted on. Services are registered once (guarded by `has_service`) and removed when the last config entry is unloaded.

**Typed config entry:** `GhostfolioConfigEntry = ConfigEntry[GhostfolioDataUpdateCoordinator]` is defined at the bottom of `__init__.py` and imported by all platform files. Use it as the type annotation for `entry` parameters instead of bare `ConfigEntry` so that `entry.runtime_data` is correctly typed without casts.

---

### API Client (`api.py`)

`GhostfolioAPI` handles all communication with the Ghostfolio backend.

- Authenticates via `POST /api/v1/auth/anonymous` and caches the bearer token.
- Automatically re-authenticates on 401 responses.
- All requests use a single persistent `aiohttp.ClientSession` (created lazily, closed on entry unload).
- `_make_authenticated_request()` retries up to 3 times on `aiohttp.ClientError` with 1s / 2s backoff. HTTP 4xx/5xx errors are not retried.
- Call `await api.close()` to release the session (done automatically in `async_unload_entry`).

**Methods:**
- `authenticate()` — fetches and stores auth token
- `get_portfolio_performance(account_id)` — global or per-account performance
- `get_accounts()` — accounts list and base currency
- `get_holdings(account_id)` — holdings per account
- `get_watchlist()` — watchlist items
- `get_activities()` — all transactions (used for dividend calculation)
- `get_market_data(data_source, symbol)` — price history and asset profile
- `get_provider_health(provider_code)` — data provider health status
- `close()` — closes the aiohttp session

---

### Sensors (`sensor.py`)

All sensors extend `GhostfolioBaseSensor` (or `GhostfolioAccountBaseSensor` for account-scoped ones), which extends `CoordinatorEntity` + `SensorEntity`.

**Global Portfolio Sensors (10):**
Portfolio Value, Portfolio Cost, Portfolio Gain, Portfolio Gain FX, Unrealized P&L, Simple Gain %, Unrealized Gain %, TWR %, TWR FX %, Total Dividends.

**Per-Account Sensors (10 per account):**
Mirror global sensors scoped to a specific account ID: Value, Net Worth, Cost, Gain, Unrealized P&L, Simple Gain %, Unrealized Gain %, TWR %, Total Dividends, Cash Balance.

**Per-Holding Sensors (1 per asset):**
State = total market value in base currency. Rich `extra_state_attributes` include prices, gains, dividends, limits, trend, currency info, asset class, and 24h change data.

**Watchlist Sensors (1 per watchlist item):**
State = current market price. Attributes include 24h change, 50d/200d trend, and limit state.

**Fundamentals Sensors (1 per symbol):**
State = ticker symbol. Key metrics (`lynch_peg_ratio`, `valuation`, `forward_pe`, etc.) are individual recorded attributes. The full raw Yahoo payload is stored under the single `detailed_stats` dict attribute, which is marked with `_unrecorded_attributes = frozenset({"detailed_stats"})` to prevent recorder bloat. Requires "Show Fundamentals" to be enabled.

**Translation keys:** All 20 static global and account sensors use `_attr_translation_key` instead of `_attr_name`. Account sensors additionally set `_attr_translation_placeholders = {"account_name": ...}` in `__init__`. Keys are defined in `strings.json` and all three language files. Per-holding, watchlist, and fundamentals sensors retain `_attr_name` because their names are dynamically derived from ticker symbols.

**Shared helpers on `GhostfolioBaseSensor`:**
- `_holdings_healthy(holdings)` — validates a list of holdings; used by both `is_portfolio_healthy` and `is_account_healthy`
- `native_unit_of_measurement` — base property that short-circuits to `_attr_native_unit_of_measurement` when set (percent sensors), otherwise derives the portfolio base currency dynamically

**Shared module-level helpers:**
- `_get_forward_pe(data)` — GBp-aware forward P/E lookup, used by both `_calculate_lynch_peg` and `extra_state_attributes`
- `LimitAlertMixin` — shared price-alert machinery for holding and watchlist sensors

All sensor types are added dynamically via a `_update_sensors()` coordinator listener registered in `async_setup_entry`. The listener is guarded with `if not coordinator.data: return` and tracks `known_ids` to avoid creating duplicate entities.

---

### Binary Sensors (`binary_sensor.py`)

- **GhostfolioServerSensor** — `CONNECTIVITY` device class, reads `coordinator.data["server_online"]`
- **GhostfolioUSMarketSensor** — no device class (market open/closed has no HA equivalent), reads `coordinator.us_market_open`
- **GhostfolioProviderSensor** — one per data provider in `DATA_PROVIDERS`, reads `coordinator.data["providers"]`

---

### Number Entities (`number.py`)

`GhostfolioLimitNumber` extends `CoordinatorEntity` + `RestoreNumber`. Creates two entities per holding and per watchlist item: Low Limit and High Limit.

- Value of `0` is treated as "no limit" (`_attr_native_value = None`) since HA number inputs cannot be empty.
- Watchlist **high limit** entities are **disabled by default** (`_attr_entity_registry_enabled_default = False`).
- On value change, immediately calls `_async_trigger_sensor_update()` to push the new limit into the associated holding/watchlist sensor's attributes.
- On HA restart, restored values are written to the state machine via `async_write_ha_state()` before triggering the sensor update.
- Entities are added dynamically via `_update_numbers()` coordinator listener.

---

### Button Entities (`button.py`)

- **GhostfolioPruneButton** — calls `coordinator.async_prune_orphans()` to clean up stale entities.
- **GhostfolioClearWatchlistLimitsButton** (high / low) — iterates the entity registry for watchlist limit entities of the given type and calls `registry.async_update_entity(..., disabled_by=RegistryEntryDisabler.USER)` on each enabled one.

---

### Switch (`switch.py`)

**GhostfolioPauseSyncSwitch** — calls `coordinator.async_set_sync_paused(True/False)`. Do not set `coordinator.sync_paused` directly; always go through `async_set_sync_paused` to ensure the timer is cancelled/restarted and the state is persisted.

---

### Diagnostics (`diagnostics.py`)

Implements `async_get_config_entry_diagnostics`. HA auto-discovers this file and adds a **Download Diagnostics** button to the integration card. The report includes config (access token redacted), coordinator state, data shape summary, and entity counts. No monetary values or holding details are included.

---

### Config Flow (`config_flow.py`)

Supports initial setup (`async_step_user`) and reconfiguration (`async_step_reconfigure`). Both steps share `_build_schema()` and `_async_validate_connection()` module-level helpers to avoid duplication. The temporary `GhostfolioAPI` instance created during validation is always closed in a `finally` block.

**Configuration options:**
- `portfolio_name` — friendly label for the integration instance
- `base_url` — Ghostfolio instance URL (validated to start with `http://` or `https://`)
- `access_token` — Ghostfolio anonymous access token (password-masked)
- `show_totals` — create global portfolio sensors
- `show_accounts` — create per-account sensors
- `show_holdings` — create per-holding sensors and limit numbers
- `show_watchlist` — create watchlist sensors and limit numbers
- `show_fundamentals` — create fundamentals sensors (daily Yahoo Finance pull)
- `verify_ssl` — SSL certificate verification (disable for self-signed or Zscaler proxies)
- `update_interval` — polling interval in minutes (1–1440, default 15)

---

### Constants (`const.py`)

All magic values live here. When adding features, add new constants rather than hardcoding values in logic files:

- `YAHOO_USER_AGENT` — shared User-Agent string for all Yahoo Finance requests
- `YAHOO_SESSION_URL`, `YAHOO_CRUMB_URL`, `YAHOO_QUOTE_URL`, `YAHOO_QUOTE_SUMMARY_URL` — Yahoo API base URLs
- `YAHOO_REQUEST_DELAY` — seconds between sequential Yahoo requests (rate limiting)
- `YAHOO_MARKET_PROXY` — ticker used to determine US market open state (`"SPY"`)
- `PRICE_LIMIT_MAX` — maximum value for price limit number entities
- `DATA_PROVIDERS` — list of provider codes to health-check
- `DEFAULT_UPDATE_INTERVAL` — default coordinator poll interval in minutes
- `API_TIMEOUT`, `API_MAX_RETRIES` — Ghostfolio API client configuration
- `EVENT_LIMIT_ALERT` — HA event name fired when a price limit is crossed
- `WATCHLIST_SCOPE` — sentinel account ID for watchlist-scoped limit entities
- `LYNCH_PEG_UNDERVALUED`, `LYNCH_PEG_OVERPRICED` — Lynch PEG ratio thresholds
- `SERVICE_REFRESH_FUNDAMENTALS`, `SERVICE_FETCH_24H_CHANGE`, `SERVICE_FETCH_PREMARKET` — service name strings
- `portfolio_device_info(config_entry)` — helper function returning the shared portfolio `DeviceInfo` dict; used by all platform files to avoid duplication

---

## Development Guidelines

### Code Style

- Follow Python PEP 8 style guidelines
- Use type hints for all function parameters and return values
- Use `%`-style formatting for all logger calls (not f-strings) — HA convention for deferred string formatting
- Move all magic numbers and strings to `const.py`
- Use async/await for all I/O operations

### Adding New Sensors

1. Add sensor class in `sensor.py` extending `GhostfolioBaseSensor` or `GhostfolioAccountBaseSensor`
2. Use `_attr_translation_key` (not `_attr_name`) for the entity name; for dynamic names with account/ticker placeholders, also set `self._attr_translation_placeholders` in `__init__`
3. Add the translation key to `strings.json` and all three language files
4. Register the entity in the appropriate setup block or `_update_sensors()` listener

### Adding New Config Options

1. Add a constant in `const.py`
2. Add the selector to `async_step_user` and `async_step_reconfigure` schemas in `config_flow.py`
3. Add labels and descriptions to `strings.json` and all three translation files

### Adding New API Endpoints

1. Add a method to `GhostfolioAPI` in `api.py` using `_make_authenticated_request()`
2. Call it from the coordinator's `_async_update_data()` and store results in the `data` dict

### Translation Updates

1. Update `strings.json` (source of truth) with the new key
2. Add translations to `translations/en.json`, `de.json`, and `fr.json` — all three must be kept in sync
3. Follow the existing nested structure: `config.step`, `config.error`, `entity.<platform>.<key>`

---

## Automated Tests

The `tests/` directory contains a basic pytest suite using [`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component).

### Install test dependencies

```bash
pip install -r requirements_test.txt
```

### Run the tests

```bash
pytest
```

### Test coverage

| File | What it tests |
|---|---|
| `test_config_flow.py` | User step success, cannot_connect, auth_failed, invalid_url, duplicate abort |
| `test_coordinator.py` | Successful data update, `UpdateFailed` on API error, sync-paused caching |
| `test_init.py` | Setup/unload lifecycle, one entity per platform (sensor, binary_sensor, button, switch), state assertion for Portfolio Value and Server sensors |

All tests use a fully mocked `GhostfolioAPI` — no live Ghostfolio or Yahoo Finance connection is required.

---

## Debugging

### Enable Debug Logging

Add to your Home Assistant `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.ghostfolio: debug
```

### Common Issues

1. **Authentication Errors**: Check access token and Ghostfolio URL format (must start with `http://` or `https://`)
2. **SSL Errors**: Disable SSL verification in integration options for self-signed certs or corporate proxies
3. **Missing Sensors**: Check if the relevant "Show …" option is enabled; check HA logs for coordinator errors
4. **Stale Entities**: Use the "Prune Orphaned Entities" button on the portfolio device page
5. **Pause Sync Not Working**: Always toggle via the switch entity — direct attribute mutation bypasses timer cancellation and persistence

---

## Testing Checklist

Before submitting changes:

- [ ] `pytest` passes with no errors
- [ ] Test with multiple portfolio configurations (multiple accounts, holdings, watchlist items)
- [ ] Verify all sensor types update correctly (global, account, holding, watchlist, fundamentals)
- [ ] Test configuration flow — initial setup and reconfigure
- [ ] Test reconfigure preserving existing entity unique IDs
- [ ] Check all translations are present in EN, DE, and FR (all four files must have identical key sets)
- [ ] Test SSL verification on and off
- [ ] Verify error handling for network issues — entities should become **unavailable** (not show stale data) when Ghostfolio is unreachable
- [ ] Test with invalid credentials
- [ ] Test Pause Sync — verify no API calls while paused and state survives HA restart
- [ ] Test Prune Orphaned Entities button after removing a holding or watchlist item in Ghostfolio
- [ ] Test Disable Watchlist High/Low Limits buttons
- [ ] Verify new watchlist items added in Ghostfolio appear in HA on next poll with high limit disabled by default
- [ ] Test pre-market / 24h change / fundamentals manual service calls — with and without `config_entry_id`
- [ ] Verify coordinator gracefully handles a data provider being down (sensor shows Unknown, not zero)
- [ ] Download Diagnostics — confirm access token is redacted in the output

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes following the development guidelines above
4. Test thoroughly using the testing checklist
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Useful Resources

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
- [Home Assistant Custom Integration Tutorial](https://developers.home-assistant.io/docs/creating_integration_manifest)
- [Home Assistant DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data)
- [Ghostfolio API Documentation](https://github.com/ghostfolio/ghostfolio)
- [aiohttp Documentation](https://docs.aiohttp.org/)
