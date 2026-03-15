"""
Elecz - Energy Decision Signal API
Real-time spot prices + cheapest hours + contract recommendations
MCP-compatible signal endpoint for AI agents and automation
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, request, redirect, render_template_string
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler
import google.generativeai as genai
import redis

# ─── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Constants ─────────────────────────────────────────────────────────────
ENTSOE_API_URL      = "https://web-api.tp.entsoe.eu/api"
FRANKFURTER_URL     = "https://api.frankfurter.app/latest"
REDIS_TTL_SPOT      = 3600    # 1 hour
REDIS_TTL_CONTRACTS = 86400   # 24 hours
REDIS_TTL_FX        = 86400   # 24 hours

PROVIDER_URLS = {
    "FI": {
        "tibber":              "https://tibber.com/fi/sahkosopimus",
        "helen":               "https://www.helen.fi/sahko/sopimukset",
        "fortum":              "https://www.fortum.fi/sahkosopimukset",
        "vattenfall":          "https://www.vattenfall.fi/sahko",
        "oomi":                "https://oomi.fi/sahkosopimus",
        "nordic_green_energy": "https://www.nordicgreenenergy.com/fi",
        "vare":                "https://www.vare.fi/sahkosopimus",
        "cheap_energy":        "https://www.cheapenergy.fi",
    },
    "SE": {
        "tibber":     "https://tibber.com/se/elpris",
        "fortum":     "https://www.fortum.se/elavtal",
        "vattenfall": "https://www.vattenfall.se/elavtal",
        "eon":        "https://www.eon.se/elavtal",
        "skekraft":   "https://www.skekraft.se/el/elavtal",
        "greenely":   "https://www.greenely.se/elavtal",
        "godel":      "https://www.godel.se/elavtal",
        "gotaenergi": "https://www.gotaenergi.se/elavtal",
    },
    "NO": {
        "tibber":      "https://tibber.com/no/strom",
        "fjordkraft":  "https://www.fjordkraft.no/strom",
        "kildenkraft": "https://www.kildenkraft.no",
        "kraftriket":  "https://www.kraftriket.no",
        "astrom":      "https://www.astrom.no",
        "nte":         "https://www.nte.no/strom",
        "lyse":        "https://www.lyse.no/strom",
    },
    "DK": {
        "tibber":       "https://tibber.com/dk/el",
        "norlys":       "https://www.norlys.dk/el",
        "ok":           "https://www.ok.dk/el",
        "modstrom":     "https://www.modstrom.dk",
        "ewii":         "https://www.ewii.dk/el",
        "vindstod":     "https://www.vindstod.dk",
        "nettopower":   "https://www.nettopower.dk",
        "cheap_energy": "https://www.cheapenergy.dk",
    },
}

PROVIDER_DIRECT_URLS = {
    "FI": {
        "tibber":              "https://tibber.com/fi",
        "helen":               "https://www.helen.fi/sahko/sopimukset",
        "fortum":              "https://www.fortum.fi/sahkosopimukset",
        "vattenfall":          "https://www.vattenfall.fi/sahko/sahkosopimus",
        "oomi":                "https://oomi.fi/sahkosopimus",
        "nordic_green_energy": "https://www.nordicgreenenergy.com/fi/sahkosopimus",
        "vare":                "https://www.vare.fi/sahkosopimus",
        "cheap_energy":        "https://www.cheapenergy.fi",
    },
    "SE": {
        "tibber":     "https://tibber.com/se",
        "fortum":     "https://www.fortum.se/elavtal",
        "vattenfall": "https://www.vattenfall.se/elavtal",
        "eon":        "https://www.eon.se/elavtal",
        "skekraft":   "https://www.skekraft.se/el/elavtal",
        "greenely":   "https://www.greenely.se/elavtal",
        "godel":      "https://www.godel.se/elavtal",
        "gotaenergi": "https://www.gotaenergi.se/elavtal",
    },
    "NO": {
        "tibber":      "https://tibber.com/no",
        "fjordkraft":  "https://www.fjordkraft.no/strom",
        "kildenkraft": "https://www.kildenkraft.no",
        "kraftriket":  "https://www.kraftriket.no",
        "astrom":      "https://www.astrom.no",
        "nte":         "https://www.nte.no/strom",
        "lyse":        "https://www.lyse.no/strom",
    },
    "DK": {
        "tibber":       "https://tibber.com/dk",
        "norlys":       "https://www.norlys.dk/el",
        "ok":           "https://www.ok.dk/el",
        "modstrom":     "https://www.modstrom.dk",
        "ewii":         "https://www.ewii.dk/el",
        "vindstod":     "https://www.vindstod.dk",
        "nettopower":   "https://www.nettopower.dk",
        "cheap_energy": "https://www.cheapenergy.dk",
    },
}

ZONES = {
    "FI":  "10YFI-1--------U",
    "SE":  "10Y1001A1001A46L",  # SE3 Stockholm default
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
    "NO":  "10YNO-1--------2",  # NO1 Oslo default
    "NO1": "10YNO-1--------2",
    "NO2": "10YNO-2--------T",
    "NO3": "10YNO-3--------J",
    "NO4": "10YNO-4--------9",
    "NO5": "10Y1001A1001A48H",
    "DK":  "10YDK-1--------W",  # DK1 default
    "DK1": "10YDK-1--------W",
    "DK2": "10YDK-2--------M",
}

ZONE_CURRENCY = {
    "FI": "EUR",
    "SE": "SEK", "SE1": "SEK", "SE2": "SEK", "SE3": "SEK", "SE4": "SEK",
    "NO": "NOK", "NO1": "NOK", "NO2": "NOK", "NO3": "NOK", "NO4": "NOK", "NO5": "NOK",
    "DK": "DKK", "DK1": "DKK", "DK2": "DKK",
}

# ─── App init ──────────────────────────────────────────────────────────────
app = Flask(__name__)

supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)
redis_client = redis.from_url(os.environ["UPSTASH_REDIS_URL"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
gemini_model  = genai.GenerativeModel("gemini-2.5-flash")
ENTSOE_TOKEN  = os.environ["ENTSOE_SECURITY_TOKEN"]


# ─── ENTSO-E helpers ───────────────────────────────────────────────────────

def _parse_entsoe_xml(xml_text: str) -> list[dict]:
    """Parse ENTSO-E XML into list of {hour, price_eur_mwh}."""
    root   = ET.fromstring(xml_text)
    ns     = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}
    rows   = []
    for ts in root.findall(".//ns:TimeSeries", ns):
        start_str = ts.find(".//ns:timeInterval/ns:start", ns)
        if start_str is None:
            continue
        start = datetime.fromisoformat(start_str.text.replace("Z", "+00:00"))
        for point in ts.findall(".//ns:Point", ns):
            pos   = int(point.find("ns:position", ns).text)
            price = float(point.find("ns:price.amount", ns).text)
            hour  = start + timedelta(hours=pos - 1)
            rows.append({"hour": hour, "price_eur_mwh": price})
    return rows


def fetch_day_ahead(zone: str, date: datetime) -> list[dict]:
    """Fetch full day-ahead price series from ENTSO-E."""
    zone_code = ZONES.get(zone)
    if not zone_code:
        return []
    period_start = date.strftime("%Y%m%d0000")
    period_end   = date.strftime("%Y%m%d2300")
    params = {
        "securityToken": ENTSOE_TOKEN,
        "documentType":  "A44",
        "in_Domain":     zone_code,
        "out_Domain":    zone_code,
        "periodStart":   period_start,
        "periodEnd":     period_end,
    }
    try:
        resp = httpx.get(ENTSOE_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        return _parse_entsoe_xml(resp.text)
    except Exception as e:
        logger.error(f"ENTSO-E day-ahead failed zone={zone}: {e}")
        return []


def get_spot_price(zone: str = "FI") -> Optional[float]:
    """Current spot price c/kWh from Redis or ENTSO-E."""
    key    = f"elecz:spot:{zone}"
    cached = redis_client.get(key)
    if cached:
        return float(cached)
    now   = datetime.now(timezone.utc)
    rows  = fetch_day_ahead(zone, now)
    if not rows:
        return None
    # Find current hour
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    for r in rows:
        if r["hour"].replace(tzinfo=timezone.utc) == current_hour:
            price = round(r["price_eur_mwh"] / 10, 4)
            redis_client.setex(key, REDIS_TTL_SPOT, str(price))
            return price
    return None


def save_day_ahead_to_supabase(zone: str, rows: list[dict]):
    """Save full day-ahead series to Supabase prices_day_ahead table."""
    records = []
    for r in rows:
        records.append({
            "zone":          zone,
            "hour":          r["hour"].isoformat(),
            "price_eur_mwh": r["price_eur_mwh"],
            "price_ckwh":    round(r["price_eur_mwh"] / 10, 4),
            "source":        "ENTSO-E",
            "created_at":    datetime.now(timezone.utc).isoformat(),
        })
    if records:
        try:
            supabase.table("prices_day_ahead").upsert(records).execute()
        except Exception as e:
            logger.error(f"Supabase prices save failed zone={zone}: {e}")


# ─── Frankfurter ───────────────────────────────────────────────────────────

def get_exchange_rate(currency: str) -> float:
    """EUR → local currency rate. Cached 24h."""
    if currency == "EUR":
        return 1.0
    key    = f"elecz:fx:{currency}"
    cached = redis_client.get(key)
    if cached:
        return float(cached)
    try:
        resp = httpx.get(FRANKFURTER_URL, params={"from": "EUR", "to": currency}, timeout=5)
        resp.raise_for_status()
        rate = resp.json()["rates"][currency]
        redis_client.setex(key, REDIS_TTL_FX, str(rate))
        return rate
    except Exception as e:
        logger.error(f"Frankfurter failed {currency}: {e}")
        return 1.0


def convert_price(price_eur: Optional[float], currency: str) -> Optional[float]:
    if price_eur is None or currency == "EUR":
        return price_eur
    return round(price_eur * get_exchange_rate(currency), 4)


# ─── Cheapest hours logic ──────────────────────────────────────────────────

def get_cheapest_hours(zone: str, n_hours: int = 5, window_h: int = 24) -> dict:
    """
    Return cheapest hours in next window_h hours.
    Data from Supabase prices_day_ahead table.
    """
    now     = datetime.now(timezone.utc)
    cutoff  = now + timedelta(hours=window_h)
    currency = ZONE_CURRENCY.get(zone, "EUR")

    try:
        result = supabase.table("prices_day_ahead").select(
            "hour, price_ckwh"
        ).eq("zone", zone).gte("hour", now.isoformat()).lte(
            "hour", cutoff.isoformat()
        ).order("price_ckwh").execute()

        rows = result.data or []
    except Exception as e:
        logger.error(f"Cheapest hours DB failed: {e}")
        rows = []

    if not rows:
        return {"available": False, "reason": "No price data yet. ENTSO-E token pending."}

    cheapest = rows[:n_hours]
    all_prices = [r["price_ckwh"] for r in rows]
    avg = sum(all_prices) / len(all_prices) if all_prices else 0

    # Best consecutive window (3h default)
    best_window = _best_consecutive_window(rows, 3)

    # Energy state
    current_price = get_spot_price(zone) or avg
    if current_price < avg * 0.7:
        energy_state = "cheap"
        confidence   = 0.90
    elif current_price > avg * 1.3:
        energy_state = "expensive"
        confidence   = 0.88
    else:
        energy_state = "normal"
        confidence   = 0.75

    return {
        "available":     True,
        "zone":          zone,
        "currency":      currency,
        "energy_state":  energy_state,
        "confidence":    confidence,
        "cheapest_hours": [
            {
                "hour":      r["hour"][:16],
                "price_eur": r["price_ckwh"],
                "price_local": convert_price(r["price_ckwh"], currency),
            }
            for r in cheapest
        ],
        "best_3h_window": best_window,
        "avoid_hours":   _expensive_hours(rows, avg),
        "recommendation": _consumption_recommendation(energy_state),
        "powered_by":    "Elecz.com",
    }


def _best_consecutive_window(rows: list, window: int) -> Optional[dict]:
    """Find best consecutive N-hour window by average price."""
    if len(rows) < window:
        return None
    best_avg  = float("inf")
    best_start = None
    for i in range(len(rows) - window + 1):
        avg = sum(r["price_ckwh"] for r in rows[i:i+window]) / window
        if avg < best_avg:
            best_avg   = avg
            best_start = rows[i]["hour"][:16]
            best_end   = rows[i+window-1]["hour"][:16]
    return {"start": best_start, "end": best_end, "avg_price_eur": round(best_avg, 4)}


def _expensive_hours(rows: list, avg: float) -> list[str]:
    """Hours more than 30% above average."""
    return [r["hour"][:16] for r in rows if r["price_ckwh"] > avg * 1.3][:6]


def _consumption_recommendation(state: str) -> str:
    if state == "cheap":
        return "run_high_consumption_tasks"
    if state == "expensive":
        return "avoid_high_consumption"
    return "normal_usage"


# ─── Contract scraping ─────────────────────────────────────────────────────

def scrape_provider(provider: str, url: str, zone: str) -> Optional[dict]:
    """Gemini scrapes contract pricing from provider website."""
    prompt = f"""
