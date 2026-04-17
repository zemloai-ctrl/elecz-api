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
from urllib.parse import quote
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse, RedirectResponse, Response
from starlette.routing import Route, Mount
from starlette.middleware.cors import CORSMiddleware
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
AEMO_API_URL = "https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY"
EM6_FREE_API_URL = "https://api.em6.co.nz/ords/em6/data_api/price/free_24hrs/"

# NZ reference nodes — industry standard proxies for NI/SI wholesale price
NZ_REFERENCE_NODES = {
    "NZ-NI": "HAY2201",  # Haywards — HVDC entry point, canonical NI price
    "NZ-SI": "BEN2201",  # Benmore — major hydro node, canonical SI price
}
REDIS_TTL_SPOT = 3600
REDIS_TTL_CONTRACTS = 86400
REDIS_TTL_FX = 86400

ABNORMAL_PRICE_HIGH = 300.0
ABNORMAL_PRICE_LOW  = -50.0

CHEAP_THRESHOLD = 0.7
EXPENSIVE_THRESHOLD = 1.3

DEFAULT_CONSUMPTION = {
    "FI": 2000, "SE": 2000, "SE1": 2000, "SE2": 2000, "SE3": 2000, "SE4": 2000,
    "NO": 2000, "NO1": 2000, "NO2": 2000, "NO3": 2000, "NO4": 2000, "NO5": 2000,
    "DK": 2000, "DK1": 2000, "DK2": 2000,
    "DE": 3500,
    "GB": 2700,
    "ES": 3000, "PT": 2800, "HR": 3000, "BG": 3500, "SI": 3500, "SK": 3500, "GR": 3500,
    "AU-NSW": 4500, "AU-VIC": 4500, "AU-QLD": 4500, "AU-SA": 4500, "AU-TAS": 4500,
    "NZ-NI": 8000, "NZ-SI": 8000,
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
    "AU": {
        "amber": "https://www.amber.com.au/electricity-plans",
        "agl": "https://www.agl.com.au/electricity",
        "origin": "https://www.originenergy.com.au/electricity",
        "energy_australia": "https://www.energyaustralia.com.au/home/electricity-and-gas",
        "red_energy": "https://www.redenergy.com.au/electricity",
        "alinta": "https://www.alintaenergy.com.au/electricity",
    },
    "NZ": {
        # Flick Electric was acquired by Meridian Energy in July 2025 — brand retired
        "mercury_energy": "https://www.mercury.co.nz/electricity",
        "contact_energy": "https://contact.co.nz/products/electricity",
        "genesis_energy": "https://www.genesisenergy.co.nz/electricity",
        "meridian_energy": "https://www.meridianenergy.co.nz/electricity",
        "electric_kiwi": "https://www.electrickiwi.co.nz/power-plans",
        "contact_energy_ev": "https://contact.co.nz/products/electricity/electric-vehicles",
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
    "AU": {
        "amber": "https://www.amber.com.au",
        "agl": "https://www.agl.com.au",
        "origin": "https://www.originenergy.com.au",
        "energy_australia": "https://www.energyaustralia.com.au",
        "red_energy": "https://www.redenergy.com.au",
        "alinta": "https://www.alintaenergy.com.au",
    },
    "NZ": {
        # Flick Electric was acquired by Meridian Energy in July 2025 — brand retired
        "mercury_energy": "https://www.mercury.co.nz",
        "contact_energy": "https://contact.co.nz",
        "genesis_energy": "https://www.genesisenergy.co.nz",
        "meridian_energy": "https://www.meridianenergy.co.nz",
        "electric_kiwi": "https://www.electrickiwi.co.nz",
        "contact_energy_ev": "https://contact.co.nz/products/electricity/electric-vehicles",
    },
}
ZONES = {
    # Nordics
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
    # Central Europe
    "DE": "10Y1001A1001A82H",
    "NL": "10YNL----------L",
    "BE": "10YBE----------2",
    "AT": "10YAT-APG------L",
    "FR": "10YFR-RTE------C",
    "IT": "10YIT-GRTN-----B",
    "PL": "10YPL-AREA-----S",
    "CZ": "10YCZ-CEPS-----N",
    "HU": "10YHU-MAVIR----U",
    "RO": "10YRO-TEL------P",
    # Southern Europe — batch 2
    "ES": "10YES-REE------0",
    "PT": "10YPT-REN------W",
    "HR": "10YHR-HEP------M",
    "BG": "10YBG-ESO------P",
    "SI": "10YSI-ELES-----O",
    "SK": "10YSK-SEPS-----K",
    "GR": "10YGR-HTSO-----Y",
    # Baltics
    "EE": "10Y1001A1001A39I",
    "LV": "10YLV-1001A00074",
    "LT": "10YLT-1001A0008Q",
}

GB_ZONES = {
    "GB", "GB-A", "GB-B", "GB-C", "GB-D", "GB-E",
    "GB-F", "GB-G", "GB-H", "GB-J", "GB-K",
    "GB-L", "GB-M", "GB-N", "GB-P",
}

GB_DNO_MAP = {
    "GB": "C",
    "GB-A": "A", "GB-B": "B", "GB-C": "C", "GB-D": "D",
    "GB-E": "E", "GB-F": "F", "GB-G": "G", "GB-H": "H",
    "GB-J": "J", "GB-K": "K", "GB-L": "L", "GB-M": "M",
    "GB-N": "N", "GB-P": "P",
}

AU_ZONES = {"AU-NSW", "AU-VIC", "AU-QLD", "AU-SA", "AU-TAS"}
CAISO_ZONES = {"US-CA"}

AU_REGION_MAP = {
    "AU-NSW": "NSW1",
    "AU-VIC": "VIC1",
    "AU-QLD": "QLD1",
    "AU-SA":  "SA1",
    "AU-TAS": "TAS1",
}

NZ_ZONES = {"NZ-NI", "NZ-SI"}
NZ_REGION_MAP = {"NZ-NI": "NI", "NZ-SI": "SI"}

# Static NZ retailer feature flags — updated manually as market changes
# Flick Electric acquired by Meridian Energy July 2025 — no spot pass-through retailers remain
NZ_FEATURES = {
    "electric_kiwi": {
        "free_hour_daily": True,
        "free_hour_note": "Hour of Power — one free hour of electricity per day (off-peak, customer selects time)",
        "ev_charger_network": False,
        "spot_passthrough": False,
    },
    "genesis_energy": {
        "free_hour_daily": False,
        "ev_charger_network": True,
        "ev_charger_note": "Genesis Energy partners with ChargeNet NZ — EV charging costs can be added to monthly bill",
        "spot_passthrough": False,
    },
    "contact_energy": {
        "free_hour_daily": False,
        "ev_charger_network": False,
        "spot_passthrough": False,
    },
    "contact_energy_ev": {
        "free_hour_daily": False,
        "ev_charger_network": False,
        "spot_passthrough": False,
        "ev_optimised": True,
        "ev_note": "Contact Energy EV-specific tariff with off-peak rates for overnight charging",
    },
    "mercury_energy": {
        "free_hour_daily": False,
        "ev_charger_network": False,
        "spot_passthrough": False,
    },
    "meridian_energy": {
        "free_hour_daily": False,
        "ev_charger_network": False,
        "spot_passthrough": False,
        "acquired_flick": True,
        "acquired_flick_note": "Meridian acquired Flick Electric (July 2025). No spot pass-through currently offered.",
    },
}

ZONE_CURRENCY = {
    "FI": "EUR",
    "SE": "SEK", "SE1": "SEK", "SE2": "SEK", "SE3": "SEK", "SE4": "SEK",
    "NO": "NOK", "NO1": "NOK", "NO2": "NOK", "NO3": "NOK", "NO4": "NOK", "NO5": "NOK",
    "DK": "DKK", "DK1": "DKK", "DK2": "DKK",
    "DE": "EUR", "NL": "EUR", "BE": "EUR", "AT": "EUR", "FR": "EUR",
    "IT": "EUR", "PL": "PLN", "CZ": "EUR", "HU": "EUR", "RO": "EUR",
    # Southern Europe batch 2 — all EUR (BG uses EUR on ENTSO-E day-ahead market)
    "ES": "EUR", "PT": "EUR", "HR": "EUR", "BG": "EUR", "SI": "EUR", "SK": "EUR", "GR": "EUR",
    "EE": "EUR", "LV": "EUR", "LT": "EUR",
    "GB": "GBP",
    "AU-NSW": "AUD", "AU-VIC": "AUD", "AU-QLD": "AUD", "AU-SA": "AUD", "AU-TAS": "AUD",
    "NZ-NI": "NZD", "NZ-SI": "NZD",
    "US-CA": "USD",
}

for _gz in GB_ZONES:
    ZONE_CURRENCY.setdefault(_gz, "GBP")

ZONE_UNIT_LOCAL = {
    "EUR": "c/kWh",
    "SEK": "ore/kWh",
    "NOK": "ore/kWh",
    "DKK": "ore/kWh",
    "GBP": "p/kWh",
    "AUD": "c/kWh",
    "NZD": "c/kWh",
    "PLN": "gr/kWh",
    "USD": "c/kWh",
}

ZONE_COUNTRY = {
    "FI": "Finland", "SE": "Sweden", "SE1": "Sweden", "SE2": "Sweden", "SE3": "Sweden", "SE4": "Sweden",
    "NO": "Norway", "NO1": "Norway", "NO2": "Norway", "NO3": "Norway", "NO4": "Norway", "NO5": "Norway",
    "DK": "Denmark", "DK1": "Denmark", "DK2": "Denmark",
    "DE": "Germany", "NL": "Netherlands", "BE": "Belgium", "AT": "Austria",
    "FR": "France", "IT": "Italy", "PL": "Poland", "CZ": "Czech Republic",
    "HU": "Hungary", "RO": "Romania",
    # Southern Europe batch 2
    "ES": "Spain", "PT": "Portugal", "HR": "Croatia", "BG": "Bulgaria",
    "SI": "Slovenia", "SK": "Slovakia", "GR": "Greece",
    "EE": "Estonia", "LV": "Latvia", "LT": "Lithuania",
    "GB": "United Kingdom",
    "AU-NSW": "Australia", "AU-VIC": "Australia", "AU-QLD": "Australia",
    "AU-SA": "Australia", "AU-TAS": "Australia",
    "NZ-NI": "New Zealand", "NZ-SI": "New Zealand",
    "US-CA": "United States",
}

for _gz in GB_ZONES:
    ZONE_COUNTRY.setdefault(_gz, "United Kingdom")

_ENTSOE_ZONES = sorted(ZONES.keys())
_AU_ZONE_LIST = "AU-NSW, AU-VIC, AU-QLD, AU-SA, AU-TAS"
_NZ_ZONE_LIST = "NZ-NI, NZ-SI"
_GB_ZONE_LIST = "GB (+ regional GB-A..GB-P)"
_US_ZONE_LIST = "US-CA"
VALID_ZONES_ERR = (
    f"Invalid zone. Supported: {', '.join(_ENTSOE_ZONES)} | "
    f"{_GB_ZONE_LIST} | {_AU_ZONE_LIST} | {_NZ_ZONE_LIST} | {_US_ZONE_LIST}"
)

supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

# Redis with explicit timeouts to prevent hanging connections on Render restarts
redis_client = redis.from_url(
    os.environ["UPSTASH_REDIS_URL"],
    socket_timeout=5,
    socket_connect_timeout=5,
    retry_on_timeout=True,
)

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
# response_mime_type ensures Gemini returns clean JSON without markdown fences
gemini_model = genai.GenerativeModel(
    "gemini-2.5-flash",
    generation_config={"response_mime_type": "application/json"},
)
ENTSOE_TOKEN = os.environ["ENTSOE_SECURITY_TOKEN"]
# ─── Analytics ─────────────────────────────────────────────────────────────

def log_api_call(tool_name: str, call_type: str = "rest", zone: str = None, ip: str = None):
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
            price_inc_vat = float(item["value_inc_vat"])
            valid_from = datetime.fromisoformat(item["valid_from"].replace("Z", "+00:00"))
            is_abnormal = price_inc_vat > 100.0 or price_inc_vat < -10.0
            rows.append({"hour": valid_from, "price_ckwh": round(price_inc_vat, 4), "is_abnormal": is_abnormal})
        except Exception as e:
            logger.warning(f"Octopus row parse error: {e}")
    logger.info(f"Octopus Agile zone={zone}: {len(rows)} half-hourly slots fetched")
    return rows

# ─── AEMO helpers (AU) ─────────────────────────────────────────────────────

def fetch_aemo() -> list[dict]:
    """Fetch current NEM spot prices from AEMO.
    PRICE field is AUD/MWh — divide by 10 to get AUD c/kWh.
    """
    try:
        resp = httpx.get(AEMO_API_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"AEMO fetch failed: {e}")
        return []
    summary = data.get("ELEC_NEM_SUMMARY", [])
    if not summary:
        logger.warning("AEMO returned empty ELEC_NEM_SUMMARY")
        return []
    aemo_to_zone = {v: k for k, v in AU_REGION_MAP.items()}
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    rows = []
    for item in summary:
        region = item.get("REGIONID", "")
        zone = aemo_to_zone.get(region)
        if not zone:
            continue
        try:
            price_aud_mwh = float(item["PRICE"])
            price_ckwh = round(price_aud_mwh / 10, 4)
            is_abnormal = price_aud_mwh > 3000.0 or price_aud_mwh < -100.0
            rows.append({"zone": zone, "hour": now, "price_ckwh": price_ckwh, "is_abnormal": is_abnormal})
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"AEMO row parse error region={region}: {e}")
    logger.info(f"AEMO fetched {len(rows)} zone prices")
    return rows

