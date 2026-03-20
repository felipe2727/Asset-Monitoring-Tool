"""
Signal computation — all 11 signals from the plan, computed per asset per day.
Each signal returns a float typically in range [-1, +1] or [0, 100].
The scoring engine normalises these into z-scores per asset class.
"""
import logging
import math
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from sentinel.config import (
    get_active_assets, BASE_WEIGHTS, SOURCE_TIERS,
    GEOPOLITICAL_KEYWORDS, REGULATORY_KEYWORDS, EXCLUSION_KEYWORDS,
)
from sentinel.database.client import get_price_history, get_latest_weights

logger = logging.getLogger(__name__)

# Legacy flat list (kept for backward compat, but tiered version is preferred)
REGULATORY_KEYWORDS_LIST = [
    "sec ", "regulation", "ban ", "approved", "etf filing", "cftc", "mica",
    "stablecoin", "executive order", "enforcement", "fine ", "settlement",
    "esma", "compliance", "lawsuit", "subpoena", "penalty",
]


def _classify_text_threat(text: str) -> tuple[float, str]:
    """
    Classifies text against the tiered geopolitical keyword taxonomy.
    Returns (weight, tier_name) of the highest-severity match, or (0.0, "none").
    """
    text_lower = text.lower()

    # Check exclusion list first
    if any(kw in text_lower for kw in EXCLUSION_KEYWORDS):
        return 0.0, "excluded"

    # Check tiers from highest to lowest severity
    for tier_name in ("critical", "high", "medium", "low"):
        tier = GEOPOLITICAL_KEYWORDS.get(tier_name, {})
        keywords = tier.get("keywords", [])
        if any(kw in text_lower for kw in keywords):
            return tier.get("weight", 0.2), tier_name

    return 0.0, "none"


def _classify_regulatory_text(text: str) -> tuple[float, str]:
    """
    Classifies text against the tiered regulatory keyword taxonomy.
    Returns (weight, tier_name) of the highest-severity match, or (0.0, "none").
    """
    text_lower = text.lower()

    # Check exclusion list first
    if any(kw in text_lower for kw in EXCLUSION_KEYWORDS):
        return 0.0, "excluded"

    for tier_name in ("critical", "high", "medium", "low"):
        tier = REGULATORY_KEYWORDS.get(tier_name, {})
        keywords = tier.get("keywords", [])
        if any(kw in text_lower for kw in keywords):
            return tier.get("weight", 0.2), tier_name

    # Fallback to legacy flat list
    if any(kw in text_lower for kw in REGULATORY_KEYWORDS_LIST):
        return 0.2, "legacy"

    return 0.0, "none"


# ─────────────────────────────────────────────────────────────────────────────
# Signal 1: News Sentiment
# ─────────────────────────────────────────────────────────────────────────────

