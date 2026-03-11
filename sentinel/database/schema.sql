-- Sentinel database schema
-- Works with both SQLite (local trial) and Supabase/Postgres (production)

CREATE TABLE IF NOT EXISTS assets (
    id          TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    board       TEXT NOT NULL DEFAULT 'public',
    sector      TEXT,
    peers       TEXT,           -- JSON array
    benchmark   TEXT,
    coingecko_id TEXT,
    active      INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS x_tweets (
    id                  TEXT PRIMARY KEY,
    tweet_id            TEXT UNIQUE,
    asset_symbol        TEXT,
    tweet_text          TEXT,
    author_handle       TEXT,
    author_verified     INTEGER DEFAULT 0,
    likes               INTEGER DEFAULT 0,
    retweets            INTEGER DEFAULT 0,
    replies             INTEGER DEFAULT 0,
    views               TEXT,
    sentiment_score     REAL,
    sentiment_confidence REAL,
    scraped_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reddit_posts (
    id                   TEXT PRIMARY KEY,
    post_id              TEXT UNIQUE,
    asset_symbol         TEXT,
    subreddit            TEXT,
    title                TEXT,
    selftext             TEXT,
    score                INTEGER DEFAULT 0,
    num_comments         INTEGER DEFAULT 0,
    sentiment_score      REAL,
    sentiment_confidence REAL,
    created_utc          TEXT,
    scraped_at           TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS news_articles (
    id                   TEXT PRIMARY KEY,
    source               TEXT NOT NULL,
    source_tier          REAL DEFAULT 0.5,
    title                TEXT,
    summary              TEXT,
    full_text            TEXT,
    url                  TEXT UNIQUE,
    asset_symbols        TEXT,       -- JSON array
    sentiment_score      REAL,
    sentiment_confidence REAL,
    published_at         TEXT,
    ingested_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS market_data (
    id                TEXT PRIMARY KEY,
    symbol            TEXT NOT NULL,
    date              TEXT NOT NULL,
    open              REAL,
    high              REAL,
    low               REAL,
    close             REAL,
    volume            INTEGER,
    market_cap        REAL,
    rsi_14            REAL,
    macd_signal       REAL,
    bollinger_position REAL,
    volatility_30d    REAL,
    avg_volume_20d    REAL,
    volume_zscore     REAL,
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS daily_signals (
    id                       TEXT PRIMARY KEY,
    symbol                   TEXT NOT NULL,
    date                     TEXT NOT NULL,
    news_sentiment           REAL DEFAULT 0,
    social_sentiment         REAL DEFAULT 0,
    sentiment_shift          REAL DEFAULT 0,
    volume_anomaly           REAL DEFAULT 0,
    momentum_score           REAL DEFAULT 0,
    correlation_divergence   REAL DEFAULT 0,
    risk_adjusted_liquidity  REAL DEFAULT 50,
    regulatory_signal        REAL DEFAULT 0,
    competitor_edge          REAL DEFAULT 0,
    geopolitical_flow        REAL DEFAULT 0,
    catalyst_freshness       REAL DEFAULT 0,
    raw_score                REAL,
    confidence               REAL,
    investability            REAL,
    final_score              REAL,
    rank                     INTEGER,
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS backtesting_log (
    id                         TEXT PRIMARY KEY,
    symbol                     TEXT NOT NULL,
    signal_date                TEXT NOT NULL,
    rank_on_signal_date        INTEGER,
    final_score_on_signal_date REAL,
    top_signals                TEXT,       -- JSON
    return_1d                  REAL,
    return_5d                  REAL,
    return_20d                 REAL,
    hit_1d                     INTEGER,
    hit_5d                     INTEGER,
    max_drawdown_5d            REAL,
    evaluated_at               TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS signal_weights (
    id              TEXT PRIMARY KEY,
    date            TEXT NOT NULL,
    asset_class     TEXT NOT NULL,
    signal_name     TEXT NOT NULL,
    base_weight     REAL,
    adjusted_weight REAL,
    hit_rate_30d    REAL,
    precision_30d   REAL,
    UNIQUE(date, asset_class, signal_name)
);

CREATE TABLE IF NOT EXISTS gdelt_events (
    id               TEXT PRIMARY KEY,
    event_code       TEXT,
    event_description TEXT,
    actor1_country   TEXT,
    actor2_country   TEXT,
    tone             REAL,
    goldstein_scale  REAL,
    num_mentions     INTEGER,
    affected_assets  TEXT,      -- JSON array
    event_date       TEXT,
    ingested_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_market_data_symbol_date ON market_data(symbol, date);
CREATE INDEX IF NOT EXISTS idx_daily_signals_date ON daily_signals(date);
CREATE INDEX IF NOT EXISTS idx_x_tweets_symbol ON x_tweets(asset_symbol);
CREATE INDEX IF NOT EXISTS idx_news_ingested ON news_articles(ingested_at);
