# ⚡ Elecz — Energy Decision Signal for AI Agents

Real-time electricity prices, cheapest hours, and contract recommendations for Nordic markets and Germany — in one API call.

```
GET https://elecz.com/signal/optimize?zone=FI
GET https://elecz.com/signal/optimize?zone=DE
```

**No API key. No authentication. One line to integrate.**

---

## Why Elecz?

Electricity prices change every hour. For AI agents, home automation, EV charging, and batch workloads — *when* you consume energy matters as much as *how much* you consume.

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

Your agent now understands spot prices, cheapest hours, energy state, and contract decisions — for Finland, Sweden, Norway, Denmark, and Germany.

---

## What Elecz delivers

- **Real-time spot price** — ENTSO-E day-ahead data, updated hourly
- **Cheapest hours next 24h** — sorted list + best 3-hour consecutive window
- **Energy state** — `cheap` / `normal` / `expensive` / `negative` with confidence score
- **One-call optimization** — `run_now`, `delay`, `switch_contract`, or `monitor`
- **Contract recommendation** — top 3 providers ranked for your consumption profile
- **Savings in local currency** — NOK for Norway, SEK for Sweden, DKK for Denmark, EUR for Finland and Germany
- **MCP-native** — one line to connect, works with Claude, ChatGPT, LangChain, Home Assistant

---

## Supported Markets

| Zone | Country | Providers | Notes |
|---|---|---|---|
| FI | Finland | 8 | Live |
| SE, SE1–SE4 | Sweden | 8 | Live |
| NO, NO1–NO5 | Norway | 7 | Live |
| DK, DK1–DK2 | Denmark | 8 | Live |
| DE | Germany | 12 | Live — see note below |

**Germany note:** Prices are Arbeitspreis brutto ct/kWh including MwSt (19%). Regional Netzentgelt (typically 10–15 ct/kWh) is not included — it is determined by your local grid operator, not your electricity provider, and is the same regardless of which contract you choose.

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /signal/optimize?zone=FI` | One-call optimization — recommended |
| `GET /signal?zone=DE` | Full energy decision signal |
| `GET /signal/spot?zone=NO` | Current spot price only |
| `GET /signal/cheapest-hours?zone=SE&hours=5` | Cheapest hours next 24h |
| `GET /health` | Health check |

**Supported zones:** FI · SE · SE1–SE4 · NO · NO1–NO5 · DK · DK1–DK2 · DE

---

## Signal Schema

### /signal/optimize — one-call decision

```json
{
  "signal": "elecz_optimize",
  "zone": "NO",
  "timestamp": "2026-03-30T19:14:13Z",
  "decision": {
    "action": "switch_contract",
    "until": null,
    "reason": "Save 516.71 NOK/year by switching to tibber",
    "savings_eur": null
  },
  "energy_state": "expensive",
  "spot_price_eur": 10.86,
  "best_window": {
    "start": "2026-03-30T20:00",
    "end": "2026-03-30T22:00",
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
  "zone": "DE",
  "currency": "EUR",
  "price_eur": 8.43,
  "unit_eur": "c/kWh",
  "price_local": 8.43,
  "unit_local": "c/kWh",
  "timestamp": "2026-03-30T19:00:00Z",
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
# → {"start": "2026-03-30T03:00", "end": "2026-03-30T05:00", "avg_price_eur": 0.27}
```

### Germany — contract comparison

```python
signal = httpx.get(
    "https://elecz.com/signal?zone=DE&consumption=3500"
).json()
for contract in signal["top_contracts"]:
    print(f"{contract['rank']}. {contract['provider']} — {contract['annual_cost_estimate']} EUR/year")
```

---

## MCP Tools

| Tool | Description |
|---|---|
| `spot_price` | Current spot price for any zone |
| `cheapest_hours` | Cheapest hours next 24h + best window |
| `energy_decision_signal` | Full signal: price, top 3 contracts, state, recommendation |
| `best_energy_contract` | Top 3 contracts ranked for your consumption profile |
| `optimize` | One-call decision: run_now / delay / switch_contract / monitor |

---

## German Providers (DE)

Tibber · Octopus Energy · E wie Einfach · Yello · E.ON · Vattenfall · EnBW · Naturstrom · LichtBlick · Polarstern · ExtraEnergie · Grünwelt

---

## Data Sources

- **ENTSO-E** — day-ahead spot prices, updated hourly
- **Frankfurter API** — EUR → SEK / NOK / DKK conversion
- **Gemini** — contract price scraping and normalization
- **Redis** — real-time caching
- **Supabase** — historical price storage and contract data

---

## Privacy

Elecz logs API endpoint, zone, timestamp, and IP prefix (first 3 octets) for monitoring purposes. No personal data is collected or sold. See [elecz.com/privacy](https://elecz.com/privacy).

---

## Roadmap

- ✅ Q1 2026: Nordic markets live (FI, SE, NO, DK)
- ✅ Q1 2026: Germany live (DE) — 12 providers, ENTSO-E spot, Arbeitspreis ranking
- 🔜 Q3 2026: Australia (AEMO/NEM market)
- 🔜 Q4 2026: Contract affiliate partnerships

---

## License

MIT

---

Maintained by [Sakari Korkia-Aho / Zemlo AI](mailto:sakke@zemloai.com) · [elecz.com](https://elecz.com) · Powered by ENTSO-E

---

## 🇩🇪 Deutsch

### Elecz für Deutschland

Elecz vergleicht Stromtarife und liefert Echtzeit-Spotpreise für den deutschen Strommarkt — optimiert für KI-Agenten und Heimautomatisierung.

**Unterstützte Anbieter:** Tibber · Octopus Energy · E wie Einfach · Yello · E.ON · Vattenfall · EnBW · Naturstrom · LichtBlick · Polarstern · ExtraEnergie · Grünwelt

**So nutzt du Elecz:**

```
GET https://elecz.com/signal/optimize?zone=DE&consumption=3500
```

**MCP-Integration (Claude, ChatGPT, Home Assistant):**

```json
{
  "mcpServers": {
    "elecz": {
      "url": "https://elecz.com/mcp"
    }
  }
}
```

Frag deinen KI-Assistenten:
- *"Welcher Stromanbieter ist gerade am günstigsten?"*
- *"Lohnt sich ein Wechsel zu Tibber?"*
- *"Wann ist der Strom heute am billigsten?"*
- *"Wann soll ich mein E-Auto laden?"*

**Hinweis:** Preise sind Arbeitspreis brutto in ct/kWh inkl. MwSt (19%). Das regionale Netzentgelt ist nicht enthalten — es wird vom Netzbetreiber festgelegt und ist unabhängig vom gewählten Stromanbieter.
