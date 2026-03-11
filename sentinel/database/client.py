"""
Database client — SQLite for local/trial runs, Supabase for production.
The interface is the same regardless of backend.
"""
import sqlite3
import json
import uuid
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from sentinel.config import DB_PATH, SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

_USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)


# ─────────────────────────────────────────────────────────────────────────────
# SQLite backend (local / trial)
# ─────────────────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create all tables from schema.sql if they don't exist."""
    schema_path = Path(__file__).parent / "schema.sql"
    schema = schema_path.read_text()
    with _get_conn() as conn:
        conn.executescript(schema)
    logger.info("Database initialised at %s", DB_PATH)


def _uid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# Asset registry
# ─────────────────────────────────────────────────────────────────────────────

def upsert_assets(assets: list[dict]) -> None:
    sql = """
        INSERT INTO assets (id, symbol, name, asset_class, board, sector, peers, benchmark, coingecko_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            name=excluded.name, asset_class=excluded.asset_class,
            sector=excluded.sector, peers=excluded.peers,
            benchmark=excluded.benchmark, coingecko_id=excluded.coingecko_id
    """
    rows = [
        (
            _uid(), a["symbol"], a["name"], a["asset_class"], a["board"],
            a.get("sector", ""), json.dumps(a.get("peers", [])),
            a.get("benchmark", "SPY"), a.get("coingecko_id", ""),
        )
        for a in assets
    ]
    with _get_conn() as conn:
        conn.executemany(sql, rows)


# ─────────────────────────────────────────────────────────────────────────────
# Tweets
# ─────────────────────────────────────────────────────────────────────────────

