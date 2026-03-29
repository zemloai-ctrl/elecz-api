"""
Elecz - Energy Decision Signal API
Real-time spot prices + cheapest hours + contract recommendations
MCP-compatible signal endpoint for AI agents and automation
Starlette + FastMCP (streamable HTTP)
Maintained by Sakari Korkia-Aho / Zemlo AI — Kokkola, Finland
"""

import os
import json
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
import xml.etree.ElementTree as ET
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse, RedirectResponse, Response
from starlette.routing import Route, Mount
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler
import google.generativeai as genai
import redis
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel as PydanticBaseModel, Field as PydanticField, ConfigDict as PydanticConfigDict

# ─── Logging ───────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Constants ─────────────────────────────────────────────────────────────

ENTSOE_API_URL = "https://web-api.tp.entsoe.eu/api"
FRANKFURTER_URL = "https://api.frankfurter.app/latest"
REDIS_TTL_SPOT = 3600
REDIS_TTL_CONTRACTS = 86400
REDIS_TTL_FX = 86400

ABNORMAL_PRICE_HIGH = 300.0   # EUR/MWh — hintapiikki
ABNORMAL_PRICE_LOW  = -50.0   # EUR/MWh — negatiivinen ääriarvo

# Zones that use live ENTSO-E fetch on cache miss (DE excluded — scheduler only)
LIVE_FETCH_ZONES = {"FI", "SE", "SE1", "SE2", "SE3", "SE4", "NO", "NO1", "NO2", "NO3", "NO4", "NO5", "DK", "DK1", "DK2"}

# Default annual consumption by market (kWh)
# DE: saksalainen kotitalous ~3500 kWh, pohjoismainen ~2000 kWh
DEFAULT_CONSUMPTION = {
    "FI": 2000, "SE": 2000, "SE1": 2000, "SE2": 2000, "SE3": 2000, "SE4": 2000,
    "NO": 2000, "NO1": 2000, "NO2": 2000, "NO3": 2000, "NO4": 2000, "NO5": 2000,
    "DK": 2000, "DK1": 2000, "DK2": 2000,
    "DE": 3500,
}

PROVIDER_URLS = {
    "FI": {
        "tibber": "https://tibber.com/fi/sahkosopimus",
        "helen": "https://www.helen.fi/sahko/sopimukset",
        "fortum": "https://www.fortum.fi/sahkosopimukset",
        "vattenfall": "https://www.vattenfall.fi/sahko",
        "oomi": "https://oomi.fi/sahkosopimus",
        "nordic_green_energy": "https://www.nordicgreenenergy.com/fi",
        "vare": "https://www.vare.fi/sahkosopimus",
        "cheap_energy": "https://www.cheapenergy.fi",
    },
    "SE": {
        "tibber": "https://tibber.com/se/elpris",
        "fortum": "https://www.fortum.se/elavtal",
        "vattenfall": "https://www.vattenfall.se/elavtal",
        "eon": "https://www.eon.se/elavtal",
        "skekraft": "https://www.skekraft.se/el/elavtal",
        "greenely": "https://www.greenely.se/elavtal",
        "godel": "https://www.godel.se/elavtal",
        "gotaenergi": "https://www.gotaenergi.se/elavtal",
    },
    "NO": {
        "tibber": "https://tibber.com/no/strom",
        "fjordkraft": "https://www.fjordkraft.no/strom",
        "kildenkraft": "https://www.kildenkraft.no",
        "kraftriket": "https://www.kraftriket.no",
        "astrom": "https://www.astrom.no",
        "nte": "https://www.nte.no/strom",
        "lyse": "https://www.lyse.no/strom",
    },
    "DK": {
        "tibber": "https://tibber.com/dk/el",
        "norlys": "https://www.norlys.dk/el",
        "ok": "https://www.ok.dk/el",
        "modstrom": "https://www.modstrom.dk",
        "ewii": "https://www.ewii.dk/el",
        "vindstod": "https://www.vindstod.dk",
        "nettopower": "https://www.nettopower.dk",
        "cheap_energy": "https://www.cheapenergy.dk",
    },
    "DE": {
        "tibber": "https://tibber.com/de/stromtarif",
        "octopus": "https://octopusenergy.de/strom",
        "e_wie_einfach": "https://www.e-wie-einfach.de/",
        "yello": "https://www.yello.de/strom/stromtarife/",
        "eon": "https://www.eon.de/de/pk/strom.html",
        "vattenfall": "https://www.vattenfall.de/strom",
        "enbw": "https://www.enbw.com/privatkunden/strom",
        "naturstrom": "https://www.naturstrom.de/privatkunden/strom/",
        "lichtblick": "https://www.lichtblick.de/oekostrom/",
        "polarstern": "https://www.polarstern-energie.de/strom/",
        "extraenergie": "https://www.extraenergie.com/strom/",
        "gruenwelt": "https://www.gruenwelt.de/strom/",
    },
}

PROVIDER_DIRECT_URLS = {
    "FI": {
        "tibber": "https://tibber.com/fi",
        "helen": "https://www.helen.fi/sahko/sopimukset",
        "fortum": "https://www.fortum.fi/sahkosopimukset",
        "vattenfall": "https://www.vattenfall.fi/sahko/sahkosopimus",
        "oomi": "https://oomi.fi/sahkosopimus",
        "nordic_green_energy": "https://www.nordicgreenenergy.com/fi/sahkosopimus",
        "vare": "https://www.vare.fi/sahkosopimus",
        "cheap_energy": "https://www.cheapenergy.fi",
    },
    "SE": {
        "tibber": "https://tibber.com/se",
        "fortum": "https://www.fortum.se/elavtal",
        "vattenfall": "https://www.vattenfall.se/elavtal",
        "eon": "https://www.eon.se/elavtal",
        "skekraft": "https://www.skekraft.se/el/elavtal",
        "greenely": "https://www.greenely.se/elavtal",
        "godel": "https://www.godel.se/elavtal",
        "gotaenergi": "https://www.gotaenergi.se/elavtal",
    },
    "NO": {
        "tibber": "https://tibber.com/no",
        "fjordkraft": "https://www.fjordkraft.no/strom",
        "kildenkraft": "https://www.kildenkraft.no",
        "kraftriket": "https://www.kraftriket.no",
        "astrom": "https://www.astrom.no",
        "nte": "https://www.nte.no/strom",
        "lyse": "https://www.lyse.no/strom",
    },
    "DK": {
        "tibber": "https://tibber.com/dk",
        "norlys": "https://www.norlys.dk/el",
        "ok": "https://www.ok.dk/el",
        "modstrom": "https://www.modstrom.dk",
        "ewii": "https://www.ewii.dk/el",
        "vindstod": "https://www.vindstod.dk",
        "nettopower": "https://www.nettopower.dk",
        "cheap_energy": "https://www.cheapenergy.dk",
    },
    "DE": {
        "tibber": "https://tibber.com/de",
        "octopus": "https://octopusenergy.de",
        "e_wie_einfach": "https://www.e-wie-einfach.de",
        "yello": "https://www.yello.de",
        "eon": "https://www.eon.de",
        "vattenfall": "https://www.vattenfall.de",
        "enbw": "https://www.enbw.com",
        "naturstrom": "https://www.naturstrom.de",
        "lichtblick": "https://www.lichtblick.de",
        "polarstern": "https://www.polarstern-energie.de",
        "extraenergie": "https://www.extraenergie.com",
        "gruenwelt": "https://www.gruenwelt.de",
    },
}

