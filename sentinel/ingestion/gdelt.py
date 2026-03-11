"""
GDELT 2.0 geopolitical event fetcher.
Free, no API key required, updates every 15 minutes.
"""
import asyncio
import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

CONFLICT_THEMES = [
    "MILITARY", "SANCTION", "TRADE_WAR", "PROTEST", "CRISI", "ARMED_CONFLICT",
    "FOOD_SECURITY", "ENERGY_SECURITY", "CYBER_ATTACK",
]

# GDELT tone/goldstein → asset impact mapping
SAFE_HAVEN_ASSETS   = ["GLD", "SLV"]
ENERGY_ASSETS       = ["USO", "UNG"]
DEFENSE_THEMES      = ["MILITARY", "ARMED_CONFLICT"]
ENERGY_THEMES       = ["ENERGY_SECURITY", "SANCTION"]


async def fetch_gdelt_events() -> list[dict]:
    """
    Fetches GDELT events from the last 24 hours matching conflict/macro themes.
    Returns normalised event dicts.
    """
    query = " OR ".join(CONFLICT_THEMES)
    params = {
        "query":       query,
        "mode":        "artlist",
        "maxrecords":  100,
        "format":      "json",
        "timespan":    "1440",  # last 1440 minutes = 24 hours
        "sort":        "DateDesc",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(GDELT_DOC_API, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("GDELT fetch error: %s", exc)
        return []

    articles = data.get("articles", [])
    events: list[dict] = []

    for art in articles:
        tone = art.get("tone", 0)
        title = art.get("title", "")
        url = art.get("url", "")
        themes = [t.strip() for t in art.get("socialimage", "").split(",")]  # GDELT themes field

        # Map to affected assets
        affected: list[str] = []
        title_lower = title.lower()

        if any(t in title_lower for t in ["gold", "silver", "safe haven", "refuge"]):
            affected.extend(SAFE_HAVEN_ASSETS)
        if any(t in title_lower for t in ["oil", "crude", "opec", "energy", "gas"]):
            affected.extend(ENERGY_ASSETS)
        if any(t in title_lower for t in ["military", "war", "conflict", "troops"]):
            affected.extend(["GLD"])  # safe haven
        if any(t in title_lower for t in ["bitcoin", "crypto", "btc"]):
            affected.extend(["BTC"])
        if any(t in title_lower for t in ["nvidia", "semiconductor", "chip"]):
            affected.extend(["NVDA", "AMD"])

        events.append({
            "event_code":       art.get("domain", ""),
            "event_description":title,
            "actor1_country":   art.get("sourcecountry", ""),
            "actor2_country":   "",
            "tone":             float(tone) if tone else 0.0,
            "goldstein_scale":  0.0,  # GDELT doc API doesn't return goldstein directly
            "num_mentions":     1,
            "affected_assets":  list(set(affected)),
            "event_date":       datetime.utcnow().date().isoformat(),
            "_url":             url,
        })

    logger.info("GDELT: %d events fetched", len(events))
    return events


def compute_geopolitical_score(events: list[dict], symbol: str) -> float:
    """
    Aggregates GDELT events to produce a geopolitical signal score for one asset.
    Score range: -1.0 (very negative) to +1.0 (very positive).
    """
    if not events:
        return 0.0

    relevant = [e for e in events if symbol in e.get("affected_assets", [])]
    if not relevant:
        return 0.0

    # Tone is GDELT's sentiment: negative = bad news, positive = good news
    # For safe havens (gold, etc.) negative world tone = GOOD signal (capital flows in)
    safe_haven_assets = {"GLD", "SLV", "BTC"}
    is_safe_haven = symbol in safe_haven_assets

    total_tone = sum(e["tone"] for e in relevant)
    avg_tone = total_tone / len(relevant)

    if is_safe_haven:
        # Negative world tone → positive for safe havens
        raw_signal = -avg_tone / 10.0
    else:
        raw_signal = avg_tone / 10.0

    return max(-1.0, min(1.0, raw_signal))
