# Context Enrichment Pipeline — Design Spec
**Date:** 2026-06-25
**Status:** Approved

---

## Overview

Improve the quality of Claude's morning briefing analysis by enriching the context it receives before each API call. Currently Claude receives only raw price data, commodity values, forex rates, and RSS headlines. This spec adds a structured enrichment pipeline that injects company domain knowledge, past pick performance, MASI trend history, Reddit community sentiment, and richer news sources — all before the prompt is built.

---

## Goal

Give Claude enough BVC-specific domain knowledge and historical context that it can produce investment picks grounded in company fundamentals, sector sensitivities, and its own track record — rather than re-deriving everything from scratch each morning.

---

## Architecture

An `enrichment/` layer is inserted between data collection and prompt building. Each enricher is an independent module with a single interface: it receives the context dict, adds its data, and returns the enriched dict. Any enricher that fails logs a warning and returns the context unchanged — the briefing always sends.

### Data Flow

```
collectors/ → raw context dict
            → enrichment pipeline (company_profiles, sector_map, outcome_tracker, masi_history, reddit)
            → enriched context dict
            → agent/prompts.py → Claude API → analysis
                                                    ↓
                                     outcome_tracker.record_picks() → DB
            → delivery/email.py
```

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `enrichment/company_profiles.py` | Loads `knowledge/company_profiles.json`, attaches profile to each stock in context |
| `enrichment/sector_map.py` | Loads `knowledge/sector_map.json`, injects sector-macro sensitivity table |
| `enrichment/outcome_tracker.py` | Reads past 30-day picks from DB pre-analysis; writes today's picks post-analysis |
| `enrichment/masi_history.py` | Reads `masi_daily` DB table, injects 30/90-day trend and 52-week high/low |
| `enrichment/reddit.py` | Fetches r/Maroc, r/Morocco, r/investing via PRAW; filters and injects top discussions |
| `knowledge/company_profiles.json` | Static profiles for all 26 BVC-listed stocks |
| `knowledge/sector_map.json` | Sector → macro factor sensitivity map |
| `scripts/seed_history.py` | One-time script to backfill 6 months of BVC price history and MASI values into DB |

### Modified files

| Path | Change |
|---|---|
| `storage/db.py` | Add `ai_picks` and `masi_daily` tables |
| `collectors/bvc.py` | Write MASI value to `masi_daily` table on each successful fetch |
| `collectors/news.py` | Add new RSS feeds; add AMMC and Bank Al-Maghrib press release scrapers |
| `scheduler/jobs.py` | Wire enrichment pipeline into `run_morning_briefing`; call `outcome_tracker.record_picks()` after analysis |
| `agent/prompts.py` | Update system prompt and template to consume enriched context blocks |
| `config.py` | Add Reddit credentials, new RSS feed URLs, enrichment constants |
| `requirements.txt` | Add `praw>=7.7` |

---

## Enrichment Modules

### 1. Company Profiles (`enrichment/company_profiles.py`)

Loads `knowledge/company_profiles.json` at module level (once, not on every call). For each stock present in the collected BVC data, attaches its profile under a `"profile"` key on the stock object.

**Profile schema per company:**

```json
{
  "OCP": {
    "sector": "Mining / Fertilizers",
    "description": "World's largest phosphate exporter. State-controlled. Revenues USD-denominated.",
    "key_drivers": ["phosphate spot price", "DAP/MAP fertilizer demand", "USD/MAD rate"],
    "risks": ["commodity price cycles", "global food demand slowdowns", "energy cost spikes"],
    "macro_sensitivity": {
      "dirham_weakness": "positive — export revenues convert to more MAD",
      "oil_rise": "negative — energy-intensive production process",
      "global_recession": "negative — fertilizer demand falls with agricultural cutbacks"
    }
  }
}
```

