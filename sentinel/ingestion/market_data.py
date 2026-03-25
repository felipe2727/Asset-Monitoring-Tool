"""
Market data ingestion:
  - Finnhub: real-time stock/ETF quotes (free tier)
  - Alpha Vantage: daily OHLCV history for technicals (free tier, 25 calls/day)
  - CoinGecko: crypto prices, volume, market cap, history (no API key needed)
"""
import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
import numpy as np
import pandas as pd

from sentinel.config import (
    get_active_assets, FINNHUB_API_KEY, ALPHA_VANTAGE_API_KEY, FRED_API_KEY,
    EIA_API_KEY, EIA_API_BASE, EIA_SERIES, YAHOO_FINANCE_URL,
)
from sentinel.utils.resilience import CircuitBreaker, rate_limiters

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
FINNHUB_BASE   = "https://finnhub.io/api/v1"
AV_BASE        = "https://www.alphavantage.co/query"


# ─────────────────────────────────────────────────────────────────────────────
# Technical indicator helpers (computed from OHLCV history)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_rsi(closes: pd.Series, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else None


def _compute_macd_signal(closes: pd.Series) -> Optional[float]:
    if len(closes) < 26:
        return None
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    # Return MACD - Signal (histogram) as the signal value
    hist = macd_line - signal_line
    return float(hist.iloc[-1]) if not hist.empty else None


def _compute_bollinger_position(closes: pd.Series, period: int = 20) -> Optional[float]:
    """Returns 0-1: where current price sits within the Bollinger Band (0=lower, 1=upper)."""
    if len(closes) < period:
        return None
    sma = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    current = closes.iloc[-1]
    band_width = (upper - lower).iloc[-1]
    if band_width == 0:
        return 0.5
    pos = (current - lower.iloc[-1]) / band_width
    return float(np.clip(pos, 0.0, 1.0))


def _compute_volume_zscore(volumes: pd.Series, window: int = 20) -> Optional[float]:
    if len(volumes) < window:
        return None
    median = volumes.rolling(window).median().iloc[-1]
    std    = volumes.rolling(window).std().iloc[-1]
    if std == 0:
        return 0.0
    return float((volumes.iloc[-1] - median) / std)


def _compute_volatility_30d(closes: pd.Series) -> Optional[float]:
    if len(closes) < 31:
        return None
    returns = closes.pct_change().dropna()
    return float(returns.tail(30).std() * np.sqrt(252) * 100)  # annualised %


# ─────────────────────────────────────────────────────────────────────────────
# Finnhub (stocks, ETFs, commodities, REITs)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_av_daily(client: httpx.AsyncClient, symbol: str) -> tuple[pd.Series, pd.Series]:
    """Fetches daily OHLCV from Alpha Vantage. Returns (closes, volumes) Series."""
    if not ALPHA_VANTAGE_API_KEY:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    try:
        resp = await client.get(
            AV_BASE,
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",  # last 100 days
                "apikey": ALPHA_VANTAGE_API_KEY,
            },
            timeout=20,
        )
        data = resp.json()
        ts = data.get("Time Series (Daily)", {})
        if not ts:
            logger.warning("  Alpha Vantage %s: no data (%s)", symbol, list(data.keys())[:2])
            return pd.Series(dtype=float), pd.Series(dtype=float)
        # Sort by date ascending
        sorted_dates = sorted(ts.keys())
        closes  = pd.Series([float(ts[d]["4. close"]) for d in sorted_dates])
        volumes = pd.Series([float(ts[d]["5. volume"]) for d in sorted_dates])
        logger.info("  Alpha Vantage %s: %d days of history", symbol, len(closes))
        return closes, volumes
    except Exception as exc:
        logger.warning("  Alpha Vantage %s: %s", symbol, exc)
        return pd.Series(dtype=float), pd.Series(dtype=float)


