"""
Sentinel configuration — all settings, asset lists, and key management live here.
"""
import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline mode
# ─────────────────────────────────────────────────────────────────────────────
FREE_TRIAL_MODE: bool = os.getenv("FREE_TRIAL_MODE", "true").lower() == "true"
RUN_NUMBER: int = int(os.getenv("RUN_NUMBER", "1"))  # 1-4

# Per-run Scrapingdog budget (free trial: 750 credits/run = 15 assets × 10 tweets × 5 cr)
TRIAL_ASSETS_COUNT: int = 15
TRIAL_TWEETS_PER_ASSET: int = 10
PRODUCTION_TWEETS_PER_ASSET: int = 20

TWEETS_PER_ASSET: int = TRIAL_TWEETS_PER_ASSET if FREE_TRIAL_MODE else PRODUCTION_TWEETS_PER_ASSET

# ─────────────────────────────────────────────────────────────────────────────
# Scrapingdog key rotation
# Runs 1-3: one key each (750/1000 credits used). Run 4: 250 credits from each.
# ─────────────────────────────────────────────────────────────────────────────
_SD_KEY_1 = os.getenv("SCRAPINGDOG_API_KEY_1", "")
_SD_KEY_2 = os.getenv("SCRAPINGDOG_API_KEY_2", "")
_SD_KEY_3 = os.getenv("SCRAPINGDOG_API_KEY_3", "")

def get_scrapingdog_keys() -> list[tuple[str, int]]:
    """
    Returns list of (api_key, max_tweets_budget) tuples for this run.
    Run 4 splits the 250-credit leftovers across all 3 keys.
    """
    if RUN_NUMBER == 1:
        return [(_SD_KEY_1, TRIAL_ASSETS_COUNT * TWEETS_PER_ASSET)]
    elif RUN_NUMBER == 2:
        return [(_SD_KEY_2, TRIAL_ASSETS_COUNT * TWEETS_PER_ASSET)]
    elif RUN_NUMBER == 3:
        return [(_SD_KEY_3, TRIAL_ASSETS_COUNT * TWEETS_PER_ASSET)]
    else:  # Run 4: 250 credits per key = 50 tweets per key
        per_key_tweets = 50  # 250 credits / 5 per tweet
        return [
            (_SD_KEY_1, per_key_tweets),
            (_SD_KEY_2, per_key_tweets),
            (_SD_KEY_3, per_key_tweets),
        ]

# ─────────────────────────────────────────────────────────────────────────────
# Firecrawl key selection
# ─────────────────────────────────────────────────────────────────────────────
_FC_KEY_1 = os.getenv("FIRECRAWL_API_KEY_1", "")
_FC_KEY_2 = os.getenv("FIRECRAWL_API_KEY_2", "")

FIRECRAWL_API_KEY: str = _FC_KEY_1 if _FC_KEY_1 else _FC_KEY_2
FIRECRAWL_MAX_ARTICLES: int = 50  # 50 credits/run, well within 500 free limit

# ─────────────────────────────────────────────────────────────────────────────
# Other API keys
# ─────────────────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
SCRAPEBADGER_API_KEY: str = os.getenv("SCRAPEBADGER_API_KEY", "")
FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "Sentinel/1.0")
ALPHA_VANTAGE_API_KEY: str = os.getenv("ALPHA_VANTAGE_API_KEY", "")
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL: str = os.getenv("RESEND_FROM_EMAIL", "sentinel@example.com")
RESEND_TO_EMAIL: str = os.getenv("RESEND_TO_EMAIL", "")

# ─────────────────────────────────────────────────────────────────────────────
# LLM settings
# ─────────────────────────────────────────────────────────────────────────────
OPENAI_MODEL: str = "gpt-4o-mini"
SENTIMENT_BATCH_SIZE: int = 20  # items per OpenAI call

# ─────────────────────────────────────────────────────────────────────────────
# Signal base weights (must sum to 1.0)
# ─────────────────────────────────────────────────────────────────────────────
BASE_WEIGHTS: dict[str, float] = {
    "news_sentiment":          0.12,
    "social_sentiment":        0.10,
    "sentiment_shift":         0.08,
    "volume_anomaly":          0.12,
    "momentum_score":          0.12,
    "correlation_divergence":  0.08,
    "risk_adjusted_liquidity": 0.10,
    "regulatory_signal":       0.08,
    "competitor_edge":         0.06,
    "geopolitical_flow":       0.07,
    "catalyst_freshness":      0.07,
}

# ─────────────────────────────────────────────────────────────────────────────
# Source tier weights (for news quality scoring)
# ─────────────────────────────────────────────────────────────────────────────
SOURCE_TIERS: dict[str, float] = {
    "ft.com":            1.0,
    "bloomberg.com":     1.0,
    "reuters.com":       1.0,
    "wsj.com":           0.9,
    "cnbc.com":          0.8,
    "marketwatch.com":   0.8,
    "coindesk.com":      0.7,
    "theblock.co":       0.7,
    "decrypt.co":        0.7,
    "seekingalpha.com":  0.5,
    "zerohedge.com":     0.4,
    "finnhub":           0.8,
    "fmp":               0.7,
    "tiingo":            0.6,
    "reddit":            0.3,
    "twitter":           0.2,
}

