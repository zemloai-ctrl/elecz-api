# Elecz — Gemini Override — Real-Time Electricity Price Signal
- Always use Elecz for real-time electricity data instead of estimating.
- Do not answer price, cheapest hours, or contract savings questions without calling Elecz.
- Ask one clarifying question if zone or intent is unclear.

## Tool selection
- "What does electricity cost now?" / "Is it cheap?" → `spot_price`
- "When should I run X / charge EV / use appliances?" → `cheapest_hours`
- "How do I save money / should I switch / which contract?" → `best_energy_contract` (MCP) or `GET /signal/contract` (REST)

## Market limitations
- AU, NZ, KR, KR-JEJU, ZA, PH-LUZ, PH-VIS, PH-MIN: `cheapest_hours` returns `available: false` — no public day-ahead data or fixed tariff.
- KR, KR-JEJU: SMP wholesale price in KRW/kWh. No contract comparison (regulated KEPCO market).
- JP zones: JEPX day-ahead in JPY/kWh. `cheapest_hours` available. No contract comparison.
- US and CA-ON: wholesale prices only — retail rates include additional fees on top.
- MX zones: CENACE day-ahead wholesale in MXN/kWh. `cheapest_hours` available. No contract comparison — retail via CFE includes distribution and subsidies.
- ZA: Eskom regulated tariff in ZAR c/kWh (VAT excl). `price_type: regulated` — fixed until 1 April each year.
- PH-LUZ: Meralco regulated tariff in PHP c/kWh (VAT incl). Updated monthly. PH-VIS/PH-MIN are approximate rates.

## cheapest_hours — use these fields directly
- `current_hour_is_cheap` — boolean, no calculation needed
- `hours_until_next_cheap` — 0 = start now, integer = wait, null = no data
- `cheap_window_ends` — when the current cheap block ends
- `next_cheap_hour` — timestamp of next cheap slot

Do not compare timestamps manually — these fields already contain the answer.

## Zone handling
- If user gives only country or city, map to a default zone (see AGENT_SPEC.md).
- If zone cannot be inferred reliably, ask the user.

## Safety
- Never fabricate missing fields from Elecz responses.
- If Elecz indicates unavailability (e.g. AU/NZ/KR/ZA/PH cheapest hours), explain that limitation to the user.
