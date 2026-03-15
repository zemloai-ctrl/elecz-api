"""
Elecz - Energy Signal API
Spot prices via ENTSO-E + contract prices via Gemini scraping
MCP-compatible signal endpoint for AI agents
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional
import httpx
from flask import Flask, jsonify, request, redirect
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler
import google.generativeai as genai
import redis

# ─── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Constants ─────────────────────────────────────────────────────────────
ENTSOE_API_URL     = "https://web-api.tp.entsoe.eu/api"
REDIS_TTL_SPOT     = 3600    # 1 hour
REDIS_TTL_CONTRACTS = 86400  # 24 hours

PROVIDER_URLS = {
    "tibber":              "https://tibber.com/fi/sahkosopimus",
    "helen":               "https://www.helen.fi/sahko/sopimukset",
    "fortum":              "https://www.fortum.fi/sahkosopimukset",
    "vattenfall":          "https://www.vattenfall.fi/sahko",
    "oomi":                "https://oomi.fi/sahkosopimus",
    "nordic_green_energy": "https://www.nordicgreenenergy.com/fi",
    "vare":                "https://www.vare.fi/sahkosopimus",
    "cheap_energy":        "https://www.cheapenergy.fi",
}

PROVIDER_DIRECT_URLS = {
    "tibber":              "https://tibber.com/fi",
    "helen":               "https://www.helen.fi/sahko/sopimukset",
    "fortum":              "https://www.fortum.fi/sahkosopimukset",
    "vattenfall":          "https://www.vattenfall.fi/sahko/sahkosopimus",
    "oomi":                "https://oomi.fi/sahkosopimus",
    "nordic_green_energy": "https://www.nordicgreenenergy.com/fi/sahkosopimus",
    "vare":                "https://www.vare.fi/sahkosopimus",
    "cheap_energy":        "https://www.cheapenergy.fi",
}

ZONES = {
    "FI": "10YFI-1--------U",
    "SE": "10YSE-1--------K",
    "NO": "10YNO-0--------C",
    "DK": "10Y1001A1001A65H",
}

# ─── App init ──────────────────────────────────────────────────────────────
app = Flask(__name__)

supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

redis_client = redis.from_url(os.environ["UPSTASH_REDIS_URL"])

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
gemini_model = genai.GenerativeModel("gemini-2.5-flash")

ENTSOE_TOKEN = os.environ["ENTSOE_SECURITY_TOKEN"]


# ─── ENTSO-E ───────────────────────────────────────────────────────────────

def fetch_spot_price_sync(zone: str = "FI") -> Optional[float]:
    """Fetch current spot price from ENTSO-E. Returns c/kWh."""
    zone_code = ZONES.get(zone)
    if not zone_code:
        return None

    now          = datetime.now(timezone.utc)
    period_start = now.strftime("%Y%m%d%H00")
    period_end   = now.strftime("%Y%m%d%H59")

    params = {
        "securityToken": ENTSOE_TOKEN,
        "documentType":  "A44",
        "in_Domain":     zone_code,
        "out_Domain":    zone_code,
        "periodStart":   period_start,
        "periodEnd":     period_end,
    }

    try:
        resp = httpx.get(ENTSOE_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root      = ET.fromstring(resp.text)
        ns        = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}
        price_mwh = float(root.find(".//ns:price.amount", ns).text)
        return round(price_mwh / 10, 4)   # EUR/MWh → c/kWh
    except Exception as e:
        logger.error(f"ENTSO-E fetch failed zone={zone}: {e}")
        return None


def get_spot_price(zone: str = "FI") -> Optional[float]:
    """Get spot price from Redis cache or ENTSO-E."""
    key    = f"elecz:spot:{zone}"
    cached = redis_client.get(key)
    if cached:
        return float(cached)
    price = fetch_spot_price_sync(zone)
    if price is not None:
        redis_client.setex(key, REDIS_TTL_SPOT, str(price))
    return price


# ─── Gemini scraper ────────────────────────────────────────────────────────

def scrape_provider(provider: str, url: str) -> Optional[dict]:
    """Use Gemini to extract pricing from provider website."""
    prompt = f"""
Go to this Finnish electricity provider page: {url}

