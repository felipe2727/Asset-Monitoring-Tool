"""
Prediction market ingestion — Polymarket + Kalshi.

Fetches crowd-sourced probabilities on geopolitical, economic, and regulatory events.
Both APIs are free and require no authentication.
"""
import asyncio
import logging

import httpx

from sentinel.config import POLYMARKET_API, KALSHI_API
from sentinel.utils.resilience import CircuitBreaker, rate_limiters

logger = logging.getLogger(__name__)

cb = CircuitBreaker(max_failures=3, cooldown_seconds=300)

# Tags that map to our signal types
FINANCE_TAGS = {"economy", "fed", "inflation", "interest-rates", "recession", "trade", "tariffs", "debt-ceiling", "finance"}
GEO_TAGS = {"geopolitical", "war", "conflict", "sanctions", "military"}
CRYPTO_TAGS = {"crypto", "bitcoin", "ethereum", "defi", "stablecoin"}
TECH_TAGS = {"ai", "tech", "science", "semiconductor"}
REGULATORY_TAGS = {"regulation", "sec", "legal", "policy"}

# Asset mapping based on event categories
TAG_TO_ASSETS: dict[str, list[str]] = {
    "fed":            ["VNQ", "O", "GLD"],
    "interest-rates": ["VNQ", "O", "GLD"],
    "recession":      ["GLD", "SLV", "BTC"],
    "inflation":      ["GLD", "USO", "UNG"],
    "tariffs":        ["AAPL", "AMZN", "TSLA", "CPER"],
    "trade":          ["AAPL", "AMZN", "TSLA", "CPER"],
    "sanctions":      ["USO", "UNG", "GLD"],
    "war":            ["GLD", "USO", "BTC"],
    "conflict":       ["GLD", "USO", "BTC"],
    "crypto":         ["BTC", "ETH", "SOL"],
    "bitcoin":        ["BTC"],
    "ethereum":       ["ETH"],
    "regulation":     ["BTC", "ETH", "COIN"],
    "sec":            ["COIN", "BTC", "ETH"],
    "ai":             ["NVDA", "AMD", "AVGO"],
    "semiconductor":  ["NVDA", "AMD", "AVGO"],
}


def _map_event_to_assets(event: dict) -> list[str]:
    """Maps a prediction market event to affected asset symbols via tags."""
    tags = set()
    # Polymarket uses "tags" as a list of dicts or strings
    raw_tags = event.get("tags", [])
    if isinstance(raw_tags, list):
        for t in raw_tags:
            if isinstance(t, dict):
                tags.add(t.get("slug", "").lower())
                tags.add(t.get("label", "").lower())
            elif isinstance(t, str):
                tags.add(t.lower())

    # Also scan the title for keywords
    title = event.get("title", "").lower()
    for keyword in TAG_TO_ASSETS:
        if keyword in title:
            tags.add(keyword)

    assets = []
    for tag in tags:
        assets.extend(TAG_TO_ASSETS.get(tag, []))
    return list(set(assets))


async def _fetch_polymarket(client: httpx.AsyncClient) -> list[dict]:
    """Fetches active prediction market events from Polymarket."""
    if not cb.is_available("polymarket"):
        return []

    events: list[dict] = []
    try:
        for tag in ["finance", "geopolitics", "crypto"]:
            await rate_limiters["polymarket"].acquire()
            resp = await client.get(
                POLYMARKET_API,
                params={"tag": tag, "closed": "false", "limit": 20},
                timeout=20,
            )
            if not resp.is_success:
                logger.warning("  Polymarket tag=%s: HTTP %d", tag, resp.status_code)
                cb.record_failure("polymarket")
                continue

            data = resp.json()
            items = data if isinstance(data, list) else data.get("events", data.get("data", []))

            for item in items:
                # Skip low-volume markets (< $1000)
                volume = float(item.get("volume", 0) or item.get("volumeNum", 0) or 0)
                if volume < 1000:
                    continue

                # Extract probability from yesPrice (0-100 cents -> 0-1)
                yes_price = item.get("yesPrice")
                if yes_price is None:
                    # Try markets sub-array
                    markets = item.get("markets", [])
                    if markets and isinstance(markets, list):
                        yes_price = markets[0].get("yesPrice") or markets[0].get("lastTradePrice")

                if yes_price is not None:
                    prob = float(yes_price) / 100.0 if float(yes_price) > 1 else float(yes_price)
                else:
                    prob = 0.5

                affected = _map_event_to_assets(item)

                events.append({
                    "source":       "polymarket",
                    "title":        item.get("title", ""),
                    "probability":  prob,
                    "volume":       volume,
                    "end_date":     item.get("endDate", ""),
                    "affected_assets": affected,
                    "_tags":        [t.get("slug", t) if isinstance(t, dict) else t
                                     for t in item.get("tags", [])],
                })

            cb.record_success("polymarket")

    except Exception as exc:
        logger.warning("  Polymarket fetch error: %s", exc)
        cb.record_failure("polymarket")

    return events


