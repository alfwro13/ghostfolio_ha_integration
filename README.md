<div align="center">
   <img src="https://brands.home-assistant.io/ghostfolio/icon.png" alt="Ghostfolio Logo" width="120" height="120">
</div>

![Total Downloads](https://img.shields.io/github/downloads/alfwro13/ghostfolio_ha_integration/total)
![Latest Release Downloads](https://img.shields.io/github/downloads/alfwro13/ghostfolio_ha_integration/latest/total)

# Ghostfolio Home Assistant Integration

A Home Assistant Custom Component (HACS integration) for monitoring your [Ghostfolio](https://github.com/ghostfolio/ghostfolio) portfolio performance. This integration works with any Ghostfolio instance, but if you prefer an all-in-one solution, you can run Ghostfolio directly on your server using the [Home Assistant Add-on](https://github.com/alfwro13/ha-addon-ghostfolio).

## Features

This integration automatically detects your portfolio's base currency and offers granular tracking options:
- **Global Totals:** Track overall portfolio value and performance.
- **Account Breakdowns:** Individual sensors for each investment account.
- **Asset Tracking:** Dedicated sensors for every holding and watchlist item.
- **Dividend Tracking:** Monitor total accumulated dividends at the global, account, and individual holding levels.
- **Fundamental Metrics:** Deep integration with Yahoo Finance to pull fundamental metrics (PEG, Margins, Valuation) for your assets.
- **Price Alerts:** Configurable High/Low limit numbers for every asset to trigger automations.
- **Diagnostic Sensors:** Monitor the connection status of your Ghostfolio server, data providers, and US market state.
- **Smart Health Checks:** Automatically detects if a data provider (e.g., Yahoo Finance) is down and marks affected sensors as `Unknown` instead of reporting erroneous zero values.
- **Entity Cleanup:** Built-in tool to remove old or sold assets from Home Assistant.

### 1. Global Portfolio Sensors
These sensors aggregate your entire Ghostfolio setup:

- **Portfolio Value**: Mapped directly to Ghostfolio's native `currentValueInBaseCurrency` for the global portfolio.
- **Portfolio Cost**: Mapped directly to Ghostfolio's native `totalInvestment`.
- **Portfolio Gain**: Mapped to Ghostfolio's native `netPerformance`. This is your absolute bottom-line gain, which correctly tracks Realized P&L when you sell stocks to cash.
- **Portfolio Gain FX**: Mapped to Ghostfolio's native `netPerformanceWithCurrencyEffect`.
- **Portfolio Unrealized P&L**: A custom integration calculation. It scans all your active holdings (ignoring Cash/Liquidity), subtracts their specific cost basis from their current live value, and sums the result. It represents exactly how much profit is currently floating in active stocks right now.
- **Simple Gain %**: Calculated as `(Portfolio Gain / Portfolio Cost) * 100`.
- **Unrealized Gain %**: Calculated as `(Portfolio Unrealized P&L / Cost of Active Stocks) * 100`.
- **Time-Weighted Return %**: Mapped to Ghostfolio's native `netPerformancePercentage`. Measures strategy performance, neutralizing the impact of your deposits and withdrawals.
- **Time-Weighted Return FX %**: Mapped to Ghostfolio's native `netPerformancePercentageWithCurrencyEffect`.
- **Portfolio Total Dividend**: Calculates the sum of all `DIVIDEND` transactions returned by the Ghostfolio `/api/v1/activities` endpoint across all accounts.

### 2. Per-Account Sensors
Sensors are created for each of your Ghostfolio accounts (excluding accounts marked as hidden). They mirror the Global sensors but strictly isolate data to the specific account ID:

- **[Account Name] Value**: Mapped to `currentValueInBaseCurrency` for the specific account.
- **[Account Name] Net Worth**: Mapped to `currentNetWorth` for the specific account.
- **[Account Name] Cost**: Mapped to `totalInvestment` for the specific account.
- **[Account Name] Gain**: Mapped to the native `netPerformance` for the specific account.
- **[Account Name] Unrealized P&L**: Custom calculation: `(Live Value of Active Equities in Account) - (Cost of Active Equities in Account)`.
- **[Account Name] Simple Gain %**: Calculated as `(Account Gain / Account Cost) * 100`.
- **[Account Name] Unrealized Gain %**: Calculated as `(Account Unrealized P&L / Account Active Equity Cost) * 100`.
- **[Account Name] Time-Weighted Return %**: Mapped to the native `netPerformancePercentage` for the specific account.
- **[Account Name] Total Dividends**: Sum of all `DIVIDEND` transactions linked to this specific account ID.
- **[Account Name] Cash Balance**: A dedicated sensor that extracts and sums any asset holding within the account where the `assetClass` is strictly defined as `LIQUIDITY` (e.g., your GBP, USD, or EUR uninvested cash).

### 3. Per-Holding Sensors (Assets)
Dedicated sensors are created for every individual asset in your portfolio. *(Note: Uninvested Cash / `LIQUIDITY` assets are intentionally filtered out of this list to prevent dashboard clutter and are instead routed to the Account Cash Balance sensors).*

- **Sensor State**: The total live market value of the holding in your base currency (`Quantity * Live Price`).
- **Friendly Name**: The ticker symbol (e.g., "AAPL", "VWRL.AS").
- **Attributes**:
  - `ticker`: The asset symbol.
  - `account`: The account this holding belongs to.
  - `number_of_shares`: Mapped to the holding's `quantity`.
  - `currency_asset`: The native currency of the asset (e.g., `USD`, `GBP`).
  - `currency_base`: Your portfolio base currency.
  - `market_price`: The live price fetched via Ghostfolio market-data or overridden by the integration's live Yahoo Finance pre-market fetch.
  - `market_price_currency`: The currency of the market price.
  - `market_price_in_base_currency`: Market price converted to your base currency.
  - `average_buy_price`: Calculated as `investment / quantity`, in base currency.
  - `average_buy_price_currency`: Currency of the average buy price.
  - `gain_value`: Calculated as `(Current Live Value) - (Total Investment Cost)`, in base currency.
  - `gain_value_currency`: Currency of the gain value.
  - `gain_pct`: Calculated as `(gain_value / Total Investment Cost) * 100`.
  - `trend_vs_buy`: Reports `up`, `down`, or `break_even` based on whether the current market price is higher or lower than your average buy price.
  - `accumulated_dividends`: Filters the global activities endpoint for `DIVIDEND` transactions specifically matching this ticker and account.
  - `accumulated_dividends_currency`: Currency of accumulated dividends.
  - `asset_class`: The asset class as reported by Ghostfolio (e.g., `EQUITY`, `CRYPTOCURRENCY`).
  - `data_source`: The data provider used for this holding (e.g., `YAHOO`).
  - `market_change_24h`: Absolute price change over the last 24 hours.
  - `market_change_pct_24h`: Percentage price change over the last 24 hours.
  - `low_limit_set` / `low_limit_reached`: Linked to the Number Entity limit helpers.
  - `high_limit_set` / `high_limit_reached`: Linked to the Number Entity limit helpers.

*Note: If the data provider for a specific holding is down, its sensor will report `Unknown`.*

### 4. Watchlist Sensors
Track items from your Ghostfolio Watchlist even if you don't own them yet.
- **Sensor State**: Current market price.
- **Friendly Name**: The ticker symbol (e.g., "TSLA").
- **Attributes**: 
  - `market_change_24h`, `market_change_pct_24h`
  - `trend_50d`, `trend_200d`
  - `low_limit_set`, `low_limit_reached`
  - `high_limit_set`, `high_limit_reached`
*(Requires "Show Watchlist Items" to be enabled in configuration)*

### 5. Fundamentals Sensors
Track detailed fundamental metrics for your holdings and watchlist items via Yahoo Finance. *(Requires "Show Fundamentals" to be enabled in configuration)*
- **Sensor State**: The ticker symbol.
- **Recorded attributes** (stored in history):
  - `valuation` (e.g., `undervalued`, `overpriced`, `fairly_valued`), `lynch_peg_ratio`
  - `standard_peg_ratio`, `forward_pe`, `dividend_yield`, `projected_1y_growth`
  - `ticker`, `data_pulled_at`
- **`detailed_stats`** (current state only, not recorded to reduce database size): a dict containing all raw Yahoo Finance fields from `defaultKeyStatistics`, `financialData`, and `summaryDetail`. Access individual fields in templates with `state_attr('sensor.TICKER_fundamentals', 'detailed_stats')['profitMargins']`.

### 6. Price Limit Configuration (Inputs)
For every Holding and Watchlist item, the integration creates two **Number** entities that allow you to set price targets directly from Home Assistant.

- **[Ticker] - Low Limit**
- **[Ticker] - High Limit**

> **Note:** Watchlist High Limit entities are **disabled by default** to reduce clutter. Enable them individually in the Home Assistant entity registry if needed. You can also use the **Disable Watchlist High/Low Limits** diagnostic buttons (see section 8) to bulk-disable them again at any time.

When you set a value in these number entities, the corresponding main Sensor (Holding or Watchlist) immediately updates its attributes:
- **`low_limit_set` / `high_limit_set`**: Displays the limit value you set (or `false` if not set).
- **`low_limit_reached`**: Becomes `true` if the value drops to or below your limit.
- **`high_limit_reached`**: Becomes `true` if the value rises to or above your limit.

### 7. Automations & Alerts (Recommended)
This integration features a built-in event system to handle price alerts efficiently. Instead of creating complex automations that watch every single sensor state, the integration fires a **single event** whenever a limit is crossed.

**Event Name:** `ghostfolio_limit_alert`

[**Limit Notification Example Automation**](assets/automation_limit_notification.md)

**Event Data Payload**: The event provides the following data variables you can use in your templates:
- ticker: The symbol (e.g., "AAPL")
- account: The account name or "Watchlist"
- limit_type: "low" or "high"
- limit_value: The threshold value that was set
- current_value: The price that triggered the alert
- currency: The currency code (e.g., "USD", "GBP")

### 8. Diagnostic Sensors & Tools
To help you troubleshoot issues and maintain your setup, the integration provides diagnostic entities. You can find these on the main Portfolio Device page in Home Assistant.

- **Ghostfolio Server**: Binary sensor indicating if your Ghostfolio instance is reachable (`Connected` / `Disconnected`).
- **US Market**: Binary sensor showing whether the US stock market is currently open or closed. Used internally to control pre-market data fetching.
- **Data Provider Status**: Individual binary sensors for each data provider (e.g., `Yahoo Status`, `Coingecko Status`) showing if they are `Available` or `Unavailable`.
- **Prune Orphaned Entities**: A button that scans your Home Assistant registry and removes any Ghostfolio entities (such as sold assets or removed watchlist items) that are no longer returned by the API.
- **Disable Watchlist High Limits**: A button that disables all currently-enabled watchlist high limit number entities in the entity registry in one click.
- **Disable Watchlist Low Limits**: A button that disables all currently-enabled watchlist low limit number entities in the entity registry in one click.
- **Pause Sync**: A switch that pauses all polling from Ghostfolio. When paused, the coordinator's update timer is cancelled and no API calls are made. The paused state is persisted across Home Assistant restarts. Toggle it back off to immediately resume syncing.
- **Download Diagnostics**: Available on the integration card in Settings → Integrations → Ghostfolio → three-dot menu. Downloads a JSON snapshot covering config (access token redacted), coordinator state, data shape, and entity counts — useful when reporting bugs.

### 9. Manual Services & Pre-Market Data

This integration exposes specific services to Home Assistant, allowing you to manually trigger data refreshes or fetch extended-hours market data.

* **`ghostfolio.fetch_premarket_data`**: Pulls live Pre-Market and Post-Market prices for US stocks (Yahoo Finance). It safely calculates the exact holding value in your base currency without breaking regular Ghostfolio updates.
* **`ghostfolio.fetch_24h_change`**: Pulls the official Previous Close to accurately calculate the 24-hour change percentage, bypassing timezone delays.
* **`ghostfolio.refresh_fundamentals`**: Forces an immediate refresh of deep fundamental metrics (PEG, Margins, etc.).

All three services accept an optional `config_entry_id` field. When provided, only that specific portfolio entry is refreshed. When omitted, all configured Ghostfolio portfolios are updated — useful for multi-portfolio setups.

```yaml
service: ghostfolio.refresh_fundamentals
data:
  config_entry_id: "abc123def456"   # optional — omit to refresh all portfolios
```

[**Example Automation (Pre-Market Fetch)**](assets/automation_pre_market_fetch.md)

### 10. Dashboards

[I documented my watchlist dashboard setup here](assets/watchlist_dashboard.md)

https://github.com/user-attachments/assets/ba93ac65-fa25-4707-ad33-7ff98fe4f38e

You can adopt that to your own needs as you see fit (see [Support & Disclaimer](#support--disclaimer))

You can modify that code and use the holding sensors created by this integration to create your own overview dashboard for your stocks (gains/losses etc), example:

<a href="https://github.com/user-attachments/assets/cbd636bd-176e-41c2-9526-9935f3bef1a2" target="_blank">
  <img width="600" alt="image" src="https://github.com/user-attachments/assets/cbd636bd-176e-41c2-9526-9935f3bef1a2" />
</a>

## Installation

### HACS (Recommended)

1. Make sure you have [HACS](https://hacs.xyz/) installed.
2. Add this repository as a custom repository in HACS:
   - Go to HACS → Integrations.
   - Click the three dots in the top right corner.
   - Select "Custom repositories".
   - Add this repository URL and select "Integration" as the category.
3. Install the integration from HACS.
4. Restart Home Assistant.

### Manual Installation

1. Download the latest release.
2. Copy the `custom_components/ghostfolio` folder to your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services**.
2. Click **Add Integration** and search for **"Ghostfolio"**.
3. Enter your details and choose which sensors to create:
   - **Portfolio Name**: A friendly name for this portfolio instance.
   - **Base URL**: The URL of your Ghostfolio instance (e.g., `https://your-ghostfolio.com`). Must start with `http://` or `https://`.
   - **Access Token**: Your Ghostfolio access token.
   - **Show Portfolio Totals**: (Optional) Create global portfolio sensors.
   - **Show Individual Accounts**: (Optional) Create sensors for each account.
   - **Show Holdings**: (Optional) Create sensors and limit numbers for individual assets.
   - **Show Watchlist Items**: (Optional) Create sensors and limit numbers for watchlist items.
   - **Show Fundamentals**: (Optional) Pull deep fundamental metrics from Yahoo Finance daily. Creates one sensor per tracked symbol.
   - **Verify SSL Certificate**: Disable if you use a corporate proxy (e.g., Zscaler) that intercepts SSL certificates.
   - **Update Interval**: How often to poll Ghostfolio for updates (in minutes, default: 15, range: 1–1440).


## API Endpoints Used

### Ghostfolio API
This integration uses the following Ghostfolio API endpoints:
- `POST /api/v1/auth/anonymous`: For authentication.
- `GET /api/v1/account`: For retrieving the account list and base currency settings.
- `GET /api/v2/portfolio/performance`: For retrieving global and per-account performance data.
- `GET /api/v1/portfolio/holdings`: For retrieving individual asset details.
- `GET /api/v1/watchlist`: For retrieving watchlist items.
- `GET /api/v1/activities`: For calculating dividends and transactions.
- `GET /api/v1/market-data`: For fetching real-time price and history for watchlist items.
- `GET /api/v1/health/data-provider/{provider}`: For checking the status of data providers.

### Yahoo Finance API (Direct)
To provide real-time updates and deep analysis, the integration communicates directly with Yahoo Finance endpoints:
- **Real-time & Pre-market Data**: Uses the `v7/finance/quote` endpoint to fetch live prices, pre-market/post-market values, and US market status.
- **Daily Fundamentals & Technicals**: Uses the `v10/finance/quoteSummary` endpoint to retrieve detailed metrics such as PEG ratios, profit margins, moving averages, and analyst recommendations.
- **Previous Close**: Fetches official "Previous Close" data via `quoteSummary` to accurately calculate 24h change percentages regardless of local timezone delays.

## Data Update Frequency

The integration updates portfolio data every **15 minutes** by default. This can be customized in the configuration options.

## Support & Disclaimer

**⚠️ Disclaimer: Use at Your Own Risk**

This custom integration is a personal project and is provided strictly "as is" and without warranty of any kind. By choosing to install and use this integration, you acknowledge and agree to the following:

* **Personal Project Disclosure:** I am not a professional developer, nor do I specialize in finance or stock markets. The sole purpose of this repository is to assist me with managing my personal portfolio and to visualize data in ways that exceed Ghostfolio's native capabilities.
* **Coding Bias & Market Focus:** I mainly trade on the UK and US stock markets. As a result, the code contains specific logic to address issues unique to London-traded stocks (such as the "Pence vs. Pounds" glitch). While the integration is designed to work with other markets, it has not been tested for them. There may be unhandled errors related to local currency conversions or data formatting in other regions.
* **No Support Provided:** The author does not provide technical support, setup assistance, or troubleshooting guidance. Please do not ask for help on how to configure Home Assistant, how to use the integration, or how to fix local environmental issues. 
* **Consult AI for Help:** If you run into issues, encounter errors, or need help creating automations for this integration, it is highly recommended to consult your preferred AI (such as ChatGPT, Claude, or Gemini). Paste your YAML, error logs, and what you are trying to achieve, and they can usually help you resolve it.
* **No Liability:** The author takes absolutely no responsibility for any damage, data loss, misuse, system instability, or any other issues caused by the installation or operation of this software.
* **Community Driven:** You are free to fork, modify, and use this integration however you see fit. If you encounter bugs, you are welcome to submit a Pull Request, but do not expect immediate fixes or dedicated maintenance.

For issues with Ghostfolio itself, please refer to the official [Ghostfolio GitHub repository](https://github.com/ghostfolio/ghostfolio).

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments
This integration is maintained by @alfwro13.
Originally based on the [ha_ghostfolio repository by MichelFR](https://github.com/MichelFR/ha_ghostfolio). It has since been significantly expanded to include granular per-holding tracking, per-account sensors, dynamic configuration options, diagnostic tools, and improved currency handling.
