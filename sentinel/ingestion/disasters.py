"""
Natural disaster and environmental threat ingestion.

- USGS Earthquake Feed: 4.5+ magnitude quakes (free, no auth)
- NASA FIRMS: Satellite fire/wildfire detection (free, API key)
- Cloudflare Radar: Internet outage tracking (free, bearer token)

Maps events to affected assets via geo-proximity to production zones.
"""
import asyncio
import csv
import io
import logging
import math
from datetime import datetime, timezone

import httpx

from sentinel.config import (
    USGS_EARTHQUAKE_URL, NASA_FIRMS_API_KEY, NASA_FIRMS_URL,
    CLOUDFLARE_RADAR_TOKEN, CLOUDFLARE_RADAR_URL,
    PRODUCTION_ZONES,
)
from sentinel.utils.resilience import CircuitBreaker, rate_limiters

logger = logging.getLogger(__name__)

cb = CircuitBreaker(max_failures=3, cooldown_seconds=300)

# Haversine distance in km
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _map_to_assets(lat: float, lon: float) -> list[str]:
    """Maps a geographic event to affected assets via proximity to production zones."""
    assets: list[str] = []
    for zone_lat, zone_lon, radius_km, zone_assets in PRODUCTION_ZONES:
        dist = _haversine_km(lat, lon, zone_lat, zone_lon)
        if dist <= radius_km:
            assets.extend(zone_assets)
    return list(set(assets))


# ─────────────────────────────────────────────────────────────────────────────
# USGS Earthquake Feed (free, no auth, pre-generated GeoJSON)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_usgs_earthquakes(client: httpx.AsyncClient) -> list[dict]:
    """Fetches 4.5+ magnitude earthquakes from the last 24 hours."""
    if not cb.is_available("usgs"):
        return []

    try:
        await rate_limiters["usgs"].acquire()
        resp = await client.get(USGS_EARTHQUAKE_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        cb.record_success("usgs")
    except Exception as exc:
        logger.warning("  USGS earthquake fetch failed: %s", exc)
        cb.record_failure("usgs")
        return []

    features = data.get("features", [])
    events: list[dict] = []

    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [0, 0, 0])

        lon, lat = float(coords[0]), float(coords[1])
        depth_km = float(coords[2]) if len(coords) > 2 else 0.0
        magnitude = float(props.get("mag", 0))
        place = props.get("place", "")
        timestamp_ms = props.get("time", 0)

        try:
            occurred_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
        except Exception:
            occurred_at = ""

        affected = _map_to_assets(lat, lon)

        events.append({
            "source":          "usgs",
            "type":            "earthquake",
            "magnitude":       magnitude,
            "place":           place,
            "latitude":        lat,
            "longitude":       lon,
            "depth_km":        depth_km,
            "occurred_at":     occurred_at,
            "affected_assets": affected,
            "_severity":       "critical" if magnitude >= 7.0 else "high" if magnitude >= 6.0 else "medium",
        })

    return events


# ─────────────────────────────────────────────────────────────────────────────
# NASA FIRMS — Satellite Fire Detection (free, API key)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_nasa_firms(client: httpx.AsyncClient) -> list[dict]:
    """Fetches significant fire detections from NASA FIRMS (last 24h)."""
    if not NASA_FIRMS_API_KEY:
        logger.info("  NASA FIRMS: API key not set, skipping")
        return []
    if not cb.is_available("nasa_firms"):
        return []

    try:
        await rate_limiters["nasa_firms"].acquire()
        # Global bounding box, last 1 day
        url = f"{NASA_FIRMS_URL}/{NASA_FIRMS_API_KEY}/VIIRS_SNPP_NRT/-180,-90,180,90/1"
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()
        cb.record_success("nasa_firms")
    except Exception as exc:
        logger.warning("  NASA FIRMS fetch failed: %s", exc)
        cb.record_failure("nasa_firms")
        return []

    events: list[dict] = []
    reader = csv.DictReader(io.StringIO(resp.text))

    for row in reader:
        try:
            confidence = int(row.get("confidence", "0").strip() or "0")
            frp = float(row.get("frp", "0").strip() or "0")

            # Filter: only significant fires (confidence >= 50, frp >= 10)
            if confidence < 50 or frp < 10:
                continue

            lat = float(row.get("latitude", 0))
            lon = float(row.get("longitude", 0))
            affected = _map_to_assets(lat, lon)

            # Only keep fires near production zones
            if not affected:
                continue

            events.append({
                "source":          "nasa_firms",
                "type":            "fire",
                "latitude":        lat,
                "longitude":       lon,
                "brightness":      float(row.get("bright_ti4", 0) or 0),
                "confidence":      confidence,
                "frp":             frp,  # Fire Radiative Power
                "acq_date":        row.get("acq_date", ""),
                "acq_time":        row.get("acq_time", ""),
                "affected_assets": affected,
                "_severity":       "high" if frp >= 50 else "medium",
            })
        except (ValueError, KeyError):
            continue

    return events


# ─────────────────────────────────────────────────────────────────────────────
# Cloudflare Radar — Internet Outage Tracking (free, bearer token)
# ─────────────────────────────────────────────────────────────────────────────

