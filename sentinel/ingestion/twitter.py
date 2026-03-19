"""
Twitter/X scraper — 3-tier cascade per asset.

Tier 1 (primary):  ScrapeBadger  (1 credit/search, 1000 free)
Tier 2 (fallback): Scrapingdog   (5 credits/search, 3 keys in .env)
Tier 3 (fallback): StockTwits    (free forever, 200 req/hr, no auth)
"""
import asyncio
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel.config import (
    SCRAPEBADGER_API_KEY, TWEETS_PER_ASSET,
    get_active_assets, get_match_keywords, get_scrapingdog_keys,
    SCRAPINGDOG_TWITTER_URL, STOCKTWITS_BASE, STOCKTWITS_SYMBOL_MAP,
)

logger = logging.getLogger(__name__)

SCRAPEBADGER_URL = "https://scrapebadger.com/v1/twitter/tweets/advanced_search"


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_query(asset) -> str:
    """Build a search query string for a given asset."""
    if asset.asset_class == "crypto":
        return f"#{asset.symbol} OR {asset.name}"
    return f"${asset.symbol} OR {asset.name}"


def _extract_tweet(raw: dict, asset_symbol: str) -> dict:
    """Normalise a raw tweet object (ScrapeBadger/Scrapingdog) into our schema."""
    return {
        "tweet_id":        str(raw.get("id") or raw.get("tweet_id", "")),
        "asset_symbol":    asset_symbol,
        "tweet_text":      raw.get("full_text") or raw.get("text", ""),
        "author_handle":   raw.get("username") or raw.get("screen_name", ""),
        "author_verified": raw.get("user_verified") or raw.get("user_is_blue_verified", False),
        "likes":           raw.get("favorite_count", 0),
        "retweets":        raw.get("retweet_count", 0),
        "replies":         raw.get("reply_count", 0),
        "views":           str(raw.get("view_count", "")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1: ScrapeBadger (1 credit/search, 5 req/min on free tier)
# ─────────────────────────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_scrapebadger(
    client: httpx.AsyncClient,
    query: str,
    count: int,
) -> list[dict]:
    """Calls the ScrapeBadger Twitter Advanced Search API."""
    params = {
        "query":      query,
        "query_type": "Top",
        "count":      min(count, 100),
    }
    headers = {"x-api-key": SCRAPEBADGER_API_KEY}
    resp = await client.get(SCRAPEBADGER_URL, params=params, headers=headers, timeout=30)
    if not resp.is_success:
        logger.warning("  ScrapeBadger %s — HTTP %d: %s", query[:40], resp.status_code, resp.text[:200])
        resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", data.get("tweets", []))
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2: Scrapingdog (5 credits/search, 3 API keys in .env)
# ─────────────────────────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_scrapingdog(
    client: httpx.AsyncClient,
    query: str,
    count: int,
    api_key: str,
) -> list[dict]:
    """Calls the Scrapingdog Twitter search API."""
    params = {
        "api_key": api_key,
        "query":   query,
        "type":    "Latest",
        "count":   min(count, 100),
    }
    resp = await client.get(SCRAPINGDOG_TWITTER_URL, params=params, timeout=30)
    if not resp.is_success:
        logger.warning("  Scrapingdog %s — HTTP %d: %s", query[:40], resp.status_code, resp.text[:200])
        resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", data.get("tweets", []))
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3: StockTwits (free, 200 req/hr, no auth)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_stocktwits(
    client: httpx.AsyncClient,
    symbol: str,
) -> list[dict]:
    """Fetches recent messages for a symbol from StockTwits."""
    st_symbol = STOCKTWITS_SYMBOL_MAP.get(symbol, symbol)
    url = f"{STOCKTWITS_BASE}/streams/symbol/{st_symbol}.json"

    resp = await client.get(url, timeout=15)
    if not resp.is_success:
        logger.warning("  StockTwits %s — HTTP %d", symbol, resp.status_code)
        return []

    data = resp.json()
    return data.get("messages", [])


