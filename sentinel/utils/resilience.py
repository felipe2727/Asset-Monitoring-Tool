"""
Resilience utilities — lightweight circuit breaker and async rate limiter.
Used across all ingestion modules to prevent hammering dead APIs
and to enforce correct pacing even with retries.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Circuit Breaker (lightweight, in-memory)
# ─────────────────────────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Tracks consecutive failures per provider and disables them with a cooldown.

    Usage:
        cb = CircuitBreaker()

        if cb.is_available("arcticshift"):
            try:
                result = await fetch(...)
                cb.record_success("arcticshift")
            except Exception:
                cb.record_failure("arcticshift")
    """

    def __init__(self, max_failures: int = 3, cooldown_seconds: int = 300):
        self._max_failures = max_failures
        self._cooldown_seconds = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._disabled_until: dict[str, datetime] = {}

    def is_available(self, provider: str) -> bool:
        if provider in self._disabled_until:
            if datetime.utcnow() < self._disabled_until[provider]:
                return False
            # Cooldown expired — re-enable
            del self._disabled_until[provider]
            self._failures[provider] = 0
            logger.info("  CircuitBreaker: %s re-enabled after cooldown", provider)
        return self._failures.get(provider, 0) < self._max_failures

    def record_failure(self, provider: str) -> None:
        self._failures[provider] = self._failures.get(provider, 0) + 1
        if self._failures[provider] >= self._max_failures:
            self._disabled_until[provider] = (
                datetime.utcnow() + timedelta(seconds=self._cooldown_seconds)
            )
            logger.warning(
                "  CircuitBreaker: %s disabled for %ds after %d consecutive failures",
                provider, self._cooldown_seconds, self._failures[provider],
            )

    def record_success(self, provider: str) -> None:
        self._failures[provider] = 0
        if provider in self._disabled_until:
            del self._disabled_until[provider]

    def status(self) -> dict[str, str]:
        """Returns {provider: 'live'|'disabled'} for all tracked providers."""
        result = {}
        all_providers = set(self._failures.keys()) | set(self._disabled_until.keys())
        for p in all_providers:
            if not self.is_available(p):
                result[p] = "disabled"
            else:
                result[p] = "live"
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Rate Limiter (async, per-provider)
# ─────────────────────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Simple async rate limiter that enforces a minimum interval between requests.

    Usage:
        limiter = RateLimiter(min_interval=13.0)  # Alpha Vantage: 5 calls/min
        await limiter.acquire()
        response = await client.get(...)
    """

    def __init__(self, min_interval: float):
        self._min_interval = min_interval
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


# ─────────────────────────────────────────────────────────────────────────────
# Pre-configured rate limiters for known APIs
# ─────────────────────────────────────────────────────────────────────────────

# Instantiated once at import time; shared across a single pipeline run
rate_limiters: dict[str, RateLimiter] = {
    "alpha_vantage":  RateLimiter(13.0),   # 5 calls/min free tier
    "finnhub":        RateLimiter(0.5),    # ~120 calls/min
    "coingecko":      RateLimiter(1.5),    # ~10 calls/min free tier
    "scrapebadger":   RateLimiter(13.0),   # 5 req/min
    "scrapingdog":    RateLimiter(13.0),   # conservative
    "stocktwits":     RateLimiter(1.0),    # 200 req/hr
    "arcticshift":    RateLimiter(0.2),    # ~500 RPM
    "rss":            RateLimiter(2.0),    # conservative
    "pullpush":       RateLimiter(0.5),    # ~500 RPM
    "polymarket":     RateLimiter(0.4),    # ~300ms recommended
    "kalshi":         RateLimiter(0.5),    # conservative
    "eia":            RateLimiter(0.5),    # generous
    "yahoo":          RateLimiter(0.7),    # 600ms min
    "acled":          RateLimiter(2.0),    # heavily rate-limited
    "usgs":           RateLimiter(0.0),    # static file, no limit
    "nasa_firms":     RateLimiter(1.0),    # conservative
    "cloudflare":     RateLimiter(1.0),    # conservative
}