async def _fetch_finnhub_data(symbols: list[str]) -> list[dict]:
    """Fetches quotes via Finnhub + daily history via Alpha Vantage for technicals."""
    if not FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not set — skipping stock market data")
        return []

    today_str = date.today().isoformat()

    results = []
    async with httpx.AsyncClient() as client:
        for symbol in symbols:
            try:
                # Current quote from Finnhub (free, works)
                q_resp = await client.get(
                    f"{FINNHUB_BASE}/quote",
                    params={"symbol": symbol, "token": FINNHUB_API_KEY},
                    timeout=15,
                )
                q_resp.raise_for_status()
                quote = q_resp.json()
                current = quote.get("c", 0)
                if not current:
                    logger.warning("  Finnhub %s: no quote data", symbol)
                    continue

                # Daily history from Alpha Vantage (Finnhub candles are 403 on free tier)
                closes, volumes = await _fetch_av_daily(client, symbol)
                if closes.empty:
                    closes  = pd.Series([current])
                    volumes = pd.Series([0])

                last_vol = int(volumes.iloc[-1]) if len(volumes) > 0 else 0
                avg_vol  = float(volumes.tail(20).mean()) if len(volumes) >= 20 else float(volumes.mean())

                results.append({
                    "symbol":             symbol,
                    "date":               today_str,
                    "open":               quote.get("o"),
                    "high":               quote.get("h"),
                    "low":                quote.get("l"),
                    "close":              current,
                    "volume":             last_vol,
                    "market_cap":         None,
                    "rsi_14":             _compute_rsi(closes),
                    "macd_signal":        _compute_macd_signal(closes),
                    "bollinger_position": _compute_bollinger_position(closes),
                    "volatility_30d":     _compute_volatility_30d(closes),
                    "avg_volume_20d":     avg_vol,
                    "volume_zscore":      _compute_volume_zscore(volumes),
                })
                logger.debug("  Finnhub %s: close=%.2f", symbol, current)

                # Alpha Vantage free: 5 calls/min — pace at 13s per symbol
                await asyncio.sleep(13)

            except Exception as exc:
                logger.warning("  Finnhub %s: %s", symbol, exc)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# CoinGecko (crypto)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_coingecko_data(assets) -> list[dict]:
    """Fetches price, volume, market cap for crypto assets from CoinGecko."""
    coingecko_assets = [(a.symbol, a.coingecko_id) for a in assets if a.coingecko_id]
    if not coingecko_assets:
        return []

    ids_str = ",".join(cg_id for _, cg_id in coingecko_assets)
    url = f"{COINGECKO_BASE}/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": ids_str,
        "order": "market_cap_desc",
        "per_page": 50,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "24h,7d",
    }

    today = date.today().isoformat()
    results = []

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=20)
            resp.raise_for_status()
            coins = resp.json()

        cg_id_to_symbol = {cg_id: sym for sym, cg_id in coingecko_assets}

        for coin in coins:
            symbol = cg_id_to_symbol.get(coin["id"])
            if not symbol:
                continue

            # Also fetch 30d history for technicals
            hist_url = f"{COINGECKO_BASE}/coins/{coin['id']}/market_chart"
            try:
                async with httpx.AsyncClient() as client:
                    hist_resp = await client.get(
                        hist_url,
                        params={"vs_currency": "usd", "days": "60"},
                        timeout=20,
                    )
                    hist_data = hist_resp.json()
                prices_series  = pd.Series([p[1] for p in hist_data.get("prices", [])])
                volumes_series = pd.Series([v[1] for v in hist_data.get("total_volumes", [])])
            except Exception:
                prices_series  = pd.Series([coin.get("current_price", 0)])
                volumes_series = pd.Series([coin.get("total_volume", 0)])

            results.append({
                "symbol":            symbol,
                "date":              today,
                "open":              None,
                "high":              coin.get("high_24h"),
                "low":               coin.get("low_24h"),
                "close":             coin.get("current_price"),
                "volume":            int(coin.get("total_volume", 0)),
                "market_cap":        coin.get("market_cap"),
                "rsi_14":            _compute_rsi(prices_series),
                "macd_signal":       _compute_macd_signal(prices_series),
                "bollinger_position":_compute_bollinger_position(prices_series),
                "volatility_30d":    _compute_volatility_30d(prices_series),
                "avg_volume_20d":    float(volumes_series.tail(20).mean()) if len(volumes_series) >= 20 else None,
                "volume_zscore":     _compute_volume_zscore(volumes_series),
                "_price_change_24h": coin.get("price_change_percentage_24h"),
                "_price_change_7d":  coin.get("price_change_percentage_7d_in_currency"),
            })
            logger.debug("  CoinGecko %s: $%.4f mktcap=$%.0fM", symbol,
                         coin.get("current_price", 0), (coin.get("market_cap", 0) or 0) / 1e6)

        # CoinGecko free tier: respect rate limit (~10 calls/min)
        await asyncio.sleep(1.5)

    except Exception as exc:
        logger.error("CoinGecko error: %s", exc)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# FRED (commodity spot prices — gold, oil, natgas, copper)
# ─────────────────────────────────────────────────────────────────────────────

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Maps FRED series to our ETF symbols (daily series only)
FRED_COMMODITY_SERIES: dict[str, str] = {
    "DCOILWTICO": "USO",   # WTI Crude Oil spot price (daily)
    "DHHNGSP":    "UNG",   # Henry Hub Natural Gas spot (daily)
}


