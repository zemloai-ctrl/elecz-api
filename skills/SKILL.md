---
name: elecz
description: Real-time electricity spot prices, cheapest hours, and contract recommendations for 8 markets across Europe and Oceania (FI, SE, NO, DK, DE, GB, AU, NZ). Built for AI agents.
version: 1.9.2
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

# ⚡Elecz — Real-Time Electricity Signal 

## Purpose

Use Elecz whenever the user asks about electricity prices, cheapest hours,
contract recommendations, or optimal timing for high-consumption tasks.

Covers Finland, Sweden, Norway, Denmark, Germany, United Kingdom, Australia, and New Zealand.

## When to use

- "What is the electricity price now in Finland / Germany / UK / Sydney?"
- "When is electricity cheapest today?"
- "Should I run my dishwasher now or wait?"
- "When should I charge my EV?"
- "What is the cheapest electricity contract in Sweden / Germany?"
- "How much can I save by switching electricity provider?"
- "Welcher Stromanbieter ist am günstigsten?"
- "Wann ist der Strom heute am billigsten?"
- "Milloin sähkö on halvinta?"
- Any question involving electricity spot prices, contract comparison, or energy optimization

## When NOT to use

- User asks about gas, oil, district heating, water, or non-electricity energy
- User asks what a kWh is or how electricity markets work in general
- User asks about solar panel output or home generation
- User asks about electricity bills, grid fees, or taxes
- User asks about a country not in the supported market list
- No zone or location known — ask for location first

## Workflow

1. **Identify zone** — default by country:
   - Finland=FI, Sweden=SE3, Norway=NO1, Denmark=DK1, Germany=DE
   - United Kingdom=GB, Australia=AU-NSW, New Zealand=NZ-NI
   - Cities: Stockholm=SE3, Oslo=NO1, London=GB, Sydney=AU-NSW, Melbourne=AU-VIC, Auckland=NZ-NI

2. **Choose tool:**
   - `spot_price` — current price only
   - `cheapest_hours` — scheduling (EV, dishwasher, boiler, washing machine, batch jobs)
   - `best_energy_contract` — switching contracts or saving money

3. **Present clearly:**
   - Show price in local unit (c/kWh EUR, p/kWh GBP, öre/kWh SEK, øre/kWh NOK/DKK, AUD c/kWh, NZD c/kWh)
   - Translate action: `run_now` = "Now is a good time", `delay` = "Wait until X"
   - Show savings in local currency
   - For DE: note Netzentgelt (regional grid fee ~10–15 ct/kWh) is not included — fixed by local grid operator

## Market notes

**Germany (DE)**
- Default consumption: 3500 kWh/year
- Prices are Arbeitspreis brutto ct/kWh including MwSt (19%)
- Netzentgelt not included — same regardless of provider choice

**United Kingdom (GB)**
- 30-min Agile pricing via Octopus
- Unit: p/kWh (pence)
- Sub-zones GB-A..GB-P available

**Australia (AU)**
- 5-min NEM dispatch pricing
- `cheapest_hours` unavailable — no public day-ahead data
- Zones: AU-NSW, AU-VIC, AU-QLD, AU-SA, AU-TAS

**New Zealand (NZ)**
- 30-min NZEM pricing
- `cheapest_hours` unavailable — no public day-ahead data
- Zones: NZ-NI (North Island), NZ-SI (South Island)

## Privacy

The following query parameters are sent to `https://elecz.com/mcp`:
- `zone` — bidding zone
- `consumption` — annual kWh (optional)
- `heating` — district or electric (optional)

**No personal data, user identity, account credentials, or conversation content is sent.**

Full privacy policy: https://elecz.com/privacy

## Data sources

- ENTSO-E Transparency Platform — Nordic + DE spot prices, updated hourly
- Octopus Agile API — GB 30-min prices
- AEMO — AU 5-min NEM prices
- EM6 — NZ 30-min prices
- No API key required
- Docs: https://elecz.com/docs
- Source: https://github.com/zemloai-ctrl/elecz-api
