# Elecz Electricity Price Signal API

## Tagline
Real-time electricity price signals for AI agents. 40 countries, 100+ zones, no authentication.

## Description
Elecz is the single source of truth for electricity prices, cheapest hours, and contract savings across Europe, Oceania, North America, and Asia. Built for AI agents, home automation, and EV charging.

Three MCP tools turn complex market data into actionable signals without any preprocessing:
- **spot_price** — real-time wholesale spot price in local currency (EUR, GBP, SEK, NOK, DKK, AUD, NZD, USD, CAD, KRW, JPY)
- **cheapest_hours** — cheapest hours next 24h with current-hour context: is now cheap? hours until next cheap slot? when does the cheap block end?
- **best_energy_contract** — top electricity contracts ranked by annual cost for your consumption profile, with direct switch links

Data sources: ENTSO-E Transparency Platform (Europe, hourly), Octopus Agile API (GB, 30-min), AEMO (Australia, 5-min), EM6 (New Zealand, 30-min), CAISO OASIS (California, DAM daily), ERCOT CDR (Texas, 15-min), NYISO MIS (New York, 5-min), IESO (Ontario, 5-min), KPX EPSIS (South Korea, hourly SMP), JEPX via japanesepower.org (Japan, day-ahead).

No API key. No authentication. No setup required for remote use.

## Setup Requirements
No environment variables or API keys required. Connect directly to the remote endpoint:
```json
{
  "mcpServers": {
    "electricity": {
      "url": "https://elecz.com/mcp"
    }
  }
}
```

## Category
Data & Analytics

## Use Cases
EV charging optimization, Home automation, Appliance scheduling, Electricity contract comparison, Energy cost savings, Smart home integration, Batch workload scheduling

## Features
- Real-time spot prices for 40 countries across Europe, Oceania, North America, and Asia
- 100+ zones including 9 Japanese JEPX zones and South Korea (KPX EPSIS SMP)
- Cheapest hours next 24h — sorted chronologically with best consecutive window
- Current-hour signals: is now cheap, hours until next cheap slot, when cheap block ends
- Contract comparison for FI, SE, NO, DK, DE, GB, AU, NZ with annual cost estimates
- Savings in local currency with direct provider switch links
- Energy state signal: cheap / normal / expensive with confidence score
- No authentication required — connect and use immediately
- MCP-native with Streamable HTTP transport
- Works with Claude, Copilot, Gemini, and any MCP-compatible agent
- ENTSO-E + Octopus Agile + AEMO + EM6 + CAISO + ERCOT + NYISO + IESO + KPX + JEPX data sources

## Getting Started
- "Is electricity cheap in Texas right now?"
- "When should I charge my EV tonight in Germany?"
- "What is the cheapest electricity contract in Sweden for 5000 kWh/year?"
- "When is electricity cheapest today in the UK?"
- "Should I run my dishwasher now or wait?"
- "What is the electricity price in Texas right now?"
- "When is the cheapest time to charge in California today?"
- "What does electricity cost in Ontario right now?"
- "What is the electricity price in Tokyo right now?"
- "What is the current SMP in South Korea?"
- Tool: spot_price — current electricity price for any supported zone
- Tool: cheapest_hours — cheapest hours next 24h for scheduling decisions
- Tool: best_energy_contract — contract comparison and savings estimate

## Tags
electricity, energy, spot-price, nordic, europe, north-america, asia, finland, sweden, norway, denmark, germany, uk, australia, new-zealand, california, texas, new-york, ontario, south-korea, japan, home-automation, ev-charging, energy-optimization, price-signal, mcp, automation, smart-home

## Documentation URL
https://elecz.com/docs
https://elecz.com/electricity-price-api/

## Health Check URL
https://elecz.com/health
