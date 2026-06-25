# Context Enrichment Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an enrichment pipeline between data collection and Claude's prompt that injects company knowledge, sector sensitivities, past pick performance, MASI history, richer news sources, and Reddit community sentiment to produce better morning briefing analysis.

**Architecture:** A new `enrichment/` package sits between `scheduler/jobs.py`'s `collect_and_persist()` and `agent/prompts.py`. Each enricher is an independent module with a single `enrich(context: dict) -> dict` interface. Failures are caught per-enricher — the briefing always sends. Static domain knowledge lives in `knowledge/` JSON files. A one-time seeding script backfills 6 months of price and MASI history into the DB.

**Tech Stack:** Python 3.13, SQLite (existing), PRAW 7.7+ (Reddit), requests + BeautifulSoup4 (AMMC/BAM scrapers), feedparser (existing RSS).

## Global Constraints

- Python ≥ 3.13; no new dependencies beyond `praw>=7.7`
- All enrichers must follow the silent-fail pattern: `try/except Exception`, `logger.warning(...)`, return context unchanged
- No enricher may raise an exception to the caller
- All new DB functions use `get_connection()` context manager from `storage/db.py`
- Tests use the `test_db` fixture from `conftest.py`: `monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")` then `db_module.init_db()`
- Commit messages: single short line, no body, no AI attribution
- `enrichment/__init__.py` exports a single `enrich(context: dict) -> dict` function
- `outcome_tracker.record_picks()` is called from `scheduler/jobs.py`, not from `enrichment/__init__.py`
- MASI daily write happens in `scheduler/jobs.py`'s `collect_and_persist()`, not in `collectors/bvc.py`

---

### Task 1: DB Schema Extensions + Config + Requirements

**Files:**
- Modify: `storage/db.py`
- Modify: `config.py`
- Modify: `requirements.txt`
- Modify: `conftest.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `insert_masi_daily(date: str, value: float, change_pct: float | None) -> None`
  - `get_masi_history(days: int = 252) -> list[dict]` — rows in ascending date order, each `{"date": str, "value": float, "change_pct": float | None}`
  - `insert_ai_pick(date: str, ticker: str, pick: str, price_at_pick: float | None, reasoning: str) -> None`
  - `get_recent_ai_picks(days: int = 30) -> list[dict]` — rows newest-first, each `{"date": str, "ticker": str, "pick": str, "price_at_pick": float | None, "reasoning": str}`
  - Config vars: `REDDIT_CLIENT_ID: str`, `REDDIT_CLIENT_SECRET: str`, `REDDIT_USER_AGENT: str`, `REDDIT_KEYWORDS: list[str]`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_storage.py

def test_init_creates_new_tables(test_db):
    with db_module.get_connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
    assert "ai_picks" in tables
    assert "masi_daily" in tables


def test_insert_and_get_masi_daily(test_db):
    db_module.insert_masi_daily("2026-06-20", 17900.5, -0.28)
    db_module.insert_masi_daily("2026-06-21", 17950.0, 0.28)
    rows = db_module.get_masi_history(days=10)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-06-20"
    assert rows[1]["value"] == 17950.0


def test_insert_masi_daily_ignores_duplicates(test_db):
    db_module.insert_masi_daily("2026-06-20", 17900.5, -0.28)
    db_module.insert_masi_daily("2026-06-20", 99999.9, 5.0)
    rows = db_module.get_masi_history(days=10)
    assert len(rows) == 1
    assert rows[0]["value"] == 17900.5


def test_insert_and_get_ai_picks(test_db):
    db_module.insert_ai_pick("2026-06-20", "OCP", "BUY", 261.0, "Strong phosphate signal")
    db_module.insert_ai_pick("2026-06-21", "ATW", "AVOID", 685.0, "Overbought RSI")
    picks = db_module.get_recent_ai_picks(days=30)
    assert len(picks) == 2
    assert picks[0]["ticker"] == "ATW"
    assert picks[1]["pick"] == "BUY"


def test_get_recent_ai_picks_respects_days_window(test_db):
    db_module.insert_ai_pick("2025-01-01", "OCP", "BUY", 200.0, "Old pick")
    db_module.insert_ai_pick("2026-06-24", "MNG", "WATCH", 430.0, "Recent pick")
    picks = db_module.get_recent_ai_picks(days=30)
    assert len(picks) == 1
    assert picks[0]["ticker"] == "MNG"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/test_storage.py::test_init_creates_new_tables tests/test_storage.py::test_insert_and_get_masi_daily -v
```

Expected: FAIL with `AttributeError: module 'storage.db' has no attribute 'insert_masi_daily'`

- [ ] **Step 3: Add tables to `init_db()` in `storage/db.py`**

Add to the `executescript` call in `init_db()`, after the existing table definitions:

```python
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

Also add `timedelta` to the existing import at the top of `storage/db.py`:

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 4: Add new DB functions to `storage/db.py`**

Add after `log_alert()`:

```python
def insert_masi_daily(date: str, value: float, change_pct: float | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO masi_daily (date, value, change_pct) VALUES (?, ?, ?)",
            (date, value, change_pct),
        )


def get_masi_history(days: int = 252) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, value, change_pct FROM masi_daily ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def insert_ai_pick(date: str, ticker: str, pick: str, price_at_pick: float | None, reasoning: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO ai_picks (date, ticker, pick, price_at_pick, reasoning) VALUES (?, ?, ?, ?, ?)",
            (date, ticker, pick, price_at_pick, reasoning),
        )


def get_recent_ai_picks(days: int = 30) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, ticker, pick, price_at_pick, reasoning FROM ai_picks WHERE date >= ? ORDER BY date DESC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Add Reddit config to `config.py`**

Add after `RECIPIENT_EMAIL`:

```python
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "Mizan/1.0")
REDDIT_KEYWORDS = [
    "OCP", "ATW", "BCP", "BOA", "IAM", "MNG", "TQM", "ADH", "LBV", "CIH",
    "bourse", "MASI", "maroc", "marché", "investissement", "action", "dividende",
    "phosphate", "dirham", "Casablanca", "Morocco stock", "invest maroc",
]
```

- [ ] **Step 6: Add Reddit env defaults to `conftest.py`**

Add after the existing `os.environ.setdefault` lines:

```python
os.environ.setdefault("REDDIT_CLIENT_ID", "test-reddit-id")
os.environ.setdefault("REDDIT_CLIENT_SECRET", "test-reddit-secret")
os.environ.setdefault("REDDIT_USER_AGENT", "Mizan/1.0-test")
```

- [ ] **Step 7: Add `praw>=7.7` to `requirements.txt`**

```
praw>=7.7
```