def insert_tweets(tweets: list[dict]) -> int:
    sql = """
        INSERT OR IGNORE INTO x_tweets
            (id, tweet_id, asset_symbol, tweet_text, author_handle, author_verified,
             likes, retweets, replies, views, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now = datetime.utcnow().isoformat()
    rows = [
        (
            _uid(), t.get("tweet_id", _uid()), t["asset_symbol"],
            t.get("tweet_text", ""), t.get("author_handle", ""),
            1 if t.get("author_verified") else 0,
            t.get("likes", 0), t.get("retweets", 0),
            t.get("replies", 0), str(t.get("views", "")), now,
        )
        for t in tweets
    ]
    with _get_conn() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def update_tweet_sentiment(tweet_id: str, score: float, confidence: float) -> None:
    sql = "UPDATE x_tweets SET sentiment_score=?, sentiment_confidence=? WHERE tweet_id=?"
    with _get_conn() as conn:
        conn.execute(sql, (score, confidence, tweet_id))


# ─────────────────────────────────────────────────────────────────────────────
# Reddit posts
# ─────────────────────────────────────────────────────────────────────────────

def insert_reddit_posts(posts: list[dict]) -> int:
    sql = """
        INSERT OR IGNORE INTO reddit_posts
            (id, post_id, asset_symbol, subreddit, title, selftext,
             score, num_comments, created_utc, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now = datetime.utcnow().isoformat()
    rows = [
        (
            _uid(), p["post_id"], p.get("asset_symbol", ""),
            p["subreddit"], p["title"], p.get("selftext", ""),
            p.get("score", 0), p.get("num_comments", 0),
            p.get("created_utc", ""), now,
        )
        for p in posts
    ]
    with _get_conn() as conn:
        conn.executemany(sql, rows)
    return len(rows)


# ─────────────────────────────────────────────────────────────────────────────
# News articles
# ─────────────────────────────────────────────────────────────────────────────

def insert_news_articles(articles: list[dict]) -> int:
    sql = """
        INSERT OR IGNORE INTO news_articles
            (id, source, source_tier, title, summary, full_text, url,
             asset_symbols, published_at, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now = datetime.utcnow().isoformat()
    rows = [
        (
            _uid(), a["source"], a.get("source_tier", 0.5),
            a.get("title", ""), a.get("summary", ""),
            a.get("full_text", ""), a.get("url", _uid()),
            json.dumps(a.get("asset_symbols", [])),
            a.get("published_at", ""), now,
        )
        for a in articles
    ]
    with _get_conn() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def update_article_sentiment(url: str, score: float, confidence: float) -> None:
    sql = "UPDATE news_articles SET sentiment_score=?, sentiment_confidence=? WHERE url=?"
    with _get_conn() as conn:
        conn.execute(sql, (score, confidence, url))


def get_articles_without_full_text(limit: int = 50) -> list[dict]:
    sql = """
        SELECT id, url, title, summary FROM news_articles
        WHERE (full_text IS NULL OR full_text = '')
          AND url NOT LIKE '%sec.gov%'
          AND url NOT LIKE '%cftc.gov%'
        ORDER BY ingested_at DESC
        LIMIT ?
    """
    with _get_conn() as conn:
        rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(r) for r in rows]


def update_article_full_text(url: str, full_text: str) -> None:
    sql = "UPDATE news_articles SET full_text=? WHERE url=?"
    with _get_conn() as conn:
        conn.execute(sql, (full_text, url))


# ─────────────────────────────────────────────────────────────────────────────
# Market data
# ─────────────────────────────────────────────────────────────────────────────

def upsert_market_data(rows: list[dict]) -> int:
    sql = """
        INSERT INTO market_data
            (id, symbol, date, open, high, low, close, volume, market_cap,
             rsi_14, macd_signal, bollinger_position, volatility_30d,
             avg_volume_20d, volume_zscore)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, date) DO UPDATE SET
            close=excluded.close, volume=excluded.volume,
            market_cap=excluded.market_cap, rsi_14=excluded.rsi_14,
            macd_signal=excluded.macd_signal, volatility_30d=excluded.volatility_30d,
            avg_volume_20d=excluded.avg_volume_20d, volume_zscore=excluded.volume_zscore
    """
    data = [
        (
            _uid(), r["symbol"], r["date"],
            r.get("open"), r.get("high"), r.get("low"), r.get("close"),
            r.get("volume"), r.get("market_cap"),
            r.get("rsi_14"), r.get("macd_signal"), r.get("bollinger_position"),
            r.get("volatility_30d"), r.get("avg_volume_20d"), r.get("volume_zscore"),
        )
        for r in rows
    ]
    with _get_conn() as conn:
        conn.executemany(sql, data)
    return len(data)


def get_price_history(symbol: str, days: int = 30) -> list[dict]:
    sql = """
        SELECT * FROM market_data
        WHERE symbol=?
        ORDER BY date DESC
        LIMIT ?
    """
    with _get_conn() as conn:
        rows = conn.execute(sql, (symbol, days)).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Daily signals
# ─────────────────────────────────────────────────────────────────────────────

def upsert_daily_signals(signals: list[dict]) -> int:
    cols = [
        "news_sentiment", "social_sentiment", "sentiment_shift",
        "volume_anomaly", "momentum_score", "correlation_divergence",
        "risk_adjusted_liquidity", "regulatory_signal", "competitor_edge",
        "geopolitical_flow", "catalyst_freshness",
        "raw_score", "confidence", "investability", "final_score", "rank",
    ]
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in cols)
    sql = f"""
        INSERT INTO daily_signals (id, symbol, date, {', '.join(cols)})
        VALUES (?, ?, ?, {', '.join('?' * len(cols))})
        ON CONFLICT(symbol, date) DO UPDATE SET {set_clause}
    """
    rows = [
        (
            _uid(), s["symbol"], s["date"],
            *[s.get(c) for c in cols],
        )
        for s in signals
    ]
    with _get_conn() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def get_signals_for_date(target_date: str) -> list[dict]:
    sql = "SELECT * FROM daily_signals WHERE date=? ORDER BY rank ASC"
    with _get_conn() as conn:
        rows = conn.execute(sql, (target_date,)).fetchall()
    return [dict(r) for r in rows]


def get_top10_for_date(target_date: str) -> list[dict]:
    sql = """
        SELECT * FROM daily_signals
        WHERE date=? AND rank IS NOT NULL
        ORDER BY rank ASC
        LIMIT 10
    """
    with _get_conn() as conn:
        rows = conn.execute(sql, (target_date,)).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Backtesting log
# ─────────────────────────────────────────────────────────────────────────────

def insert_backtest_results(results: list[dict]) -> int:
    sql = """
        INSERT OR REPLACE INTO backtesting_log
            (id, symbol, signal_date, rank_on_signal_date, final_score_on_signal_date,
             top_signals, return_1d, return_5d, return_20d, hit_1d, hit_5d,
             max_drawdown_5d, evaluated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    now = datetime.utcnow().isoformat()
    rows = [
        (
            _uid(), r["symbol"], r["signal_date"],
            r.get("rank"), r.get("final_score"),
            json.dumps(r.get("top_signals", {})),
            r.get("return_1d"), r.get("return_5d"), r.get("return_20d"),
            1 if r.get("hit_1d") else 0,
            1 if r.get("hit_5d") else 0,
            r.get("max_drawdown_5d"), now,
        )
        for r in results
    ]
    with _get_conn() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def get_signal_hit_rates(days: int = 30) -> dict[str, float]:
    """Returns hit rate per signal type over last N days."""
    sql = """
        SELECT
            AVG(hit_5d) as overall_hit_rate,
            COUNT(*) as total_predictions
        FROM backtesting_log
        WHERE signal_date >= date('now', ?)
    """
    with _get_conn() as conn:
        row = conn.execute(sql, (f"-{days} days",)).fetchone()
    if row and row["total_predictions"] > 0:
        return {"overall": row["overall_hit_rate"] or 0.0, "count": row["total_predictions"]}
    return {"overall": 0.0, "count": 0}


def get_recent_scorecard(days: int = 7) -> list[dict]:
    sql = """
        SELECT b.symbol, b.signal_date, b.rank_on_signal_date,
               b.final_score_on_signal_date, b.return_1d, b.return_5d, b.hit_5d
        FROM backtesting_log b
        WHERE b.signal_date >= date('now', ?)
          AND b.rank_on_signal_date <= 10
        ORDER BY b.signal_date DESC, b.rank_on_signal_date ASC
    """
    with _get_conn() as conn:
        rows = conn.execute(sql, (f"-{days} days",)).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Signal weights
# ─────────────────────────────────────────────────────────────────────────────

def upsert_signal_weights(weights: list[dict]) -> None:
    sql = """
        INSERT INTO signal_weights
            (id, date, asset_class, signal_name, base_weight, adjusted_weight, hit_rate_30d, precision_30d)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, asset_class, signal_name) DO UPDATE SET
            adjusted_weight=excluded.adjusted_weight,
            hit_rate_30d=excluded.hit_rate_30d
    """
    rows = [
        (
            _uid(), w["date"], w["asset_class"], w["signal_name"],
            w.get("base_weight", 0), w.get("adjusted_weight", 0),
            w.get("hit_rate_30d", 0), w.get("precision_30d", 0),
        )
        for w in weights
    ]
    with _get_conn() as conn:
        conn.executemany(sql, rows)


def get_latest_weights(asset_class: str) -> dict[str, float]:
    """Returns most recent adjusted weights for an asset class, or base weights."""
    sql = """
        SELECT signal_name, adjusted_weight FROM signal_weights
        WHERE asset_class=?
        ORDER BY date DESC
        LIMIT 11
    """
    from sentinel.config import BASE_WEIGHTS
    with _get_conn() as conn:
        rows = conn.execute(sql, (asset_class,)).fetchall()
    if rows:
        return {r["signal_name"]: r["adjusted_weight"] for r in rows}
    return BASE_WEIGHTS.copy()
