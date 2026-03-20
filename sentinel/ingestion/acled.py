"""
ACLED (Armed Conflict Location & Event Data) ingestion.

Provides structured conflict events with type, location, actors, and fatalities.
Complements GDELT (which measures news tone) with actual event data.

Auth: OAuth 2.0 (email + password) or legacy static token.
Free with registration at https://acleddata.com/
"""
import asyncio
import logging
from datetime import date, timedelta

import httpx

from sentinel.config import ACLED_EMAIL, ACLED_PASSWORD, ACLED_TOKEN_URL, ACLED_API_URL
from sentinel.utils.resilience import CircuitBreaker, rate_limiters

logger = logging.getLogger(__name__)

cb = CircuitBreaker(max_failures=2, cooldown_seconds=600)

# Cached OAuth token (lives for duration of pipeline run)
_cached_token: str = ""

# Event type -> asset mapping
EVENT_TYPE_ASSETS: dict[str, list[str]] = {
    "Battles":                       ["GLD", "USO", "UNG"],
    "Explosions/Remote violence":    ["GLD", "USO", "UNG"],
    "Violence against civilians":    ["GLD", "BTC"],
    "Protests":                      ["GLD", "BTC"],
    "Riots":                         ["GLD"],
    "Strategic developments":        ["GLD", "USO"],
}

# Country-specific asset mappings (conflict in these countries = specific impact)
COUNTRY_ASSET_MAP: dict[str, list[str]] = {
    "Ukraine":        ["GLD", "USO", "UNG"],
    "Russia":         ["GLD", "USO", "UNG"],
    "Iran":           ["USO", "UNG", "GLD"],
    "Iraq":           ["USO"],
    "Saudi Arabia":   ["USO"],
    "Libya":          ["USO"],
    "Israel":         ["USO", "GLD"],
    "Palestine":      ["USO", "GLD"],
    "Lebanon":        ["USO", "GLD"],
    "Yemen":          ["USO"],
    "Syria":          ["USO", "GLD"],
    "China":          ["NVDA", "AMD", "AAPL", "CPER"],
    "Taiwan":         ["NVDA", "AMD", "AVGO"],
    "South Korea":    ["NVDA", "AMD"],
    "Myanmar":        ["CPER"],
    "Chile":          ["CPER"],
    "Peru":           ["CPER", "GLD"],
    "South Africa":   ["GLD", "SLV"],
    "DR Congo":       ["CPER"],
    "Nigeria":        ["USO"],
    "Venezuela":      ["USO"],
}


async def _get_acled_token(client: httpx.AsyncClient) -> str:
    """Obtains an OAuth access token from ACLED. Returns empty string on failure."""
    global _cached_token
    if _cached_token:
        return _cached_token

    if not ACLED_EMAIL or not ACLED_PASSWORD:
        return ""

    try:
        resp = await client.post(
            ACLED_TOKEN_URL,
            data={
                "grant_type": "password",
                "client_id": "acled",
                "username": ACLED_EMAIL,
                "password": ACLED_PASSWORD,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        _cached_token = data.get("access_token", "")
        if _cached_token:
            logger.info("  ACLED: OAuth token obtained")
        return _cached_token
    except Exception as exc:
        logger.warning("  ACLED OAuth failed: %s", exc)
        return ""


async def fetch_acled_events() -> list[dict]:
    """
    Fetches armed conflict events from the last 3 days.
    Focuses on event types that impact financial markets.
    """
    if not ACLED_EMAIL or not ACLED_PASSWORD:
        logger.debug("  ACLED: credentials not set, skipping")
        return []
    if not cb.is_available("acled"):
        return []

    async with httpx.AsyncClient() as client:
        token = await _get_acled_token(client)
        if not token:
            return []

        today = date.today()
        start_date = (today - timedelta(days=3)).isoformat()
        end_date = today.isoformat()

        # Fetch conflict events (Battles + Explosions + Violence)
        event_types = "Battles|Explosions/Remote violence|Violence against civilians|Protests|Riots"

        try:
            await rate_limiters["acled"].acquire()
            resp = await client.get(
                ACLED_API_URL,
                params={
                    "event_type": event_types,
                    "event_date": f"{start_date}|{end_date}",
                    "event_date_where": "BETWEEN",
                    "limit": 200,
                    "_format": "json",
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            cb.record_success("acled")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                logger.warning("  ACLED 403 Forbidden — account may be on 'Open' tier (no API access). "
                               "Apply for Research-level access at acleddata.com/register/")
            else:
                logger.warning("  ACLED fetch failed: %s", exc)
            cb.record_failure("acled")
            return []
        except Exception as exc:
            logger.warning("  ACLED fetch failed: %s", exc)
            cb.record_failure("acled")
            return []

    raw_events = data.get("data", [])
    events: list[dict] = []

    for raw in raw_events:
        event_type = raw.get("event_type", "")
        country = raw.get("country", "")
        fatalities = int(raw.get("fatalities", 0) or 0)

        # Map to affected assets
        affected: list[str] = []
        affected.extend(EVENT_TYPE_ASSETS.get(event_type, []))
        affected.extend(COUNTRY_ASSET_MAP.get(country, []))
        affected = list(set(affected))

        # Compute severity based on fatalities and event type
        if fatalities >= 50 or event_type == "Battles":
            severity = "critical"
        elif fatalities >= 10 or event_type == "Explosions/Remote violence":
            severity = "high"
        elif fatalities >= 1:
            severity = "medium"
        else:
            severity = "low"

        events.append({
            "source":           "acled",
            "event_type":       event_type,
            "sub_event_type":   raw.get("sub_event_type", ""),
            "country":          country,
            "location":         raw.get("location", ""),
            "latitude":         float(raw.get("latitude", 0) or 0),
            "longitude":        float(raw.get("longitude", 0) or 0),
            "event_date":       raw.get("event_date", ""),
            "fatalities":       fatalities,
            "actor1":           raw.get("actor1", ""),
            "actor2":           raw.get("actor2", ""),
            "notes":            (raw.get("notes", "") or "")[:500],
            "affected_assets":  affected,
            "_severity":        severity,
        })

    with_assets = sum(1 for e in events if e["affected_assets"])
    logger.info(
        "ACLED: %d conflict events (%d with asset mappings, %d fatalities total)",
        len(events), with_assets, sum(e["fatalities"] for e in events),
    )
    return events


def compute_conflict_signal(events: list[dict], symbol: str) -> float:
    """
    Computes a conflict-based signal for one asset.
    Returns: float in [-1.0, 1.0]

    For safe-haven assets (GLD, SLV, BTC): conflict = positive (capital inflow).
    For risk assets: conflict = negative (supply disruption, uncertainty).
    """
    relevant = [e for e in events if symbol in e.get("affected_assets", [])]
    if not relevant:
        return 0.0

    safe_havens = {"GLD", "SLV", "BTC"}
    is_safe_haven = symbol in safe_havens

    severity_weights = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.2}
    total_impact = 0.0

    for event in relevant:
        sev = event.get("_severity", "low")
        base_weight = severity_weights.get(sev, 0.2)

        # Fatality-weighted intensity
        fatalities = event.get("fatalities", 0)
        fatality_factor = min(1.0, fatalities / 50.0) if fatalities > 0 else 0.1

        impact = base_weight * (0.5 + 0.5 * fatality_factor)
        total_impact += impact

    # Cap and normalize
    total_impact = min(1.0, total_impact / max(1, len(relevant)) * 1.5)

    if is_safe_haven:
        return total_impact
    else:
        return -total_impact
