"""
Jinja2 HTML email renderer.
Transforms scored asset data into the daily digest email.
"""
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from sentinel.config import get_active_assets

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.7:
        return "HIGH"
    if confidence >= 0.4:
        return "MEDIUM"
    return "LOW"


def _confidence_class(confidence: float) -> str:
    if confidence >= 0.7:
        return "high"
    if confidence >= 0.4:
        return "medium"
    return "low"


def _risk_label(risk_adj: float) -> str:
    """risk_adj is 0-1, where 1 = lowest risk."""
    if risk_adj >= 0.7:
        return "LOW"
    if risk_adj >= 0.4:
        return "MEDIUM"
    return "HIGH"


def _risk_class(risk_adj: float) -> str:
    if risk_adj >= 0.7:
        return "high"      # green styling = low risk
    if risk_adj >= 0.4:
        return "medium"
    return "low"           # red styling = high risk


def _format_macro(macro_context: dict) -> dict:
    """Format macro data for the email template."""
    vix = macro_context.get("^VIX")
    yield_10y = macro_context.get("^TNX")
    btc_dom = macro_context.get("BTC_DOMINANCE")
    spy = macro_context.get("SPY")

    # Simple regime detection
    if vix is not None:
        if vix < 15:
            regime = "Risk-On (Low Fear)"
        elif vix < 25:
            regime = "Neutral"
        else:
            regime = "Risk-Off (Elevated Fear)"
    else:
        regime = "Unknown"

    return {
        "regime":       regime,
        "vix":          f"{vix:.1f}" if vix else "N/A",
        "yield_10y":    f"{yield_10y:.2f}%" if yield_10y else "N/A",
        "btc_dominance":f"{btc_dom:.1f}%" if btc_dom else "N/A",
        "spy":          f"${spy:.0f}" if spy else "N/A",
    }


def _build_why_text(asset_row: dict, articles: list[dict], tweets: list[dict]) -> str:
    """Generates a brief 'WHY' explanation for each top asset."""
    symbol = asset_row["symbol"]
    lines: list[str] = []

    # Top signals
    top_signals = asset_row.get("_top_signals", {})
    signal_names = {
        "news_sentiment":          "News sentiment",
        "social_sentiment":        "Social sentiment",
        "sentiment_shift":         "Sentiment momentum",
        "volume_anomaly":          "Volume",
        "momentum_score":          "Price momentum",
        "correlation_divergence":  "Correlation break",
        "risk_adjusted_liquidity": "Risk/liquidity profile",
        "regulatory_signal":       "Regulatory signal",
        "competitor_edge":         "Competitor advantage",
        "geopolitical_flow":       "Geopolitical flows",
        "catalyst_freshness":      "Fresh catalyst",
    }

    for sig_key, contribution in top_signals.items():
        name = signal_names.get(sig_key, sig_key)
        if contribution > 0.1:
            lines.append(f"{name} strongly positive.")
        elif contribution < -0.1:
            lines.append(f"{name} negative — flag.")

    # Add top article headline if available
    relevant_articles = [a for a in articles if symbol in a.get("asset_symbols", [])]
    if relevant_articles:
        best = max(relevant_articles, key=lambda a: a.get("source_tier", 0))
        lines.append(f'Latest: "{best.get("title", "")[:100]}"')

    # Volume note
    vol_z = (asset_row.get("_market_data") or {}).get("volume_zscore")
    if vol_z and vol_z > 1.5:
        lines.append(f"Volume {vol_z:.1f}σ above 20d median.")

    return " ".join(lines[:3]) if lines else "Composite signals positive across multiple sources."


def _count_sources(articles: list[dict], symbol: str) -> int:
    relevant = [a for a in articles if symbol in a.get("asset_symbols", [])]
    return len(set(a.get("source", "") for a in relevant))


def build_asset_template_data(
    top10: list[dict],
    articles: list[dict],
    tweets: list[dict],
    asset_meta: dict,
) -> list[dict]:
    """Convert scored asset rows into template-ready dicts."""
    result = []
    for row in top10:
        sym = row["symbol"]
        meta = asset_meta.get(sym)
        conf = row.get("confidence", 0.5)
        risk = row.get("risk_adjusted_liquidity", 0.5)

        top_sig = row.get("_top_signals", {})
        top_drivers = sorted(top_sig.items(), key=lambda x: abs(x[1]), reverse=True)[:3]

        result.append({
            "rank":             row.get("rank"),
            "symbol":           sym,
            "name":             meta.name if meta else sym,
            "asset_class":      row.get("_asset_class", "stock"),
            "sector":           meta.sector if meta else "",
            "final_score":      row.get("final_score", 0.0),
            "confidence":       conf,
            "confidence_label": _confidence_label(conf),
            "confidence_class": _confidence_class(conf),
            "risk_label":       _risk_label(risk),
            "risk_class":       _risk_class(risk),
            "source_count":     _count_sources(articles, sym),
            "why":              _build_why_text(row, articles, tweets),
            "top_drivers":      top_drivers,
        })
    return result


def build_regulatory_items(articles: list[dict]) -> list[dict]:
    """Extract regulatory articles for the watchlist section."""
    regulatory = [
        a for a in articles
        if a.get("_is_regulatory")
        and a.get("source_tier", 0) >= 0.7
    ]
    return [
        {"source": a.get("source", ""), "title": a.get("title", "")[:120]}
        for a in regulatory[:6]
    ]


def render_email(
    top10: list[dict],
    scorecard: dict,
    articles: list[dict],
    tweets: list[dict],
    macro_context: dict,
    run_date: Optional[str] = None,
) -> str:
    """
    Renders the full HTML email.

    Args:
        top10: Top 10 scored asset rows
        scorecard: Yesterday's accuracy data
        articles: All news articles (for WHY text and regulatory section)
        tweets: All tweets (for WHY text)
        macro_context: VIX, DXY, etc.
        run_date: ISO date string, defaults to today

    Returns:
        HTML string ready to send.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("email.html")

    asset_meta = {a.symbol: a for a in get_active_assets()}
    run_date   = run_date or date.today().strftime("%B %d, %Y")

    # Count active sources
    sources_active = len(set(a.get("source", "") for a in articles if a.get("title")))

    context = {
        "run_date":          run_date,
        "signals_processed": sum([len(top10) * 11, len(articles), len(tweets)]),
        "asset_count":       len(get_active_assets()),
        "macro":             _format_macro(macro_context),
        "top10":             build_asset_template_data(top10, articles, tweets, asset_meta),
        "scorecard":         scorecard,
        "regulatory_items":  build_regulatory_items(articles),
        "sources_active":    sources_active,
    }

    html = template.render(**context)
    logger.info("Email rendered: %d assets, %d regulatory items", len(top10), len(context["regulatory_items"]))
    return html
