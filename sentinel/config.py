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

# New API keys (Phase 1-3 enhancements)
EIA_API_KEY: str = os.getenv("EIA_API_KEY", "")
ACLED_EMAIL: str = os.getenv("ACLED_EMAIL", "")
ACLED_PASSWORD: str = os.getenv("ACLED_PASSWORD", "")
NASA_FIRMS_API_KEY: str = os.getenv("NASA_FIRMS_API_KEY", "")
CLOUDFLARE_RADAR_TOKEN: str = os.getenv("CLOUDFLARE_RADAR_TOKEN", "")

# ─────────────────────────────────────────────────────────────────────────────
# Scraper endpoint URLs
# ─────────────────────────────────────────────────────────────────────────────
ARCTICSHIFT_BASE: str = "https://arctic-shift.photon-reddit.com/api"
SCRAPINGDOG_TWITTER_URL: str = "https://api.scrapingdog.com/twitter/"
STOCKTWITS_BASE: str = "https://api.stocktwits.com/api/2"

STOCKTWITS_SYMBOL_MAP: dict[str, str] = {
    "BTC": "BTC.X", "ETH": "ETH.X", "SOL": "SOL.X", "AVAX": "AVAX.X",
    "LINK": "LINK.X", "DOT": "DOT.X", "MATIC": "MATIC.X",
    "ARB": "ARB.X", "OP": "OP.X", "NEAR": "NEAR.X",
    "SUI": "SUI.X", "INJ": "INJ.X", "RENDER": "RNDR.X",
    "FET": "FET.X", "APT": "APT.X",
}

# New data source URLs (WorldMonitor audit enhancements)
POLYMARKET_API: str = "https://gamma-api.polymarket.com/events"
KALSHI_API: str = "https://api.elections.kalshi.com/trade-api/v2/events"
USGS_EARTHQUAKE_URL: str = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
EIA_API_BASE: str = "https://api.eia.gov/v2/seriesid"
ACLED_TOKEN_URL: str = "https://acleddata.com/oauth/token"
ACLED_API_URL: str = "https://acleddata.com/api/acled/read"
NASA_FIRMS_URL: str = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
CLOUDFLARE_RADAR_URL: str = "https://api.cloudflare.com/client/v4/radar/annotations/outages"
YAHOO_FINANCE_URL: str = "https://query1.finance.yahoo.com/v8/finance/chart"

# EIA series IDs for energy data
EIA_SERIES: dict[str, dict] = {
    "PET.RWTC.W":     {"symbol": "USO", "name": "WTI Crude Oil spot (weekly)"},
    "PET.RBRTE.W":    {"symbol": "USO", "name": "Brent Crude Oil spot (weekly)"},
    "PET.WCRFPUS2.W": {"symbol": "USO", "name": "US Crude Production (weekly)", "type": "production"},
    "PET.WCESTUS1.W": {"symbol": "USO", "name": "US Crude Inventory (weekly)", "type": "inventory"},
}
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
    "news_sentiment":          0.11,   # 26 RSS feeds incl. wire services
    "social_sentiment":        0.09,   # Twitter + Reddit 3-tier cascades
    "sentiment_shift":         0.07,   # derivative of above two
    "volume_anomaly":          0.12,   # Finnhub + EIA inventory/production for energy
    "momentum_score":          0.11,   # RSI/MACD/BB from AV + Yahoo fallback
    "correlation_divergence":  0.07,   # needs 30d+ history, bootstrap penalty
    "risk_adjusted_liquidity": 0.09,   # vol, illiquidity, drawdown, small-cap
    "regulatory_signal":       0.10,   # 32 tiered keywords + Polymarket regulatory markets
    "competitor_edge":         0.05,   # peer-relative, narrower scope
    "geopolitical_flow":       0.12,   # GDELT + ACLED + Polymarket + USGS + FIRMS + Cloudflare
    "catalyst_freshness":      0.07,   # recency × source tier × uniqueness
}  # sum = 1.00

# ─────────────────────────────────────────────────────────────────────────────
# Source tier weights (for news quality scoring)
# ─────────────────────────────────────────────────────────────────────────────
SOURCE_TIERS: dict[str, float] = {
    "ft.com":            1.0,
    "bloomberg.com":     1.0,
    "reuters.com":       1.0,
    "reutersagency.com": 1.0,
    "apnews.com":        1.0,
    "wsj.com":           0.9,
    "cnbc.com":          0.8,
    "marketwatch.com":   0.8,
    "bbc.co.uk":         0.8,
    "npr.org":           0.7,
    "theguardian.com":   0.7,
    "coindesk.com":      0.7,
    "theblock.co":       0.7,
    "decrypt.co":        0.7,
    "cointelegraph.com": 0.6,
    "seekingalpha.com":  0.5,
    "zerohedge.com":     0.4,
    "finnhub":           0.8,
    "fmp":               0.7,
    "tiingo":            0.6,
    "reddit":            0.3,
    "twitter":           0.2,
    "oilprice.com":      0.6,
    "google-news-metals": 0.6,
    "investing.com":     0.6,
    "eia.gov":           0.8,
    "aljazeera.com":     0.6,
    "france24.com":      0.6,
    "scmp.com":          0.6,
    "nikkei.com":        0.7,
    "spglobal.com":      0.8,
}

