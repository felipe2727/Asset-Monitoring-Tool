"""
Composite scoring engine.

Formula:
  RawScore(a,t) = Σ [ w_k(t) × Z_k(a,t) ]   ← z-scores within asset class first
  FinalScore    = 100 × sigmoid(RawScore) × Confidence × Investability

Two-stage: public investable board (stocks, crypto, commodities, REITs).
Hard filters applied before ranking.
"""
import logging
import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from sentinel.config import (
    BASE_WEIGHTS, MIN_MARKET_CAP_STOCK, MIN_MARKET_CAP_CRYPTO,
    MIN_DATA_SOURCES, get_active_assets,
)
from sentinel.database.client import get_latest_weights

logger = logging.getLogger(__name__)

SIGNAL_KEYS = [
    "news_sentiment", "social_sentiment", "sentiment_shift",
    "volume_anomaly", "momentum_score", "correlation_divergence",
    "risk_adjusted_liquidity", "regulatory_signal", "competitor_edge",
    "geopolitical_flow", "catalyst_freshness",
]


# ─────────────────────────────────────────────────────────────────────────────
# Hard filters
# ─────────────────────────────────────────────────────────────────────────────

def _check_investability(signal_row: dict, market_row: Optional[dict]) -> float:
    """
    Returns 0.0 if asset fails any hard filter, else 0.3-1.0 based on data quality.
    """
    if not market_row:
        return 0.3  # heavy penalty for zero market data

    asset_class = signal_row.get("_asset_class", "stock")
    market_cap  = market_row.get("market_cap") or 0
    symbol      = signal_row["symbol"]

    # Min market cap
    if asset_class == "stock" and market_cap and market_cap < MIN_MARKET_CAP_STOCK:
        logger.debug("  Filter: %s fails min market cap (stock)", symbol)
        return 0.0
    if asset_class == "crypto" and market_cap and market_cap < MIN_MARKET_CAP_CRYPTO:
        logger.debug("  Filter: %s fails min market cap (crypto)", symbol)
        return 0.0

    # Active SEC enforcement = disqualify
    reg_score = signal_row.get("regulatory_signal", 0.0)
    if reg_score < -0.8:
        logger.debug("  Filter: %s severe regulatory red flag", symbol)
        return 0.0

    # Data coverage check — count ALL non-zero signals
    data_sources = sum(
        1 for k in SIGNAL_KEYS
        if abs(signal_row.get(k, 0.0)) > 0.001
    )
    if data_sources < 3:
        logger.debug("  Filter: %s low data coverage (%d/11 signals)", symbol, data_sources)
        investability = 0.4 + 0.05 * data_sources  # 0.4 to 0.55
    else:
        investability = 0.5 + 0.05 * min(data_sources, 10)  # 0.65 to 1.0

    # Data completeness multiplier: penalize missing market data fields
    populated = sum(1 for k in ["rsi_14", "macd_signal", "bollinger_position",
                                 "volatility_30d", "volume_zscore", "market_cap"]
                    if market_row.get(k) is not None)
    completeness = 0.5 + 0.5 * (populated / 6.0)  # 0.5 to 1.0
    investability *= completeness

    return min(1.0, investability)


# ─────────────────────────────────────────────────────────────────────────────
# Confidence score
# ─────────────────────────────────────────────────────────────────────────────

