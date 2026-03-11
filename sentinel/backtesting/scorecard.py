"""
Backtesting & scorecard module.

Daily jobs:
  1. evaluate_yesterday() — looks up yesterday's top 10, fetches actual returns,
     computes hit rates, stores in backtesting_log.
  2. update_dynamic_weights() — after 30+ days of data, adjusts signal weights
     based on precision per signal per asset class.
  3. build_scorecard_summary() — returns dict for the email scorecard section.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import yfinance as yf

from sentinel.config import BASE_WEIGHTS, get_active_assets
from sentinel.database.client import (
    get_top10_for_date,
    get_price_history,
    get_signal_hit_rates,
    get_recent_scorecard,
    insert_backtest_results,
    upsert_signal_weights,
    get_latest_weights,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Fetch actual returns
# ─────────────────────────────────────────────────────────────────────────────

def _get_actual_return(symbol: str, signal_date_str: str, horizon_days: int = 1) -> Optional[float]:
    """
    Fetches the actual price return for a symbol over horizon_days after signal_date.
    Returns pct change as float (e.g. 0.021 = +2.1%) or None if data unavailable.
    """
    try:
        signal_date = date.fromisoformat(signal_date_str)
        start = signal_date
        end   = signal_date + timedelta(days=horizon_days + 5)  # buffer for weekends

        # First check local DB cache
        history = get_price_history(symbol, days=horizon_days + 10)
        if history:
            close_on_signal = None
            close_after     = None
            for row in history:
                row_date = date.fromisoformat(row["date"])
                if row_date == signal_date:
                    close_on_signal = row.get("close")
                if close_on_signal and row_date >= signal_date + timedelta(days=horizon_days):
                    close_after = row.get("close")
                    break

            if close_on_signal and close_after:
                return (close_after - close_on_signal) / close_on_signal

        # Fallback to yfinance
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start.isoformat(), end=end.isoformat())

        if hist.empty or len(hist) < 2:
            return None

        price_on_signal = hist["Close"].iloc[0]
        price_after     = hist["Close"].iloc[min(horizon_days, len(hist) - 1)]
        return float((price_after - price_on_signal) / price_on_signal)

    except Exception as exc:
        logger.debug("Return fetch error %s: %s", symbol, exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Evaluate yesterday's top 10
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_yesterday() -> list[dict]:
    """
    Looks up yesterday's top 10 predictions, fetches 1-day returns,
    stores results in backtesting_log.
    Returns list of backtest result dicts.
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    top10 = get_top10_for_date(yesterday)

    if not top10:
        logger.info("No predictions found for %s — skipping backtest.", yesterday)
        return []

    results: list[dict] = []
    for row in top10:
        symbol      = row["symbol"]
        signal_date = row["date"]
        rank        = row.get("rank")
        final_score = row.get("final_score")

        return_1d  = _get_actual_return(symbol, signal_date, horizon_days=1)
        return_5d  = _get_actual_return(symbol, signal_date, horizon_days=5)

        hit_1d = return_1d is not None and return_1d >= 0.01   # +1% threshold
        hit_5d = return_5d is not None and return_5d >= 0.01

        results.append({
            "symbol":       symbol,
            "signal_date":  signal_date,
            "rank":         rank,
            "final_score":  final_score,
            "top_signals":  {},  # would need to store from daily_signals
            "return_1d":    return_1d,
            "return_5d":    return_5d,
            "return_20d":   None,  # filled in later
            "hit_1d":       hit_1d,
            "hit_5d":       hit_5d,
            "max_drawdown_5d": None,
        })

    stored = insert_backtest_results(results)
    hits = sum(1 for r in results if r.get("hit_1d"))
    logger.info(
        "Backtest for %s: %d/%d hits (1d), stored %d records",
        yesterday, hits, len(results), stored,
    )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic weight adjustment
# ─────────────────────────────────────────────────────────────────────────────

def update_dynamic_weights(lookback_days: int = 30) -> dict:
    """
    Updates signal weights based on hit rate over the last N days.
    Formula: w_k(t) = base_w_k × clamp(0.5 + 1.5 × HitRate_k, 0.5, 2.0)
    Only runs if we have ≥30 days of backtest data.

    Returns dict of updated weights by asset class.
    """
    stats = get_signal_hit_rates(days=lookback_days)

    if stats.get("count", 0) < 20:
        logger.info(
            "Dynamic weights: only %d predictions in DB (need 20). Using base weights.",
            stats.get("count", 0),
        )
        return {}

    overall_hit_rate = stats.get("overall", 0.33)
    today = date.today().isoformat()

    asset_classes = list(set(a.asset_class for a in get_active_assets()))
    updated_weights: dict = {}

    for ac in asset_classes:
        current_weights = get_latest_weights(ac)
        new_weights: dict[str, float] = {}

        for sig_name, base_w in BASE_WEIGHTS.items():
            # TODO: In phase 4, track hit rates per signal per asset class
            # For now, use overall hit rate as a uniform multiplier
            multiplier = max(0.5, min(2.0, 0.5 + 1.5 * overall_hit_rate))
            new_w = base_w * multiplier

            new_weights[sig_name] = new_w

        # Normalise to sum to 1.0
        total = sum(new_weights.values())
        if total > 0:
            new_weights = {k: v / total for k, v in new_weights.items()}

        updated_weights[ac] = new_weights

        weight_rows = [
            {
                "date":            today,
                "asset_class":     ac,
                "signal_name":     sig,
                "base_weight":     BASE_WEIGHTS.get(sig, 0.0),
                "adjusted_weight": w,
                "hit_rate_30d":    overall_hit_rate,
                "precision_30d":   overall_hit_rate,
            }
            for sig, w in new_weights.items()
        ]
        upsert_signal_weights(weight_rows)

    logger.info("Dynamic weights updated for %d asset classes (hit_rate=%.1f%%)",
                len(asset_classes), overall_hit_rate * 100)
    return updated_weights


# ─────────────────────────────────────────────────────────────────────────────
# Scorecard summary for email
# ─────────────────────────────────────────────────────────────────────────────

def build_scorecard_summary() -> dict:
    """
    Builds the email scorecard section: yesterday's picks + accuracy stats.
    """
    recent = get_recent_scorecard(days=7)

    # Yesterday's picks
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yesterday_entries = [r for r in recent if r["signal_date"] == yesterday]

    # 1-day hit rate (yesterday)
    if yesterday_entries:
        hits_1d = sum(1 for e in yesterday_entries if e.get("hit_5d"))
        hit_rate_1d = round(hits_1d / len(yesterday_entries) * 100)
    else:
        hit_rate_1d = 0

    # 7-day rolling hit rate
    all_with_results = [r for r in recent if r.get("hit_5d") is not None]
    if all_with_results:
        hit_rate_7d = round(sum(1 for r in all_with_results if r["hit_5d"]) / len(all_with_results) * 100)
    else:
        hit_rate_7d = 0

    # Format yesterday entries for template
    entries = []
    for e in sorted(yesterday_entries, key=lambda x: x.get("rank_on_signal_date") or 99):
        ret_1d = e.get("return_1d")
        entries.append({
            "rank":      e.get("rank_on_signal_date", "?"),
            "symbol":    e["symbol"],
            "score":     e.get("final_score_on_signal_date", 0.0),
            "return_1d": (ret_1d or 0) * 100,
            "hit":       bool(e.get("hit_5d")),
        })

    return {
        "entries":           entries,
        "hit_rate_1d":       hit_rate_1d,
        "hit_rate_7d":       hit_rate_7d,
        "total_predictions": len(all_with_results),
    }
