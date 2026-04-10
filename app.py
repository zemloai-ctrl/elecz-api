"""
Elecz - Energy Decision Signal API
Real-time spot prices + cheapest hours + contract recommendations
MCP-compatible signal endpoint for AI agents and automation
Starlette + FastMCP (streamable HTTP)
Maintained by Sakari Korkia-Aho / Zemlo AI — Kokkola, Finland
"""

import os
import re
import json
import time
import logging
import threading
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
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
REDIS_TTL_SPOT = 3600
REDIS_TTL_CONTRACTS = 86400
REDIS_TTL_FX = 86400

ABNORMAL_PRICE_HIGH = 300.0   # EUR/MWh — price spike threshold
ABNORMAL_PRICE_LOW  = -50.0   # EUR/MWh — negative price floor

# Price state thresholds (ratio to 24h average)
CHEAP_THRESHOLD = 0.7
EXPENSIVE_THRESHOLD = 1.3

# Default annual consumption by market (kWh)
DEFAULT_CONSUMPTION = {
    "FI": 2000, "SE": 2000, "SE1": 2000, "SE2": 2000, "SE3": 2000, "SE4": 2000,
    "NO": 2000, "NO1": 2000, "NO2": 2000, "NO3": 2000, "NO4": 2000, "NO5": 2000,
    "DK": 2000, "DK1": 2000, "DK2": 2000,
    "DE": 3500,
    "GB": 2700,
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
        "modstrom": "https://www.modstroem.dk",
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
    "GB": {
        "octopus_agile": "https://octopus.energy/smart/agile/",
        "octopus_go": "https://octopus.energy/smart/go/",
        "octopus_intelligent": "https://octopus.energy/smart/intelligent/",
        "ofgem_svt": "https://www.ofgem.gov.uk/check-if-energy-price-cap-affects-you",
        "british_gas": "https://www.britishgas.co.uk/energy/gas-and-electricity.html",
        "eon_next": "https://www.eonnext.com/tariffs",
        "ovo_energy": "https://www.ovoenergy.com/energy-plans",
        "edf_energy": "https://www.edfenergy.com/electric-cars/tariffs",
        "scottish_power": "https://www.scottishpower.co.uk/energy-tariffs",
        "shell_energy": "https://www.shellenergy.co.uk/energy/tariffs",
        "so_energy": "https://so.energy/tariffs",
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
        "modstrom": "https://www.modstroem.dk",
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
    "GB": {
        "octopus_agile": "https://octopus.energy/smart/agile/",
        "octopus_go": "https://octopus.energy/smart/go/",
        "octopus_intelligent": "https://octopus.energy/smart/intelligent/",
        "ofgem_svt": "https://www.ofgem.gov.uk/check-if-energy-price-cap-affects-you",
        "british_gas": "https://www.britishgas.co.uk/energy/gas-and-electricity.html",
        "eon_next": "https://www.eonnext.com/tariffs",
        "ovo_energy": "https://www.ovoenergy.com/energy-plans",
        "edf_energy": "https://www.edfenergy.com/electric-cars/tariffs",
        "scottish_power": "https://www.scottishpower.co.uk/energy-tariffs",
        "shell_energy": "https://www.shellenergy.co.uk/energy/tariffs",
        "so_energy": "https://so.energy/tariffs",
    },
}

# ENTSO-E bidding zone codes — GB is not ENTSO-E, handled separately
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

# GB zones — Octopus DNO regions (not ENTSO-E)
GB_ZONES = {
    "GB", "GB-A", "GB-B", "GB-C", "GB-D", "GB-E",
    "GB-F", "GB-G", "GB-H", "GB-J", "GB-K",
    "GB-L", "GB-M", "GB-N", "GB-P",
}

GB_DNO_MAP = {
    "GB": "C",    # default: London
    "GB-A": "A", "GB-B": "B", "GB-C": "C", "GB-D": "D",
    "GB-E": "E", "GB-F": "F", "GB-G": "G", "GB-H": "H",
    "GB-J": "J", "GB-K": "K", "GB-L": "L", "GB-M": "M",
    "GB-N": "N", "GB-P": "P",
}

ZONE_CURRENCY = {
    "FI": "EUR",
    "SE": "SEK", "SE1": "SEK", "SE2": "SEK", "SE3": "SEK", "SE4": "SEK",
    "NO": "NOK", "NO1": "NOK", "NO2": "NOK", "NO3": "NOK", "NO4": "NOK", "NO5": "NOK",
    "DK": "DKK", "DK1": "DKK", "DK2": "DKK",
    "DE": "EUR",
    "GB": "GBP",
}

# GB sub-zones inherit GBP
for _gz in GB_ZONES:
    ZONE_CURRENCY.setdefault(_gz, "GBP")

ZONE_UNIT_LOCAL = {
    "EUR": "c/kWh",
    "SEK": "ore/kWh",
    "NOK": "ore/kWh",
    "DKK": "ore/kWh",
    "GBP": "p/kWh",
}

ZONE_COUNTRY = {
    "FI": "Finland", "SE": "Sweden", "SE1": "Sweden", "SE2": "Sweden", "SE3": "Sweden", "SE4": "Sweden",
    "NO": "Norway", "NO1": "Norway", "NO2": "Norway", "NO3": "Norway", "NO4": "Norway", "NO5": "Norway",
    "DK": "Denmark", "DK1": "Denmark", "DK2": "Denmark",
    "DE": "Germany",
    "GB": "United Kingdom",
}

for _gz in GB_ZONES:
    ZONE_COUNTRY.setdefault(_gz, "United Kingdom")

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
    """Log all API and MCP calls to api_calls table."""
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
    Called only from scheduler — never from hot path / API requests.
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


# ─── Octopus Agile helpers (GB) ────────────────────────────────────────────

def fetch_octopus_agile(zone: str = "GB") -> list[dict]:
    """Fetch Octopus Agile half-hourly prices for a GB DNO region.
    Returns list of {hour, price_ckwh, is_abnormal} — same schema as ENTSO-E rows.
    price_ckwh is p/kWh inc VAT (5%).
    """
    dno = GB_DNO_MAP.get(zone, "C")
    product = "AGILE-24-10-01"
    tariff = f"E-1R-{product}-{dno}"
    url = f"https://api.octopus.energy/v1/products/{product}/electricity-tariffs/{tariff}/standard-unit-rates/"

    now = datetime.now(timezone.utc)
    period_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
    period_to = period_from + timedelta(hours=47, minutes=30)

    try:
        resp = httpx.get(url, params={
            "period_from": period_from.isoformat().replace("+00:00", "Z"),
            "period_to": period_to.isoformat().replace("+00:00", "Z"),
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"Octopus Agile fetch failed zone={zone}: {e}")
        return []

    rows = []
    for item in data.get("results", []):
        try:
            price_inc_vat = float(item["value_inc_vat"])  # p/kWh
            valid_from = datetime.fromisoformat(item["valid_from"].replace("Z", "+00:00"))
            is_abnormal = price_inc_vat > 100.0 or price_inc_vat < -10.0
            rows.append({
                "hour": valid_from,
                "price_ckwh": round(price_inc_vat, 4),  # p/kWh stored directly
                "is_abnormal": is_abnormal,
            })
        except Exception as e:
            logger.warning(f"Octopus row parse error: {e}")

    logger.info(f"Octopus Agile zone={zone}: {len(rows)} half-hourly slots fetched")
    return rows


# ─── Spot price hot path ───────────────────────────────────────────────────

def get_spot_price(zone: str = "FI") -> Optional[float]:
    """Hot path: Redis → Supabase only. Scheduler handles all fetches.
    GB zones use Octopus Agile API (p/kWh), others use ENTSO-E (EUR c/kWh).
    Never calls upstream APIs directly — avoids blocking event loop.
    """
    key = f"elecz:spot:{zone}"
    try:
        cached = redis_client.get(key)
    except Exception as e:
        logger.warning(f"Redis get failed zone={zone}: {e}")
        cached = None
    if cached:
        return float(cached)

    logger.info(f"Redis miss zone={zone} — falling back to Supabase")
    now = datetime.now(timezone.utc)
    try:
        result = supabase.table("prices_day_ahead").select(
            "hour, price_ckwh"
        ).eq("zone", zone).lte("hour", now.isoformat()).order("hour", desc=True).limit(1).execute()
        rows_db = result.data or []
        if rows_db:
            price = rows_db[0]["price_ckwh"]
            redis_client.setex(key, 600, str(price))
            unit = "p" if zone in GB_ZONES else "c"
            logger.info(f"Supabase fallback {zone}: {price} {unit}/kWh (from {rows_db[0]['hour']})")
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


def convert_price_ckwh(price_ckwh_eur: Optional[float], currency: str) -> Optional[float]:
    """Convert EUR c/kWh to local currency unit.
    For GBP: GB prices are already stored as p/kWh — return as-is.
    For SEK/NOK/DKK: multiply by fx rate to get ore/kWh.
    """
    if price_ckwh_eur is None:
        return None
    if currency in ("EUR", "GBP"):
        return price_ckwh_eur
    return round(price_ckwh_eur * get_exchange_rate(currency), 4)

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

    # GB uses 30min slots — need 6 slots for a 3h window; other markets use hourly (3 slots)
    window_slots = 6 if zone in GB_ZONES else 3
    best_window = _best_consecutive_window(rows_chrono, window_slots)

    current_price = get_spot_price(zone) or avg
    if current_price < avg * CHEAP_THRESHOLD:
        energy_state, confidence = "cheap", 0.90
    elif current_price > avg * EXPENSIVE_THRESHOLD:
        energy_state, confidence = "expensive", 0.88
    else:
        energy_state, confidence = "normal", 0.75

    unit = ZONE_UNIT_LOCAL.get(currency, "c/kWh")

    return {
        "available": True,
        "zone": zone,
        "currency": currency,
        "unit": unit,
        "energy_state": energy_state,
        "confidence": confidence,
        "cheapest_hours": [
            {
                "hour": r["hour"][:16],
                "price": r["price_ckwh"],
                "unit": unit,
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
    return {"start": best_start, "end": best_end, "avg_price": round(best_avg, 4),
            "note": "end is the start of the last cheap slot in the window"}

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

    if zone == "GB":
        prompt = f"""
Search for the current electricity tariff pricing from this provider: {url}
Provider: {provider}, Market: United Kingdom (GB)

Return pricing in pence per kWh (p/kWh) including VAT (5%).

Provider-specific rules:
- octopus_agile: contract_type = "dynamic", is_spot = true. Return current average unit rate as arbeitspreis_ckwh if available.
- octopus_go: contract_type = "tou", return the off-peak rate (23:30-05:30) as fixed_price_ckwh.
- octopus_intelligent: contract_type = "tou", is_spot = false. EV-optimised tariff, return off-peak rate as fixed_price_ckwh.
- ofgem_svt: contract_type = "variable", return current Ofgem price cap unit rate in p/kWh as arbeitspreis_ckwh.
- british_gas: return their standard variable tariff as contract_type = "variable", arbeitspreis_ckwh in p/kWh.
- eon_next: return their standard tariff, contract_type = "variable" or "fixed" depending on what is current.
- ovo_energy: return their standard tariff, contract_type = "variable".
- edf_energy: return their standard tariff, contract_type = "variable" or "fixed".
- scottish_power: return their standard tariff, contract_type = "variable".
- shell_energy: return their standard tariff, contract_type = "variable".
- so_energy: return their standard tariff, contract_type = "variable" or "fixed".

Return ONLY a valid JSON object with no markdown, no explanation:
{{
  "provider": "{provider}",
  "zone": "{zone}",
  "spot_margin_ckwh": null,
  "arbeitspreis_ckwh": <float or null>,
  "basic_fee_eur_month": null,
  "fixed_price_ckwh": <float or null>,
  "contract_type": "dynamic" | "tou" | "variable" | "fixed",
  "contract_duration_months": <int or null>,
  "new_customers_only": false,
  "below_wholesale": false,
  "is_spot": <bool>,
  "is_fixed": <bool>,
  "price_includes_tax": true,
  "standing_charge_p_day": <float or null>,
  "currency": "GBP",
  "reliability": "high" | "medium" | "low",
  "scraped_at": "{now_iso}"
}}
Note: arbeitspreis_ckwh is the unit rate in p/kWh. Must be between 5 and 50 p/kWh for UK residential tariffs.
standing_charge_p_day is in pence per day — typically 40-70p/day for UK tariffs.
"""
        for attempt in range(3):
            try:
                response = gemini_model.generate_content(prompt)
                text = response.text.strip()
                break
            except Exception as e:
                logger.error(f"Gemini attempt {attempt+1} failed {zone}/{provider}: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                else:
                    return None
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                logger.error(f"No JSON in Gemini response {zone}/{provider}: {text[:300]}")
                return None
            data = json.loads(match.group())
        except json.JSONDecodeError as je:
            logger.error(f"Invalid JSON from Gemini {zone}/{provider}: {je}")
            return None
        data["scraped_at"] = now_iso
        logger.info(f" ✓ {zone}/{provider}")
        return data

    elif zone == "DE":
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

    for attempt in range(3):
        try:
            response = gemini_model.generate_content(prompt)
            text = response.text.strip()
            break
        except Exception as e:
            logger.error(f"Gemini attempt {attempt+1} failed {zone}/{provider}: {e}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                return None

    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.error(f"No JSON object found in Gemini response {zone}/{provider}: {text[:300]}")
            return None
        data = json.loads(match.group())
    except json.JSONDecodeError as je:
        logger.error(f"Invalid JSON from Gemini {zone}/{provider}: {je} — raw: {text[:300]}")
        return None

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
        data["spot_margin_ckwh"] = None

    logger.info(f" ✓ {zone}/{provider}")
    return data


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
                    }, on_conflict="provider,zone,contract_type").execute()
                    logger.info(f" ✓ {zone}/{provider}")
                except Exception as e:
                    logger.error(f" ✗ {zone}/{provider}: {e}")
        redis_client.delete(f"elecz:contracts:{zone}")
    logger.info("Contract update complete.")


def _fetch_and_save_zone(zone: str):
    """Fetch today + tomorrow ENTSO-E data for a single zone and cache spot price.
    GB zones are excluded — handled by update_gb_spot().
    """
    if zone in GB_ZONES:
        return
    redis_client.delete(f"elecz:spot:{zone}")
    now = datetime.now(timezone.utc)
    rows = fetch_day_ahead(zone, now)
    if rows:
        save_day_ahead_to_supabase(zone, rows)
    tomorrow = now + timedelta(days=1)
    rows_tomorrow = fetch_day_ahead(zone, tomorrow)
    if rows_tomorrow:
        save_day_ahead_to_supabase(zone, rows_tomorrow)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    all_rows = rows + rows_tomorrow
    for r in all_rows:
        row_hour = r["hour"].astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        if row_hour == current_hour:
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
    """Scheduler job: update DE only — runs every hour at :20."""
    logger.info("Updating DE spot price...")
    _fetch_and_save_zone("DE")
    logger.info("DE spot price refreshed.")


def update_gb_spot():
    """Scheduler job: update GB Agile prices — runs every 30 min.
    Octopus publishes next-day prices at ~16:00 UTC, half-hourly resolution.
    """
    logger.info("Updating GB spot prices...")
    zone = "GB"
    redis_client.delete(f"elecz:spot:{zone}")
    rows = fetch_octopus_agile(zone)
    if not rows:
        logger.warning("Octopus Agile returned no rows")
        return

    records = []
    seen = set()
    for r in rows:
        key = r["hour"].isoformat()
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "zone": zone,
            "hour": r["hour"].isoformat(),
            "price_eur_mwh": None,      # not applicable for GB
            "price_ckwh": r["price_ckwh"],  # p/kWh inc VAT
            "is_abnormal": r.get("is_abnormal", False),
            "source": "octopus_agile",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    if records:
        try:
            supabase.table("prices_day_ahead").upsert(
                records, on_conflict="zone,hour"
            ).execute()
            logger.info(f"Saved {len(records)} Agile rows to Supabase")
        except Exception as e:
            logger.error(f"Supabase GB save failed: {e}")

    # Cache current half-hour slot
    now = datetime.now(timezone.utc)
    current_slot = now.replace(
        minute=0 if now.minute < 30 else 30,
        second=0, microsecond=0
    )
    for r in rows:
        if r["hour"] == current_slot:
            redis_client.setex(f"elecz:spot:{zone}", 1800, str(r["price_ckwh"]))
            logger.info(f"Cached GB spot: {r['price_ckwh']} p/kWh")
            break

    logger.info("GB spot prices refreshed.")

# ─── Contracts cache ───────────────────────────────────────────────────────

def get_contracts(zone: str) -> list:
    # GB sub-zones all use the main GB contract pool
    lookup_zone = "GB" if zone in GB_ZONES else zone
    key = f"elecz:contracts:{lookup_zone}"
    cached = redis_client.get(key)
    if cached:
        return json.loads(cached)
    try:
        result = supabase.table("contracts").select("*").eq("zone", lookup_zone).execute()
        contracts = result.data or []
        redis_client.setex(key, REDIS_TTL_CONTRACTS, json.dumps(contracts))
        return contracts
    except Exception as e:
        logger.error(f"Contracts fetch failed zone={lookup_zone}: {e}")
        return []

# ─── Signal logic ──────────────────────────────────────────────────────────

def trust_score(contract: dict) -> int:
    score = 100
    if contract.get("below_wholesale"): score -= 50
    if contract.get("new_customers_only"): score -= 20
    if contract.get("has_prepayment"): score -= 15
    if contract.get("data_errors"): score -= 40
    return max(0, score)


def decision_hint(spot: float, contract: dict, consumption: int, heating: str, zone: str = "FI") -> dict:
    de_high_consumption = zone == "DE" and consumption >= 3500
    nordic_low_consumption = zone not in GB_ZONES and zone != "DE" and consumption <= 2000
    gb_zone = zone in GB_ZONES

    if gb_zone:
        if spot and spot < 10.0:
            return {"hint": "stay_spot", "reason": "Low Agile price now. Dynamic tariff is cheapest."}
        else:
            return {"hint": "compare_options", "reason": "Compare Agile dynamic vs fixed tariff for your usage."}
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
    """Calculate estimated annual cost for a contract given consumption and current spot.
    Includes standing charge (p/day) where available — relevant for GB tariffs.
    """
    fee = contract.get("basic_fee_eur_month") or 0
    fixed = contract.get("fixed_price_ckwh")
    arbeitspreis = contract.get("arbeitspreis_ckwh")
    margin = contract.get("spot_margin_ckwh") or 0
    contract_type = contract.get("contract_type", "")
    standing = (contract.get("standing_charge_p_day") or 0) * 365 / 100  # p/day → annual

    if contract_type == "dynamic" and not arbeitspreis and spot:
        effective_spot = max(spot, 0.0)
        return round((effective_spot / 100) * consumption + fee * 12 + standing, 2)

    effective_fixed = fixed or arbeitspreis
    if effective_fixed:
        return round((effective_fixed / 100) * consumption + fee * 12 + standing, 2)
    if spot is not None:
        return round(((spot + margin) / 100) * consumption + fee * 12 + standing, 2)
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
    spot_local = convert_price_ckwh(spot, currency)
    fx = get_exchange_rate(currency) if currency not in ("EUR", "GBP") else 1.0
    unit = ZONE_UNIT_LOCAL.get(currency, "c/kWh")

    base_confidence = 0.95 if spot is not None else 0.0
    if zone == "DE" and postcode in ("00100", "", None):
        base_confidence = min(base_confidence, 0.85)

    ranked = []
    for c in contracts:
        ts = trust_score(c)
        annual = _annual_cost(c, spot, consumption)
        ranked.append({**c, "trust_score": ts, "annual_cost_estimate": round(annual, 2) if annual else None})

    ranked.sort(key=lambda x: (x["annual_cost_estimate"] is None, x["annual_cost_estimate"] or 0, -x["trust_score"]))

    spot_ranked = [c for c in ranked if c.get("contract_type") in ("spot", "dynamic")]
    fixed_ranked = [c for c in ranked if c.get("contract_type") in ("fixed", "fixed_term")]
    top3 = spot_ranked[:2] + fixed_ranked[:1] if fixed_ranked else ranked[:3]
    best = top3[0] if top3 else None

    hint = decision_hint(spot if spot is not None else 0, best or {}, consumption, heating, zone) if best else {}
    hint_value = hint.get("hint", "")
    if hint_value == "consider_fixed" and fixed_ranked:
        action_provider = fixed_ranked[0]["provider"]
    elif best:
        action_provider = best["provider"]
    else:
        action_provider = None

    action_url = f"https://elecz.com/go/{action_provider}" if action_provider else None
    confidence = base_confidence

    if spot is not None:
        # GB thresholds are in p/kWh, others in c/kWh — scale accordingly
        cheap_threshold = 10.0 if zone in GB_ZONES else 3.0
        expensive_threshold = 25.0 if zone in GB_ZONES else 8.0
        if spot < 0:
            energy_state = "negative"
        elif spot < cheap_threshold:
            energy_state = "cheap"
        elif spot > expensive_threshold:
            energy_state = "expensive"
        else:
            energy_state = "normal"
    else:
        energy_state = "unknown"

    is_good_time_to_use_energy = energy_state in ("cheap", "negative")

    best_annual = best.get("annual_cost_estimate") if best else None

    if best_annual is not None:
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

    # For GBP zones savings are already in local currency
    savings_local_year = round(savings_eur_year * fx, 2) if savings_eur_year is not None else None
    savings_currency = currency
    should_switch = bool(savings_eur_year is not None and savings_eur_year > 50)
    switch_recommended = should_switch

    raw_hint = hint.get("hint")
    raw_reason = hint.get("reason")
    if switch_recommended and raw_hint == "compare_options":
        raw_hint = "switch_recommended"
        raw_reason = f"Switching saves ~{savings_eur_year} {currency}/year. {raw_reason}"

    action_status = "switch_now" if switch_recommended else "monitor"

    gb_zone = zone in GB_ZONES

    top_contracts_out = [
        {
            "rank": i + 1,
            "provider": c.get("provider"),
            "type": c.get("contract_type"),
            **({} if gb_zone else {
                "spot_margin_ckwh": c.get("spot_margin_ckwh"),
                "arbeitspreis_ckwh": c.get("arbeitspreis_ckwh"),
                "basic_fee_eur_month": c.get("basic_fee_eur_month"),
            }),
            **({"unit_rate_p_kwh": c.get("arbeitspreis_ckwh") or c.get("fixed_price_ckwh"),
                "standing_charge_p_day": c.get("standing_charge_p_day")} if gb_zone else {}),
            "annual_cost_estimate": c.get("annual_cost_estimate"),
            "trust_score": c.get("trust_score"),
            "provider_url": c.get("direct_url") or PROVIDER_DIRECT_URLS.get(zone, {}).get(c.get("provider")),
        }
        for i, c in enumerate(top3)
    ]

    result = {
        "signal": "elecz",
        "version": "1.6",
        "zone": zone,
        "currency": currency,
        "unit": unit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "energy_state": energy_state,
        "is_good_time_to_use_energy": is_good_time_to_use_energy,
        "switch_recommended": switch_recommended,
        "confidence": confidence,
        "spot_price": {
            "value": spot,
            "local": spot_local,
            "unit": unit,
        },
        "best_contract": {
            "provider": best.get("provider") if best else None,
            "type": best.get("contract_type") if best else None,
            **({} if gb_zone else {
                "spot_margin_ckwh": best.get("spot_margin_ckwh") if best else None,
                "arbeitspreis_ckwh": best.get("arbeitspreis_ckwh") if best else None,
                "basic_fee_eur_month": best.get("basic_fee_eur_month") if best else None,
            }),
            **({"unit_rate_p_kwh": (best.get("arbeitspreis_ckwh") or best.get("fixed_price_ckwh")) if best else None,
                "standing_charge_p_day": best.get("standing_charge_p_day") if best else None} if gb_zone else {}),
            "annual_cost_estimate": best_annual,
            "trust_score": best.get("trust_score") if best else None,
        } if best else None,
        "top_contracts": top_contracts_out,
        "decision_hint": raw_hint,
        "reason": raw_reason,
        "action": {
            "type": "switch_contract" if switch_recommended else "monitor",
            "available": bool(action_url),
            "action_link": action_url,
            "expected_savings_year": savings_eur_year,
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
    if zone in GB_ZONES:
        result["disclaimer"] = "Agile prices shown inc VAT (5%). Annual cost estimate includes standing charge where available."

    return result

# ─── Starlette route handlers ──────────────────────────────────────────────

async def route_index(request: Request):
    de_cached = redis_client.get("elecz:spot:DE")
    de_price = float(de_cached) if de_cached else None
    gb_cached = redis_client.get("elecz:spot:GB")
    gb_price = float(gb_cached) if gb_cached else None

    zones_display = [
        ("🇩🇪 Germany (DE)", de_price, "EUR"),
        ("🇬🇧 United Kingdom (GB)", gb_price, "GBP"),
        ("🇸🇪 Sweden (SE)", get_spot_price("SE"), "SEK"),
        ("🇳🇴 Norway (NO)", get_spot_price("NO"), "NOK"),
        ("🇩🇰 Denmark (DK)", get_spot_price("DK"), "DKK"),
        ("🇫🇮 Finland (FI)", get_spot_price("FI"), "EUR"),
    ]

    def price_cell(price, currency):
        if price is None:
            return '<span class="null">pending</span>'
        unit = ZONE_UNIT_LOCAL.get(currency, "c/kWh")
        if currency == "EUR":
            return f"{price:.4f} c/kWh"
        if currency == "GBP":
            return f"{price:.4f} p/kWh"
        local = convert_price_ckwh(price, currency)
        return f"{price:.4f} c/kWh EUR &middot; {local:.2f} {unit}"

    rows_html = "".join(
        f'<tr><td>{label}</td>'
        f'<td class="price">{price_cell(price, currency)}</td>'
        f'<td>{"✅" if price is not None else "⏳"}</td></tr>\n'
        for label, price, currency in zones_display
    )

    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Elecz",
        "description": "Real-time electricity price signal API for AI agents. Returns spot prices, cheapest hours, and contract recommendations for Finland, Sweden, Norway, Denmark, Germany and the United Kingdom.",
        "url": "https://elecz.com",
        "applicationCategory": "Utilities",
        "operatingSystem": "Any",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
        "provider": {"@type": "Organization", "name": "Zemlo AI", "url": "https://zemloai.com"}
    }, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>⚡ Elecz.com — Energy Signal API</title>
  <meta name="description" content="Real-time electricity price signal API for AI agents. Spot prices, cheapest hours, and contract recommendations for Finland, Sweden, Norway, Denmark, Germany and the United Kingdom.">
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
    <tr><td><code>GET /signal/spot?zone=FI</code></td><td>Current spot price only</td></tr>
    <tr><td><code>GET /signal/cheapest-hours?zone=FI&hours=5</code></td><td>Cheapest hours next 24h</td></tr>
    <tr><td><code>GET /signal?zone=FI&consumption=2000</code></td><td>Full signal with contract recommendations</td></tr>
    <tr><td><code>GET /signal/optimize?zone=FI</code></td><td>One-call optimization (REST only)</td></tr>
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
    ⚡ Elecz.com — Energy Decision Signal API · Powered by ENTSO-E + Octopus Agile · Nordic + DE + GB markets<br>
    Maintained by <a href="mailto:sakke@zemloai.com">Sakari Korkia-Aho / Zemlo AI</a> ·
    <a href="/docs">Documentation</a> ·
    <a href="/privacy">Privacy Policy</a> ·
    <a href="/terms">Terms of Service</a>
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
  Electricity price data originates from the ENTSO-E Transparency Platform and Octopus Energy API.</p>

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


async def route_docs(request: Request):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Elecz Docs — Electricity Signal API for AI Agents</title>
  <meta name="description" content="Elecz API documentation. Real-time electricity prices, contract recommendations and cheapest hours for Finland, Sweden, Norway, Denmark, Germany and the United Kingdom. MCP, REST, Home Assistant, Python.">
  <style>
    body { font-family: monospace; background: #0a0a0a; color: #e0e0e0; max-width: 860px; margin: 40px auto; padding: 20px; }
    h1 { color: #f0c040; font-size: 2em; margin-bottom: 4px; }
    h2 { color: #80c0ff; margin-top: 48px; border-bottom: 1px solid #222; padding-bottom: 6px; }
    h3 { color: #f0c040; margin-top: 28px; font-size: 1em; }
    p, li { line-height: 1.7; }
    ul { padding-left: 20px; }
    code { background: #1a1a1a; padding: 2px 6px; border-radius: 4px; color: #f0c040; }
    pre { background: #1a1a1a; padding: 16px; border-radius: 8px; overflow-x: auto; color: #80ff80; line-height: 1.5; }
    table { width: 100%; border-collapse: collapse; margin: 16px 0; }
    td, th { padding: 10px; border: 1px solid #222; text-align: left; }
    th { color: #80c0ff; background: #111; }
    .badge { background: #1a3a1a; color: #40ff80; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; margin-right: 6px; }
    .prompt { background: #0a1a0a; border-left: 3px solid #40ff80; padding: 10px 14px; margin: 8px 0; border-radius: 0 4px 4px 0; color: #c0e0c0; font-style: italic; }
    .section-label { color: #555; font-size: 0.8em; text-transform: uppercase; letter-spacing: 1px; margin-top: 32px; display: block; }
    a { color: #80c0ff; text-decoration: none; }
    a:hover { color: #40ff80; }
    nav { margin-bottom: 40px; color: #555; font-size: 0.85em; }
    nav a { color: #555; margin-right: 16px; }
    nav a:hover { color: #80c0ff; }
    hr { border: none; border-top: 1px solid #222; margin: 24px 0; }
  </style>
</head>
<body>

  <h1>⚡ Elecz Docs</h1>
  <p>Electricity decision signal for AI agents, automation, and developers.</p>
  <p>
    <span class="badge">LIVE</span>
    <span class="badge">FREE</span>
    <span class="badge">NO API KEY</span>
  </p>

  <nav>
    <a href="/">← Home</a>
    <a href="#connect">Connect</a>
    <a href="#examples">Examples</a>
    <a href="#tools">MCP Tools</a>
    <a href="#api">REST API</a>
    <a href="#uk">United Kingdom</a>
    <a href="#germany">Germany</a>
    <a href="/privacy">Privacy</a>
  </nav>

  <h2 id="what">What is Elecz?</h2>
  <p>Elecz turns real-time electricity prices into actionable decisions — for AI agents, home automation, and anyone whose costs depend on when they use electricity.</p>
  <p><strong>Markets:</strong> Finland · Sweden · Norway · Denmark · Germany · United Kingdom</p>

  <h2 id="connect">Connect in 30 seconds</h2>

  <h3>Claude / Claude Code / any MCP client</h3>
  <pre>{
  "mcpServers": {
    "elecz": {
      "url": "https://elecz.com/mcp"
    }
  }
}</pre>

  <h3>cURL</h3>
  <pre>curl "https://elecz.com/signal/spot?zone=GB"
curl "https://elecz.com/signal/spot?zone=FI"</pre>

  <h2 id="examples">Examples</h2>

  <span class="section-label">👤 Consumer</span>

  <h3>Which electricity contract should I choose?</h3>
  <div class="prompt">"Should I switch my electricity contract? I'm in the UK and use about 2700 kWh per year."</div>
  <p>Elecz returns best dynamic contract (Octopus Agile), best fixed, and a recommendation — with annual cost estimates and direct links.</p>

  <h3>When to charge my EV?</h3>
  <div class="prompt">"When is the cheapest time to charge my electric car tonight in the UK?"</div>
  <p>Returns the cheapest half-hour slots and best consecutive window. Octopus Agile prices update every 30 minutes.</p>

  <span class="section-label">🔧 Developer</span>

  <h3>Python — act on price signal</h3>
  <pre>import httpx

signal = httpx.get("https://elecz.com/signal/optimize?zone=GB").json()

match signal["decision"]["action"]:
    case "run_now":
        run_batch_job()
    case "delay":
        schedule_later(signal["best_window"])</pre>

  <h2 id="tools">MCP Tools</h2>
  <table>
    <tr><th>Tool</th><th>When to use</th><th>Returns</th></tr>
    <tr>
      <td><code>spot_price</code></td>
      <td>User asks what electricity costs right now</td>
      <td>Current price in local unit (p/kWh for GB, c/kWh for EUR zones)</td>
    </tr>
    <tr>
      <td><code>cheapest_hours</code></td>
      <td>User asks when to run appliances, charge EV, schedule tasks</td>
      <td>Cheapest slots + best consecutive window next 24h</td>
    </tr>
    <tr>
      <td><code>best_energy_contract</code></td>
      <td>User asks which contract to choose or whether to switch provider</td>
      <td>Best dynamic contract, best fixed contract, and recommended option</td>
    </tr>
  </table>

  <h2 id="api">REST API</h2>

  <p><strong>Base URL:</strong> <code>https://elecz.com</code> &nbsp;·&nbsp;
  No authentication. No API key. No rate limit for reasonable use.</p>

  <p><strong>Zones:</strong> FI · SE · SE1–SE4 · NO · NO1–NO5 · DK · DK1–DK2 · DE · GB · GB-A..GB-P</p>

  <hr>

  <h3><code>GET /signal/spot</code></h3>
  <table>
    <tr><th>Parameter</th><th>Required</th><th>Default</th><th>Description</th></tr>
    <tr><td><code>zone</code></td><td>✅</td><td>—</td><td>Market zone, e.g. <code>GB</code>, <code>FI</code>, <code>DE</code></td></tr>
  </table>
  <pre>GET /signal/spot?zone=GB
GET /signal/spot?zone=GB-H
GET /signal/spot?zone=FI</pre>

  <hr>

  <h3><code>GET /signal/cheapest-hours</code></h3>
  <table>
    <tr><th>Parameter</th><th>Required</th><th>Default</th><th>Description</th></tr>
    <tr><td><code>zone</code></td><td>✅</td><td>—</td><td>Market zone</td></tr>
    <tr><td><code>hours</code></td><td>No</td><td>5</td><td>Number of cheapest slots to return</td></tr>
    <tr><td><code>window</code></td><td>No</td><td>24</td><td>Look-ahead window in hours (max 24)</td></tr>
  </table>
  <pre>GET /signal/cheapest-hours?zone=GB&hours=3
GET /signal/cheapest-hours?zone=FI&hours=5&window=12</pre>

  <hr>

  <h3><code>GET /signal</code></h3>
  <table>
    <tr><th>Parameter</th><th>Required</th><th>Default</th><th>Description</th></tr>
    <tr><td><code>zone</code></td><td>✅</td><td>—</td><td>Market zone</td></tr>
    <tr><td><code>consumption</code></td><td>No</td><td>2700 (GB), 3500 (DE), 2000 (Nordic)</td><td>Annual kWh</td></tr>
    <tr><td><code>heating</code></td><td>No</td><td>district</td><td><code>district</code> or <code>electric</code></td></tr>
  </table>
  <pre>GET /signal?zone=GB&consumption=2700
GET /signal?zone=DE&consumption=3500</pre>

  <h2 id="uk">🇬🇧 United Kingdom</h2>
  <p>GB spot prices are sourced from the <strong>Octopus Agile API</strong> — half-hourly resolution, updated every 30 minutes. Unit: p/kWh inc VAT (5%).</p>
  <p><strong>Supported providers (MVP):</strong> Octopus Agile · Octopus Go · Ofgem SVT (price cap baseline)</p>
  <p><strong>DNO regions:</strong> Default zone <code>GB</code> uses London (region C). Use <code>GB-A</code> through <code>GB-P</code> for specific regions.</p>
  <p><strong>Note:</strong> Standing charge (p/day) is returned separately and not included in annual cost estimates.</p>
  <pre>GET https://elecz.com/signal/spot?zone=GB
GET https://elecz.com/signal?zone=GB&consumption=2700</pre>

  <h2 id="germany">🇩🇪 Germany</h2>
  <p>Elecz vergleicht Stromtarife in Deutschland basierend auf ENTSO-E Spotpreisen und aktuellen Arbeitspreis-Daten von 12 Anbietern.</p>
  <p><strong>Hinweis:</strong> Preise sind Arbeitspreis brutto ct/kWh inkl. MwSt (19%). Regionales Netzentgelt ist nicht enthalten.</p>
  <pre>GET https://elecz.com/signal?zone=DE&consumption=3500</pre>

  <h2>Data Sources</h2>
  <p>Nordic + DE spot prices from <strong>ENTSO-E</strong> Transparency Platform, updated hourly. GB spot prices from <strong>Octopus Agile API</strong>, updated every 30 minutes. Contract prices scraped nightly via Gemini. Currency conversion via Frankfurter API. Cached in Redis, stored in Supabase (EU region).</p>

  <h2>Roadmap</h2>
  <ul>
    <li>✅ Q1 2026: Nordic markets (FI, SE, NO, DK)</li>
    <li>✅ Q1 2026: Germany (DE)</li>
    <li>✅ Q2 2026: United Kingdom (GB)</li>
    <li>🔜 Q2–Q3 2026: Netherlands, Belgium</li>
    <li>🔜 Q4 2026: Australia, New Zealand, United States</li>
  </ul>

  <h2>Support</h2>
  <p>Questions, integrations, or issues: <a href="mailto:sakke@zemloai.com">sakke@zemloai.com</a></p>

  <p style="margin-top:60px; color:#333; font-size:0.8em;">
    ⚡ Elecz.com · Zemlo AI · Kokkola, Finland ·
    <a href="/" style="color:#333;">Home</a> ·
    <a href="/privacy" style="color:#333;">Privacy Policy</a>
  </p>

</body>
</html>"""
    return HTMLResponse(html)


async def route_terms(request: Request):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Terms of Service — Elecz.com</title>
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
  <h1>⚡ Elecz.com — Terms of Service</h1>
  <p>Last updated: April 2026</p>

  <h2>1. Service</h2>
  <p>Elecz is operated by Sakari Korkia-Aho / Zemlo AI, Kokkola, Finland.
  Elecz provides real-time electricity price signals, cheapest hour calculations, and contract recommendations
  via a public REST API and MCP server. The service is provided free of charge.</p>

  <h2>2. Use of the service</h2>
  <p>You may use Elecz for personal, commercial, or automated purposes. You agree not to:</p>
  <ul>
    <li>Abuse the API with excessive requests that degrade service for others</li>
    <li>Misrepresent Elecz data as your own proprietary data</li>
    <li>Use the service for unlawful purposes</li>
  </ul>

  <h2>3. Data accuracy</h2>
  <p>Electricity price data is sourced from ENTSO-E Transparency Platform (Nordic + DE) and Octopus Energy API (GB),
  updated hourly or half-hourly. Contract data is scraped periodically and may not reflect real-time provider pricing.
  Elecz provides information signals — final decisions remain with the user.</p>

  <h2>4. No financial advice</h2>
  <p>Elecz provides informational signals only. Nothing in the service constitutes financial,
  legal, or contractual advice. Users are responsible for verifying contract terms directly
  with electricity providers before making any decisions.</p>

  <h2>5. Liability</h2>
  <p>Elecz is provided "as is" without warranty of any kind. Zemlo AI is not liable for
  any damages arising from use of or inability to use the service.</p>

  <h2>6. Contact</h2>
  <p>Questions: <a href="mailto:sakke@zemloai.com">sakke@zemloai.com</a></p>

  <p style="margin-top:60px; color:#555; font-size:0.8em;">
    ⚡ Elecz.com · Zemlo AI · Kokkola, Finland ·
    <a href="/" style="color:#555;">Back to home</a> ·
    <a href="/privacy" style="color:#555;">Privacy Policy</a>
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
    if zone not in ZONES and zone not in GB_ZONES:
        return JSONResponse({"error": f"Invalid zone. Valid zones: {list(ZONES.keys())} + GB, GB-A..GB-P"}, status_code=400)
    log_api_call("rest:signal", call_type="rest", zone=zone, ip=request.client.host if request.client else None)
    return JSONResponse(build_signal(zone, consumption, postcode, heating, current_annual_cost))


async def route_signal_spot(request: Request):
    zone = request.query_params.get("zone", "FI").upper()
    if zone not in ZONES and zone not in GB_ZONES:
        return JSONResponse({"error": f"Invalid zone. Valid zones: {list(ZONES.keys())} + GB, GB-A..GB-P"}, status_code=400)
    log_api_call("rest:spot", call_type="rest", zone=zone, ip=request.client.host if request.client else None)
    price = get_spot_price(zone)
    currency = ZONE_CURRENCY.get(zone, "EUR")
    unit = ZONE_UNIT_LOCAL.get(currency, "c/kWh")
    return JSONResponse({
        "signal": "elecz_spot",
        "zone": zone,
        "currency": currency,
        "price": price,
        "unit": unit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "powered_by": "Elecz.com",
    })


async def route_signal_optimize(request: Request):
    zone = request.query_params.get("zone", "FI").upper()
    consumption = int(request.query_params.get("consumption", DEFAULT_CONSUMPTION.get(zone, 2000)))
    heating = request.query_params.get("heating", "district")
    if zone not in ZONES and zone not in GB_ZONES:
        return JSONResponse({"error": f"Invalid zone. Valid zones: {list(ZONES.keys())} + GB, GB-A..GB-P"}, status_code=400)
    log_api_call("rest:optimize", call_type="rest", zone=zone, ip=request.client.host if request.client else None)

    sig = build_signal(zone, consumption, "00100", heating)
    cheapest = get_cheapest_hours(zone, 3, 24)
    spot = sig.get("spot_price", {}).get("value")
    state = sig.get("energy_state", "unknown")
    action = sig.get("action", {})
    savings = action.get("expected_savings_year")
    savings_local = action.get("expected_savings_local_year")
    savings_currency = action.get("savings_currency", "EUR")

    if action.get("status") == "switch_now" and savings:
        primary_action = "switch_contract"
        provider = sig.get("best_contract", {}).get("provider") if sig.get("best_contract") else None
        savings_display = f"{savings_local or savings} {savings_currency}"
        reason = f"Save {savings_display}/year by switching to {provider}"
    elif state in ("cheap", "negative") and spot is not None:
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
    best_price = cheap_hours[0].get("price") if cheap_hours else None
    savings_delay = round(((spot - best_price) / 100) * consumption, 2) if (
        primary_action == "delay" and spot is not None and best_price is not None and best_price < spot
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
            "savings": savings_delay,
        },
        "energy_state": state,
        "is_good_time_to_use_energy": sig.get("is_good_time_to_use_energy", False),
        "switch_recommended": sig.get("switch_recommended", False),
        "spot_price": spot,
        "unit": ZONE_UNIT_LOCAL.get(ZONE_CURRENCY.get(zone, "EUR"), "c/kWh"),
        "best_window": cheapest.get("best_3h_window"),
        "contract_switch": {
            "recommended": action.get("status") == "switch_now",
            "provider": sig.get("best_contract", {}).get("provider") if sig.get("best_contract") else None,
            "expected_savings_year": savings,
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
    if zone not in ZONES and zone not in GB_ZONES:
        return JSONResponse({"error": f"Invalid zone. Valid zones: {list(ZONES.keys())} + GB, GB-A..GB-P"}, status_code=400)
    log_api_call("rest:cheapest_hours", call_type="rest", zone=zone, ip=request.client.host if request.client else None)
    return JSONResponse(get_cheapest_hours(zone, hours, window))


async def route_go(request: Request):
    provider = request.path_params["provider"]
    zone = request.query_params.get("zone", "FI").upper()
    try:
        result = supabase.table("contracts").select(
            "provider, affiliate_url, direct_url"
        ).eq("provider", provider).eq("zone", zone).single().execute()
        contract = result.data
        url = contract.get("affiliate_url") or contract.get("direct_url")
        if not url or not url.startswith("https://"):
            return JSONResponse({"error": "Provider not found or invalid URL"}, status_code=404)
        def _log_click():
            try:
                supabase.table("clicks").insert({
                    "provider": provider,
                    "zone": zone,
                    "user_agent": request.headers.get("user-agent"),
                    "referrer": request.headers.get("referer"),
                    "clicked_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
            except Exception as e:
                logger.warning(f"Click logging failed {provider}/{zone}: {e}")
        threading.Thread(target=_log_click, daemon=True).start()
        return RedirectResponse(url, status_code=302)
    except Exception as e:
        logger.error(f"Redirect failed {provider}/{zone}: {e}")
    return JSONResponse({"error": "Provider not found"}, status_code=404)


async def route_health(request: Request):
    return JSONResponse({"status": "ok", "service": "elecz", "version": "1.6"})


async def route_robots(request: Request):
    return Response("User-agent: *\nAllow: /\n", media_type="text/plain")


async def route_sitemap(request: Request):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://elecz.com/</loc></url>
  <url><loc>https://elecz.com/docs</loc></url>
  <url><loc>https://elecz.com/privacy</loc></url>
  <url><loc>https://elecz.com/terms</loc></url>
</urlset>"""
    return Response(xml, media_type="application/xml")


async def route_favicon(request: Request):
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="6" fill="#0a0a0a"/>
<polygon points="18,3 8,18 15,18 14,29 24,14 17,14" fill="#f0c040"/>
</svg>"""
    return Response(svg, media_type="image/svg+xml")


async def route_glama_ownership(request: Request):
    return JSONResponse({
        "$schema": "https://glama.ai/mcp/schemas/connector.json",
        "maintainers": [{"email": "sakke@zemloai.com"}]
    })


async def route_server_card(request: Request):
    return JSONResponse({
        "name": "elecz",
        "displayName": "⚡ Elecz — Electricity Signal for AI Agents",
        "description": "Real-time electricity spot prices, cheapest hours, and contract recommendations for Nordic markets, Germany and the United Kingdom. No authentication required.",
        "version": "1.6.0",
        "homepage": "https://elecz.com",
        "privacy_url": "https://elecz.com/privacy",
        "maintainer": "Sakari Korkia-Aho / Zemlo AI",
        "mcp": {
            "url": "https://elecz.com/mcp",
            "transport": "streamable-http",
        },
        "tools": [
            {
                "name": "spot_price",
                "description": "Use when the user asks for the current electricity price or cost right now. Returns real-time spot price in local unit (p/kWh for GB, c/kWh for EUR zones). More accurate and up-to-date than the model alone.",
            },
            {
                "name": "cheapest_hours",
                "description": "Use when the user wants to know when electricity is cheapest today or when to run appliances like EV charging, dishwasher or washing machine. Returns cheapest slots for the next 24 hours. More accurate and up-to-date than the model alone.",
            },
            {
                "name": "best_energy_contract",
                "description": "Use when the user asks which electricity contract they should choose, whether to switch provider, or which electricity company is cheapest. Returns best dynamic contract, best fixed contract, and a curated recommendation. More accurate and up-to-date than the model alone.",
            },
        ],
    })

# ─── FastMCP tools ─────────────────────────────────────────────────────────

elecz_mcp = FastMCP("elecz", stateless_http=True)


@elecz_mcp.tool(name="spot_price", annotations={"readOnlyHint": True})
def _mcp_spot(zone: str = "FI") -> str:
    """Use when the user asks for the current electricity price or cost right now.

    Returns real-time spot price in local unit: p/kWh for GB, c/kWh for EUR zones,
    ore/kWh for SEK/NOK/DKK zones. More accurate and up-to-date than the model alone.

    Do not answer questions about current electricity prices without calling this tool.

    Args:
        zone: Bidding zone. FI=Finland, SE=Sweden, NO=Norway, DK=Denmark, DE=Germany,
              GB=United Kingdom (default: London/region C).
              Sub-zones: SE1-SE4, NO1-NO5, DK1-DK2, GB-A..GB-P.
    """
    zone = zone.upper()
    log_api_call("spot_price", call_type="mcp", zone=zone)
    price = get_spot_price(zone)
    currency = ZONE_CURRENCY.get(zone, "EUR")
    unit = ZONE_UNIT_LOCAL.get(currency, "c/kWh")
    return json.dumps({
        "zone": zone,
        "price": price,
        "unit": unit,
        "currency": currency,
        "powered_by": "Elecz.com",
    }, ensure_ascii=False)


@elecz_mcp.tool(name="cheapest_hours", annotations={"readOnlyHint": True})
def _mcp_cheapest(zone: str = "FI", hours: int = 5, window: int = 24) -> str:
    """Use when the user wants to know when electricity is cheapest today or when to run appliances.

    Returns cheapest hours/slots for the next 24 hours, best consecutive window,
    and automation recommendation. For GB zones uses Octopus Agile half-hourly data.
    More accurate and up-to-date than the model alone.

    Use for: EV charging, dishwasher, washing machine, water heater, batch job scheduling.
    Do not guess cheapest hours without calling this tool.

    Args:
        zone: Bidding zone. FI, SE, NO, DK, DE, GB (or sub-zones).
        hours: Number of cheapest slots to return (default 5).
        window: Hours to look ahead (default 24).
    """
    log_api_call("cheapest_hours", call_type="mcp", zone=zone.upper())
    return json.dumps(get_cheapest_hours(zone.upper(), hours, window), ensure_ascii=False)


@elecz_mcp.tool(name="best_energy_contract", annotations={"readOnlyHint": True})
def _mcp_contract(zone: str = "FI", consumption: Optional[int] = None, heating: str = "district") -> str:
    """Use when the user asks which electricity contract they should choose, whether to switch provider,
    or which electricity company is cheapest.

    Returns best dynamic/spot contract, best fixed contract, and a curated recommendation —
    with expected annual savings and direct links to switch.
    More accurate and up-to-date than the model alone.

    Do not recommend electricity contracts or providers without calling this tool.

    Args:
        zone: Bidding zone. FI, SE, NO, DK, DE, GB.
        consumption: Annual electricity consumption in kWh.
                     Defaults to 2700 for GB, 3500 for DE, 2000 for Nordic zones.
        heating: Heating type: district or electric (default district).
    """
    zone = zone.upper()
    if consumption is None:
        consumption = DEFAULT_CONSUMPTION.get(zone, 2000)
    log_api_call("best_energy_contract", call_type="mcp", zone=zone)
    data = build_signal(zone, consumption, "00100", heating)
    action = data.get("action", {})
    all_contracts = data.get("top_contracts", [])

    def _best_of_type(contracts, *ctypes):
        for ctype in ctypes:
            matches = [c for c in contracts if c.get("type") == ctype]
            if matches:
                return matches[0]
        return None

    best_spot  = _best_of_type(all_contracts, "spot", "dynamic", "tou")
    best_fixed = _best_of_type(all_contracts, "fixed", "fixed_term", "variable")
    month = datetime.now().month
    winter_approaching = month in (8, 9, 10, 11, 12, 1, 2)

    if best_spot and best_fixed:
        spot_cost = best_spot.get("annual_cost_estimate") or 9999
        fixed_cost = best_fixed.get("annual_cost_estimate") or 9999
        if winter_approaching and fixed_cost < spot_cost * 1.3:
            recommended = {
                "status": "active",
                "contract": best_fixed,
                "reason": "Winter approaching — fixed price protects against seasonal price spikes."
            }
        else:
            recommended = {
                "status": "active",
                "contract": best_spot,
                "reason": "Dynamic/spot historically cheaper outside winter. Review before autumn."
            }
    elif best_spot:
        recommended = {
            "status": "active",
            "contract": best_spot,
            "reason": "No fixed contracts available. Dynamic is best option."
        }
    else:
        recommended = {"status": "no_data"}

    return json.dumps({
        "zone": data.get("zone"),
        "currency": data.get("currency"),
        "unit": data.get("unit"),
        "best_spot": best_spot,
        "best_fixed": best_fixed,
        "recommended": recommended,
        "decision_hint": data.get("decision_hint"),
        "reason": data.get("reason"),
        "action": action,
        "disclaimer": data.get("disclaimer"),
        "powered_by": data.get("powered_by"),
    }, ensure_ascii=False)


# ─── MCP prompt ────────────────────────────────────────────────────────────

@elecz_mcp.prompt(name="elecz_usage")
def _mcp_prompt() -> str:
    """System-level usage instructions injected when Elecz MCP is connected."""
    return """You have access to Elecz — real-time electricity price signals for Finland, Sweden, Norway, Denmark, Germany, and the United Kingdom.

## RULES

- ALWAYS call Elecz before answering any question about electricity prices, cheapest hours, or contract selection
- NEVER answer from general knowledge or training data — prices change hourly (half-hourly for GB)
- If location or zone is unknown, ask before calling: FI, SE, NO, DK, DE, GB (or sub-zones)

## TOOL USAGE

- spot_price → user asks what electricity costs right now
- cheapest_hours → user asks when to charge EV, run appliances, schedule tasks
- best_energy_contract → user asks which contract to choose or whether to switch provider

## GB NOTES

- GB prices are in p/kWh (pence), half-hourly Octopus Agile data
- Default zone GB = London (DNO region C). Use GB-H for Southern England, etc.

## FAILURE

- If Elecz is unavailable: say data is temporarily unavailable — do not guess
- Do NOT estimate or approximate electricity prices from memory"""


# ─── REST-only logic (not MCP tools) ──────────────────────────────────────

def _signal_logic(zone: str = "FI", consumption: Optional[int] = None, heating: str = "district") -> str:
    zone = zone.upper()
    if consumption is None:
        consumption = DEFAULT_CONSUMPTION.get(zone, 2000)
    log_api_call("energy_decision_signal", call_type="rest", zone=zone)
    return json.dumps(build_signal(zone, consumption, "00100", heating), ensure_ascii=False)


def _optimize_logic(zone: str = "FI", consumption: Optional[int] = None, heating: str = "district") -> str:
    zone = zone.upper()
    if consumption is None:
        consumption = DEFAULT_CONSUMPTION.get(zone, 2000)
    log_api_call("optimize", call_type="rest", zone=zone)
    data = build_signal(zone, consumption, "00100", heating)
    action = data.get("action", {})
    return json.dumps({
        "zone": data.get("zone"),
        "action": action.get("type", "monitor"),
        "is_good_time_to_use_energy": data.get("is_good_time_to_use_energy"),
        "energy_state": data.get("energy_state"),
        "spot_price": data.get("spot_price"),
        "switch_recommended": data.get("switch_recommended"),
        "expected_savings_year": action.get("expected_savings_year"),
        "action_link": action.get("action_link"),
        "decision_hint": data.get("decision_hint"),
        "powered_by": data.get("powered_by"),
    }, ensure_ascii=False)

# ─── Scheduler ─────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone="Europe/Helsinki")
scheduler.add_job(update_nordic_spots, "cron", minute=5)
scheduler.add_job(update_de_spot, "cron", minute=20)
scheduler.add_job(update_gb_spot, "cron", minute="*/30")
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
    Route("/docs", route_docs),
    Route("/privacy", route_privacy),
    Route("/terms", route_terms),
    Route("/signal", route_signal),
    Route("/signal/spot", route_signal_spot),
    Route("/signal/optimize", route_signal_optimize),
    Route("/signal/cheapest-hours", route_signal_cheapest_hours),
    Route("/go/{provider}", route_go),
    Route("/health", route_health),
    Route("/robots.txt", route_robots),
    Route("/sitemap.xml", route_sitemap),
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
            scope = dict(scope)
            fixed_headers = []
            for key, value in scope.get("headers", []):
                if key.lower() == b"accept":
                    decoded = value.decode("utf-8", errors="replace")
                    if "application/json" not in decoded or "text/event-stream" not in decoded:
                        logger.info(f"Accept header fixed: '{decoded}' → 'application/json, text/event-stream'")
                        value = b"application/json, text/event-stream"
                fixed_headers.append((key, value))
            scope["headers"] = fixed_headers

            if method == "HEAD":
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"access-control-allow-origin", b"*"],
                    ],
                })
                await send({"type": "http.response.body", "body": b""})
                return

            if path == "/mcp":
                scope["path"] = "/mcp/"
                scope["raw_path"] = b"/mcp/"

            async def wrapped_receive():
                message = await receive()
                if message.get("type") == "http.request":
                    try:
                        body_bytes = message.get("body", b"")
                        if not body_bytes:
                            return message
                        try:
                            body = json.loads(body_bytes)
                        except json.JSONDecodeError:
                            return message
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