async def _fetch_fred_spot_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """
    Fetches latest commodity spot prices from FRED.
    Returns {symbol: spot_price} e.g. {"GLD": 3025.50, "USO": 68.20}.
    """
    if not FRED_API_KEY:
        return {}

    spot_prices: dict[str, float] = {}
    for series_id, symbol in FRED_COMMODITY_SERIES.items():
        try:
            resp = await client.get(
                FRED_BASE,
                params={
                    "series_id": series_id,
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 5,  # last 5 observations to find non-"." value
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            observations = data.get("observations", [])
            for obs in observations:
                val = obs.get("value", ".")
                if val != ".":
                    spot_prices[symbol] = float(val)
                    logger.info("  FRED %s (%s): $%.2f", symbol, series_id, float(val))
                    break
        except Exception as exc:
            logger.warning("  FRED %s: %s", series_id, exc)

    return spot_prices


# ─────────────────────────────────────────────────────────────────────────────
# CoinCap (crypto fallback when CoinGecko fails)
# ─────────────────────────────────────────────────────────────────────────────

COINCAP_BASE = "https://api.coincap.io/v2"

# Maps our symbols to CoinCap asset IDs
COINCAP_IDS: dict[str, str] = {
    "BTC":  "bitcoin",
    "ETH":  "ethereum",
    "SOL":  "solana",
    "AVAX": "avalanche",
    "LINK": "chainlink",
    "DOT":  "polkadot",
    "NEAR": "near-protocol",
    "SUI":  "sui",
    "ARB":  "arbitrum",
    "OP":   "optimism",
    "INJ":  "injective-protocol",
    "APT":  "aptos",
}


async def _fetch_coincap_data(assets) -> list[dict]:
    """Fallback crypto data from CoinCap (no API key needed)."""
    coingecko_assets = [(a.symbol, a.coingecko_id) for a in assets if a.coingecko_id]
    if not coingecko_assets:
        return []

    today = date.today().isoformat()
    results = []

    try:
        async with httpx.AsyncClient() as client:
            for symbol, _ in coingecko_assets:
                coincap_id = COINCAP_IDS.get(symbol)
                if not coincap_id:
                    continue
                try:
                    # Current price
                    resp = await client.get(
                        f"{COINCAP_BASE}/assets/{coincap_id}", timeout=15,
                    )
                    resp.raise_for_status()
                    coin = resp.json().get("data", {})
                    if not coin:
                        continue

                    price = float(coin.get("priceUsd", 0))
                    volume = float(coin.get("volumeUsd24Hr", 0))
                    mcap = float(coin.get("marketCapUsd", 0))

                    # 60-day history for technicals
                    end_ms = int(datetime.utcnow().timestamp() * 1000)
                    start_ms = end_ms - 60 * 86400 * 1000
                    hist_resp = await client.get(
                        f"{COINCAP_BASE}/assets/{coincap_id}/history",
                        params={"interval": "d1", "start": start_ms, "end": end_ms},
                        timeout=15,
                    )
                    hist_data = hist_resp.json().get("data", [])
                    if hist_data:
                        prices_series = pd.Series([float(d["priceUsd"]) for d in hist_data])
                    else:
                        prices_series = pd.Series([price])

                    results.append({
                        "symbol":             symbol,
                        "date":               today,
                        "open":               None,
                        "high":               None,
                        "low":                None,
                        "close":              price,
                        "volume":             int(volume),
                        "market_cap":         mcap,
                        "rsi_14":             _compute_rsi(prices_series),
                        "macd_signal":        _compute_macd_signal(prices_series),
                        "bollinger_position": _compute_bollinger_position(prices_series),
                        "volatility_30d":     _compute_volatility_30d(prices_series),
                        "avg_volume_20d":     None,
                        "volume_zscore":      None,
                    })
                    logger.debug("  CoinCap %s: $%.4f", symbol, price)
                    await asyncio.sleep(0.5)

                except Exception as exc:
                    logger.warning("  CoinCap %s: %s", symbol, exc)

    except Exception as exc:
        logger.error("CoinCap error: %s", exc)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# EIA Direct API (structured energy data — WTI, Brent, production, inventory)
# ─────────────────────────────────────────────────────────────────────────────

cb = CircuitBreaker(max_failures=3, cooldown_seconds=300)


async def _fetch_eia_data(client: httpx.AsyncClient) -> dict[str, dict]:
    """
    Fetches EIA energy data: WTI/Brent prices, US production, US inventory.
    Returns {symbol: {wti: float, brent: float, production: float, inventory: float, inventory_change: float}}.
    """
    if not EIA_API_KEY:
        return {}
    if not cb.is_available("eia"):
        return {}

    result: dict[str, dict] = {}

    for series_id, meta in EIA_SERIES.items():
        try:
            await rate_limiters["eia"].acquire()
            resp = await client.get(
                f"{EIA_API_BASE}/{series_id}",
                params={"api_key": EIA_API_KEY, "num": 2},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            observations = data.get("response", {}).get("data", [])

            if not observations:
                continue

            current_val = float(observations[0].get("value", 0))
            prev_val = float(observations[1].get("value", 0)) if len(observations) > 1 else current_val

            symbol = meta["symbol"]
            if symbol not in result:
                result[symbol] = {}

            data_type = meta.get("type", "price")
            if data_type == "inventory":
                result[symbol]["inventory"] = current_val
                result[symbol]["inventory_change"] = current_val - prev_val
                logger.info("  EIA %s (inventory): %.1f (change: %+.1f)", series_id, current_val, current_val - prev_val)
            elif data_type == "production":
                result[symbol]["production"] = current_val
                logger.info("  EIA %s (production): %.1f", series_id, current_val)
            else:
                # Price data
                name_lower = meta["name"].lower()
                if "brent" in name_lower:
                    result[symbol]["brent"] = current_val
                    logger.info("  EIA Brent: $%.2f", current_val)
                else:
                    result[symbol]["wti"] = current_val
                    logger.info("  EIA WTI: $%.2f", current_val)

            cb.record_success("eia")

        except Exception as exc:
            logger.warning("  EIA %s: %s", series_id, exc)
            cb.record_failure("eia")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Yahoo Finance (fallback for Finnhub + Alpha Vantage)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_yahoo_finance(symbols: list[str]) -> list[dict]:
    """
    Fallback: fetches market data from Yahoo Finance when Finnhub/AV fail.
    Returns list of market data dicts in the same schema as _fetch_finnhub_data.
    """
    if not cb.is_available("yahoo"):
        return []

    today_str = date.today().isoformat()
    results = []

    async with httpx.AsyncClient() as client:
        for symbol in symbols:
            try:
                await rate_limiters["yahoo"].acquire()
                url = f"{YAHOO_FINANCE_URL}/{symbol}"
                resp = await client.get(
                    url,
                    params={"interval": "1d", "range": "3mo"},
                    headers={"User-Agent": "Mozilla/5.0 (Sentinel/1.0)"},
                    timeout=15,
                )
                if not resp.is_success:
                    logger.warning("  Yahoo %s: HTTP %d", symbol, resp.status_code)
                    cb.record_failure("yahoo")
                    continue

                data = resp.json()
                chart = data.get("chart", {}).get("result", [])
                if not chart:
                    continue

                result = chart[0]
                meta = result.get("meta", {})
                indicators = result.get("indicators", {})
                quotes = indicators.get("quote", [{}])[0]

                closes_raw = quotes.get("close", [])
                volumes_raw = quotes.get("volume", [])

                # Filter None values
                closes_clean = [c for c in closes_raw if c is not None]
                volumes_clean = [v for v in volumes_raw if v is not None]

                if not closes_clean:
                    continue

                closes = pd.Series(closes_clean)
                volumes = pd.Series(volumes_clean) if volumes_clean else pd.Series([0])

                current = closes.iloc[-1]
                last_vol = int(volumes.iloc[-1]) if len(volumes) > 0 else 0
                avg_vol = float(volumes.tail(20).mean()) if len(volumes) >= 20 else float(volumes.mean())

                results.append({
                    "symbol":             symbol,
                    "date":               today_str,
                    "open":               meta.get("previousClose"),
                    "high":               float(max(closes_raw[-5:])) if len(closes_raw) >= 5 else None,
                    "low":                float(min(c for c in closes_raw[-5:] if c)) if len(closes_raw) >= 5 else None,
                    "close":              float(current),
                    "volume":             last_vol,
                    "market_cap":         None,
                    "rsi_14":             _compute_rsi(closes),
                    "macd_signal":        _compute_macd_signal(closes),
                    "bollinger_position": _compute_bollinger_position(closes),
                    "volatility_30d":     _compute_volatility_30d(closes),
                    "avg_volume_20d":     avg_vol,
                    "volume_zscore":      _compute_volume_zscore(volumes),
                    "_source":            "yahoo",
                })
                logger.debug("  Yahoo %s: close=%.2f", symbol, float(current))
                cb.record_success("yahoo")

            except Exception as exc:
                logger.warning("  Yahoo %s: %s", symbol, exc)
                cb.record_failure("yahoo")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_market_data() -> dict[str, dict]:
    """
    Fetches market data for all active assets.
    Returns dict: symbol -> market_data_row.
    """
    assets = get_active_assets()

    stock_symbols    = [a.symbol for a in assets if a.asset_class in ("stock", "commodity", "reit")]
    crypto_assets    = [a for a in assets if a.asset_class == "crypto"]

    # Fetch stocks/ETFs via Finnhub + Alpha Vantage
    stock_rows = await _fetch_finnhub_data(stock_symbols)

    # Yahoo Finance fallback: if Finnhub/AV returned < 50% of expected, fill gaps
    covered_symbols = {r["symbol"] for r in stock_rows}
    missing_symbols = [s for s in stock_symbols if s not in covered_symbols]
    yahoo_rows: list[dict] = []
    if missing_symbols:
        logger.info("  %d stock symbols missing from Finnhub/AV — trying Yahoo Finance", len(missing_symbols))
        yahoo_rows = await _fetch_yahoo_finance(missing_symbols)
        stock_rows.extend(yahoo_rows)

    # Fetch crypto: CoinGecko primary, CoinCap fallback
    crypto_rows = await _fetch_coingecko_data(crypto_assets)
    if not crypto_rows:
        logger.warning("CoinGecko returned no data -- falling back to CoinCap")
        crypto_rows = await _fetch_coincap_data(crypto_assets)

    all_rows = stock_rows + crypto_rows
    by_symbol = {r["symbol"]: r for r in all_rows}

    # Enrich commodity ETFs with FRED spot prices
    async with httpx.AsyncClient() as client:
        fred_spots = await _fetch_fred_spot_prices(client)

        # Also fetch EIA energy data (WTI, Brent, production, inventory)
        eia_data = await _fetch_eia_data(client)

    for symbol, spot_price in fred_spots.items():
        if symbol in by_symbol:
            by_symbol[symbol]["_spot_price"] = spot_price
        else:
            logger.debug("  FRED spot for %s but no market row -- skipping", symbol)

    # Merge EIA data into market rows
    for symbol, eia_info in eia_data.items():
        if symbol in by_symbol:
            by_symbol[symbol]["_eia"] = eia_info
        else:
            logger.debug("  EIA data for %s but no market row -- skipping", symbol)

    logger.info(
        "Market data: %d stocks/ETFs (%d via Yahoo), %d crypto, %d FRED spots, %d EIA series (%d total)",
        len(stock_rows), len(yahoo_rows), len(crypto_rows), len(fred_spots), len(eia_data), len(all_rows),
    )
    return by_symbol


async def fetch_macro_context() -> dict:
    """
    Fetches macro indicators: SPY price, BTC dominance.
    Used in the email header.
    """
    macro = {}

    # SPY via Finnhub (proxy for broad market)
    if FINNHUB_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{FINNHUB_BASE}/quote",
                    params={"symbol": "SPY", "token": FINNHUB_API_KEY},
                    timeout=10,
                )
                if resp.is_success:
                    macro["SPY"] = resp.json().get("c")
        except Exception as exc:
            logger.warning("Macro SPY fetch error: %s", exc)

    # BTC dominance from CoinGecko global endpoint
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{COINGECKO_BASE}/global", timeout=10)
            data = resp.json().get("data", {})
            macro["BTC_DOMINANCE"] = data.get("market_cap_percentage", {}).get("btc")
    except Exception:
        pass

    # VIX + 10Y Yield via Yahoo Finance
    for yf_symbol, macro_key in [("^VIX", "^VIX"), ("^TNX", "^TNX")]:
        try:
            async with httpx.AsyncClient() as client:
                await rate_limiters["yahoo"].acquire()
                resp = await client.get(
                    f"{YAHOO_FINANCE_URL}/{yf_symbol}",
                    params={"interval": "1d", "range": "1d"},
                    headers={"User-Agent": "Mozilla/5.0 (Sentinel/1.0)"},
                    timeout=15,
                )
                if resp.is_success:
                    chart = resp.json().get("chart", {}).get("result", [])
                    if chart:
                        price = chart[0].get("meta", {}).get("regularMarketPrice")
                        if price is None:
                            closes = chart[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                            closes = [c for c in closes if c is not None]
                            if closes:
                                price = closes[-1]
                        if price is not None:
                            macro[macro_key] = float(price)
        except Exception as exc:
            logger.warning("Macro %s fetch error: %s", yf_symbol, exc)

    return macro
