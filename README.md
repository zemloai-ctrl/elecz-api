# ⚡ Elecz — Energy Decision Signal for AI Agents

Real-time Nordic electricity prices, cheapest hours, and contract recommendations — in one API call.

```
GET https://elecz.com/signal/optimize?zone=FI
```

**No API key. No authentication. One line to integrate.**

---

## Why Elecz?

Electricity prices in the Nordic market change every hour. For AI agents, home automation, EV charging, and batch workloads — *when* you consume energy matters as much as *how much* you consume.

Elecz turns complex ENTSO-E market data into a single actionable signal:

> *"Run now. Electricity is cheap."*
> *"Wait until 03:00. Best 3-hour window starts then."*
> *"Switch to Tibber. Save 516 NOK/year."*

---

## Quickstart — Add to your agent

```json
{
  "mcpServers": {
    "elecz": {
      "url": "https://elecz.com/mcp"
    }
  }
}
```

Your agent now understands Nordic spot prices, cheapest hours, energy state, and contract decisions — for Finland, Sweden, Norway, and Denmark.

---

## What Elecz delivers

- **Real-time spot price** — ENTSO-E day-ahead data, updated hourly
- **Cheapest hours next 24h** — sorted list + best 3-hour consecutive window
- **Energy state** — `cheap` / `normal` / `expensive` with confidence score
- **One-call optimization** — `run_now`, `delay`, `switch_contract`, or `monitor`
- **Contract recommendation** — best provider for your consumption profile
- **Savings in local currency** — NOK for Norway, SEK for Sweden, DKK for Denmark, EUR for Finland
- **MCP-native** — one line to connect, works with Claude, ChatGPT, LangChain, Home Assistant

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /signal/optimize?zone=FI` | One-call optimization — recommended |
| `GET /signal?zone=FI` | Full energy decision signal |
| `GET /signal/spot?zone=FI` | Current spot price only |
| `GET /signal/cheapest-hours?zone=FI&hours=5` | Cheapest hours next 24h |
| `GET /health` | Health check |

**Supported zones:** FI, SE, SE1–SE4, NO, NO1–NO5, DK, DK1–DK2

---

## Signal Schema

### /signal/optimize — one-call decision

```json
{
  "signal": "elecz_optimize",
  "zone": "NO",
  "timestamp": "2026-03-22T19:14:13Z",
  "decision": {
    "action": "switch_contract",
    "until": null,
    "reason": "Save 516.71 NOK/year by switching to tibber",
    "savings_eur": null
  },
  "energy_state": "expensive",
  "spot_price_eur": 10.86,
  "best_window": {
    "start": "2026-03-22T20:00",
    "end": "2026-03-22T22:00",
    "avg_price_eur": 10.93
  },
  "contract_switch": {
    "recommended": true,
    "provider": "tibber",
    "expected_savings_eur_year": 46.85,
    "expected_savings_local_year": 516.71,
    "savings_currency": "NOK",
    "link": "https://elecz.com/go/tibber"
  },
  "confidence": 0.95,
  "powered_by": "Elecz.com"
}
```

**Action values:**
- `run_now` — electricity is cheap, act now
- `delay` — expensive now, wait for best window
- `switch_contract` — savings available by switching provider
- `monitor` — normal pricing, no action needed

### /signal/spot — current price

```json
{
  "signal": "elecz_spot",
  "zone": "SE",
  "currency": "SEK",
  "price_eur": 3.43,
  "unit_eur": "c/kWh",
  "price_local": 36.99,
  "unit_local": "ore/kWh",
  "timestamp": "2026-03-22T19:00:00Z",
  "powered_by": "Elecz.com"
}
```

---

## Examples

### Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "elecz": {
      "url": "https://elecz.com/mcp"
    }
  }
}
```

### Python — schedule batch jobs by price

```python
import httpx

signal = httpx.get("https://elecz.com/signal/optimize?zone=FI").json()
decision = signal["decision"]

if decision["action"] == "run_now":
    run_batch_job()
elif decision["action"] == "delay":
    print(f"Wait until {decision['until']}")
elif decision["action"] == "switch_contract":
    print(decision["reason"])  # "Save 47 EUR/year by switching to helen"
```

### Home Assistant — automate EV charging

```python
signal = httpx.get("https://elecz.com/signal/cheapest-hours?zone=FI&hours=3").json()
best_window = signal["best_3h_window"]
# → {"start": "2026-03-23T03:00", "end": "2026-03-23T05:00", "avg_price_eur": 0.27}
```

---

## MCP Tools

| Tool | Description |
|---|---|
| `spot_price` | Current spot price for a Nordic zone |
| `cheapest_hours` | Cheapest hours next 24h + best window |
| `energy_decision_signal` | Full signal: price, contract, state, recommendation |
| `best_energy_contract` | Best contract for your consumption profile |
| `optimize` | One-call decision: run_now / delay / switch_contract / monitor |

---

## Data Sources

- **ENTSO-E** — day-ahead spot prices, updated hourly
- **Frankfurter API** — EUR → SEK / NOK / DKK conversion
- **Redis** — real-time caching
- **Supabase** — historical price storage and contract data

---

## Privacy

Elecz logs API endpoint, zone, timestamp, and IP address for monitoring purposes. No personal data is collected or sold. See [elecz.com/privacy](https://elecz.com/privacy).

---

## Roadmap

- Q2 2026: EU expansion (DE, FR, UK)
- Q3 2026: Device-level integrations (EV, heat pumps, boilers)
- Q4 2026: Contract switching with affiliate partnerships

---

## License

MIT

---

Maintained by [Sakari Korkia-Aho / Zemlo AI](mailto:sakke@zemloai.com) · [elecz.com](https://elecz.com) · Powered by ENTSO-E · Nordic markets
