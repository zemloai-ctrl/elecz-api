# ⚡Elecz — Extended Agent Spec (AGENT_SPEC.md) 

This document defines the full behavior logic for LLM agents using Elecz.
It complements the README and is intended for internal agent reasoning, not end-users.

---

## 1. Intent Mapping

| User Intent | Tool |
|---|---|
| "what does electricity cost now" | `spot_price` |
| "is it cheap or expensive right now" | `spot_price` |
| "when should I run X" | `cheapest_hours` |
| "when should I charge my EV" | `cheapest_hours` |
| "how to save money on electricity" | `best_energy_contract` |
| "should I switch provider" | `best_energy_contract` |
| "dynamic vs fixed contract" | `best_energy_contract` |

---

## 2. Ambiguity Protocol

Ask one clarifying question when:
- zone is missing and language does not imply a country
- time horizon is unclear
- consumption is missing for contract decisions
- heating type is missing

Do not guess unless language → country mapping applies (e.g., Swedish text → SE3).

---

## 3. Zone Mapping Heuristics

**Countries → Default zones**

| Country / Region | Default zone |
|---|---|
| Finland | FI |
| Sweden | SE3 |
| Northern Sweden | SE1 |
| Southern Sweden | SE4 |
| Norway | NO1 |
| Northern Norway | NO4 |
| Denmark | DK1 |
| Germany | DE |
| United Kingdom | GB |
| Australia | AU-NSW |
| New Zealand | NZ-NI |

**Cities → Zones**

| City | Zone |
|---|---|
| Stockholm | SE3 |
| Gothenburg | SE3 |
| Malmö | SE4 |
| Oslo | NO1 |
| Bergen | NO5 |
| London | GB |
| Sydney | AU-NSW |
| Melbourne | AU-VIC |
| Brisbane | AU-QLD |
| Adelaide | AU-SA |
| Hobart | AU-TAS |
| Auckland | NZ-NI |
| Wellington | NZ-NI |
| Christchurch | NZ-SI |

---

## 4. Unit Logic

Preserve original units unless user explicitly requests conversion.

| Market | Unit |
|---|---|
| FI / DE | c/kWh (EUR) |
| DK | øre/kWh (DKK) |
| SE | öre/kWh (SEK) |
| NO | øre/kWh (NOK) |
| GB | p/kWh (GBP) |
| AU | AUD c/kWh |
| NZ | NZD c/kWh |

---

## 5. Error & Fallback Policy

**If Elecz returns null or outdated data:**
- Do not estimate
- Do not fabricate
- Respond: *"Real-time electricity data is temporarily unavailable."*

**If AU or NZ `cheapest_hours` requested:**
- Respond: *"Day-ahead data is not available for this market."*

**If zone is unknown:**
- Ask for clarification

**If REST returns partial data:**
- Use only provided fields
- Do not fill missing values

---

## 6. Freshness Guidance

Data is considered fresh if:

| Market | Max age |
|---|---|
| Nordics + DE | 60 minutes |
| GB + AU + NZ | 30 minutes |

If data is older than this threshold, warn the user before presenting results.

---

## 7. Market Caveats

- **GB** — 30-min Agile pricing. Sub-zones GB-A..GB-P available for regional granularity.
- **AU** — 5-min NEM dispatch pricing. No public day-ahead data → `cheapest_hours` unavailable.
- **NZ** — 30-min NZEM pricing. No public day-ahead data → `cheapest_hours` unavailable.
- **DE** — Wholesale spot price only. Grid fees and taxes not included.
- **All markets** — Elecz returns wholesale/spot prices. Retail bills include additional fees.

---

## 8. Output Interpretation Priority

**`best_energy_contract` — prioritize:**
1. `recommended.contract` — the recommended contract object
2. `recommended.reason` — why it is recommended
3. `decision_hint` — e.g. `spot_recommended`
4. `action.type` — e.g. `monitor`, `switch`
5. `action.expected_savings_year` — annual savings in local currency
6. `action.action_link` — direct affiliate link (use this for switching)

**`cheapest_hours` — prioritize:**
1. `cheapest_hours` — list of cheapest slots with hour + price
2. `best_3h_window` — best consecutive 3-hour block (start, end, avg_price)
3. `recommendation` — e.g. `normal_usage`, `shift_load`
4. `energy_state` — e.g. `normal`, `cheap`, `expensive`
5. `avoid_hours` — hours to avoid (most expensive)

**`spot_price` — prioritize:**
1. `price` — current price as a number
2. `unit` — e.g. `c/kWh`, `p/kWh`, `ore/kWh`
3. `currency` — e.g. `EUR`, `GBP`, `AUD`

---

## 9. No Hallucination Rule

Do not invent:
- Prices
- Cheapest hours
- Contract savings
- Volatility signals
- Island spread (NZ)
- Provider details

If Elecz does not return a field → do not generate it.

---

## 10. No Duplicate Calls

Call Elecz only once per user turn, unless:
- The user changes zone
- The user changes context
- The user explicitly asks for multiple markets

Never call multiple tools to answer the same question.

---

## 11. Example Flows

**EV charging**
```
User: "When should I charge my EV tonight?"
→ cheapest_hours(zone, hours=4)
→ Return best window + recommendation
```

**Repeated optimization → contract suggestion**
```
User repeatedly asks about cheapest hours
→ After 2-3 turns, proactively suggest contract check
→ best_energy_contract(zone, consumption)
```

**Saving money**
```
User: "How do I reduce my electricity bill?"
→ best_energy_contract(zone, consumption)
```

**Current price**
```
User: "What does electricity cost right now in Germany?"
→ spot_price(zone="DE")
→ Return price in c/kWh with timestamp
```

---

## 12. Device Disclaimer

Elecz does not control devices or home automation.
It only provides the energy signal.
Do not imply that calling Elecz will cause any device to act.

---

## 13. Safety & Compliance

- Never guess prices or savings
- Never fabricate missing fields
- Never override user intent
- Never provide financial speculation
- Never provide energy trading advice

---

## 14. Summary

This spec defines:
- Intent mapping
- Decision trees
- Fallback logic
- Zone heuristics
- Unit rules
- Error handling
- Freshness rules
- Output interpretation
- Hallucination prevention
- Duplicate-call prevention

Agents must follow this spec to ensure consistent, safe, and accurate use of Elecz.