# ─────────────────────────────────────────────────────────────────────────────
# Tiered keyword taxonomy (WorldMonitor-inspired)
# ─────────────────────────────────────────────────────────────────────────────

GEOPOLITICAL_KEYWORDS: dict[str, dict] = {
    "critical": {
        "keywords": [
            "declaration of war", "armed invasion", "military coup", "nuclear",
            "economic collapse", "martial law", "government overthrown",
        ],
        "weight": 1.0,
        "confidence": 0.9,
    },
    "high": {
        "keywords": [
            "military mobilization", "border conflict", "ceasefire broken",
            "financial sanctions imposed", "currency crisis", "sovereign default",
            "major cyberattack", "power grid attack", "embassy attack",
            "mass casualty", "infrastructure attack",
        ],
        "weight": 0.7,
        "confidence": 0.7,
    },
    "medium": {
        "keywords": [
            "trade sanctions", "diplomatic expulsion", "border closure",
            "arms deal", "protest crackdown", "bank run", "credit downgrade",
            "tariff increase", "supply chain disruption", "military exercise",
        ],
        "weight": 0.4,
        "confidence": 0.5,
    },
    "low": {
        "keywords": [
            "diplomatic tension", "trade dispute", "defense spending",
            "opposition protest", "price controls", "export restriction",
            "military parade",
        ],
        "weight": 0.2,
        "confidence": 0.3,
    },
}

REGULATORY_KEYWORDS: dict[str, dict] = {
    "critical": {
        "keywords": [
            "sec charges", "fraud charges", "criminal indictment",
            "exchange delisted", "trading halted", "ponzi scheme",
            "emergency ban", "asset seizure",
        ],
        "weight": 1.0,
    },
    "high": {
        "keywords": [
            "sec lawsuit", "enforcement action", "cease and desist",
            "etf approved", "etf rejected", "fine imposed",
            "regulatory crackdown", "subpoena issued", "settlement reached",
        ],
        "weight": 0.7,
    },
    "medium": {
        "keywords": [
            "regulation proposed", "etf filing", "compliance review",
            "executive order", "stablecoin regulation", "mica",
            "cftc investigation", "esma guidance", "congressional hearing",
        ],
        "weight": 0.4,
    },
    "low": {
        "keywords": [
            "regulatory update", "compliance", "policy review",
            "comment period", "public consultation", "draft legislation",
        ],
        "weight": 0.2,
    },
}

EXCLUSION_KEYWORDS: list[str] = [
    "celebrity", "entertainment", "sports", "box office", "album release",
    "movie review", "fashion", "dating", "relationship", "gossip",
    "concert", "reality tv", "award show", "red carpet",
]

# ─────────────────────────────────────────────────────────────────────────────
# Geo-proximity zones for disaster -> asset mapping
# ─────────────────────────────────────────────────────────────────────────────

# Each zone: (lat, lon, radius_km, affected_assets)
PRODUCTION_ZONES: list[tuple[float, float, float, list[str]]] = [
    # Copper: Chile, Peru, DRC, Zambia
    (-23.5, -70.5, 800, ["CPER"]),        # Northern Chile (Antofagasta)
    (-15.0, -75.0, 600, ["CPER"]),        # Southern Peru
    (-5.0,  27.0,  500, ["CPER"]),        # DRC copper belt
    # Gold: South Africa, Australia, Nevada
    (-26.0, 28.0,  400, ["GLD", "SLV"]),  # Witwatersrand, SA
    (-31.0, 121.0, 600, ["GLD"]),         # Western Australia
    (40.8, -117.0, 300, ["GLD", "SLV"]),  # Nevada
    # Oil/Gas: Middle East, Gulf of Mexico, North Sea
    (26.0,  50.0,  800, ["USO", "UNG"]),  # Persian Gulf
    (28.0, -90.0,  500, ["USO", "UNG"]),  # Gulf of Mexico
    (58.0,   2.0,  400, ["USO", "UNG"]),  # North Sea
    (62.0,  70.0,  600, ["USO", "UNG"]),  # Western Siberia
    # Semiconductors: Taiwan, South Korea
    (24.0, 121.0,  200, ["NVDA", "AMD", "AVGO"]),  # Taiwan (TSMC)
    (37.0, 127.0,  200, ["NVDA", "AMD"]),           # South Korea (Samsung)
    # Real estate: California, Tokyo
    (36.0, -119.0, 400, ["VNQ"]),         # California
    (35.7, 139.7,  200, ["VNQ"]),         # Tokyo
]

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