# ─── EM6 helpers (NZ) ──────────────────────────────────────────────────────

def fetch_nz_spot() -> list[dict]:
    """Fetch current NZ spot prices from EM6 free 24hrs API.
    Uses industry-standard reference nodes: HAY2201 (NI), BEN2201 (SI).
    Prices are in NZD/MWh — divide by 10 to get NZD c/kWh.
    No authentication required.
    Endpoint: https://api.em6.co.nz/ords/em6/data_api/price/free_24hrs/
    """
    try:
        resp = httpx.get(EM6_FREE_API_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"EM6 free fetch failed: {e}")
        return []
    items = data.get("items", [])
    if not items:
        logger.warning("EM6 free returned empty items")
        return []
    # Find latest trading period for each reference node
    node_latest = {}
    for item in items:
        node = item.get("node_id")
        if node not in NZ_REFERENCE_NODES.values():
            continue
        ts = item.get("timestamp", "")
        if node not in node_latest or ts > node_latest[node]["timestamp"]:
            node_latest[node] = item
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    rows = []
    for nz_zone, node_id in NZ_REFERENCE_NODES.items():
        item = node_latest.get(node_id)
        if not item:
            logger.warning(f"EM6 free: node {node_id} not found for {nz_zone}")
            continue
        try:
            price_nzd_mwh = float(item["price"])
            price_ckwh = round(price_nzd_mwh / 10, 4)
            is_abnormal = price_nzd_mwh > 5000.0 or price_nzd_mwh < -200.0
            rows.append({"zone": nz_zone, "hour": now, "price_ckwh": price_ckwh, "is_abnormal": is_abnormal})
            logger.info(f"EM6 {nz_zone} ({node_id}): {price_nzd_mwh} NZD/MWh = {price_ckwh} c/kWh")
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"EM6 free parse error node={node_id}: {e}")
    logger.info(f"EM6 free fetched {len(rows)} NZ zone prices")
    return rows
# ─── Spot price hot path ───────────────────────────────────────────────────

def get_spot_price(zone: str = "FI") -> Optional[float]:
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
    GBP, AUD, NZD: prices already stored in local unit — return as-is.
    SEK/NOK/DKK: multiply by fx rate.
    """
    if price_ckwh_eur is None:
        return None
    if currency in ("EUR", "GBP", "AUD", "NZD"):
        return price_ckwh_eur
    return round(price_ckwh_eur * get_exchange_rate(currency), 4)

# ─── Cheapest hours ────────────────────────────────────────────────────────

def get_cheapest_hours(zone: str, n_hours: int = 5, window_h: int = 24) -> dict:
    if zone in NZ_ZONES:
        return {
            "available": False, "zone": zone,
            "reason": "New Zealand uses 30-minute real-time trading periods (NZEM). "
                      "Day-ahead price forecasts are not publicly available. "
                      "Use spot_price for current NZD pricing.",
            "powered_by": "Elecz.com",
        }
    if zone in AU_ZONES:
        return {
            "available": False, "zone": zone,
            "reason": "Day-ahead price data is not publicly available for Australian NEM zones. "
                      "Real-time 5-minute spot data is available via spot_price. "
                      "For half-hourly forward prices, consider Amber Electric (registration required).",
            "powered_by": "Elecz.com",
        }
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
        "available": True, "zone": zone, "currency": currency, "unit": unit,
        "energy_state": energy_state, "confidence": confidence,
        "cheapest_hours": [{"hour": r["hour"][:16], "price": r["price_ckwh"], "unit": unit} for r in cheapest],
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

    if zone == "NZ":
        prompt = f"""Search for the current electricity contract pricing from this provider: {url}
Provider: {provider}, Market: New Zealand (NZEM)

Return pricing in New Zealand cents per kWh (NZD c/kWh) including GST (15%).
If price is listed as NZD/kWh, multiply by 100.

Provider-specific rules:
- mercury_energy: standard fixed tariff, contract_type = "fixed"
- contact_energy: standard fixed tariff, contract_type = "fixed"
- contact_energy_ev: EV-specific tariff, contract_type = "fixed"
- genesis_energy: standard fixed tariff, contract_type = "fixed". ChargeNet EV partner.
- meridian_energy: standard fixed tariff, contract_type = "fixed". Acquired Flick Electric July 2025.
- electric_kiwi: cheapest fixed tariff, contract_type = "fixed". Offers Hour of Power daily.

Note: No NZ retailer currently offers spot pass-through (Flick acquired by Meridian July 2025).
Typical NZ usage rates: 20-40 NZD c/kWh incl GST. Daily supply charge: 50-120 NZD c/day.

