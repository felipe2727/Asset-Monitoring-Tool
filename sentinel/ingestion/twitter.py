"""
ScrapeBadger X/Twitter scraper.
Docs: https://scrapebadger.com/docs
Credits: 1 per search call (up to 100 tweets). Trial: 1,000 free credits = 66+ full runs.
"""
import asyncio
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel.config import SCRAPEBADGER_API_KEY, get_active_assets, TWEETS_PER_ASSET

logger = logging.getLogger(__name__)

SCRAPEBADGER_URL = "https://scrapebadger.com/v1/twitter/tweets/advanced_search"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_tweets_for_query(
    client: httpx.AsyncClient,
    query: str,
    count: int,
) -> list[dict]:
    """
    Calls the ScrapeBadger Twitter Advanced Search API.
    1 credit per search call regardless of result count.
    """
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

    # ScrapeBadger returns {"data": [...], "next_cursor": ...}
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", data.get("tweets", []))
    return []


def _extract_tweet(raw: dict, asset_symbol: str) -> dict:
    """Normalise a raw ScrapeBadger tweet object into our schema."""
    return {
        "tweet_id":        str(raw.get("id") or raw.get("tweet_id", "")),
        "asset_symbol":    asset_symbol,
        "tweet_text":      raw.get("full_text") or raw.get("text", ""),
        "author_handle":   raw.get("username", ""),
        "author_verified": raw.get("user_verified") or raw.get("user_is_blue_verified", False),
        "likes":           raw.get("favorite_count", 0),
        "retweets":        raw.get("retweet_count", 0),
        "replies":         raw.get("reply_count", 0),
        "views":           str(raw.get("view_count", "")),
    }


async def scrape_twitter() -> list[dict]:
    """
    Scrapes tweets for all active assets using ScrapeBadger.
    1 credit per asset (1 search call). Returns flat list of tweet dicts.
    """
    if not SCRAPEBADGER_API_KEY:
        logger.warning("SCRAPEBADGER_API_KEY not set — skipping Twitter scrape")
        return []

    assets = get_active_assets()
    all_tweets: list[dict] = []

    queries: list[tuple[str, str]] = []
    for asset in assets:
        if asset.asset_class == "crypto":
            queries.append((asset.symbol, f"#{asset.symbol} OR {asset.name}"))
        else:
            queries.append((asset.symbol, f"${asset.symbol} OR {asset.name}"))

    async with httpx.AsyncClient() as client:
        for symbol, query in queries:
            try:
                raw_tweets = await _fetch_tweets_for_query(client, query, TWEETS_PER_ASSET)
                tweets = [_extract_tweet(t, symbol) for t in raw_tweets if t]
                all_tweets.extend(tweets)
                logger.info("  Twitter %s: fetched %d tweets", symbol, len(tweets))
            except Exception as exc:
                logger.error("  Twitter %s: error — %s", symbol, exc)

            # ScrapeBadger free tier: 5 req/min — must pace at 1 per 13s
            await asyncio.sleep(13)

    logger.info("Twitter scrape complete: %d tweets across %d assets", len(all_tweets), len(queries))
    return all_tweets
