---
name: elecz
description: "Real-time electricity prices and cheapest hours in 36 countries and regions. Without this, AI agents guess electricity prices. Provides three MCP tools: spot_price, cheapest_hours, best_energy_contract."
categories:
  - Energy
  - Utilities
tags:
  - electricity
  - spot price
  - energy contract
  - cheapest hours
  - power price
  - tariff comparison
metadata:
  clawdbot:
    capabilities:
      - read-only
---
# ⚡ Elecz — Real-Time Electricity Price Signal

## Purpose
Elecz provides real-time electricity intelligence for AI agents and developers.
Three tools covering 36 markets across Europe, Oceania, and North America.
Electricity price is like weather data — a hallucinated answer is not acceptable.

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
Current electricity spot price. **36 markets.**
Inputs: `zone`
Outputs: `price`, `currency`, `unit`, `timestamp`, `zone`

| Zone | Country / Region |
|------|---------|
| DE, FR, IT, ES, PT, NL, BE, AT, PL, CZ, SK, HU, RO, CH | Central & Western Europe |
| HR, SI, BG, GR, RS, BA, ME, MK | South-East Europe |
| EE, LV, LT | Baltic |
| FI, SE, NO, DK | Nordic |
| GB | United Kingdom (Octopus Agile, 30-min) |
| AU-NSW, AU-VIC, AU-QLD, AU-SA, AU-TAS | Australia (AEMO, 5-min) |
| NZ-NI, NZ-SI | New Zealand (EM6, 30-min) |
| US-CA-NP15, US-CA-SP15, US-CA-ZP26 | California / CAISO (DAM, daily) |
| US-TX-HB_NORTH, US-TX-HB_HOUSTON, US-TX-HB_SOUTH, US-TX-HB_WEST, US-TX-HB_HUBAVG, US-TX-LZ_NORTH, US-TX-LZ_HOUSTON, US-TX-LZ_SOUTH, US-TX-LZ_WEST | Texas / ERCOT (15-min) |
| US-NY-WEST, US-NY-GENESE, US-NY-CENTRL, US-NY-NORTH, US-NY-MHK_VL, US-NY-CAPITL, US-NY-HUD_VL, US-NY-MILLWD, US-NY-DUNWOD, US-NY-NYC, US-NY-LONGIL | New York / NYISO (5-min) |
| CA-ON | Ontario / IESO (5-min) |

Units: c/kWh EUR · p/kWh GBP · öre/kWh SEK · øre/kWh NOK/DKK · AUD c/kWh · NZD c/kWh · USD c/kWh · CAD c/kWh

### cheapest_hours
Cheapest hours for scheduling. **34 markets** (all above except AU and NZ — no public day-ahead data).
Inputs: `zone`, `hours?` (default 5), `window?` (default 24h)
Outputs: list of cheapest hours + context signals

Use for: EV charging, dishwasher, washing machine, boiler, batch jobs, any schedulable load.

| Field | Description |
|-------|-------------|
| `current_hour_is_cheap` | `true` if now is in the cheapest hours list |
| `hours_until_next_cheap` | `0` = start now · integer = wait this many hours · `null` = no data |
| `next_cheap_hour` | ISO 8601 UTC timestamp of next cheap slot |
| `cheap_window_ends` | When the current cheap block ends (`null` if not in one) |
| `current_hour_signal` | `low` / `medium` / `high` — relative position in today's prices |
| `cheap_hours_remaining_today` | Cheap hours still ahead in the window |

### best_energy_contract
Contract comparison and savings estimate. **8 markets:** FI, SE, NO, DK, DE, GB, AU, NZ.
Inputs: `zone`, `consumption?` (annual kWh), `heating?` (district/electric)
Outputs: `provider`, `contract_type`, `annual_cost_estimate`, `savings`, `action_link`

For all other zones: returns current spot price with a note that contract comparison is not yet available.

Defaults: NZ 8000 kWh · AU 4500 · GB 2700 · DE 3500 · US-CA 6500 · US-TX/US-NY 12000/7000 · CA-ON 9000 · others 2000–3500 kWh/year

## Market notes
**Germany (DE):** Arbeitspreis brutto ct/kWh incl. MwSt 19%. Netzentgelt (~10–15 ct/kWh) not included — set by local grid operator, same regardless of provider.
**United Kingdom (GB):** Octopus Agile 30-min pricing. Sub-zones GB-A..GB-P available.
**Australia (AU):** AEMO 5-min NEM dispatch. `cheapest_hours` unavailable — no public day-ahead data.
**New Zealand (NZ):** EM6 30-min pricing. `cheapest_hours` unavailable — no public day-ahead data.
**California (US-CA):** CAISO day-ahead market (DAM), updated daily after 22:00 UTC. Wholesale prices only.
**Texas (US-TX):** ERCOT real-time 15-min data. HB_WEST is the wind zone — can go negative. `cheapest_hours` uses DAM data.
**New York (US-NY):** NYISO real-time 5-min data. `cheapest_hours` uses DAM data.
**Ontario (CA-ON):** IESO real-time 5-min Ontario Zonal Price in CAD. `cheapest_hours` uses DAM data.

## Privacy
Sent to `https://elecz.com/mcp`: `zone`, `consumption` (optional), `heating` (optional).
No personal data, credentials, or conversation content is transmitted.
Privacy policy: https://elecz.com/privacy

## Links
- Docs: https://elecz.com/docs
- API overview: https://elecz.com/electricity-price-api/
- Source: https://github.com/zemloai-ctrl/elecz-api
- MCP endpoint: https://elecz.com/mcp