Visit this electricity provider page: {url}
Country/zone: {zone}

Extract pricing and return ONLY a valid JSON object:
{{
  "provider": "{provider}",
  "zone": "{zone}",
  "spot_margin_ckwh": <float or null>,
  "basic_fee_eur_month": <float or null>,
  "fixed_price_ckwh": <float or null>,
  "contract_type": "spot" | "fixed" | "fixed_term",
  "contract_duration_months": <int or null>,
  "new_customers_only": <bool>,
  "below_wholesale": <bool>,
  "scraped_at": "{datetime.now(timezone.utc).isoformat()}"
}}

Return ONLY the JSON object. No markdown, no explanation.
"""
    try:
        response = gemini_model.generate_content(prompt)
        text = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(text)
    except Exception as e:
        logger.error(f"Gemini scrape failed {zone}/{provider}: {e}")
        return None


def update_contract_prices():
    """Scheduled 02:00 — scrape all providers."""
    logger.info("Updating contract prices...")
    for zone, providers in PROVIDER_URLS.items():
        for provider, url in providers.items():
            data = scrape_provider(provider, url, zone)
            if data:
                try:
                    supabase.table("contracts").upsert({
                        **data,
                        "direct_url":    PROVIDER_DIRECT_URLS.get(zone, {}).get(provider),
                        "affiliate_url": None,
                        "updated_at":    datetime.now(timezone.utc).isoformat(),
                    }).execute()
                    logger.info(f"  ✓ {zone}/{provider}")
                except Exception as e:
                    logger.error(f"  ✗ {zone}/{provider}: {e}")
        redis_client.delete(f"elecz:contracts:{zone}")
    logger.info("Contract update complete.")


def update_spot_prices():
    """Scheduled hourly — refresh spot + save day-ahead."""
    for zone in ["FI", "SE", "NO", "DK"]:
        redis_client.delete(f"elecz:spot:{zone}")
        now  = datetime.now(timezone.utc)
        rows = fetch_day_ahead(zone, now)
        if rows:
            save_day_ahead_to_supabase(zone, rows)
            # Also save tomorrow if available (published ~13:15)
            tomorrow = now + timedelta(days=1)
            rows_tomorrow = fetch_day_ahead(zone, tomorrow)
            if rows_tomorrow:
                save_day_ahead_to_supabase(zone, rows_tomorrow)
        get_spot_price(zone)
    logger.info("Spot prices refreshed.")


# ─── Contracts cache ───────────────────────────────────────────────────────

def get_contracts(zone: str) -> list:
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


# ─── Signal logic ──────────────────────────────────────────────────────────

def trust_score(contract: dict) -> int:
    score = 100
    if contract.get("below_wholesale"):    score -= 30
    if contract.get("new_customers_only"): score -= 20
    if contract.get("has_prepayment"):     score -= 15
    if contract.get("data_errors"):        score -= 10
    return max(0, score)


def decision_hint(spot: float, contract: dict, consumption: int, heating: str) -> dict:
    if consumption <= 2000 and heating == "district":
        return {"hint": "spot_recommended", "reason": "Low consumption: minimize basic fee. Spot is cheapest long-term."}
    if consumption >= 15000:
        if spot < 5.0:
            return {"hint": "stay_spot",      "reason": "High consumption + low spot. Spot is cheapest now."}
        else:
            return {"hint": "consider_fixed", "reason": "High consumption + elevated spot. Fixed offers price certainty."}
    return {"hint": "compare_options", "reason": "Compare spot margin + basic fee vs fixed price for your consumption."}


def build_signal(zone: str, consumption: int, postcode: str, heating: str) -> dict:
    spot      = get_spot_price(zone)
    contracts = get_contracts(zone)
    currency  = ZONE_CURRENCY.get(zone, "EUR")
    spot_local = convert_price(spot, currency)

    ranked = []
    for c in contracts:
        ts    = trust_score(c)
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

    # Confidence based on data freshness
    confidence = 0.95 if spot else 0.0

    # Energy state
    if spot:
        if spot < 3.0:   energy_state = "cheap"
        elif spot > 8.0: energy_state = "expensive"
        else:            energy_state = "normal"
    else:
        energy_state = "unknown"

    return {
        "signal":       "elecz",
        "version":      "1.1",
        "zone":         zone,
        "currency":     currency,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "energy_state": energy_state,
        "confidence":   confidence,
        "spot_price": {
            "eur":   spot,
            "local": spot_local,
            "unit":  f"c/kWh",
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

@app.route("/")
def index():
    """Landing page — developer docs + live spot price."""
    spot_fi = get_spot_price("FI")
    spot_se = get_spot_price("SE")
    spot_no = get_spot_price("NO")
    spot_dk = get_spot_price("DK")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>⚡ Elecz.com — Energy Signal API</title>
  <style>
    body {{ font-family: monospace; background: #0a0a0a; color: #e0e0e0; max-width: 800px; margin: 40px auto; padding: 20px; }}
    h1 {{ color: #f0c040; font-size: 2em; margin-bottom: 4px; }}
    h2 {{ color: #80c0ff; margin-top: 40px; }}
    .price {{ font-size: 1.4em; color: #40ff80; }}
    .null {{ color: #666; }}
    table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
    td, th {{ padding: 10px; border: 1px solid #333; text-align: left; }}
    th {{ color: #80c0ff; }}
    code {{ background: #1a1a1a; padding: 2px 6px; border-radius: 4px; color: #f0c040; }}
    pre {{ background: #1a1a1a; padding: 16px; border-radius: 8px; overflow-x: auto; color: #80ff80; }}
    .badge {{ background: #1a3a1a; color: #40ff80; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }}
  </style>
</head>
<body>
  <h1>⚡ Elecz.com</h1>
  <p>Real-time energy decision signal for AI agents and automation.</p>
  <span class="badge">LIVE</span>

  <h2>Nordic Spot Prices — Now</h2>
  <table>
    <tr><th>Zone</th><th>Price (c/kWh EUR)</th><th>Status</th></tr>
    <tr><td>🇫🇮 Finland (FI)</td><td class="price">{f'{spot_fi:.4f}' if spot_fi else '<span class="null">pending token</span>'}</td><td>{'✅' if spot_fi else '⏳'}</td></tr>
    <tr><td>🇸🇪 Sweden (SE)</td><td class="price">{f'{spot_se:.4f}' if spot_se else '<span class="null">pending token</span>'}</td><td>{'✅' if spot_se else '⏳'}</td></tr>
    <tr><td>🇳🇴 Norway (NO)</td><td class="price">{f'{spot_no:.4f}' if spot_no else '<span class="null">pending token</span>'}</td><td>{'✅' if spot_no else '⏳'}</td></tr>
    <tr><td>🇩🇰 Denmark (DK)</td><td class="price">{f'{spot_dk:.4f}' if spot_dk else '<span class="null">pending token</span>'}</td><td>{'✅' if spot_dk else '⏳'}</td></tr>
  </table>

  <h2>API Endpoints</h2>
  <table>
    <tr><th>Endpoint</th><th>Description</th></tr>
    <tr><td><code>GET /signal?zone=FI</code></td><td>Full energy decision signal — spot + best contract + hint</td></tr>
    <tr><td><code>GET /signal/spot?zone=FI</code></td><td>Current spot price only</td></tr>
    <tr><td><code>GET /signal/cheapest-hours?zone=FI&hours=5</code></td><td>Cheapest hours next 24h — for automation</td></tr>
    <tr><td><code>GET /go/&lt;provider&gt;</code></td><td>Redirect to provider + analytics</td></tr>
    <tr><td><code>GET /mcp</code></td><td>MCP tool manifest</td></tr>
    <tr><td><code>GET /health</code></td><td>Health check</td></tr>
  </table>

  <h2>Example Response — /signal/cheapest-hours?zone=FI&hours=3</h2>
  <pre>{{
  "energy_state": "cheap",
  "confidence": 0.90,
  "cheapest_hours": [
    {{"hour": "2026-03-16T03:00", "price_eur": 2.1}},
    {{"hour": "2026-03-16T04:00", "price_eur": 2.3}}
  ],
  "best_3h_window": {{
    "start": "2026-03-16T02:00",
    "end":   "2026-03-16T04:00",
    "avg_price_eur": 2.2
  }},
  "recommendation": "run_high_consumption_tasks",
  "powered_by": "Elecz.com"
}}</pre>

  <h2>MCP Integration</h2>
  <p>Add to your AI agent config:</p>
  <pre>{{
  "mcpServers": {{
    "elecz": {{
      "url": "https://elecz.com/mcp"
    }}
  }}
}}</pre>

  <p style="color:#555; margin-top:60px; font-size:0.8em;">
    ⚡ Elecz.com — Energy Decision Signal API · Powered by ENTSO-E · Nordic markets
  </p>
</body>
</html>"""
    return html


