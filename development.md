# Development Guide

This document provides guidance for developers who want to contribute to or modify the Ghostfolio Home Assistant integration.

## Prerequisites

- Python 3.11 or higher
- Home Assistant Core 2023.1 or higher
- A running Ghostfolio instance for testing
- Git for version control

## Development Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd ghostfolio
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
custom_components/ghostfolio/
├── __init__.py          # Integration initialization and setup
├── api.py              # Ghostfolio API client
├── config_flow.py      # Configuration flow for setup/reconfigure
├── const.py            # Constants and configuration keys
├── manifest.json       # Integration metadata
└── sensor.py           # Sensor entities (6 sensors total)

translations/
├── de.json             # German translations
├── en.json             # English translations
├── fr.json             # French translations
└── strings.json        # Base translation strings
```

## Key Components

### API Client (`api.py`)

* Handles authentication with Ghostfolio (`/api/v1/auth/anonymous`)

* **`get_portfolio_performance`**: Fetches total or per-account performance

* **`get_accounts`**: Fetches list of accounts and base currency settings

* **`get_holdings`**: Fetches individual asset data per account

### Sensors (`sensor.py`)

The integration now creates three distinct types of sensors, controlled by configuration options:

**1. Global Portfolio Sensors**

* **Portfolio Value**: Current total market value

* **Portfolio Cost**: Total investment amount

* **Portfolio Gain**: Absolute net performance

* **Portfolio Gain FX**: Absolute net performance with currency effects

* **Simple Gain %**: Money-weighted return proxy `(Value - Cost) / Cost`

* **Time-Weighted Return %**: Strategy performance (Ghostfolio standard)

* **Time-Weighted Return FX %**: Strategy performance with currency effects

**2. Per-Account Sensors**
Dynamically created for each account (e.g., "ISA", "Trading"):

* **Value**: Current market value

* **Cost**: Total investment

* **Gain**: Absolute gain/loss

* **Simple Gain %**: Percentage gain/loss

* **Time-Weighted Return %**: Account-specific strategy performance

**3. Per-Holding Sensors**
One sensor created for every asset in your portfolio:

* **State**: Total market value in base currency

* **Attributes**: `current_price`, `average_buy_price`, `number_of_shares`, `gain_value`, `gain_pct`, `trend_vs_buy`

### Configuration Flow (`config_flow.py`)

* **Show Portfolio Totals**: Boolean toggle for global sensors

* **Show Individual Accounts**: Boolean toggle for account sensors

* **Show Holdings**: Boolean toggle for individual asset sensors

* Supports re-configuration of these options without reinstalling

## Development Guidelines

### Code Style

- Follow Python PEP 8 style guidelines
- Use type hints for all function parameters and return values
- Add docstrings to all classes and methods
- Use async/await patterns for all I/O operations

### Testing

1. **Manual Testing**: Use Home Assistant's developer tools to test sensor updates
2. **Integration Testing**: Test with real Ghostfolio instances
3. **Error Handling**: Test with invalid credentials, network issues, etc.

### Adding New Features

1. **New Sensors**: Add sensor classes in `sensor.py` following the existing pattern
2. **Configuration Options**: Add new constants in `const.py` and update `config_flow.py`
3. **API Endpoints**: Extend the `GhostfolioAPI` class in `api.py`

### Translation Updates

1. Update `translations/strings.json` with new keys
2. Add translations to `en.json`, `de.json`, and `fr.json`
3. Follow the existing translation key structure

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

1. **Authentication Errors**: Check access token and Ghostfolio URL
2. **SSL Errors**: Verify SSL certificate or disable SSL verification
3. **Sensor Updates**: Check update intervals and API rate limits

## Testing Checklist

Before submitting changes:

- [ ] Test with multiple portfolio configurations
- [ ] Verify all sensors update correctly
- [ ] Test configuration flow (setup and reconfigure)
- [ ] Check translations in all supported languages
- [ ] Test SSL verification on/off
- [ ] Verify error handling for network issues
- [ ] Test with invalid credentials

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes following the development guidelines
4. Test thoroughly using the testing checklist
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Useful Resources

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
- [Home Assistant Custom Integration Tutorial](https://developers.home-assistant.io/docs/creating_integration_manifest)
- [Ghostfolio API Documentation](https://github.com/ghostfolio/ghostfolio)
- [aiohttp Documentation](https://docs.aiohttp.org/)

## Support

For development questions or issues:

1. Check existing GitHub issues
2. Review Home Assistant logs with debug logging enabled
3. Test with a minimal configuration to isolate issues
4. Create a detailed issue report with logs and configuration details
