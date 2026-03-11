"""
Reddit scraper using Reddit's public JSON API.
No OAuth, no API keys, no PRAW required.

Reddit exposes every public subreddit as JSON:
  GET https://www.reddit.com/r/{subreddit}/hot.json?limit=50

Rate limit: ~30 requests/minute is safe. We add a small delay between calls.
"""
import asyncio
import logging
from datetime import datetime

import httpx

from sentinel.config import SUBREDDITS, REDDIT_POSTS_PER_SUB, get_active_assets

logger = logging.getLogger(__name__)

REDDIT_JSON_BASE = "https://www.reddit.com"
HEADERS = {
    # Reddit requires a descriptive User-Agent or it returns 429
    "User-Agent": "Sentinel/1.0 (financial monitoring tool; contact: sentinel-bot)",
}


def _get_asset_mentions(text: str, symbols: list[str], names: list[str]) -> list[str]:
    """Returns asset symbols mentioned in the text (cashtag or name match)."""
    text_lower = text.lower()
    mentioned = []
    for sym, name in zip(symbols, names):
        if (f"${sym.lower()}" in text_lower
                or f" {sym.lower()} " in text_lower
                or f"({sym.lower()})" in text_lower
                or name.lower()[:6] in text_lower):
            mentioned.append(sym)
    return list(set(mentioned))


async def _fetch_subreddit(
    client: httpx.AsyncClient,
    subreddit: str,
    sort: str = "hot",
    limit: int = 50,
) -> list[dict]:
    """Fetches posts from one subreddit using the public .json endpoint."""
    url = f"{REDDIT_JSON_BASE}/r/{subreddit}/{sort}.json"
    params = {"limit": limit, "raw_json": 1}

    try:
        resp = await client.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("  Reddit r/%s: HTTP %s", subreddit, exc.response.status_code)
        return []
    except Exception as exc:
        logger.warning("  Reddit r/%s: %s", subreddit, exc)
        return []

    children = data.get("data", {}).get("children", [])
    return [c["data"] for c in children if c.get("kind") == "t3"]


async def scrape_reddit() -> list[dict]:
    """
    Fetches hot posts from all configured subreddits using the public Reddit JSON API.
    No authentication required. Returns list of post dicts.
    """
    active_assets = get_active_assets()
    symbols = [a.symbol for a in active_assets]
    names   = [a.name   for a in active_assets]

    all_posts: list[dict] = []

    async with httpx.AsyncClient(headers=HEADERS) as client:
        for sub_name in SUBREDDITS:
            raw_posts = await _fetch_subreddit(
                client, sub_name, sort="hot", limit=REDDIT_POSTS_PER_SUB
            )

            for post in raw_posts:
                title    = post.get("title", "")
                selftext = post.get("selftext", "")
                text     = f"{title} {selftext}"

                mentioned = _get_asset_mentions(text, symbols, names)

                created_utc = post.get("created_utc", 0)
                try:
                    created_iso = datetime.utcfromtimestamp(created_utc).isoformat()
                except Exception:
                    created_iso = ""

                all_posts.append({
                    "post_id":           post.get("id", ""),
                    "asset_symbol":      mentioned[0] if mentioned else "",
                    "subreddit":         sub_name,
                    "title":             title,
                    "selftext":          selftext[:2000],
                    "score":             post.get("score", 0),
                    "num_comments":      post.get("num_comments", 0),
                    "created_utc":       created_iso,
                    "_mentioned_assets": mentioned,
                    "_url":              f"https://reddit.com{post.get('permalink', '')}",
                })

            logger.info("  Reddit r/%s: %d posts", sub_name, len(raw_posts))

            # Polite delay — Reddit's public API is generous but not unlimited
            await asyncio.sleep(0.8)

    logger.info(
        "Reddit scrape complete: %d posts across %d subreddits",
        len(all_posts), len(SUBREDDITS),
    )
    return all_posts
