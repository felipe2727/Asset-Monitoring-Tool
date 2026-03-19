"""
GDELT 2.0 geopolitical event fetcher.
Free, no API key required, updates every 15 minutes.
"""
import asyncio
import logging
import random
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# Split into smaller query groups to reduce GDELT processing load
# NOTE: GDELT requires OR queries to be wrapped in parentheses
QUERY_GROUPS = [
    "(military OR sanctions OR trade war OR conflict)",
    "(oil OR gold OR copper OR natural gas OR commodity)",
]

# GDELT tone/goldstein -> asset impact mapping
SAFE_HAVEN_ASSETS = ["GLD", "SLV"]
ENERGY_ASSETS = ["USO", "UNG"]

# Expanded keyword -> asset mapping
ASSET_KEYWORD_MAP = [
    # Commodities
    (["gold", "silver", "safe haven", "refuge", "precious metal"],          ["GLD", "SLV"]),
    (["oil", "crude", "opec", "petroleum", "wti", "brent"],                 ["USO"]),
    (["natural gas", "lng", "henry hub"],                                    ["UNG"]),
    (["copper", "mining", "base metal"],                                     ["CPER"]),
    # Geopolitical -> safe havens
    (["military", "war", "conflict", "troops", "missile", "invasion"],       ["GLD", "BTC"]),
    (["sanctions", "iran", "russia", "libya", "embargo"],                    ["USO", "UNG", "GLD"]),
    # Crypto
    (["bitcoin", "crypto", "btc", "stablecoin", "central bank digital"],     ["BTC"]),
    (["ethereum", "defi"],                                                    ["ETH"]),
    # Tech
    (["semiconductor", "chip", "nvidia", "ai regulation"],                   ["NVDA", "AMD"]),
    (["tariff", "trade war", "supply chain"],                                ["AAPL", "AMZN", "TSLA"]),
    # REITs
    (["real estate", "housing", "mortgage", "interest rate", "fed rate"],     ["VNQ", "O"]),
]


async def _fetch_gdelt_query(client: httpx.AsyncClient, query: str) -> list[dict]:
    """Fetches one GDELT query with exponential backoff."""
    params = {
        "query":      query,
        "mode":       "artlist",
        "maxrecords": 50,
        "format":     "json",
        "timespan":   "720",  # last 12 hours (less load than 24h)
        "sort":       "DateDesc",
    }

    for attempt in range(3):
        try:
            resp = await client.get(GDELT_DOC_API, params=params, timeout=20)
            resp.raise_for_status()

            # Validate response is actually JSON
            body = resp.text.strip()
            if not body or body[0] not in "{[":
                logger.warning("  GDELT returned non-JSON response (%d bytes)", len(body))
                return []

            data = resp.json()
            return data.get("articles", [])

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < 2:
                wait = min(120, 30 * (2 ** attempt) + random.uniform(0, 10))
                logger.info("  GDELT rate-limited, waiting %.0fs (attempt %d/3)...", wait, attempt + 1)
                await asyncio.sleep(wait)
            else:
                logger.warning("  GDELT query error: HTTP %d", exc.response.status_code)
                return []
        except Exception as exc:
            logger.warning("  GDELT query error: %s", exc)
            return []

    return []


async def fetch_gdelt_events() -> list[dict]:
    """
    Fetches GDELT events from the last 12 hours matching conflict/macro themes.
    Splits into smaller queries to avoid rate limits.
    """
    all_articles: list[dict] = []

    async with httpx.AsyncClient() as client:
        for query in QUERY_GROUPS:
            articles = await _fetch_gdelt_query(client, query)
            all_articles.extend(articles)
            # Pause between queries to avoid rate limiting
            if articles:
                await asyncio.sleep(5)

    events: list[dict] = []
    for art in all_articles:
        tone = art.get("tone", 0)
        title = art.get("title", "")
        url = art.get("url", "")

        # Map to affected assets via keyword matching
        affected: list[str] = []
        title_lower = title.lower()

        for keywords, assets in ASSET_KEYWORD_MAP:
            if any(kw in title_lower for kw in keywords):
                affected.extend(assets)

        events.append({
            "event_code":        art.get("domain", ""),
            "event_description": title,
            "actor1_country":    art.get("sourcecountry", ""),
            "actor2_country":    "",
            "tone":              float(tone) if tone else 0.0,
            "goldstein_scale":   0.0,
            "num_mentions":      1,
            "affected_assets":   list(set(affected)),
            "event_date":        datetime.utcnow().date().isoformat(),
            "_url":              url,
        })

    logger.info("GDELT: %d events fetched (%d with asset mappings)",
                len(events), sum(1 for e in events if e["affected_assets"]))
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
        raw_signal = -avg_tone / 10.0
    else:
        raw_signal = avg_tone / 10.0

    return max(-1.0, min(1.0, raw_signal))
