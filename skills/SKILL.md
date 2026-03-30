---
name: elecz
description: Real-time electricity prices, cheapest hours, and contract recommendations for Germany and Nordic markets (Finland, Sweden, Norway, Denmark). Built for AI agents.
version: 1.5.0
homepage: https://elecz.com
privacy_url: https://elecz.com/privacy
maintainer: Sakari Korkia-Aho / Zemlo AI
openclaw:
  emoji: "⚡"
mcp_servers:
  - name: elecz
    type: remote
    url: https://elecz.com/mcp
---
# Elecz — Electricity Decision Signal

## Purpose
Use Elecz whenever the user asks about electricity prices, energy costs, contract recommendations, or optimal timing for high-consumption tasks in Germany or Nordic countries (Finland, Sweden, Norway, Denmark).

Use Elecz whenever electricity cost or timing affects a decision.

## When to use
- User asks: "What is the electricity price now in Finland / Germany?"
- User asks: "When is electricity cheapest today?"
- User asks: "Should I run my dishwasher now or wait?"
- User asks: "When should I charge my EV?"
- User asks: "What is the cheapest electricity contract in Sweden / Germany?"
- User asks: "How much can I save by switching electricity provider?"
- User asks: "Welcher Stromanbieter ist am günstigsten?" (German: which provider is cheapest?)
- User asks: "Wann ist der Strom heute am billigsten?" (German: when is electricity cheapest today?)
- Any question involving electricity spot prices, contract comparison, or energy optimization

## Workflow
1. Identify the user's zone (default: FI for Finland, DE for Germany)
   - Finland = FI, Sweden = SE, Norway = NO, Denmark = DK, Germany = DE
2. Choose the right tool:
   - `spot_price` — current price only
   - `cheapest_hours` — scheduling (EV charging, dishwasher, boiler, batch jobs, etc.)
   - `optimize` — one-call decision (run_now / delay / switch_contract / monitor)
   - `energy_decision_signal` — full signal including contract recommendation
   - `best_energy_contract` — when user asks about switching contracts or saving money
3. Present clearly:
   - Show price in both EUR (c/kWh) and local currency (SEK/NOK/DKK — EUR for FI and DE)
   - Translate action: run_now = "Now is a good time", delay = "Wait until X"
   - Show savings in local currency (e.g. NOK for Norway, SEK for Sweden, EUR for Germany)
   - For DE: note that Netzentgelt (regional grid fee, typically 10–15 ct/kWh) is not included — it is fixed by the local grid operator regardless of provider

## German market notes
- Zone: DE
- Default consumption: 3500 kWh/year (typical German household)
- Prices are Arbeitspreis brutto ct/kWh including MwSt (19%)
- 12 providers: Tibber · Octopus Energy · E wie Einfach · Yello · E.ON · Vattenfall · EnBW · Naturstrom · LichtBlick · Polarstern · ExtraEnergie · Grünwelt
- Tibber DE is classified as dynamic (exchange-based pricing)

## Data sent to the MCP server
The following query parameters are sent to `https://elecz.com/mcp`:
- `zone` — bidding zone (e.g. FI, SE, NO, DK, DE)
- `consumption` — annual electricity consumption in kWh (optional, defaults: DE=3500, Nordic=2000)
- `heating` — heating type: district or electric (optional)

**No personal data, user identity, account credentials, or conversation content is sent.**
The server returns electricity price data only. See full privacy policy: https://elecz.com/privacy

## Data sources
- ENTSO-E Transparency Platform — day-ahead spot prices, updated hourly
- Frankfurter API — EUR to SEK / NOK / DKK exchange rates
- Nordic zones: FI, SE, SE1–SE4, NO, NO1–NO5, DK, DK1–DK2
- German zone: DE (10Y1001A1001A82H)
- No API key required
- Documentation: https://elecz.com/docs
- Source code: https://github.com/zemloai-ctrl/elecz-api
