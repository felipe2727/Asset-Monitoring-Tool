"""
Sentinel — Daily Asset Intelligence Pipeline
============================================
Run with:  python main.py

Controls:
  RUN_NUMBER=1|2|3|4   ->Selects Scrapingdog key rotation (see FREE-TRIAL-RUN-PLAN.md)
  FREE_TRIAL_MODE=true  ->15 assets, 10 tweets each (default)
  FREE_TRIAL_MODE=false → Full 50 assets, 20 tweets each (production)

The pipeline:
  1.  Scrape X/Twitter via Scrapingdog
  2.  Scrape Reddit via PRAW
  3.  Fetch RSS feeds
  4.  Pull market data (yfinance, CoinGecko)
  5.  Fetch full article text (Firecrawl)
  6.  Run LLM sentiment (OpenAI GPT-4o-mini)
  7.  Compute 11 signals per asset
  8.  Composite scoring + ranking
  9.  Evaluate yesterday's picks (backtest)
  10. Update dynamic signal weights
  11. Generate HTML email
  12. Send via Resend (or save to file)
  13. Log everything to SQLite
"""
import asyncio
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn

# ─── Setup logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        RichHandler(rich_tracebacks=True, show_path=False),
        logging.FileHandler(
            Path(__file__).parent / "logs" / f"sentinel_{date.today().isoformat()}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("sentinel")
console = Console()


async def run_pipeline() -> None:
    """Main pipeline coroutine."""
    start_time = time.time()
    today = date.today().isoformat()

    console.rule(f"[bold blue]SENTINEL DAILY RADAR — {today}[/bold blue]")

    # ── Import all modules (deferred to avoid slow startup) ──────────────────
    from sentinel.config import FREE_TRIAL_MODE, RUN_NUMBER, SUBREDDITS, get_active_assets
    from sentinel.database.client import init_db, upsert_assets, upsert_market_data, insert_tweets, insert_reddit_posts, insert_news_articles, upsert_daily_signals
    from sentinel.ingestion.twitter import scrape_twitter
    from sentinel.ingestion.reddit import scrape_reddit
    from sentinel.ingestion.rss_feeds import fetch_rss_feeds
    from sentinel.ingestion.firecrawl import fetch_full_text
    from sentinel.ingestion.market_data import fetch_market_data, fetch_macro_context
    from sentinel.ingestion.gdelt import fetch_gdelt_events
    from sentinel.analysis.sentiment import analyze_tweets, analyze_reddit_posts, analyze_articles
    from sentinel.analysis.signals import compute_all_signals
    from sentinel.scoring.engine import compute_scores, get_top10
    from sentinel.backtesting.scorecard import evaluate_yesterday, update_dynamic_weights, build_scorecard_summary
    from sentinel.output.renderer import render_email
    from sentinel.output.sender import send_email

    assets = get_active_assets()
    mode_label = f"FREE TRIAL (Run #{RUN_NUMBER}, {len(assets)} assets)" if FREE_TRIAL_MODE else f"PRODUCTION ({len(assets)} assets)"
    logger.info("Mode: %s", mode_label)

    # ── Step 0: Initialise database ──────────────────────────────────────────
    logger.info("[0/12] Initialising database...")
    init_db()
    upsert_assets([
        {
            "symbol": a.symbol, "name": a.name, "asset_class": a.asset_class,
            "board": a.board, "sector": a.sector, "peers": a.peers,
            "benchmark": a.benchmark, "coingecko_id": a.coingecko_id,
        }
        for a in assets
    ])

    # ── Step 1: Scrape X/Twitter ─────────────────────────────────────────────
    logger.info("[1/12] Scraping X/Twitter (ScrapeBadger → Scrapingdog → StockTwits)...")
    try:
        tweets = await scrape_twitter()
        insert_tweets(tweets)
        logger.info("  -> %d tweets stored", len(tweets))
    except Exception as exc:
        logger.error("Twitter scrape failed: %s", exc)
        tweets = []

    # ── Step 2: Scrape Reddit ────────────────────────────────────────────────
    logger.info("[2/12] Scraping Reddit (ArcticShift → RSS → PullPush)...")
    try:
        reddit_posts = await scrape_reddit()
        insert_reddit_posts(reddit_posts)
        logger.info("  -> %d Reddit posts stored", len(reddit_posts))
    except Exception as exc:
        logger.error("Reddit scrape failed: %s", exc)
        reddit_posts = []

    # ── Step 3: Fetch RSS feeds ──────────────────────────────────────────────
    logger.info("[3/12] Fetching RSS feeds...")
    try:
        articles = await fetch_rss_feeds()
        insert_news_articles(articles)
        logger.info("  ->%d articles stored", len(articles))
    except Exception as exc:
        logger.error("RSS fetch failed: %s", exc)
        articles = []

    # ── Step 4: Fetch market data ────────────────────────────────────────────
    logger.info("[4/12] Fetching market data (Finnhub + Alpha Vantage + CoinGecko)...")
    try:
        market_data = await fetch_market_data()
        macro_context = await fetch_macro_context()
        market_rows = list(market_data.values())
        upsert_market_data(market_rows)
        logger.info("  ->%d symbols with market data", len(market_data))
    except Exception as exc:
        logger.error("Market data fetch failed: %s", exc)
        market_data = {}
        macro_context = {}

    # ── Step 5: Fetch GDELT geopolitical events ──────────────────────────────
    logger.info("[5/12] Fetching GDELT geopolitical events...")
    try:
        gdelt_events = await fetch_gdelt_events()
        logger.info("  ->%d GDELT events", len(gdelt_events))
    except Exception as exc:
        logger.warning("GDELT fetch failed: %s", exc)
        gdelt_events = []

    # ── Step 6: Fetch full article text (Firecrawl) ──────────────────────────
    logger.info("[6/12] Fetching full article text via Firecrawl...")
    try:
        articles = await fetch_full_text(articles)
        full_text_count = sum(1 for a in articles if a.get("full_text"))
        logger.info("  ->%d/%d articles with full text", full_text_count, len(articles))
    except Exception as exc:
        logger.error("Firecrawl failed: %s", exc)

    # ── Step 6.5: Data quality manifest ───────────────────────────────────
    manifest = {
        "tweets": len(tweets),
        "reddit_posts": len(reddit_posts),
        "articles": len(articles),
        "market_symbols": len(market_data),
        "gdelt_events": len(gdelt_events),
    }
    logger.info("Data manifest: %s", manifest)

    expected = {"tweets": len(assets) * 10, "reddit_posts": len(SUBREDDITS) * 50,
                "articles": 100, "market_symbols": len(assets), "gdelt_events": 1}
    for key, actual in manifest.items():
        exp = expected.get(key, 1)
        if exp > 0 and actual < exp * 0.1:
            logger.warning("  LOW DATA: %s = %d (expected ~%d)", key, actual, exp)

    # ── Step 7: LLM Sentiment Analysis ──────────────────────────────────────
    logger.info("[7/12] Running LLM sentiment analysis (GPT-4o-mini)...")
    try:
        if tweets:
            tweets = await analyze_tweets(tweets)
        else:
            logger.info("  Skipping tweet sentiment (0 tweets)")
        if reddit_posts:
            reddit_posts = await analyze_reddit_posts(reddit_posts)
        else:
            logger.info("  Skipping Reddit sentiment (0 posts)")
        if articles:
            articles = await analyze_articles(articles)
        else:
            logger.info("  Skipping article sentiment (0 articles)")

        total_items = len(tweets) + len(reddit_posts) + len(articles)
        scored_count = sum(1 for t in tweets + reddit_posts + articles
                          if t.get("sentiment_confidence", 0) > 0.3)
        logger.info("  ->%d/%d items scored with confidence >0.3", scored_count, total_items)
    except Exception as exc:
        logger.error("Sentiment analysis failed: %s", exc)

    # ── Step 8: Compute all 11 signals per asset ─────────────────────────────
    logger.info("[8/12] Computing signals for %d assets...", len(assets))
    signal_rows: list[dict] = []
    for asset in assets:
        try:
            row = compute_all_signals(
                symbol      = asset.symbol,
                asset_class = asset.asset_class,
                benchmark   = asset.benchmark,
                peers       = asset.peers,
                tweets      = tweets,
                reddit_posts = reddit_posts,
                articles    = articles,
                market_data = market_data,
                gdelt_events = gdelt_events,
            )
            signal_rows.append(row)
        except Exception as exc:
            logger.error("  Signal computation failed for %s: %s", asset.symbol, exc)

    logger.info("  ->%d assets with signals computed", len(signal_rows))

    # ── Step 9: Composite scoring + ranking ──────────────────────────────────
    logger.info("[9/12] Scoring and ranking...")
    try:
        scored = compute_scores(signal_rows, market_data, articles)
        top10  = get_top10(scored)

        if top10:
            logger.info("  TOP 3: %s",
                        ", ".join(f"{s['symbol']} ({s['final_score']:.1f})" for s in top10[:3]))

        # Persist signals to DB
        db_signal_rows = [
            {k: v for k, v in row.items() if not k.startswith("_")}
            for row in scored
        ]
        upsert_daily_signals(db_signal_rows)
    except Exception as exc:
        logger.error("Scoring failed: %s", exc)
        top10 = []

    # ── Step 10: Backtest yesterday's predictions ─────────────────────────────
    logger.info("[10/12] Evaluating yesterday's predictions...")
    try:
        yesterday_results = evaluate_yesterday()
        if yesterday_results:
            hits = sum(1 for r in yesterday_results if r.get("hit_1d"))
            logger.info("  ->Yesterday: %d/%d hits", hits, len(yesterday_results))
    except Exception as exc:
        logger.warning("Backtest failed: %s", exc)

    # ── Step 11: Update dynamic signal weights ────────────────────────────────
    logger.info("[11/12] Updating signal weights...")
    try:
        update_dynamic_weights()
    except Exception as exc:
        logger.warning("Weight update failed: %s", exc)

    # ── Step 12: Generate and send email ─────────────────────────────────────
    logger.info("[12/12] Generating and sending email digest...")
    try:
        scorecard = build_scorecard_summary()
        html = render_email(
            top10         = top10,
            scorecard     = scorecard,
            articles      = articles,
            tweets        = tweets,
            macro_context = macro_context,
        )
        send_email(html)
    except Exception as exc:
        logger.error("Email generation/send failed: %s", exc)

    # ── Done ──────────────────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    console.rule(f"[bold green]Pipeline complete in {elapsed:.0f}s[/bold green]")
    logger.info(
        "Run #%s complete | Assets: %d | Tweets: %d | Articles: %d | Top asset: %s (%.1f)",
        RUN_NUMBER, len(assets), len(tweets), len(articles),
        top10[0]["symbol"] if top10 else "N/A",
        top10[0]["final_score"] if top10 else 0,
    )


def main() -> None:
    """Entry point."""
    try:
        asyncio.run(run_pipeline())
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Fatal pipeline error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
