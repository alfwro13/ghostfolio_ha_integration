# AGENTS.md — Ghostfolio Home Assistant Integration

This file guides AI coding agents working in this repository. Read it before making any changes.

---

## What This Repository Is

A Home Assistant custom integration (HACS-compatible) that connects HA to a self-hosted [Ghostfolio](https://github.com/ghostfolio/ghostfolio) portfolio tracker. It polls the Ghostfolio API and also calls Yahoo Finance directly for pre-market prices, previous close data, and fundamental metrics.

The full feature description is in [README.md](README.md). Architecture details are in [development.md](development.md).

---

## Project Layout

```
custom_components/ghostfolio/
├── __init__.py        # Coordinator, services, setup/unload lifecycle
├── api.py             # Ghostfolio API client
├── binary_sensor.py   # Server, US Market, Data Provider sensors
├── button.py          # Prune button + disable watchlist limit buttons
├── config_flow.py     # Setup and reconfigure UI flows
├── const.py           # ALL constants live here
├── manifest.json      # Integration metadata and version
├── number.py          # Price limit number entities (High/Low per asset)
├── sensor.py          # All sensor entities
├── services.yaml      # Custom service definitions
├── strings.json       # Translation source of truth
├── switch.py          # Pause Sync switch
└── translations/
    ├── de.json
    ├── en.json
    └── fr.json
```

---

## Rules — Always Follow These

### Constants
- **All magic values belong in `const.py`** — URLs, delays, numeric limits, string literals used in logic. Never hardcode them inline.
- Yahoo Finance URLs and the User-Agent string are already in `const.py`. Import them; do not duplicate them.

### Logging
- **Use `%`-style formatting** for all `_LOGGER` calls — never f-strings.
  ```python
  # correct
  _LOGGER.debug("Failed to fetch %s: %s", symbol, err)
  # wrong
  _LOGGER.debug(f"Failed to fetch {symbol}: {err}")
  ```

### Translations
- **All four files must stay in sync**: `strings.json`, `translations/en.json`, `translations/de.json`, `translations/fr.json`.
- `strings.json` is the source of truth — add keys there first, then mirror to all three language files.
- Never add a key to only some files.
- German translations go in `de.json`, French in `fr.json`. Provide reasonable translations; do not leave keys untranslated.

### Coordinator Data Access
- **Always guard listener callbacks** against `coordinator.data` being `None`:
  ```python
  @callback
  def _update_sensors():
      if not coordinator.data:
          return
      ...
  ```
- **Use `.get()` with defaults** — never bare `dict["key"]` on API response data. The API shape can change.
  ```python
  # correct
  account_id = account.get("id")
  if not account_id:
      continue
  # wrong
  account_id = account["id"]
  ```

### Pause Sync
- **Never set `coordinator.sync_paused` directly.** Always use `await coordinator.async_set_sync_paused(True/False)`. This method handles timer cancellation, state persistence, and immediate refresh on resume.

### Entity Unique IDs
- **Never change the unique_id format of an existing entity type.** Changing a unique_id orphans the entity for all existing users, breaking their automations and history. If a rename is unavoidable, document it as a breaking change.

### Session Lifecycle
- The `GhostfolioAPI` object owns a single `aiohttp.ClientSession`. It is closed in `async_unload_entry` via `await entry.runtime_data.api.close()`. Do not create additional sessions; do not call `close()` elsewhere.

### Service Registration
- Services are registered in `async_setup_entry` behind a `has_service` guard and deregistered in `async_unload_entry` when the last config entry is removed. Do not register services outside this pattern.

### Disabled-by-Default Entities
- Set `_attr_entity_registry_enabled_default = False` in `__init__` for entities that should start disabled. This only affects first registration — HA remembers user preference thereafter.

---

## Rules — Never Do These

- **Do not use f-strings in logger calls** (see Logging above).
- **Do not hardcode Yahoo Finance URLs, the User-Agent string, or numeric limits** — use constants from `const.py`.
- **Do not mutate `coordinator.sync_paused` directly** — use `async_set_sync_paused()`.
- **Do not change existing entity unique_id formats.**
- **Do not add `async_call_later` for timing workarounds** — call `async_write_ha_state()` first and then trigger updates directly.
- **Do not add translation keys to only some language files.**
- **Do not log full API response bodies at ERROR level** — truncate to 500 chars.
- **Do not catch `Exception` silently with `pass`** — at minimum log at debug level with the exception.
- **Do not skip the `coordinator.data` null guard** in coordinator listener callbacks.

---

## Key Architectural Decisions to Preserve

### GBp (British Pence) Handling
London-listed stocks quote in pence (GBp), not pounds (GBP). The integration divides marketPrice by 100 when `currency == "GBp"`. This logic exists in `sensor.py` and `__init__.py`. Do not remove it.

### Watchlist High Limits Disabled by Default
Watchlist high-limit number entities set `_attr_entity_registry_enabled_default = False`. This is intentional to reduce clutter. The "Disable Watchlist High/Low Limits" buttons let users bulk-disable them again after enabling.

### Yahoo Finance Crumb Auth
Yahoo Finance requires a session cookie + crumb token. `_get_yahoo_crumb()` establishes the session via `fc.yahoo.com` then fetches the crumb. The crumb is cached in-memory for the coordinator's lifetime. All direct Yahoo calls must use this crumb.

### Zero as "No Limit" Sentinel
Number entities use `0` to mean "no limit set" because HA number inputs cannot be empty. `async_set_native_value(0)` sets `_attr_native_value = None`. Automations and sensors checking limit values must account for this (`if limit_val > 0`).

### Provider Health Gathering
`asyncio.gather()` for provider health checks uses `return_exceptions=True`. Results that are `Exception` instances are logged and skipped — they must not abort the coordinator update.

### Dynamic Entity Creation
Holding, watchlist, account, and fundamentals entities are created dynamically inside coordinator listener callbacks (`_update_sensors`, `_update_numbers`). A `known_ids` set prevents duplicate creation. New entity types should follow this same pattern.

---

## Adding a New Feature — Checklist

- [ ] New constants in `const.py`
- [ ] Logic in the appropriate platform file (`sensor.py`, `binary_sensor.py`, etc.)
- [ ] Translation key added to `strings.json` AND `en.json`, `de.json`, `fr.json`
- [ ] If a new config option: add to both `async_step_user` and `async_step_reconfigure` in `config_flow.py`
- [ ] If a new entity: unique_id follows the pattern `ghostfolio_{type}_{qualifier}_{entry_id}`
- [ ] If a new service: register behind `has_service` guard and deregister in `async_unload_entry`
- [ ] `README.md` updated to document the new feature
- [ ] `development.md` updated if architecture changes

---

## Testing Changes

There are no automated unit tests in this repository. 

---

## Files Not to Touch

- `hacs.json` — HACS metadata, only change for category/filename updates
- `.github/workflows/` — CI pipelines, only change if adding a new workflow
- `custom_components/ghostfolio/manifest.json` - if changes are necessary inform the operator
- `LICENSE` — do not modify