Return ONLY valid JSON, no markdown:
{{"provider": "{provider}", "zone": "NZ", "spot_margin_ckwh": null,
"arbeitspreis_ckwh": null, "basic_fee_eur_month": null, "fixed_price_ckwh": null,
"contract_type": "fixed", "contract_duration_months": null, "new_customers_only": false,
"below_wholesale": false, "is_spot": false, "is_fixed": true, "price_includes_tax": true,
"standing_charge_p_day": null, "currency": "NZD", "reliability": "high", "scraped_at": "{now_iso}"}}"""

    elif zone == "AU":
        prompt = f"""Search for the current electricity contract pricing from this provider: {url}
Provider: {provider}, Market: Australia (NEM)

Return pricing in Australian cents per kWh (AUD c/kWh) including GST (10%).

Provider-specific rules:
- amber: contract_type = "dynamic", is_spot = true. spot_margin_ckwh is the service fee (9-15 AUD c/kWh). MUST return numeric value — use 11.0 if unknown.
- agl: standard variable tariff, contract_type = "variable"
- origin: standard variable tariff, contract_type = "variable"
- energy_australia: standard variable tariff, contract_type = "variable"
- red_energy: standard fixed tariff, contract_type = "fixed"
- alinta: standard variable tariff, contract_type = "variable"

Typical AU usage rates: 20-45 AUD c/kWh incl GST. Daily supply charge: 80-130 AUD c/day.

Return ONLY valid JSON, no markdown:
{{"provider": "{provider}", "zone": "AU", "spot_margin_ckwh": null,
"arbeitspreis_ckwh": null, "basic_fee_eur_month": null, "fixed_price_ckwh": null,
"contract_type": "variable", "contract_duration_months": null, "new_customers_only": false,
"below_wholesale": false, "is_spot": false, "is_fixed": false, "price_includes_tax": true,
"standing_charge_p_day": null, "currency": "AUD", "reliability": "high", "scraped_at": "{now_iso}"}}"""

    elif zone == "GB":
        prompt = f"""Search for the current electricity tariff pricing from this provider: {url}
Provider: {provider}, Market: United Kingdom (GB)

Return pricing in pence per kWh (p/kWh) including VAT (5%).

Provider-specific rules:
- octopus_agile: contract_type = "dynamic", is_spot = true
- octopus_go: contract_type = "tou", off-peak rate as fixed_price_ckwh
- octopus_intelligent: contract_type = "tou", EV-optimised
- ofgem_svt: contract_type = "variable", Ofgem price cap unit rate
- british_gas/eon_next/ovo_energy/edf_energy/scottish_power/shell_energy/so_energy: contract_type = "variable"

Unit rate must be 5-50 p/kWh. Standing charge: 40-70 p/day.

Return ONLY valid JSON, no markdown:
{{"provider": "{provider}", "zone": "{zone}", "spot_margin_ckwh": null,
"arbeitspreis_ckwh": null, "basic_fee_eur_month": null, "fixed_price_ckwh": null,
"contract_type": "variable", "contract_duration_months": null, "new_customers_only": false,
"below_wholesale": false, "is_spot": false, "is_fixed": false, "price_includes_tax": true,
"standing_charge_p_day": null, "currency": "GBP", "reliability": "high", "scraped_at": "{now_iso}"}}"""

    elif zone == "DE":
        prompt = f"""Search for the current electricity contract pricing from this provider: {url}
Provider: {provider}, Country/zone: {zone}
Assume location: Berlin, PLZ 10115.

IMPORTANT: If provider is "tibber" and zone is "DE", contract_type = "dynamic", is_spot = true, spot_margin_ckwh = null.

Return Arbeitspreis as brutto ct/kWh including MwSt (19%).
If netto price, multiply by 1.19.
Ignore: Neukundenbonus, Sofortbonus, promotional prices. Return only standard ongoing tariff.

arbeitspreis_ckwh must be 5-100 ct/kWh. If in EUR/kWh, multiply by 100.

Return ONLY valid JSON, no markdown:
{{"provider": "{provider}", "zone": "{zone}", "spot_margin_ckwh": null,
"arbeitspreis_ckwh": null, "basic_fee_eur_month": null, "fixed_price_ckwh": null,
"contract_type": "fixed", "contract_duration_months": null, "new_customers_only": false,
"below_wholesale": false, "is_spot": false, "is_fixed": false, "price_includes_tax": true,
"grundpreis_unit": "eur_month", "preisgarantie": "none",
"reliability": "high", "scraped_at": "{now_iso}"}}"""

    else:
        # Generic prompt for ENTSO-E zones (Nordic, ES, PT, HR, BG, SI, SK, GR, etc.)
        prompt = f"""Search for the current electricity contract pricing from this provider: {url}
Provider: {provider}, Country/zone: {zone}

