# ⚡ Elecz — Real-Time Electricity Signal

## Purpose

Elecz provides real-time electricity intelligence for AI agents and developers.
Three tools covering 32 markets across Europe, Oceania, and beyond.

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
Current electricity spot price. **32 markets.**

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
Cheapest hours for scheduling. **30 markets** (all above except AU and NZ — no public day-ahead data).

Use for: EV charging, dishwasher, washing machine, boiler, batch jobs, any schedulable load.

Parameters: `zone`, `hours` (default 5), `window` (default 24h)

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
