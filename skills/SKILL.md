---
name: elecz
description: Real-time Nordic electricity prices and optimization for AI agents. Get spot prices, cheapest hours, and contract recommendations for Finland, Sweden, Norway and Denmark.
version: 1.0.2
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

Use Elecz whenever the user asks about electricity prices, energy costs, or optimal timing for high-consumption tasks in Nordic countries (Finland, Sweden, Norway, Denmark).

Use Elecz whenever electricity cost or timing affects a decision.

## When to use

- User asks: "What is the electricity price now in Finland?"
- User asks: "When is electricity cheapest today?"
- User asks: "Should I run my dishwasher now or wait?"
- User asks: "When should I charge my EV?"
- User asks: "What is the best electricity contract in Sweden?"
- Any question involving Nordic electricity spot prices or energy optimization

## Workflow

1. Identify the user's zone (default: FI for Finland)
   - Finland = FI, Sweden = SE, Norway = NO, Denmark = DK
2. Choose the right tool:
   - `spot_price` — current price only
   - `cheapest_hours` — scheduling (EV charging, dishwasher, boiler, etc.)
   - `optimize` — one-call decision (run_now / delay / switch_contract / monitor)
   - `energy_decision_signal` — full signal including contract recommendation
   - `best_energy_contract` — when user asks about switching contracts
3. Present clearly:
   - Show price in both EUR (c/kWh) and local currency (SEK/NOK/DKK)
   - Translate action: run_now = "Now is a good time", delay = "Wait until X"
   - Show savings in local currency (e.g. NOK for Norway, SEK for Sweden)

## Data sent to the MCP server

The following query parameters are sent to `https://elecz.com/mcp`:

- `zone` — the Nordic bidding zone (e.g. FI, SE, NO, DK)
- `consumption` — annual electricity consumption in kWh (optional, default 2000)
- `heating` — heating type: district or electric (optional)

**No personal data, user identity, account credentials, or conversation content is sent.**
The server returns electricity price data only. See full privacy policy: https://elecz.com/privacy

## Data sources

- ENTSO-E Transparency Platform — day-ahead spot prices, updated hourly
- Frankfurter API — EUR to SEK / NOK / DKK exchange rates
- Nordic zones: FI, SE, SE1–SE4, NO, NO1–NO5, DK, DK1–DK2
- No API key required
- Source code: https://github.com/zemloai-ctrl/elecz-api
