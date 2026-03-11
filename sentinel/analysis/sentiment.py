"""
LLM sentiment analysis using OpenAI GPT-4o-mini.
Processes tweets, Reddit posts, and news articles in batches.
Returns structured {sentiment: float, confidence: float, entities: [], topics: [], is_regulatory: bool}
"""
import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel.config import OPENAI_API_KEY, OPENAI_MODEL, SENTIMENT_BATCH_SIZE

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

SENTIMENT_SYSTEM_PROMPT = """You are a financial analyst AI. Analyze text about financial assets and return ONLY valid JSON.

Return this exact structure:
{
  "sentiment": <float -1.0 (extremely bearish) to 1.0 (extremely bullish)>,
  "confidence": <float 0.0 to 1.0>,
  "entities": [<ticker symbols or asset names mentioned>],
  "topics": [<from: earnings, regulation, merger, layoffs, product_launch, macro, conflict, technical, other>],
  "is_regulatory": <boolean>,
  "regulatory_direction": <"positive", "negative", "neutral", or null>
}

Rules:
- 0.0 = perfectly neutral
- Consider FINANCIAL implications, not just tone
- "Revenue missed estimates" = bearish even if tone sounds calm
- "SEC approves ETF" = strongly positive for that asset class
- Social media hype without substance = low confidence, neutral to mildly positive
- If uncertain, use 0.0 with low confidence (0.2-0.4)
- Do NOT wrap JSON in markdown code blocks"""


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set in .env")
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
async def _analyze_batch(texts: list[str]) -> list[dict]:
    """Sends a batch of texts to GPT-4o-mini and returns parsed results."""
    client = _get_client()

    # Format multiple texts as numbered list for efficiency
    combined = "\n\n---\n\n".join(
        f"[{i+1}] {text[:800]}" for i, text in enumerate(texts)
    )
    user_prompt = (
        f"Analyze these {len(texts)} financial texts. Return a JSON array with one object per text, "
        f"in the same order:\n\n{combined}"
    )

    resp = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=1500,
    )

    raw = resp.choices[0].message.content or "{}"
    parsed = json.loads(raw)

    # Handle both {"results": [...]} and direct array responses
    if isinstance(parsed, list):
        results = parsed
    elif "results" in parsed:
        results = parsed["results"]
    elif len(texts) == 1:
        # Single item returned as object
        results = [parsed]
    else:
        # Fallback: try to extract array from any key
        for v in parsed.values():
            if isinstance(v, list):
                results = v
                break
        else:
            results = [{"sentiment": 0.0, "confidence": 0.3} for _ in texts]

    # Ensure we have the right number of results
    while len(results) < len(texts):
        results.append({"sentiment": 0.0, "confidence": 0.3})

    return results[:len(texts)]


def _default_result() -> dict:
    return {"sentiment": 0.0, "confidence": 0.0, "entities": [], "topics": [], "is_regulatory": False}


async def run_sentiment_analysis(items: list[dict]) -> list[dict]:
    """
    Runs sentiment analysis on a list of items.
    Each item must have 'text' key. Returns items with 'sentiment_score' and
    'sentiment_confidence' added.

    Args:
        items: list of dicts with at minimum {'text': str, 'id': str}

    Returns:
        Same list with sentiment_score, sentiment_confidence, and _sentiment_meta added.
    """
    if not items:
        return items

    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — skipping sentiment analysis.")
        for item in items:
            item["sentiment_score"]      = 0.0
            item["sentiment_confidence"] = 0.0
        return items

    texts = [item.get("text", "") for item in items]

    # Process in batches to stay within token limits and rate limits
    all_results: list[dict] = []
    for i in range(0, len(texts), SENTIMENT_BATCH_SIZE):
        batch = texts[i : i + SENTIMENT_BATCH_SIZE]
        try:
            batch_results = await _analyze_batch(batch)
            all_results.extend(batch_results)
            logger.debug("Sentiment batch %d/%d: %d items", i // SENTIMENT_BATCH_SIZE + 1,
                         (len(texts) - 1) // SENTIMENT_BATCH_SIZE + 1, len(batch))
        except Exception as exc:
            logger.error("Sentiment batch error: %s", exc)
            all_results.extend([_default_result()] * len(batch))

        # Rate limit: ~20 req/min on free tier
        if i + SENTIMENT_BATCH_SIZE < len(texts):
            await asyncio.sleep(1.0)

    # Merge results back into items
    for item, result in zip(items, all_results):
        item["sentiment_score"]      = float(result.get("sentiment", 0.0))
        item["sentiment_confidence"] = float(result.get("confidence", 0.0))
        item["_sentiment_meta"]      = result

    scored = sum(1 for r in all_results if r.get("confidence", 0) > 0.3)
    logger.info("Sentiment complete: %d/%d items scored with confidence >0.3", scored, len(items))
    return items


async def analyze_tweets(tweets: list[dict]) -> list[dict]:
    """Scores tweet sentiment. Returns tweets with sentiment fields."""
    for t in tweets:
        t["text"] = t.get("tweet_text", "")
    return await run_sentiment_analysis(tweets)


async def analyze_reddit_posts(posts: list[dict]) -> list[dict]:
    """Scores Reddit post sentiment."""
    for p in posts:
        p["text"] = f"{p.get('title', '')} {p.get('selftext', '')}"[:1000]
    return await run_sentiment_analysis(posts)


async def analyze_articles(articles: list[dict]) -> list[dict]:
    """Scores news article sentiment (prefers full_text over summary)."""
    for a in articles:
        a["text"] = (a.get("full_text") or a.get("summary") or a.get("title", ""))[:1200]
    return await run_sentiment_analysis(articles)
