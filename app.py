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
    """Current spot price c/kWh. Priority: Redis cache → ENTSO-E live → Supabase fallback."""
    key    = f"elecz:spot:{zone}"
    cached = redis_client.get(key)
    if cached:
        return float(cached)

    # Try ENTSO-E live
    now          = datetime.now(timezone.utc)
    rows         = fetch_day_ahead(zone, now)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    if rows:
        for r in rows:
            if r["hour"].replace(tzinfo=timezone.utc) == current_hour:
                price = round(r["price_eur_mwh"] / 10, 4)
                redis_client.setex(key, REDIS_TTL_SPOT, str(price))
                return price

    # Fallback: most recent known price from Supabase
    logger.warning(f"ENTSO-E unavailable for {zone} — falling back to Supabase")
    try:
        result = supabase.table("prices_day_ahead").select(
            "hour, price_ckwh"
        ).eq("zone", zone).lte(
            "hour", now.isoformat()
        ).order("hour", desc=True).limit(1).execute()
        rows_db = result.data or []
        if rows_db:
            price = rows_db[0]["price_ckwh"]
            # Cache briefly — stale data, refresh in 10 min
            redis_client.setex(key, 600, str(price))
            logger.info(f"Supabase fallback {zone}: {price} c/kWh (from {rows_db[0]['hour']})")
            return price
    except Exception as e:
        logger.error(f"Supabase fallback failed {zone}: {e}")

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
    """Return cheapest hours in next window_h hours."""
    now      = datetime.now(timezone.utc)
    cutoff   = now + timedelta(hours=window_h)
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

    cheapest   = rows[:n_hours]
    all_prices = [r["price_ckwh"] for r in rows]
    avg        = sum(all_prices) / len(all_prices) if all_prices else 0

    best_window   = _best_consecutive_window(rows, 3)
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
                "hour":        r["hour"][:16],
                "price_eur":   r["price_ckwh"],
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
    if len(rows) < window:
        return None
    best_avg   = float("inf")
    best_start = None
    for i in range(len(rows) - window + 1):
        avg = sum(r["price_ckwh"] for r in rows[i:i+window]) / window
        if avg < best_avg:
            best_avg   = avg
            best_start = rows[i]["hour"][:16]
            best_end   = rows[i+window-1]["hour"][:16]
    return {"start": best_start, "end": best_end, "avg_price_eur": round(best_avg, 4)}


def _expensive_hours(rows: list, avg: float) -> list[str]:
    return [r["hour"][:16] for r in rows if r["price_ckwh"] > avg * 1.3][:6]


def _consumption_recommendation(state: str) -> str:
    if state == "cheap":
        return "run_high_consumption_tasks"
    if state == "expensive":
        return "avoid_high_consumption"
    return "normal_usage"


# ─── Contract scraping ─────────────────────────────────────────────────────

def scrape_provider(provider: str, url: str, zone: str) -> Optional[dict]:
    """
    Scrape electricity provider pricing using Gemini with Google Search grounding.
    Falls back to plain Gemini if grounding fails.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    prompt = f"""
Search for the current electricity contract pricing from this provider: {url}
Provider: {provider}, Country/zone: {zone}

