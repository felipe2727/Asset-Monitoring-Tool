"""
Firecrawl full-text article extractor.
Converts RSS-linked article URLs into clean markdown for LLM sentiment analysis.
Credits: 1 per page. Trial budget: 50 articles/run (far under 500 free limit).
"""
import asyncio
import logging
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel.config import FIRECRAWL_API_KEY, FIRECRAWL_MAX_ARTICLES

logger = logging.getLogger(__name__)


def _get_firecrawl_app():
    """Lazily initialise the Firecrawl client."""
    try:
        from firecrawl import FirecrawlApp
        return FirecrawlApp(api_key=FIRECRAWL_API_KEY)
    except ImportError:
        logger.error("firecrawl-py not installed. Run: pip install firecrawl-py")
        return None
    except Exception as exc:
        logger.error("Firecrawl init error: %s", exc)
        return None


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
def _scrape_url(app, url: str) -> Optional[str]:
    """Scrapes one URL, returns markdown text or None."""
    try:
        result = app.scrape_url(url, params={"formats": ["markdown"]})
        if isinstance(result, dict):
            return result.get("markdown") or result.get("content") or result.get("text")
        return str(result) if result else None
    except Exception as exc:
        logger.warning("  Firecrawl %s: %s", url[:60], exc)
        return None


async def fetch_full_text(articles: list[dict]) -> list[dict]:
    """
    Fetches full text for articles that only have headlines/summaries.
    Updates each article dict with 'full_text' key.
    Returns the updated articles list.
    """
    if not FIRECRAWL_API_KEY:
        logger.warning("FIRECRAWL_API_KEY not set — skipping full-text extraction.")
        return articles

    app = _get_firecrawl_app()
    if not app:
        return articles

    # Only fetch articles that don't already have full text
    to_fetch = [a for a in articles if not a.get("full_text")][:FIRECRAWL_MAX_ARTICLES]

    if not to_fetch:
        logger.info("Firecrawl: no articles need full-text extraction")
        return articles

    # Firecrawl SDK is sync — run in thread pool to not block async pipeline
    loop = asyncio.get_event_loop()

    fetched = 0
    for article in to_fetch:
        url = article.get("url", "")
        if not url:
            continue

        full_text = await loop.run_in_executor(None, _scrape_url, app, url)
        if full_text:
            article["full_text"] = full_text[:5000]  # cap to save tokens
            fetched += 1
        else:
            article["full_text"] = article.get("summary", "")

        # Small delay to respect rate limits
        await asyncio.sleep(0.3)

    logger.info("Firecrawl complete: %d/%d articles extracted", fetched, len(to_fetch))
    return articles