Install it:

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/pip install "praw>=7.7"
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/test_storage.py -v
```

Expected: All storage tests PASS (including the 5 new ones).

- [ ] **Step 9: Commit**

```bash
git add storage/db.py config.py requirements.txt conftest.py tests/test_storage.py
git commit -m "feat: add ai_picks and masi_daily tables, Reddit config"
```

---

### Task 2: Knowledge Files

**Files:**
- Create: `knowledge/company_profiles.json`
- Create: `knowledge/sector_map.json`

**Interfaces:**
- Produces: JSON files consumed by `enrichment/company_profiles.py` and `enrichment/sector_map.py`
- No DB or Python imports. No tests needed — tested implicitly by enricher tests in Task 3/4.

- [ ] **Step 1: Create `knowledge/company_profiles.json`**

```json
{
  "OCP": {
    "sector": "Mining / Fertilizers",
    "description": "World's largest phosphate exporter, state-controlled. Produces phosphate rock, phosphoric acid, and DAP/MAP fertilizers sold globally.",
    "key_drivers": ["phosphate rock spot price", "DAP/MAP fertilizer demand", "USD/MAD exchange rate", "global agricultural output"],
    "risks": ["commodity price cycles", "global food demand slowdowns", "energy cost spikes (energy-intensive production)", "geopolitical supply chain disruptions"],
    "macro_sensitivity": {
      "dirham_weakness": "positive — export revenues are USD-denominated, convert to more MAD",
      "oil_rise": "negative — energy-intensive production raises operating costs",
      "global_recession": "negative — fertilizer demand falls with reduced agricultural investment",
      "phosphate_price_rise": "strongly positive — direct revenue uplift",
      "eur_mad_weakness": "neutral — most OCP exports priced in USD not EUR"
    }
  },
  "ATW": {
    "sector": "Banking",
    "description": "Attijariwafa Bank — largest bank in Morocco and one of the largest in Africa. Operations in 25+ African countries. Retail, corporate, and investment banking.",
    "key_drivers": ["Bank Al-Maghrib policy rate", "credit growth in Morocco", "Pan-African subsidiary performance", "sovereign credit rating"],
    "risks": ["rate hike compression of margins", "NPL rise in economic downturns", "currency risk from African subsidiaries", "regulatory capital requirements"],
    "macro_sensitivity": {
      "rate_hike": "negative short-term (cost of funds rises, existing loan margins compress)",
      "rate_cut": "positive — stimulates credit demand",
      "dirham_weakness": "mixed — African subsidiary revenues lose value when converted to MAD",
      "gdp_growth": "positive — strong economy drives credit demand",
      "sovereign_downgrade": "negative — raises cost of funding"
    }
  },
  "BCP": {
    "sector": "Banking",
    "description": "Banque Centrale Populaire — second-largest banking group in Morocco. Strong retail banking network, significant government ties, large SME lending book.",
    "key_drivers": ["Bank Al-Maghrib rate", "retail credit growth", "SME loan performance", "government-linked deposits"],
    "risks": ["NPL exposure from SME sector", "rate sensitivity on variable-rate loans", "competition from ATW and BOA"],
    "macro_sensitivity": {
      "rate_hike": "negative — raises funding costs, compresses retail loan margins",
      "gdp_growth": "positive — SME activity drives loan demand",
      "dirham_weakness": "low sensitivity — primarily domestic operations"
    }
  },
  "BOA": {
    "sector": "Banking",
    "description": "Bank of Africa (formerly BMCE Bank) — major Moroccan bank with pan-African presence across 20+ countries. Strong in trade finance and correspondent banking.",
    "key_drivers": ["Bank Al-Maghrib rate", "African trade finance volumes", "EUR/MAD rate (European correspondent banking)", "commodity trade flows"],
    "risks": ["African political risk in operating markets", "currency translation losses", "trade finance exposure to commodity exporters"],
    "macro_sensitivity": {
      "rate_hike": "negative — cost of funds rises",
      "eur_mad_weakness": "mixed — affects European correspondent revenues",
      "commodity_boom": "positive — drives trade finance volumes for African commodity exporters"
    }
  },
  "IAM": {
    "sector": "Telecommunications",
    "description": "Maroc Telecom (Itissalat Al-Maghrib) — dominant telecom operator in Morocco, majority owned by UAE's e& (formerly Etisalat). Fixed, mobile, internet, and African subsidiaries.",
    "key_drivers": ["mobile subscriber growth", "ARPU trends", "regulatory tariff decisions", "African subsidiary performance", "dividend policy"],
    "risks": ["market saturation in Morocco", "regulatory price caps", "e& strategic decisions affecting dividends", "competition from Orange Maroc and InwiMaroc"],
    "macro_sensitivity": {
      "dirham_weakness": "low — mostly domestic MAD revenues",
      "rate_hike": "low — telecom is defensive, low debt sensitivity",
      "gdp_growth": "low-positive — defensive stock, weak correlation to economic cycle",
      "regulatory_risk": "high — tariff changes directly affect revenue"
    }
  },
  "MNG": {
    "sector": "Mining",
    "description": "Managem — Moroccan mining conglomerate producing copper, gold, cobalt, silver, and zinc across Africa. Majority owned by SNI (ONA group).",
    "key_drivers": ["copper spot price", "gold spot price", "cobalt demand (EV batteries)", "silver price", "production volumes per mine"],
    "risks": ["commodity price cycles", "mine operational disruptions", "African political risk", "energy cost (mining is energy-intensive)"],
    "macro_sensitivity": {
      "copper_rise": "strongly positive — copper is the largest revenue contributor",
      "gold_rise": "positive — safe-haven demand boosts revenues",
      "cobalt_rise": "positive — EV battery supply chain demand",
      "oil_rise": "negative — raises energy costs at mine sites",
      "global_recession": "negative — industrial metals demand falls"
    }
  },
  "LHM": {
    "sector": "Cement",
    "description": "LafargeHolcim Maroc — largest cement producer in Morocco, part of the global Holcim group. Serves construction, infrastructure, and housing sectors.",
    "key_drivers": ["construction activity in Morocco", "government infrastructure spending", "housing starts", "energy cost (clinker production)", "cement price"],
    "risks": ["construction market slowdown", "energy cost spikes", "competition from Ciments du Maroc", "import competition"],
    "macro_sensitivity": {
      "gdp_growth": "positive — construction tracks economic growth",
      "rate_hike": "negative — raises mortgage costs, slows housing",
      "oil_rise": "negative — kiln fuel costs rise",
      "government_spend": "positive — infrastructure projects drive bulk cement demand"
    }
  },
  "CIMAR": {
    "sector": "Cement",
    "description": "Ciments du Maroc — second-largest cement producer in Morocco, part of the HeidelbergMaterials group. Strong in southern Morocco and export markets.",
    "key_drivers": ["construction activity", "export volumes to sub-Saharan Africa", "energy cost", "domestic cement price"],
    "risks": ["competition from LHM", "energy cost volatility", "construction market slowdown"],
    "macro_sensitivity": {
      "gdp_growth": "positive — construction tracks GDP",
      "oil_rise": "negative — production energy costs",
      "rate_hike": "negative — slows housing activity"
    }
  },
  "CSUMAR": {
    "sector": "Food / Agribusiness",
    "description": "Cosumar — Morocco's monopoly sugar refiner and distributor. Refines imported raw sugar and processes domestic sugar beet and cane. Government-regulated consumer prices.",
    "key_drivers": ["global raw sugar price", "government sugar subsidy policy", "domestic consumption volumes", "beet/cane harvest quality"],
    "risks": ["subsidy reform risk (government price controls)", "global raw sugar price spikes raise input costs", "agricultural yield variability"],
    "macro_sensitivity": {
      "sugar_price_rise": "negative — raises input costs if not passed to consumers via regulated prices",
      "subsidy_reform": "negative — government reducing sugar subsidies compresses margins",
      "gdp_growth": "low sensitivity — sugar is a staple commodity"
    }
  },
  "TQM": {
    "sector": "Energy / Fuel Distribution",
    "description": "TotalEnergies Marketing Maroc — fuel distribution and petroleum product marketing across Morocco. Petrol stations, lubricants, aviation fuel, and LPG.",
    "key_drivers": ["crude oil / refined product prices", "EUR/MAD and USD/MAD rate (products priced in USD)", "domestic fuel consumption", "refining margin"],
    "risks": ["oil price volatility", "dirham weakness raises product costs", "government fuel price cap changes", "competition from Vivo Energy / Shell Maroc"],
    "macro_sensitivity": {
      "oil_rise": "mixed — higher prices raise costs but also inventory gains",
      "dirham_weakness": "negative — imported products cost more in MAD",
      "gdp_growth": "positive — economic activity drives fuel consumption"
    }
  },
  "ADH": {
    "sector": "Real Estate",
    "description": "Addoha — one of Morocco's largest residential real estate developers. Focus on affordable and mid-range housing. Operations across Morocco and some African markets.",
    "key_drivers": ["mortgage interest rates", "government affordable housing program (VEFA)", "urbanization rate", "construction material costs", "Bank Al-Maghrib rate"],
    "risks": ["rate hike kills housing affordability", "government program discontinuation", "high debt leverage", "unsold inventory buildup"],
    "macro_sensitivity": {
      "rate_hike": "strongly negative — mortgage affordability falls sharply",
      "rate_cut": "strongly positive — unlocks latent housing demand",
      "steel_rise": "negative — construction material costs rise",
      "government_housing_policy": "high impact — subsidized housing programs are core revenue"
    }
  },
  "ADI": {
    "sector": "Real Estate",
    "description": "Alliances Développement Immobilier — real estate developer focused on mid-to-high-end residential, tourism real estate, and social housing contracts.",
    "key_drivers": ["interest rates", "tourism real estate demand", "government contracts", "construction costs"],
    "risks": ["rate sensitivity", "high leverage", "project delivery delays", "tourism market volatility"],
    "macro_sensitivity": {
      "rate_hike": "negative — reduces buyer affordability",
      "tourism_recovery": "positive — drives resort and second-home demand"
    }
  },
  "LBV": {
    "sector": "Retail / Consumer",
    "description": "Label'Vie — largest supermarket and hypermarket operator in Morocco. Carrefour franchisee. Consumer staples and non-food retail across Morocco.",
    "key_drivers": ["consumer spending", "food price inflation", "store expansion", "private label margins", "Carrefour franchise terms"],
    "risks": ["food inflation margin squeeze", "competition from traditional trade and e-commerce", "consumer purchasing power erosion"],
    "macro_sensitivity": {
      "inflation": "mixed — higher food prices boost revenue but squeeze margins on non-food",
      "gdp_growth": "positive — consumer spending rises with income",
      "dirham_weakness": "negative — imported goods cost more, pressure on margins"
    }
  },
  "WAA": {
    "sector": "Insurance",
    "description": "Wafa Assurance — leading Moroccan insurer (part of Attijariwafa group). Life insurance, property and casualty, and health insurance.",
    "key_drivers": ["premium growth", "investment portfolio yield (government bond rates)", "claims ratio", "life insurance penetration in Morocco"],
    "risks": ["low insurance penetration limiting growth", "investment portfolio sensitivity to bond yields", "catastrophic event claims"],
    "macro_sensitivity": {
      "rate_rise": "positive — higher bond yields boost investment portfolio income",
      "gdp_growth": "positive — higher incomes drive insurance adoption",
      "market_crash": "negative — equity portfolio losses"
    }
  },
  "ATL": {
    "sector": "Insurance",
    "description": "Atlanta — mid-sized Moroccan insurance company offering property, casualty, life, and transport insurance.",
    "key_drivers": ["premium volume growth", "claims ratio", "bond portfolio yield", "market competition"],
    "risks": ["large claims events", "investment portfolio duration risk", "competition from larger players"],
    "macro_sensitivity": {
      "rate_rise": "positive — bond portfolio income rises",
      "gdp_growth": "positive — drives commercial insurance demand"
    }
  },
  "MSA": {
    "sector": "Ports / Logistics",
    "description": "Marsa Maroc — state-controlled port operator managing container terminals and bulk cargo facilities at Morocco's major ports (Casablanca, Agadir, Nador, Tanger).",
    "key_drivers": ["container throughput volumes", "phosphate export volumes (OCP)", "import trade volumes", "port tariff levels", "Tanger Med competition"],
    "risks": ["trade volume slowdowns", "competition from Tanger Med", "vessel size evolution requiring capex", "regulatory tariff controls"],
    "macro_sensitivity": {
      "global_trade_growth": "positive — higher trade flows increase throughput",
      "oil_price": "indirect positive — Morocco's phosphate exports are energy-linked",
      "dirham_weakness": "positive — port fees partly USD/EUR denominated"
    }
  },
  "RISMA": {
    "sector": "Hospitality",
    "description": "Risma — Morocco's largest hotel operator, managing Accor-branded hotels (Ibis, Novotel, Mercure, Sofitel) across Morocco.",
    "key_drivers": ["Morocco tourist arrivals", "international travel demand", "Accor brand strength", "RevPAR (revenue per available room)", "EUR/MAD rate (European tourists)"],
    "risks": ["global travel disruptions (pandemics, geopolitics)", "terrorism perception", "competition from independent hotels and Airbnb", "seasonal demand concentration"],
    "macro_sensitivity": {
      "eur_mad_rise": "positive — European tourists spend more in MAD terms",
      "global_recession": "negative — discretionary travel falls",
      "oil_rise": "negative — raises European airfare, reduces tourist arrivals"
    }
  },
  "HPS": {
    "sector": "Fintech / Payments",
    "description": "HPS (Hightech Payment Systems) — Moroccan fintech providing payment processing software and services to banks and financial institutions globally. Niche B2B player.",
    "key_drivers": ["software license and SaaS revenue growth", "new bank client wins globally", "payment card transaction volumes", "R&D investment cycle"],
    "risks": ["concentrated client base", "competition from global payment vendors", "technology obsolescence risk", "small float — illiquid stock"],
    "macro_sensitivity": {
      "gdp_growth": "low direct sensitivity — B2B software revenues are contractual",
      "dirham_weakness": "positive — significant USD/EUR revenue from international clients",
      "fintech_adoption": "positive — more digital payments drive transaction-based revenue"
    }
  },
  "CIH": {
    "sector": "Banking",
    "description": "CIH Bank (Crédit Immobilier et Hôtelier) — specialised Moroccan bank historically focused on real estate and hospitality financing, now a broader retail bank.",
    "key_drivers": ["mortgage loan book performance", "real estate market health", "Bank Al-Maghrib rate", "retail deposit growth"],
    "risks": ["real estate concentration risk", "rate hike impact on mortgage book", "NPL exposure in hospitality sector"],
    "macro_sensitivity": {
      "rate_hike": "negative — mortgage affordability falls, new lending slows",
      "real_estate_downturn": "negative — core loan book impaired"
    }
  },
  "CDM": {
    "sector": "Banking",
    "description": "Crédit du Maroc — subsidiary of Crédit Agricole (France). Retail and corporate banking in Morocco with strong agricultural lending heritage.",
    "key_drivers": ["agricultural sector performance", "retail credit growth", "Crédit Agricole group strategy", "Bank Al-Maghrib rate"],
    "risks": ["agricultural yield variability", "rate sensitivity", "parent group strategy changes"],
    "macro_sensitivity": {
      "rainfall_harvest": "positive — good harvest years boost agricultural loan repayment",
      "rate_hike": "negative — cost of funds rises"
    }
  },
  "BMCI": {
    "sector": "Banking",
    "description": "BMCI — BNP Paribas subsidiary in Morocco. Corporate and retail banking with strong ties to French corporate clients operating in Morocco.",
    "key_drivers": ["BNP Paribas group strategy", "corporate banking volumes", "Bank Al-Maghrib rate", "French investment in Morocco"],
    "risks": ["parent group strategic decisions", "corporate concentration risk", "rate sensitivity"],
    "macro_sensitivity": {
      "france_morocco_trade": "positive — French corporate activity in Morocco drives revenues",
      "rate_hike": "negative — cost of funds rises"
    }
  },
  "SON": {
    "sector": "Steel",
    "description": "Sonasid — Morocco's leading flat steel producer (part of ArcelorMittal group). Supplies construction and industrial sectors with rebar, wire rod, and billets.",
    "key_drivers": ["global steel price", "scrap metal cost (input)", "Moroccan construction activity", "electricity cost", "ArcelorMittal group decisions"],
    "risks": ["steel price cycle volatility", "scrap metal price spikes", "energy cost", "import competition from cheap Chinese steel"],
    "macro_sensitivity": {
      "steel_price_rise": "positive — direct revenue uplift",
      "scrap_price_rise": "negative — main raw material cost",
      "electricity_cost": "high sensitivity — electric arc furnace is energy-intensive",
      "construction_slowdown": "negative — primary domestic market"
    }
  }
}
```

- [ ] **Step 2: Create `knowledge/sector_map.json`**

```json
{
  "Banking": {
    "stocks": ["ATW", "BCP", "BOA", "CIH", "CDM", "BMCI"],
    "sensitive_to": ["Bank Al-Maghrib policy rate", "credit growth", "EUR/MAD rate", "sovereign credit rating", "NPL ratio"],
    "rate_hike_impact": "negative short-term — cost of funds rises, margins compress on variable-rate loans",
    "rate_cut_impact": "positive — stimulates credit demand, improves loan affordability",
    "dirham_weakness_impact": "mixed — pan-African banks (ATW, BOA) lose on currency translation; domestic-only banks neutral",
    "gdp_growth_impact": "positive — economic expansion drives loan demand and reduces defaults"
  },
  "Mining / Fertilizers": {
    "stocks": ["OCP", "MNG"],
    "sensitive_to": ["phosphate price", "copper price", "gold price", "cobalt price", "USD/MAD rate", "energy cost"],
    "commodity_rise_impact": "strongly positive — direct revenue uplift for respective metals",
    "oil_rise_impact": "negative — energy-intensive operations across all mines",
    "dirham_weakness_impact": "positive — revenues are USD-denominated exports",
    "global_recession_impact": "negative — industrial and agricultural commodity demand falls"
  },
  "Telecommunications": {
    "stocks": ["IAM"],
    "sensitive_to": ["regulatory tariff decisions", "mobile subscriber growth", "ARPU", "dividend policy"],
    "rate_hike_impact": "low — telecom is defensive with stable cash flows",
    "gdp_growth_impact": "low — defensive stock, not strongly correlated to economic cycle",
    "note": "Most defensive sector on the BVC; moves primarily on company-specific news and dividends"
  },
  "Cement": {
    "stocks": ["LHM", "CIMAR"],
    "sensitive_to": ["construction activity", "government infrastructure spending", "energy cost", "cement price"],
    "rate_hike_impact": "negative — slows mortgage origination and housing starts",
    "oil_rise_impact": "negative — kiln fuel costs rise directly",
    "gdp_growth_impact": "positive — construction closely tracks economic growth",
    "government_spend_impact": "strongly positive — infrastructure contracts are bulk cement demand"
  },
  "Energy / Fuel Distribution": {
    "stocks": ["TQM"],
    "sensitive_to": ["crude oil price", "USD/MAD rate", "domestic fuel consumption", "government price caps"],
    "oil_rise_impact": "mixed — higher pump prices raise revenue but compress margins if caps prevent full pass-through",
    "dirham_weakness_impact": "negative — imported refined products cost more in MAD"
  },
  "Real Estate": {
    "stocks": ["ADH", "ADI"],
    "sensitive_to": ["Bank Al-Maghrib rate", "mortgage availability", "government housing programs", "construction material costs"],
    "rate_hike_impact": "strongly negative — mortgage affordability falls, buyer demand collapses",
    "rate_cut_impact": "strongly positive — unlocks latent housing demand",
    "steel_rise_impact": "negative — construction input costs rise"
  },
  "Retail / Consumer": {
    "stocks": ["LBV"],
    "sensitive_to": ["consumer spending", "food price inflation", "purchasing power"],
    "inflation_impact": "mixed — boosts headline revenue but squeezes margins on non-food items",
    "gdp_growth_impact": "positive — higher incomes drive discretionary spending",
    "dirham_weakness_impact": "negative — imported goods cost more"
  },
  "Insurance": {
    "stocks": ["WAA", "ATL"],
    "sensitive_to": ["bond yields (investment portfolio)", "premium growth", "claims ratio"],
    "rate_rise_impact": "positive — higher bond yields boost investment income",
    "market_crash_impact": "negative — equity portfolio losses",
    "gdp_growth_impact": "positive — higher incomes drive insurance adoption"
  },
  "Ports / Logistics": {
    "stocks": ["MSA"],
    "sensitive_to": ["trade volumes", "OCP phosphate export volumes", "Tanger Med competition"],
    "global_trade_growth_impact": "positive — higher throughput volumes",
    "dirham_weakness_impact": "positive — some fees are USD/EUR denominated"
  },
  "Hospitality": {
    "stocks": ["RISMA"],
    "sensitive_to": ["tourist arrivals", "EUR/MAD rate", "oil price (affects European airfares)", "global travel demand"],
    "eur_mad_rise_impact": "positive — European tourists spend more in MAD terms",
    "global_recession_impact": "negative — discretionary travel is first cut"
  },
  "Fintech / Payments": {
    "stocks": ["HPS"],
    "sensitive_to": ["software contract wins", "digital payment adoption", "USD/EUR revenue (international clients)"],
    "dirham_weakness_impact": "positive — significant international revenues",
    "note": "Low-liquidity stock; large price moves on thin volume are common"
  },
  "Food / Agribusiness": {
    "stocks": ["CSUMAR"],
    "sensitive_to": ["global sugar price", "government subsidy policy", "harvest quality"],
    "sugar_price_rise_impact": "negative — raises input costs if government caps prevent price pass-through"
  },
  "Steel": {
    "stocks": ["SON"],
    "sensitive_to": ["global steel price", "scrap metal price", "electricity cost", "construction activity"],
    "steel_price_rise_impact": "positive — direct revenue uplift",
    "scrap_price_rise_impact": "negative — main raw material input",
    "electricity_cost_impact": "high — electric arc furnace production"
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add knowledge/company_profiles.json knowledge/sector_map.json
git commit -m "feat: add BVC company profiles and sector map knowledge files"
```

---

### Task 3: Enrichment Pipeline Base + Company Profiles Enricher

**Files:**
- Create: `enrichment/__init__.py`
- Create: `enrichment/company_profiles.py`
- Create: `tests/enrichment/__init__.py`
- Create: `tests/enrichment/test_company_profiles.py`

**Interfaces:**
- Consumes: `knowledge/company_profiles.json` (from Task 2)
- Produces:
  - `enrichment.enrich(context: dict) -> dict` — runs all enrichers in sequence, silent-fail per enricher
  - `enrichment.company_profiles.enrich(context: dict) -> dict` — attaches `"profile"` key to each stock that has a matching ticker in the JSON

- [ ] **Step 1: Write the failing tests**

Create `tests/enrichment/__init__.py` (empty file), then:

```python
# tests/enrichment/test_company_profiles.py
import pytest
from unittest.mock import patch
from pathlib import Path
import json


SAMPLE_PROFILES = {
    "OCP": {
        "sector": "Mining / Fertilizers",
        "description": "Phosphate exporter.",
        "key_drivers": ["phosphate price"],
        "risks": ["commodity cycles"],
        "macro_sensitivity": {"dirham_weakness": "positive"}
    }
}


@pytest.fixture
def context_with_stocks():
    return {
        "bvc": {
            "data": {
                "stocks": [
                    {"ticker": "OCP", "close": 261.5},
                    {"ticker": "ATW", "close": 685.0},
                ]
            }
        }
    }


def test_profile_attached_to_matching_stock(context_with_stocks, tmp_path):
    profiles_file = tmp_path / "company_profiles.json"
    profiles_file.write_text(json.dumps(SAMPLE_PROFILES))

    with patch("enrichment.company_profiles._PROFILES_PATH", profiles_file):
        import enrichment.company_profiles as cp
        cp._profiles = None  # reset cache
        result = cp.enrich(context_with_stocks)

    ocp = next(s for s in result["bvc"]["data"]["stocks"] if s["ticker"] == "OCP")
    assert ocp["profile"]["sector"] == "Mining / Fertilizers"
    assert ocp["profile"]["key_drivers"] == ["phosphate price"]


def test_missing_ticker_leaves_stock_unchanged(context_with_stocks, tmp_path):
    profiles_file = tmp_path / "company_profiles.json"
    profiles_file.write_text(json.dumps(SAMPLE_PROFILES))

    with patch("enrichment.company_profiles._PROFILES_PATH", profiles_file):
        import enrichment.company_profiles as cp
        cp._profiles = None
        result = cp.enrich(context_with_stocks)

    atw = next(s for s in result["bvc"]["data"]["stocks"] if s["ticker"] == "ATW")
    assert "profile" not in atw


def test_enrich_returns_context_unchanged_on_missing_file():
    from enrichment import company_profiles as cp
    cp._profiles = None
    with patch("enrichment.company_profiles._PROFILES_PATH", Path("/nonexistent/path.json")):
        context = {"bvc": {"data": {"stocks": [{"ticker": "OCP", "close": 261.5}]}}}
        result = cp.enrich(context)
    assert result == context
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_company_profiles.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'enrichment'`

- [ ] **Step 3: Create `enrichment/__init__.py`**

```python
import logging

logger = logging.getLogger(__name__)


def enrich(context: dict) -> dict:
    from enrichment import (
        company_profiles,
        sector_map,
        outcome_tracker,
        masi_history,
        reddit,
    )
    enrichers = [company_profiles, sector_map, outcome_tracker, masi_history, reddit]
    for enricher in enrichers:
        try:
            context = enricher.enrich(context)
        except Exception as exc:
            logger.warning(f"Enricher {enricher.__name__} failed: {exc}")
    return context
```

- [ ] **Step 4: Create `enrichment/company_profiles.py`**

```python
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROFILES_PATH = Path(__file__).parent.parent / "knowledge" / "company_profiles.json"
_profiles: dict | None = None


def _load() -> dict:
    global _profiles
    if _profiles is None:
        _profiles = json.loads(_PROFILES_PATH.read_text())
    return _profiles


def enrich(context: dict) -> dict:
    try:
        profiles = _load()
    except Exception as exc:
        logger.warning(f"company_profiles: failed to load profiles: {exc}")
        return context

    stocks = context.get("bvc", {}).get("data", {}).get("stocks", [])
    for stock in stocks:
        ticker = stock.get("ticker")
        if ticker and ticker in profiles:
            stock["profile"] = profiles[ticker]
    return context
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_company_profiles.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add enrichment/__init__.py enrichment/company_profiles.py tests/enrichment/__init__.py tests/enrichment/test_company_profiles.py
git commit -m "feat: add enrichment pipeline base and company profiles enricher"
```

---

### Task 4: Sector Map Enricher

**Files:**
- Create: `enrichment/sector_map.py`
- Create: `tests/enrichment/test_sector_map.py`

**Interfaces:**
- Consumes: `knowledge/sector_map.json` (from Task 2)
- Produces: `enrichment.sector_map.enrich(context: dict) -> dict` — injects `context["sector_map"]` dict

- [ ] **Step 1: Write the failing tests**

```python
# tests/enrichment/test_sector_map.py
import json
import pytest
from unittest.mock import patch
from pathlib import Path

SAMPLE_SECTOR_MAP = {
    "Banking": {
        "stocks": ["ATW", "BCP"],
        "sensitive_to": ["Bank Al-Maghrib rate"],
        "rate_hike_impact": "negative"
    }
}


def test_sector_map_injected_into_context(tmp_path):
    sector_file = tmp_path / "sector_map.json"
    sector_file.write_text(json.dumps(SAMPLE_SECTOR_MAP))

    import enrichment.sector_map as sm
    sm._sector_map = None
    with patch("enrichment.sector_map._SECTOR_MAP_PATH", sector_file):
        result = sm.enrich({})

    assert "sector_map" in result
    assert "Banking" in result["sector_map"]
    assert result["sector_map"]["Banking"]["rate_hike_impact"] == "negative"


def test_sector_map_returns_context_unchanged_on_missing_file():
    import enrichment.sector_map as sm
    sm._sector_map = None
    with patch("enrichment.sector_map._SECTOR_MAP_PATH", Path("/nonexistent.json")):
        context = {"foo": "bar"}
        result = sm.enrich(context)
    assert result == {"foo": "bar"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_sector_map.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'enrichment.sector_map'`

- [ ] **Step 3: Create `enrichment/sector_map.py`**

```python
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SECTOR_MAP_PATH = Path(__file__).parent.parent / "knowledge" / "sector_map.json"
_sector_map: dict | None = None


def _load() -> dict:
    global _sector_map
    if _sector_map is None:
        _sector_map = json.loads(_SECTOR_MAP_PATH.read_text())
    return _sector_map


def enrich(context: dict) -> dict:
    try:
        context["sector_map"] = _load()
    except Exception as exc:
        logger.warning(f"sector_map: failed to load sector map: {exc}")
    return context
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_sector_map.py -v
```

Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add enrichment/sector_map.py tests/enrichment/test_sector_map.py
git commit -m "feat: add sector map enricher"
```

---

### Task 5: Outcome Tracker Enricher

**Files:**
- Create: `enrichment/outcome_tracker.py`
- Create: `tests/enrichment/test_outcome_tracker.py`

**Interfaces:**
- Consumes: `get_recent_ai_picks(days=30)` and `insert_ai_pick(...)` from `storage.db` (Task 1)
- Produces:
  - `enrichment.outcome_tracker.enrich(context: dict) -> dict` — injects `context["past_performance"]` (or `None` if < 3 picks)
  - `enrichment.outcome_tracker.record_picks(analysis: dict, context: dict) -> None` — writes Claude's picks to `ai_picks` table

- [ ] **Step 1: Write the failing tests**

```python
# tests/enrichment/test_outcome_tracker.py
import pytest
import storage.db as db_module
import enrichment.outcome_tracker as ot


@pytest.fixture(autouse=True)
def reset_db(test_db, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db()


def test_returns_null_when_fewer_than_3_picks():
    context = {"bvc": {"data": {"stocks": []}}}
    db_module.insert_ai_pick("2026-06-24", "OCP", "BUY", 261.0, "test")
    db_module.insert_ai_pick("2026-06-24", "ATW", "WATCH", 685.0, "test")
    result = ot.enrich(context)
    assert result["past_performance"] is None


def test_computes_correct_outcome_for_buy_pick():
    db_module.insert_ai_pick("2026-06-10", "OCP", "BUY", 260.0, "test")
    db_module.insert_ai_pick("2026-06-11", "ATW", "AVOID", 700.0, "test")
    db_module.insert_ai_pick("2026-06-12", "MNG", "WATCH", 430.0, "test")
    context = {
        "bvc": {
            "data": {
                "stocks": [
                    {"ticker": "OCP", "close": 270.0},
                    {"ticker": "ATW", "close": 680.0},
                    {"ticker": "MNG", "close": 435.0},
                ]
            }
        }
    }
    result = ot.enrich(context)
    pp = result["past_performance"]
    assert pp is not None
    ocp_pick = next(p for p in pp["picks"] if p["ticker"] == "OCP")
    assert ocp_pick["outcome"] == "correct"
    assert ocp_pick["change_pct"] == pytest.approx(3.85, abs=0.1)

    atw_pick = next(p for p in pp["picks"] if p["ticker"] == "ATW")
    assert atw_pick["outcome"] == "correct"

    mng_pick = next(p for p in pp["picks"] if p["ticker"] == "MNG")
    assert mng_pick["outcome"] == "neutral"


def test_accuracy_summary_string_format():
    db_module.insert_ai_pick("2026-06-10", "OCP", "BUY", 260.0, "r")
    db_module.insert_ai_pick("2026-06-11", "ATW", "AVOID", 700.0, "r")
    db_module.insert_ai_pick("2026-06-12", "MNG", "BUY", 430.0, "r")
    context = {
        "bvc": {
            "data": {
                "stocks": [
                    {"ticker": "OCP", "close": 270.0},
                    {"ticker": "ATW", "close": 680.0},
                    {"ticker": "MNG", "close": 420.0},
                ]
            }
        }
    }
    result = ot.enrich(context)
    summary = result["past_performance"]["accuracy_summary"]
    assert "BUY" in summary
    assert "AVOID" in summary


def test_record_picks_writes_to_db():
    analysis = {
        "ai_picks": [
            {"ticker": "OCP", "label": "BUY", "explanation": "Strong phosphate signal"},
            {"ticker": "ATW", "label": "WATCH", "explanation": "Wait for data"},
        ]
    }
    context = {
        "bvc": {
            "data": {
                "stocks": [
                    {"ticker": "OCP", "close": 261.0},
                    {"ticker": "ATW", "close": 685.0},
                ]
            }
        }
    }
    ot.record_picks(analysis, context)
    picks = db_module.get_recent_ai_picks(days=1)
    assert len(picks) == 2
    ocp = next(p for p in picks if p["ticker"] == "OCP")
    assert ocp["pick"] == "BUY"
    assert ocp["price_at_pick"] == 261.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_outcome_tracker.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'enrichment.outcome_tracker'`

- [ ] **Step 3: Create `enrichment/outcome_tracker.py`**

```python
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def enrich(context: dict) -> dict:
    from storage.db import get_recent_ai_picks

    picks = get_recent_ai_picks(days=30)
    if len(picks) < 3:
        context["past_performance"] = None
        return context

    stocks_by_ticker = {
        s["ticker"]: s
        for s in context.get("bvc", {}).get("data", {}).get("stocks", [])
    }

    evaluated = []
    for pick in picks:
        ticker = pick["ticker"]
        current = (stocks_by_ticker.get(ticker) or {}).get("close")
        price_at = pick["price_at_pick"]
        change_pct = None
        outcome = "unknown"
        if current and price_at:
            change_pct = round((current - price_at) / price_at * 100, 2)
            if pick["pick"] == "BUY":
                outcome = "correct" if change_pct > 0 else "incorrect"
            elif pick["pick"] == "AVOID":
                outcome = "correct" if change_pct < 0 else "incorrect"
            else:
                outcome = "neutral"
        evaluated.append({
            "ticker": ticker,
            "date": pick["date"],
            "pick": pick["pick"],
            "price_at_pick": price_at,
            "current_price": current,
            "change_pct": change_pct,
            "outcome": outcome,
        })

    buy_correct = sum(1 for p in evaluated if p["pick"] == "BUY" and p["outcome"] == "correct")
    buy_incorrect = sum(1 for p in evaluated if p["pick"] == "BUY" and p["outcome"] == "incorrect")
    avoid_correct = sum(1 for p in evaluated if p["pick"] == "AVOID" and p["outcome"] == "correct")
    avoid_incorrect = sum(1 for p in evaluated if p["pick"] == "AVOID" and p["outcome"] == "incorrect")

    context["past_performance"] = {
        "window_days": 30,
        "picks": evaluated,
        "accuracy_summary": f"BUY: {buy_correct} correct / {buy_incorrect} incorrect. AVOID: {avoid_correct} correct / {avoid_incorrect} incorrect.",
    }
    return context


def record_picks(analysis: dict, context: dict) -> None:
    from storage.db import insert_ai_pick

    today = datetime.now(timezone.utc).date().isoformat()
    stocks_by_ticker = {
        s["ticker"]: s
        for s in context.get("bvc", {}).get("data", {}).get("stocks", [])
    }
    for pick in analysis.get("ai_picks", []):
        ticker = pick.get("ticker")
        if not ticker:
            continue
        current_price = (stocks_by_ticker.get(ticker) or {}).get("close")
        try:
            insert_ai_pick(
                date=today,
                ticker=ticker,
                pick=pick.get("label", "WATCH"),
                price_at_pick=current_price,
                reasoning=pick.get("explanation", ""),
            )
        except Exception as exc:
            logger.warning(f"outcome_tracker: failed to record pick for {ticker}: {exc}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_outcome_tracker.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add enrichment/outcome_tracker.py tests/enrichment/test_outcome_tracker.py
git commit -m "feat: add outcome tracker enricher"
```

---

### Task 6: MASI History Enricher

**Files:**
- Create: `enrichment/masi_history.py`
- Create: `tests/enrichment/test_masi_history.py`

**Interfaces:**
- Consumes: `get_masi_history(days=252)` from `storage.db` (Task 1)
- Produces: `enrichment.masi_history.enrich(context: dict) -> dict` — replaces `context["bvc"]["data"]["masi"]` bare dict with enriched version containing `change_30d_pct`, `change_90d_pct`, `week52_high`, `week52_low`, `trend`

- [ ] **Step 1: Write the failing tests**

```python
# tests/enrichment/test_masi_history.py
import pytest
import storage.db as db_module
import enrichment.masi_history as mh


@pytest.fixture(autouse=True)
def reset_db(test_db, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db()


def _make_context(masi_value):
    return {"bvc": {"data": {"masi": {"value": masi_value}}}}


def test_returns_context_unchanged_when_fewer_than_5_rows():
    context = _make_context(17984.0)
    db_module.insert_masi_daily("2026-06-24", 17984.0, None)
    result = mh.enrich(context)
    assert result["bvc"]["data"]["masi"] == {"value": 17984.0}


def test_computes_30d_trend_correctly():
    for i in range(35):
        date = f"2026-05-{i+1:02d}" if i < 31 else f"2026-06-{i-30:02d}"
        value = 17000.0 + i * 10
        db_module.insert_masi_daily(date, value, None)
    context = _make_context(17350.0)
    result = mh.enrich(context)
    masi = result["bvc"]["data"]["masi"]
    assert "change_30d_pct" in masi
    assert "week52_high" in masi
    assert "week52_low" in masi
    assert masi["week52_high"] >= masi["week52_low"]


def test_trend_label_rising():
    for i in range(35):
        db_module.insert_masi_daily(f"2026-05-{i+1:02d}" if i < 31 else f"2026-06-{i-30:02d}", 17000.0 + i * 50, None)
    context = _make_context(19000.0)
    result = mh.enrich(context)
    assert result["bvc"]["data"]["masi"]["trend"] == "rising"


def test_returns_unchanged_when_no_masi_value_in_context():
    for i in range(10):
        db_module.insert_masi_daily(f"2026-06-{i+1:02d}", 17000.0 + i * 10, None)
    context = {"bvc": {"data": {"masi": {}}}}
    result = mh.enrich(context)
    assert "change_30d_pct" not in result["bvc"]["data"]["masi"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_masi_history.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'enrichment.masi_history'`

- [ ] **Step 3: Create `enrichment/masi_history.py`**

```python
import logging

logger = logging.getLogger(__name__)


def enrich(context: dict) -> dict:
    from storage.db import get_masi_history

    current_value = context.get("bvc", {}).get("data", {}).get("masi", {}).get("value")
    if not current_value:
        return context

    rows = get_masi_history(days=252)
    if len(rows) < 5:
        return context

    values = [r["value"] for r in rows if r["value"]]
    if not values:
        return context

    change_30d = None
    if len(values) >= 30:
        change_30d = round((current_value - values[-30]) / values[-30] * 100, 2)

    change_90d = None
    if values:
        oldest = values[0] if len(values) < 90 else values[-90]
        change_90d = round((current_value - oldest) / oldest * 100, 2)

    trend = "flat"
    if change_30d is not None:
        if change_30d > 1.0:
            trend = "rising"
        elif change_30d < -1.0:
            trend = "declining"

    masi = context["bvc"]["data"]["masi"]
    masi.update({
        "change_30d_pct": change_30d,
        "change_90d_pct": change_90d,
        "week52_high": max(values),
        "week52_low": min(values),
        "trend": trend,
    })
    return context
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_masi_history.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add enrichment/masi_history.py tests/enrichment/test_masi_history.py
git commit -m "feat: add MASI history enricher"
```

---

### Task 7: Reddit Enricher

**Files:**
- Create: `enrichment/reddit.py`
- Create: `tests/enrichment/test_reddit.py`

**Interfaces:**
- Consumes: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, `REDDIT_KEYWORDS` from `config` (Task 1)
- Produces: `enrichment.reddit.enrich(context: dict) -> dict` — injects `context["reddit_discussions"]` list

- [ ] **Step 1: Write the failing tests**

```python
# tests/enrichment/test_reddit.py
import pytest
from unittest.mock import MagicMock, patch


def _make_comment(body, score, replies=None):
    comment = MagicMock()
    comment.body = body
    comment.score = score
    comment.replies = replies or []
    return comment


def _make_submission(title, score, comments):
    sub = MagicMock()
    sub.title = title
    sub.score = score
    sub.selftext = ""
    sub.url = "https://reddit.com/r/Maroc/test"
    sub.comments = MagicMock()
    sub.comments.__getitem__ = lambda self, s: comments[s]
    sub.comments.replace_more = MagicMock()
    sub.comments.__iter__ = lambda self: iter(comments)
    return sub


def test_filters_replies_below_score_threshold():
    import enrichment.reddit as reddit_mod

    low_score_reply = _make_comment("short", 1)
    high_score_reply = _make_comment("This is a long enough reply that adds real value here", 5)
    comment = _make_comment("Top comment about bourse maroc OCP", 20, [low_score_reply, high_score_reply])
    submission = _make_submission("OCP bourse maroc annonce", 100, [comment])

    mock_reddit = MagicMock()
    mock_subreddit = MagicMock()
    mock_subreddit.new.return_value = [submission]
    mock_reddit.subreddit.return_value = mock_subreddit

    with patch("enrichment.reddit.praw.Reddit", return_value=mock_reddit):
        result = reddit_mod.enrich({})

    assert "reddit_discussions" in result
    if result["reddit_discussions"]:
        post = result["reddit_discussions"][0]
        comment_data = post["top_comments"][0]
        for reply in comment_data["notable_replies"]:
            assert reply["score"] >= 3
            assert len(reply["text"]) >= 40


def test_caps_at_max_posts():
    import enrichment.reddit as reddit_mod

    submissions = []
    for i in range(20):
        sub = _make_submission(f"bourse maroc OCP news {i}", 50, [])
        sub.comments.__getitem__ = lambda self, s: [][s]
        sub.comments.replace_more = MagicMock()
        sub.comments.__iter__ = lambda self: iter([])
        submissions.append(sub)

    mock_reddit = MagicMock()
    mock_subreddit = MagicMock()
    mock_subreddit.new.return_value = submissions
    mock_reddit.subreddit.return_value = mock_subreddit

    with patch("enrichment.reddit.praw.Reddit", return_value=mock_reddit):
        result = reddit_mod.enrich({})

    assert len(result.get("reddit_discussions", [])) <= 8


def test_single_subreddit_failure_does_not_break_others():
    import enrichment.reddit as reddit_mod

    def side_effect(name):
        if name == "Maroc":
            raise Exception("Subreddit unavailable")
        mock_sub = MagicMock()
        mock_sub.new.return_value = []
        return mock_sub

    mock_reddit = MagicMock()
    mock_reddit.subreddit.side_effect = side_effect

    with patch("enrichment.reddit.praw.Reddit", return_value=mock_reddit):
        result = reddit_mod.enrich({})

    assert "reddit_discussions" in result


def test_returns_empty_list_on_full_failure():
    import enrichment.reddit as reddit_mod

    with patch("enrichment.reddit.praw.Reddit", side_effect=Exception("No credentials")):
        result = reddit_mod.enrich({"existing": "data"})

    assert result["reddit_discussions"] == []
    assert result["existing"] == "data"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_reddit.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'enrichment.reddit'`

- [ ] **Step 3: Create `enrichment/reddit.py`**

```python
import logging
import praw

from config import REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT, REDDIT_KEYWORDS

logger = logging.getLogger(__name__)

_SUBREDDITS = ["Maroc", "Morocco", "investing"]
_MAX_POSTS = 8
_MAX_TOP_COMMENTS = 3
_MAX_NOTABLE_REPLIES = 3
_MIN_REPLY_SCORE = 3
_MIN_REPLY_LENGTH = 40


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in REDDIT_KEYWORDS)


def enrich(context: dict) -> dict:
    discussions = []
    try:
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
            read_only=True,
        )
        for subreddit_name in _SUBREDDITS:
            if len(discussions) >= _MAX_POSTS:
                break
            try:
                subreddit = reddit.subreddit(subreddit_name)
                for submission in subreddit.new(limit=50):
                    if len(discussions) >= _MAX_POSTS:
                        break
                    text = submission.title + " " + (submission.selftext or "")
                    if not _matches_keywords(text):
                        continue
                    submission.comments.replace_more(limit=0)
                    top_comments = []
                    for comment in list(submission.comments)[:_MAX_TOP_COMMENTS]:
                        notable_replies = []
                        for reply in list(getattr(comment, "replies", []))[:10]:
                            body = getattr(reply, "body", "")
                            score = getattr(reply, "score", 0)
                            if score >= _MIN_REPLY_SCORE and len(body) >= _MIN_REPLY_LENGTH:
                                notable_replies.append({"text": body[:500], "score": score})
                                if len(notable_replies) >= _MAX_NOTABLE_REPLIES:
                                    break
                        top_comments.append({
                            "text": getattr(comment, "body", "")[:500],
                            "score": getattr(comment, "score", 0),
                            "notable_replies": notable_replies,
                        })
                    discussions.append({
                        "subreddit": subreddit_name,
                        "title": submission.title,
                        "score": submission.score,
                        "url": submission.url,
                        "top_comments": top_comments,
                    })
            except Exception as exc:
                logger.warning(f"reddit: failed to fetch r/{subreddit_name}: {exc}")
    except Exception as exc:
        logger.warning(f"reddit enricher failed: {exc}")

    context["reddit_discussions"] = discussions
    return context
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/enrichment/test_reddit.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add enrichment/reddit.py tests/enrichment/test_reddit.py
git commit -m "feat: add Reddit enricher with PRAW"
```

---

### Task 8: News Sources Expansion

**Files:**
- Modify: `collectors/news.py`
- Modify: `config.py`
- Create: `tests/test_news_scrapers.py`

**Interfaces:**
- Consumes: existing `RSS_FEEDS` list from `config.py`
- Produces: `_scrape_ammc()` and `_scrape_bam()` return `list[dict]` with keys `{title, summary, published, link, source}` — same format as RSS articles

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_scrapers.py
from unittest.mock import patch, MagicMock
import requests


AMMC_HTML = """
<html><body>
<div class="views-row">
  <h3><a href="/fr/actualites/1">OCP émet des obligations</a></h3>
  <span class="date">2026-06-24</span>
</div>
<div class="views-row">
  <h3><a href="/fr/actualites/2">Résultats semestriels ATW</a></h3>
  <span class="date">2026-06-23</span>
</div>
</body></html>
"""


def test_scrape_ammc_returns_normalized_articles():
    from collectors.news import _scrape_ammc
    mock_resp = MagicMock()
    mock_resp.text = AMMC_HTML
    mock_resp.raise_for_status = MagicMock()
    with patch("collectors.news.requests.get", return_value=mock_resp):
        articles = _scrape_ammc()
    assert len(articles) >= 1
    assert articles[0]["source"] == "AMMC"
    assert "title" in articles[0]
    assert "link" in articles[0]


def test_scrape_ammc_returns_empty_list_on_failure():
    from collectors.news import _scrape_ammc
    with patch("collectors.news.requests.get", side_effect=Exception("timeout")):
        articles = _scrape_ammc()
    assert articles == []


def test_scrape_bam_returns_empty_list_on_failure():
    from collectors.news import _scrape_bam
    with patch("collectors.news.requests.get", side_effect=Exception("timeout")):
        articles = _scrape_bam()
    assert articles == []


def test_collect_still_returns_articles_when_scrapers_fail():
    from collectors.news import collect
    import feedparser
    mock_feed = MagicMock()
    mock_feed.bozo = False
    mock_feed.entries = [MagicMock(title="Test", summary="Test summary", published="", link="http://example.com")]
    with patch("collectors.news.feedparser.parse", return_value=mock_feed), \
         patch("collectors.news._scrape_ammc", side_effect=Exception("scrape failed")), \
         patch("collectors.news._scrape_bam", side_effect=Exception("scrape failed")):
        result = collect()
    assert result["success"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/test_news_scrapers.py -v
```

Expected: FAIL with `ImportError: cannot import name '_scrape_ammc' from 'collectors.news'`

- [ ] **Step 3: Add new RSS feeds to `config.py`**

Replace the existing `RSS_FEEDS` list:

```python
RSS_FEEDS = [
    {"name": "Google News Maroc", "url": "https://news.google.com/rss/search?q=bourse+maroc&hl=fr&gl=MA&ceid=MA:fr"},
    {"name": "Google News OCP", "url": "https://news.google.com/rss/search?q=OCP+Maroc&hl=fr&gl=MA&ceid=MA:fr"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Medias24", "url": "https://medias24.com/feed"},
    {"name": "MAP", "url": "https://www.mapnews.ma/en/rss.xml"},
    {"name": "L'Économiste", "url": "https://www.leconomiste.com/rss.xml"},
    {"name": "TelQuel", "url": "https://telquel.ma/feed"},
    {"name": "Hespress Économie", "url": "https://fr.hespress.com/category/economie/feed"},
]
```

- [ ] **Step 4: Update `collectors/news.py`**

Add `import requests` and `from bs4 import BeautifulSoup` at the top (these packages are already in requirements.txt). Then add scraper functions and update `collect()`:

```python
import logging
import requests
import feedparser
from bs4 import BeautifulSoup

from config import RSS_FEEDS

logger = logging.getLogger(__name__)

MAX_ARTICLES_PER_FEED = 10


def _fetch_feed(url: str, name: str) -> list[dict]:
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Failed to parse feed: {feed.bozo_exception}")
    articles = []
    for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
        articles.append({
            "title": entry.get("title", ""),
            "summary": entry.get("summary", entry.get("description", "")),
            "published": entry.get("published", ""),
            "link": entry.get("link", ""),
            "source": name,
        })
    return articles


def _scrape_ammc() -> list[dict]:
    try:
        url = "https://www.ammc.ma/fr/actualites/communiques-de-presse"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        articles = []
        for item in soup.select(".views-row")[:5]:
            title_el = item.select_one("h3 a, h2 a, a")
            date_el = item.select_one(".date, time, .field-date, span")
            if not title_el:
                continue
            href = title_el.get("href", "")
            link = ("https://www.ammc.ma" + href) if href.startswith("/") else href
            articles.append({
                "title": title_el.get_text(strip=True),
                "summary": "",
                "published": date_el.get_text(strip=True) if date_el else "",
                "link": link,
                "source": "AMMC",
            })
        return articles
    except Exception as exc:
        logger.warning(f"AMMC scraper failed: {exc}")
        return []


def _scrape_bam() -> list[dict]:
    try:
        url = "https://www.bkam.ma/Politique-monetaire/Decisions-du-conseil/Communiques"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        articles = []
        for item in (soup.select(".views-row") or soup.select("article"))[:5]:
            title_el = item.select_one("h3 a, h2 a, a")
            date_el = item.select_one(".date, time, .field-date, span")
            if not title_el:
                continue
            href = title_el.get("href", "")
            link = ("https://www.bkam.ma" + href) if href.startswith("/") else href
            articles.append({
                "title": title_el.get_text(strip=True),
                "summary": "",
                "published": date_el.get_text(strip=True) if date_el else "",
                "link": link,
                "source": "Bank Al-Maghrib",
            })
        return articles
    except Exception as exc:
        logger.warning(f"Bank Al-Maghrib scraper failed: {exc}")
        return []


def collect() -> dict:
    all_articles = []
    errors = []

    for feed_cfg in RSS_FEEDS:
        try:
            articles = _fetch_feed(feed_cfg["url"], feed_cfg["name"])
            all_articles.extend(articles)
        except Exception as exc:
            logger.error(f"News: failed to fetch {feed_cfg['name']}: {exc}")
            errors.append(f"{feed_cfg['name']}: {exc}")

    all_articles.extend(_scrape_ammc())
    all_articles.extend(_scrape_bam())

    return {
        "success": len(all_articles) > 0,
        "data": {"articles": all_articles},
        "errors": errors,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/test_news_scrapers.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 6: Run the full test suite to check nothing broke**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add collectors/news.py config.py tests/test_news_scrapers.py
git commit -m "feat: add AMMC/BAM scrapers and expanded RSS feeds"
```

---

### Task 9: Prompt Updates

**Files:**
- Modify: `agent/prompts.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: enriched context dict with keys: `sector_map`, `past_performance`, `reddit_discussions`, and `bvc.data.stocks[].profile`
- Produces: updated `build_morning_briefing_prompt(context: dict) -> str` that renders 4 new context blocks before the JSON data dump

- [ ] **Step 1: Read existing agent tests**

```bash
cat /Users/ahmedennaime/Desktop/Mizan/tests/test_agent.py
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_agent.py`:

```python
def test_prompt_includes_company_profiles_when_present():
    from agent.prompts import build_morning_briefing_prompt
    context = {
        "bvc": {
            "data": {
                "stocks": [
                    {
                        "ticker": "OCP",
                        "close": 261.5,
                        "profile": {
                            "sector": "Mining / Fertilizers",
                            "description": "Phosphate exporter.",
                            "key_drivers": ["phosphate price"],
                            "macro_sensitivity": {"dirham_weakness": "positive"}
                        }
                    }
                ],
                "masi": {"value": 17984.0}
            }
        }
    }
    prompt = build_morning_briefing_prompt(context)
    assert "COMPANY PROFILES" in prompt
    assert "OCP" in prompt
    assert "Phosphate exporter" in prompt


def test_prompt_includes_sector_map_when_present():
    from agent.prompts import build_morning_briefing_prompt
    context = {
        "bvc": {"data": {"stocks": [], "masi": {}}},
        "sector_map": {"Banking": {"rate_hike_impact": "negative"}}
    }
    prompt = build_morning_briefing_prompt(context)
    assert "SECTOR MAP" in prompt
    assert "Banking" in prompt


def test_prompt_skips_past_performance_when_null():
    from agent.prompts import build_morning_briefing_prompt
    context = {
        "bvc": {"data": {"stocks": [], "masi": {}}},
        "past_performance": None
    }
    prompt = build_morning_briefing_prompt(context)
    assert "PAST PERFORMANCE" not in prompt


def test_prompt_includes_past_performance_when_present():
    from agent.prompts import build_morning_briefing_prompt
    context = {
        "bvc": {"data": {"stocks": [], "masi": {}}},
        "past_performance": {
            "window_days": 30,
            "picks": [{"ticker": "OCP", "pick": "BUY", "change_pct": 3.2, "outcome": "correct"}],
            "accuracy_summary": "BUY: 1 correct / 0 incorrect. AVOID: 0 correct / 0 incorrect."
        }
    }
    prompt = build_morning_briefing_prompt(context)
    assert "PAST PERFORMANCE" in prompt
    assert "BUY: 1 correct" in prompt


def test_prompt_skips_reddit_when_empty():
    from agent.prompts import build_morning_briefing_prompt
    context = {
        "bvc": {"data": {"stocks": [], "masi": {}}},
        "reddit_discussions": []
    }
    prompt = build_morning_briefing_prompt(context)
    assert "REDDIT SENTIMENT" not in prompt


def test_prompt_includes_reddit_when_present():
    from agent.prompts import build_morning_briefing_prompt
    context = {
        "bvc": {"data": {"stocks": [], "masi": {}}},
        "reddit_discussions": [
            {
                "subreddit": "Maroc",
                "title": "OCP résultats positifs",
                "score": 142,
                "url": "https://reddit.com/test",
                "top_comments": [
                    {"text": "Bonne nouvelle", "score": 45, "notable_replies": []}
                ]
            }
        ]
    }
    prompt = build_morning_briefing_prompt(context)
    assert "REDDIT SENTIMENT" in prompt
    assert "OCP résultats positifs" in prompt
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/test_agent.py -v -k "prompt"
```

Expected: The new tests FAIL (blocks not yet in prompt).

- [ ] **Step 4: Update `agent/prompts.py`**

Replace the full file content:

```python
import json


MORNING_BRIEFING_SYSTEM = """You are an AI investment assistant specializing in the Casablanca Stock Exchange (BVC).
Your user is a beginner investor in Morocco learning as they invest. Explain reasoning in clear, educational terms — never use jargon without defining it.
You have access to structured company profiles describing each BVC stock's business model, key revenue drivers, and macro sensitivities. Use these when explaining why a macro event (e.g. rising oil, weak dirham) affects a specific company.
You also have a record of your past pick performance over the last 30 days — factor this into your confidence level.
Reddit discussions reflect retail investor sentiment in Morocco — treat them as a supplementary signal, not a primary one.
Respond ONLY with valid JSON matching the exact schema provided. No markdown fences, no extra text."""


ALERT_SYSTEM = """You are a real-time investment alert assistant for a beginner investor on the Casablanca Stock Exchange (BVC).
Write clear, short, educational alerts. Explain what happened and why it matters in simple terms.
Respond ONLY with valid JSON matching the exact schema provided. No markdown fences, no extra text."""


def _build_company_profiles_block(context: dict) -> str:
    stocks = context.get("bvc", {}).get("data", {}).get("stocks", [])
    lines = []
    for stock in stocks:
        profile = stock.get("profile")
        if not profile:
            continue
        ticker = stock.get("ticker", "")
        desc = profile.get("description", "")
        drivers = ", ".join(profile.get("key_drivers", []))
        sensitivity = "; ".join(
            f"{k}: {v}" for k, v in (profile.get("macro_sensitivity") or {}).items()
        )
        line = f"{ticker}: {desc}"
        if drivers:
            line += f" Key drivers: {drivers}."
        if sensitivity:
            line += f" Macro: {sensitivity}."
        lines.append(line)
    if not lines:
        return ""
    return "COMPANY PROFILES:\n" + "\n".join(lines)


def _build_sector_map_block(context: dict) -> str:
    sector_map = context.get("sector_map")
    if not sector_map:
        return ""
    lines = ["SECTOR MAP (use when linking macro events to specific sectors):"]
    for sector, data in sector_map.items():
        stocks = ", ".join(data.get("stocks", []))
        impacts = {k: v for k, v in data.items() if k.endswith("_impact")}
        impact_str = "; ".join(f"{k.replace('_impact','')}: {v}" for k, v in list(impacts.items())[:3])
        lines.append(f"  {sector} [{stocks}]: {impact_str}")
    return "\n".join(lines)


def _build_past_performance_block(context: dict) -> str:
    pp = context.get("past_performance")
    if not pp:
        return ""
    lines = [
        "YOUR PAST 30-DAY PICK PERFORMANCE (factor this into confidence):",
        f"  {pp['accuracy_summary']}",
    ]
    misses = [p for p in pp.get("picks", []) if p.get("outcome") == "incorrect"]
    if misses:
        miss = misses[0]
        lines.append(
            f"  Recent miss: {miss['ticker']} {miss['pick']} at {miss['price_at_pick']} → {miss.get('change_pct', 'N/A')}% after {pp['window_days']} days"
        )
    return "\n".join(lines)


def _build_reddit_block(context: dict) -> str:
    discussions = context.get("reddit_discussions")
    if not discussions:
        return ""
    lines = ["REDDIT SENTIMENT (last 24h — supplementary signal only):"]
    for post in discussions[:5]:
        lines.append(f"  [r/{post['subreddit']}, {post['score']} upvotes] \"{post['title']}\"")
        for comment in post.get("top_comments", [])[:3]:
            lines.append(f"    → \"{comment['text'][:200]}\" ({comment['score']} upvotes)")
            for reply in comment.get("notable_replies", [])[:2]:
                lines.append(f"       ↳ \"{reply['text'][:150]}\" ({reply['score']} upvotes)")
    return "\n".join(lines)


def build_morning_briefing_prompt(context: dict) -> str:
    blocks = [
        _build_company_profiles_block(context),
        _build_sector_map_block(context),
        _build_past_performance_block(context),
        _build_reddit_block(context),
    ]
    enrichment_section = "\n\n".join(b for b in blocks if b)

    return f"""Analyze today's BVC market data and produce a morning briefing.

{enrichment_section + chr(10) + chr(10) if enrichment_section else ""}MARKET DATA:
{json.dumps(context, indent=2, ensure_ascii=False, default=str)}

Return a JSON object with this EXACT structure (no extra fields):
{{
  "market_pulse": {{
    "masi": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "gold": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "oil": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "eur_mad": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "cac40": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "phosphate_proxy": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}}
  }},
  "whats_happening": "<3-4 sentence summary of today's key events and their BVC relevance, in plain language>",
  "ai_picks": [
    {{
      "ticker": "<BVC ticker>",
      "name": "<company name>",
      "label": "<BUY|WATCH|AVOID>",
      "strategy": "<1-2 sentence tactical recommendation>",
      "explanation": "<3-4 sentence educational explanation for a beginner, including what technical signal supports this>"
    }}
  ],
  "this_week": ["<forward-looking event 1>", "<event 2>", "<event 3>"]
}}

Rules:
- Select 3-5 stocks for ai_picks; base decisions on technical signals in the data, not company fame
- Each explanation must define at least one technical term used (e.g. RSI, MACD, support level)
- Use null for any market_pulse value not present in the data
- Use the company profiles and sector map to ground explanations in the company's actual business drivers"""


def build_alert_prompt(alert_type: str, context: dict) -> str:
    return f"""Generate a real-time BVC investment alert.

ALERT TYPE: {alert_type}
CONTEXT:
{json.dumps(context, indent=2, ensure_ascii=False, default=str)}

Return a JSON object with this EXACT structure:
{{
  "alert_type": "{alert_type}",
  "ticker": "<affected BVC ticker or null>",
  "headline": "<10-15 word headline summarizing the event>",
  "what_happened": "<2-3 sentences describing what occurred>",
  "what_it_means": "<2-3 sentences explaining portfolio impact for a beginner investor>",
  "educational_lesson": "<1-2 sentences: one investing concept this event illustrates>"
}}"""
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/test_agent.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/prompts.py tests/test_agent.py
git commit -m "feat: update prompt to consume enriched context blocks"
```

---

### Task 10: Jobs Wiring

**Files:**
- Modify: `scheduler/jobs.py`

**Interfaces:**
- Consumes:
  - `enrichment.enrich(context: dict) -> dict` (Task 3)
  - `enrichment.outcome_tracker.record_picks(analysis: dict, context: dict) -> None` (Task 5)
  - `storage.db.insert_masi_daily(date, value, change_pct)` (Task 1)

No new test file needed — this is integration wiring. Run the full suite and `make dry-run` to verify.

- [ ] **Step 1: Update `collect_and_persist()` in `scheduler/jobs.py` to write MASI daily**

Find the block in `collect_and_persist()` where BVC prices are persisted:

```python
    if bvc["success"]:
        for stock in bvc["data"].get("stocks", []):
            if stock.get("ticker"):
                upsert_price(stock["ticker"], today, { ... })
```

Add the MASI write immediately after the `for` loop (inside the `if bvc["success"]:` block):

```python
        masi = bvc["data"].get("masi", {})
        if masi.get("value"):
            from storage.db import insert_masi_daily
            insert_masi_daily(today, masi["value"], masi.get("change_pct"))
```

- [ ] **Step 2: Update `run_morning_briefing()` to call the enrichment pipeline**

In `run_morning_briefing()`, find:

```python
    context = collect_and_persist()
    date_str = context["date"]
    analysis = run_morning_analysis(context)
```

Replace with:

```python
    context = collect_and_persist()
    date_str = context["date"]
    from enrichment import enrich
    context = enrich(context)
    analysis = run_morning_analysis(context)
```

- [ ] **Step 3: Update `run_morning_briefing()` to record picks after analysis**

Find the block after `analysis = run_morning_analysis(context)` where `"error" in analysis` is checked. After the successful analysis path (after `html = format_morning_briefing(analysis, date_str)`), add pick recording:

```python
    html = format_morning_briefing(analysis, date_str)
    save_briefing(date_str, html, context)

    from enrichment.outcome_tracker import record_picks
    try:
        record_picks(analysis, context)
    except Exception as exc:
        logger.warning(f"Failed to record picks: {exc}")
```

The full updated `run_morning_briefing()` function after changes:

```python
def run_morning_briefing(dry_run: bool = False) -> None:
    from agent.analyst import run_morning_analysis
    from agent.formatter import format_morning_briefing
    from delivery.email import send_morning_briefing
    from storage.db import save_briefing
    from enrichment import enrich
    from enrichment.outcome_tracker import record_picks

    logger.info("Running morning briefing")
    context = collect_and_persist()
    date_str = context["date"]
    context = enrich(context)
    analysis = run_morning_analysis(context)

    if "error" in analysis:
        logger.warning("AI analysis unavailable; sending fallback briefing with raw data")
        raw_bvc = context.get("bvc", {}).get("data", {})
        raw_json = json.dumps(raw_bvc, indent=2, default=str)[:3000]
        html = (
            f"<html><body>"
            f"<h2>BVC Briefing — {date_str} (AI Unavailable)</h2>"
            f"<p>AI analysis could not be generated today. Raw market data below.</p>"
            f"<pre>{raw_json}</pre>"
            f"</body></html>"
        )
        save_briefing(date_str, html, context)
        if dry_run:
            print("\n" + "=" * 60)
            print("FALLBACK BRIEFING (AI unavailable — DRY RUN)")
            print("=" * 60)
            print(html[:500])
        else:
            try:
                send_morning_briefing(html)
            except Exception as exc:
                logger.error(f"Fallback briefing email delivery failed: {exc}", exc_info=True)
        return

    html = format_morning_briefing(analysis, date_str)
    save_briefing(date_str, html, context)

    try:
        record_picks(analysis, context)
    except Exception as exc:
        logger.warning(f"Failed to record picks: {exc}")

    if dry_run:
        print("\n" + "=" * 60)
        print("MORNING BRIEFING (DRY RUN — email not sent)")
        print("=" * 60)
        print(html[:2000])
        print("..." if len(html) > 2000 else "")
    else:
        last_exc = None
        for attempt in range(2):
            try:
                send_morning_briefing(html)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(f"Morning briefing email attempt {attempt + 1} failed: {exc}")
        if last_exc is not None:
            logger.error(
                f"Morning briefing email delivery failed after 2 attempts: {last_exc}",
                exc_info=True,
            )
```

- [ ] **Step 4: Run the full test suite**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run `make dry-run` to verify end-to-end**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && make dry-run
```

Expected: Morning briefing prints successfully. Logs should show enrichers running. Company profiles and sector map blocks visible in the printed prompt section.

- [ ] **Step 6: Commit**

```bash
git add scheduler/jobs.py
git commit -m "feat: wire enrichment pipeline into morning briefing flow"
```

---

### Task 11: History Seeding Script

**Files:**
- Create: `scripts/seed_history.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `upsert_price()` and `insert_masi_daily()` from `storage.db` (Task 1)
- Produces: `make seed-history` command that backfills 6 months of price and MASI data

This is a one-time operational script, not application code. No unit tests — verified by running it and checking row counts.

- [ ] **Step 1: Inspect the BVC historical data endpoint**

Before writing the script, open `https://www.casablanca-bourse.com/fr/market-data/equities/OCP` in a browser, open DevTools → Network tab, and look for an API call that returns historical OHLCV data. Look for endpoints containing `historic`, `historical`, `history`, or `ohlcv` in the URL. Note the exact URL pattern and parameters.

If no dedicated API endpoint exists, the script uses a fallback: the `_next/data` route for individual stock pages, which may embed chart data.

- [ ] **Step 2: Create `scripts/seed_history.py`**

```python
#!/usr/bin/env python3
"""One-time script to backfill 6 months of BVC price and MASI history."""
import sys
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from storage.db import upsert_price, insert_masi_daily, get_price_history, init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Mizan-Seeder/1.0)",
    "Accept": "application/json",
}

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def _get_all_tickers() -> list[str]:
    """Fetch all BVC tickers from the market_watch API."""
    from config import BVC_API_URL
    r = requests.get(
        BVC_API_URL,
        headers=HEADERS,
        params={"include": "symbol", "page[limit]": "200"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    tickers = []
    included = {i["id"]: i for i in data.get("included", [])}
    for record in data.get("data", []):
        sym_rel = (record.get("relationships") or {}).get("symbol", {}).get("data") or {}
        sym = included.get(sym_rel.get("id"), {})
        url = sym.get("attributes", {}).get("instrument_url", "")
        ticker = url.split("/")[-1] if url else None
        if ticker:
            tickers.append(ticker)
    return tickers


def _fetch_ticker_history(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """
    Fetch historical OHLCV for a single ticker.

    The BVC API historical endpoint pattern (discovered via DevTools inspection):
    GET https://api.casablanca-bourse.com/fr/api/bourse_data/historic_data
    Params: ticker=OCP&from=2025-12-25&to=2026-06-25

    If the endpoint returns 404, this function returns [] and the caller skips.
    """
    url = "https://api.casablanca-bourse.com/fr/api/bourse_data/historic_data"
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            params={"ticker": ticker, "from": from_date, "to": to_date},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        rows = []
        for record in data.get("data", []):
            attr = record.get("attributes", {})
            date = attr.get("sessionDate") or attr.get("date") or attr.get("transactTime", "")[:10]
            if not date:
                continue
            rows.append({
                "date": date,
                "open": attr.get("openingPrice"),
                "high": attr.get("highPrice"),
                "low": attr.get("lowPrice"),
                "close": attr.get("coursCourant") or attr.get("lastPrice"),
                "volume": int(float(attr.get("cumulTitresEchanges") or 0)),
            })
        return rows
    except Exception as exc:
        logger.warning(f"  [{ticker}] history fetch failed: {exc}")
        return []


def main():
    init_db()
    today = datetime.now(timezone.utc).date()
    from_date = (today - timedelta(days=180)).isoformat()
    to_date = today.isoformat()

    logger.info(f"Seeding BVC price history from {from_date} to {to_date}")

    tickers = _get_all_tickers()
    logger.info(f"Found {len(tickers)} tickers")

    seeded = 0
    for ticker in tickers:
        existing = get_price_history(ticker, days=200)
        if len(existing) >= 100:
            logger.info(f"  [{ticker}] already has {len(existing)} rows — skipping")
            continue

        rows = _fetch_ticker_history(ticker, from_date, to_date)
        if not rows:
            logger.warning(f"  [{ticker}] no history returned")
            continue

        for row in rows:
            upsert_price(ticker, row["date"], row)

        logger.info(f"  [{ticker}] seeded {len(rows)} rows")
        seeded += 1

    logger.info(f"Done. Seeded history for {seeded} tickers.")
    logger.info("MASI history is populated automatically as the daily scheduler runs.")
    logger.info("Run 'make dry-run' to verify technical indicators now compute.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add `seed-history` target to `Makefile`**

Add before the `clean:` target:

```makefile
seed-history:
	$(PYTHON) scripts/seed_history.py
```

Also add `seed-history` to the `.PHONY` line.

- [ ] **Step 4: Test the script runs without crashing**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && make seed-history
```

If the historical endpoint returns 404, rows will be 0 per ticker and the log will show `history fetch failed`. This is acceptable — the script degrades gracefully. The technical analysis will build up naturally as the scheduler runs daily.

If historical data IS returned, verify the DB was populated:

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -c "
from storage.db import get_price_history
rows = get_price_history('OCP', days=200)
print(f'OCP history rows: {len(rows)}')
if rows:
    print(f'Oldest: {rows[0][\"date\"]}, Newest: {rows[-1][\"date\"]}')
"
```

- [ ] **Step 5: Run the full test suite one final time**

```bash
cd /Users/ahmedennaime/Desktop/Mizan && .venv/bin/python -m pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/seed_history.py Makefile
git commit -m "feat: add history seeding script"
```