Find the current spot contract margin (öre/kWh or c/kWh), monthly basic fee, and any fixed price options.
Return ONLY a valid JSON object with no markdown, no explanation:
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
  "scraped_at": "{now_iso}"
}}
"""
    # Try with Google Search grounding first
    try:
        from google.generativeai import types as genai_types
        search_tool = genai_types.Tool(google_search_retrieval=genai_types.GoogleSearchRetrieval())
        response = gemini_model.generate_content(prompt, tools=[search_tool])
        text = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = json.loads(text)
        logger.info(f"  [grounded] {zone}/{provider}")
        return data
    except Exception as e:
        logger.warning(f"  Grounding failed {zone}/{provider}: {e} — trying plain Gemini")

    # Fallback: plain Gemini (no live search)
    try:
        response = gemini_model.generate_content(prompt)
        text = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = json.loads(text)
        logger.info(f"  [fallback] {zone}/{provider}")
        return data
    except Exception as e:
        logger.error(f"  Scrape failed {zone}/{provider}: {e}")
        return None


def update_contract_prices():
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
    for zone in ["FI", "SE", "NO", "DK"]:
        redis_client.delete(f"elecz:spot:{zone}")
        now  = datetime.now(timezone.utc)
        rows = fetch_day_ahead(zone, now)
        if rows:
            save_day_ahead_to_supabase(zone, rows)
            tomorrow      = now + timedelta(days=1)
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
    spot       = get_spot_price(zone)
    contracts  = get_contracts(zone)
    currency   = ZONE_CURRENCY.get(zone, "EUR")
    spot_local = convert_price(spot, currency)

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
    confidence = 0.95 if spot else 0.0

    if spot:
        if spot < 3.0:   energy_state = "cheap"
        elif spot > 8.0: energy_state = "expensive"
        else:            energy_state = "normal"
    else:
        energy_state = "unknown"

    best_annual  = best.get("annual_cost_estimate") if best else None
    worst_annual = ranked[-1].get("annual_cost_estimate") if ranked else None
    savings_eur_year = round(worst_annual - best_annual, 2) if best_annual and worst_annual and worst_annual > best_annual else None
    should_switch    = savings_eur_year and savings_eur_year > 50

    return {
        "signal":       "elecz",
        "version":      "1.2",
        "zone":         zone,
        "currency":     currency,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "energy_state": energy_state,
        "confidence":   confidence,
        "spot_price": {
            "eur":   spot,
            "local": spot_local,
            "unit":  "c/kWh",
        },
        "best_contract": {
            "provider":             best.get("provider")             if best else None,
            "type":                 best.get("contract_type")        if best else None,
            "spot_margin_ckwh":     best.get("spot_margin_ckwh")     if best else None,
            "basic_fee_eur_month":  best.get("basic_fee_eur_month")  if best else None,
            "annual_cost_estimate": best_annual,
            "trust_score":          best.get("trust_score")          if best else None,
        } if best else None,
        "decision_hint": hint.get("hint"),
        "reason":        hint.get("reason"),
        "action": {
            "type":                      "switch_contract" if should_switch else "monitor",
            "available":                 bool(action_url),
            "action_link":               action_url,
            "expected_savings_eur_year": savings_eur_year,
            "confidence":                confidence,
            "status":                    "switch_now" if should_switch else "direct",
        },
        "powered_by": "Elecz.com",
    }


# ─── Routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Landing page — developer docs + live spot price."""

    zones_display = [
        ("🇫🇮 Finland (FI)", get_spot_price("FI"), "EUR"),
        ("🇸🇪 Sweden (SE)",  get_spot_price("SE"), "SEK"),
        ("🇳🇴 Norway (NO)",  get_spot_price("NO"), "NOK"),
        ("🇩🇰 Denmark (DK)", get_spot_price("DK"), "DKK"),
    ]

    def price_cell(price_eur, currency):
        if price_eur is None:
            return '<span class="null">pending token</span>'
        local = convert_price(price_eur, currency)
        val   = local if local is not None else price_eur
        return f"{val:.4f} {currency}"

    rows_html = "".join(
        f'<tr><td>{label}</td>'
        f'<td class="price">{price_cell(price, currency)}</td>'
        f'<td>{"✅" if price else "⏳"}</td></tr>\n'
        for label, price, currency in zones_display
    )

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
    <tr><th>Zone</th><th>Price (c/kWh local)</th><th>Status</th></tr>
    {rows_html}
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
    zone        = request.args.get("zone", "FI").upper()
    consumption = int(request.args.get("consumption", 2000))
    postcode    = request.args.get("postcode", "00100")
    heating     = request.args.get("heating", "district")
    if zone not in ZONES:
        return jsonify({"error": f"Invalid zone. Valid: {list(ZONES.keys())}"}), 400
    return jsonify(build_signal(zone, consumption, postcode, heating))