def compute_news_sentiment(articles: list[dict], symbol: str) -> float:
    """
    NewsSentiment = 0.5 × CurrentSentiment + 0.3 × SentimentAcceleration + 0.2 × SourceConcentration
    """
    relevant = [a for a in articles if symbol in a.get("asset_symbols", [])]
    if not relevant:
        return 0.0

    # Current sentiment (weighted by source tier)
    weighted_scores = []
    sources_seen: set[str] = set()
    for art in relevant:
        score = art.get("sentiment_score", 0.0)
        conf  = art.get("sentiment_confidence", 0.5)
        tier  = art.get("source_tier", 0.5)
        if conf > 0.2:
            weighted_scores.append(score * tier)
            sources_seen.add(art.get("source", ""))

    current_sentiment = float(np.mean(weighted_scores)) if weighted_scores else 0.0

    # Source concentration penalty (reward diversity, penalise single-source)
    source_concentration = min(1.0, len(sources_seen) / 5.0)  # 5+ sources = max score

    # Sentiment acceleration: would need historical data; default to current if not available
    sentiment_acceleration = current_sentiment  # simplified for early runs

    score = (
        0.5 * current_sentiment +
        0.3 * sentiment_acceleration +
        0.2 * source_concentration
    )
    return float(np.clip(score, -1.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Signal 2: Social Sentiment
# ─────────────────────────────────────────────────────────────────────────────

def compute_social_sentiment(
    tweets: list[dict],
    reddit_posts: list[dict],
    symbol: str,
) -> float:
    """
    SocialSentiment = 0.4 × CurrentSocial + 0.3 × SocialMomentum + 0.2 × MentionVolume + 0.1 × InfluencerWeight
    """
    rel_tweets  = [t for t in tweets  if t.get("asset_symbol") == symbol
                   or symbol in t.get("_mentioned_assets", [])]
    rel_reddit  = [p for p in reddit_posts if p.get("asset_symbol") == symbol
                   or symbol in p.get("_mentioned_assets", [])]

    if not rel_tweets and not rel_reddit:
        return 0.0

    # Current social sentiment (weighted by engagement)
    tweet_scores: list[float] = []
    for t in rel_tweets:
        score = t.get("sentiment_score", 0.0)
        conf  = t.get("sentiment_confidence", 0.3)
        # Verified accounts get more weight
        weight = 0.7 if t.get("author_verified") else 0.2
        engagement = 1 + math.log1p(t.get("likes", 0) + t.get("retweets", 0))
        if conf > 0.2:
            tweet_scores.append(score * weight * min(engagement / 10, 2.0))

    reddit_scores: list[float] = []
    for p in rel_reddit:
        score = p.get("sentiment_score", 0.0)
        conf  = p.get("sentiment_confidence", 0.3)
        engagement = 1 + math.log1p(p.get("score", 0) + p.get("num_comments", 0))
        if conf > 0.2:
            reddit_scores.append(score * min(engagement / 50, 2.0))

    all_scores = tweet_scores + reddit_scores
    current_social = float(np.mean(all_scores)) if all_scores else 0.0

    # Mention volume (z-score approximation — raw count normalised)
    mention_count = len(rel_tweets) + len(rel_reddit)
    mention_volume = min(1.0, mention_count / 20.0)  # 20+ mentions = max

    # Influencer weight bonus
    verified_tweets = [t for t in rel_tweets if t.get("author_verified")]
    influencer_bonus = min(0.5, len(verified_tweets) * 0.1)

    score = (
        0.4 * current_social +
        0.3 * current_social +    # momentum (same as current for early runs)
        0.2 * mention_volume +
        0.1 * influencer_bonus
    )
    return float(np.clip(score, -1.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Signal 3: Sentiment Shift
# ─────────────────────────────────────────────────────────────────────────────

def compute_sentiment_shift(
    news_sentiment: float,
    social_sentiment: float,
    prev_news_sentiment: float = 0.0,
    prev_social_sentiment: float = 0.0,
) -> float:
    """
    SentimentShift = weighted_avg(24h_shift, news_vs_social_divergence)
    Captures momentum in sentiment — the derivative, not absolute level.
    """
    shift_24h = (news_sentiment - prev_news_sentiment + social_sentiment - prev_social_sentiment) / 2

    # Divergence signal: when trusted news and social disagree strongly
    divergence = abs(news_sentiment - social_sentiment)
    # Direction: if news is higher → trust news; if social is higher → mild positive (FOMO risk)
    if news_sentiment > social_sentiment:
        divergence_signal = divergence * 0.5   # news leading social = opportunity
    else:
        divergence_signal = -divergence * 0.3  # social leading news = potential noise

    score = 0.7 * shift_24h + 0.3 * divergence_signal
    return float(np.clip(score, -1.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Signal 4: Volume Anomaly
# ─────────────────────────────────────────────────────────────────────────────

def compute_volume_anomaly(market_row: Optional[dict]) -> float:
    """
    VolumeAnomaly = z_score(today_volume, rolling_20d_median, rolling_20d_std)
    Score: z < 1 = low, 1-2 = moderate, 2-3 = strong, > 3 = extreme.
    """
    if not market_row:
        return 0.0

    z = market_row.get("volume_zscore")
    if z is None:
        return 0.0

    # Normalize z-score to [-1, 1] range: z=3 → 1.0, z=-3 → -1.0
    return float(np.clip(z / 3.0, -1.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Signal 5: Price Regime / Momentum
# ─────────────────────────────────────────────────────────────────────────────

def compute_momentum_score(market_row: Optional[dict]) -> float:
    """
    MomentumScore = 0.4 × price_vs_20dma + 0.3 × RSI_position + 0.3 × MACD_signal
    """
    if not market_row:
        return 0.0

    rsi    = market_row.get("rsi_14")
    macd   = market_row.get("macd_signal")
    bb_pos = market_row.get("bollinger_position")

    scores: list[float] = []
    weights: list[float] = []

    # RSI: 30-50 rising = strong oversold recovery; 50-70 = healthy; >70 = overbought
    if rsi is not None:
        if rsi < 30:
            rsi_score = -0.5    # oversold (could recover, but currently negative momentum)
        elif rsi < 50:
            rsi_score = 0.3     # recovering
        elif rsi < 70:
            rsi_score = 0.6     # healthy
        else:
            rsi_score = -0.2    # overbought
        scores.append(rsi_score)
        weights.append(0.35)

    # MACD histogram: positive = bullish crossover
    if macd is not None:
        macd_score = np.clip(macd / 5.0, -1.0, 1.0)
        scores.append(float(macd_score))
        weights.append(0.35)

    # Bollinger position: 0.5 = middle band; >0.8 = near upper (momentum); <0.2 = near lower
    if bb_pos is not None:
        bb_score = (bb_pos - 0.5) * 2.0  # map 0-1 to -1..+1
        scores.append(float(bb_score))
        weights.append(0.30)

    if not scores:
        return 0.0

    weighted = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
    return float(np.clip(weighted, -1.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Signal 6: Correlation Divergence
# ─────────────────────────────────────────────────────────────────────────────

def compute_correlation_divergence(
    symbol: str,
    benchmark: str,
    market_data: dict[str, dict],
) -> float:
    """
    CorrelationScore = |current_30d_correlation - historical_90d_correlation|
    Needs price history from DB. Returns 0 if insufficient data.
    """
    sym_history   = get_price_history(symbol, days=90)
    bench_history = get_price_history(benchmark, days=90)

    if len(sym_history) < 30 or len(bench_history) < 30:
        return 0.0  # bootstrap: insufficient history

    sym_closes   = pd.Series([r["close"] for r in sym_history if r["close"]]).dropna()
    bench_closes = pd.Series([r["close"] for r in bench_history if r["close"]]).dropna()

    min_len = min(len(sym_closes), len(bench_closes))
    if min_len < 20:
        return 0.0

    sym_ret   = sym_closes.pct_change().dropna()
    bench_ret = bench_closes.pct_change().dropna()
    min_len   = min(len(sym_ret), len(bench_ret))

    if min_len < 20:
        return 0.0

    sym_ret   = sym_ret.iloc[-min_len:]
    bench_ret = bench_ret.iloc[-min_len:]

    corr_30d = sym_ret.tail(30).corr(bench_ret.tail(30))
    corr_90d = sym_ret.corr(bench_ret)

    divergence = float(corr_90d - corr_30d)

    # Positive divergence (less correlated to benchmark recently) can be bullish
    return float(np.clip(divergence, -1.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Signal 7: Risk-Adjusted Liquidity (inverted — lower risk = higher score)
# ─────────────────────────────────────────────────────────────────────────────

def compute_risk_adjusted_liquidity(market_row: Optional[dict], asset_class: str) -> float:
    """
    Risk = 0.40 × Volatility + 0.25 × Illiquidity + 0.20 × Drawdown + 0.15 × SmallCapPenalty
    RiskAdj (0-100) = 100 - Risk.
    Returned as 0-1 float (divide by 100).
    """
    if not market_row:
        return 0.5  # neutral if no data

    risk_score = 0.0

    # Volatility component (0-100)
    vol = market_row.get("volatility_30d")
    if vol is not None:
        vol_pct = min(100, vol)  # already in % (annualized)
        risk_score += 0.40 * vol_pct

    # Illiquidity proxy: based on average daily volume vs market cap
    market_cap = market_row.get("market_cap") or 0
    avg_vol    = market_row.get("avg_volume_20d") or 0
    close      = market_row.get("close") or 1
    adtv       = avg_vol * close  # Average Daily Trading Value

    if market_cap > 0 and adtv > 0:
        turnover_ratio = adtv / market_cap
        # Low turnover = illiquid. Normalize 0-100 (0.001 ratio = 100% illiquid)
        illiquidity_pct = max(0, 100 - turnover_ratio * 10000)
        risk_score += 0.25 * illiquidity_pct
    else:
        risk_score += 0.25 * 50  # neutral if unknown

    # Small-cap penalty
    if asset_class == "stock" and market_cap < 1e9:
        small_cap_penalty = max(0, 100 - market_cap / 1e7)
        risk_score += 0.15 * small_cap_penalty
    elif asset_class == "crypto" and market_cap < 5e8:
        small_cap_penalty = max(0, 100 - market_cap / 5e6)
        risk_score += 0.15 * small_cap_penalty

    risk_adj = max(0.0, 100.0 - risk_score) / 100.0
    return float(np.clip(risk_adj, 0.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Signal 8: Regulatory Signal
# ─────────────────────────────────────────────────────────────────────────────

def compute_regulatory_signal(articles: list[dict], symbol: str, asset_class: str) -> float:
    """
    RegulatoryScore from SEC/CFTC RSS + news filtered for tiered regulatory keywords.
    Uses severity-weighted scoring (critical events count 5x more than low events).
    Returns -1 (strongly negative) to +1 (strongly positive).
    """
    relevant_regulatory: list[tuple[dict, float]] = []  # (article, severity_weight)

    for art in articles:
        if symbol not in art.get("asset_symbols", []) and symbol not in art.get("title", ""):
            # Include broad crypto regulatory news for crypto assets
            if asset_class == "crypto":
                text = (art.get("title", "") + art.get("summary", "")).lower()
                if not any(kw in text for kw in ["crypto", "bitcoin", "ethereum", "defi", "stablecoin"]):
                    continue
            # Include broad commodity regulatory news for commodity assets
            elif asset_class == "commodity":
                text = (art.get("title", "") + art.get("summary", "")).lower()
                if not any(kw in text for kw in [
                    "oil", "crude", "opec", "gold", "silver", "copper",
                    "natural gas", "commodity", "mining", "tariff",
                    "sanctions", "strategic reserve", "eia", "inventory",
                ]):
                    continue
            else:
                continue

        text = art.get("title", "") + " " + art.get("summary", "")
        reg_weight, reg_tier = _classify_regulatory_text(text)

        if reg_tier == "excluded":
            continue

        if reg_weight > 0 or art.get("_is_regulatory"):
            # Use the higher of tiered weight or default 0.2 for _is_regulatory
            weight = max(reg_weight, 0.2 if art.get("_is_regulatory") else 0.0)
            relevant_regulatory.append((art, weight))

    if not relevant_regulatory:
        return 0.0

    # Score each regulatory event (severity-weighted)
    weighted_scores: list[float] = []
    total_weight = 0.0

    for art, severity_weight in relevant_regulatory:
        sentiment = art.get("sentiment_score", 0.0)
        meta = art.get("_sentiment_meta", {})

        if meta.get("is_regulatory"):
            rd = meta.get("regulatory_direction", "neutral")
            if rd == "positive":
                event_score = 1.0
            elif rd == "negative":
                event_score = -1.0
            elif rd == "neutral":
                event_score = 0.0
            else:
                event_score = sentiment
        else:
            event_score = sentiment

        weighted_scores.append(event_score * severity_weight)
        total_weight += severity_weight

    if total_weight == 0:
        return 0.0

    score = sum(weighted_scores) / total_weight
    return float(np.clip(score, -1.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Signal 9: Competitor Relative Edge
# ─────────────────────────────────────────────────────────────────────────────

def compute_competitor_edge(
    symbol: str,
    peers: list[str],
    articles: list[dict],
    market_data: dict[str, dict],
) -> float:
    """
    CompetitorScore = (own_positive - peer_avg_positive) - (own_negative - peer_avg_negative)
    """
    if not peers:
        return 0.0

    def _asset_sentiment(sym: str) -> float:
        rel = [a for a in articles if sym in a.get("asset_symbols", [])]
        if not rel:
            return 0.0
        scores = [a.get("sentiment_score", 0.0) for a in rel if a.get("sentiment_confidence", 0) > 0.2]
        return float(np.mean(scores)) if scores else 0.0

    own_sentiment  = _asset_sentiment(symbol)
    peer_sentiments = [_asset_sentiment(p) for p in peers]
    peer_avg        = float(np.mean(peer_sentiments)) if peer_sentiments else 0.0

    sentiment_edge = own_sentiment - peer_avg

    # Also check relative price performance vs peers
    own_close  = (market_data.get(symbol) or {}).get("close") or 0
    own_change = (market_data.get(symbol) or {}).get("_price_change_24h") or 0

    peer_changes = [
        (market_data.get(p) or {}).get("_price_change_24h") or 0
        for p in peers
    ]
    peer_avg_change = float(np.mean(peer_changes)) if peer_changes else 0
    price_edge = (own_change - peer_avg_change) / 10.0  # normalize by 10%

    score = 0.6 * sentiment_edge + 0.4 * price_edge
    return float(np.clip(score, -1.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Signal 10: Geopolitical Capital-Flow
# ─────────────────────────────────────────────────────────────────────────────
# (computation delegated to gdelt.compute_geopolitical_score)

# ─────────────────────────────────────────────────────────────────────────────
# Signal 11: Catalyst Freshness / Source Quality
# ─────────────────────────────────────────────────────────────────────────────

def compute_catalyst_freshness(articles: list[dict], symbol: str) -> float:
    """
    CatalystScore = recency_weight × source_tier_weight × uniqueness
    Exponential decay: signal from 2h ago scores 5x higher than 48h ago.
    """
    relevant = [a for a in articles if symbol in a.get("asset_symbols", [])]
    if not relevant:
        return 0.0

    now = datetime.utcnow()
    total_score = 0.0
    sources_reporting: set[str] = set()

    for art in relevant:
        # Recency decay
        try:
            pub = datetime.fromisoformat(art.get("published_at", "").replace("Z", ""))
            hours_ago = (now - pub).total_seconds() / 3600
        except Exception:
            hours_ago = 12.0

        recency = math.exp(-hours_ago / 12.0)  # half-life of 12 hours

        # Source tier
        tier = art.get("source_tier", 0.5)

        # Sentiment confidence
        conf = art.get("sentiment_confidence", 0.5)

        total_score += recency * tier * conf
        sources_reporting.add(art.get("source", ""))

    # Uniqueness bonus: first-mover signals (few sources = higher alpha potential)
    uniqueness = 1.0 if len(sources_reporting) == 1 else min(1.0, 2.0 / len(sources_reporting))

    raw = total_score * uniqueness
    return float(np.clip(raw, 0.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Master signal computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_all_signals(
    symbol: str,
    asset_class: str,
    benchmark: str,
    peers: list[str],
    tweets: list[dict],
    reddit_posts: list[dict],
    articles: list[dict],
    market_data: dict[str, dict],
    gdelt_events: list[dict],
    prediction_events: list[dict] | None = None,
    disaster_events: list[dict] | None = None,
    acled_events: list[dict] | None = None,
) -> dict:
    """
    Computes all 11 signals for one asset and returns a dict ready for DB insertion.
    Now incorporates prediction markets, disaster events, and ACLED conflict data
    into the geopolitical_flow and regulatory_signal computations.
    """
    from sentinel.ingestion.gdelt import compute_geopolitical_score
    from sentinel.ingestion.polymarket import compute_prediction_market_signal
    from sentinel.ingestion.disasters import compute_disaster_signal
    from sentinel.ingestion.acled import compute_conflict_signal

    mkt = market_data.get(symbol)

    news_s    = compute_news_sentiment(articles, symbol)
    social_s  = compute_social_sentiment(tweets, reddit_posts, symbol)
    shift_s   = compute_sentiment_shift(news_s, social_s)
    volume_s  = compute_volume_anomaly(mkt)
    momentum_s = compute_momentum_score(mkt)
    corr_s    = compute_correlation_divergence(symbol, benchmark, market_data)
    risk_s    = compute_risk_adjusted_liquidity(mkt, asset_class)
    reg_s     = compute_regulatory_signal(articles, symbol, asset_class)
    comp_s    = compute_competitor_edge(symbol, peers, articles, market_data)
    fresh_s   = compute_catalyst_freshness(articles, symbol)

    # ── Enhanced geopolitical_flow: combine GDELT + ACLED + Polymarket + disasters ──
    gdelt_score = compute_geopolitical_score(gdelt_events, symbol)

    # Prediction market signal (regulatory + geopolitical)
    pred_score = compute_prediction_market_signal(prediction_events or [], symbol)

    # Disaster/environmental signal
    disaster_score = compute_disaster_signal(disaster_events or [], symbol)

    # ACLED conflict signal
    conflict_score = compute_conflict_signal(acled_events or [], symbol)

    # Weighted combination: GDELT (0.3) + ACLED (0.3) + Prediction Markets (0.2) + Disasters (0.2)
    geo_components = []
    geo_weights = []

    if gdelt_score != 0.0:
        geo_components.append(gdelt_score)
        geo_weights.append(0.3)
    if conflict_score != 0.0:
        geo_components.append(conflict_score)
        geo_weights.append(0.3)
    if pred_score != 0.0:
        geo_components.append(pred_score)
        geo_weights.append(0.2)
    if disaster_score != 0.0:
        geo_components.append(disaster_score)
        geo_weights.append(0.2)

    if geo_components:
        total_weight = sum(geo_weights)
        geo_s = sum(c * w for c, w in zip(geo_components, geo_weights)) / total_weight
        geo_s = float(np.clip(geo_s, -1.0, 1.0))
    else:
        geo_s = 0.0

    # ── Enhance regulatory signal with prediction market data ──
    if pred_score != 0.0 and reg_s != 0.0:
        # Blend: 70% article-based, 30% prediction-market-based
        reg_s = 0.7 * reg_s + 0.3 * pred_score
        reg_s = float(np.clip(reg_s, -1.0, 1.0))

    # ── Enhance volume_anomaly for energy assets with EIA data ──
    if mkt and mkt.get("_eia"):
        eia = mkt["_eia"]
        inv_change = eia.get("inventory_change", 0)
        if inv_change != 0:
            # Inventory draw (negative change) = bullish for USO/UNG
            # Inventory build (positive change) = bearish
            eia_signal = -inv_change / 5000.0  # normalize: 5M barrel change -> +-1.0
            eia_signal = float(np.clip(eia_signal, -0.5, 0.5))
            # Blend with existing volume signal
            volume_s = 0.7 * volume_s + 0.3 * eia_signal
            volume_s = float(np.clip(volume_s, -1.0, 1.0))

    today = date.today().isoformat()

    return {
        "symbol":                  symbol,
        "date":                    today,
        "news_sentiment":          news_s,
        "social_sentiment":        social_s,
        "sentiment_shift":         shift_s,
        "volume_anomaly":          volume_s,
        "momentum_score":          momentum_s,
        "correlation_divergence":  corr_s,
        "risk_adjusted_liquidity": risk_s,
        "regulatory_signal":       reg_s,
        "competitor_edge":         comp_s,
        "geopolitical_flow":       geo_s,
        "catalyst_freshness":      fresh_s,
        "_market_data":            mkt,  # pass-through for scoring engine
    }