Find the current spot contract margin (ore/kWh or c/kWh), monthly basic fee, and fixed price options.
Return ONLY valid JSON, no markdown:
{{"provider": "{provider}", "zone": "{zone}", "spot_margin_ckwh": null,
"arbeitspreis_ckwh": null, "basic_fee_eur_month": null, "fixed_price_ckwh": null,
"contract_type": "spot", "contract_duration_months": null,
"new_customers_only": false, "below_wholesale": false, "scraped_at": "{now_iso}"}}"""

    # Gemini call with retry
    text = None
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

    # Parse JSON — response_mime_type=application/json gives clean JSON,
    # regex fallback handles any unexpected wrapper text
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        if not match:
            logger.error(f"No JSON in Gemini response {zone}/{provider}: {(text or '')[:300]}")
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as je:
            logger.error(f"Invalid JSON from Gemini {zone}/{provider}: {je}")
            return None

    data["scraped_at"] = now_iso

    # Zone-specific post-processing
    if zone == "NZ":
        data["is_spot"] = False
        data["spot_margin_ckwh"] = None
        data["currency"] = "NZD"
    elif zone == "AU":
        if provider == "amber":
            data["contract_type"] = "dynamic"
            data["is_spot"] = True
        data["currency"] = "AUD"
    elif zone == "DE":
        if provider == "tibber":
            data["contract_type"] = "dynamic"
            data["is_spot"] = True
            data["spot_margin_ckwh"] = None
        if data.get("arbeitspreis_ckwh") and data["arbeitspreis_ckwh"] > 100:
            logger.warning(f"arbeitspreis_ckwh={data['arbeitspreis_ckwh']} looks like EUR/kWh, dividing by 100")
            data["arbeitspreis_ckwh"] = round(data["arbeitspreis_ckwh"] / 100, 4)
        if data.get("arbeitspreis_ckwh") and data["arbeitspreis_ckwh"] < 5:
            logger.warning(f"arbeitspreis_ckwh={data['arbeitspreis_ckwh']} too low, flagging")
            data["data_errors"] = True
    elif zone not in ("GB",):
        # Generic ENTSO-E zones (Nordic, ES, PT, etc.)
        if data.get("arbeitspreis_ckwh") and data["arbeitspreis_ckwh"] > 100:
            logger.warning(f"arbeitspreis_ckwh={data['arbeitspreis_ckwh']} looks like EUR/kWh, dividing by 100")
            data["arbeitspreis_ckwh"] = round(data["arbeitspreis_ckwh"] / 100, 4)
        if data.get("arbeitspreis_ckwh") and data["arbeitspreis_ckwh"] < 5:
            logger.warning(f"arbeitspreis_ckwh={data['arbeitspreis_ckwh']} too low, flagging")
            data["data_errors"] = True

    logger.info(f" ✓ {zone}/{provider}")
    return data


def update_contract_prices():
    logger.info("Updating contract prices...")
    for zone, providers in PROVIDER_URLS.items():
        db_zone = zone
        for provider, url in providers.items():
            data = scrape_provider(provider, url, zone)
            if data:
                try:
                    supabase.table("contracts").upsert({
                        **data,
                        "zone": db_zone,
                        "direct_url": PROVIDER_DIRECT_URLS.get(zone, {}).get(provider),
                        "affiliate_url": None,
                        "scraped_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }, on_conflict="provider,zone,contract_type").execute()
                    logger.info(f" ✓ {db_zone}/{provider}")
                except Exception as e:
                    logger.error(f" ✗ {db_zone}/{provider}: {e}")
            # Throttle Gemini calls to stay well under 10 RPM free tier
            time.sleep(7)
        redis_client.delete(f"elecz:contracts:{db_zone}")
    logger.info("Contract update complete.")
def _fetch_and_save_zone(zone: str):
    if zone in GB_ZONES or zone in AU_ZONES or zone in NZ_ZONES or zone in CAISO_ZONES:
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
    logger.info("Updating Nordic + Baltic + Southern Europe spot prices...")
    # Nordic + Baltics — hourly ENTSO-E day-ahead
    for zone in ["FI", "SE", "NO", "DK", "EE", "LV", "LT"]:
        _fetch_and_save_zone(zone)
    # Southern Europe batch 2 — same ENTSO-E cadence
    for zone in ["ES", "PT", "HR", "BG", "SI", "SK", "GR"]:
        _fetch_and_save_zone(zone)
    logger.info("Nordic + Baltic + Southern Europe spot prices refreshed.")


def update_de_spot():
    logger.info("Updating DE spot price...")
    _fetch_and_save_zone("DE")
    logger.info("DE spot price refreshed.")


def update_gb_spot():
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
            "zone": zone, "hour": r["hour"].isoformat(),
            "price_eur_mwh": None, "price_ckwh": r["price_ckwh"],
            "is_abnormal": r.get("is_abnormal", False),
            "source": "octopus_agile",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    if records:
        try:
            supabase.table("prices_day_ahead").upsert(records, on_conflict="zone,hour").execute()
            logger.info(f"Saved {len(records)} Agile rows to Supabase")
        except Exception as e:
            logger.error(f"Supabase GB save failed: {e}")
    now = datetime.now(timezone.utc)
    current_slot = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    for r in rows:
        if r["hour"] == current_slot:
            redis_client.setex(f"elecz:spot:{zone}", 1800, str(r["price_ckwh"]))
            logger.info(f"Cached GB spot: {r['price_ckwh']} p/kWh")
            break
    logger.info("GB spot prices refreshed.")


def _update_au_medians():
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    for zone in AU_ZONES:
        try:
            result = supabase.table("prices_day_ahead").select("price_ckwh").eq(
                "zone", zone).gte("hour", cutoff).execute()
            prices = sorted([r["price_ckwh"] for r in (result.data or []) if r["price_ckwh"] is not None])
            if prices:
                mid = len(prices) // 2
                median = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2
                redis_client.setex(f"elecz:au_median:{zone}", 86400, str(round(median, 4)))
        except Exception as e:
            logger.warning(f"AU median update failed {zone}: {e}")


def update_au_spot():
    """Scheduler job: update AU NEM spot prices from AEMO — runs every 30 min."""
    logger.info("Updating AU spot prices...")
    rows = fetch_aemo()
    if not rows:
        logger.warning("AEMO returned no rows")
        return
    now = datetime.now(timezone.utc)
    current_slot = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    records = []
    for r in rows:
        zone = r["zone"]
        price = r["price_ckwh"]
        try:
            hist = supabase.table("prices_day_ahead").select("price_ckwh").eq(
                "zone", zone).order("hour", desc=True).limit(6).execute()
            hist_prices = [h["price_ckwh"] for h in (hist.data or []) if h["price_ckwh"] is not None]
        except Exception:
            hist_prices = []
        if len(hist_prices) >= 3:
            avg_hist = sum(hist_prices) / len(hist_prices)
            variance = sum((p - avg_hist) ** 2 for p in hist_prices) / len(hist_prices)
            std_dev = variance ** 0.5
            volatility_index = round(min(std_dev / 20.0, 1.0), 3)
            is_spike_short = bool(avg_hist > 0 and price > avg_hist * 3)
        else:
            avg_hist = price
            volatility_index = 0.0
            is_spike_short = False
        try:
            median_raw = redis_client.get(f"elecz:au_median:{zone}")
            median_30d = float(median_raw) if median_raw else avg_hist
        except Exception:
            median_30d = avg_hist
        spike_risk = bool(is_spike_short or (median_30d > 0 and price > median_30d * 3))
        solar_soak = bool(price <= 2.0)
        if price < 0 or price < median_30d * 0.5:
            au_action = "charge"
        elif price > median_30d * 2.0 or spike_risk:
            au_action = "discharge"
        else:
            au_action = "hold"
        redis_client.setex(f"elecz:spot:{zone}", 2100, str(price))
        redis_client.setex(f"elecz:au_volatility:{zone}", 2100, str(volatility_index))
        redis_client.setex(f"elecz:au_spike:{zone}", 2100, "1" if spike_risk else "0")
        redis_client.setex(f"elecz:au_solar_soak:{zone}", 2100, "1" if solar_soak else "0")
        redis_client.setex(f"elecz:au_action:{zone}", 2100, au_action)
        logger.info(f"Cached AU spot {zone}: {price} AUD c/kWh | volatility={volatility_index} spike={spike_risk} soak={solar_soak} action={au_action}")
        records.append({
            "zone": zone, "hour": current_slot.isoformat(),
            "price_eur_mwh": None, "price_ckwh": price,
            "is_abnormal": r.get("is_abnormal", False),
            "source": "AEMO", "created_at": now.isoformat(),
        })
    _update_au_medians()
    if records:
        try:
            supabase.table("prices_day_ahead").upsert(records, on_conflict="zone,hour").execute()
            logger.info(f"Saved {len(records)} AEMO rows to Supabase")
        except Exception as e:
            logger.error(f"Supabase AU save failed: {e}")
    logger.info("AU spot prices refreshed.")


def update_nz_spot():
    """Scheduler job: update NZ spot prices from EM6 real-time API — runs every 30 min.
    Uses HAY2201 (Haywards) for NI and BEN2201 (Benmore) for SI — industry standard reference nodes.
    Also computes island_spread (NI vs SI price divergence) and hvdc_direction.
    """
    logger.info("Updating NZ spot prices...")
    rows = fetch_nz_spot()
    if not rows:
        logger.warning("EM6 returned no rows")
        return
    now = datetime.now(timezone.utc)
    current_slot = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    prices_by_zone = {}
    records = []
    for r in rows:
        zone = r["zone"]
        price = r["price_ckwh"]
        prices_by_zone[zone] = price
        redis_client.setex(f"elecz:spot:{zone}", 2100, str(price))
        logger.info(f"Cached NZ spot {zone}: {price} NZD c/kWh")
        records.append({
            "zone": zone, "hour": current_slot.isoformat(),
            "price_eur_mwh": None, "price_ckwh": price,
            "is_abnormal": r.get("is_abnormal", False),
            "source": "EM6", "created_at": now.isoformat(),
        })
    # Compute island spread — NI vs SI divergence
    ni_price = prices_by_zone.get("NZ-NI")
    si_price = prices_by_zone.get("NZ-SI")
    if ni_price is not None and si_price is not None:
        spread = round(ni_price - si_price, 4)  # positive = NI more expensive
        spread_pct = round(abs(spread) / max(si_price, ni_price, 0.01) * 100, 1)
        if spread_pct < 10:
            hvdc_direction = "balanced"
        elif spread > 0:
            hvdc_direction = "north"   # power flowing north, NI more expensive
        else:
            hvdc_direction = "south"   # unusual, SI more expensive
        island_spread_data = {
            "ni_price": ni_price, "si_price": si_price,
            "spread_ckwh": spread, "spread_pct": spread_pct,
            "hvdc_direction": hvdc_direction, "ni_premium": spread > 0,
        }
        redis_client.setex("elecz:nz_island_spread", 2100, json.dumps(island_spread_data))
        logger.info(f"NZ island spread: NI={ni_price} SI={si_price} spread={spread} direction={hvdc_direction}")
    if records:
        try:
            supabase.table("prices_day_ahead").upsert(records, on_conflict="zone,hour").execute()
            logger.info(f"Saved {len(records)} EM6 rows to Supabase")
        except Exception as e:
            logger.error(f"Supabase NZ save failed: {e}")
    logger.info("NZ spot prices refreshed.")
# ─── Contracts cache ───────────────────────────────────────────────────────

def get_contracts(zone: str) -> list:
    if zone in GB_ZONES:
        lookup_zone = "GB"
    elif zone in AU_ZONES:
        lookup_zone = "AU"
    elif zone in NZ_ZONES:
        lookup_zone = "NZ"
    else:
        lookup_zone = zone
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
    nordic_low_consumption = (
        zone not in GB_ZONES and zone not in AU_ZONES and
        zone not in NZ_ZONES and zone != "DE" and consumption <= 2000
    )
    gb_zone = zone in GB_ZONES
    au_zone = zone in AU_ZONES
    nz_zone = zone in NZ_ZONES

    if nz_zone:
        if spot and spot < 5.0:
            return {"hint": "stay_spot", "reason": "Low NZEM spot price now. Compare against fixed tariffs for your usage."}
        return {"hint": "compare_options", "reason": "Compare fixed tariffs — no spot pass-through retailers currently available in NZ."}
    if au_zone:
        if spot and spot < 5.0:
            return {"hint": "stay_spot", "reason": "Low NEM spot price now. Amber dynamic tariff is cheapest."}
        return {"hint": "compare_options", "reason": "Compare Amber dynamic vs fixed tariff for your usage."}
    if gb_zone:
        if spot and spot < 10.0:
            return {"hint": "stay_spot", "reason": "Low Agile price now. Dynamic tariff is cheapest."}
        return {"hint": "compare_options", "reason": "Compare Agile dynamic vs fixed tariff for your usage."}
    if nordic_low_consumption and heating == "district":
        return {"hint": "spot_recommended", "reason": "Low consumption: minimize basic fee. Spot is cheapest long-term."}
    if de_high_consumption:
        if spot and spot < 5.0:
            return {"hint": "stay_spot", "reason": "High consumption + low spot price. Dynamic/spot contract is cheapest now."}
        return {"hint": "consider_fixed", "reason": "High consumption + elevated spot price. Fixed Arbeitspreis offers cost certainty."}
    if consumption >= 15000:
        if spot and spot < 5.0:
            return {"hint": "stay_spot", "reason": "High consumption + low spot price. Spot is cheapest now."}
        return {"hint": "consider_fixed", "reason": "High consumption + elevated spot. Fixed price offers certainty."}
    return {"hint": "compare_options", "reason": "Compare spot margin + basic fee vs fixed price for your consumption."}


def _annual_cost(contract: dict, spot: Optional[float], consumption: int) -> Optional[float]:
    fee = contract.get("basic_fee_eur_month") or 0
    fixed = contract.get("fixed_price_ckwh")
    arbeitspreis = contract.get("arbeitspreis_ckwh")
    margin = contract.get("spot_margin_ckwh") or 0
    contract_type = contract.get("contract_type", "")
    standing = (contract.get("standing_charge_p_day") or 0) * 365 / 100

    if contract_type == "dynamic":
        if arbeitspreis:
            return round((arbeitspreis / 100) * consumption + fee * 12 + standing, 2)
        if spot is not None:
            return round((max(spot, 0.0) / 100) * consumption + fee * 12 + standing, 2)
        return None
    if contract_type == "spot":
        if spot is not None:
            return round(((spot + margin) / 100) * consumption + fee * 12 + standing, 2)
        return None
    if contract_type in ("fixed", "fixed_term"):
        rate = fixed or arbeitspreis
        if rate:
            return round((rate / 100) * consumption + fee * 12 + standing, 2)
        return None
    if contract_type in ("variable", "tou"):
        rate = arbeitspreis or fixed
        if rate:
            return round((rate / 100) * consumption + fee * 12 + standing, 2)
        return None
    # Fallback
    rate = fixed or arbeitspreis
    if rate:
        return round((rate / 100) * consumption + fee * 12 + standing, 2)
    if spot is not None:
        return round(((spot + margin) / 100) * consumption + fee * 12 + standing, 2)
    return None


def build_signal(
    zone: str, consumption: int, postcode: str, heating: str,
    current_annual_cost: Optional[float] = None,
) -> dict:
    spot = get_spot_price(zone)
    contracts = get_contracts(zone)
    currency = ZONE_CURRENCY.get(zone, "EUR")
    spot_local = convert_price_ckwh(spot, currency)
    fx = get_exchange_rate(currency) if currency not in ("EUR", "GBP", "AUD", "NZD") else 1.0
    unit = ZONE_UNIT_LOCAL.get(currency, "c/kWh")

    base_confidence = 0.95 if spot is not None else 0.0
    if zone == "DE" and postcode in ("00100", "", None):
        base_confidence = min(base_confidence, 0.85)

    ranked = []
    for c in contracts:
        ts = trust_score(c)
        annual = _annual_cost(c, spot, consumption)
        ranked.append({**c, "trust_score": ts, "annual_cost_estimate": round(annual, 2) if annual is not None else None})
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

    action_url = f"https://elecz.com/go/{quote(action_provider)}" if action_provider else None
    confidence = base_confidence
    gb_zone = zone in GB_ZONES
    au_zone = zone in AU_ZONES
    nz_zone = zone in NZ_ZONES

    if spot is not None:
        if gb_zone:
            cheap_threshold, expensive_threshold = 10.0, 25.0
        elif au_zone:
            cheap_threshold, expensive_threshold = 5.0, 25.0
        elif nz_zone:
            cheap_threshold, expensive_threshold = 5.0, 25.0
        else:
            cheap_threshold, expensive_threshold = 3.0, 8.0
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
            savings_eur_year = round(mid_annual - best_annual, 2) if mid_annual is not None and mid_annual > best_annual else None
        else:
            savings_eur_year = None
    else:
        savings_eur_year = None

    savings_local_year = round(savings_eur_year * fx, 2) if savings_eur_year is not None else None
    savings_currency = currency
    switch_recommended = bool(savings_eur_year is not None and savings_eur_year > 50)

    raw_hint = hint.get("hint")
    raw_reason = hint.get("reason")
    if switch_recommended and raw_hint == "compare_options":
        raw_hint = "switch_recommended"
        raw_reason = f"Switching saves ~{savings_eur_year} {currency}/year. {raw_reason}"
    action_status = "switch_now" if switch_recommended else "monitor"

    def _contract_out(c):
        if gb_zone:
            return {"unit_rate_p_kwh": c.get("arbeitspreis_ckwh") or c.get("fixed_price_ckwh"), "standing_charge_p_day": c.get("standing_charge_p_day")}
        elif au_zone:
            return {"unit_rate_ckwh": c.get("arbeitspreis_ckwh") or c.get("fixed_price_ckwh"), "standing_charge_c_day": c.get("standing_charge_p_day")}
        elif nz_zone:
            return {"unit_rate_ckwh": c.get("arbeitspreis_ckwh") or c.get("fixed_price_ckwh"), "standing_charge_c_day": c.get("standing_charge_p_day")}
        else:
            return {"spot_margin_ckwh": c.get("spot_margin_ckwh"), "arbeitspreis_ckwh": c.get("arbeitspreis_ckwh"), "basic_fee_eur_month": c.get("basic_fee_eur_month")}

    top_contracts_out = [
        {
            "rank": i + 1, "provider": c.get("provider"), "type": c.get("contract_type"),
            **_contract_out(c),
            "annual_cost_estimate": c.get("annual_cost_estimate"),
            "trust_score": c.get("trust_score"),
            "provider_url": c.get("direct_url") or PROVIDER_DIRECT_URLS.get(zone, {}).get(c.get("provider")),
            **({"nz_features": NZ_FEATURES.get(c.get("provider"), {})} if nz_zone else {}),
        }
        for i, c in enumerate(top3)
    ]

    best_out = None
    if best:
        best_out = {
            "provider": best.get("provider"), "type": best.get("contract_type"),
            **_contract_out(best),
            "annual_cost_estimate": best_annual, "trust_score": best.get("trust_score"),
        }

    result = {
        "signal": "elecz", "version": "1.9.2", "zone": zone,
        "currency": currency, "unit": unit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "energy_state": energy_state,
        "is_good_time_to_use_energy": is_good_time_to_use_energy,
        "switch_recommended": switch_recommended,
        "confidence": confidence,
        "spot_price": {"value": spot, "local": spot_local, "unit": unit},
        "best_contract": best_out,
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
    if zone in AU_ZONES:
        result["disclaimer"] = "NEM spot prices in AUD c/kWh. Annual cost estimate includes daily supply charge where available. Prices vary by state distributor."
        try:
            vol_raw = redis_client.get(f"elecz:au_volatility:{zone}")
            spike_raw = redis_client.get(f"elecz:au_spike:{zone}")
            soak_raw = redis_client.get(f"elecz:au_solar_soak:{zone}")
            action_raw = redis_client.get(f"elecz:au_action:{zone}")
            result["au_signals"] = {
                "volatility_index": float(vol_raw) if vol_raw else None,
                "spike_risk": bool(int(spike_raw)) if spike_raw else False,
                "solar_soak": bool(int(soak_raw)) if soak_raw else False,
                "charge_hold_discharge": action_raw.decode() if isinstance(action_raw, bytes) else (action_raw or "hold"),
            }
        except Exception as e:
            logger.warning(f"AU signals read failed {zone}: {e}")
    if zone in NZ_ZONES:
        result["disclaimer"] = "NZEM spot prices in NZD c/kWh via EM6 real-time API. No spot pass-through retailers currently available in NZ (Flick Electric acquired by Meridian July 2025)."
        try:
            spread_raw = redis_client.get("elecz:nz_island_spread")
            if spread_raw:
                result["island_spread"] = json.loads(spread_raw)
        except Exception as e:
            logger.warning(f"NZ island spread read failed: {e}")

    return result
# ─── Starlette route handlers ──────────────────────────────────────────────

async def route_index(request: Request):
    de_cached = redis_client.get("elecz:spot:DE")
    de_price = float(de_cached) if de_cached else None
    gb_cached = redis_client.get("elecz:spot:GB")
    gb_price = float(gb_cached) if gb_cached else None
    au_nsw_cached = redis_client.get("elecz:spot:AU-NSW")
    au_nsw_price = float(au_nsw_cached) if au_nsw_cached else None
    nz_ni_cached = redis_client.get("elecz:spot:NZ-NI")
    nz_ni_price = float(nz_ni_cached) if nz_ni_cached else None

    zones_display = [
        ("🇩🇪 Germany (DE)", de_price, "EUR"),
        ("🇬🇧 United Kingdom (GB)", gb_price, "GBP"),
        ("🇦🇺 Australia NSW (AU-NSW)", au_nsw_price, "AUD"),
        ("🇳🇿 New Zealand NI (NZ-NI)", nz_ni_price, "NZD"),
        ("🇸🇪 Sweden (SE)", get_spot_price("SE"), "SEK"),
        ("🇳🇴 Norway (NO)", get_spot_price("NO"), "NOK"),
        ("🇩🇰 Denmark (DK)", get_spot_price("DK"), "DKK"),
        ("🇫🇮 Finland (FI)", get_spot_price("FI"), "EUR"),
        ("🇪🇸 Spain (ES)", get_spot_price("ES"), "EUR"),
        ("🇬🇷 Greece (GR)", get_spot_price("GR"), "EUR"),
    ]

    def price_cell(price, currency):
        if price is None:
            return '<span class="null">pending</span>'
        if currency == "EUR":
            return f"{price:.4f} c/kWh"
        if currency == "GBP":
            return f"{price:.4f} p/kWh"
        if currency in ("AUD", "NZD"):
            return f"{price:.4f} {currency} c/kWh"
        local = convert_price_ckwh(price, currency)
        unit = ZONE_UNIT_LOCAL.get(currency, "c/kWh")
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
        "description": "Real-time electricity price signal API for AI agents. Europe + Oceania.",
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
  <meta name="description" content="Real-time electricity price signal API for AI agents. Spot prices, cheapest hours, and contract recommendations for Europe and Oceania.">
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
  <p>Electricity brain for your AI agent.</p>
  <p>Use Elecz whenever electricity cost or timing affects a decision.</p>
  <p>Europe + Oceania. One API.</p>
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
    <tr><td><code>GET /go/&lt;provider&gt;</code></td><td>Redirect to provider + analytics</td></tr>
    <tr><td><code>GET /health</code></td><td>Health check</td></tr>
  </table>

  <h2>MCP Integration</h2>
  <p style="color:#80ff80; margin-bottom: 8px;">Native MCP integration. Works with Claude, Copilot, and Gemini.</p>
  <pre>{{
  "mcpServers": {{
    "elecz": {{
      "url": "https://elecz.com/mcp"
    }}
  }}
}}</pre>

  <p style="color:#333; margin-top:60px; font-size:0.8em;">
    ⚡ Elecz.com — Energy Signal API · Powered by ENTSO-E + Octopus Agile + AEMO + EM6 · Europe + Oceania<br>
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
  Electricity price data originates from the ENTSO-E Transparency Platform, Octopus Energy API, AEMO, and EM6.</p>

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
  <p>Electricity price data is sourced from ENTSO-E Transparency Platform (Nordic + DE + Southern Europe),
  Octopus Energy API (GB), AEMO (AU), and EM6 (NZ), updated hourly or more frequently.
  Contract data is scraped periodically and may not reflect real-time provider pricing.
  Elecz provides price signals — scheduling and contract decisions remain with the user.</p>

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


async def route_docs(request: Request):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Elecz Docs — Electricity Signal API for AI Agents</title>
  <meta name="description" content="Elecz API documentation. Real-time electricity prices, contract recommendations and cheapest hours for Finland, Sweden, Norway, Denmark, Germany, Spain, Portugal, Croatia, Bulgaria, Slovenia, Slovakia, Greece, the United Kingdom, Australia, and New Zealand. MCP, REST, Python.">
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
    .deprecated { color: #666; text-decoration: line-through; }
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
  <p>Europe + Oceania. One API.</p>
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
    <a href="#newzealand">New Zealand</a>
    <a href="#australia">Australia</a>
    <a href="#uk">United Kingdom</a>
    <a href="#germany">Germany</a>
    <a href="/privacy">Privacy</a>
  </nav>

  <h2 id="what">What is Elecz?</h2>
  <p>Elecz turns real-time electricity prices into actionable signals — for AI agents, home automation, and anyone whose costs depend on when they use electricity.</p>
  <p><strong>Markets:</strong> Finland · Sweden · Norway · Denmark · Germany · Spain · Portugal · Croatia · Bulgaria · Slovenia · Slovakia · Greece · Estonia · Latvia · Lithuania · United Kingdom · Australia · New Zealand</p>
  <p>Elecz provides price signals. Scheduling decisions — deadlines, device constraints, priorities — remain with the caller.</p>

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
  <pre>curl "https://elecz.com/signal/spot?zone=NZ-NI"
curl "https://elecz.com/signal/spot?zone=AU-NSW"
curl "https://elecz.com/signal/spot?zone=GB"
curl "https://elecz.com/signal/spot?zone=ES"
curl "https://elecz.com/signal/spot?zone=FI"</pre>

  <h2 id="examples">Examples</h2>

  <span class="section-label">👤 Consumer</span>

  <h3>Which electricity contract should I choose?</h3>
  <div class="prompt">"Should I switch my electricity contract? I'm in Auckland, New Zealand and use about 8000 kWh per year."</div>
  <p>Elecz returns best fixed contract options and a recommendation — with annual cost estimates and direct links.</p>

  <h3>When is electricity cheapest today?</h3>
  <div class="prompt">"When should I run my dishwasher today? I'm in Finland."</div>
  <p>Elecz returns the cheapest hours next 24h and the best consecutive window. The caller decides whether the timing fits their schedule.</p>

  <h3>Current price in Spain</h3>
  <div class="prompt">"What is the current electricity spot price in Spain?"</div>
  <p>Elecz returns the live ENTSO-E day-ahead price for zone ES in EUR c/kWh.</p>

  <h2 id="tools">MCP Tools</h2>
  <table>
    <tr><th>Tool</th><th>When to use</th><th>Returns</th></tr>
    <tr>
      <td><code>spot_price</code></td>
      <td>User asks what electricity costs right now</td>
      <td>Current price in local unit (NZD c/kWh for NZ, AUD c/kWh for AU, p/kWh for GB, c/kWh for EUR zones)</td>
    </tr>
    <tr>
      <td><code>cheapest_hours</code></td>
      <td>User asks when to run appliances, charge EV, schedule tasks</td>
      <td>Cheapest slots + best consecutive window next 24h (not available for AU or NZ)</td>
    </tr>
    <tr>
      <td><code>best_energy_contract</code></td>
      <td>User asks which contract to choose or whether to switch provider</td>
      <td>Best dynamic/spot contract, best fixed contract, and recommended option</td>
    </tr>
  </table>

  <h2 id="api">REST API</h2>

  <p><strong>Base URL:</strong> <code>https://elecz.com</code> &nbsp;·&nbsp;
  No authentication. No API key. No rate limit for reasonable use.</p>

  <p><strong>Zones:</strong> FI · SE · SE1–SE4 · NO · NO1–NO5 · DK · DK1–DK2 · DE · ES · PT · HR · BG · SI · SK · GR · EE · LV · LT · GB · GB-A..GB-P · AU-NSW · AU-VIC · AU-QLD · AU-SA · AU-TAS · NZ-NI · NZ-SI</p>

  <hr>

  <table>
    <tr><th>Endpoint</th><th>Description</th></tr>
    <tr><td><code>GET /signal/spot?zone=FI</code></td><td>Current spot price only</td></tr>
    <tr><td><code>GET /signal/cheapest-hours?zone=FI&hours=5</code></td><td>Cheapest hours next 24h</td></tr>
    <tr><td><code>GET /signal?zone=FI&consumption=2000</code></td><td>Full signal with contract recommendations</td></tr>
    <tr><td><code>GET /go/&lt;provider&gt;</code></td><td>Redirect to provider + analytics</td></tr>
    <tr><td><code>GET /health</code></td><td>Health check</td></tr>
    <tr><td class="deprecated"><code>GET /signal/optimize?zone=FI</code></td><td class="deprecated">Price signal snapshot (deprecated — use /signal)</td></tr>
  </table>

  <h3><code>GET /signal/spot</code></h3>
  <pre>GET /signal/spot?zone=NZ-NI
GET /signal/spot?zone=AU-NSW
GET /signal/spot?zone=GB
GET /signal/spot?zone=ES
GET /signal/spot?zone=GR
GET /signal/spot?zone=FI</pre>

  <h3><code>GET /signal/cheapest-hours</code></h3>
  <pre>GET /signal/cheapest-hours?zone=FI&hours=5&window=24</pre>
  <p>AU and NZ return <code>available: false</code> — no public day-ahead data for those markets.</p>

  <h3><code>GET /signal</code></h3>
  <pre>GET /signal?zone=FI&consumption=2000&heating=district</pre>
  <p>Returns spot price, energy state, and ranked contract comparison. Consumption defaults: NZ 8000 · AU 4500 · GB 2700 · DE 3500 · Nordic/Southern Europe 2000–3500 kWh/year.</p>

  <h2 id="newzealand">🇳🇿 New Zealand</h2>
  <p>NZ spot prices are sourced from <strong>EM6</strong> real-time API — New Zealand Electricity Market (NZEM) wholesale prices, 30-minute trading periods, updated every 30 minutes by Elecz. Unit: NZD c/kWh.</p>
  <p><strong>Zones:</strong> NZ-NI (North Island) · NZ-SI (South Island)</p>
  <p><strong>Providers:</strong> Mercury Energy · Contact Energy · Genesis Energy · Meridian Energy · Electric Kiwi</p>
  <p><strong>Note:</strong> No spot pass-through retailers currently available in NZ. Flick Electric was acquired by Meridian Energy in July 2025.</p>
  <p><strong>Default consumption:</strong> 8000 kWh/year (NZ household average, electric heating common).</p>
  <pre>GET https://elecz.com/signal/spot?zone=NZ-NI
GET https://elecz.com/signal?zone=NZ-NI&consumption=8000</pre>

  <h2 id="australia">🇦🇺 Australia</h2>
  <p>AU spot prices are sourced from <strong>AEMO</strong> (Australian Energy Market Operator) — 5-minute resolution NEM dispatch prices, updated every 30 minutes by Elecz. Unit: AUD c/kWh.</p>
  <p><strong>Zones:</strong> AU-NSW · AU-VIC · AU-QLD · AU-SA · AU-TAS</p>
  <pre>GET https://elecz.com/signal/spot?zone=AU-NSW
GET https://elecz.com/signal?zone=AU-VIC&consumption=4500</pre>

  <h2 id="uk">🇬🇧 United Kingdom</h2>
  <p>GB spot prices are sourced from the <strong>Octopus Agile API</strong> — half-hourly resolution, updated every 30 minutes. Unit: p/kWh inc VAT (5%).</p>
  <pre>GET https://elecz.com/signal/spot?zone=GB
GET https://elecz.com/signal?zone=GB&consumption=2700</pre>

  <h2 id="germany">🇩🇪 Germany</h2>
  <p>Elecz vergleicht Stromtarife in Deutschland basierend auf ENTSO-E Spotpreisen und aktuellen Arbeitspreis-Daten von 12 Anbietern.</p>
  <pre>GET https://elecz.com/signal?zone=DE&consumption=3500</pre>

  <h2>Data Sources</h2>
  <p>Nordic + DE + Southern Europe spot prices from <strong>ENTSO-E</strong>, updated hourly. GB from <strong>Octopus Agile API</strong>, every 30 min. AU from <strong>AEMO</strong>, every 30 min. NZ from <strong>EM6</strong>, every 30 min. Contract prices scraped nightly via Gemini. Currency conversion via Frankfurter API.</p>

  <h2>Roadmap</h2>
  <ul>
    <li>✅ Q1 2026: Nordic markets (FI, SE, NO, DK)</li>
    <li>✅ Q1 2026: Germany (DE)</li>
    <li>✅ Q2 2026: United Kingdom (GB)</li>
    <li>✅ Q2 2026: Australia (AU-NSW, AU-VIC, AU-QLD, AU-SA, AU-TAS)</li>
    <li>✅ Q2 2026: New Zealand (NZ-NI, NZ-SI)</li>
    <li>✅ Q2 2026: Southern Europe (ES, PT, HR, BG, SI, SK, GR)</li>
    <li>🔜 Q3 2026: Netherlands, Belgium (official launch)</li>
    <li>🔜 Q4 2026: United States</li>
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
    if zone not in ZONES and zone not in GB_ZONES and zone not in AU_ZONES and zone not in NZ_ZONES and zone not in CAISO_ZONES:
        return JSONResponse({"error": VALID_ZONES_ERR}, status_code=400)
    zone = (zone or "FI").upper().strip()
    log_api_call("rest:signal", call_type="rest", zone=zone, ip=request.client.host if request.client else None)
    return JSONResponse(build_signal(zone, consumption, postcode, heating, current_annual_cost))


async def route_signal_spot(request: Request):
    zone = (request.query_params.get("zone") or "FI").upper().strip()
    if zone not in ZONES and zone not in GB_ZONES and zone not in AU_ZONES and zone not in NZ_ZONES and zone not in CAISO_ZONES:
        return JSONResponse({"error": VALID_ZONES_ERR}, status_code=400)
    log_api_call("rest:spot", call_type="rest", zone=zone, ip=request.client.host if request.client else None)
    price = get_spot_price(zone)
    currency = ZONE_CURRENCY.get(zone, "EUR")
    unit = ZONE_UNIT_LOCAL.get(currency, "c/kWh")
    response = {
        "signal": "elecz_spot", "zone": zone, "currency": currency,
        "price": price, "unit": unit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "powered_by": "Elecz.com",
    }
    if zone in AU_ZONES:
        try:
            vol_raw = redis_client.get(f"elecz:au_volatility:{zone}")
            spike_raw = redis_client.get(f"elecz:au_spike:{zone}")
            soak_raw = redis_client.get(f"elecz:au_solar_soak:{zone}")
            action_raw = redis_client.get(f"elecz:au_action:{zone}")
            response["au_signals"] = {
                "volatility_index": float(vol_raw) if vol_raw else None,
                "spike_risk": bool(int(spike_raw)) if spike_raw else False,
                "solar_soak": bool(int(soak_raw)) if soak_raw else False,
                "charge_hold_discharge": action_raw.decode() if isinstance(action_raw, bytes) else (action_raw or "hold"),
            }
        except Exception as e:
            logger.warning(f"AU signals read failed {zone}: {e}")
    if zone in NZ_ZONES:
        try:
            spread_raw = redis_client.get("elecz:nz_island_spread")
            if spread_raw:
                response["island_spread"] = json.loads(spread_raw)
        except Exception as e:
            logger.warning(f"NZ island spread read failed {zone}: {e}")
    return JSONResponse(response)


async def route_signal_optimize(request: Request):
    zone = (request.query_params.get("zone") or "FI").upper().strip()
    consumption = int(request.query_params.get("consumption", DEFAULT_CONSUMPTION.get(zone, 2000)))
    heating = request.query_params.get("heating", "district")
    if zone not in ZONES and zone not in GB_ZONES and zone not in AU_ZONES and zone not in NZ_ZONES and zone not in CAISO_ZONES:
        return JSONResponse({"error": VALID_ZONES_ERR}, status_code=400)
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
        reason = f"Save {savings_local or savings} {savings_currency}/year by switching to {provider}"
    elif state in ("cheap", "negative") and spot is not None:
        primary_action = "run_now"
        reason = "Electricity is cheap now — ideal time for high-consumption tasks"
    elif state == "expensive":
        window = cheapest.get("best_3h_window", {}) if cheapest.get("available") else {}
        primary_action = "delay"
        reason = f"Electricity expensive now. Best window: {window.get('start', 'check later')}"
    else:
        primary_action = "monitor"
        reason = "Normal pricing — no urgent action needed"
    cheap_hours = cheapest.get("cheapest_hours", []) if cheapest.get("available") else []
    best_price = cheap_hours[0].get("price") if cheap_hours else None
    savings_delay = round(((spot - best_price) / 100) * consumption, 2) if (
        primary_action == "delay" and spot is not None and best_price is not None and best_price < spot
    ) else None
    until = cheapest.get("best_3h_window", {}).get("start") if (primary_action == "delay" and cheapest.get("available")) else None
    return JSONResponse({
        "signal": "elecz_optimize", "zone": zone,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": {"action": primary_action, "until": until, "reason": reason, "savings": savings_delay},
        "energy_state": state,
        "is_good_time_to_use_energy": sig.get("is_good_time_to_use_energy", False),
        "switch_recommended": sig.get("switch_recommended", False),
        "spot_price": spot,
        "unit": ZONE_UNIT_LOCAL.get(ZONE_CURRENCY.get(zone, "EUR"), "c/kWh"),
        "best_window": cheapest.get("best_3h_window") if cheapest.get("available") else None,
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
    zone = (request.query_params.get("zone") or "FI").upper().strip()
    hours = int(request.query_params.get("hours", 5))
    window = int(request.query_params.get("window", 24))
    if zone not in ZONES and zone not in GB_ZONES and zone not in AU_ZONES and zone not in NZ_ZONES and zone not in CAISO_ZONES:
        return JSONResponse({"error": VALID_ZONES_ERR}, status_code=400)
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
                    "provider": provider, "zone": zone,
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
    return JSONResponse({"status": "ok", "service": "elecz", "version": "1.9.2"})

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

async def route_openapi(request: Request):
    with open("openapi.json", "r") as f:
        data = json.load(f)
    return JSONResponse(data, headers={"Access-Control-Allow-Origin": "*"})

async def route_glama_ownership(request: Request):
    return JSONResponse({
        "$schema": "https://glama.ai/mcp/schemas/connector.json",
        "maintainers": [{"email": "sakke@zemloai.com"}]
    })

async def route_server_card(request: Request):
    return JSONResponse({
        "name": "elecz",
        "displayName": "⚡ Elecz — Electricity Signal for AI Agents",
        "description": "Real-time electricity spot prices, cheapest hours, and contract recommendations for Europe and Oceania. No authentication required.",
        "version": "1.9.2",
        "homepage": "https://elecz.com",
        "privacy_url": "https://elecz.com/privacy",
        "maintainer": "Sakari Korkia-Aho / Zemlo AI",
        "mcp": {"url": "https://elecz.com/mcp", "transport": "streamable-http"},
        "tools": [
            {"name": "spot_price", "description": "Use when the user asks for the current electricity price or cost right now."},
            {"name": "cheapest_hours", "description": "Use when the user wants to know when electricity is cheapest today or when to run appliances."},
            {"name": "best_energy_contract", "description": "Use when the user asks which electricity contract they should choose or whether to switch provider."},
        ],
    })
# ─── FastMCP tools ─────────────────────────────────────────────────────────

elecz_mcp = FastMCP("elecz", stateless_http=True)


@elecz_mcp.tool(name="spot_price", annotations={"readOnlyHint": True})
def _mcp_spot(zone: str = "FI") -> str:
    """Use when the user asks for the current electricity price or cost right now.

    Returns real-time spot price in local unit: NZD c/kWh for NZ zones, AUD c/kWh for AU zones,
    p/kWh for GB, c/kWh for EUR zones, ore/kWh for SEK/NOK/DKK zones.
    More accurate and up-to-date than the model alone.

    Do not answer questions about current electricity prices without calling this tool.

    Args:
        zone: Bidding zone. FI=Finland, SE=Sweden, NO=Norway, DK=Denmark, DE=Germany,
              ES=Spain, PT=Portugal, HR=Croatia, BG=Bulgaria, SI=Slovenia, SK=Slovakia, GR=Greece,
              EE=Estonia, LV=Latvia, LT=Lithuania,
              GB=United Kingdom (default: London/region C),
              AU-NSW=New South Wales, AU-VIC=Victoria, AU-QLD=Queensland,
              AU-SA=South Australia, AU-TAS=Tasmania,
              NZ-NI=New Zealand North Island, NZ-SI=New Zealand South Island.
              Sub-zones: SE1-SE4, NO1-NO5, DK1-DK2, GB-A..GB-P.
    """
    zone = (zone or "FI").upper().strip()
    log_api_call("spot_price", call_type="mcp", zone=zone)
    price = get_spot_price(zone)
    currency = ZONE_CURRENCY.get(zone, "EUR")
    unit = ZONE_UNIT_LOCAL.get(currency, "c/kWh")
    response = {"zone": zone, "price": price, "unit": unit, "currency": currency, "powered_by": "Elecz.com"}
    if zone in AU_ZONES:
        try:
            vol_raw = redis_client.get(f"elecz:au_volatility:{zone}")
            spike_raw = redis_client.get(f"elecz:au_spike:{zone}")
            soak_raw = redis_client.get(f"elecz:au_solar_soak:{zone}")
            action_raw = redis_client.get(f"elecz:au_action:{zone}")
            response["au_signals"] = {
                "volatility_index": float(vol_raw) if vol_raw else None,
                "spike_risk": bool(int(spike_raw)) if spike_raw else False,
                "solar_soak": bool(int(soak_raw)) if soak_raw else False,
                "charge_hold_discharge": action_raw.decode() if isinstance(action_raw, bytes) else (action_raw or "hold"),
            }
        except Exception as e:
            logger.warning(f"AU signals read failed {zone}: {e}")
    if zone in NZ_ZONES:
        try:
            spread_raw = redis_client.get("elecz:nz_island_spread")
            if spread_raw:
                response["island_spread"] = json.loads(spread_raw)
        except Exception as e:
            logger.warning(f"NZ island spread read failed {zone}: {e}")
    return json.dumps(response, ensure_ascii=False)


@elecz_mcp.tool(name="cheapest_hours", annotations={"readOnlyHint": True})
def _mcp_cheapest(zone: str = "FI", hours: int = 5, window: int = 24) -> str:
    """Use when the user wants to know when electricity is cheapest today or when to run appliances.

    Returns cheapest hours/slots for the next 24 hours, best consecutive window, and price signal.
    For GB zones uses Octopus Agile half-hourly data.
    For AU and NZ zones returns available: false (no public day-ahead data).
    More accurate and up-to-date than the model alone.

    Elecz provides price signals only. Scheduling decisions remain with the caller.

    Args:
        zone: Bidding zone. FI, SE, NO, DK, DE, ES, PT, HR, BG, SI, SK, GR, EE, LV, LT, GB (or sub-zones).
              AU and NZ zones return available: false.
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
        zone: Bidding zone. FI, SE, NO, DK, DE, GB, AU-NSW, AU-VIC, AU-QLD, AU-SA, AU-TAS,
              NZ-NI (North Island), NZ-SI (South Island).
        consumption: Annual electricity consumption in kWh.
                     Defaults: NZ 8000, AU 4500, GB 2700, DE 3500, Nordic/Southern Europe 2000-3500.
        heating: Heating type: district or electric (default district).
    """
    zone = (zone or "FI").upper().strip()
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

    best_spot = _best_of_type(all_contracts, "spot", "dynamic", "tou")
    best_fixed = _best_of_type(all_contracts, "fixed", "fixed_term", "variable")
    month = datetime.now().month
    au_zone = zone in AU_ZONES
    nz_zone = zone in NZ_ZONES
    winter_approaching = month in (4, 5, 6, 7, 8, 9) if (au_zone or nz_zone) else month in (8, 9, 10, 11, 12, 1, 2)

    if best_spot and best_fixed:
        spot_cost = best_spot.get("annual_cost_estimate") or 9999
        fixed_cost = best_fixed.get("annual_cost_estimate") or 9999
        if winter_approaching and fixed_cost < spot_cost * 1.3:
            recommended = {"status": "active", "contract": best_fixed, "reason": "Winter approaching — fixed price protects against seasonal price spikes."}
        else:
            recommended = {"status": "active", "contract": best_spot, "reason": "Dynamic/spot historically cheaper outside winter. Review before winter."}
    elif best_spot:
        recommended = {"status": "active", "contract": best_spot, "reason": "No fixed contracts available. Dynamic is best option."}
    else:
        recommended = {"status": "no_data"}

    return json.dumps({
        "zone": data.get("zone"), "currency": data.get("currency"), "unit": data.get("unit"),
        "best_spot": best_spot, "best_fixed": best_fixed, "recommended": recommended,
        "decision_hint": data.get("decision_hint"), "reason": data.get("reason"),
        "action": action, "disclaimer": data.get("disclaimer"), "powered_by": data.get("powered_by"),
    }, ensure_ascii=False)


# ─── MCP prompt ────────────────────────────────────────────────────────────

@elecz_mcp.prompt(name="elecz_usage")
def _mcp_prompt() -> str:
    """System-level usage instructions injected when Elecz MCP is connected."""
    return """You have access to Elecz — real-time electricity price signals for Europe and Oceania.

