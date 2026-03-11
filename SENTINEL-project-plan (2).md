# SENTINEL — Asset Intelligence & Daily Digest System

## Comprehensive Project Plan v1.0

---

## Table of Contents

1. [Vision & Objectives](#1-vision--objectives)
2. [System Architecture](#2-system-architecture)
3. [Data Sources — Complete Stack](#3-data-sources--complete-stack)
4. [Scoring Engine — The Formula](#4-scoring-engine--the-formula)
5. [Daily Digest Email — Format & Content](#5-daily-digest-email--format--content)
6. [Technical Implementation](#6-technical-implementation)
7. [Asset Watchlist](#7-asset-watchlist)
8. [Build Phases & Timeline](#8-build-phases--timeline)
9. [Budget](#9-budget)
10. [Risks & Mitigations](#10-risks--mitigations)
11. [Rules — What We Do NOT Do](#11-rules--what-we-do-not-do)

---

## 1. Vision & Objectives

Sentinel is a multi-layer intelligence pipeline that ingests social media chatter and trusted financial data, runs sentiment analysis, volume anomaly detection, correlation tracking, risk scoring, and false-signal filtering, then produces a daily email ranking the top 10 public investable assets to consider — with full reasoning, confidence levels, and a self-correcting accuracy scorecard.

**Core principles:**

- Legal-first, cost-aware. Official/open feeds by default. No brittle scraper farms.
- Two boards: Public Investable (daily ranked) and Private Watchlist (startups, private RE themes). The daily "top 10" email comes exclusively from the public board. Private assets appear in a separate watchlist section.
- Cross-sectional normalization. A startup, gold, BTC, and a mid-cap stock do not have the same liquidity, price discovery, or execution profile. We never rank them in one raw bucket. Z-scores are computed within each asset class first.
- Self-improving. The system tracks its own prediction accuracy and dynamically adjusts signal weights over time.
- Lean start, scale later. Validate signals on free tiers before paying for premium data.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        DATA INGESTION LAYER                       │
│                                                                    │
│  Social Media             Financial News           Market Data     │
│  ┌──────────────┐        ┌────────────────┐      ┌─────────────┐ │
│  │ X / Twitter   │        │ RSS Feeds (15+) │      │ Finnhub     │ │
│  │ (Scrapingdog) │        │ FT, Bloomberg,  │      │ (Stocks,    │ │
│  │ $40/mo        │        │ Reuters, CNBC,  │      │  Forex,     │ │
│  │               │        │ CoinDesk, etc.  │      │  News)      │ │
│  ├──────────────┤        ├────────────────┤      │ FREE        │ │
│  │ Reddit        │        │ Finnhub News    │      ├─────────────┤ │
│  │ (PRAW)        │        │ (with sentiment)│      │ CoinGecko   │ │
│  │ FREE          │        │ FREE            │      │ (Crypto)    │ │
│  ├──────────────┤        ├────────────────┤      │ FREE        │ │
│  │ GDELT 2.0     │        │ FMP Sentiment   │      ├─────────────┤ │
│  │ (Geopolitical)│        │ RSS Feed        │      │ yfinance    │ │
│  │ FREE          │        │ FREE            │      │ (Historical,│ │
│  └──────────────┘        ├────────────────┤      │  Commodities│ │
│                           │ SEC / CFTC /    │      │  REITs)     │ │
│                           │ ESMA RSS        │      │ FREE        │ │
│                           │ FREE            │      ├─────────────┤ │
│                           ├────────────────┤      │ Alpha       │ │
│                           │ Firecrawl       │      │ Vantage     │ │
│                           │ (full-text      │      │ (Indicators)│ │
│                           │  extraction)    │      │ FREE        │ │
│                           │ $16/mo          │      ├─────────────┤ │
│                           └────────────────┘      │ FRED        │ │
│                                                    │ (Macro/RE)  │ │
│                                                    │ FREE        │ │
│                                                    └─────────────┘ │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                     PROCESSING & ANALYSIS LAYER                   │
│                                                                    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐ │
│  │ Sentiment        │  │ Volume Anomaly   │  │ Correlation      │ │
│  │ Analysis         │  │ Detection        │  │ Tracking         │ │
│  │ (LLM: Gemini     │  │ (Z-score vs      │  │ (Rolling 30d/90d │ │
│  │  Flash-Lite or   │  │  30d rolling)    │  │  Pearson)        │ │
│  │  DeepSeek V3)    │  │                  │  │                  │ │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐ │
│  │ Risk Scoring     │  │ Competitor       │  │ Regulatory       │ │
│  │ (Volatility,     │  │ Monitoring       │  │ Signal           │ │
│  │  Liquidity,      │  │ (Peer basket     │  │ (SEC, CFTC,      │ │
│  │  Drawdown,       │  │  divergence)     │  │  ESMA + keyword) │ │
│  │  MarketCap)      │  │                  │  │                  │ │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐                       │
│  │ Geopolitical     │  │ False Signal     │                       │
│  │ Capital Flow     │  │ Adjustment       │                       │
│  │ (GDELT +         │  │ (Backtesting     │                       │
│  │  safe-haven      │  │  + dynamic       │                       │
│  │  mapping)        │  │  weight update)  │                       │
│  └─────────────────┘  └─────────────────┘                       │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                     COMPOSITE SCORING ENGINE                      │
│                                                                    │
│  RawScore = Σ [ w_k(t) × Z_k(a,t) ]  (per asset class)          │
│  FinalScore = 100 × sigmoid(RawScore) × Confidence × Investab.   │
│  Hard filters → Rank → Top 10                                     │
│                                                                    │
│  Two boards:                                                       │
│  ├── Public Investable Board (stocks, crypto, commodities, REITs) │
│  └── Private Watchlist Board (startups, private RE themes)        │
│                                                                    │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                       DAILY DIGEST OUTPUT                         │
│                                                                    │
│  HTML email via Resend (free tier, 3K/mo)                         │
│  Orchestrated by Modal @modal.cron() (free tier, $30/mo credits)  │
│  Logged to Supabase for backtesting (free tier)                   │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Sources — Complete Stack

### 3.1 Social Media

#### X / Twitter → Scrapingdog X Scraper API

**Why Scrapingdog over Apify:** Single API endpoint, single pricing model, single data schema. No actor marketplace roulette. Dedicated X scraper returns parsed JSON (tweet text, likes, retweets, comments, profile data) directly. No HTML parsing needed.

**Why not open-source libraries (twikit, twscrape):** They require burner X account credentials, break every 2-4 weeks when Twitter rotates internal GraphQL APIs, and get accounts banned when run from cloud VPS IPs. twikit's GitHub issues page has dozens of unresolved issues. One developer documented needing 10-15 hours/month maintaining cookie-based scrapers. That's not "free."

| Detail | Value |
|--------|-------|
| Provider | Scrapingdog |
| Plan | Lite — $40/month |
| Credits | 200,000/month |
| Cost per X request | 5 credits = ~$0.001/tweet |
| Our volume | 50 assets × 20 tweets/day × 30 days = 30,000 tweets/month = 150,000 credits |
| Headroom | 50,000 credits buffer (~33%) |
| Overflow | PAYG: $10 = 25,000 additional credits (no expiry) |
| Free trial | 1,000 credits (enough to validate 200 tweets) |
| Output format | Parsed JSON |
| Search support | Yes (keyword, hashtag, profile) |

**Implementation notes:**

- Use keyword searches: `$AAPL`, `$BTC`, `NVIDIA earnings`, `gold price`, `$SOL`
- Also scrape 10-15 key financial influencer profiles for high-signal tweets
- Schedule daily at 04:00 UTC via Modal `@modal.cron()`
- Store raw JSON in Supabase `x_tweets` table

#### Reddit → PRAW (Official Python API)

**Why PRAW:** Free, official, no auth hassles for reading public data, 60 requests/minute is more than enough for daily monitoring of 15 subreddits. No scraping risk.

| Detail | Value |
|--------|-------|
| Provider | Reddit Official API via PRAW |
| Cost | $0 |
| Rate limit | 60 requests/minute (authenticated) |
| Auth | OAuth2 (free developer app registration) |
| Our volume | 15 subreddits × ~50 top posts each = 750 posts/day |

**Subreddits to monitor:**

- Stocks/general: r/wallstreetbets, r/investing, r/stocks, r/StockMarket, r/options
- Crypto: r/cryptocurrency, r/bitcoin, r/ethereum, r/defi, r/altcoin
- Real estate: r/RealEstate, r/REBubble, r/commercialrealestate
- Macro/general: r/economics, r/startups

**Implementation notes:**

- Pull top 50 hot + top 20 new posts per subreddit daily
- Extract: title, selftext, score, num_comments, created_utc, subreddit
- Store in Supabase `reddit_posts` table

#### LinkedIn → NOT a source

LinkedIn's ToS explicitly prohibits scraping with third-party bots. Most useful API access is partner-program-only. For startup/company data, use Crunchbase instead.

### 3.2 Trusted Financial News

#### RSS Feeds → Free, self-hosted with Python feedparser

RSS is the zero-cost workhorse. These feeds are public, legal, and designed for consumption.

**Feeds to monitor (grouped by priority):**

**Tier 1 — Major financial news (poll every 30 min):**

- Reuters — `reuters.com/arc/outboundfeeds/rss/` (multiple topic feeds)
- CNBC — `cnbc.com/id/100003114/device/rss/rss.html`
- MarketWatch — `feeds.marketwatch.com/marketwatch/topstories`
- Financial Times — `ft.com/rss/home` (headlines, limited full text)
- Bloomberg — `bloomberg.com/feed/podcast/...` (headlines)

**Tier 2 — Crypto-specific (poll every 30 min):**

- CoinDesk — `coindesk.com/arc/outboundfeeds/rss/`
- The Block — `theblock.co/rss`
- Decrypt — `decrypt.co/feed`

**Tier 3 — Analysis & opinion (poll every 2 hours):**

- Seeking Alpha — `seekingalpha.com/feed.xml`
- Investing.com RSS — `investing.com/rss/news.rss` (read-only RSS is fine; scraping the site is not)
- Zero Hedge — RSS feed

**Tier 4 — Macro / central bank (poll every 4 hours):**

- FRED Blog RSS
- IMF Blog RSS
- ECB press releases RSS

**Implementation:** Python `feedparser` + `APScheduler`. Parse title, summary, published date, link. Store in Supabase `news_articles` table. Use Firecrawl ($16/mo) to fetch full article text from links when the RSS summary is too short for sentiment analysis.

#### Finnhub Market News API (Free Tier)

Pre-categorized news with built-in sentiment. Categories: general, forex, crypto, merger.

| Detail | Value |
|--------|-------|
| Cost | $0 (free tier) |
| Rate limit | 60 calls/minute |
| Features | News headlines, related tickers, source, datetime, sentiment |
| Categories | general, forex, crypto, merger |

#### FMP News Sentiment RSS (Free Tier)

Pre-scored sentiment per ticker. Updated daily.

| Detail | Value |
|--------|-------|
| Cost | $0 (free tier) |
| Features | Headline, snippet, URL, ticker symbol, sentiment score |

#### Benzinga Basic (Free Tier via AWS Marketplace)

Headlines + teaser text. Good for tracking breaking market news.

#### Tiingo News API (Free Tier)

Non-traditional sources with rich tagging. 3 months of historical data. ~700K articles added per month. Tags by company mentions, product mentions, and slang.

#### Firecrawl (Hobby Plan — $16/mo)

For extracting full article text from RSS-linked articles, company IR pages, and regulator pages that only provide headlines in their feeds.

| Detail | Value |
|--------|-------|
| Plan | Hobby — $16/month |
| Credits | 3,000/month |
| Cost per page | 1 credit |
| Our volume | ~100 full-text extractions/day = ~3,000/month |
| Use cases | Full article text from RSS links, SEC filing pages, company earnings pages |

### 3.3 Market Price Data

| Asset Class | Primary Source | Backup | Cost |
|-------------|---------------|--------|------|
| US Stocks (real-time quotes) | Finnhub free tier | — | $0 |
| US Stocks (historical prices, indicators) | yfinance (Python) | Alpha Vantage free | $0 |
| Crypto (prices, volume, market cap) | CoinGecko free tier (10K calls/mo) | — | $0 |
| Commodities (gold, oil, silver, copper, nat gas) | yfinance via ETF proxies (GLD, USO, SLV, CPER, UNG) | Alpha Vantage | $0 |
| REITs | yfinance (VNQ, O, AMT, PLD, EQIX) | — | $0 |
| Forex | Finnhub free tier | — | $0 |
| Technical indicators (RSI, MACD, Bollinger) | Alpha Vantage free (25 calls/day) | yfinance + ta-lib | $0 |
| Company fundamentals (earnings, PE, revenue) | FMP free tier | Finnhub free | $0 |
| SEC filings | FMP free tier | SEC EDGAR RSS | $0 |

**Note on Twelve Data:** ChatGPT recommended Twelve Data ($79/mo Grow) as a unified vendor. This is the correct long-term play — one SDK, one auth flow, one schema for stocks+crypto+forex+commodities. But at the MVP stage, the free-tier patchwork (Finnhub + CoinGecko + yfinance + Alpha Vantage) validates the concept at $0. Upgrade to Twelve Data when we've proven the system generates useful signals.

### 3.4 Geopolitical & Regulatory

#### GDELT 2.0 (Free, Open)

GDELT monitors global news media in 100+ languages, updates every 15 minutes, and provides event data, tone/sentiment scores, and geographic metadata. It's purpose-built for tracking conflict intensity, capital flows, and political events.

| Detail | Value |
|--------|-------|
| Cost | $0 |
| Update frequency | Every 15 minutes |
| Data | Event records, tone scores, themes, locations, actors |
| API | REST + BigQuery (free tier) |
| Use case | Conflict detection, sanctions monitoring, safe-haven flow signals |

**Implementation:** Query GDELT's API for events matching themes like MILITARY, SANCTIONS, TRADE_WAR, PROTEST. Map conflict intensity to likely beneficiaries/losers:

- Safe havens: gold, USD, Treasuries, BTC (in some narratives)
- Energy shocks: oil, gas, shipping stocks
- Food shocks: wheat, fertilizer companies
- Defense: defense ETFs (ITA, XAR), specific defense names
- Region-specific: FX pairs, country ETFs

#### Regulatory Feeds (Free)

| Source | Type | Coverage |
|--------|------|----------|
| SEC EDGAR RSS | Official filings | US public companies, crypto enforcement |
| CFTC RSS | Official | Commodities, derivatives, crypto |
| ESMA Newsletters | Official | EU market regulation |
| Finnhub SEC filings endpoint | API | Parsed filing data |

### 3.5 Real Estate & Macro

| Source | Type | Cost | Data |
|--------|------|------|------|
| FRED API | Official Fed Reserve data | $0 | Interest rates, CPI, unemployment, housing starts, yield curves |
| Zillow Public Data | Published datasets | $0 | Home values, rental indices by metro |
| yfinance REITs | Market data | $0 | REIT prices, yields, volume |

### 3.6 Startups / Private Companies (Watchlist Board Only)

| Source | Type | Cost | Data |
|--------|------|------|------|
| Crunchbase Basic API | Official | $0 (basic endpoints) | Organization info, funding rounds, key people |
| RSS/News monitoring | Passive | $0 | Funding announcements, pivots, exits |

**Note:** Advanced Crunchbase endpoints (detailed financials, advanced search) require commercial licensing. Start with basic endpoints; upgrade if the private watchlist proves valuable.

---

## 4. Scoring Engine — The Formula

### 4.1 Two-Layer Architecture

#### Layer 1: Base Opportunity Score

For asset `a` on day `t`:

```
RawScore(a,t) = Σ [ w_k(t) × Z_k(a,t) ]
```

Where `Z_k` are **cross-sectionally normalized features within each asset class first**. This means a crypto asset's volume anomaly is compared to other crypto assets, not to Apple's trading volume.

#### Layer 2: Reliability Filter + Final Score

```
FinalScore = 100 × sigmoid(RawScore) × Confidence × Investability
```

Where:

- **Confidence** = source_breadth × source_quality × freshness
  - source_breadth: How many independent sources contributed signals (more = higher)
  - source_quality: Weighted by source tier (FT/Bloomberg mention = 1.0, Reddit = 0.3, random X = 0.1)
  - freshness: Exponential decay — signals from 1 hour ago score higher than 24 hours ago

- **Investability** = 0 if any hard filter fails, else 0.6–1.0
  - Hard filters (instant disqualification if failed):
    - Minimum average daily volume threshold
    - Minimum market cap (stocks: >$500M, crypto: >$50M)
    - No severe unresolved regulatory red flag (active SEC enforcement = disqualify)
    - No broken data coverage (if we have <3 data sources for an asset, don't rank it)
    - No extreme spread/slippage penalty

### 4.2 Signal Definitions & Weights

#### Signal 1: News Sentiment (Base Weight: 0.12)

Sentiment from trusted financial news sources (RSS, Finnhub News, FMP, Tiingo).

```
NewsSentiment = 0.5 × CurrentSentiment + 0.3 × SentimentAcceleration + 0.2 × SourceConcentration
```

- **CurrentSentiment** (normalized -1 to +1): LLM-scored from article text. Run each article through Gemini Flash-Lite with structured prompt returning `{sentiment: float, confidence: float, entities: string[]}`.
- **SentimentAcceleration**: Delta between today's avg vs 7-day rolling avg. Rapid shifts score high.
- **SourceConcentration**: Penalize if all sentiment comes from one source. Reward diversity.

**Key insight:** A strong signal is often not "high sentiment" but **sentiment improving while price hasn't fully moved yet**.

#### Signal 2: Social Sentiment (Base Weight: 0.10)

Sentiment from X/Twitter and Reddit.

```
SocialSentiment = 0.4 × CurrentSocial + 0.3 × SocialMomentum + 0.2 × MentionVolume + 0.1 × InfluencerWeight
```

- **CurrentSocial**: LLM-scored from tweets and Reddit posts. Classify as strongly_bullish, bullish, neutral, bearish, strongly_bearish.
- **SocialMomentum**: 24-hour sentiment delta vs 7-day baseline.
- **MentionVolume**: Z-score of mention count vs 30-day baseline.
- **InfluencerWeight**: Verified financial analysts on X = 0.7x weight. Random accounts = 0.1x. WSB posts with >500 upvotes = 0.5x.

**Blend differently by asset class:**

- Stocks/REITs/Commodities: heavier trusted-news weight (0.14 news / 0.08 social)
- Crypto: more balanced (0.10 news / 0.12 social)
- Startups: trusted-news + funding mentions, very light raw social

**Track disagreement:** When trusted news says one thing and social says another, that IS a signal. Flag it.

#### Signal 3: Sentiment Shift (Base Weight: 0.08)

Captures momentum in sentiment — the derivative, not the absolute level.

```
SentimentShift = weighted_avg(
    0.5 × shift_24h_vs_7d,
    0.3 × shift_7d_vs_30d,
    0.2 × news_vs_social_divergence
)
```

#### Signal 4: Volume Anomaly (Base Weight: 0.12)

Detect unusual trading activity that often precedes price movements.

```
VolumeAnomaly = z_score(today_volume, rolling_20d_median, rolling_20d_std)
```

- Pull daily volume from Finnhub (stocks), CoinGecko (crypto), yfinance (commodities).
- Use 20-day median (more robust to outliers than mean).
- **Scoring:** z < 1 = low signal, z 1-2 = moderate, z 2-3 = strong, z > 3 = extreme.
- Cross-reference with price direction: volume spike + price up = bullish accumulation. Volume spike + flat price = stealth accumulation (even more bullish).

**Flag only when anomaly is confirmed by at least one of:** improving sentiment, positive catalyst, or peer-relative strength. Unconfirmed volume spikes get dampened.

**Additional where available:**

- Social mention volume vs normal baseline (from X/Reddit data)
- Options open interest anomaly (from Finnhub, where available)

#### Signal 5: Price Regime / Momentum Confirmation (Base Weight: 0.12)

```
MomentumScore = 0.4 × price_vs_20dma + 0.3 × RSI_position + 0.3 × MACD_signal
```

- Price above 20-day MA = bullish trend confirmation
- RSI 30-50 rising = oversold recovery (strong)
- RSI 50-70 = healthy momentum
- MACD crossover = trend change signal

Data source: Alpha Vantage technical indicators API (free, 25 calls/day — batch smartly).

#### Signal 6: Correlation Divergence (Base Weight: 0.08)

```
CorrelationScore = |current_30d_correlation - historical_90d_correlation|
```

- Compute rolling 30-day Pearson correlation between each asset and its benchmark:
  - Stocks → S&P 500 (SPY)
  - Altcoins → Bitcoin (BTC)
  - Commodities → Dollar Index (DXY, inverted)
  - REITs → 10-year Treasury yield (inverted)
- Also track inter-asset correlations (e.g., NVDA vs AMD, BTC vs ETH).
- A **correlation break** is valuable when the asset stops behaving like its historical regime before the market narrative catches up.

**Scoring:** Small divergence (<0.1) = weak. Medium (0.1-0.3) = moderate. Large (>0.3) = strong. Direction matters: diverging positively (outperforming when correlated peer drops) scores higher.

#### Signal 7: Risk-Adjusted Liquidity (Base Weight: 0.10) — INVERTED

Lower risk = higher score contribution. This is a safety gate.

```
Risk = 0.40 × VolatilityPct + 0.25 × IlliquidityPct + 0.20 × DrawdownPct + 0.15 × SmallCapPenalty
RiskAdj = 100 - Risk
```

- **VolatilityPct** (0-100): Annualized std dev of daily returns over 30 days. Normalized within asset class.
- **IlliquidityPct** (0-100): Based on average daily volume × price. Low liquidity = high risk.
- **DrawdownPct** (0-100): Current drawdown from 52-week high. Deep drawdown = higher risk.
- **SmallCapPenalty** (0-100): Micro-cap stocks (<$1B) and sub-$50M crypto get penalized.

**For startups/private assets (watchlist board only):**

Substitute with: funding recency, funding runway proxy, news dependence, information opacity, mark-to-market uncertainty.

#### Signal 8: Regulatory Signal (Base Weight: 0.08)

```
RegulatoryScore = base_neutral + Σ(event × direction × impact)
```

Create a signed event score per regulatory event: strongly_positive (+2), mildly_positive (+1), neutral (0), mildly_negative (-1), strongly_negative (-2).

**Keywords monitored:** "SEC", "regulation", "ban", "approval", "ETF filing", "CFTC", "MiCA", "stablecoin bill", "executive order", "enforcement action", "fine", "settlement".

**For crypto:** Regulatory signal is a separate factor, NOT folded into general news sentiment. Crypto regulatory events are binary catalysts that deserve independent weight.

Data sources: SEC RSS, CFTC RSS, ESMA notifications, Finnhub news (filtered), RSS feeds (filtered).

#### Signal 9: Competitor Relative Edge (Base Weight: 0.06)

For stocks and startups only.

```
CompetitorScore = Σ(own_positive - peer_avg_positive) - Σ(own_negative - peer_avg_negative)
```

- Define 3-5 peer basket per watched company (e.g., NVDA peers: AMD, INTC, AVGO, QCOM).
- Compare news sentiment vs peers.
- Compare relative returns vs peers.
- Compare volume anomaly vs peers.
- Flag "positive divergence" (outperforming peers on sentiment/price) or "negative divergence."

This is especially useful when one company gets good news but the entire peer group is already pricing it in.

#### Signal 10: Geopolitical Capital-Flow Signal (Base Weight: 0.07)

This is a **capital-flow classifier**, not just a headline feed.

```
GeopoliticalScore = safe_haven_flow + sanctions_impact + conflict_proximity
```

Map conflict intensity (from GDELT) to likely beneficiaries/losers:

| Conflict Type | Beneficiaries | Losers |
|---------------|---------------|--------|
| Military escalation | Gold, USD, Treasuries, defense ETFs | Regional equities, travel stocks |
| Energy sanctions | Oil, gas, shipping stocks | Energy-importing country equities |
| Trade war / tariffs | Domestic manufacturers, import substitutes | Export-dependent companies |
| Food crisis | Wheat futures, fertilizer companies | Food-importing country equities |
| Currency crisis | BTC (sometimes), USD, gold | Local currency assets |

Data source: GDELT 2.0 (free, 15-min updates) + RSS conflict keywords + price reaction confirmation + correlation breaks.

#### Signal 11: Catalyst Freshness / Source Quality (Base Weight: 0.07)

```
CatalystScore = recency_weight × source_tier_weight × uniqueness
```

- **Recency:** Exponential decay. A catalyst from 2 hours ago scores 5x higher than one from 48 hours ago.
- **Source tier:** FT/Bloomberg/Reuters = 1.0, CNBC/MarketWatch = 0.8, CoinDesk/TheBlock = 0.7 (for crypto), Seeking Alpha = 0.5, Reddit = 0.3, X = 0.1-0.7 (depends on account).
- **Uniqueness:** First-mover signal (only one source reporting) scores higher than consensus signal (everyone reporting). First-mover = potential alpha.

### 4.3 Dynamic Weight Adjustment (The False-Signal Filter)

This is the meta-layer that makes the system self-improving.

For each signal family `k`, track:

- Precision of past alerts (did high-score assets actually go up?)
- Forward 1-day, 5-day, 20-day return quality
- Hit rate **by asset class** (social sentiment might work for crypto but not commodities)
- Average drawdown after alert

Then update weights dynamically:

```
w_k(t) = base_w_k × clamp(0.5 + 1.5 × HitRate_k, 0.5, 2.0)
```

This means:

- If a signal has 0% hit rate → weight drops to 50% of base (0.5x)
- If a signal has 33% hit rate → weight stays at base (1.0x)
- If a signal has 100% hit rate → weight doubles (2.0x)
- Clamped so no single signal can dominate or be fully zeroed

**Per-asset-class tracking:** If "social sentiment spike" works badly for commodities but well for crypto, its weight falls for commodities and rises for crypto automatically.

**Minimum lookback:** 30 days before adjustments kick in. Start with base weights.

### 4.4 Weight Summary Table

| # | Signal | Base Weight | Data Sources |
|---|--------|-------------|--------------|
| 1 | News Sentiment | 0.12 | RSS, Finnhub News, FMP, Tiingo |
| 2 | Social Sentiment | 0.10 | X (Scrapingdog), Reddit (PRAW) |
| 3 | Sentiment Shift | 0.08 | Derived from signals 1+2 |
| 4 | Volume Anomaly | 0.12 | Finnhub, CoinGecko, yfinance |
| 5 | Price Regime / Momentum | 0.12 | Alpha Vantage, yfinance |
| 6 | Correlation Divergence | 0.08 | Computed from price data |
| 7 | Risk-Adjusted Liquidity | 0.10 | Computed from price/volume data |
| 8 | Regulatory Signal | 0.08 | SEC/CFTC/ESMA RSS, Finnhub |
| 9 | Competitor Relative Edge | 0.06 | Derived from news + price vs peers |
| 10 | Geopolitical Capital-Flow | 0.07 | GDELT 2.0, RSS conflict keywords |
| 11 | Catalyst Freshness / Quality | 0.07 | Metadata from all sources |
| | **Total** | **1.00** | |

---

## 5. Daily Digest Email — Format & Content

The email goes out at **07:00 local time**, generated by a pipeline that runs starting at 04:00 UTC.

### 5.1 Email Structure

```
Subject: 🎯 Sentinel Daily Radar — March 10, 2026

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 MARKET REGIME SUMMARY

Regime: Risk-On | VIX: 16.2 (low fear) | DXY: 103.4 (stable)
10Y Treasury: 4.08% (↓3bp) | BTC Dominance: 58.2% (rising)
Macro context: FOMC minutes Wednesday. No rate change expected.
GDELT conflict intensity: Elevated (Eastern Europe +12% vs 7d avg)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🏆 TOP 10 PUBLIC INVESTABLE ASSETS
Based on 1,247 signals processed across 50 assets

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

#1 — NVIDIA (NVDA) ..................... Score: 91.4 (↑3.2)
    Asset Class: Stock | Sector: Semiconductors
    Confidence: HIGH (12 sources) | Risk: LOW

    WHY: Earnings beat leaked by 3 credible analysts on X.
    Social sentiment surged +34% in 24h while price flat
    (= unfilled gap). Volume 2.8σ above 20d median.
    AMD down 4% on weak guidance = competitor tailwind.

    Top drivers: 🟢 Social 94 | 🟢 Volume 88 | 🟢 Competitor 85
    Top risk: Concentration — all signal from one earnings event

#2 — Bitcoin (BTC) .................... Score: 87.2 (↑1.8)
    Asset Class: Crypto
    Confidence: HIGH (9 sources) | Risk: MEDIUM

    WHY: SEC commissioner speech signaling favorable stance
    on spot ETF options. Reddit sentiment hit 6-month high.
    Diverging from altcoin correlation (BTC dominance rising).
    GDELT: safe-haven flows accelerating.

    Top drivers: 🟢 Regulatory 92 | 🟢 Sentiment 81 | 🟡 Risk 65
    Top risk: Volatility inherent to asset class

    ...

#10 — Gold (GLD) ...................... Score: 72.1 (↑0.4)
    Asset Class: Commodity
    Confidence: MEDIUM (6 sources) | Risk: LOW

    WHY: GDELT conflict intensity elevated in Eastern Europe.
    Safe-haven flows confirmed by correlation break (gold
    diverging from DXY pattern). Volume +1.4σ.

    Top drivers: 🟢 Geopolitical 82 | 🟢 Correlation 76 | 🟢 Risk 88
    Top risk: Conflict de-escalation would reverse signal

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 YESTERDAY'S ALERTS SCORECARD

Yesterday's Top 10 → 24-hour performance:
  ✅ NVDA: +2.1% (was #1, score 88.2)
  ✅ BTC: +1.4% (was #2, score 85.4)
  ✅ SOL: +3.8% (was #3, score 83.1)
  ❌ AMZN: -0.6% (was #4, score 81.7)
  ✅ GLD: +0.8% (was #5, score 79.3)
  ...

  24h hit rate: 7/10 (70%) ← on target
  7d rolling hit rate: 64% (improving from 58%)
  30d rolling hit rate: 61%

  Signal accuracy by type (30d):
  🟢 Volume anomaly: 72% precision (strongest)
  🟢 Regulatory signal: 68% precision
  🟡 News sentiment: 59% precision
  🟡 Social sentiment: 54% precision (weight being reduced for commodities)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ REGULATORY WATCH

  • SEC: New enforcement action against [crypto exchange] — bearish for exchange tokens
  • CFTC: Proposed rule on crypto derivatives — neutral, comment period open
  • EU MiCA: Implementation deadline approaching for stablecoin provisions

🌍 CONFLICT / CAPITAL-FLOW WATCH

  • Eastern Europe: Tension elevated (+12% GDELT intensity)
    → Beneficiaries: Gold, defense ETFs, energy
    → At risk: European equities, regional FX
  • Middle East: Stable (no change)
  • US-China trade: New semiconductor export controls rumored
    → Watch: ASML, TSMC, Chinese tech ADRs

📈 COMPETITOR DIVERGENCE ALERTS

  • NVDA vs AMD: NVDA positive divergence (+4.2% relative, sentiment gap widening)
  • COIN vs crypto peers: COIN lagging despite BTC strength (negative divergence)

🔍 PRIVATE WATCHLIST (Research Only — Not Ranked)

  • [Startup A]: Series B announced, $45M at $300M valuation
  • [Startup B]: CTO departure reported on LinkedIn → risk flag

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sentinel v1.0 | Signals processed: 1,247 | Sources: 23 active
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 5.2 "Hit" Definition for Scorecard

An asset "hit" is defined as: **price increased by ≥1% within 5 trading days of being in the top 10.**

We also track 1-day and 20-day returns for additional context, but the primary precision metric uses the 5-day window.

---

## 6. Technical Implementation

### 6.1 Tech Stack

| Component | Tool | Why |
|-----------|------|-----|
| **Language** | Python 3.12 | Ecosystem for data science, all APIs have Python SDKs |
| **Orchestration + Runtime** | Modal (free tier, $30/mo credits) | Python-native serverless. `@modal.cron()` decorator = entire scheduling logic. Per-second billing, $0 idle cost, no YAML/Docker/Kubernetes. ~$3/mo actual compute for our pipeline, well within $30 free credit. If we ever self-host the LLM sentiment layer, Modal gives instant GPU access. |
| **Database** | Supabase (Postgres, free tier) | Structured storage, real-time, Edge Functions, dashboard |
| **X Scraping** | Scrapingdog X Scraper API ($40/mo) | Dedicated, parsed JSON, single vendor |
| **Reddit** | PRAW (free) | Official API, no risk |
| **RSS Parsing** | Python feedparser (free) | Lightweight, reliable |
| **Full-text extraction** | Firecrawl Hobby ($16/mo) | LLM-ready markdown from article URLs |
| **Financial APIs** | Finnhub + CoinGecko + yfinance + Alpha Vantage (all free) | Cross-asset coverage at $0 |
| **Geopolitical** | GDELT 2.0 (free) | 15-min updates, conflict/event data |
| **Regulatory** | SEC/CFTC/ESMA RSS (free) | Official feeds |
| **Macro** | FRED API (free) | Official Fed data |
| **LLM (Sentiment)** | Gemini Flash-Lite (~$0.07/1M input tokens) or DeepSeek V3 (~$0.14/1M) | Cheapest models for structured sentiment classification |
| **Email** | Resend (free, 3K/mo) | Developer-friendly API, HTML templates |
| **Monitoring** | Supabase Dashboard + optional Airtable | Visual oversight |

#### Why Modal over GitHub Actions and Trigger.dev

We evaluated three cloud orchestration options:

| Factor | GitHub Actions | Modal | Trigger.dev |
|--------|---------------|-------|-------------|
| **Cost** | $0 (public repo) or 2K free min/mo (private) | $0 ($30 free credits/mo, we use ~$3) | $0 ($5 free usage/mo) |
| **Language** | Any (YAML workflow + Ubuntu container) | Python-native (decorators) | TypeScript-first |
| **Cron reliability** | 15-20 min drift common, auto-disables after 60 days of repo inactivity | Reliable, sub-minute precision | Reliable |
| **Pipeline fit** | Workable but clunky YAML config | Perfect — `@modal.cron("0 4 * * *")` on our main function is the entire scheduling logic | Mismatch — TS-first, Python is second-class citizen |
| **DX** | YAML workflows, limited local debugging | `modal run` for local testing, instant cloud logs, hot-reload | Great for TS, awkward for Python pipelines |
| **GPU scaling** | No GPU support | Autoscale to A100/H100 GPUs if we self-host LLM sentiment | No GPU support |
| **Free headroom** | ~500 min/mo buffer | ~$27/mo buffer of unused free credit | ~$1-2/mo buffer |

**Modal wins** because Sentinel is fundamentally a scheduled Python pipeline that runs daily, hits APIs, processes data, and sends output. Modal is purpose-built for this. The `@modal.cron()` decorator replaces all YAML config, and if we ever want to self-host the sentiment LLM instead of paying for Gemini Flash API calls, Modal gives us instant GPU access within the same codebase.

#### Modal Pipeline Structure

```python
import modal

app = modal.App("sentinel")

# Define the container image with all dependencies
image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "feedparser", "praw", "httpx", "pandas", "numpy",
    "supabase", "resend", "google-generativeai",
)

# Persistent storage for cookies, caches, model weights
volume = modal.Volume.from_name("sentinel-data", create_if_missing=True)

@app.function(
    image=image,
    volumes={"/data": volume},
    secrets=[modal.Secret.from_name("sentinel-secrets")],  # API keys
    timeout=3600,  # 1 hour max
)
@modal.cron("0 4 * * *")  # Run daily at 04:00 UTC
async def run_daily_pipeline():
    """Main Sentinel pipeline — runs every day at 04:00 UTC."""
    
    # Step 1: Ingest data
    tweets = await scrape_x()           # Scrapingdog
    reddit_posts = await scrape_reddit() # PRAW
    news = await fetch_rss_feeds()       # feedparser
    gdelt = await fetch_gdelt()          # GDELT API
    market_data = await fetch_prices()   # Finnhub + CoinGecko + yfinance
    articles = await fetch_full_text()   # Firecrawl
    
    # Step 2: Analyze
    sentiments = await run_sentiment(tweets, reddit_posts, news, articles)
    signals = compute_signals(market_data, sentiments, gdelt)
    
    # Step 3: Score & rank
    scores = compute_composite_scores(signals)
    top_10 = rank_and_filter(scores, board="public")
    
    # Step 4: Backtest yesterday
    scorecard = evaluate_yesterday(scores)
    update_dynamic_weights(scorecard)
    
    # Step 5: Send email
    html = render_email(top_10, scorecard)
    send_via_resend(html)
    
    # Step 6: Log everything
    log_to_supabase(scores, signals, top_10, scorecard)
```

### 6.2 Database Schema (Supabase / Postgres)

```sql
-- Core asset registry
CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    asset_class TEXT NOT NULL CHECK (asset_class IN ('stock', 'crypto', 'commodity', 'reit', 'startup')),
    board TEXT NOT NULL CHECK (board IN ('public', 'private')),
    sector TEXT,
    peers TEXT[],                    -- peer basket symbols
    benchmark_symbol TEXT,           -- correlation benchmark (SPY, BTC, DXY, etc.)
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Raw X/Twitter data
CREATE TABLE x_tweets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tweet_id TEXT UNIQUE,
    asset_symbol TEXT REFERENCES assets(symbol),
    tweet_text TEXT,
    author_handle TEXT,
    author_verified BOOLEAN,
    likes INTEGER,
    retweets INTEGER,
    replies INTEGER,
    views TEXT,
    sentiment_score FLOAT,          -- LLM-scored -1 to +1
    sentiment_confidence FLOAT,
    scraped_at TIMESTAMPTZ DEFAULT now()
);

-- Raw Reddit data
CREATE TABLE reddit_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id TEXT UNIQUE,
    asset_symbol TEXT REFERENCES assets(symbol),
    subreddit TEXT,
    title TEXT,
    selftext TEXT,
    score INTEGER,
    num_comments INTEGER,
    sentiment_score FLOAT,
    sentiment_confidence FLOAT,
    created_utc TIMESTAMPTZ,
    scraped_at TIMESTAMPTZ DEFAULT now()
);

-- News articles (RSS + API)
CREATE TABLE news_articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,            -- 'reuters', 'finnhub', 'fmp', etc.
    source_tier FLOAT,               -- 1.0 for FT/Bloomberg, 0.5 for Seeking Alpha, etc.
    title TEXT,
    summary TEXT,
    full_text TEXT,                   -- from Firecrawl extraction
    url TEXT UNIQUE,
    asset_symbols TEXT[],            -- which assets mentioned
    sentiment_score FLOAT,
    sentiment_confidence FLOAT,
    published_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ DEFAULT now()
);

-- GDELT geopolitical events
CREATE TABLE gdelt_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_code TEXT,
    event_description TEXT,
    actor1_country TEXT,
    actor2_country TEXT,
    tone FLOAT,
    goldstein_scale FLOAT,           -- conflict intensity (-10 to +10)
    num_mentions INTEGER,
    affected_assets TEXT[],
    event_date DATE,
    ingested_at TIMESTAMPTZ DEFAULT now()
);

-- Daily market data snapshot
CREATE TABLE market_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol TEXT REFERENCES assets(symbol),
    date DATE NOT NULL,
    open FLOAT,
    high FLOAT,
    low FLOAT,
    close FLOAT,
    volume BIGINT,
    market_cap FLOAT,
    rsi_14 FLOAT,
    macd_signal FLOAT,
    bollinger_position FLOAT,        -- position within bands (0-1)
    volatility_30d FLOAT,            -- annualized
    avg_volume_20d FLOAT,
    volume_zscore FLOAT,             -- pre-computed
    UNIQUE(symbol, date)
);

-- Daily computed signals per asset
CREATE TABLE daily_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol TEXT REFERENCES assets(symbol),
    date DATE NOT NULL,
    news_sentiment FLOAT,
    social_sentiment FLOAT,
    sentiment_shift FLOAT,
    volume_anomaly FLOAT,
    momentum_score FLOAT,
    correlation_divergence FLOAT,
    risk_adjusted_liquidity FLOAT,
    regulatory_signal FLOAT,
    competitor_edge FLOAT,
    geopolitical_flow FLOAT,
    catalyst_freshness FLOAT,
    raw_score FLOAT,
    confidence FLOAT,
    investability FLOAT,
    final_score FLOAT,
    rank INTEGER,
    UNIQUE(symbol, date)
);

-- Backtesting log (for false-signal adjustment)
CREATE TABLE backtesting_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol TEXT REFERENCES assets(symbol),
    signal_date DATE NOT NULL,
    rank_on_signal_date INTEGER,
    final_score_on_signal_date FLOAT,
    top_signals JSONB,               -- which signals drove the score
    return_1d FLOAT,
    return_5d FLOAT,
    return_20d FLOAT,
    hit_1d BOOLEAN,                  -- >1% in 1 day?
    hit_5d BOOLEAN,                  -- >1% in 5 days?
    max_drawdown_5d FLOAT,
    evaluated_at TIMESTAMPTZ DEFAULT now()
);

-- Signal weight history (tracks dynamic adjustments)
CREATE TABLE signal_weights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    asset_class TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    base_weight FLOAT,
    adjusted_weight FLOAT,
    hit_rate_30d FLOAT,
    precision_30d FLOAT,
    UNIQUE(date, asset_class, signal_name)
);
```

### 6.3 Pipeline Execution Schedule (Daily)

All times UTC. Local delivery at 07:00 user time. The entire pipeline runs as a single Modal function triggered by `@modal.cron("0 4 * * *")`.

| Time | Step | Duration | Tool |
|------|------|----------|------|
| 04:00 | Scrape X via Scrapingdog (50 assets × 20 tweets) | ~10 min | Python + Scrapingdog API |
| 04:15 | Scrape Reddit via PRAW (15 subreddits × 50 posts) | ~5 min | Python + PRAW |
| 04:25 | Fetch RSS feeds (15+ sources) | ~3 min | Python + feedparser |
| 04:30 | Fetch GDELT events (last 24h, conflict themes) | ~2 min | Python + GDELT API |
| 04:35 | Pull market data (Finnhub, CoinGecko, yfinance) | ~8 min | Python + API calls |
| 04:45 | Fetch full article text via Firecrawl (top 50 articles) | ~10 min | Python + Firecrawl API |
| 05:00 | Run LLM sentiment on all collected text (~500-1000 items) | ~15 min | Python + Gemini Flash API |
| 05:20 | Compute all 11 signals per asset | ~5 min | Python + numpy/pandas |
| 05:30 | Run composite scoring + ranking | ~3 min | Python |
| 05:35 | Evaluate yesterday's predictions (backtest) | ~3 min | Python + Supabase query |
| 05:40 | Update dynamic signal weights (if ≥30 days data) | ~2 min | Python |
| 05:45 | Generate email HTML | ~2 min | Python + Jinja2 template |
| 05:47 | Send via Resend | Instant | Python + Resend API |
| 05:50 | Log all scores, signals, predictions to Supabase | ~3 min | Python + Supabase client |

**Total pipeline runtime: ~50 minutes**
**Estimated Modal compute cost: ~$0.10/run × 30 days = ~$3/month** (well within $30 free credit)

### 6.4 LLM Sentiment Prompt (Structured Output)

```python
SENTIMENT_PROMPT = """
Analyze the following text about financial assets and return ONLY valid JSON.

Text: {text}

Return this exact JSON structure:
{
  "sentiment": <float between -1.0 (extremely bearish) and 1.0 (extremely bullish)>,
  "confidence": <float between 0.0 and 1.0>,
  "entities": [<list of ticker symbols or asset names mentioned>],
  "topics": [<list of topics: "earnings", "regulation", "merger", "layoffs", "product_launch", "macro", "conflict", "technical", "other">],
  "is_regulatory": <boolean>,
  "regulatory_direction": <"positive", "negative", "neutral", or null if not regulatory>
}

Rules:
- 0.0 sentiment = perfectly neutral
- Consider the FINANCIAL implications, not just tone
- "Revenue missed estimates" = bearish even if article tone is neutral
- "SEC approves ETF" = strongly positive for that asset class
- If uncertain, bias toward 0.0 with low confidence
"""
```

Batch process ~500-1000 text items/day. At Gemini Flash-Lite pricing (~$0.07/1M input tokens), with an average of ~200 tokens per item, this costs approximately $0.007-0.014/day = **~$0.30/month**.

---

## 7. Asset Watchlist

### 7.1 Public Investable Board (50 assets)

#### Stocks (20)

| Symbol | Name | Sector | Peers |
|--------|------|--------|-------|
| NVDA | NVIDIA | Semiconductors | AMD, INTC, AVGO, QCOM |
| AAPL | Apple | Tech Hardware | MSFT, GOOG, AMZN |
| MSFT | Microsoft | Software/Cloud | AAPL, GOOG, AMZN |
| GOOG | Alphabet | Advertising/AI | META, MSFT, AMZN |
| AMZN | Amazon | E-commerce/Cloud | MSFT, GOOG, SHOP |
| TSLA | Tesla | EV/Energy | RIVN, F, GM |
| META | Meta Platforms | Social/AI | GOOG, SNAP, PINS |
| AMD | Advanced Micro Devices | Semiconductors | NVDA, INTC, AVGO |
| AVGO | Broadcom | Semiconductors | NVDA, AMD, QCOM |
| CRM | Salesforce | SaaS | MSFT, ORCL, NOW |
| PLTR | Palantir | AI/Defense | SNOW, AI, BBAI |
| COIN | Coinbase | Crypto Exchange | — (crypto proxy) |
| SQ | Block (Square) | Fintech | PYPL, SOFI, AFRM |
| SHOP | Shopify | E-commerce | AMZN, WIX, BIGC |
| NET | Cloudflare | Cybersecurity | CRWD, ZS, PANW |
| SNOW | Snowflake | Data/AI | PLTR, DDOG, MDB |
| ARM | Arm Holdings | Semiconductors | NVDA, QCOM, AVGO |
| SMCI | Super Micro Computer | AI Hardware | DELL, HPE |
| LLY | Eli Lilly | Pharma/Biotech | NVO, ABBV, MRK |
| UBER | Uber | Mobility | LYFT, DASH |

#### Crypto (15)

| Symbol | Name | Category |
|--------|------|----------|
| BTC | Bitcoin | Store of value |
| ETH | Ethereum | Smart contract platform |
| SOL | Solana | Alt L1 |
| AVAX | Avalanche | Alt L1 |
| LINK | Chainlink | Oracle |
| DOT | Polkadot | Interoperability |
| MATIC | Polygon | L2 |
| ARB | Arbitrum | L2 |
| OP | Optimism | L2 |
| NEAR | NEAR Protocol | Alt L1 |
| SUI | Sui | Alt L1 |
| INJ | Injective | DeFi |
| RENDER | Render | AI/GPU |
| FET | Fetch.ai | AI |
| APT | Aptos | Alt L1 |

#### Commodities (5 — via ETF proxies)

| Symbol | Name | Commodity |
|--------|------|-----------|
| GLD | SPDR Gold Shares | Gold |
| SLV | iShares Silver Trust | Silver |
| USO | United States Oil Fund | Crude Oil |
| UNG | United States Natural Gas Fund | Natural Gas |
| CPER | United States Copper Index Fund | Copper |

#### REITs (5)

| Symbol | Name | Subsector |
|--------|------|-----------|
| VNQ | Vanguard Real Estate ETF | Broad REIT |
| O | Realty Income | Net Lease |
| AMT | American Tower | Cell Towers |
| PLD | Prologis | Industrial/Logistics |
| EQIX | Equinix | Data Centers |

#### Macro Indicators (5 — tracked but not ranked)

| Symbol/Metric | Name | Source |
|---------------|------|--------|
| SPY | S&P 500 ETF | yfinance |
| DXY | Dollar Index | yfinance |
| ^VIX | CBOE Volatility Index | yfinance |
| ^TNX | 10-Year Treasury Yield | yfinance |
| BTC.D | Bitcoin Dominance | CoinGecko |

### 7.2 Private Watchlist Board (5-10 startups)

User-defined. Track via Crunchbase Basic API + RSS news monitoring. Not ranked in the daily email — appears in the separate "Private Watchlist" section.

---

## 8. Build Phases & Timeline

### Phase 1 — Data Ingestion (Week 1-2)

**Goal:** All data flowing into Supabase.

- [ ] Set up Supabase project + create all tables from schema
- [ ] Implement RSS feed parser (Python feedparser + APScheduler) — 15+ sources
- [ ] Implement Finnhub data fetcher (stocks, news, forex)
- [ ] Implement CoinGecko data fetcher (crypto prices, volume, market cap)
- [ ] Implement yfinance data fetcher (historical prices, commodities, REITs, technical indicators)
- [ ] Implement Alpha Vantage fetcher (RSI, MACD, Bollinger Bands)
- [ ] Set up Scrapingdog account — validate with free 1,000 credits against 10 assets
- [ ] Implement X/Twitter scraper (Scrapingdog API → Supabase)
- [ ] Implement Reddit scraper (PRAW → Supabase)
- [ ] Implement GDELT event fetcher (REST API → Supabase)
- [ ] Implement SEC/CFTC/ESMA RSS fetcher
- [ ] Implement FRED API fetcher (interest rates, CPI, housing data)
- [ ] Set up Firecrawl account — implement full-text article extraction
- [ ] Populate `assets` table with full watchlist (50 public + initial private)

**Deliverable:** All raw data tables populated daily. Manual verification of data quality.

### Phase 2 — Analysis Engine (Week 3-4)

**Goal:** All 11 signals computed per asset per day.

- [ ] Build LLM sentiment pipeline (batch processing with Gemini Flash-Lite, structured output)
- [ ] Implement volume anomaly detection (z-score vs 20d median)
- [ ] Build correlation tracking (rolling 30d/90d Pearson matrix)
- [ ] Implement momentum/price regime scoring (RSI, MACD, price vs MA)
- [ ] Implement risk scoring module (volatility, liquidity, drawdown, market cap)
- [ ] Implement regulatory signal detector (keyword matching + LLM classification)
- [ ] Implement competitor peer comparison logic
- [ ] Implement GDELT → capital-flow mapping
- [ ] Implement catalyst freshness scoring
- [ ] Unit test each signal independently against known scenarios
- [ ] Write signal normalization (z-score per asset class)

**Deliverable:** `daily_signals` table populated correctly. Manual review of signal quality.

### Phase 3 — Scoring + Output (Week 5-6)

**Goal:** End-to-end pipeline producing a daily email.

- [ ] Implement composite scoring formula (sigmoid × confidence × investability)
- [ ] Implement hard filters (liquidity, market cap, regulatory red flags, data coverage)
- [ ] Build two-board ranking (public investable vs private watchlist)
- [ ] Build HTML email template (Jinja2, responsive design)
- [ ] Implement Resend email integration
- [ ] Set up Modal app with `@modal.cron("0 4 * * *")` trigger
- [ ] Configure Modal secrets (all API keys) and volume (persistent cache)
- [ ] Implement backtesting evaluator (check yesterday's picks vs actual returns)
- [ ] Build "Yesterday's Scorecard" section
- [ ] End-to-end integration test (full pipeline → email delivery)
- [ ] Log everything to `backtesting_log` table

**Deliverable:** Daily email arriving at 07:00 with top 10 ranked assets + scorecard.

### Phase 4 — Intelligence Layer (Week 7-8)

**Goal:** Self-improving system with advanced signals.

- [ ] Implement false-signal adjustment loop (dynamic weight recalculation)
- [ ] Implement per-asset-class weight tracking
- [ ] Build sentiment disagreement detector (news vs social divergence)
- [ ] Add options/open interest anomaly detection (where available via Finnhub)
- [ ] Implement social mention volume baseline + anomaly detection
- [ ] Build GDELT conflict intensity trend tracker (not just daily snapshot)
- [ ] Implement signal accuracy dashboard (Supabase or Airtable view)
- [ ] Tune hard filter thresholds based on first 30 days of data
- [ ] Document signal performance for each asset class

**Deliverable:** System self-adjusting weights. Accuracy dashboard live.

### Phase 5 — Calibration & Scale (Month 3+)

**Goal:** Prove signal quality, then upgrade infrastructure.

- [ ] 30-day review: Which signals actually predicted returns? Which are noise?
- [ ] Adjust asset watchlist (add/remove based on signal coverage quality)
- [ ] Evaluate: Does X data improve scores? If yes → consider official X API. If no → reduce volume.
- [ ] Evaluate: Would Twelve Data ($79/mo) simplify the market data layer enough to justify cost?
- [ ] Evaluate: Would CoinGecko Analyst ($129/mo) improve crypto signal quality?
- [ ] Consider adding FT/Bloomberg licensed feeds if premium news shows alpha improvement
- [ ] Scale to 100+ assets if system proves profitable
- [ ] Consider building a web dashboard (Next.js) for real-time monitoring

---

## 9. Budget

### 9.1 MVP Monthly Cost (Month 1-2)

| Item | Provider | Monthly Cost |
|------|----------|-------------|
| X/Twitter scraping | Scrapingdog Lite (200K credits) | $40.00 |
| Article full-text extraction | Firecrawl Hobby (3K credits) | $16.00 |
| LLM sentiment analysis | Gemini Flash-Lite (~500-1K items/day) | ~$0.30 |
| Reddit | PRAW (official, free) | $0.00 |
| RSS feeds | Python feedparser | $0.00 |
| Stock data | Finnhub free + yfinance | $0.00 |
| Crypto data | CoinGecko free (10K calls/mo) | $0.00 |
| Commodity/REIT data | yfinance ETF proxies | $0.00 |
| Technical indicators | Alpha Vantage free (25 calls/day) | $0.00 |
| Geopolitical | GDELT 2.0 (free/open) | $0.00 |
| Regulatory | SEC/CFTC/ESMA RSS (free) | $0.00 |
| Macro/RE | FRED API (free) | $0.00 |
| Database | Supabase free tier | $0.00 |
| Email delivery | Resend free tier (3K emails/mo) | $0.00 |
| Orchestration + Hosting | Modal free tier ($30/mo credit, ~$3 actual usage) | $0.00 |
| **TOTAL** | | **~$56.30/mo** |

### 9.2 Scaled Monthly Cost (Month 3+ if validated)

| Upgrade | Provider | Monthly Cost |
|---------|----------|-------------|
| All MVP costs | — | $56.30 |
| Market data unification | Twelve Data Grow | +$79.00 |
| Crypto enrichment | CoinGecko Analyst | +$129.00 |
| Higher X volume | Scrapingdog Standard ($90/mo, 1M credits) | +$50.00 |
| Higher Firecrawl volume | Firecrawl Standard ($99/mo, 100K credits) | +$83.00 |
| Self-hosted LLM sentiment (optional) | Modal GPU (T4 ~$0.59/hr, ~2hr/mo) | +$1.20 |
| Premium news (if alpha proven) | FT/Bloomberg licensing | TBD |
| **TOTAL (scaled)** | | **~$399/mo** |

Only upgrade when the MVP proves that better data actually improves prediction accuracy.

---

## 10. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Scrapingdog X scraper goes down or degrades | MEDIUM | PAYG credits as buffer. If persistent, evaluate official X API or Apify fallback. Independent benchmarks show 36% general success rate — validate X-specific reliability during Phase 1. |
| Twitter changes anti-scraping measures | MEDIUM | Scrapingdog handles proxy/CAPTCHA. If they can't keep up, official X API is the fallback. Budget $0 for this initially. |
| API rate limits hit | LOW | Batch requests, cache aggressively, stagger calls across 04:00-05:00 window. All free-tier limits are well above our volume. |
| LLM sentiment hallucination | MEDIUM | Structured output schema constrains responses. Validate scores in range. Cross-reference LLM scores with pre-scored Finnhub/FMP sentiment. Flag disagreements. |
| False positives overwhelm signal | HIGH initially | Expected. False-signal adjustment loop self-corrects within 30 days. Start with conservative base weights. |
| Data staleness | LOW | RSS polled every 30 min. Market data at daily close. X scraped at fixed daily time. GDELT updates every 15 min. |
| Overfitting to recent data | MEDIUM | Use rolling windows (30d for signals, 90d for backtesting). Clamp weight adjustments (0.5x-2.0x). |
| Single-asset-class dominance | LOW | Cross-sectional normalization within each class. Crypto volatility won't drown out stock signals. |
| Supabase free tier limits | LOW | Free tier: 500MB database, 2GB bandwidth. Our daily data is ~10-20MB/day. Good for months. |
| Modal free tier exceeded | LOW | $30/mo free credit, we use ~$3. If pipeline grows to require GPU or higher volume, Modal Team plan at $250/mo unlocks unlimited crons and 1000 containers — but that's a scale problem, not an MVP problem. |
| Legal/compliance risk | LOW | No LinkedIn scraping. No Investing.com scraping. Reddit via official API. X via paid API (Scrapingdog handles proxy compliance). RSS feeds are public. GDELT is open. |

---

## 11. Rules — What We Do NOT Do

1. **No LinkedIn scraping.** Their ToS prohibits third-party crawlers. If we need startup data, use Crunchbase.
2. **No Investing.com scraping.** Their ToS explicitly prohibits data mining, bots, and automated extraction.
3. **No twikit/twscrape/open-source X scrapers in production.** Account ban risk and 10-15 hours/month maintenance make them unsuitable for a daily automated pipeline.
4. **No Bright Data for X.** $500/mo minimum is absurd for our volume.
5. **No ScrapingBee or ScraperAPI for X.** They're general scrapers requiring HTML parsing — defeats the purpose.
6. **No ranking startups alongside public assets.** Two separate boards. Different liquidity, price discovery, and execution profiles.
7. **No FT/Bloomberg licensing until proven alpha.** Start with free RSS feeds. Upgrade only when backtesting proves premium sources improve hit rate enough to justify cost.
8. **No premature optimization of market data.** Free-tier patchwork first. Twelve Data ($79/mo) only after validating the system produces useful signals.
9. **No manual intervention in scoring.** The system ranks by formula. Human override defeats the purpose. Trust the math, improve the math.
10. **No shipping without backtesting.** Every daily email includes yesterday's scorecard. If 30-day precision drops below 50%, pause and recalibrate before continuing.

---

*Sentinel v1.0 — Built lean at ~$56/month on Modal's serverless Python infrastructure. Designed to scale to $400+/month when signal quality is proven. The cheapest path to a serious, durable investment intelligence system.*