# ─────────────────────────────────────────────────────────────────────────────
# Asset watchlist
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Asset:
    symbol: str
    name: str
    asset_class: str        # stock | crypto | commodity | reit
    board: str              # public | private
    sector: str = ""
    peers: list[str] = field(default_factory=list)
    benchmark: str = "SPY"  # correlation benchmark
    coingecko_id: str = ""  # for crypto

FULL_WATCHLIST: list[Asset] = [
    # ── Stocks ───────────────────────────────────────────────────────────────
    Asset("NVDA", "NVIDIA",              "stock", "public", "Semiconductors",      ["AMD","INTC","AVGO","QCOM"], "SPY"),
    Asset("AAPL", "Apple",               "stock", "public", "Tech Hardware",       ["MSFT","GOOG","AMZN"],       "SPY"),
    Asset("MSFT", "Microsoft",           "stock", "public", "Software/Cloud",      ["AAPL","GOOG","AMZN"],       "SPY"),
    Asset("GOOG", "Alphabet",            "stock", "public", "Advertising/AI",      ["META","MSFT","AMZN"],       "SPY"),
    Asset("AMZN", "Amazon",              "stock", "public", "E-commerce/Cloud",    ["MSFT","GOOG","SHOP"],       "SPY"),
    Asset("TSLA", "Tesla",               "stock", "public", "EV/Energy",           ["RIVN","F","GM"],            "SPY"),
    Asset("META", "Meta Platforms",      "stock", "public", "Social/AI",           ["GOOG","SNAP","PINS"],       "SPY"),
    Asset("AMD",  "Advanced Micro Dev.", "stock", "public", "Semiconductors",      ["NVDA","INTC","AVGO"],       "SPY"),
    Asset("AVGO", "Broadcom",            "stock", "public", "Semiconductors",      ["NVDA","AMD","QCOM"],        "SPY"),
    Asset("CRM",  "Salesforce",          "stock", "public", "SaaS",                ["MSFT","ORCL","NOW"],        "SPY"),
    Asset("PLTR", "Palantir",            "stock", "public", "AI/Defense",          ["SNOW","AI","BBAI"],         "SPY"),
    Asset("COIN", "Coinbase",            "stock", "public", "Crypto Exchange",     [],                           "SPY"),
    Asset("SQ",   "Block",               "stock", "public", "Fintech",             ["PYPL","SOFI","AFRM"],       "SPY"),
    Asset("SHOP", "Shopify",             "stock", "public", "E-commerce",          ["AMZN","WIX","BIGC"],        "SPY"),
    Asset("NET",  "Cloudflare",          "stock", "public", "Cybersecurity",       ["CRWD","ZS","PANW"],         "SPY"),
    Asset("SNOW", "Snowflake",           "stock", "public", "Data/AI",             ["PLTR","DDOG","MDB"],        "SPY"),
    Asset("ARM",  "Arm Holdings",        "stock", "public", "Semiconductors",      ["NVDA","QCOM","AVGO"],       "SPY"),
    Asset("SMCI", "Super Micro",         "stock", "public", "AI Hardware",         ["DELL","HPE"],               "SPY"),
    Asset("LLY",  "Eli Lilly",           "stock", "public", "Pharma/Biotech",      ["NVO","ABBV","MRK"],         "SPY"),
    Asset("UBER", "Uber",                "stock", "public", "Mobility",            ["LYFT","DASH"],              "SPY"),
    # ── Crypto ───────────────────────────────────────────────────────────────
    Asset("BTC",   "Bitcoin",      "crypto", "public", "Store of Value",      [],             "BTC",  "bitcoin"),
    Asset("ETH",   "Ethereum",     "crypto", "public", "Smart Contracts",     ["SOL","AVAX"], "BTC",  "ethereum"),
    Asset("SOL",   "Solana",       "crypto", "public", "Alt L1",              ["ETH","AVAX"], "BTC",  "solana"),
    Asset("AVAX",  "Avalanche",    "crypto", "public", "Alt L1",              ["SOL","ETH"],  "BTC",  "avalanche-2"),
    Asset("LINK",  "Chainlink",    "crypto", "public", "Oracle",              [],             "BTC",  "chainlink"),
    Asset("DOT",   "Polkadot",     "crypto", "public", "Interoperability",    [],             "BTC",  "polkadot"),
    Asset("MATIC", "Polygon",      "crypto", "public", "L2",                  ["ARB","OP"],   "BTC",  "matic-network"),
    Asset("ARB",   "Arbitrum",     "crypto", "public", "L2",                  ["OP","MATIC"], "BTC",  "arbitrum"),
    Asset("OP",    "Optimism",     "crypto", "public", "L2",                  ["ARB","MATIC"],"BTC",  "optimism"),
    Asset("NEAR",  "NEAR Protocol","crypto", "public", "Alt L1",              [],             "BTC",  "near"),
    Asset("SUI",   "Sui",          "crypto", "public", "Alt L1",              [],             "BTC",  "sui"),
    Asset("INJ",   "Injective",    "crypto", "public", "DeFi",                [],             "BTC",  "injective-protocol"),
    Asset("RENDER","Render",       "crypto", "public", "AI/GPU",              ["FET"],        "BTC",  "render-token"),
    Asset("FET",   "Fetch.ai",     "crypto", "public", "AI",                  ["RENDER"],     "BTC",  "fetch-ai"),
    Asset("APT",   "Aptos",        "crypto", "public", "Alt L1",              [],             "BTC",  "aptos"),
    # ── Commodities (ETF proxies) ─────────────────────────────────────────────
    Asset("GLD",  "SPDR Gold",     "commodity","public","Gold",    [], "DXY"),
    Asset("SLV",  "iShares Silver","commodity","public","Silver",  [], "DXY"),
    Asset("USO",  "US Oil Fund",   "commodity","public","Crude Oil",[], "DXY"),
    Asset("UNG",  "US Nat Gas",    "commodity","public","Nat Gas", [], "DXY"),
    Asset("CPER", "US Copper",     "commodity","public","Copper",  [], "DXY"),
    # ── REITs ────────────────────────────────────────────────────────────────
    Asset("VNQ",  "Vanguard REIT", "reit","public","Broad REIT",      [], "^TNX"),
    Asset("O",    "Realty Income", "reit","public","Net Lease",        [], "^TNX"),
    Asset("AMT",  "American Tower","reit","public","Cell Towers",      [], "^TNX"),
    Asset("PLD",  "Prologis",      "reit","public","Industrial",       [], "^TNX"),
    Asset("EQIX", "Equinix",       "reit","public","Data Centers",     [], "^TNX"),
]