@app.route("/signal", methods=["GET"])
def signal():
    """Full energy decision signal."""
    zone        = request.args.get("zone", "FI").upper()
    consumption = int(request.args.get("consumption", 2000))
    postcode    = request.args.get("postcode", "00100")
    heating     = request.args.get("heating", "district")
    if zone not in ZONES:
        return jsonify({"error": f"Invalid zone. Valid: {list(ZONES.keys())}"}), 400
    return jsonify(build_signal(zone, consumption, postcode, heating))


@app.route("/signal/spot", methods=["GET"])
def signal_spot():
    """Current spot price only."""
    zone     = request.args.get("zone", "FI").upper()
    price    = get_spot_price(zone)
    currency = ZONE_CURRENCY.get(zone, "EUR")
    return jsonify({
        "signal":     "elecz_spot",
        "zone":       zone,
        "currency":   currency,
        "price_eur":  price,
        "price_local": convert_price(price, currency),
        "unit":       "c/kWh",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "powered_by": "Elecz.com",
    })


@app.route("/signal/cheapest-hours", methods=["GET"])
def signal_cheapest_hours():
    """
    Cheapest hours in next N hours — for home automation and EV charging.
    ?zone=FI&hours=5&window=24
    """
    zone   = request.args.get("zone", "FI").upper()
    hours  = int(request.args.get("hours", 5))
    window = int(request.args.get("window", 24))
    if zone not in ZONES:
        return jsonify({"error": f"Invalid zone. Valid: {list(ZONES.keys())}"}), 400
    return jsonify(get_cheapest_hours(zone, hours, window))


