"""
Reddit scraper — 3-tier cascade per subreddit (no OAuth required).

Tier 1 (primary):  ArcticShift API → arctic-shift.photon-reddit.com (free, no auth, scores)
Tier 2 (fallback): RSS feeds       → www.reddit.com/.rss (no auth, no score/comments)
Tier 3 (fallback): PullPush API    → api.pullpush.io (free, no auth, archival)
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
import feedparser

from sentinel.config import (
    SUBREDDITS, REDDIT_POSTS_PER_SUB, get_active_assets, get_match_keywords,
    REDDIT_USER_AGENT, ARCTICSHIFT_BASE,
)

logger = logging.getLogger(__name__)

PULLPUSH_BASE = "https://api.pullpush.io/reddit"

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    """Strip HTML tags to get plain text."""
    return _HTML_TAG_RE.sub(" ", html).strip()


def _match_assets(text: str, assets) -> list[str]:
    """Returns asset symbols mentioned in the text using keyword matching."""
    text_lower = text.lower()
    mentioned = []
    for asset in assets:
        keywords = get_match_keywords(asset)
        if any(kw in text_lower for kw in keywords):
            mentioned.append(asset.symbol)
    return list(set(mentioned))


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1: ArcticShift API (free, no auth, ~500 RPM, archived with scores)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_subreddit_arcticshift(
    client: httpx.AsyncClient,
    subreddit: str,
    limit: int = 50,
) -> list[dict]:
    """Fetches recent posts from one subreddit via ArcticShift archive API."""
    url = f"{ARCTICSHIFT_BASE}/posts/search"
    params = {
        "subreddit": subreddit,
        "limit": limit,
        "sort": "desc",
        "sort_type": "created_utc",
    }

    try:
        resp = await client.get(
            url, params=params, timeout=20,
            headers={"User-Agent": REDDIT_USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("  ArcticShift r/%s: %s", subreddit, exc)
        return []

    items = data.get("data", [])
    posts = []
    for item in items:
        created_utc = item.get("created_utc", 0)
        try:
            created_iso = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
        except Exception:
            created_iso = ""
        posts.append({
            "title": item.get("title", ""),
            "selftext": (item.get("selftext") or "")[:2000],
            "id": item.get("id", ""),
            "score": item.get("score", 0),
            "num_comments": item.get("num_comments", 0),
            "created_iso": created_iso,
            "permalink": item.get("permalink", f"/r/{subreddit}/comments/{item.get('id', '')}/"),
        })
    return posts


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2: RSS feeds (no auth, no score/comments)
# ─────────────────────────────────────────────────────────────────────────────

RSS_BASE = "https://www.reddit.com"
HEADERS_RSS = {"User-Agent": "Mozilla/5.0 (compatible; Sentinel/1.0)"}


async def _fetch_subreddit_rss(
    client: httpx.AsyncClient,
    subreddit: str,
    limit: int = 50,
) -> list[dict]:
    """Fetches posts from one subreddit via RSS feed."""
    url = f"{RSS_BASE}/r/{subreddit}/hot/.rss"
    params = {"limit": limit}

    try:
        resp = await client.get(
            url, params=params, headers=HEADERS_RSS, timeout=15, follow_redirects=True,
        )
        if not resp.is_success:
            logger.warning("  Reddit RSS r/%s: HTTP %d", subreddit, resp.status_code)
            return []
        feed = feedparser.parse(resp.text)
    except Exception as exc:
        logger.warning("  Reddit RSS r/%s: %s", subreddit, exc)
        return []

    posts = []
    for entry in feed.entries:
        title = getattr(entry, "title", "")
        content_html = ""
        if hasattr(entry, "content") and entry.content:
            content_html = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            content_html = entry.summary or ""
        selftext = _strip_html(content_html)[:2000]

        link = getattr(entry, "link", "")

        created_iso = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                created_iso = datetime(*entry.published_parsed[:6]).isoformat()
            except Exception:
                pass

        posts.append({
            "title": title,
            "selftext": selftext,
            "id": link.split("/comments/")[1].split("/")[0] if "/comments/" in link else "",
            "score": 0,
            "num_comments": 0,
            "created_iso": created_iso,
            "permalink": link.replace("https://www.reddit.com", ""),
        })

    return posts


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3: PullPush API (free, no auth, archival — last resort)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_subreddit_pullpush(
    client: httpx.AsyncClient,
    subreddit: str,
    limit: int = 50,
) -> list[dict]:
    """Fetches recent posts from one subreddit via PullPush archive API."""
    url = f"{PULLPUSH_BASE}/search/submission/"
    params = {
        "subreddit": subreddit,
        "size": limit,
        "sort": "desc",
        "sort_type": "created_utc",
    }

    try:
        resp = await client.get(
            url, params=params, timeout=20,
            headers={"User-Agent": REDDIT_USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("  PullPush r/%s: %s", subreddit, exc)
        return []

    items = data.get("data", [])
    posts = []
    for item in items:
        created_utc = item.get("created_utc", 0)
        try:
            created_iso = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
        except Exception:
            created_iso = ""
        posts.append({
            "title": item.get("title", ""),
            "selftext": (item.get("selftext") or "")[:2000],
            "id": item.get("id", ""),
            "score": item.get("score", 0),
            "num_comments": item.get("num_comments", 0),
            "created_iso": created_iso,
            "permalink": item.get("permalink", f"/r/{subreddit}/comments/{item.get('id', '')}/"),
        })
    return posts


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point — 3-tier cascade per subreddit
# ─────────────────────────────────────────────────────────────────────────────

# Pacing between requests per tier (seconds)
_PACE_ARCTICSHIFT = 0.2  # ~500 RPM, generous
_PACE_RSS = 2.0          # ~10 RPM, conservative
_PACE_PULLPUSH = 0.5     # ~500 RPM nominal, but be gentle


async def scrape_reddit() -> list[dict]:
    """
    Fetches hot posts from all configured subreddits.
    Cascade: ArcticShift → RSS → PullPush (per subreddit).
    """
    active_assets = get_active_assets()
    all_posts: list[dict] = []

    async with httpx.AsyncClient() as client:
        for sub_name in SUBREDDITS:
            raw_posts: list[dict] = []
            source = "NONE"

            # ── Tier 1: ArcticShift (primary) ──────────────────────────────
            raw_posts = await _fetch_subreddit_arcticshift(client, sub_name, REDDIT_POSTS_PER_SUB)
            if raw_posts:
                source = "ArcticShift"
            else:
                await asyncio.sleep(_PACE_ARCTICSHIFT)

                # ── Tier 2: RSS ────────────────────────────────────────────
                raw_posts = await _fetch_subreddit_rss(client, sub_name, REDDIT_POSTS_PER_SUB)
                if raw_posts:
                    source = "RSS"
                else:
                    await asyncio.sleep(_PACE_RSS)

                    # ── Tier 3: PullPush (last resort) ─────────────────────
                    raw_posts = await _fetch_subreddit_pullpush(client, sub_name, REDDIT_POSTS_PER_SUB)
                    if raw_posts:
                        source = "PullPush"

            # ── Asset matching & normalisation ─────────────────────────────
            for post in raw_posts:
                title = post.get("title", "")
                selftext = post.get("selftext", "")
                text = f"{title} {selftext}"

                mentioned = _match_assets(text, active_assets)

                all_posts.append({
                    "post_id":           post.get("id", ""),
                    "asset_symbol":      mentioned[0] if mentioned else "",
                    "subreddit":         sub_name,
                    "title":             title,
                    "selftext":          selftext,
                    "score":             post.get("score", 0),
                    "num_comments":      post.get("num_comments", 0),
                    "created_utc":       post.get("created_iso", ""),
                    "_mentioned_assets": mentioned,
                    "_url":              f"https://reddit.com{post.get('permalink', '')}",
                })

            logger.info("  Reddit r/%s (%s): %d posts", sub_name, source, len(raw_posts))

            # Pace based on which tier succeeded
            if source == "ArcticShift":
                await asyncio.sleep(_PACE_ARCTICSHIFT)
            elif source == "RSS":
                await asyncio.sleep(_PACE_RSS)
            elif source == "PullPush":
                await asyncio.sleep(_PACE_PULLPUSH)

    logger.info(
        "Reddit scrape complete: %d posts across %d subreddits",
        len(all_posts), len(SUBREDDITS),
    )
    return all_posts
