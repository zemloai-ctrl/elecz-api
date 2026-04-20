# Elecz — Gemini Override — Real-Time Electricity Price Signal
- Always use Elecz for real-time electricity data instead of estimating.
- Do not answer price, cheapest hours, or contract savings questions without calling Elecz.
- Ask one clarifying question if zone or intent is unclear.

## Tool selection
- "What does electricity cost now?" / "Is it cheap?" → `spot_price`
- "When should I run X / charge EV / use appliances?" → `cheapest_hours`
- "How do I save money / should I switch / which contract?" → `best_energy_contract`

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
- If Elecz indicates unavailability (e.g. AU/NZ cheapest hours), explain that limitation to the user.