@app.route("/go/<provider>", methods=["GET"])
def go(provider: str):
    """Redirect to provider + log click."""
    try:
        result   = supabase.table("contracts").select(
            "provider, affiliate_url, direct_url"
        ).eq("provider", provider).single().execute()
        contract = result.data
        url      = contract.get("affiliate_url") or contract.get("direct_url")
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
    return jsonify({"status": "ok", "service": "elecz", "version": "1.1"})


@app.route("/mcp", methods=["GET"])
def mcp_manifest():
    """MCP tool manifest for Smithery / Glama."""
    return jsonify({
        "name":        "elecz_mcp",
        "description": "Real-time energy decision signal for Nordic electricity markets. Provides spot prices, cheapest hours for automation, and best contract recommendations.",
        "version":     "1.1.0",
        "tools": [
            {
                "name":        "energy_decision_signal",
                "description": "Get full energy decision signal: spot price, best contract, and recommendation for a Nordic zone.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "zone":        {"type": "string", "enum": list(ZONES.keys()), "description": "Bidding zone e.g. FI, SE, NO, DK"},
                        "consumption": {"type": "integer", "description": "Annual consumption kWh (default 2000)"},
                        "heating":     {"type": "string",  "enum": ["district", "electric"]},
                    },
                    "required": ["zone"],
                },
                "endpoint": "/signal",
                "method":   "GET",
            },
            {
                "name":        "best_energy_contract",
                "description": "Get cheapest and most reliable electricity contract for a zone and consumption profile.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "zone":        {"type": "string", "enum": list(ZONES.keys())},
                        "consumption": {"type": "integer"},
                    },
                    "required": ["zone"],
                },
                "endpoint": "/signal",
                "method":   "GET",
            },
            {
                "name":        "cheapest_hours",
                "description": "Get cheapest electricity hours in next 24h. Use for EV charging, home automation, heat pumps.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "zone":   {"type": "string", "enum": list(ZONES.keys())},
                        "hours":  {"type": "integer", "description": "Number of cheapest hours to return (default 5)"},
                        "window": {"type": "integer", "description": "Hours to look ahead (default 24)"},
                    },
                    "required": ["zone"],
                },
                "endpoint": "/signal/cheapest-hours",
                "method":   "GET",
            },
            {
                "name":        "spot_price",
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
scheduler.add_job(update_spot_prices,     "cron", minute=5)
scheduler.add_job(update_contract_prices, "cron", hour=2)
scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
