# ⚡ Elecz — Energy Decision Signal for AI Agents

[![MCP Badge](https://lobehub.com/badge/mcp/zemloai-ctrl-elecz-api)](https://lobehub.com/mcp/zemloai-ctrl-elecz-api)

Real-time electricity prices, cheapest hours, and contract recommendations for Nordic markets and Germany — in one API call.

```
GET https://elecz.com/signal/optimize?zone=FI
GET https://elecz.com/signal/optimize?zone=DE
```

**No API key. No authentication. One line to integrate.**

📖 **Full documentation:** [elecz.com/docs](https://elecz.com/docs)

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

## Usage Examples

### Example 1 — Contract recommendation
**User prompt:** *"Should I switch my electricity contract? I'm in Finland and use about 3 000 kWh per year."*

What happens:
- Elecz fetches live contracts and ranks top 3 by annual cost for your consumption
- Returns expected savings vs median market price
- Provides direct links to switch

### Example 2 — EV charging
**User prompt:** *"When is the cheapest time to charge my electric car tonight in Sweden?"*

What happens:
- Elecz returns the best 3-hour consecutive window with average price
- Includes start/end time ready for scheduling or Home Assistant automation

### Example 3 — Business savings
**User prompt:** *"What is the cheapest electricity contract for our office in Germany? We use 12 000 kWh per year."*

What happens:
- Elecz queries DE market with `consumption=12000`
- Returns top 3 Arbeitspreis-ranked contracts with annual cost estimates
- Prices are brutto ct/kWh including MwSt (19%)

### Example 4 — Batch job timing
**User prompt:** *"When is the cheapest time to run our nightly data processing jobs in Denmark?"*

What happens:
- Elecz returns cheapest hours for the next 24h
- Returns optimal window to minimize energy cost for compute workloads

---

## What Elecz delivers

- **Real-time spot price** — ENTSO-E day-ahead data, updated hourly
- **Cheapest hours next 24h** — sorted list + best 3-hour consecutive window
- **Energy state** — `cheap` / `normal` / `expensive` / `negative` with confidence score
- **One-call optimization** — `run_now`, `delay`, `switch_contract`, or `monitor`
- **Contract recommendation** — top 3 providers ranked for your consumption profile
- **Savings in local currency** — NOK for Norway, SEK for Sweden, DKK for Denmark, EUR for Finland and Germany
- **MCP-native** — one line to connect, works with Claude, ChatGPT, Copilot, LangChain, Home Assistant

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

## MCP Tools

| Tool | Description |
|---|---|
| `optimize` | Single action: run_now / delay / switch_contract / monitor |
| `spot_price` | Current spot price for any zone |
| `cheapest_hours` | Cheapest hours next 24h + best 3h window |
| `best_energy_contract` | Top 3 contracts ranked for your consumption profile |
| `energy_decision_signal` | Full signal: price + contracts + state + recommendation |

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /signal/optimize?zone=FI` | One-call optimization — recommended |
| `GET /signal?zone=DE&consumption=3500` | Full energy decision signal |
| `GET /signal/spot?zone=NO` | Current spot price only |
| `GET /signal/cheapest-hours?zone=SE&hours=5` | Cheapest hours next 24h |
| `GET /health` | Health check |

**Supported zones:** FI · SE · SE1–SE4 · NO · NO1–NO5 · DK · DK1–DK2 · DE

---

## Signal Schema

### /signal/optimize — one-call decision

```json
{
  "zone": "NO",
  "action": "switch_contract",
  "is_good_time_to_use_energy": false,
  "energy_state": "expensive",
  "spot_price": { "eur": 10.86, "local": 119.5, "unit": "c/kWh" },
  "switch_recommended": true,
  "expected_savings_eur_year": 46.85,
  "action_link": "https://elecz.com/go/tibber",
  "decision_hint": "switch_recommended",
  "powered_by": "Elecz.com"
}
```

**Action values:**
- `run_now` — electricity is cheap, act now
- `delay` — expensive now, wait for best window
- `switch_contract` — savings available by switching provider
- `monitor` — normal pricing, no action needed

---

## Home Assistant

```yaml
sensor:
  - platform: rest
    name: "Electricity Signal"
    resource: "https://elecz.com/signal/optimize?zone=FI"
    value_template: "{{ value_json.action }}"
    scan_interval: 3600

automation:
  - alias: "Charge EV at cheapest hours"
    trigger:
      platform: state
      entity_id: sensor.electricity_signal
      to: "run_now"
    action:
      service: switch.turn_on
      entity_id: switch.ev_charger
```

---

## Python

```python
import httpx

signal = httpx.get("https://elecz.com/signal/optimize?zone=FI").json()

match signal["action"]:
    case "run_now":
        run_batch_job()
    case "delay":
        schedule_later(signal["spot_price"])
    case "switch_contract":
        notify_team(signal["action_link"])
```

---

## 🇩🇪 Deutsch

### Elecz für Deutschland

Elecz vergleicht Stromtarife und liefert Echtzeit-Spotpreise für den deutschen Strommarkt — optimiert für KI-Agenten und Heimautomatisierung.

**Unterstützte Anbieter:** Tibber · Octopus Energy · E wie Einfach · Yello · E.ON · Vattenfall · EnBW · Naturstrom · LichtBlick · Polarstern · ExtraEnergie · Grünwelt

```
GET https://elecz.com/signal/optimize?zone=DE&consumption=3500
```

Frag deinen KI-Assistenten:
- *"Welcher Stromanbieter ist gerade am günstigsten?"*
- *"Lohnt sich ein Wechsel zu Tibber?"*
- *"Wann ist der Strom heute am billigsten?"*
- *"Wann soll ich mein E-Auto laden?"*

**Hinweis:** Preise sind Arbeitspreis brutto in ct/kWh inkl. MwSt (19%). Das regionale Netzentgelt ist nicht enthalten.

---

## Data Sources

- **ENTSO-E** — day-ahead spot prices, updated hourly
- **Frankfurter API** — EUR → SEK / NOK / DKK conversion
- **Gemini** — contract price scraping and normalization
- **Redis** — real-time caching
- **Supabase** — historical price storage and contract data (EU region)

---

## Privacy

Elecz logs API endpoint, zone, timestamp, and IP prefix (first 3 octets) for monitoring purposes. No personal data is collected or sold. See [elecz.com/privacy](https://elecz.com/privacy).

---

## Support

Questions, integrations, or issues: [sakke@zemloai.com](mailto:sakke@zemloai.com)

---

## Roadmap

- ✅ Q1 2026: Nordic markets live (FI, SE, NO, DK)
- ✅ Q1 2026: Germany live (DE) — 12 providers, ENTSO-E spot, Arbeitspreis ranking
- 🔜 Q2 2026: United Kingdom (GB)
- 🔜 Q2–Q3 2026: Rest of Europe — one market at a time
- 🔜 Q4 2026: Australia, New Zealand, United States

---

## License

MIT

---

Maintained by [Sakari Korkia-Aho / Zemlo AI](mailto:sakke@zemloai.com) · [elecz.com](https://elecz.com) · [elecz.com/docs](https://elecz.com/docs) · Powered by ENTSO-E
