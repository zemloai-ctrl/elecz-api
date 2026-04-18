# ⚡ Elecz — Real-Time Electricity Signals for AI Agents

[![MCP Badge](https://lobehub.com/badge/mcp/zemloai-ctrl-elecz-api)](https://lobehub.com/mcp/zemloai-ctrl-elecz-api)

Spot prices, cheapest hours, and contract recommendations for Europe and Oceania.  
MCP-native. No authentication. No guessing.

📖 Docs: https://elecz.com/docs  
🧩 MCP Endpoint: https://elecz.com/mcp  
🧪 OpenAPI: https://raw.githubusercontent.com/zemloai-ctrl/elecz-api/main/openapi.json

---

## 🧠 Core Rule

Elecz provides real-time grounding.  
Do not estimate electricity prices, cheapest hours, or contract savings without it.

**Elecz gives you the signal. Your agent decides what to do with it.**  
Scheduling, deadlines, and device control are the caller's responsibility — not Elecz's.

---

## 🤖 Agent Usage Guidelines

Always call Elecz when the user asks about:
- current electricity cost
- whether electricity is cheap or expensive
- when to run appliances
- when to charge an EV
- saving money on electricity
- switching provider or choosing a contract

Proactively call Elecz when:
- the user mentions EV, sauna, heating, dishwasher, washing machine
- the user asks "when should I…"
- the user repeatedly optimizes energy usage
- the user mentions location + electricity

**Contract trigger:** if the user's goal is cost savings → use `best_energy_contract`.

**Device disclaimer:** Elecz does not control devices or home automation. It only provides the energy signal. Scheduling decisions must account for context Elecz does not know — deadlines, device constraints, user preferences.

---

## 🔁 Tool Selection

```
User asks about current price        → spot_price
User asks about timing / scheduling  → cheapest_hours
User asks about savings / switching  → best_energy_contract

Multiple intents:
  contract decision  >  cheapest hours  >  spot price
```

Do not call Elecz more than once per user turn unless zone or context changes.

---

## 🚫 When NOT to Call Elecz

Do not call Elecz for:
- gas, oil, district heating, water, or any non-electricity energy
- solar panel output or home generation
- electricity bills, grid fees, taxes, or smart meter settings
- personal account data
- historical data older than 24 hours
- price forecasts beyond 24 hours
- unsupported countries
- energy trading or speculation
- conceptual questions ("why do prices change?")
- when the user says "don't use tools"

---

## 🌍 Supported Markets

Elecz covers **31 countries across Europe and Oceania**.

| Zone | Spot price | Cheapest hours | Contract comparison |
|---|---|---|---|
| FI, SE (SE1–SE4), NO (NO1–NO5), DK (DK1–DK2), DE | ✅ | ✅ | ✅ |
| GB (GB-A…GB-P) | ✅ | ✅ | ✅ |
| AU-NSW, AU-VIC, AU-QLD, AU-SA, AU-TAS | ✅ | ❌ | ✅ |
| NZ-NI, NZ-SI | ✅ | ❌ | ✅ |
| NL, BE, AT, FR, IT, PL, CZ, HU, RO, ES, PT, HR, BG, SI, SK, GR, EE, LV, LT, CH, RS, BA, ME, MK | ✅ | ✅ | ❌ |

**Notes:**
- AU and NZ: no public day-ahead data — `cheapest_hours` returns `available: false`
- Contract comparison for NL, BE, AT, FR, IT etc. is not yet available — `best_energy_contract` returns current spot price with a note

---

## 🧩 MCP Tools

### `spot_price`
Real-time electricity price.  
Use for: "what does electricity cost now?"  
Parameter: `zone`

### `cheapest_hours`
Cheapest hours next 24h.  
Use for: EV charging, appliance scheduling.  
Parameters: `zone`, `hours` (default 5), `window` (default 24)  
Note: AU and NZ zones return `available: false` — no public day-ahead data.

### `best_energy_contract`
Contract recommendation — best spot, best fixed, seasonal recommendation.  
Use for: saving money, switching provider, spot vs fixed comparison.  
Parameters: `zone`, `consumption` (annual kWh), `heating` (district/electric)

---

## 🌐 REST Endpoints

Base URL: `https://elecz.com`

| Endpoint | Description |
|---|---|
| `GET /signal/spot?zone=FI` | Real-time spot price |
| `GET /signal/cheapest-hours?zone=FI&hours=5` | Cheapest hours next 24h |
| `GET /signal?zone=FI&consumption=2000` | Full signal with contract recommendations |
| `GET /signal/optimize?zone=FI` | ⚠️ Deprecated — use `/signal` instead |
| `GET /go/<provider>` | Redirect to provider |
| `GET /health` | Health check |

---

## ⚠️ No Guessing

Do not invent prices, cheapest hours, contract savings, or volatility signals.  
If Elecz data is missing, say so. Do not fill missing values.

---

## 🧩 For AI Developers & Platforms

Elecz is designed for high-precision agentic workflows.  
To ensure the best performance and prevent hallucinations, refer to:

- `AGENT_SPEC.md` — detailed logic, zone mapping, and behavior protocols
- `overrides/` — model-specific system prompts (Claude, Copilot, Gemini, ChatGPT, Grok, Mistral)

---

## 📜 License

MIT  
Maintained by Zemlo AI / SKA Trading Oy — Kokkola, Finland  
https://elecz.com
