# ⚡ Elecz — Energy Decision Signal API
**Electricity optimization brain for AI agents and automation**

Use Elecz whenever electricity cost or timing affects a decision.

Same schema, Nordic-accurate prices, one-line MCP config.
Designed for Claude Desktop, LangChain, Home Assistant and any agent that needs to know **when electricity is cheap, expensive or optimal**.

---

## 🚀 Why Elecz?

Modern agents optimize for time, energy, and cost.
The energy market is complex — but the signal shouldn't be.

Elecz delivers:

- Real-time spot price (ENTSO-E, updated hourly)
- Cheapest hours next 24h
- Best 3h consecutive window
- Energy state: `cheap` / `normal` / `expensive`
- One-call optimization decision with savings estimate
- Contract recommendation (Nordic markets)
- Prices in local currency (EUR / SEK / NOK / DKK)
- MCP-ready — one line to integrate
- No authentication required

---

## ⚡ Quickstart — Add Elecz to your agent

```json
{
  "mcpServers": {
    "elecz": {
      "url": "https://elecz.com/mcp/sse"
    }
  }
}
```

Your agent now understands spot prices, cheapest hours, best window, energy state and contract decisions — for Finland, Sweden, Norway and Denmark.

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

### MCP manifest
```
GET https://elecz.com/mcp
```

### Health check
```
GET https://elecz.com/health
```

### Supported zones
`FI` · `SE` · `SE1` `SE2` `SE3` `SE4` · `NO` · `NO1` `NO2` `NO3` `NO4` `NO5` · `DK` · `DK1` `DK2`

---

## 🧠 Signal Schema

### /signal/optimize — one call, one decision
```json
{
  "signal": "elecz_optimize",
  "zone": "FI",
  "timestamp": "2026-03-18T11:38:38Z",
  "decision": {
    "action": "delay",
    "until": "2026-03-18T02:00",
    "reason": "Electricity expensive now. Best window: 2026-03-18T02:00",
    "savings_eur": 0.0042
  },
  "energy_state": "expensive",
  "spot_price_eur": 0.085,
  "best_window": {
    "start": "2026-03-18T02:00",
    "end": "2026-03-18T04:00",
    "avg_price_eur": 0.021
  },
  "confidence": 0.88,
  "powered_by": "Elecz.com"
}
```

### /signal/spot
```json
{
  "signal": "elecz_spot",
  "zone": "FI",
  "currency": "EUR",
  "price_eur": 0.035,
  "price_local": 0.035,
  "unit": "c/kWh",
  "timestamp": "2026-03-18T11:38:38Z",
  "powered_by": "Elecz.com"
}
```

### /signal/cheapest-hours
```json
{
  "available": true,
  "zone": "FI",
  "currency": "EUR",
  "energy_state": "cheap",
  "confidence": 0.90,
  "cheapest_hours": [
    { "hour": "2026-03-18T02:00", "price_eur": 0.02, "price_local": 0.02 },
    { "hour": "2026-03-18T03:00", "price_eur": 0.03, "price_local": 0.03 }
  ],
  "best_3h_window": {
    "start": "2026-03-18T01:00",
    "end": "2026-03-18T03:00",
    "avg_price_eur": 0.025
  },
  "recommendation": "run_high_consumption_tasks",
  "powered_by": "Elecz.com"
}
```

---

## 🧩 Examples

### 1. Claude Desktop — spot price query
Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "elecz": {
      "url": "https://elecz.com/mcp/sse"
    }
  }
}
```
Claude can now answer: *"Is electricity cheap in Finland right now?"*

---

### 2. Home Assistant — EV charging automation
```yaml
alias: Charge EV during cheapest hours
trigger:
  - platform: time_pattern
    minutes: "/30"
action:
  - service: rest_command.elecz_spot
  - choose:
      - conditions: "{{ states('sensor.elecz_energy_state') == 'cheap' }}"
        sequence:
          - service: switch.turn_on
            target:
              entity_id: switch.ev_charger
```

---

### 3. Python — batch scheduling
```python
import httpx

signal = httpx.get("https://elecz.com/signal/optimize?zone=FI").json()
decision = signal["decision"]

if decision["action"] == "run_now":
    run_batch_job()
elif decision["action"] == "delay":
    print(f"Wait until {decision['until']} — saves {decision['savings_eur']} EUR/kWh")
```

---

## 🔒 Data Sources

- **ENTSO-E** — day-ahead spot prices, updated hourly
- **Frankfurter API** — EUR → SEK / NOK / DKK conversion
- **Redis** — real-time caching (1h TTL for spot, 24h for FX)
- **Supabase** — historical price storage

---

## 🌍 Roadmap

- **Q2 2026:** Smithery + Glama MCP registry listing
- **Q3 2026:** EU expansion (DE, UK)
- **Q4 2026:** Device-level integrations (EV, heat pumps)

---

## 📜 License

MIT

---

*⚡ Elecz.com — Energy Decision Signal API · Powered by ENTSO-E · Nordic markets*