ZONES = {
    "FI": "10YFI-1--------U",
    "SE": "10Y1001A1001A46L",
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
    "NO": "10YNO-1--------2",
    "NO1": "10YNO-1--------2",
    "NO2": "10YNO-2--------T",
    "NO3": "10YNO-3--------J",
    "NO4": "10YNO-4--------9",
    "NO5": "10Y1001A1001A48H",
    "DK": "10YDK-1--------W",
    "DK1": "10YDK-1--------W",
    "DK2": "10YDK-2--------M",
    "DE": "10Y1001A1001A82H",
}

ZONE_CURRENCY = {
    "FI": "EUR",
    "SE": "SEK", "SE1": "SEK", "SE2": "SEK", "SE3": "SEK", "SE4": "SEK",
    "NO": "NOK", "NO1": "NOK", "NO2": "NOK", "NO3": "NOK", "NO4": "NOK", "NO5": "NOK",
    "DK": "DKK", "DK1": "DKK", "DK2": "DKK",
    "DE": "EUR",
}

ZONE_UNIT_LOCAL = {
    "EUR": "c/kWh",
    "SEK": "ore/kWh",
    "NOK": "ore/kWh",
    "DKK": "ore/kWh",
}

ZONE_COUNTRY = {
    "FI": "Finland", "SE": "Sweden", "SE1": "Sweden", "SE2": "Sweden", "SE3": "Sweden", "SE4": "Sweden",
    "NO": "Norway", "NO1": "Norway", "NO2": "Norway", "NO3": "Norway", "NO4": "Norway", "NO5": "Norway",
    "DK": "Denmark", "DK1": "Denmark", "DK2": "Denmark",
    "DE": "Germany",
}

# ─── Clients ───────────────────────────────────────────────────────────────

supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