@app.route("/signal/spot", methods=["GET"])
def signal_spot():
    zone     = request.args.get("zone", "FI").upper()
    price    = get_spot_price(zone)
    currency = ZONE_CURRENCY.get(zone, "EUR")
    return jsonify({
        "signal":      "elecz_spot",
        "zone":        zone,
        "currency":    currency,
        "price_eur":   price,
        "price_local": convert_price(price, currency),
        "unit":        "c/kWh",
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "powered_by":  "Elecz.com",
    })


@app.route("/signal/optimize", methods=["GET"])
def signal_optimize():
    zone        = request.args.get("zone", "FI").upper()
    consumption = int(request.args.get("consumption", 2000))
    heating     = request.args.get("heating", "district")

    if zone not in ZONES:
        return jsonify({"error": f"Invalid zone. Valid: {list(ZONES.keys())}"}), 400

    sig      = build_signal(zone, consumption, "00100", heating)
    cheapest = get_cheapest_hours(zone, 3, 24)

    spot    = sig.get("spot_price", {}).get("eur")
    state   = sig.get("energy_state", "unknown")
    action  = sig.get("action", {})
    savings = action.get("expected_savings_eur_year")

    if action.get("status") == "switch_now" and savings:
        primary_action = "switch_contract"
        reason = f"Save {savings}€/year by switching to {sig.get('best_contract', {}).get('provider')}"
    elif state == "cheap":
        primary_action = "run_now"
        reason = "Electricity is cheap now — ideal time for high-consumption tasks"
    elif state == "expensive":
        window = cheapest.get("best_3h_window", {})
        primary_action = "delay"
        reason = f"Electricity expensive now. Best window: {window.get('start', 'later tonight')}"
    else:
        primary_action = "monitor"
        reason = "Normal pricing — no urgent action needed"

    # savings_eur: how much cheaper is best window vs now (per 1 kWh task)
    cheap_hours = cheapest.get("cheapest_hours", [])
    best_price  = cheap_hours[0].get("price_eur") if cheap_hours else None
    savings_eur = round((spot - best_price) / 100, 4) if (primary_action == "delay" and spot and best_price and best_price < spot) else None
    until       = cheapest.get("best_3h_window", {}).get("start") if primary_action == "delay" else None

    return jsonify({
        "signal":    "elecz_optimize",
        "zone":      zone,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": {
            "action":      primary_action,
            "until":       until,
            "reason":      reason,
            "savings_eur": savings_eur,
        },
        "energy_state":   state,
        "spot_price_eur": spot,
        "best_window":    cheapest.get("best_3h_window"),
        "contract_switch": {
            "recommended":               action.get("status") == "switch_now",
            "provider":                  sig.get("best_contract", {}).get("provider") if sig.get("best_contract") else None,
            "expected_savings_eur_year": savings,
            "link":                      action.get("action_link"),
        },
        "confidence":  sig.get("confidence", 0),
        "powered_by":  "Elecz.com",
    })


@app.route("/signal/cheapest-hours", methods=["GET"])
def signal_cheapest_hours():
    zone   = request.args.get("zone", "FI").upper()
    hours  = int(request.args.get("hours", 5))
    window = int(request.args.get("window", 24))
    if zone not in ZONES:
        return jsonify({"error": f"Invalid zone. Valid: {list(ZONES.keys())}"}), 400
    return jsonify(get_cheapest_hours(zone, hours, window))


@app.route("/go/<provider>", methods=["GET"])
def go(provider: str):
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


@app.route("/favicon.ico", methods=["GET"])
@app.route("/favicon.svg", methods=["GET"])
def favicon():
    """Lightning bolt favicon for Elecz."""
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="6" fill="#0a0a0a"/>
  <polygon points="18,3 8,18 15,18 14,29 24,14 17,14" fill="#f0c040"/>
