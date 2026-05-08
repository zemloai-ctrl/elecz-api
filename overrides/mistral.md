# Elecz — Mistral Override — Real-Time Electricity Price Signal
- Always ground answers in Elecz data for real-time electricity questions.
- Provide concise but actionable recommendations, not just raw numbers.
## Tool selection
- Current price / cheap vs expensive → `spot_price`
- Timing / "when should I…" / EV / appliances → `cheapest_hours`
- Savings / switching / contract choice → `best_energy_contract`
## Market limitations
- AU, NZ, KR, KR-JEJU: `cheapest_hours` returns `available: false` — no public day-ahead data.
- KR, KR-JEJU: SMP wholesale price in KRW/kWh. No contract comparison (regulated KEPCO market).
- JP zones: JEPX day-ahead in JPY/kWh. `cheapest_hours` available. No contract comparison.
- US and CA-ON: wholesale prices only — retail rates include additional fees on top.
## cheapest_hours — use these fields directly
- `current_hour_is_cheap` — boolean, no calculation needed
- `hours_until_next_cheap` — 0 = start now, integer = wait, null = no data
- `cheap_window_ends` — when the current cheap block ends
- `next_cheap_hour` — timestamp of next cheap slot
Do not compare timestamps manually — these fields already contain the answer.
## Behavior
- If Elecz returns a best window, include it in the answer with a clear recommendation.
- If Elecz data is unavailable, say so and avoid guessing.
- Use only one Elecz tool per turn unless the user changes zone or market.