redis_client = redis.from_url(os.environ["UPSTASH_REDIS_URL"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
gemini_model = genai.GenerativeModel("gemini-2.5-flash")
ENTSOE_TOKEN = os.environ["ENTSOE_SECURITY_TOKEN"]

# ─── Analytics ─────────────────────────────────────────────────────────────

def log_api_call(tool_name: str, call_type: str = "rest", zone: str = None, ip: str = None):
    """Log all API and MCP calls to api_calls table with call_type, ip_prefix and country_hint."""
    ip_prefix = None
    if ip:
        parts = ip.split(".")
        if len(parts) == 4:
            ip_prefix = ".".join(parts[:3])
        elif ":" in ip:
            ip_prefix = ip[:18]

    country_hint = ZONE_COUNTRY.get(zone.upper(), None) if zone else None

    try:
        supabase.table("api_calls").insert({
            "call_type": call_type,
            "tool_name": tool_name,
            "zone": zone,
            "ip_prefix": ip_prefix,
            "country_hint": country_hint,
            "called_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning(f"Analytics failed: {e}")

# ─── ENTSO-E helpers ───────────────────────────────────────────────────────

def _parse_entsoe_xml(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    ns = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}
    rows = []
    for ts in root.findall(".//ns:TimeSeries", ns):
        start_str = ts.find(".//ns:timeInterval/ns:start", ns)
        if start_str is None:
            continue
        start = datetime.fromisoformat(start_str.text.replace("Z", "+00:00"))
        for point in ts.findall(".//ns:Point", ns):
            pos = int(point.find("ns:position", ns).text)
            price = float(point.find("ns:price.amount", ns).text)
            hour = start + timedelta(hours=pos - 1)
            is_abnormal = price > ABNORMAL_PRICE_HIGH or price < ABNORMAL_PRICE_LOW
            rows.append({"hour": hour, "price_eur_mwh": price, "is_abnormal": is_abnormal})
    return rows


def fetch_day_ahead(zone: str, date: datetime, _retry: int = 3) -> list[dict]:
    """Fetch ENTSO-E day-ahead prices with retry and rate-limit detection.
    DE uses longer timeout and backoff to handle ENTSO-E throttling.
    """
    zone_code = ZONES.get(zone)
    if not zone_code:
        return []
    params = {
        "securityToken": ENTSOE_TOKEN,
        "documentType": "A44",
        "in_Domain": zone_code,
        "out_Domain": zone_code,
        "periodStart": date.strftime("%Y%m%d0000"),
        "periodEnd": date.strftime("%Y%m%d2300"),
    }
    # DE is heavily throttled by ENTSO-E — use longer timeout and backoff
    timeout = 60 if zone == "DE" else 15
    base_backoff = 15 if zone == "DE" else 5

    for attempt in range(1, _retry + 1):
        try:
            resp = httpx.get(ENTSOE_API_URL, params=params, timeout=timeout)
            if resp.status_code == 429:
                wait = 60 * attempt
                logger.warning(f"ENTSO-E rate limit zone={zone}, waiting {wait}s (attempt {attempt}/{_retry})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            if zone == "DE":
                logger.info(f"ENTSO-E DE raw XML: {resp.text[:800]}")
            rows = _parse_entsoe_xml(resp.text)
            if rows:
                logger.info(f"ENTSO-E zone={zone} parsed {len(rows)} rows")
            else:
                logger.warning(f"ENTSO-E zone={zone} returned 200 but 0 rows parsed")
            return rows
        except httpx.HTTPStatusError as e:
            logger.error(f"ENTSO-E HTTP error zone={zone} attempt={attempt}: {e}")
        except Exception as e:
            logger.error(f"ENTSO-E fetch failed zone={zone} attempt={attempt}: {e}")
        if attempt < _retry:
            wait = base_backoff * attempt
            logger.info(f"ENTSO-E retry zone={zone} waiting {wait}s")
            time.sleep(wait)
    logger.error(f"ENTSO-E all {_retry} attempts failed zone={zone}")
    return []


def get_spot_price(zone: str = "FI") -> Optional[float]:
    key = f"elecz:spot:{zone}"
    cached = redis_client.get(key)
    if cached:
        return float(cached)

    # DE: never do live ENTSO-E fetch on cache miss — scheduler only.
    # Live fetches from REST/MCP requests pile up and trigger ENTSO-E throttling.
    # Fall straight through to Supabase fallback.
    if zone not in LIVE_FETCH_ZONES:
        logger.info(f"Zone {zone} not in live-fetch set — going straight to Supabase fallback")
    else:
        now = datetime.now(timezone.utc)
        rows = fetch_day_ahead(zone, now)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        if rows:
            for r in rows:
                if r["hour"].replace(tzinfo=timezone.utc) == current_hour:
                    price = round(r["price_eur_mwh"] / 10, 4)
                    redis_client.setex(key, REDIS_TTL_SPOT, str(price))
                    return price

    logger.warning(f"ENTSO-E unavailable for {zone} — falling back to Supabase")
    now = datetime.now(timezone.utc)
    try:
        result = supabase.table("prices_day_ahead").select(
            "hour, price_ckwh"
        ).eq("zone", zone).lte("hour", now.isoformat()).order("hour", desc=True).limit(1).execute()
        rows_db = result.data or []
        if rows_db:
            price = rows_db[0]["price_ckwh"]
            redis_client.setex(key, 600, str(price))
            logger.info(f"Supabase fallback {zone}: {price} c/kWh (from {rows_db[0]['hour']})")
            return price
    except Exception as e:
        logger.error(f"Supabase fallback failed {zone}: {e}")
    return None


def save_day_ahead_to_supabase(zone: str, rows: list[dict]):
    seen = set()
    unique_rows = []
    for r in rows:
        key = r["hour"].isoformat()
        if key not in seen:
            seen.add(key)
            unique_rows.append(r)

    records = [
        {
            "zone": zone,
            "hour": r["hour"].isoformat(),
            "price_eur_mwh": r["price_eur_mwh"],
            "price_ckwh": round(r["price_eur_mwh"] / 10, 4),
            "is_abnormal": r.get("is_abnormal", False),
            "source": "ENTSO-E",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        for r in unique_rows
    ]
    if records:
        try:
            supabase.table("prices_day_ahead").upsert(records, on_conflict="zone,hour").execute()
            logger.info(f"Saved {len(records)} rows to Supabase for zone={zone}")
        except Exception as e:
            logger.error(f"Supabase prices save failed zone={zone}: {e}")

# ─── Frankfurter ───────────────────────────────────────────────────────────

def get_exchange_rate(currency: str) -> float:
    if currency == "EUR":
        return 1.0
    key = f"elecz:fx:{currency}"
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

# ─── Cheapest hours ────────────────────────────────────────────────────────

def get_cheapest_hours(zone: str, n_hours: int = 5, window_h: int = 24) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=window_h)
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
        return {"available": False, "reason": "No price data available."}

    cheapest = rows[:n_hours]
    all_prices = [r["price_ckwh"] for r in rows]
    avg = sum(all_prices) / len(all_prices) if all_prices else 0

    try:
        result_chrono = supabase.table("prices_day_ahead").select(
            "hour, price_ckwh"
        ).eq("zone", zone).gte("hour", now.isoformat()).lte(
            "hour", cutoff.isoformat()
        ).order("hour").execute()
        rows_chrono = result_chrono.data or []
    except Exception as e:
        logger.error(f"Cheapest hours chrono fetch failed: {e}")
        rows_chrono = sorted(rows, key=lambda r: r["hour"])

    best_window = _best_consecutive_window(rows_chrono, 3)

    current_price = get_spot_price(zone) or avg
    if current_price < avg * 0.7:
        energy_state, confidence = "cheap", 0.90
    elif current_price > avg * 1.3:
        energy_state, confidence = "expensive", 0.88
    else:
        energy_state, confidence = "normal", 0.75

    return {
        "available": True,
        "zone": zone,
        "currency": currency,
        "energy_state": energy_state,
        "confidence": confidence,
        "cheapest_hours": [
            {
                "hour": r["hour"][:16],
                "price_eur": r["price_ckwh"],
                "price_local": convert_price(r["price_ckwh"], currency),
            }
            for r in cheapest
        ],
        "best_3h_window": best_window,
        "avoid_hours": _expensive_hours(rows, avg),
        "recommendation": _consumption_recommendation(energy_state),
        "powered_by": "Elecz.com",
    }


def _best_consecutive_window(rows: list, window: int) -> Optional[dict]:
    if len(rows) < window:
        return None
    best_avg, best_start, best_end = float("inf"), None, None
    for i in range(len(rows) - window + 1):
        avg = sum(r["price_ckwh"] for r in rows[i:i + window]) / window
        if avg < best_avg:
            best_avg = avg
            best_start = rows[i]["hour"][:16]
            best_end = rows[i + window - 1]["hour"][:16]
    return {"start": best_start, "end": best_end, "avg_price_eur": round(best_avg, 4)}


def _expensive_hours(rows: list, avg: float) -> list[str]:
    return [r["hour"][:16] for r in rows if r["price_ckwh"] > avg * 1.3][:6]


def _consumption_recommendation(state: str) -> str:
    if state in ("cheap", "negative"):
        return "run_high_consumption_tasks"
    if state == "expensive":
        return "avoid_high_consumption"
    return "normal_usage"

# ─── Contract scraping ─────────────────────────────────────────────────────

def scrape_provider(provider: str, url: str, zone: str) -> Optional[dict]:
    now_iso = datetime.now(timezone.utc).isoformat()

    if zone == "DE":
        prompt = f"""
Search for the current electricity contract pricing from this provider: {url}
Provider: {provider}, Country/zone: {zone}
Assume location: Berlin, PLZ 10115 (use as baseline if postcode is required).

IMPORTANT: If provider is "tibber" and zone is "DE", set contract_type to "dynamic" and is_spot to true.
Tibber Germany uses exchange-based dynamic pricing (Tibber Dynamic), not a fixed spot margin.
Do not return a spot_margin_ckwh for Tibber DE — return arbeitspreis_ckwh as the current average effective price if available.

Return Arbeitspreis as brutto ct/kWh including MwSt (19%).
If price is listed as netto, multiply by 1.19.
Ignore: Neukundenbonus, Sofortbonus, Treuebonus, promotional first-year prices, and campaign discounts.
Return only the standard ongoing tariff price.

Return ONLY a valid JSON object with no markdown, no explanation:
{{
  "provider": "{provider}",
  "zone": "{zone}",
  "spot_margin_ckwh": <float or null>,
  "arbeitspreis_ckwh": <float or null>,
  "basic_fee_eur_month": <float or null>,
  "fixed_price_ckwh": <float or null>,
  "contract_type": "spot" | "fixed" | "fixed_term" | "dynamic",
  "contract_duration_months": <int or null>,
  "new_customers_only": <bool>,
  "below_wholesale": <bool>,
  "is_spot": <bool>,
  "is_fixed": <bool>,
  "price_includes_tax": <bool>,
  "grundpreis_unit": "eur_month" | "eur_year",
  "preisgarantie": "full" | "partial" | "none",
  "reliability": "high" | "medium" | "low",
  "scraped_at": "{now_iso}"
}}
Note: arbeitspreis_ckwh must be between 5 and 100 ct/kWh. If value seems to be in EUR/kWh, multiply by 100.
is_spot=true if contract tracks exchange spot price. is_fixed=true if price is fixed for the contract duration.
"""
    else:
        prompt = f"""
Search for the current electricity contract pricing from this provider: {url}
Provider: {provider}, Country/zone: {zone}

Find the current spot contract margin (ore/kWh or c/kWh), monthly basic fee, and any fixed price options.
Return ONLY a valid JSON object with no markdown, no explanation:
{{
  "provider": "{provider}",
  "zone": "{zone}",
  "spot_margin_ckwh": <float or null>,
  "arbeitspreis_ckwh": <float or null>,
  "basic_fee_eur_month": <float or null>,
  "fixed_price_ckwh": <float or null>,
  "contract_type": "spot" | "fixed" | "fixed_term",
  "contract_duration_months": <int or null>,
  "new_customers_only": <bool>,
  "below_wholesale": <bool>,
  "scraped_at": "{now_iso}"
}}
"""
    try:
        response = gemini_model.generate_content(prompt)
        text = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = json.loads(text)
        data["scraped_at"] = now_iso

        if data.get("arbeitspreis_ckwh") and data["arbeitspreis_ckwh"] > 100:
            logger.warning(f"arbeitspreis_ckwh={data['arbeitspreis_ckwh']} looks like EUR/kWh, dividing by 100")
            data["arbeitspreis_ckwh"] = round(data["arbeitspreis_ckwh"] / 100, 4)

        if data.get("arbeitspreis_ckwh") and data["arbeitspreis_ckwh"] < 5:
            logger.warning(f"arbeitspreis_ckwh={data['arbeitspreis_ckwh']} too low, flagging data_errors")
            data["data_errors"] = True

        # Enforce Tibber DE = dynamic regardless of what Gemini returns
        if provider == "tibber" and zone == "DE":
            data["contract_type"] = "dynamic"
            data["is_spot"] = True
            data["spot_margin_ckwh"] = None  # Tibber DE has no fixed margin

        logger.info(f" ✓ {zone}/{provider}")
        return data
    except Exception as e:
        logger.error(f" Scrape failed {zone}/{provider}: {e}")
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
                        "direct_url": PROVIDER_DIRECT_URLS.get(zone, {}).get(provider),
                        "affiliate_url": None,
                        "scraped_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }, on_conflict="provider,zone").execute()
                    logger.info(f" ✓ {zone}/{provider}")
                except Exception as e:
                    logger.error(f" ✗ {zone}/{provider}: {e}")
        redis_client.delete(f"elecz:contracts:{zone}")
    logger.info("Contract update complete.")


def _fetch_and_save_zone(zone: str):
    """Fetch today + tomorrow ENTSO-E data for a single zone and cache spot price."""
    redis_client.delete(f"elecz:spot:{zone}")
    now = datetime.now(timezone.utc)
    rows = fetch_day_ahead(zone, now)
    if rows:
        save_day_ahead_to_supabase(zone, rows)
    tomorrow = now + timedelta(days=1)
    rows_tomorrow = fetch_day_ahead(zone, tomorrow)
    if rows_tomorrow:
        save_day_ahead_to_supabase(zone, rows_tomorrow)
    # Populate Redis cache from freshly saved data
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    all_rows = rows + rows_tomorrow
    for r in all_rows:
        if r["hour"].replace(tzinfo=timezone.utc) == current_hour:
            price = round(r["price_eur_mwh"] / 10, 4)
            redis_client.setex(f"elecz:spot:{zone}", REDIS_TTL_SPOT, str(price))
            logger.info(f"Cached spot {zone}: {price} c/kWh")
            break


def update_nordic_spots():
    """Scheduler job: update FI, SE, NO, DK — runs every hour at :05."""
    logger.info("Updating Nordic spot prices...")
    for zone in ["FI", "SE", "NO", "DK"]:
        _fetch_and_save_zone(zone)
    logger.info("Nordic spot prices refreshed.")


def update_de_spot():
    """Scheduler job: update DE only — runs every hour at :20, offset from Nordics.
    Separate slot reduces ENTSO-E request density and avoids IP throttling.
    """
    logger.info("Updating DE spot price...")
    _fetch_and_save_zone("DE")
    logger.info("DE spot price refreshed.")

# ─── Contracts cache ───────────────────────────────────────────────────────

def get_contracts(zone: str) -> list:
    key = f"elecz:contracts:{zone}"
    cached = redis_client.get(key)
    if cached:
        return json.loads(cached)
    try:
        result = supabase.table("contracts").select("*").eq("zone", zone).execute()
        contracts = result.data or []
        redis_client.setex(key, REDIS_TTL_CONTRACTS, json.dumps(contracts))
        return contracts
    except Exception as e:
        logger.error(f"Contracts fetch failed zone={zone}: {e}")
        return []

# ─── Signal logic ──────────────────────────────────────────────────────────

def trust_score(contract: dict) -> int:
    score = 100
    if contract.get("below_wholesale"): score -= 30
    if contract.get("new_customers_only"): score -= 20
    if contract.get("has_prepayment"): score -= 15
    if contract.get("data_errors"): score -= 10
    return max(0, score)


def decision_hint(spot: float, contract: dict, consumption: int, heating: str, zone: str = "FI") -> dict:
    # DE-specific defaults: saksalainen kuluttaa enemmän
    de_high_consumption = zone == "DE" and consumption >= 3500
    nordic_low_consumption = zone != "DE" and consumption <= 2000

    if nordic_low_consumption and heating == "district":
        return {"hint": "spot_recommended", "reason": "Low consumption: minimize basic fee. Spot is cheapest long-term."}
    if de_high_consumption:
        if spot and spot < 5.0:
            return {"hint": "stay_spot", "reason": "High consumption + low spot price. Dynamic/spot contract is cheapest now."}
        else:
            return {"hint": "consider_fixed", "reason": "High consumption + elevated spot price. Fixed Arbeitspreis offers cost certainty."}
    if consumption >= 15000:
        if spot and spot < 5.0:
            return {"hint": "stay_spot", "reason": "High consumption + low spot price. Spot is cheapest now."}
        else:
            return {"hint": "consider_fixed", "reason": "High consumption + elevated spot. Fixed price offers certainty."}
    return {"hint": "compare_options", "reason": "Compare spot margin + basic fee vs fixed price for your consumption."}


def _annual_cost(contract: dict, spot: Optional[float], consumption: int) -> Optional[float]:
    """Calculate estimated annual cost for a contract given consumption and current spot."""
    fee = contract.get("basic_fee_eur_month") or 0
    fixed = contract.get("fixed_price_ckwh")
    arbeitspreis = contract.get("arbeitspreis_ckwh")
    margin = contract.get("spot_margin_ckwh") or 0
    contract_type = contract.get("contract_type", "")

    # Dynamic contracts (Tibber DE): use spot as proxy if no fixed arbeitspreis available
    if contract_type == "dynamic" and not arbeitspreis and spot:
        # Dynamic = spot price, no fixed margin — use spot as current cost estimate
        return round((spot / 100) * consumption + fee * 12, 2)

    effective_fixed = fixed or arbeitspreis
    if effective_fixed:
        return round((effective_fixed / 100) * consumption + fee * 12, 2)
    if spot is not None:
        return round(((spot + margin) / 100) * consumption + fee * 12, 2)
    return None


def build_signal(
    zone: str,
    consumption: int,
    postcode: str,
    heating: str,
    current_annual_cost: Optional[float] = None,
) -> dict:
    spot = get_spot_price(zone)
    contracts = get_contracts(zone)
    currency = ZONE_CURRENCY.get(zone, "EUR")
    spot_local = convert_price(spot, currency)
    fx = get_exchange_rate(currency)

    # DE: confidence alennetaan jos ei PLZ:aa
    base_confidence = 0.95 if spot else 0.0
    if zone == "DE" and postcode in ("00100", "", None):
        base_confidence = min(base_confidence, 0.85)

    ranked = []
    for c in contracts:
        ts = trust_score(c)
        annual = _annual_cost(c, spot, consumption)
        ranked.append({**c, "trust_score": ts, "annual_cost_estimate": round(annual, 2) if annual else None})

    ranked.sort(key=lambda x: (x["annual_cost_estimate"] or 9999, -x["trust_score"]))

    # Top 3 contracts — avoids single-provider liability framing
    top3 = ranked[:3]
    best = top3[0] if top3 else None

    hint = decision_hint(spot or 0, best or {}, consumption, heating, zone) if best else {}
    action_url = f"https://elecz.com/go/{best['provider']}" if best else None
    confidence = base_confidence

    if spot is not None:
        if spot < 0:
            energy_state = "negative"
        elif spot < 3.0:
            energy_state = "cheap"
        elif spot > 8.0:
            energy_state = "expensive"
        else:
            energy_state = "normal"
    else:
        energy_state = "unknown"

    is_good_time_to_use_energy = energy_state in ("cheap", "negative")

    best_annual = best.get("annual_cost_estimate") if best else None

    # Savings: compare best contract vs user's current cost (if provided),
    # else vs median provider in the ranked list (not worst — avoids inflated framing).
    if best_annual:
        if current_annual_cost and current_annual_cost > best_annual:
            savings_eur_year = round(current_annual_cost - best_annual, 2)
        elif len(ranked) > 1:
            mid_idx = len(ranked) // 2
            mid_annual = ranked[mid_idx].get("annual_cost_estimate")
            savings_eur_year = round(mid_annual - best_annual, 2) if mid_annual and mid_annual > best_annual else None
        else:
            savings_eur_year = None
    else:
        savings_eur_year = None

    savings_local_year = round(savings_eur_year * fx, 2) if savings_eur_year else None
    savings_currency = currency
    should_switch = bool(savings_eur_year and savings_eur_year > 0)
    switch_recommended = should_switch

    raw_hint = hint.get("hint")
    raw_reason = hint.get("reason")
    if switch_recommended and raw_hint == "compare_options":
        raw_hint = "switch_recommended"
        raw_reason = f"Switching saves ~{savings_eur_year} EUR/year. {raw_reason}"

    action_status = "switch_now" if switch_recommended else "monitor"

    # Build top_contracts list for response (cleaner subset of fields)
    top_contracts_out = [
        {
            "rank": i + 1,
            "provider": c.get("provider"),
            "type": c.get("contract_type"),
            "spot_margin_ckwh": c.get("spot_margin_ckwh"),
            "arbeitspreis_ckwh": c.get("arbeitspreis_ckwh"),
            "basic_fee_eur_month": c.get("basic_fee_eur_month"),
            "annual_cost_estimate": c.get("annual_cost_estimate"),
            "trust_score": c.get("trust_score"),
            "direct_url": c.get("direct_url") or PROVIDER_DIRECT_URLS.get(zone, {}).get(c.get("provider")),
        }
        for i, c in enumerate(top3)
    ]

    result = {
        "signal": "elecz",
        "version": "1.5",
        "zone": zone,
        "currency": currency,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "energy_state": energy_state,
        "is_good_time_to_use_energy": is_good_time_to_use_energy,
        "switch_recommended": switch_recommended,
        "confidence": confidence,
        "spot_price": {
            "eur": spot,
            "local": spot_local,
            "unit": "c/kWh",
        },
        # best_contract kept for backwards compatibility
        "best_contract": {
            "provider": best.get("provider") if best else None,
            "type": best.get("contract_type") if best else None,
            "spot_margin_ckwh": best.get("spot_margin_ckwh") if best else None,
            "arbeitspreis_ckwh": best.get("arbeitspreis_ckwh") if best else None,
            "basic_fee_eur_month": best.get("basic_fee_eur_month") if best else None,
            "annual_cost_estimate": best_annual,
            "trust_score": best.get("trust_score") if best else None,
        } if best else None,
        # top_contracts: full ranked list of top 3
        "top_contracts": top_contracts_out,
        "decision_hint": raw_hint,
        "reason": raw_reason,
        "action": {
            "type": "switch_contract" if switch_recommended else "monitor",
            "available": bool(action_url),
            "action_link": action_url,
            "expected_savings_eur_year": savings_eur_year,
            "expected_savings_local_year": savings_local_year,
            "savings_currency": savings_currency,
            "savings_basis": "vs_current_contract" if current_annual_cost else "vs_median_provider",
            "confidence": confidence,
            "status": action_status,
        },
        "powered_by": "Elecz.com",
    }

    if zone == "DE":
        result["disclaimer"] = "Price excludes regional Netzentgelt (varies 10-15 ct/kWh by area)."

    return result

# ─── Starlette route handlers ──────────────────────────────────────────────

async def route_index(request: Request):
    de_cached = redis_client.get("elecz:spot:DE")
    de_price = float(de_cached) if de_cached else None

    zones_display = [
        ("🇫🇮 Finland (FI)", get_spot_price("FI"), "EUR"),
        ("🇸🇪 Sweden (SE)", get_spot_price("SE"), "SEK"),
        ("🇳🇴 Norway (NO)", get_spot_price("NO"), "NOK"),
        ("🇩🇰 Denmark (DK)", get_spot_price("DK"), "DKK"),
        ("🇩🇪 Germany (DE) [beta]", de_price, "EUR"),
    ]

    def price_cell(price_eur, currency):
        if price_eur is None:
            return '<span class="null">pending</span>'
        local = convert_price(price_eur, currency)
        unit_local = ZONE_UNIT_LOCAL.get(currency, "c/kWh")
        if currency == "EUR":
            return f"{price_eur:.4f} c/kWh"
        return f"{price_eur:.4f} c/kWh EUR &middot; {local:.2f} {unit_local}"

    rows_html = "".join(
        f'<tr><td>{label}</td>'
        f'<td class="price">{price_cell(price, currency)}</td>'
        f'<td>{"✅" if price else "⏳"}</td></tr>\n'
        for label, price, currency in zones_display
    )

    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Elecz",
        "description": "Real-time electricity price signal API for AI agents. Returns spot prices, cheapest hours, and contract recommendations for Finland, Sweden, Norway, Denmark and Germany.",
        "url": "https://elecz.com",
        "applicationCategory": "Utilities",
        "operatingSystem": "Any",
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "EUR"
        },
        "provider": {
            "@type": "Organization",
            "name": "Zemlo AI",
            "url": "https://zemloai.com"
        }
    }, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>⚡ Elecz.com — Energy Signal API</title>
  <meta name="description" content="Real-time electricity price signal API for AI agents. Spot prices, cheapest hours, and contract recommendations for Finland, Sweden, Norway, Denmark and Germany.">
  <script type="application/ld+json">
{json_ld}
  </script>
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
    a {{ color: #555; text-decoration: none; }}
    a:hover {{ color: #80c0ff; }}
  </style>
</head>
<body>
  <h1>⚡ Elecz.com</h1>
  <p>Electricity optimization brain for AI agents and automation.</p>
  <p>Use Elecz whenever electricity cost or timing affects a decision.</p>
  <span class="badge">LIVE</span>

  <h2>Spot Prices — Now</h2>
  <table>
    <tr><th>Zone</th><th>Price</th><th>Status</th></tr>
    {rows_html}
  </table>

  <h2>API Endpoints</h2>
  <table>
    <tr><th>Endpoint</th><th>Description</th></tr>
    <tr><td><code>GET /signal/optimize?zone=FI</code></td><td>One-call optimization — recommended</td></tr>
    <tr><td><code>GET /signal?zone=FI</code></td><td>Full energy decision signal</td></tr>
    <tr><td><code>GET /signal/spot?zone=FI</code></td><td>Current spot price only</td></tr>
    <tr><td><code>GET /signal/cheapest-hours?zone=FI&hours=5</code></td><td>Cheapest hours next 24h</td></tr>
    <tr><td><code>GET /go/&lt;provider&gt;</code></td><td>Redirect to provider + analytics</td></tr>
    <tr><td><code>GET /health</code></td><td>Health check</td></tr>
  </table>

  <h2>MCP Integration</h2>
  <pre>{{
  "mcpServers": {{
    "elecz": {{
      "url": "https://elecz.com/mcp"
    }}
  }}
}}</pre>

  <p style="color:#333; margin-top:60px; font-size:0.8em;">
    ⚡ Elecz.com — Energy Decision Signal API · Powered by ENTSO-E · Nordic + DE markets<br>
    Maintained by <a href="mailto:sakke@zemloai.com">Sakari Korkia-Aho / Zemlo AI</a> ·
    <a href="/privacy">Privacy Policy</a>
  </p>
</body>
</html>"""
    return HTMLResponse(html)


async def route_privacy(request: Request):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Privacy Policy — Elecz.com</title>
  <style>
    body { font-family: monospace; background: #0a0a0a; color: #e0e0e0; max-width: 700px; margin: 40px auto; padding: 20px; }
    h1 { color: #f0c040; }
    h2 { color: #80c0ff; margin-top: 32px; }
    a { color: #40ff80; }
    p, li { line-height: 1.7; }
    ul { padding-left: 20px; }
  </style>
</head>
<body>
  <h1>⚡ Elecz.com — Privacy Policy</h1>
  <p>Last updated: March 2026</p>

  <h2>Who we are</h2>
  <p>Elecz is operated by Sakari Korkia-Aho / Zemlo AI, Kokkola, Finland.<br>
  Contact: <a href="mailto:sakke@zemloai.com">sakke@zemloai.com</a></p>

  <h2>What data we collect</h2>
  <p>When you use the Elecz API or MCP server, we may log the following:</p>
  <ul>
    <li>The API endpoint and query parameters (e.g. zone=FI)</li>
    <li>Timestamp of the request</li>
    <li>IP address prefix (first 3 octets only, e.g. 160.79.106)</li>
    <li>User-agent string</li>
  </ul>

  <h2>What we do not collect</h2>
  <p>We do not collect personal information, names, email addresses, or any data that identifies individual users.
  We do not store full IP addresses. We do not set cookies. We do not use tracking pixels or advertising networks.</p>

  <h2>How we use data</h2>
  <p>Logged data is used solely for service monitoring, debugging, and aggregate usage analytics
  (e.g. which zones are most queried). Data is never sold or shared with third parties.</p>

  <h2>Data storage</h2>
  <p>Request logs and price data are stored in Supabase (EU region) and cached in Upstash Redis.
  Electricity price data originates from the ENTSO-E Transparency Platform.</p>

  <h2>MCP server</h2>
  <p>The MCP endpoint at <code>https://elecz.com/mcp</code> processes tool call requests from AI agents.
  It receives query parameters (zone, consumption estimates) and returns electricity price signals.
  No user identity data is transmitted or stored.</p>

  <h2>Third-party links</h2>
  <p>Elecz may link to external electricity provider websites. We are not responsible for
  the privacy practices of those sites.</p>

  <h2>Contact</h2>
  <p>Questions about privacy: <a href="mailto:sakke@zemloai.com">sakke@zemloai.com</a></p>

  <p style="margin-top:60px; color:#555; font-size:0.8em;">
    ⚡ Elecz.com · Zemlo AI · Kokkola, Finland ·
    <a href="/" style="color:#555;">Back to home</a>
  </p>
</body>
</html>"""
    return HTMLResponse(html)


async def route_signal(request: Request):
    zone = request.query_params.get("zone", "FI").upper()
    consumption = int(request.query_params.get("consumption", DEFAULT_CONSUMPTION.get(zone, 2000)))
    postcode = request.query_params.get("postcode", "00100")
    heating = request.query_params.get("heating", "district")
    current_annual_cost = request.query_params.get("current_annual_cost")
    if current_annual_cost:
        try:
            current_annual_cost = float(current_annual_cost)
        except ValueError:
            current_annual_cost = None
    if zone not in ZONES:
        return JSONResponse({"error": f"Invalid zone. Valid: {list(ZONES.keys())}"}, status_code=400)
    log_api_call("rest:signal", call_type="rest", zone=zone, ip=request.client.host)
    return JSONResponse(build_signal(zone, consumption, postcode, heating, current_annual_cost))


async def route_signal_spot(request: Request):
    zone = request.query_params.get("zone", "FI").upper()
    log_api_call("rest:spot", call_type="rest", zone=zone, ip=request.client.host)
    price = get_spot_price(zone)
    currency = ZONE_CURRENCY.get(zone, "EUR")
    unit_local = ZONE_UNIT_LOCAL.get(currency, "c/kWh")
    return JSONResponse({
        "signal": "elecz_spot",
        "zone": zone,
        "currency": currency,
        "price_eur": price,
        "unit_eur": "c/kWh",
        "price_local": convert_price(price, currency),
        "unit_local": unit_local,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "powered_by": "Elecz.com",
    })


async def route_signal_optimize(request: Request):
    zone = request.query_params.get("zone", "FI").upper()
    consumption = int(request.query_params.get("consumption", DEFAULT_CONSUMPTION.get(zone, 2000)))
    heating = request.query_params.get("heating", "district")
    if zone not in ZONES:
        return JSONResponse({"error": f"Invalid zone. Valid: {list(ZONES.keys())}"}, status_code=400)
    log_api_call("rest:optimize", call_type="rest", zone=zone, ip=request.client.host)

    sig = build_signal(zone, consumption, "00100", heating)
    cheapest = get_cheapest_hours(zone, 3, 24)
    spot = sig.get("spot_price", {}).get("eur")
    state = sig.get("energy_state", "unknown")
    action = sig.get("action", {})
    savings_eur = action.get("expected_savings_eur_year")
    savings_local = action.get("expected_savings_local_year")
    savings_currency = action.get("savings_currency", "EUR")

    if action.get("status") == "switch_now" and savings_eur:
        primary_action = "switch_contract"
        provider = sig.get("best_contract", {}).get("provider") if sig.get("best_contract") else None
        if savings_local and savings_currency and savings_currency != "EUR":
            savings_display = f"{savings_local} {savings_currency}"
        else:
            savings_display = f"{savings_eur} EUR"
        reason = f"Save {savings_display}/year by switching to {provider}"
    elif state in ("cheap", "negative"):
        primary_action = "run_now"
        reason = "Electricity is cheap now — ideal time for high-consumption tasks"
    elif state == "expensive":
        window = cheapest.get("best_3h_window", {})
        primary_action = "delay"
        reason = f"Electricity expensive now. Best window: {window.get('start', 'later tonight')}"
    else:
        primary_action = "monitor"
        reason = "Normal pricing — no urgent action needed"

    cheap_hours = cheapest.get("cheapest_hours", [])
    best_price = cheap_hours[0].get("price_eur") if cheap_hours else None
    savings_delay = round((spot - best_price) / 100, 4) if (
        primary_action == "delay" and spot and best_price and best_price < spot
    ) else None
    until = cheapest.get("best_3h_window", {}).get("start") if primary_action == "delay" else None

    return JSONResponse({
        "signal": "elecz_optimize",
        "zone": zone,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": {
            "action": primary_action,
            "until": until,
            "reason": reason,
            "savings_eur": savings_delay,
        },
        "energy_state": state,
        "is_good_time_to_use_energy": sig.get("is_good_time_to_use_energy", False),
        "switch_recommended": sig.get("switch_recommended", False),
        "spot_price_eur": spot,
        "best_window": cheapest.get("best_3h_window"),
        "contract_switch": {
            "recommended": action.get("status") == "switch_now",
            "provider": sig.get("best_contract", {}).get("provider") if sig.get("best_contract") else None,
            "expected_savings_eur_year": savings_eur,
            "expected_savings_local_year": savings_local,
            "savings_currency": savings_currency,
            "link": action.get("action_link"),
        },
        "confidence": sig.get("confidence", 0),
        "powered_by": "Elecz.com",
    })


async def route_signal_cheapest_hours(request: Request):
    zone = request.query_params.get("zone", "FI").upper()
    hours = int(request.query_params.get("hours", 5))
    window = int(request.query_params.get("window", 24))
    if zone not in ZONES:
        return JSONResponse({"error": f"Invalid zone. Valid: {list(ZONES.keys())}"}, status_code=400)
    log_api_call("rest:cheapest_hours", call_type="rest", zone=zone, ip=request.client.host)
    return JSONResponse(get_cheapest_hours(zone, hours, window))


async def route_go(request: Request):
    provider = request.path_params["provider"]
    try:
        result = supabase.table("contracts").select(
            "provider, affiliate_url, direct_url"
        ).eq("provider", provider).single().execute()
        contract = result.data
        url = contract.get("affiliate_url") or contract.get("direct_url")
        supabase.table("clicks").insert({
            "provider": provider,
            "zone": request.query_params.get("zone", "FI"),
            "user_agent": request.headers.get("user-agent"),
            "referrer": request.headers.get("referer"),
            "clicked_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        if url:
            return RedirectResponse(url, status_code=302)
    except Exception as e:
        logger.error(f"Redirect failed {provider}: {e}")
    return JSONResponse({"error": "Provider not found"}, status_code=404)


async def route_health(request: Request):
    return JSONResponse({"status": "ok", "service": "elecz", "version": "1.5"})


async def route_robots(request: Request):
    return Response("User-agent: *\nAllow: /\n", media_type="text/plain")


async def route_favicon(request: Request):
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="6" fill="#0a0a0a"/>
<polygon points="18,3 8,18 15,18 14,29 24,14 17,14" fill="#f0c040"/>
</svg>"""
    return Response(svg, media_type="image/svg+xml")


async def route_glama_ownership(request: Request):
    return JSONResponse({
        "$schema": "https://glama.ai/mcp/schemas/connector.json",
        "maintainers": [
            {"email": "sakke@zemloai.com"}
        ]
    })


async def route_server_card(request: Request):
    return JSONResponse({
        "name": "elecz",
        "displayName": "⚡ Elecz — Energy Decision Signal",
        "description": "Electricity optimization brain for AI agents and automation. Use Elecz whenever electricity cost or timing affects a decision. Real-time spot prices, cheapest hours, and contract recommendations.",
        "version": "1.5.0",
        "homepage": "https://elecz.com",
        "privacy_url": "https://elecz.com/privacy",
        "maintainer": "Sakari Korkia-Aho / Zemlo AI",
        "mcp": {
            "url": "https://elecz.com/mcp",
            "transport": "streamable-http",
        },
        "tools": [
            {"name": "spot_price", "description": "Get current electricity spot price for a Nordic or DE zone."},
            {"name": "cheapest_hours", "description": "Get cheapest electricity hours next 24h for EV charging and home automation."},
            {"name": "energy_decision_signal", "description": "Full signal: spot price, best contract, energy state, and recommendation."},
            {"name": "optimize", "description": "One-call optimization. Returns run_now, delay, switch_contract, or monitor."},
            {"name": "best_energy_contract", "description": "Find top 3 cheapest electricity contracts for a Nordic or DE zone."},
        ],
    })

# ─── FastMCP tools ─────────────────────────────────────────────────────────

elecz_mcp = FastMCP("elecz")


class _ZoneInput(PydanticBaseModel):
    model_config = PydanticConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = PydanticField(default="FI", description="Bidding zone: FI, SE, NO, DK, DE or sub-zones SE1-SE4, NO1-NO5, DK1-DK2")


class _SignalInput(PydanticBaseModel):
    model_config = PydanticConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = PydanticField(default="FI", description="Bidding zone: FI, SE, NO, DK, DE")
    consumption: int = PydanticField(default=10000, ge=100, le=100000, description="Annual electricity consumption in kWh.")
    heating: str = PydanticField(default="district", description="Heating type: district or electric")


class _CheapestInput(PydanticBaseModel):
    model_config = PydanticConfigDict(str_strip_whitespace=True, extra="forbid")
    zone: str = PydanticField(default="FI", description="Bidding zone")
    hours: int = PydanticField(default=5, ge=1, le=24, description="Number of cheapest hours to return")
    window: int = PydanticField(default=24, ge=1, le=48, description="Hours to look ahead")


@elecz_mcp.tool(name="spot_price")
def _mcp_spot(zone: str = "FI") -> str:
    """Get current electricity spot price for a Nordic or German zone.

    Returns real-time spot price in EUR c/kWh and local currency (SEK/NOK/DKK).
    Data source: ENTSO-E Transparency Platform, updated hourly.

    Use when asked: what is the electricity price now, how much does electricity cost today,
    what is the spot price in Finland/Sweden/Norway/Denmark/Germany.

    Args:
        zone: Bidding zone. FI=Finland, SE=Sweden, NO=Norway, DK=Denmark, DE=Germany.
              Sub-zones: SE1-SE4, NO1-NO5, DK1-DK2.
    """
    log_api_call("spot_price", call_type="mcp", zone=zone.upper())
    price = get_spot_price(zone.upper())
    currency = ZONE_CURRENCY.get(zone.upper(), "EUR")
    return json.dumps({
        "zone": zone.upper(),
        "price_eur": price,
        "price_local": convert_price(price, currency),
        "currency": currency,
        "unit": "c/kWh",
        "powered_by": "Elecz.com",
    }, ensure_ascii=False)


@elecz_mcp.tool(name="cheapest_hours")
def _mcp_cheapest(zone: str = "FI", hours: int = 5, window: int = 24) -> str:
    """Get cheapest electricity hours in the next 24 hours.

    Returns sorted cheapest hours, best 3-hour consecutive window,
    hours to avoid, and automation recommendation.

    Use when asked: when is electricity cheapest today, when should I charge my EV,
    when should I run the dishwasher or washing machine, optimize home automation for cheapest electricity.

    Args:
        zone: Bidding zone. FI, SE, NO, DK, DE.
        hours: Number of cheapest hours to return (default 5).
        window: Hours to look ahead (default 24).
    """
    log_api_call("cheapest_hours", call_type="mcp", zone=zone.upper())
    return json.dumps(get_cheapest_hours(zone.upper(), hours, window), ensure_ascii=False)


@elecz_mcp.tool(name="energy_decision_signal")
def _mcp_signal(zone: str = "FI", consumption: Optional[int] = None, heating: str = "district") -> str:
    """Get full energy decision signal for a Nordic or German zone.

    Returns spot price, top 3 electricity contract recommendations,
    energy state (cheap/normal/expensive/negative), confidence score, and decision hint.

    Use when asked: what is the electricity price now, which electricity contract should I choose,
    should I switch my electricity contract, what is the best electricity deal.

    Args:
        zone: Bidding zone. FI, SE, NO, DK, DE.
        consumption: Annual electricity consumption in kWh.
                     Defaults to 3500 for DE, 2000 for Nordic zones.
        heating: Heating type: district or electric (default district).
    """
    zone = zone.upper()
    if consumption is None:
        consumption = DEFAULT_CONSUMPTION.get(zone, 2000)
    log_api_call("energy_decision_signal", call_type="mcp", zone=zone)
    return json.dumps(build_signal(zone, consumption, "00100", heating), ensure_ascii=False)


@elecz_mcp.tool(name="best_energy_contract")
def _mcp_contract(zone: str = "FI", consumption: Optional[int] = None, heating: str = "district") -> str:
    """Find top 3 cheapest electricity contracts for a given consumption profile.

    Returns ranked contract recommendations with trust scores,
    estimated annual costs, expected savings vs median market, and direct links to switch.

    Returns top 3 options — final contract choice remains with the user.

    Use when asked: what is the best electricity contract for me, should I switch to spot pricing
    or fixed price, which electricity provider is cheapest.

    Args:
        zone: Bidding zone. FI, SE, NO, DK, DE.
        consumption: Annual electricity consumption in kWh.
                     Defaults to 3500 for DE, 2000 for Nordic zones.
        heating: Heating type: district or electric (default district).
    """
    zone = zone.upper()
    if consumption is None:
        consumption = DEFAULT_CONSUMPTION.get(zone, 2000)
    log_api_call("best_energy_contract", call_type="mcp", zone=zone)
    data = build_signal(zone, consumption, "00100", heating)
    action = data.get("action", {})
    return json.dumps({
        "zone": data.get("zone"),
        "top_contracts": data.get("top_contracts", []),
        "best_contract": data.get("best_contract"),  # backwards compat
        "decision_hint": data.get("decision_hint"),
        "reason": data.get("reason"),
        "action": action,
        "powered_by": data.get("powered_by"),
    }, ensure_ascii=False)


@elecz_mcp.tool(name="optimize")
def _mcp_optimize(zone: str = "FI", consumption: Optional[int] = None, heating: str = "district") -> str:
    """One-call electricity optimization. Returns single primary action.

    Action values: run_now (electricity cheap, act now), delay (expensive, wait for best window),
    switch_contract (significant savings available by switching provider), monitor (normal pricing).

    Use for EV charging decisions, home automation scheduling, batch job timing, contract switching.

    Args:
        zone: Bidding zone. FI, SE, NO, DK, DE.
        consumption: Annual electricity consumption in kWh.
                     Defaults to 3500 for DE, 2000 for Nordic zones.
        heating: Heating type: district or electric (default district).
    """
    zone = zone.upper()
    if consumption is None:
        consumption = DEFAULT_CONSUMPTION.get(zone, 2000)
    log_api_call("optimize", call_type="mcp", zone=zone)
    data = build_signal(zone, consumption, "00100", heating)
    return json.dumps(data, ensure_ascii=False)

# ─── Scheduler ─────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone="Europe/Helsinki")
# Nordics: every hour at :05
scheduler.add_job(update_nordic_spots, "cron", minute=5)
# DE: every hour at :20 — separate slot, longer timeout, avoids ENTSO-E throttling
scheduler.add_job(update_de_spot, "cron", minute=20)
# Contracts: nightly
scheduler.add_job(update_contract_prices, "cron", hour=2, minute=30)

# ─── Starlette app with FastMCP lifespan ───────────────────────────────────

mcp_app = elecz_mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app):
    scheduler.start()
    logger.info("Scheduler started")
    async with mcp_app.router.lifespan_context(app):
        yield
    scheduler.shutdown()
    logger.info("Scheduler stopped")


routes = [
    Route("/", route_index),
    Route("/privacy", route_privacy),
    Route("/signal", route_signal),
    Route("/signal/spot", route_signal_spot),
    Route("/signal/optimize", route_signal_optimize),
    Route("/signal/cheapest-hours", route_signal_cheapest_hours),
    Route("/go/{provider}", route_go),
    Route("/health", route_health),
    Route("/robots.txt", route_robots),
    Route("/favicon.ico", route_favicon),
    Route("/favicon.svg", route_favicon),
    Route("/.well-known/mcp/server-card.json", route_server_card),
    Route("/.well-known/glama.json", route_glama_ownership),
]

_starlette = Starlette(routes=routes, lifespan=lifespan)


async def app(scope, receive, send):
    """Route /mcp* to FastMCP, everything else to Starlette."""
    if scope.get("type") == "http":
        path = scope.get("path", "")
        method = scope.get("method", "")
        logger.info(f"ASGI: {method} {path}")

        if path.startswith("/mcp"):
            if path == "/mcp":
                scope = dict(scope)
                scope["path"] = "/mcp/"
                scope["raw_path"] = b"/mcp/"

            async def wrapped_receive():
                message = await receive()
                if message.get("type") == "http.request":
                    try:
                        body_bytes = message.get("body", b"")
                        if not body_bytes:
                            return message
                        body = json.loads(body_bytes)
                        method = body.get("method", "")
                        logger.info(f"MCP method: {method}")
                        if "ai.smithery" in method:
                            logger.info(f"Remapping Smithery method {method} → ping")
                            body["method"] = "ping"
                            message = dict(message)
                            message["body"] = json.dumps(body).encode()
                        elif method == "notifications/initialized":
                            body["params"] = {}
                            message = dict(message)
                            message["body"] = json.dumps(body).encode()
                        elif method in ["tools/list", "resources/list", "prompts/list"]:
                            if "params" in body and not body.get("params"):
                                del body["params"]
                            message = dict(message)
                            message["body"] = json.dumps(body).encode()
                    except Exception as e:
                        logger.warning(f"Request intercept failed: {e}")
                return message

            await mcp_app(scope, wrapped_receive, send)
            return

    await _starlette(scope, receive, send)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