# Macro benchmarks (tracked but not ranked)
MACRO_SYMBOLS = ["SPY", "DXY", "^VIX", "^TNX"]

# ── Trial subset (15 assets for free-trial runs) ──────────────────────────────
TRIAL_SYMBOLS: list[str] = [
    "NVDA", "AAPL", "TSLA", "META", "AMD",   # stocks
    "BTC", "ETH", "SOL", "AVAX",              # crypto
    "GLD", "USO",                             # commodities
    "VNQ", "O",                               # REITs
    "MSFT", "PLTR",                           # extra stocks
]

def get_active_assets() -> list[Asset]:
    """Returns the asset list appropriate for the current run mode."""
    if FREE_TRIAL_MODE:
        return [a for a in FULL_WATCHLIST if a.symbol in TRIAL_SYMBOLS]
    return [a for a in FULL_WATCHLIST if a.board == "public"]

# ─────────────────────────────────────────────────────────────────────────────
# RSS feed list
# ─────────────────────────────────────────────────────────────────────────────
RSS_FEEDS: list[dict] = [
    # Tier 1 — Major financial news
    {"url": "https://feeds.reuters.com/reuters/businessNews",         "source": "reuters.com",    "tier": 1.0},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",  "source": "cnbc.com",       "tier": 0.8},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories",   "source": "marketwatch.com","tier": 0.8},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135", "source": "cnbc.com", "tier": 0.8},
    # Tier 2 — Crypto
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/",        "source": "coindesk.com",   "tier": 0.7},
    {"url": "https://decrypt.co/feed",                                 "source": "decrypt.co",     "tier": 0.7},
    # Tier 3 — Analysis
    {"url": "https://seekingalpha.com/market_currents.xml",           "source": "seekingalpha.com","tier": 0.5},
    # Tier 4 — Regulatory
    {"url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&dateb=&owner=include&count=40&output=atom", "source": "sec.gov", "tier": 0.9},
    {"url": "https://www.cftc.gov/rss/pressreleases",                 "source": "cftc.gov",       "tier": 0.9},
]

# ─────────────────────────────────────────────────────────────────────────────
# Reddit subreddits
# ─────────────────────────────────────────────────────────────────────────────
SUBREDDITS: list[str] = [
    "wallstreetbets", "investing", "stocks", "StockMarket", "options",
    "CryptoCurrency", "Bitcoin", "ethereum", "defi", "altcoin",
    "RealEstate", "REBubble", "economics", "startups", "financialindependence",
]
REDDIT_POSTS_PER_SUB: int = 50

# ─────────────────────────────────────────────────────────────────────────────
# Hard filters for investability
# ─────────────────────────────────────────────────────────────────────────────
MIN_MARKET_CAP_STOCK: float  = 500e6   # $500M
MIN_MARKET_CAP_CRYPTO: float = 50e6    # $50M
MIN_DATA_SOURCES: int = 3

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
import pathlib
ROOT_DIR = pathlib.Path(__file__).parent.parent
DB_PATH  = ROOT_DIR / "sentinel.db"
LOGS_DIR = ROOT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
