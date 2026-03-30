"""
Elecz MCP Server
Real-time energy decision signal for AI agents.
Electricity spot prices, cheapest hours, and contract recommendations
for Finland, Sweden, Norway, Denmark and Germany.
FastMCP-based server with streamable HTTP transport.
"""

import os
import json
import logging
import httpx
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ─── FastMCP init ──────────────────────────────────────────────────────────
mcp = FastMCP("elecz_mcp")

ELECZ_API_BASE = os.environ.get("ELECZ_API_BASE", "https://elecz.com")

VALID_ZONES = [
    "FI", "SE", "SE1", "SE2", "SE3", "SE4",
    "NO", "NO1", "NO2", "NO3", "NO4", "NO5",
    "DK", "DK1", "DK2",
    "DE",
]

# Default annual consumption by market (kWh)
# DE: ~3500 kWh (German household average)
# Nordic: ~2000 kWh
DEFAULT_CONSUMPTION = {
    "FI": 2000, "SE": 2000, "SE1": 2000, "SE2": 2000, "SE3": 2000, "SE4": 2000,
    "NO": 2000, "NO1": 2000, "NO2": 2000, "NO3": 2000, "NO4": 2000, "NO5": 2000,
    "DK": 2000, "DK1": 2000, "DK2": 2000,
    "DE": 3500,
}

# ─── Input models ──────────────────────────────────────────────────────────

class ZoneInput(BaseModel):
    """Input for zone-based queries."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = Field(
        default="FI",
        description=(
            "Bidding zone. Nordic: FI=Finland, SE=Sweden, NO=Norway, DK=Denmark. "
            "Germany: DE. Sub-zones: SE1-SE4, NO1-NO5, DK1-DK2."
        )
    )


class SignalInput(BaseModel):
    """Input for full energy decision signal."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = Field(
        default="FI",
        description=(
            "Bidding zone. FI=Finland, SE=Sweden, NO=Norway, DK=Denmark, DE=Germany. "
            "Sub-zones: SE1-SE4, NO1-NO5, DK1-DK2."
        )
    )
    consumption: Optional[int] = Field(
        default=None,
        ge=100,
        le=100000,
        description=(
            "Annual electricity consumption in kWh. "
            "Defaults to 3500 for Germany (DE), 2000 for Nordic zones. "
            "Typical German household: 3000-4000 kWh. "
            "Typical Nordic apartment: 1500-2000 kWh, house: 5000-20000 kWh."
        )
    )
    heating: str = Field(
        default="district",
        description="Heating type: 'district' or 'electric'."
    )