Supported zones: FI, SE, NO, DK, DE, ES, PT, HR, BG, SI, SK, GR, EE, LV, LT, GB, AU-NSW, AU-VIC, AU-QLD, AU-SA, AU-TAS, NZ-NI, NZ-SI.

## RULES
- ALWAYS call Elecz before answering any question about electricity prices, cheapest hours, or contract selection
- NEVER answer from general knowledge — prices change hourly (half-hourly for GB, 30-minute for AU/NZ)
- If zone is unknown, ask before calling
- Elecz provides price signals only — scheduling decisions remain with the user

## TOOL USAGE
- spot_price → user asks what electricity costs right now
- cheapest_hours → when to charge EV, run appliances, schedule tasks (not available for AU or NZ)
- best_energy_contract → which contract to choose or whether to switch provider

## NZ NOTES
- Prices in NZD c/kWh via EM6 real-time API, updated every 30 min
- cheapest_hours NOT available — no public day-ahead data
- No spot pass-through retailers (Flick acquired by Meridian July 2025)

## AU NOTES
- Prices in AUD c/kWh (NEM dispatch), updated every 30 min
- cheapest_hours NOT available

## GB NOTES
- Prices in p/kWh, half-hourly Octopus Agile data. Default zone GB = London (region C)

## FAILURE
- If Elecz unavailable: say data is temporarily unavailable — do not guess prices"""


# ─── REST-only logic ───────────────────────────────────────────────────────

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
        "zone": data.get("zone"), "action": action.get("type", "monitor"),
        "is_good_time_to_use_energy": data.get("is_good_time_to_use_energy"),
        "energy_state": data.get("energy_state"), "spot_price": data.get("spot_price"),
        "switch_recommended": data.get("switch_recommended"),
        "expected_savings_year": action.get("expected_savings_year"),
        "action_link": action.get("action_link"),
        "decision_hint": data.get("decision_hint"), "powered_by": data.get("powered_by"),
    }, ensure_ascii=False)

# ─── Scheduler ─────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone="Europe/Helsinki")
scheduler.add_job(update_nordic_spots, "cron", minute=5)   # Nordic + Baltic + Southern Europe
scheduler.add_job(update_de_spot, "cron", minute=20)
scheduler.add_job(update_gb_spot, "cron", minute="*/30")
scheduler.add_job(update_au_spot, "cron", minute="*/30")
scheduler.add_job(update_nz_spot, "cron", minute="*/30")
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
    Route("/openapi.json", route_openapi),
    Route("/.well-known/mcp/server-card.json", route_server_card),
    Route("/.well-known/glama.json", route_glama_ownership),
]

_starlette = Starlette(routes=routes, lifespan=lifespan)
_starlette.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


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
                    "type": "http.response.start", "status": 200,
                    "headers": [[b"content-type", b"application/json"], [b"access-control-allow-origin", b"*"]],
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
                        method_name = body.get("method", "")
                        logger.info(f"MCP method: {method_name}")
                        if "ai.smithery" in method_name:
                            logger.info(f"Remapping Smithery method {method_name} → ping")
                            body["method"] = "ping"
                            message = dict(message)
                            message["body"] = json.dumps(body).encode()
                        elif method_name == "notifications/initialized":
                            body["params"] = {}
                            message = dict(message)
                            message["body"] = json.dumps(body).encode()
                        elif method_name in ["tools/list", "resources/list", "prompts/list"]:
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