def _extract_stocktwits_message(msg: dict, asset_symbol: str) -> dict:
    """Map a StockTwits message to the tweet schema."""
    user = msg.get("user", {})
    return {
        "tweet_id":        f"st_{msg.get('id', '')}",
        "asset_symbol":    asset_symbol,
        "tweet_text":      msg.get("body", ""),
        "author_handle":   user.get("username", ""),
        "author_verified": user.get("official", False),
        "likes":           msg.get("likes", {}).get("total", 0) if isinstance(msg.get("likes"), dict) else 0,
        "retweets":        0,
        "replies":         0,
        "views":           "",
        "_source":         "stocktwits",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point — 3-tier cascade per asset
# ─────────────────────────────────────────────────────────────────────────────

async def scrape_twitter() -> list[dict]:
    """
    Scrapes social posts for all active assets.
    Cascade per asset: ScrapeBadger → Scrapingdog → StockTwits.
    """
    assets = get_active_assets()
    all_tweets: list[dict] = []

    # Build keyword map for cross-asset mention detection
    asset_keywords = {a.symbol: get_match_keywords(a) for a in assets}

    # Determine provider availability
    sb_available = bool(SCRAPEBADGER_API_KEY)
    sd_keys = get_scrapingdog_keys()
    sd_available = any(k for k, _ in sd_keys)
    sd_key = sd_keys[0][0] if sd_available else ""

    if not sb_available:
        logger.warning("SCRAPEBADGER_API_KEY not set — ScrapeBadger tier disabled")
    if not sd_available:
        logger.info("No Scrapingdog keys available — Scrapingdog tier disabled")

    async with httpx.AsyncClient() as client:
        for asset in assets:
            tweets: list[dict] = []
            source = "NONE"

            # ── Tier 1: ScrapeBadger ─────────────────────────────────────
            if sb_available and not tweets:
                try:
                    query = _build_query(asset)
                    raw = await _fetch_scrapebadger(client, query, TWEETS_PER_ASSET)
                    tweets = [_extract_tweet(t, asset.symbol) for t in raw if t]
                    if tweets:
                        source = "ScrapeBadger"
                except Exception as exc:
                    logger.warning("  ScrapeBadger %s failed: %s", asset.symbol, exc)
                    # Detect credit exhaustion — disable for remaining assets
                    exc_str = str(exc).lower()
                    if "402" in exc_str or "credit" in exc_str or "quota" in exc_str:
                        logger.warning("  ScrapeBadger credits exhausted — disabling for remaining assets")
                        sb_available = False

            # ── Tier 2: Scrapingdog ──────────────────────────────────────
            if not tweets and sd_available:
                try:
                    query = _build_query(asset)
                    raw = await _fetch_scrapingdog(client, query, TWEETS_PER_ASSET, sd_key)
                    tweets = [_extract_tweet(t, asset.symbol) for t in raw if t]
                    if tweets:
                        source = "Scrapingdog"
                except Exception as exc:
                    logger.warning("  Scrapingdog %s failed: %s", asset.symbol, exc)
                    exc_str = str(exc).lower()
                    if "402" in exc_str or "credit" in exc_str or "quota" in exc_str:
                        logger.warning("  Scrapingdog credits exhausted — disabling for remaining assets")
                        sd_available = False

            # ── Tier 3: StockTwits (free, always available) ──────────────
            if not tweets:
                try:
                    raw_msgs = await _fetch_stocktwits(client, asset.symbol)
                    tweets = [_extract_stocktwits_message(m, asset.symbol) for m in raw_msgs if m]
                    if tweets:
                        source = "StockTwits"
                except Exception as exc:
                    logger.warning("  StockTwits %s failed: %s", asset.symbol, exc)

            # ── Cross-asset mention scan (unchanged) ─────────────────────
            for tweet in tweets:
                text_lower = tweet["tweet_text"].lower()
                mentioned = []
                for sym, keywords in asset_keywords.items():
                    if any(kw in text_lower for kw in keywords):
                        mentioned.append(sym)
                if asset.symbol not in mentioned:
                    mentioned.insert(0, asset.symbol)
                tweet["_mentioned_assets"] = mentioned

            all_tweets.extend(tweets)
            logger.info("  Twitter %s (%s): %d posts", asset.symbol, source, len(tweets))

            # Pacing depends on which tier responded
            if source in ("ScrapeBadger", "Scrapingdog"):
                await asyncio.sleep(13)  # 5 req/min limit on commercial APIs
            elif source == "StockTwits":
                await asyncio.sleep(1)   # 200 req/hr — generous

    logger.info("Twitter scrape complete: %d posts across %d assets", len(all_tweets), len(assets))
    return all_tweets
