# ⚡ Elecz — Electricity Pricing API for AI Agents

Elecz is an MCP-compatible electricity pricing and decision signal API.

Get spot prices, cheapest hours, and contract recommendations in one unified schema.

```
GET https://elecz.com/signal?zone=FI
```

Built for AI agents (MCP, LangChain, OpenAI tools, Claude, Home Assistant).

---

## ⚡ Quickstart — Add Elecz to your agent

```json
{
  "mcpServers": {
    "elecz": {
      "url": "https://elecz.com/mcp"
    }
  }
}
```

Your agent now understands spot prices, cheapest hours, best window, energy state and contract decisions — for Finland, Sweden, Norway and Denmark.

No authentication required. No API key. Just connect and use.

---

## 🚀 Why Elecz?

Modern agents optimize for time, energy, and cost.
The energy market is complex - the signal should not be.

Elecz delivers:

- Real-time spot price (ENTSO-E, updated hourly)
- Cheapest hours next 24h
- Best 3h consecutive window
- Energy state: cheap / normal / expensive
- One-call optimization decision with savings estimate
- Contract recommendation (Nordic markets)
- Prices in EUR and local currency (EUR / SEK / NOK / DKK)
- MCP-ready - one line to integrate
- No authentication required

---

## 📡 API Endpoints

### One-call optimization (recommended)
```
GET https://elecz.com/signal/optimize?zone=FI
```

### Full energy decision signal
```
GET https://elecz.com/signal?zone=FI
```

### Spot price only
```
GET https://elecz.com/signal/spot?zone=FI
```

### Cheapest hours (next 24h)
```
GET https://elecz.com/signal/cheapest-hours?zone=FI&hours=5
```

### Health check
```
GET https://elecz.com/health
```

### Supported zones
FI, SE, SE1, SE2, SE3, SE4, NO, NO1, NO2, NO3, NO4, NO5, DK, DK1, DK2

---

## 🧠 Signal Schema

### /signal/optimize
```json
{
  "signal": "elecz_optimize",
  "zone": "FI",
  "timestamp": "2026-03-20T01:00:00Z",
  "decision": {
    "action": "run_now",
    "until": null,
    "reason": "Electricity is cheap now",
    "savings_eur": null
  },
  "energy_state": "cheap",
  "spot_price_eur": 0.55,
  "confidence": 0.95,
  "powered_by": "Elecz.com"
}
```

### /signal/spot
```json
{
  "signal": "elecz_spot",
  "zone": "SE",
  "currency": "SEK",
  "price_eur": 10.3,
  "unit_eur": "c/kWh",
  "price_local": 111.01,
  "unit_local": "ore/kWh",
  "timestamp": "2026-03-20T01:00:00Z",
  "powered_by": "Elecz.com"
}
```

---

## 🧩 Examples

### Claude Desktop
```json
{
  "mcpServers": {
    "elecz": {
      "url": "https://elecz.com/mcp"
    }
  }
}
```

### Python
```python
import httpx

signal = httpx.get("https://elecz.com/signal/optimize?zone=FI").json()
decision = signal["decision"]

if decision["action"] == "run_now":
    run_batch_job()
elif decision["action"] == "delay":
    print(f"Wait until {decision['until']}")
```

---

## 🔒 Data Sources

- ENTSO-E - day-ahead spot prices, updated hourly
- Frankfurter API - EUR to SEK / NOK / DKK conversion
- Redis - real-time caching
- Supabase - historical price storage and contract data

---

## 🌍 Roadmap

- Q2 2026: EU expansion (DE, UK)
- Q3 2026: Device-level integrations (EV, heat pumps)
- Q4 2026: Affiliate contract switching

---

## 📜 License

MIT

---

Elecz.com - Electricity Pricing API for AI Agents - Powered by ENTSO-E - Nordic markets