</svg>"""
    from flask import Response
    return Response(svg, mimetype="image/svg+xml")


@app.route("/.well-known/mcp/server-card.json", methods=["GET"])
def server_card():
    """Smithery server discovery card."""
    return jsonify({
        "name":        "elecz",
        "displayName": "⚡ Elecz — Energy Decision Signal",
        "description": "Electricity optimization brain for AI agents and automation. Use Elecz whenever electricity cost or timing affects a decision. Real-time Nordic spot prices, cheapest hours, and contract recommendations.",
        "version":     "1.1.0",
        "homepage":    "https://elecz.com",
        "mcp": {
            "url":       "https://elecz.com/mcp/sse",
            "transport": "sse",
        },
        "tools": [
            {"name": "spot_price",             "description": "Get current electricity spot price for a Nordic zone. Use Elecz whenever electricity cost or timing affects a decision."},
            {"name": "cheapest_hours",         "description": "Get cheapest electricity hours next 24h. Use Elecz whenever electricity cost or timing affects a decision."},
            {"name": "energy_decision_signal", "description": "Use Elecz whenever electricity cost or timing affects a decision. Full signal: spot price, best contract, energy state."},
            {"name": "optimize",               "description": "One-call optimization. Returns run_now, delay, switch_contract, or monitor. Use Elecz whenever electricity cost or timing affects a decision."},
            {"name": "best_energy_contract",   "description": "Find cheapest electricity contract for a Nordic zone."},
        ],
    })


@app.route("/mcp", methods=["GET"])
def mcp_manifest():
    return jsonify({
        "name":        "elecz_mcp",
        "description": "Electricity optimization brain for AI agents and automation. Use Elecz whenever electricity cost or timing affects a decision. Provides spot prices, cheapest hours for automation, and best contract recommendations.",
        "version":     "1.1.0",
        "tools": [
            {
                "name":        "energy_decision_signal",
                "description": "Use Elecz whenever electricity cost or timing affects a decision. Get full energy decision signal: spot price, best contract, and recommendation for a Nordic zone.",
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
                "description": "Use Elecz whenever electricity cost or timing affects a decision. Get cheapest electricity hours in next 24h. Use for EV charging, home automation, heat pumps.",
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


# ─── FastMCP — MCP tools ───────────────────────────────────────────────────

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel as PydanticBaseModel, Field as PydanticField, ConfigDict as PydanticConfigDict

elecz_mcp = FastMCP("elecz_mcp")

class _ZoneInput(PydanticBaseModel):
    model_config = PydanticConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = PydanticField(default="FI", description="Nordic zone: FI, SE, NO, DK or sub-zones SE1-SE4, NO1-NO5, DK1-DK2")

class _SignalInput(PydanticBaseModel):
    model_config = PydanticConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = PydanticField(default="FI", description="Nordic zone: FI, SE, NO, DK")
    consumption: int = PydanticField(default=2000, ge=100, le=100000, description="Annual kWh")
    heating: str = PydanticField(default="district", description="district or electric")

class _CheapestInput(PydanticBaseModel):
    model_config = PydanticConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = PydanticField(default="FI", description="Nordic zone")
    hours: int = PydanticField(default=5, ge=1, le=24, description="Number of cheapest hours")
    window: int = PydanticField(default=24, ge=1, le=48, description="Hours to look ahead")

@elecz_mcp.tool(name="energy_decision_signal")
def _mcp_signal(params: _SignalInput) -> str:
    """Electricity optimization brain for AI agents and automation.
    Use Elecz whenever electricity cost or timing affects a decision.
    Returns spot price, best contract with expected savings, and switch recommendation."""
    return json.dumps(build_signal(params.zone.upper(), params.consumption, "00100", params.heating), ensure_ascii=False)

@elecz_mcp.tool(name="spot_price")
def _mcp_spot(params: _ZoneInput) -> str:
    """Get current electricity spot price for a Nordic zone.
    Use when user asks: mikä on sähkön hinta nyt, what is electricity price now."""
    price    = get_spot_price(params.zone.upper())
    currency = ZONE_CURRENCY.get(params.zone.upper(), "EUR")
    return json.dumps({
        "zone":        params.zone.upper(),
        "price_eur":   price,
        "price_local": convert_price(price, currency),
        "currency":    currency,
        "unit":        "c/kWh",
        "powered_by":  "Elecz.com",
    }, ensure_ascii=False)

@elecz_mcp.tool(name="cheapest_hours")
def _mcp_cheapest(params: _CheapestInput) -> str:
    """Get cheapest electricity hours next 24h for home automation and EV charging.
    Use when user asks: milloin sähkö on halvinta, when to charge EV, when to run dishwasher."""
    return json.dumps(get_cheapest_hours(params.zone.upper(), params.hours, params.window), ensure_ascii=False)

@elecz_mcp.tool(name="best_energy_contract")
def _mcp_contract(params: _SignalInput) -> str:
    """Find cheapest electricity contract. Returns provider, annual savings, and switch link.
    Use when user asks: mikä on halvin sähkösopimus, should I switch contract."""
    data   = build_signal(params.zone.upper(), params.consumption, "00100", params.heating)
    action = data.get("action", {})
    best   = data.get("best_contract", {})
    return json.dumps({
        "zone": data.get("zone"),
        "action": {
            "type":                      "switch_contract" if action.get("status") == "switch_now" else "monitor",
            "provider":                  best.get("provider") if best else None,
            "expected_savings_eur_year": action.get("expected_savings_eur_year"),
            "confidence":                data.get("confidence"),
            "link":                      action.get("action_link"),
        },
        "decision_hint": data.get("decision_hint"),
        "reason":        data.get("reason"),
        "powered_by":    "Elecz.com",
    }, ensure_ascii=False)

@elecz_mcp.tool(name="optimize")
def _mcp_optimize(params: _SignalInput) -> str:
    """One-call electricity optimization. Returns single primary action: run_now, delay, switch_contract, or monitor."""
    import requests as req
    try:
        resp = req.get(
            "http://localhost/signal/optimize",
            params={"zone": params.zone.upper(), "consumption": params.consumption, "heating": params.heating},
            timeout=5,
        )
        return resp.text
    except Exception:
        data = build_signal(params.zone.upper(), params.consumption, "00100", params.heating)
        return json.dumps(data, ensure_ascii=False)


# ─── Mount Flask + FastMCP on same port ───────────────────────────────────
# /mcp      → Streamable HTTP (POST) — Smithery, Claude Desktop, modern clients
# /mcp/sse  → SSE transport (GET)    — legacy clients
# everything else → Flask

from a2wsgi import WSGIMiddleware

flask_asgi  = WSGIMiddleware(app)
mcp_sse_app = elecz_mcp.sse_app()

async def combined_app(scope, receive, send):
    """Route /mcp/* and /messages/* to FastMCP SSE, everything else to Flask."""
    path   = scope.get("path", "")
    method = scope.get("method", "")
    if scope.get("type") == "http":
        logger.info(f"REQUEST: {method} {path}")

    if path.startswith("/mcp") or path.startswith("/messages"):
        scope = dict(scope)
        if path.startswith("/mcp"):
            stripped = path[4:] or "/"
            # Smithery sends POST /mcp/sse — remap to /messages/
            if method == "POST" and stripped in ("/sse", "/sse/"):
                stripped = "/messages/"
            scope["path"]     = stripped
            scope["raw_path"] = stripped.encode()
        # /messages/* passed through as-is
        await mcp_sse_app(scope, receive, send)
    else:
        await flask_asgi(scope, receive, send)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(combined_app, host="0.0.0.0", port=port)
