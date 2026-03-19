"""
RSS feed parser using feedparser.
Fetches headlines + summaries from 15+ financial news sources.
"""
import asyncio
import hashlib
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx
import feedparser

from sentinel.config import RSS_FEEDS, SOURCE_TIERS, get_active_assets, get_match_keywords

logger = logging.getLogger(__name__)

# Keywords and cashtags to match articles to assets
REGULATORY_KEYWORDS = [
    "sec ", "regulation", "ban ", "approval", "etf filing", "cftc", "mica",
    "stablecoin", "executive order", "enforcement action", "fine ", "settlement",
    "esma", "compliance", "lawsuit",
]


def _parse_date(entry: feedparser.FeedParserDict) -> str:
    """Best-effort date extraction from feed entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6]).isoformat()
            except Exception:
                pass
    return datetime.utcnow().isoformat()


def _stable_url_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _match_assets(text: str, assets) -> list[str]:
    """Returns asset symbols mentioned in the text using keyword matching."""
    text_lower = text.lower()
    mentioned = []
    for asset in assets:
        keywords = get_match_keywords(asset)
        if any(kw in text_lower for kw in keywords):
            mentioned.append(asset.symbol)
    return list(set(mentioned))


async def _fetch_feed(
    client: httpx.AsyncClient,
    feed_config: dict,
) -> list[dict]:
    """Fetches and parses one RSS feed, returns list of article dicts."""
    url = feed_config["url"]
    source = feed_config["source"]
    tier = feed_config.get("tier", SOURCE_TIERS.get(source, 0.5))

    try:
        resp = await client.get(url, timeout=15, follow_redirects=True)
        content = resp.text
    except Exception as exc:
        logger.warning("  RSS %s: fetch error — %s", source, exc)
        return []

    feed = feedparser.parse(content)
    if not feed.entries:
        logger.debug("  RSS %s: no entries", source)
        return []

    active_assets = get_active_assets()

    articles = []
    for entry in feed.entries[:30]:  # cap at 30 per feed
        title = getattr(entry, "title", "")
        summary = getattr(entry, "summary", "")
        link = getattr(entry, "link", "")
        if not link:
            continue

        text = f"{title} {summary}"
        mentioned = _match_assets(text, active_assets)

        articles.append({
            "source":        source,
            "source_tier":   tier,
            "title":         title,
            "summary":       summary[:1000],
            "url":           link,
            "asset_symbols": mentioned,
            "published_at":  _parse_date(entry),
            "_is_regulatory": any(kw in text.lower() for kw in REGULATORY_KEYWORDS),
        })

    logger.info("  RSS %s: %d articles", source, len(articles))
    return articles


async def fetch_rss_feeds() -> list[dict]:
    """Fetches all configured RSS feeds concurrently."""
    async with httpx.AsyncClient(
        headers={"User-Agent": "Sentinel/1.0 (financial monitoring bot)"},
    ) as client:
        tasks = [_fetch_feed(client, cfg) for cfg in RSS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles: list[dict] = []
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)
        elif isinstance(result, Exception):
            logger.error("RSS feed error: %s", result)

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for a in all_articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)

    logger.info("RSS complete: %d unique articles from %d feeds", len(unique), len(RSS_FEEDS))
    return unique