class CheapestHoursInput(BaseModel):
    """Input for cheapest hours query."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = Field(
        default="FI",
        description=(
            "Bidding zone. FI, SE, NO, DK, DE. Sub-zones: SE1-SE4, NO1-NO5, DK1-DK2."
        )
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

def _call_elecz(path: str, params: dict) -> dict:
    """Call Elecz REST API and return JSON."""
    try:
        resp = httpx.get(f"{ELECZ_API_BASE}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e), "powered_by": "Elecz.com"}


def _resolve_consumption(zone: str, consumption: Optional[int]) -> int:
    if consumption is not None:
        return consumption
    return DEFAULT_CONSUMPTION.get(zone.upper(), 2000)


# ─── MCP Tools ─────────────────────────────────────────────────────────────

@mcp.tool(name="energy_decision_signal")
def energy_decision_signal(params: SignalInput) -> str:
    """
    Get full energy decision signal for a Nordic or German zone.

    Returns current spot price, top 3 electricity contract recommendations,
    energy state (cheap/normal/expensive/negative), confidence score, and decision hint.

    Use this when user asks:
    - What is the electricity price now?
    - Which electricity contract should I choose?
    - Should I switch my electricity contract?
    - What is the best electricity deal in Finland/Sweden/Norway/Denmark/Germany?
    - Was ist der beste Stromtarif in Deutschland?
    - Welcher Stromanbieter ist am günstigsten?
    - Mikä on halvin sähkösopimus?

    Args:
        params: SignalInput with zone, consumption (kWh/year), and heating type.

    Returns:
        str: JSON with spot_price, top_contracts, energy_state, confidence, decision_hint, action.
    """
    zone = params.zone.upper()
    consumption = _resolve_consumption(zone, params.consumption)
    data = _call_elecz("/signal", {
        "zone": zone,
        "consumption": consumption,
        "heating": params.heating,
    })
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool(name="spot_price")
def spot_price(params: ZoneInput) -> str:
    """
    Get current electricity spot price for a Nordic or German zone.

    Returns real-time spot price in EUR c/kWh and local currency.
    Data source: ENTSO-E Transparency Platform, updated hourly.

    Use this when user asks:
    - What is the electricity price right now?
    - How much does electricity cost today?
    - What is the spot price in Germany/Finland/Sweden/Norway/Denmark?
    - Was kostet Strom gerade? / Wie hoch ist der aktuelle Strompreis?
    - Mikä on sähkön hinta nyt? / Vad kostar el nu?

    Args:
        params: ZoneInput with zone code (FI, SE, NO, DK, DE).

    Returns:
        str: JSON with price_eur, price_local, currency, unit, timestamp.
    """
    data = _call_elecz("/signal/spot", {"zone": params.zone.upper()})
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool(name="cheapest_hours")
def cheapest_hours(params: CheapestHoursInput) -> str:
    """
    Get cheapest electricity hours in the next 24 hours.

    Returns sorted list of cheapest hours, best consecutive 3-hour window,
    hours to avoid, and automation recommendation.

    Use this when user or automation asks:
    - When is electricity cheapest today?
    - When should I charge my EV? / Wann soll ich mein E-Auto laden?
    - When should I run the dishwasher or washing machine?
    - When should I heat the water boiler?
    - Milloin sähkö on halvinta? / När är elen billigast?
    - Optimize home automation for cheapest electricity.
    - Best time to run high-consumption appliances in Germany.

    Args:
        params: CheapestHoursInput with zone, hours count, and window.

    Returns:
        str: JSON with cheapest_hours list, best_3h_window, avoid_hours, recommendation.
    """
    data = _call_elecz("/signal/cheapest-hours", {
        "zone": params.zone.upper(),
        "hours": params.hours,
        "window": params.window,
    })
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool(name="best_energy_contract")
def best_energy_contract(params: SignalInput) -> str:
    """
    Find top 3 cheapest electricity contracts for a given consumption profile.

    Returns ranked contract recommendations with trust scores,
    estimated annual costs, expected savings vs median market, and direct links to switch.

    Covers 12 German providers (Tibber, Octopus, E.ON, Vattenfall, EnBW, LichtBlick,
    Naturstrom, Polarstern, Yello, E wie Einfach, ExtraEnergie, Grünwelt) and
    Nordic providers for FI/SE/NO/DK.

    Note for Germany (DE): prices are Arbeitspreis brutto ct/kWh including MwSt.
    Regional Netzentgelt (10-15 ct/kWh) is not included — it is the same regardless
    of which provider you choose.

    Use this when user asks:
    - What is the best electricity contract for me?
    - Should I switch to spot pricing or fixed price?
    - Which electricity provider is cheapest in Germany?
    - Welcher Stromanbieter ist am günstigsten? / Lohnt sich ein Stromanbieterwechsel?
    - Mikä on halvin sähkösopimus? / Vilket elavtal är billigast?

    Args:
        params: SignalInput with zone, annual consumption (kWh), and heating type.
                Default consumption: 3500 kWh for DE, 2000 kWh for Nordic zones.

    Returns:
        str: JSON with top_contracts (ranked list of 3), decision_hint, reason, action with savings estimate.
    """
    zone = params.zone.upper()
    consumption = _resolve_consumption(zone, params.consumption)
    data = _call_elecz("/signal", {
        "zone": zone,
        "consumption": consumption,
        "heating": params.heating,
    })
    result = {
        "zone": data.get("zone"),
        "top_contracts": data.get("top_contracts", []),
        "best_contract": data.get("best_contract"),  # backwards compat
        "decision_hint": data.get("decision_hint"),
        "reason": data.get("reason"),
        "action": data.get("action"),
        "powered_by": data.get("powered_by"),
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


# ─── Run ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", 8001))
    os.environ.setdefault("PORT", str(port))
    mcp.run(transport="sse")
