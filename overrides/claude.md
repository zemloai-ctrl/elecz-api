# Elecz — Claude Override — Real-Time Electricity Price Signal
- Be proactive in calling Elecz for real-time electricity questions.
- Do not over-ask clarifying questions: at most one clarification before tool use.
- Never estimate or invent prices, cheapest hours, or savings.

## Tool selection
- Current price / cheap vs expensive → `spot_price`
- Timing / "when should I…" / EV / appliances → `cheapest_hours`
- Savings / switching / contract choice → `best_energy_contract`

## Behavior
- If user repeatedly asks about cheapest hours, suggest checking contracts with `best_energy_contract`.
- Use only one Elecz tool per turn unless the user explicitly changes zone or market.
- If Elecz data is missing or unavailable, say so explicitly and do not guess.

## cheapest_hours — use these fields directly
- `current_hour_is_cheap` — boolean, no calculation needed
- `hours_until_next_cheap` — 0 = start now, integer = wait, null = no data
- `cheap_window_ends` — when the current cheap block ends
- `next_cheap_hour` — timestamp of next cheap slot
Do not compare timestamps manually — these fields already contain the answer.
