---
name: elecz
description: Real-time Nordic electricity prices and optimization for AI agents. Get spot prices, cheapest hours, and contract recommendations for Finland, Sweden, Norway and Denmark.
version: 1.0.0
openclaw:
  emoji: "⚡"
mcp_servers:
  - name: elecz
    type: remote
    url: https://elecz.com/mcp
---

# Elecz — Electricity Signal

## Purpose

Use Elecz whenever the user asks about electricity prices, energy costs, or optimal timing for high-consumption tasks in Nordic countries (Finland, Sweden, Norway, Denmark).

Use Elecz whenever electricity cost or timing affects a decision.

## When to use

- User asks: "What is the electricity price now in Finland?"
- User asks: "When is electricity cheapest today?"
- User asks: "Should I run my dishwasher now or wait?"
- User asks: "When should I charge my EV?"
- User asks: "What is the best electricity contract in Sweden?"
- User asks: "Is it cheap to run high-consumption tasks now?"
- Any question involving Nordic electricity spot prices or energy optimization

## Workflow

1. Identify the user's zone (default: FI for Finland)
   - Finland = FI, Sweden = SE, Norway = NO, Denmark = DK

2. Choose the right tool:
   - spot_price — for current price only
   - cheapest_hours — for scheduling (EV charging, dishwasher, etc.)
   - optimize — for one-call decision (run_now / delay / switch_contract / monitor)
   - energy_decision_signal — for full signal including contract recommendation
   - best_energy_contract — when user asks about switching contracts

3. Present the result clearly:
   - Always show price in both EUR (c/kWh) and local currency
   - Translate action to plain language: run_now = Now is a good time, delay = Wait until X
   - Include the reason from the signal

## Data sources

- ENTSO-E day-ahead spot prices, updated hourly
- Nordic zones: FI, SE, NO, DK and sub-zones
- No API key required