async def _fetch_kalshi(client: httpx.AsyncClient) -> list[dict]:
    """Fetches active prediction market events from Kalshi."""
    if not cb.is_available("kalshi"):
        return []

    events: list[dict] = []
    try:
        await rate_limiters["kalshi"].acquire()
        resp = await client.get(
            KALSHI_API,
            params={"status": "open", "limit": 30},
            timeout=20,
        )
        if not resp.is_success:
            logger.warning("  Kalshi: HTTP %d", resp.status_code)
            cb.record_failure("kalshi")
            return []

        data = resp.json()
        items = data.get("events", [])

        for item in items:
            title = item.get("title", "")
            markets = item.get("markets", [])

            # Aggregate across sub-markets
            for mkt in markets:
                yes_price = mkt.get("yes_price") or mkt.get("last_price", 50)
                volume = int(mkt.get("volume", 0) or 0)

                if volume < 100:
                    continue

                prob = float(yes_price) / 100.0 if float(yes_price) > 1 else float(yes_price)

                # Map via title keywords
                affected: list[str] = []
                title_lower = title.lower()
                for keyword, assets in TAG_TO_ASSETS.items():
                    if keyword in title_lower:
                        affected.extend(assets)
                affected = list(set(affected))

                events.append({
                    "source":          "kalshi",
                    "title":           f"{title} - {mkt.get('ticker', '')}",
                    "probability":     prob,
                    "volume":          volume,
                    "end_date":        mkt.get("close_time", ""),
                    "affected_assets": affected,
                })

        cb.record_success("kalshi")

    except Exception as exc:
        logger.warning("  Kalshi fetch error: %s", exc)
        cb.record_failure("kalshi")

    return events


async def fetch_prediction_markets() -> list[dict]:
    """
    Fetches prediction market data from Polymarket and Kalshi.
    Returns combined list of market events with probabilities and asset mappings.
    """
    async with httpx.AsyncClient() as client:
        polymarket_events = await _fetch_polymarket(client)
        kalshi_events = await _fetch_kalshi(client)

    all_events = polymarket_events + kalshi_events

    with_assets = sum(1 for e in all_events if e["affected_assets"])
    logger.info(
        "Prediction markets: %d Polymarket + %d Kalshi events (%d with asset mappings)",
        len(polymarket_events), len(kalshi_events), with_assets,
    )
    return all_events


def compute_prediction_market_signal(events: list[dict], symbol: str) -> float:
    """
    Computes a prediction-market-based signal for one asset.
    High-probability negative events (recession, war) -> negative signal for risk assets.
    High-probability positive events (ETF approval) -> positive signal.

    Returns: float in [-1.0, 1.0]
    """
    relevant = [e for e in events if symbol in e.get("affected_assets", [])]
    if not relevant:
        return 0.0

    # Score each event based on probability and nature
    signals: list[float] = []
    for event in relevant:
        prob = event.get("probability", 0.5)
        title = event.get("title", "").lower()
        volume = event.get("volume", 0)

        # Volume-based confidence (higher volume = more reliable)
        vol_weight = min(1.0, volume / 50000) if volume else 0.3

        # Determine direction from title keywords
        negative_keywords = ["recession", "war", "conflict", "default", "crisis", "crash",
                             "ban", "reject", "sanctions", "collapse"]
        positive_keywords = ["approved", "growth", "recovery", "rate cut", "peace",
                             "settlement", "expansion"]

        is_negative = any(kw in title for kw in negative_keywords)
        is_positive = any(kw in title for kw in positive_keywords)

        if is_negative:
            # High prob of negative event = negative signal
            signal = -(prob - 0.5) * 2.0  # prob=0.8 -> -0.6, prob=0.2 -> +0.6
        elif is_positive:
            signal = (prob - 0.5) * 2.0
        else:
            # Ambiguous — slight negative bias (uncertainty = risk)
            signal = -(prob - 0.5) * 0.5

        signals.append(signal * vol_weight)

    if not signals:
        return 0.0

    avg_signal = sum(signals) / len(signals)
    return max(-1.0, min(1.0, avg_signal))
