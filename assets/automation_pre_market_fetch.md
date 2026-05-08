# How to Set Up Ghostfolio Pre-Market Fetching with Worldclock

This guide explains how to accurately trigger the Ghostfolio Pre-Market data fetch using the official US Eastern Time (`America/New_York`). This ensures your polling works perfectly regardless of your local timezone or Daylight Saving Time (DST) changes.

---

## Step 1: Add the Worldclock Integration

Since the US market operates on Eastern Time, we need a sensor that tracks it perfectly. 

1. In Home Assistant, navigate to **Settings** > **Devices & Services**.
2. Click the **Add Integration** button in the bottom right corner.
3. Search for **Worldclock** and select it.
4. Set the **Timezone** to `America/New_York` and submit.
5. Home Assistant will create a new sensor. Note its exact entity ID (usually `sensor.worldclock_sensor`). Rename it if you wish to: `sensor.worldclock_sensor_new_york`

> **Note:** By default, this sensor outputs the time in a 24-hour format (e.g., `04:00`, `15:30`). The automation below relies on this standard `HH:MM` format.

---

## Step 2: Create the Polling Automation

This automation runs every 5 minutes but uses strict conditions so it only actually executes the Ghostfolio service when the market is closed **and** it is past 4:00 AM New York time. 

### How to add this:
1. Go to **Settings** > **Automations & Dashboards** > **Create Automation** > **Create new automation**.
2. Click the three dots in the top right corner and select **Edit in YAML**.
3. Paste the configuration below.
4. **Important:** Verify that `binary_sensor.ghostfolio_portfolio_us_market` matches the exact name of your US Market sensor, and verify your Worldclock entity ID.

```yaml
alias: "Ghostfolio - Fetch Pre-Market Data (NY Time)"
description: "Pulls pre-market data every 5 minutes starting at 4:00 AM NY Time while the market is closed."
mode: single

trigger:
  - platform: time_pattern
    minutes: "/5"

condition:
  # 1. Only run on weekdays
  - condition: time
    weekday:
      - mon
      - tue
      - wed
      - thu
      - fri
      
  # 2. Only run when the US Market is Closed
  - condition: state
    entity_id: binary_sensor.ghostfolio_portfolio_us_market
    state: "off"
    
  # 3. Only run if the New York time is 04:00 or later
  - condition: template
    value_template: >-
      {% set ny_time = states('sensor.worldclock_sensor_new_york') %}
      {{ '04:00' <= ny_time }}

action:
  - service: ghostfolio.fetch_premarket_data