Extract pricing and return ONLY a JSON object:
{{
  "provider": "{provider}",
  "zone": "FI",
  "spot_margin_ckwh": <float or null>,
  "basic_fee_eur_month": <float or null>,
  "fixed_price_ckwh": <float or null>,
  "contract_type": "spot" | "fixed" | "fixed_term",
  "contract_duration_months": <int or null>,
  "new_customers_only": <bool>,
  "below_wholesale": <bool>,
  "scraped_at": "{datetime.now(timezone.utc).isoformat()}"
}}

Return ONLY valid JSON, no markdown, no explanation.
"""
    try:
        response = gemini_model.generate_content(prompt)
        text = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(text)
    except Exception as e:
        logger.error(f"Gemini scrape failed {provider}: {e}")
        return None


def update_contract_prices():
    """Scheduled: scrape all providers → Supabase."""
    logger.info("Updating contract prices...")
    for provider, url in PROVIDER_URLS.items():
        data = scrape_provider(provider, url)
        if data:
            try:
                supabase.table("contracts").upsert({
                    **data,
                    "direct_url":    PROVIDER_DIRECT_URLS.get(provider),
                    "affiliate_url": None,
                    "updated_at":    datetime.now(timezone.utc).isoformat(),
                }).execute()
                logger.info(f"  ✓ {provider}")
            except Exception as e:
                logger.error(f"  ✗ {provider}: {e}")
    redis_client.delete("elecz:contracts:FI")
    logger.info("Contract update complete.")


def update_spot_prices():
    """Scheduled: refresh spot prices for all zones."""
    for zone in ZONES:
        redis_client.delete(f"elecz:spot:{zone}")
        get_spot_price(zone)
    logger.info("Spot prices refreshed.")


# ─── Signal logic ──────────────────────────────────────────────────────────

def get_contracts(zone: str = "FI") -> list:
    """Get contracts from Redis or Supabase."""
    key    = f"elecz:contracts:{zone}"
    cached = redis_client.get(key)
    if cached:
        return json.loads(cached)
    try:
        result    = supabase.table("contracts").select("*").eq("zone", zone).execute()
        contracts = result.data or []
        redis_client.setex(key, REDIS_TTL_CONTRACTS, json.dumps(contracts))
        return contracts
    except Exception as e:
        logger.error(f"Contracts fetch failed zone={zone}: {e}")
        return []


def trust_score(contract: dict) -> int:
    """Score 0–100. Penalise warning flags."""
    score = 100
    if contract.get("below_wholesale"):    score -= 30
    if contract.get("new_customers_only"): score -= 20
    if contract.get("has_prepayment"):     score -= 15
    if contract.get("data_errors"):        score -= 10
    return max(0, score)


def decision_hint(spot: float, contract: dict, consumption: int, heating: str) -> dict:
    """Plain-language recommendation based on user profile."""
    ctype = contract.get("contract_type", "spot")

    if consumption <= 2000 and heating == "district":
        return {
            "hint":   "spot_recommended",
            "reason": "Pienellä kulutuksella tärkeintä on pieni perusmaksu. Pörssisähkö on pitkällä aikavälillä halvin.",
        }
    if consumption >= 15000:
        if spot < 5.0:
            return {"hint": "stay_spot",       "reason": "Suuri kulutus + matala spot-hinta. Pörssisähkö kannattaa nyt."}
        else:
            return {"hint": "consider_fixed",  "reason": "Suuri kulutus + korkea spot-hinta. Kiinteä sopimus tarjoaa hintatakuun."}

    return {"hint": "compare_options", "reason": "Vertaa marginaalia + perusmaksua vs. kiinteä hinta omalla kulutuksellasi."}


def build_signal(zone: str, consumption: int, postcode: str, heating: str) -> dict:
    """Build the full Elecz MCP payload."""
    spot      = get_spot_price(zone)
    contracts = get_contracts(zone)

    # Rank by estimated annual cost, then trust score
    ranked = []
    for c in contracts:
        ts     = trust_score(c)
        margin = c.get("spot_margin_ckwh") or 0
        fee    = c.get("basic_fee_eur_month") or 0
        fixed  = c.get("fixed_price_ckwh")

        if fixed:
            annual = (fixed / 100) * consumption + fee * 12
        elif spot:
            annual = ((spot + margin) / 100) * consumption + fee * 12
        else:
            annual = None

        ranked.append({**c, "trust_score": ts, "annual_cost_estimate": round(annual, 2) if annual else None})

    ranked.sort(key=lambda x: (x["annual_cost_estimate"] or 9999, -x["trust_score"]))
    best = ranked[0] if ranked else None

    hint       = decision_hint(spot or 0, best or {}, consumption, heating) if best else {}
    action_url = f"https://elecz.com/go/{best['provider']}" if best else None

    return {
        "signal":    "elecz",
        "version":   "1.0",
        "zone":      zone,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spot_price": {
            "now":  spot,
            "unit": "c/kWh",
        },
        "best_contract": {
            "provider":             best.get("provider")             if best else None,
            "type":                 best.get("contract_type")        if best else None,
            "spot_margin_ckwh":     best.get("spot_margin_ckwh")     if best else None,
            "basic_fee_eur_month":  best.get("basic_fee_eur_month")  if best else None,
            "annual_cost_estimate": best.get("annual_cost_estimate") if best else None,
            "trust_score":          best.get("trust_score")          if best else None,
        } if best else None,
        "decision_hint": hint.get("hint"),
        "reason":        hint.get("reason"),
        "action": {
            "available":   bool(action_url),
            "action_link": action_url,
            "status":      "direct",
        },
        "powered_by": "Elecz.com",
    }


# ─── Routes ────────────────────────────────────────────────────────────────

@app.route("/signal", methods=["GET"])
def signal():
    """
    Main MCP signal endpoint.
    ?zone=FI&consumption=2000&postcode=00100&heating=district
    """
    zone        = request.args.get("zone", "FI").upper()
    consumption = int(request.args.get("consumption", 2000))
    postcode    = request.args.get("postcode", "00100")
    heating     = request.args.get("heating", "district")

    if zone not in ZONES:
        return jsonify({"error": f"Invalid zone. Valid zones: {list(ZONES.keys())}"}), 400

    return jsonify(build_signal(zone, consumption, postcode, heating))


@app.route("/signal/spot", methods=["GET"])
def spot():
    """Quick spot price — no contract data needed."""
    zone  = request.args.get("zone", "FI").upper()
    price = get_spot_price(zone)
    return jsonify({
        "signal":     "elecz_spot",
        "zone":       zone,
        "price":      price,
        "unit":       "c/kWh",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "powered_by": "Elecz.com",
    })


@app.route("/go/<provider>", methods=["GET"])
def go(provider: str):
    """Redirect to provider + log click for analytics."""
    try:
        result   = supabase.table("contracts").select(
            "provider, affiliate_url, direct_url"
        ).eq("provider", provider).single().execute()
        contract = result.data
        url      = contract.get("affiliate_url") or contract.get("direct_url")

        # Log click
        supabase.table("clicks").insert({
            "provider":   provider,
            "zone":       request.args.get("zone", "FI"),
            "user_agent": request.headers.get("User-Agent"),
            "referrer":   request.referrer,
            "clicked_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        if url:
            return redirect(url, code=302)
    except Exception as e:
        logger.error(f"Redirect failed {provider}: {e}")

    return jsonify({"error": "Provider not found"}), 404


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "elecz", "version": "1.0"})


@app.route("/mcp", methods=["GET"])
def mcp_manifest():
    """MCP manifest for Smithery / Glama registration."""
    return jsonify({
        "name":        "elecz_mcp",
        "description": "Real-time electricity spot prices and best contract recommendations for Nordic countries.",
        "version":     "1.0.0",
        "tools": [
            {
                "name":        "elecz_get_signal",
                "description": "Get electricity spot price and best contract for a zone.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "zone":        {"type": "string", "enum": list(ZONES.keys())},
                        "consumption": {"type": "integer", "description": "Annual kWh"},
                        "postcode":    {"type": "string"},
                        "heating":     {"type": "string", "enum": ["district", "electric"]},
                    },
                    "required": ["zone"],
                },
                "endpoint": "/signal",
                "method":   "GET",
            },
            {
                "name":        "elecz_get_spot",
                "description": "Get current electricity spot price for a zone.",
                "inputSchema": {
                    "type":       "object",
                    "properties": {"zone": {"type": "string", "enum": list(ZONES.keys())}},
                    "required":   ["zone"],
                },
                "endpoint": "/signal/spot",
                "method":   "GET",
            },
        ],
    })


# ─── Scheduler ─────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone="Europe/Helsinki")
scheduler.add_job(update_spot_prices,     "cron", minute=5)   # Every hour at :05
scheduler.add_job(update_contract_prices, "cron", hour=2)     # Daily 02:00
scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
