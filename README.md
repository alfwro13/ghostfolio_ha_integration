<div align="center">
   <img src="https://brands.home-assistant.io/ghostfolio/icon.png" alt="Ghostfolio Logo" width="120" height="120">
</div>

# Ghostfolio Home Assistant Integration

A Home Assistant Custom Component (HACS integration) for monitoring your [Ghostfolio](https://github.com/ghostfolio/ghostfolio) portfolio performance.

## Features

This integration automatically detects your portfolio's base currency and allows you to toggle exactly which sensors you want to see via the configuration options.

### 1. Global Portfolio Sensors
- **Portfolio Value**: The current total market value of your portfolio.
- **Portfolio Cost**: The total amount of money you have invested.
- **Portfolio Gain**: The absolute net performance (Value - Cost).
- **Portfolio Gain FX**: The absolute net performance including currency effects.
- **Simple Gain %**: The simple percentage return, calculated as `(Value - Cost) / Cost`.
- **Time-Weighted Return %**: The Time-Weighted Rate of Return (TWR) of your portfolio (measures strategy performance, ignoring deposits/withdrawals).
- **Time-Weighted Return FX %**: The TWR percentage including currency effects.

### 2. Per-Account Sensors
Sensors are created for each of your Ghostfolio accounts (excluding hidden ones):
- **[Account Name] Value**: Current market value of the specific account.
- **[Account Name] Cost**: Total investment in the specific account.
- **[Account Name] Gain**: Absolute gain/loss for the specific account.
- **[Account Name] Simple Gain %**: Simple percentage gain/loss for the specific account.
- **[Account Name] Time-Weighted Return %**: Time-Weighted Return percentage for the specific account.

### 3. Per-Holding Sensors (Assets)
Track every individual asset in your portfolio with a dedicated sensor:
- **Sensor State**: Total market value of the holding in your base currency.
**Attributes:**

| Attribute | Description |
| --- | --- |
| `ticker` | The symbol of the asset (e.g., `AAPL`, `VWRL.AS`). |
| `account` | The name of the account holding this asset (e.g., `ISA`, `Trading`). |
| `asset_class` | The class of the asset (e.g., `EQUITY`, `CRYPTOCURRENCY`). |
| `number_of_shares` | Total quantity of shares held. |
| `currency_asset` | The native currency of the asset (e.g., `USD` for Apple). |
| `currency_base` | Your portfolio's base currency (e.g., `GBP`). |
| `market_price` | Current price of one share in the **asset's** currency. |
| `market_price_currency` | The currency code for the market price (e.g., `USD`). |
| `market_price_in_base_currency` | Current price of one share converted to your **base** currency. |
| `average_buy_price` | Average buy price per share in your **base** currency. |
| `average_buy_price_currency` | The currency code for the average buy price (e.g., `GBP`). |
| `gain_value` | Total monetary gain/loss in your **base** currency. |
| `gain_value_currency` | The currency code for the gain value (e.g., `GBP`). |
| `gain_pct` | Total percentage gain/loss (`Simple Gain`). |
| `trend_vs_buy` | Indicator (`up`, `down`, or `break_even`) comparing current price vs. average buy price. |

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
   - **Base URL**: The URL of your Ghostfolio instance (e.g., `https://your-ghostfolio.com`).
   - **Access Token**: Your Ghostfolio access token.
   - **Show Portfolio Totals**: (Optional) Check to create global portfolio sensors.
   - **Show Individual Accounts**: (Optional) Check to create sensors for each account.
   - **Show Holdings**: (Optional) Check to create sensors for individual assets.

### Getting Your Access Token

1. Log in to your Ghostfolio instance.
2. Go to **Settings > Security**.
3. Scroll to **Security Token**.
4. Generate or copy your access token (Anonymous Access).

## API Endpoints Used

This integration uses the following Ghostfolio API endpoints:

- `POST /api/v1/auth/anonymous`: For authentication.
- `GET /api/v1/account`: For retrieving the account list and base currency settings.
- `GET /api/v2/portfolio/performance`: For retrieving global and per-account performance data.
- `GET /api/v1/portfolio/holdings`: For retrieving individual asset details.

## Data Update Frequency

The integration updates portfolio data every **15 minutes** by default. This can be customized in the configuration options.

## Support

For issues with this integration, please open an issue on the GitHub repository.

For issues with Ghostfolio itself, please refer to the [Ghostfolio GitHub repository](https://github.com/ghostfolio/ghostfolio).

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments
This integration is maintained by @alfwro13.
Originally based on the [ha_ghostfolio repository by MichelFR](https://github.com/MichelFR/ha_ghostfolio). It has since been significantly expanded to include granular per-holding tracking, per-account sensors, dynamic configuration options, and improved currency handling.