# Country -> asset mapping (internet outages in these countries = supply disruption)
OUTAGE_COUNTRY_MAP: dict[str, list[str]] = {
    "IR": ["USO", "UNG"],       # Iran — oil/gas sanctions
    "RU": ["USO", "UNG", "GLD"],# Russia — energy & safe havens
    "CN": ["NVDA", "AMD", "AAPL", "AMZN", "CPER"],  # China — tech + copper
    "TW": ["NVDA", "AMD", "AVGO"],  # Taiwan — semiconductors
    "KR": ["NVDA", "AMD"],      # South Korea — semiconductors
    "SA": ["USO"],              # Saudi Arabia — oil
    "UA": ["GLD", "USO"],       # Ukraine — safe havens + energy
    "IQ": ["USO"],              # Iraq — oil
    "LY": ["USO"],              # Libya — oil
    "VE": ["USO"],              # Venezuela — oil
    "CL": ["CPER"],             # Chile — copper
    "PE": ["CPER", "GLD"],      # Peru — copper + gold
    "ZA": ["GLD"],              # South Africa — gold
}


async def _fetch_cloudflare_outages(client: httpx.AsyncClient) -> list[dict]:
    """Fetches recent internet outages from Cloudflare Radar."""
    if not CLOUDFLARE_RADAR_TOKEN:
        logger.debug("  Cloudflare Radar: token not set, skipping")
        return []
    if not cb.is_available("cloudflare"):
        return []

    try:
        await rate_limiters["cloudflare"].acquire()
        resp = await client.get(
            CLOUDFLARE_RADAR_URL,
            params={"dateRange": "1d", "limit": 20},
            headers={"Authorization": f"Bearer {CLOUDFLARE_RADAR_TOKEN}"},
            timeout=20,
        )
        resp.raise_for_status()
        cb.record_success("cloudflare")
    except Exception as exc:
        logger.warning("  Cloudflare Radar fetch failed: %s", exc)
        cb.record_failure("cloudflare")
        return []

    data = resp.json()
    annotations = data.get("result", {}).get("annotations", [])
    events: list[dict] = []

    for ann in annotations:
        raw_locations = ann.get("locations", "")
        # API returns locations as list or comma-separated string
        if isinstance(raw_locations, list):
            locations = raw_locations
        else:
            locations = str(raw_locations).split(",") if raw_locations else []
        cause = ann.get("outage", {}).get("outageCause", "unknown") if isinstance(ann.get("outage"), dict) else "unknown"
        scope = ann.get("scope", "")

        affected: list[str] = []
        for loc in locations:
            loc = loc.strip().upper()
            affected.extend(OUTAGE_COUNTRY_MAP.get(loc, []))
        affected = list(set(affected))

        if not affected:
            continue

        events.append({
            "source":          "cloudflare_radar",
            "type":            "internet_outage",
            "locations":       locations,
            "cause":           cause,
            "scope":           scope,
            "start_date":      ann.get("startDate", ""),
            "end_date":        ann.get("endDate", ""),
            "affected_assets": affected,
            "_severity":       "high" if scope == "nationwide" else "medium",
        })

    return events


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_disaster_events() -> list[dict]:
    """
    Fetches all disaster/environmental events:
    USGS earthquakes + NASA FIRMS fires + Cloudflare outages.
    """
    async with httpx.AsyncClient() as client:
        earthquakes = await _fetch_usgs_earthquakes(client)
        fires = await _fetch_nasa_firms(client)
        outages = await _fetch_cloudflare_outages(client)

    all_events = earthquakes + fires + outages

    eq_with_assets = sum(1 for e in earthquakes if e["affected_assets"])
    fire_with_assets = len(fires)  # already filtered to production zones

    logger.info(
        "Disasters: %d earthquakes (%d near production zones), %d fires, %d outages",
        len(earthquakes), eq_with_assets, len(fires), len(outages),
    )
    return all_events


def compute_disaster_signal(events: list[dict], symbol: str) -> float:
    """
    Computes a disaster-based supply disruption signal for one asset.
    Returns: float in [-1.0, 1.0] (negative = disruption risk, positive = unaffected)

    For safe-haven assets (GLD, SLV, BTC), disasters = positive signal (capital inflow).
    For production assets, disasters = negative signal (supply disruption).
    """
    relevant = [e for e in events if symbol in e.get("affected_assets", [])]
    if not relevant:
        return 0.0

    safe_havens = {"GLD", "SLV", "BTC"}
    is_safe_haven = symbol in safe_havens

    severity_weights = {"critical": 1.0, "high": 0.7, "medium": 0.4}
    total_impact = 0.0

    for event in relevant:
        sev = event.get("_severity", "medium")
        weight = severity_weights.get(sev, 0.4)

        if event["type"] == "earthquake":
            # Scale by magnitude
            mag = event.get("magnitude", 5.0)
            impact = weight * (mag - 4.0) / 4.0  # 4.5 -> 0.125, 7.0 -> 0.75, 8.0 -> 1.0
        elif event["type"] == "fire":
            frp = event.get("frp", 10)
            impact = weight * min(1.0, frp / 100.0)
        elif event["type"] == "internet_outage":
            impact = weight * (0.8 if event.get("scope") == "nationwide" else 0.4)
        else:
            impact = weight * 0.3

        total_impact += impact

    # Cap total impact
    total_impact = min(1.0, total_impact)

    if is_safe_haven:
        return total_impact   # disasters drive capital into safe havens
    else:
        return -total_impact  # disasters disrupt production/supply
