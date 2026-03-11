# SENTINEL — Free Trial Run Plan
## 4 Full Workflow Runs at $0

---

## Credit Inventory

| Service | Keys | Credits/Key | Total |
|---|---|---|---|
| Scrapingdog | 3 | 1,000 | **3,000** |
| Firecrawl | 2 | ~500 | **~1,000** |

> Firecrawl free plan: ~500 credits/month per account. Confirm actual amount when signing up.

---

## Per-Run Budget

### Scrapingdog
- Total: 3,000 credits ÷ 4 runs = **750 credits/run**
- 750 credits ÷ 5 credits/tweet = **150 tweets/run**
- Configuration: **15 assets × 10 tweets/asset** (down from 50 assets × 20 in production)

### Firecrawl
- Per run: 50 articles × 1 credit = **50 credits/run**
- 4 runs × 50 = **200 credits total**
- Key 1 alone covers all 4 runs. Key 2 is pure backup.

---

## Asset Subset — 15 Assets (Representative Mix)

Pick 15 from the full watchlist covering all asset classes so every pipeline branch is exercised:

| Class | Count | Examples |
|---|---|---|
| US Equities | 5 | NVDA, AAPL, TSLA, MSFT, META |
| Crypto | 4 | BTC, ETH, SOL, BNB |
| Commodities | 2 | Gold (GLD), Oil (USO) |
| ETFs / Macro | 2 | SPY, QQQ |
| International / Other | 2 | your choice |

> This ensures sentiment, scoring, normalization, and email rendering all run end-to-end — not just for one asset class.

---

## Key Rotation Strategy

### Scrapingdog — 3 Keys

| Run | Key Used | Credits Spent | Credits Remaining on Key |
|---|---|---|---|
| Run 1 | Key 1 | 750 | 250 left |
| Run 2 | Key 2 | 750 | 250 left |
| Run 3 | Key 3 | 750 | 250 left |
| Run 4 | Keys 1+2+3 | 250+250+250 | 0 on all |

Enforce a hard per-run limit in code (`MAX_TWEETS_PER_RUN = 150`) so no single run accidentally bleeds into another key's budget.

### Firecrawl — 2 Keys

| Run | Key Used |
|---|---|
| Runs 1–4 | Key 1 (uses 200 of ~500 credits) |
| Backup | Key 2 (untouched unless Key 1 fails) |

No rotation needed. Key 2 is a fallback only.

---

## Environment Variable Setup

Rotate keys by setting them as env vars before each run. No code changes needed between runs.

```bash
# Run 1
SCRAPINGDOG_API_KEY=<key_1>
FIRECRAWL_API_KEY=<firecrawl_key_1>

# Run 2
SCRAPINGDOG_API_KEY=<key_2>
FIRECRAWL_API_KEY=<firecrawl_key_1>   # same key, still has budget

# Run 3
SCRAPINGDOG_API_KEY=<key_3>
FIRECRAWL_API_KEY=<firecrawl_key_1>

# Run 4 — split Scrapingdog across remaining balances
# Handle in code: start with Key 1 remainder, overflow to Key 2, then Key 3
SCRAPINGDOG_API_KEY_1=<key_1>          # 250 credits remaining
SCRAPINGDOG_API_KEY_2=<key_2>          # 250 credits remaining
SCRAPINGDOG_API_KEY_3=<key_3>          # 250 credits remaining
FIRECRAWL_API_KEY=<firecrawl_key_1>
```

> For Run 4, the scraper needs a simple key-fallback loop: exhaust Key 1 remainder → switch to Key 2 → switch to Key 3.

---

## What to Validate Each Run

| Run | Focus |
|---|---|
| 1 | Full pipeline fires end-to-end. Data lands in Supabase. Email renders correctly. |
| 2 | Scoring engine produces stable z-scores. No division-by-zero or NaN in normalization. |
| 3 | Signal weights and ranking logic. Confirm top-10 email order makes intuitive sense. |
| 4 | Accuracy scorecard / self-correction loop. Previous predictions get scored. |

---

## Hard Limits to Add in Code

```python
# sentinel/config.py
MAX_ASSETS_FREE_TRIAL = 15
MAX_TWEETS_PER_ASSET  = 10
MAX_ARTICLES_FIRECRAWL = 50  # unchanged from production

SCRAPINGDOG_KEYS = [
    os.getenv("SCRAPINGDOG_API_KEY_1"),
    os.getenv("SCRAPINGDOG_API_KEY_2"),
    os.getenv("SCRAPINGDOG_API_KEY_3"),
]
```

Use a `FREE_TRIAL_MODE = True` flag in config that swaps `MAX_ASSETS` and `MAX_TWEETS_PER_ASSET` to trial values at runtime. Flip to `False` when going to production with paid keys.

---

## Credit Burn Summary

| Service | Budget | Used | Leftover |
|---|---|---|---|
| Scrapingdog | 3,000 | 3,000 | 0 |
| Firecrawl | ~1,000 | 200 | ~800 |

The ~800 leftover Firecrawl credits can be used for additional testing or debugging individual articles.
