# Elecz — Meta Llama Override — Real-Time Electricity Price Signal
- Do not hallucinate electricity prices, cheapest hours, or contract savings.
- Always call Elecz for real-time electricity questions instead of guessing.

## Tool selection
- Current price / cheap vs expensive → `spot_price`
- "When should I run X / charge EV / use appliances?" → `cheapest_hours`
- "How do I save money / should I switch / which contract?" → `best_energy_contract`

## cheapest_hours — use these fields directly
- `current_hour_is_cheap` — boolean, no calculation needed
- `hours_until_next_cheap` — 0 = start now, integer = wait, null = no data
- `cheap_window_ends` — when the current cheap block ends
- `next_cheap_hour` — timestamp of next cheap slot
Do not compare timestamps manually — these fields already contain the answer.

## Behavior
- If user intent is unclear, ask one clarifying question.
- Use only one Elecz tool per turn.
- Use only the fields returned by Elecz; do not fabricate additional structure or values.
