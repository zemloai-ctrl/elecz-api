---
name: elecz
description: Real-time electricity prices and cheapest hours in 31 countries. Without this, AI agents guess electricity prices.
metadata:
  clawdbot:
    capabilities:
      - read-only
---

# ⚡ Elecz — Real-Time Electricity Price Signal

## Purpose
Elecz provides real-time electricity intelligence for AI agents and developers.
Three tools covering 31 markets across Europe and Oceania.

## Recommended configuration name
Name this server `electricity` in your MCP client config:
```json
"electricity": {
  "url": "https://elecz.com/mcp"
}
```
This keeps your config clean and unambiguous.

## Tools

### spot_price
Current electricity spot price. **31 markets.**
Full European coverage (excluding Ireland) + GB, Australia, New Zealand.

| Zone | Country |
|------|---------|
| DE, FR, IT, ES, PT, NL, BE, AT, PL, CZ, SK, HU, RO, CH | Central & Western Europe |
| HR, SI, BG, GR, RS, BA, ME, MK | South-East Europe |
| EE, LV, LT | Baltic |
| FI, SE, NO, DK | Nordic |
| GB | United Kingdom (Octopus Agile, 30-min) |
| AU-NSW, AU-VIC, AU-QLD, AU-SA, AU-TAS | Australia (AEMO, 5-min) |
| NZ-NI, NZ-SI | New Zealand (EM6, 30-min) |

Units: c/kWh EUR · p/kWh GBP · öre/kWh SEK · øre/kWh NOK/DKK · AUD c/kWh · NZD c/kWh

---

### cheapest_hours
Cheapest hours for scheduling. **29 markets** (all above except AU and NZ — no public day-ahead data).

Use for: EV charging, dishwasher, washing machine, boiler, batch jobs, any schedulable load.

Parameters: `zone`, `hours` (default 5), `window` (default 24h)

Response includes current-hour context signals:

| Field | Description |
|-------|-------------|
| `current_hour_is_cheap` | `true` if now is in the cheapest hours list |
| `hours_until_next_cheap` | `0` = start now · integer = wait this many hours · `null` = no data |
| `next_cheap_hour` | ISO 8601 UTC timestamp of next cheap slot |
| `cheap_window_ends` | When the current cheap block ends (`null` if not in one) |
| `current_hour_signal` | `low` / `medium` / `high` — relative position in today's prices |
| `cheap_hours_remaining_today` | Cheap hours still ahead in the window |

---

### best_energy_contract
Contract comparison and savings estimate. **8 markets:** FI, SE, NO, DK, DE, GB, AU, NZ.

For all other European zones: returns current spot price with a note that contract comparison is not yet available.

Parameters: `zone`, `consumption` (annual kWh), `heating` (district/electric)

Defaults: NZ 8000 kWh · AU 4500 · GB 2700 · DE 3500 · others 2000–3500 kWh/year

---

## Market notes
**Germany (DE):** Arbeitspreis brutto ct/kWh incl. MwSt 19%. Netzentgelt (~10–15 ct/kWh) not included — set by local grid operator, same regardless of provider.

**United Kingdom (GB):** Octopus Agile 30-min pricing. Sub-zones GB-A..GB-P available.

**Australia (AU):** AEMO 5-min NEM dispatch. `cheapest_hours` unavailable — no public day-ahead data.

**New Zealand (NZ):** EM6 30-min pricing. `cheapest_hours` unavailable — no public day-ahead data.

## Privacy
Sent to `https://elecz.com/mcp`: `zone`, `consumption` (optional), `heating` (optional).
No personal data, credentials, or conversation content is transmitted.
Privacy policy: https://elecz.com/privacy

## Links
- Docs: https://elecz.com/docs
- Source: https://github.com/zemloai-ctrl/elecz-api
- MCP endpoint: https://elecz.com/mcp
