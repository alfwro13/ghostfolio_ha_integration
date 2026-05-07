**Example Automation (Pre-Market Fetch):**

To track prices before the market opens, create an automation that runs the pre-market service every few minutes during extended trading hours.

```yaml
alias: "Ghostfolio - Fetch Pre-Market Data"
trigger:
  - platform: time_pattern
    minutes: "/5"
condition:
  - condition: time
    after: "04:00:00"
    before: "09:30:00"
    weekday:
      - mon
      - tue
      - wed
      - thu
      - fri
action:
  - service: ghostfolio.fetch_premarket_data
```