# ─────────────────────────────────────────────────────────────────────────────
# Asset keyword matching (for text mention detection)
# ─────────────────────────────────────────────────────────────────────────────
_ASSET_ALIASES: dict[str, list[str]] = {
    # Commodities — match by underlying, not ETF name
    "GLD":  ["gold"],
    "SLV":  ["silver"],
    "USO":  ["crude oil", "wti", "brent", "oil price"],
    "UNG":  ["natural gas", "nat gas", "henry hub"],
    "CPER": ["copper"],
    # REITs
    "VNQ":  ["real estate", "reit"],
    "O":    ["realty income"],
    # Crypto
    "BTC":  ["bitcoin", "btc"],
    "ETH":  ["ethereum", "eth"],
    "SOL":  ["solana"],
    "AVAX": ["avalanche"],
}


def get_match_keywords(asset: "Asset") -> list[str]:
    """Returns lowercase keywords to detect this asset in free text."""
    terms = [asset.symbol.lower(), asset.name.lower()]
    if asset.sector:
        terms.append(asset.sector.lower())
    terms.extend(_ASSET_ALIASES.get(asset.symbol, []))
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


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
    Asset("GLD",  "SPDR Gold",     "commodity","public","Gold",      ["SLV","CPER"], "DXY"),
    Asset("SLV",  "iShares Silver","commodity","public","Silver",    ["GLD","CPER"], "DXY"),
    Asset("USO",  "US Oil Fund",   "commodity","public","Crude Oil", ["UNG"],        "DXY"),
    Asset("UNG",  "US Nat Gas",    "commodity","public","Nat Gas",   ["USO"],        "DXY"),
    Asset("CPER", "US Copper",     "commodity","public","Copper",    ["GLD","SLV"],  "DXY"),
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
    # ── Tier 1 — Wire services (highest quality) ─────────────────────────────
    {"url": "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best", "source": "reutersagency.com", "tier": 1.0},
    {"url": "https://rsshub.app/apnews/topics/business",               "source": "apnews.com",      "tier": 1.0},
    {"url": "https://feeds.bloomberg.com/markets/news.rss",            "source": "bloomberg.com",   "tier": 1.0},
    # ── Tier 1 — Major financial ─────────────────────────────────────────────
    {"url": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB", "source": "google-news-business", "tier": 0.8},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",   "source": "cnbc.com",        "tier": 0.8},
    {"url": "https://feeds.marketwatch.com/marketwatch/topstories",    "source": "marketwatch.com", "tier": 0.8},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135", "source": "cnbc.com", "tier": 0.8},
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml",         "source": "bbc.co.uk",       "tier": 0.8},
    {"url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",          "source": "wsj.com",         "tier": 0.9},
    {"url": "https://feeds.npr.org/1006/rss.xml",                     "source": "npr.org",         "tier": 0.7},
    {"url": "https://www.theguardian.com/uk/business/rss",             "source": "theguardian.com", "tier": 0.7},
    # ── Tier 2 — Crypto / DeFi ──────────────────────────────────────────────
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/",         "source": "coindesk.com",    "tier": 0.7},
    {"url": "https://decrypt.co/feed",                                  "source": "decrypt.co",      "tier": 0.7},
    {"url": "https://www.theblock.co/rss/all",                         "source": "theblock.co",     "tier": 0.7},
    {"url": "https://cointelegraph.com/rss",                           "source": "cointelegraph.com", "tier": 0.6},
    # ── Tier 2 — Geopolitical (new category) ─────────────────────────────────
    {"url": "https://www.aljazeera.com/xml/rss/all.xml",               "source": "aljazeera.com",   "tier": 0.6},
    {"url": "https://www.france24.com/en/rss",                         "source": "france24.com",    "tier": 0.6},
    {"url": "https://www.scmp.com/rss/4/feed",                        "source": "scmp.com",        "tier": 0.6},
    # ── Tier 3 — Analysis ────────────────────────────────────────────────────
    {"url": "https://seekingalpha.com/market_currents.xml",            "source": "seekingalpha.com", "tier": 0.5},
    # ── Tier 4 — Regulatory ──────────────────────────────────────────────────
    {"url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&dateb=&owner=include&count=40&output=atom", "source": "sec.gov", "tier": 0.9},
    {"url": "https://www.cftc.gov/PressRoom/PressReleases/rss.xml",   "source": "cftc.gov",        "tier": 0.9},
    # ── Tier 2 — Commodities / Energy / Metals ───────────────────────────────
    {"url": "https://oilprice.com/rss/main",                           "source": "oilprice.com",    "tier": 0.7},
    {"url": "https://news.google.com/rss/search?q=gold+silver+copper+metals+mining&hl=en-US&gl=US&ceid=US:en", "source": "google-news-metals", "tier": 0.6},
    {"url": "https://www.investing.com/rss/commodities.rss",           "source": "investing.com",   "tier": 0.6},
    {"url": "https://www.eia.gov/rss/todayinenergy.xml",               "source": "eia.gov",         "tier": 0.8},
    {"url": "https://www.spglobal.com/commodityinsights/en/rss-feed",  "source": "spglobal.com",    "tier": 0.8},
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
