# Dynamic Watchlist Dashboard Documentation

Using data provided by the integration it is possible to visualize the watchlist entities in a miningfull table where you can filter/sort and search for items:

<a href="https://github.com/user-attachments/assets/cbbd469a-b310-4bab-ad70-4be81bc35897" target="_blank">
  <img width="600" alt="image" src="https://github.com/user-attachments/assets/cbbd469a-b310-4bab-ad70-4be81bc35897" />
</a>


and a detailed dashboard for selected entities:

<a href="https://github.com/user-attachments/assets/e812f2c6-d260-4dfc-804e-59e4f3777104" target="_blank">
  <img width="600" alt="image" src="https://github.com/user-attachments/assets/e812f2c6-d260-4dfc-804e-59e4f3777104" />
</a>


The setup of those require some work and below I have documented it as best as I can remember, so if I have missed a step please forgive me. This setup requires good knowledge of Home Assistant. If you do get lost - figure it out - do not ask me for help.

This document outlines the complete architecture and configuration for the Home Assistant Dynamic Watchlist Dashboard. 

## Architecture Overview
This dashboard uses a decoupled architecture to bypass Home Assistant's 255-character state limit and keep the UI snappy:
1. **The Selector (Memory):** An `input_text` and `select` entity work together to hold the chosen ticker.
2. **The Data Bridge:** A master Template Sensor listens to the selector and pulls together slow daily fundamentals and live pricing into its attributes.
3. **The Frontend:** Lovelace cards (Mushroom, Markdown, and Config-Template) dynamically render based solely on the Data Bridge.

### Prerequisites (HACS)
Ensure the following custom frontend repositories are installed via HACS:
* `mushroom`
* `config-template-card`
* `mini-graph-card`
* `collapsable-cards`

---

## Phase 1: Backend Configuration

Place these definitions in your `configuration.yaml` (or use GUI) (or split them into your preferred packages/includes).

### 1. The Memory Helper
This `input_text` acts as the stable database to store your current selection.

```yaml
input_text:
  watchlist_selected_ticker:
    name: Watchlist Selected Ticker
    max: 100
```
<a href="https://github.com/user-attachments/assets/dbe8f624-ff73-438a-bd0c-dd59cea2cf94" target="_blank">
  <img width="600" alt="image" src="https://github.com/user-attachments/assets/dbe8f624-ff73-438a-bd0c-dd59cea2cf94" />
</a>


### 2. The Template Select & Data Bridge
This YAML handles the dropdown options, data aggregation, and conditional UI logic.

```yaml
template:
  # 1. THE DYNAMIC DROPDOWN
  - select:
      - name: "Watchlist Ticker Selector"
        unique_id: watchlist_ticker_selector
        # Read state from our memory helper
        state: >
          {{ states('input_text.watchlist_selected_ticker') if states('input_text.watchlist_selected_ticker') not in ['unknown', '', 'unavailable'] else 'AAPL' }}
        # Dynamically build options from watchlist sensors ONLY
        options: >
          {% set ns = namespace(tickers=[]) %}
          {% for state in states.sensor 
            if state.entity_id.startswith('sensor.watchlist_') 
            and not (state.entity_id.startswith('sensor.isa_') or 
                     state.entity_id.startswith('sensor.junior_isa_') or 
                     state.entity_id.startswith('sensor.freetrade_')) %}
            {% set ticker = state.attributes.get('ticker') %}
            {% if ticker and ticker not in ns.tickers %}
              {% set ns.tickers = ns.tickers + [ticker] %}
            {% endif %}
          {% endfor %}
          {{ ns.tickers | sort | list }}
        # Save selection back to the memory helper
        select_option:
          - action: input_text.set_value
            target:
              entity_id: input_text.watchlist_selected_ticker
            data:
              value: "{{ option }}"

  # 2. THE DATA BRIDGE SENSOR
  - sensor:
      - name: "Watchlist Selected Fundamental Data"
        unique_id: watchlist_selected_fundamental_data
        state: "{{ states('select.watchlist_ticker_selector') }}"
        attributes:
          # Pull the slow, daily fundamentals (converted to lower and dots to underscores)
          all_data: >
            {% set ticker = states('select.watchlist_ticker_selector') | lower | replace('.', '_') %}
            {% set entity_id = 'sensor.fundamentals_' ~ ticker ~ '_fundamentals' %}
            {{ states[entity_id].attributes if states[entity_id] is not none else {} }}
            
          # Scan for the fast, 1-minute live data & entity_id for graphing
          live_data: >
            {% set target_ticker = states('select.watchlist_ticker_selector') %}
            {% set ns = namespace(found=false, data={}) %}
            
            {% for state in states.sensor 
               if state.entity_id.startswith('sensor.watchlist_') 
               and not (state.entity_id.startswith('sensor.isa_') or 
                        state.entity_id.startswith('sensor.junior_isa_') or 
                        state.entity_id.startswith('sensor.freetrade_')) %}
               
              {% if state.attributes.get('ticker') == target_ticker and not ns.found %}
                {% set ns.found = true %}
                {% set raw_name = state.attributes.get('friendly_name', target_ticker) %}
                {% set clean_name = raw_name | replace('Watchlist ', '') %}
                
                {% set ns.data = {
                  'market_price': state.attributes.get('market_price'),
                  'change_24h': state.attributes.get('market_change_24h'),
                  'change_pct_24h': state.attributes.get('market_change_pct_24h'),
                  'currency': state.attributes.get('market_price_currency', state.attributes.get('currency_asset')),
                  'clean_name': clean_name,
                  'entity_id': state.entity_id
                } %}
              {% endif %}
            {% endfor %}
            {{ ns.data }}

  # 3. ASSET TYPE HELPER (Used for UI conditionals)
  - sensor:
      - name: "Watchlist Asset Type"
        unique_id: watchlist_asset_type
        state: >
          {% set data = state_attr('sensor.watchlist_selected_fundamental_data', 'all_data') or {} %}
          {% if data.get('legalType') == 'Exchange Traded Fund' or 'ETF' in data.get('friendly_name', '') or (data.get('totalAssets') and not data.get('marketCap')) %}
            fund
          {% elif data.get('marketCap') %}
            equity
          {% else %}
            unknown
          {% endif %}
```

Some of the sensors can be setup using GUI some are only available via the configuration.yaml
Once the above is done you should see this in your helpers:
<a href="https://github.com/user-attachments/assets/65341729-6b54-49f0-a6b2-4a43b5f81086" target="_blank">
  <img width="600" alt="image" src="https://github.com/user-attachments/assets/65341729-6b54-49f0-a6b2-4a43b5f81086" />
</a>

<a href="https://github.com/user-attachments/assets/b8130fb5-7290-4646-b51d-b78199e7cf15" target="_blank">
  <img width="600" alt="image" src="https://github.com/user-attachments/assets/b8130fb5-7290-4646-b51d-b78199e7cf15" />
</a>


---

## Phase 2: Lovelace Dashboard Configuration

This is the complete YAML for the UI:

Watchlist Dashboard - it is a single card panel (so it displays on the whole page)

[Watchlist Dashboard](asset/watchlist_card.yaml)

And this is the Watchlist Details setup as copied from the Home Assistant Raw Configuration Editor:

[Watchlist Details Dashboard](assets/watchlist_details.yaml)