def _compute_confidence(signal_row: dict, articles: list[dict], symbol: str) -> float:
    """
    Confidence = source_breadth × source_quality × freshness
    """
    relevant_articles = [a for a in articles if symbol in a.get("asset_symbols", [])]

    # Source breadth: how many independent sources
    sources = set(a.get("source", "") for a in relevant_articles)
    breadth = min(1.0, len(sources) / 5.0)   # 5+ independent sources = max

    # Source quality: weighted average tier
    if relevant_articles:
        quality = float(np.mean([a.get("source_tier", 0.5) for a in relevant_articles]))
    else:
        quality = 0.4  # low confidence if no news

    # Freshness: based on catalyst_freshness signal
    freshness = signal_row.get("catalyst_freshness", 0.3)

    confidence = 0.4 * breadth + 0.35 * quality + 0.25 * freshness
    return float(np.clip(confidence, 0.1, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Z-score normalisation per asset class
# ─────────────────────────────────────────────────────────────────────────────

def _zscore_within_class(
    signal_rows: list[dict],
    signal_key: str,
    asset_class: str,
) -> dict[str, float]:
    """
    Computes z-score of signal_key within an asset class.
    Returns {symbol: z_score}.
    """
    class_rows = [r for r in signal_rows if r.get("_asset_class") == asset_class]
    if len(class_rows) < 3:
        # Too few members for stable z-scores — return raw values
        return {r["symbol"]: r.get(signal_key, 0.0) for r in class_rows}

    values = np.array([r.get(signal_key, 0.0) for r in class_rows], dtype=float)
    mean   = np.mean(values)
    std    = np.std(values)

    if std < 1e-9:
        return {r["symbol"]: 0.0 for r in class_rows}

    return {
        row["symbol"]: float((row.get(signal_key, 0.0) - mean) / std)
        for row in class_rows
    }


# ─────────────────────────────────────────────────────────────────────────────
# Sigmoid
# ─────────────────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# ─────────────────────────────────────────────────────────────────────────────
# Main scoring function
# ─────────────────────────────────────────────────────────────────────────────

def compute_scores(
    signal_rows: list[dict],   # one per asset, output of signals.compute_all_signals
    market_data: dict[str, dict],
    articles: list[dict],
) -> list[dict]:
    """
    Takes raw signal rows, normalises within asset class, applies weights,
    computes final scores, applies hard filters, and returns ranked list.

    Returns list of score dicts with final_score and rank.
    """
    if not signal_rows:
        return []

    # Attach asset metadata to each row
    asset_meta = {a.symbol: a for a in get_active_assets()}
    for row in signal_rows:
        asset = asset_meta.get(row["symbol"])
        row["_asset_class"] = asset.asset_class if asset else "stock"
        row["_benchmark"]   = asset.benchmark if asset else "SPY"
        row["_peers"]       = asset.peers if asset else []

    asset_classes = list(set(r["_asset_class"] for r in signal_rows))

    # ── Step 1: Z-score each signal within asset class ─────────────────────
    z_scores: dict[str, dict[str, float]] = {r["symbol"]: {} for r in signal_rows}

    for signal_key in SIGNAL_KEYS:
        for ac in asset_classes:
            class_z = _zscore_within_class(signal_rows, signal_key, ac)
            for sym, z in class_z.items():
                z_scores[sym][signal_key] = z

    # ── Step 2: Load weights (dynamic if available, else base) ─────────────
    weights_by_class: dict[str, dict[str, float]] = {}
    for ac in asset_classes:
        weights_by_class[ac] = get_latest_weights(ac)

    # ── Step 3: Compute raw score and final score per asset ─────────────────
    scored: list[dict] = []

    for row in signal_rows:
        sym = row["symbol"]
        ac  = row["_asset_class"]
        weights = weights_by_class.get(ac, BASE_WEIGHTS)
        mkt = market_data.get(sym)

        # Weighted sum of z-scores
        z = z_scores.get(sym, {})
        raw_score = sum(weights.get(k, 0.0) * z.get(k, 0.0) for k in SIGNAL_KEYS)

        # Confidence and investability
        confidence    = _compute_confidence(row, articles, sym)
        investability = _check_investability(row, mkt)

        if investability == 0.0:
            final_score = 0.0
        else:
            final_score = 100.0 * _sigmoid(raw_score) * confidence * investability

        # Top signal drivers for email
        signal_contributions = {
            k: weights.get(k, 0.0) * z.get(k, 0.0)
            for k in SIGNAL_KEYS
        }
        top_signals = sorted(signal_contributions.items(), key=lambda x: abs(x[1]), reverse=True)[:3]

        scored.append({
            **row,
            "raw_score":     raw_score,
            "confidence":    confidence,
            "investability": investability,
            "final_score":   final_score,
            "_top_signals":  dict(top_signals),
            "_z_scores":     z,
        })

    # ── Step 4: Filter disqualified, rank remaining ─────────────────────────
    eligible   = [s for s in scored if s["investability"] > 0.0]
    ineligible = [s for s in scored if s["investability"] == 0.0]

    eligible.sort(key=lambda x: x["final_score"], reverse=True)

    for rank, row in enumerate(eligible, start=1):
        row["rank"] = rank

    for row in ineligible:
        row["rank"] = None

    all_scored = eligible + ineligible

    logger.info(
        "Scoring complete: %d eligible assets, top score=%.1f (%s)",
        len(eligible),
        eligible[0]["final_score"] if eligible else 0,
        eligible[0]["symbol"] if eligible else "N/A",
    )

    return all_scored


def get_top10(scored: list[dict]) -> list[dict]:
    """Returns the top 10 ranked eligible assets."""
    eligible = [s for s in scored if s.get("rank") is not None]
    return sorted(eligible, key=lambda x: x["rank"])[:10]