Profiles are written for all 26 BVC-listed companies covering: banking (ATW, BCP, BMCE, CIH, BMCI, CDM), telecom (IAM), mining (OCP, Managem), cement (Lafarge, CIMAR), energy (TotalEnergies Maroc), real estate (Addoha, Alliances), retail (Label'Vie), insurance (Wafa Assurance, Atlanta), ports (Marsa Maroc), hotels (Risma), fintech (HPS), steel (Sonasid), sugar (Cosumar).

If a stock has no profile (e.g. a newly listed company), the enricher skips it silently.

---

### 2. Sector Map (`enrichment/sector_map.py`)

Loads `knowledge/sector_map.json`. Injected once as a top-level key `"sector_map"` in the context. Claude uses this as a lookup when the prompt instructs it to cross-reference today's macro moves against sector sensitivities.

**Schema:**

```json
{
  "Banking": {
    "stocks": ["ATW", "BCP", "BMCE", "CIH", "BMCI", "CDM"],
    "sensitive_to": ["Bank Al-Maghrib rate", "credit growth", "EUR/MAD", "sovereign rating"],
    "rate_hike_impact": "negative short-term — cost of funds rises",
    "dirham_weakness_impact": "mixed — import financing costs rise, export client revenues benefit"
  },
  "Mining / Fertilizers": {
    "stocks": ["OCP", "MNG"],
    "sensitive_to": ["phosphate price", "copper price", "gold price", "USD/MAD"],
    "oil_rise_impact": "negative — energy-intensive operations",
    "dirham_weakness_impact": "positive — USD/EUR-denominated export revenues"
  }
}
```

---

### 3. Outcome Tracker (`enrichment/outcome_tracker.py`)

**Pre-analysis (read phase):**

Queries the `ai_picks` DB table for all picks from the last 30 days. For each pick, compares `price_at_pick` to the stock's current price in today's collected data. Computes `change_pct` and a simple directional accuracy label (correct/incorrect for BUY and AVOID; neutral for WATCH).

Injects into context:

```json
{
  "past_performance": {
    "window_days": 30,
    "picks": [
      {"ticker": "OCP", "date": "2026-06-10", "pick": "BUY", "price_at_pick": 258.0, "current_price": 268.5, "change_pct": 4.07, "outcome": "correct"},
      {"ticker": "ATW", "date": "2026-06-18", "pick": "WATCH", "price_at_pick": 685.0, "current_price": 672.0, "change_pct": -1.90, "outcome": "neutral"}
    ],
    "accuracy_summary": "BUY: 3 correct / 1 incorrect. AVOID: 2 correct / 0 incorrect."
  }
}
```

If fewer than 3 days of picks exist in DB (early operation), injects `{"past_performance": null}` and the prompt template skips the block.

**Post-analysis (write phase):**

Called from `scheduler/jobs.py` after `run_morning_analysis()` returns. Reads the `"ai_picks"` array from Claude's JSON response and inserts one row per pick into `ai_picks` with today's date and current price.

---

### 4. MASI History (`enrichment/masi_history.py`)

Reads the `masi_daily` table for the last 90 rows. Computes:
- `change_30d_pct` — percentage change from 30 trading days ago to today
- `change_90d_pct` — percentage change from 90 trading days ago to today
- `week52_high` / `week52_low` — from `masi_daily` if 252 rows exist, otherwise from available rows
- `trend` — derived label: "rising", "declining", or "flat" based on 30-day direction

Injects as the `"masi"` key (replacing the current bare `{"value": ...}` dict).

If `masi_daily` has fewer than 5 rows, falls back to the current bare value with no trend data — same silent-fail pattern.

---

### 5. Reddit (`enrichment/reddit.py`)

PRAW read-only client (no posting). Credentials stored in `.env` as `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`.

**Subreddits fetched:** `r/Maroc`, `r/Morocco`, `r/investing`

**Filter:** Posts from the last 24 hours containing at least one keyword from a defined list: BVC ticker symbols, "bourse", "MASI", "OCP", "Maroc", "investissement", "action", "marché", "phosphate", "dirham", plus English equivalents.

**Per post:** title, upvote score, subreddit, URL, top 3 top-level comments (sorted by score descending).

**Per comment:** text, score, plus notable replies filtered by score ≥ 3 AND length ≥ 40 characters, capped at 3 replies per comment.

**Cap:** Maximum 8 posts total across all three subreddits. If a subreddit is unreachable, skip it and continue with the others.

**Output key:** `"reddit_discussions"` — list of post objects as described above.

---

## Data Layer

### New DB tables (`storage/db.py`)

```sql
CREATE TABLE IF NOT EXISTS ai_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    pick TEXT NOT NULL,
    price_at_pick REAL,
    reasoning TEXT
);

CREATE TABLE IF NOT EXISTS masi_daily (
    date TEXT PRIMARY KEY,
    value REAL NOT NULL,
    change_pct REAL
);
```

Both tables are created in `init_db()` alongside existing tables.

### MASI daily write

`collectors/bvc.py` — after a successful `_fetch_masi()` call, inserts one row into `masi_daily` for today's date using `INSERT OR IGNORE` (safe to re-run).

### History seeding (`scripts/seed_history.py`)

One-time script. Fetches 6 months of per-ticker OHLCV data from casablanca-bourse.com historical data pages and inserts into the existing `price_history` table using `INSERT OR IGNORE`. Also backfills `masi_daily` for the same window. Prints progress per ticker. Safe to re-run — already-existing rows are skipped.

Invoked via:

```makefile
seed-history:
    $(PYTHON) scripts/seed_history.py
```

---

## News Sources

### New RSS feeds added to `config.py`

```python
RSS_FEEDS = [
    # existing
    {"name": "Google News Maroc", "url": "https://news.google.com/rss/search?q=bourse+maroc&hl=fr&gl=MA&ceid=MA:fr"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Medias24", "url": "https://medias24.com/feed"},
    {"name": "MAP", "url": "https://www.mapnews.ma/en/rss.xml"},
    # new
    {"name": "L'Économiste", "url": "https://www.leconomiste.com/rss.xml"},
    {"name": "TelQuel", "url": "https://telquel.ma/feed"},
    {"name": "Hespress Économie", "url": "https://fr.hespress.com/category/economie/feed"},
    {"name": "Google News OCP", "url": "https://news.google.com/rss/search?q=OCP+Maroc&hl=fr&gl=MA&ceid=MA:fr"},
]
```

### AMMC and Bank Al-Maghrib scrapers

These institutions publish press releases without RSS feeds. A dedicated scraper function in `collectors/news.py` fetches their press release listing pages (HTML), extracts the 5 most recent entries by date, and returns them normalized to `{"title", "summary", "source", "url", "published"}` — the same format as RSS articles. Failures are caught and logged; the rest of news collection continues unaffected.

---

## Prompt Changes (`agent/prompts.py`)

### System prompt addition

Appended to `MORNING_BRIEFING_SYSTEM`:

> You have access to structured company profiles describing each BVC stock's business model, key revenue drivers, and macro sensitivities. Use these when explaining why a macro event (e.g. rising oil, weak dirham) affects a specific company. You also have a record of your past pick performance over the last 30 days — factor this into your confidence level. Reddit discussions reflect retail investor sentiment in Morocco — treat them as a supplementary signal, not a primary one.

### Template additions to `build_morning_briefing_prompt`

Four new context blocks injected before the JSON market data blob, each conditionally rendered (skipped if the data is absent):

**Block 1 — Company profiles** (rendered per watchlist stock):
```
COMPANY PROFILES:
OCP: Phosphate exporter. Revenue USD-denominated. Moves with DAP/MAP fertilizer prices. Dirham weakness is a tailwind.
ATW: Largest Moroccan bank. Sensitive to BAM rate decisions and credit growth.
MNG: Mining — copper, gold, cobalt. Correlated to commodity prices and EV battery demand.
```

**Block 2 — Sector sensitivities** (rendered from sector_map, cross-referenced with today's macro moves):
```
SECTOR CONTEXT (today's macro):
Banking: EUR/MAD +3.42% → mixed impact (import financing costs rise, export clients benefit)
Mining: copper +2.66%, gold +1.53% → positive signal for OCP, Managem
```

**Block 3 — Past pick performance** (skipped if `past_performance` is null):
```
YOUR PAST 30-DAY PERFORMANCE:
BUY picks: 3 correct / 1 incorrect
AVOID picks: 2 correct / 0 incorrect
Recent miss: ATW WATCH at 685 → -1.9% after 7 days (data was unavailable at time of pick)
```

**Block 4 — Reddit sentiment** (skipped if `reddit_discussions` is empty):
```
REDDIT SENTIMENT (last 24h):
[r/Maroc, 142 upvotes] "OCP résultats semestriels positifs"
  → "Bénéfices +12% grâce aux prix du phosphate" (45 upvotes)
     ↳ "Expansion Afrique subsaharienne mentionnée dans le call" (11 upvotes)
  → "Le cours est déjà bien valorisé à 261 MAD" (32 upvotes)
```

---

## Error Handling

All enrichers follow the same pattern: wrap the entire enrichment body in try/except, log a warning with the enricher name and error, and return the context dict unchanged. The morning briefing pipeline in `scheduler/jobs.py` calls enrichers sequentially — a failure in one does not prevent subsequent enrichers from running.

---

## Testing

- `tests/enrichment/test_company_profiles.py` — profile lookup returns correct data; missing ticker returns stock unchanged
- `tests/enrichment/test_outcome_tracker.py` — correct/incorrect accuracy calculation; null return when < 3 days of data
- `tests/enrichment/test_masi_history.py` — trend computation; graceful fallback with < 5 rows
- `tests/enrichment/test_reddit.py` — reply filtering (score < 3 and length < 40 excluded); cap at 8 posts; single subreddit failure does not break others
- All existing tests continue to pass unchanged

---

## Environment Variables Added

```env
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USER_AGENT=Mizan/1.0 by ahmedennaime20@gmail.com
```

---

## Out of Scope

- Web dashboard or UI for reviewing past picks
- Automatic retraining or fine-tuning of the Claude model
- Telegram or push notifications (Phase 2)
- Sentiment scoring / NLP classification of Reddit posts (plain text passed to Claude as-is)
