"""
Elecz MCP Server
Real-time energy decision signal for AI agents.
FastMCP-based server with streamable HTTP transport.
"""

import os
import json
import logging
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ─── FastMCP init ──────────────────────────────────────────────────────────
mcp = FastMCP("elecz_mcp")

ELECZ_API_BASE = os.environ.get("ELECZ_API_BASE", "https://elecz-api.onrender.com")

VALID_ZONES = ["FI", "SE", "SE1", "SE2", "SE3", "SE4", "NO", "NO1", "NO2", "NO3", "NO4", "NO5", "DK", "DK1", "DK2"]


# ─── Input models ──────────────────────────────────────────────────────────

class ZoneInput(BaseModel):
    """Input for zone-based queries."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = Field(
        default="FI",
        description="Nordic bidding zone. FI=Finland, SE=Sweden, NO=Norway, DK=Denmark. Sub-zones: SE1-SE4, NO1-NO5, DK1-DK2."
    )


class SignalInput(BaseModel):
    """Input for full energy decision signal."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = Field(
        default="FI",
        description="Nordic bidding zone. FI=Finland, SE=Sweden, NO=Norway, DK=Denmark."
    )
    consumption: int = Field(
        default=2000,
        ge=100,
        le=100000,
        description="Annual electricity consumption in kWh. Typical apartment: 1500-2000, house: 5000-20000."
    )
    heating: str = Field(
        default="district",
        description="Heating type: 'district' (kaukolämpö) or 'electric' (sähkölämmitys)."
    )


class CheapestHoursInput(BaseModel):
    """Input for cheapest hours query."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = Field(
        default="FI",
        description="Nordic bidding zone."
    )
    hours: int = Field(
        default=5,
        ge=1,
        le=24,
        description="Number of cheapest hours to return."
    )
    window: int = Field(
        default=24,
        ge=1,
        le=48,
        description="Hours to look ahead (default 24)."
    )


# ─── Helper ────────────────────────────────────────────────────────────────

import httpx

def _call_elecz(path: str, params: dict) -> dict:
    """Call Elecz REST API and return JSON."""
    try:
        resp = httpx.get(f"{ELECZ_API_BASE}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e), "powered_by": "Elecz.com"}


# ─── MCP Tools ─────────────────────────────────────────────────────────────

@mcp.tool(
    name="energy_decision_signal",
    annotations={
        "title": "Energy Decision Signal",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def energy_decision_signal(params: SignalInput) -> str:
    """
    Get full energy decision signal for a Nordic zone.

    Returns current spot price, best electricity contract recommendation,
    energy state (cheap/normal/expensive), confidence score, and decision hint.

    Use this when user asks:
    - What is the electricity price now?
    - Which electricity contract should I choose?
    - Should I switch my electricity contract?
    - What is the best electricity deal in Finland/Sweden/Norway/Denmark?

    Args:
        params: SignalInput with zone, consumption (kWh/year), and heating type.

    Returns:
        str: JSON with spot_price, best_contract, energy_state, confidence, decision_hint, action_link.
    """
    data = _call_elecz("/signal", {
        "zone":        params.zone.upper(),
        "consumption": params.consumption,
        "heating":     params.heating,
    })
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool(
    name="spot_price",
    annotations={
        "title": "Current Spot Price",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def spot_price(params: ZoneInput) -> str:
    """
    Get current electricity spot price for a Nordic zone.

    Returns real-time spot price in EUR c/kWh and local currency.
    Data source: ENTSO-E Transparency Platform.

    Use this when user asks:
    - What is the electricity price right now?
    - How much does electricity cost today?
    - What is pörssisähkö price now?
    - Mikä on sähkön hinta nyt?

    Args:
        params: ZoneInput with zone code.

    Returns:
        str: JSON with price_eur, price_local, currency, timestamp.
    """
    data = _call_elecz("/signal/spot", {"zone": params.zone.upper()})
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool(
    name="cheapest_hours",
    annotations={
        "title": "Cheapest Electricity Hours",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def cheapest_hours(params: CheapestHoursInput) -> str:
    """
    Get cheapest electricity hours in the next 24 hours.

    Returns sorted list of cheapest hours, best consecutive window,
    hours to avoid, and automation recommendation.

    Use this when user or automation asks:
    - When is electricity cheapest today?
    - When should I charge my EV?
    - When should I run the dishwasher/washing machine?
    - When should I heat the water boiler?
    - Milloin sähkö on halvinta?
    - Optimize home automation for cheapest electricity.

    Args:
        params: CheapestHoursInput with zone, hours count, and window.

    Returns:
        str: JSON with cheapest_hours list, best_3h_window, avoid_hours, recommendation.
    """
    data = _call_elecz("/signal/cheapest-hours", {
        "zone":   params.zone.upper(),
        "hours":  params.hours,
        "window": params.window,
    })
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool(
    name="best_energy_contract",
    annotations={
        "title": "Best Energy Contract",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def best_energy_contract(params: SignalInput) -> str:
    """
    Get best electricity contract for a given consumption profile.

    Returns ranked contract recommendation with trust score,
    estimated annual cost, and direct link to switch.

    Use this when user asks:
    - What is the best electricity contract for me?
    - Should I switch to spot pricing or fixed price?
    - Which electricity provider is cheapest?
    - Mikä on halvin sähkösopimus?

    Args:
        params: SignalInput with zone, annual consumption (kWh), and heating type.

    Returns:
        str: JSON with best_contract, trust_score, annual_cost_estimate, action_link.
    """
    data = _call_elecz("/signal", {
        "zone":        params.zone.upper(),
        "consumption": params.consumption,
        "heating":     params.heating,
    })
    # Return only contract-relevant fields
    result = {
        "zone":          data.get("zone"),
        "best_contract": data.get("best_contract"),
        "decision_hint": data.get("decision_hint"),
        "reason":        data.get("reason"),
        "action":        data.get("action"),
        "powered_by":    data.get("powered_by"),
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


# ─── Run ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", 8001))
    mcp.run(transport="streamable_http", port=port)
