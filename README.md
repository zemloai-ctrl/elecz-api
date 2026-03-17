# ⚡ Elecz — Energy Decision Signal API  
**Energy‑Awareness‑as‑a‑Service for AI agents**

Elecz provides a **unified energy signal** for AI agents:  
same schema, Nordic‑accurate prices, one‑line MCP config.

Designed for OpenClaw, LangChain, Claude Desktop, Copilot Extensions, Home Assistant automations and any agent that needs to know **when electricity is cheap, expensive or optimal**.

---

# 🚀 Why Elecz?

Modern agents optimize for time, energy, and cost.
The energy market is complex — but the signal shouldn't be.
Elecz delivers:

- Real‑time spot price  
- Cheapest hours (next 24h)  
- Best 3h window  
- Energy state (cheap / normal / expensive)  
- Contract recommendation (Nordic markets)  
- Unified JSON schema  
- MCP manifest for instant agent integration  
- No authentication required  

**If your agent can optimize energy in the Nordics, it can do it anywhere.**

---

# ⚡ Quickstart — Add Elecz to your agent

Copy‑paste this into your agent config:

```json
{
  "mcpServers": {
    "elecz": {
      "url": "https://elecz.com/mcp"
    }
  }
}
```

Your agent now understands:

- spot price  
- cheapest hours  
- best window  
- energy state  
- contract decisions  

---

# 📡 API Endpoints

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

### Redirect to provider
```
GET https://elecz.com/go/<provider>
```

### MCP manifest
```
GET https://elecz.com/mcp
```

---

# 🧠 Energy Signal Schema v0.1

All Elecz endpoints follow the same unified schema:

```json
{
  "signal": "elecz",
  "version": "1.1",
  "zone": "FI",
  "currency": "EUR",
  "timestamp": "2026-03-17T05:00:00Z",

  "energy_state": "cheap",
  "confidence": 0.92,

  "spot_price": {
    "eur": 3.2,
    "local": 3.2,
    "unit": "c/kWh"
  },

  "cheapest_hours": [
    { "hour": "2026-03-17T02:00", "price_eur": 2.1 },
    { "hour": "2026-03-17T03:00", "price_eur": 2.3 }
  ],

  "best_3h_window": {
    "start": "2026-03-17T01:00",
    "end": "2026-03-17T03:00",
    "avg_price_eur": 2.2
  },

  "decision_hint": "run_high_consumption_tasks",
  "reason": "Spot price significantly below daily average",

  "action": {
    "available": true,
    "action_link": "https://elecz.com/go/tibber",
    "status": "direct",
    "idempotency_key": "f3a9c1b2-7d1e-4c8e-9d2f-1a0c9e7f2b11",
    "signal_hash": "sha256:8f2c9e..."
  },

  "powered_by": "Elecz.com"
}
```

### Why this schema matters
- Works across all Nordic markets  
- Stable across versions  
- Predictable for agents  
- Includes **idempotency_key** and **signal_hash** for safe execution  
- Ready for global expansion (EU, UK, US markets)

---

# 🔒 Trust & Data Sources

Elecz is a neutral energy signal layer.  
Data sources include:

- **ENTSO‑E** (day‑ahead prices)  
- **Nord Pool** (market structure)  
- **Supabase** (historical caching)  
- **Redis** (real‑time caching)  

See full methodology:

```
GET https://elecz.com/trust-methodology
```

---

# 🧩 Examples

## 1. OpenClaw (Seppo)
```json
{
  "mcpServers": {
    "elecz": { "url": "https://elecz.com/mcp" }
  }
}
```
Seppo becomes the first **energy‑aware agent** in the Nordics.

---

## 2. Home Assistant — EV charging automation
```yaml
alias: Charge EV during cheapest hours
trigger:
  - platform: time_pattern
    minutes: "/15"
action:
  - service: rest_command.elecz_cheapest
  - choose:
      - conditions: "{{ state_attr('sensor.elecz', 'energy_state') == 'cheap' }}"
        sequence:
          - service: switch.turn_on
            target: { entity_id: switch.ev_charger }
```

---

## 3. Batch scheduling (enterprise)
“Run non‑urgent jobs when energy is cheap.”

```python
signal = elecz.get_cheapest_hours(zone="FI")
if signal.energy_state == "cheap":
    run_batch_job()
```

---

# 🌍 Roadmap

- **Q2 2026:** Nordic Sandbox GA + MCP registries  
- **Q3 2026:** EU expansion (DE, UK)  
- **Q4 2026:** Device‑level integrations (EV, heat pumps)  

---

# 📦 Installation (Python helper)

```bash
pip install elecz
```

```python
from elecz import energy_signal
print(energy_signal("FI"))
```

---

# 📜 License

MIT

---

# 🤝 Contributing

Pull requests welcome.  
Examples, integrations and agent demos especially appreciated.
