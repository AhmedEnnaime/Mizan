# Mizan — BVC AI Investment Assistant — Design Spec
**Date:** 2026-06-24
**Status:** Approved

---

## Overview

A Python-based AI agent that monitors the Casablanca Stock Exchange (BVC) daily and helps a beginner investor make informed decisions. The system delivers a morning briefing email at 8:00 AM with market analysis, educational stock recommendations, and real-time alert emails throughout the trading day when something urgent happens.

The tool operates in two modes simultaneously:
- **Discovery mode** — scans all ~76 BVC-listed stocks every morning and surfaces the most interesting opportunities regardless of company size or fame, purely based on opportunity signals
- **Watchlist mode** — monitors stocks the user has added and alerts on price targets and news events specific to those companies

---

## Goals

- Help a beginner investor understand and participate in the Casablanca stock market
- Provide daily AI-powered analysis that teaches as it recommends (educational explanations with every call)
- Surface genuine opportunities across the full BVC universe — not just well-known large caps
- Stay up to date with everything that affects BVC stocks: Morocco-specific news, global markets, commodities, macro indicators, geopolitics, climate
- Run reliably 24/7 with minimal maintenance, containerized via Docker

---

## Phase 1 Scope

Phase 1 delivers: AI agent + email delivery (morning briefing + real-time alerts).
Phase 2 (out of scope here): web dashboard, Telegram notifications, portfolio tracker.

---

## Data Sources

The AI agent consumes data from 9 categories every morning and every 30 minutes during market hours:

### 1. BVC Market Data
- Stock prices (open, high, low, close, volume) for all ~76 listed companies
- MASI and MADEX index levels
- Company earnings, dividend announcements, and AMMC regulatory filings
- Profit warnings and share buyback announcements
- **Source:** bvc.ma scraper (BeautifulSoup)

### 2. Morocco Macroeconomic Data
- Bank Al-Maghrib interest rate decisions
- Morocco CPI (inflation), GDP growth forecasts
- Unemployment rate, trade balance, FDI flows
- Money supply (M2/M3), industrial production index
- Morocco sovereign credit ratings (Fitch, Moody's, S&P)
- **Source:** HCP (Haut Commissariat au Plan) website + Bank Al-Maghrib RSS

### 3. Commodities
- **Phosphate prices** — most Morocco-specific signal; OCP Group is the world's largest exporter
- **Brent crude oil** — Morocco imports nearly all its energy; oil prices affect inflation and transport stocks
- **Natural gas** — industrial energy costs
- **Gold** — global safe-haven signal; rising gold often signals market stress
- **Silver, copper** — secondary indicators
- **Wheat and corn** — Morocco imports food; agricultural commodity prices affect inflation and agri stocks
- **Fertilizer prices** — linked to OCP revenue
- **Source:** yfinance Python library (free)

### 4. Currencies / Forex
- USD/MAD and EUR/MAD exchange rates (EU is Morocco's #1 trade partner)
- DXY — US Dollar Index
- EUR/USD (feeds into MAD basket)
- Moroccan diaspora (MRE) remittance flow data (monthly)
- **Source:** yfinance + ExchangeRate-API (free tier)

### 5. Global Markets
- S&P 500 (US market sentiment)
- CAC 40 (France — key Morocco trade and investment partner)
- MSCI Emerging Markets and MSCI Frontier Markets indices
- VIX — global fear/volatility index
- US 10-year Treasury yield (capital flow indicator)
- US Fed and ECB interest rate decisions
- **Source:** yfinance (free)

### 6. Geopolitical & Regional News
- MENA region stability events
- Algeria–Morocco relations (border, gas pipeline context)
- Morocco's Sub-Saharan Africa banking expansion news
- EU–Morocco trade agreement updates
- Middle East conflicts (affect oil and gold)
- Russia–Ukraine war updates (affect wheat and gas)
- US tariff and trade policy
- Morocco World Cup 2030 infrastructure news
- **Source:** RSS feeds (Reuters, Al Jazeera English, MAP — Maghreb Arab Press)

### 7. Morocco Sector News
- Banking sector: NPL ratios, credit growth, Bank Al-Maghrib decisions
- Real estate: construction permits, mortgage rate trends, tourism data
- Telecoms: subscriber growth, ARPU, regulatory changes
- OCP / Phosphates: fertilizer demand, export volumes, contract prices
- Insurance: claims ratios and investment return disclosures
- Government infrastructure and public spending announcements
- **Source:** RSS feeds from Médias24, L'Économiste, TelQuel, Le Matin

### 8. Climate & Agriculture
- Rainfall levels and drought alerts (Morocco's agriculture is rain-fed)
- Cereal harvest forecasts (HCP seasonal reports)
- Heatwave impact on construction and tourism sectors
- Water reservoir levels (affects hydroelectric power and agriculture)
- **Source:** Météo Maroc RSS + HCP seasonal reports

### 9. Technical Analysis
Computed locally from stored price history using `pandas-ta`:
- Moving averages: 20-day, 50-day, 200-day
- RSI (Relative Strength Index) — overbought/oversold signal
- MACD and MACD signal line — momentum direction
- Bollinger Bands — volatility envelope
- Support and resistance levels
- Volume trend analysis
- Fibonacci retracement levels

---

## Architecture

### Layer 1 — Data Collection
Five Python collector modules, each responsible for one data category:

| Module | Responsibility | Source |
|---|---|---|
| `collectors/bvc.py` | BVC prices, index, filings | bvc.ma scraper |
| `collectors/news.py` | Moroccan + global news | RSS feeds |
| `collectors/commodities.py` | Gold, oil, gas, phosphate, wheat | yfinance |
| `collectors/macro.py` | Forex, global indices, VIX | yfinance + ExchangeRate-API |
| `collectors/technical.py` | RSI, MACD, MAs from price history | pandas-ta + local DB |

All collectors return a standardized Python dict. Failures are caught per-collector — if one fails, the rest continue and the gap is noted in the output.

### Layer 2 — AI Agent (Claude API)
`agent/analyst.py` receives a bundled context package from all collectors and runs two tasks:

1. **Morning analysis** — full market analysis, discovery picks, educational explanations, strategy recommendations per stock
2. **Alert analysis** — triggered mid-day when a threshold is crossed; produces a short focused alert with context and explanation

Prompts are centralized in `agent/prompts.py` for easy iteration without touching logic code.

`agent/formatter.py` converts the AI's structured output into HTML email content.

### Layer 3 — Delivery
`delivery/email.py` handles two email types:

**Morning Briefing (8:00 AM daily):**
- Market Pulse — 6-number snapshot (MASI, gold, oil, EUR/MAD, CAC 40, phosphate)
- What's Happening — plain-language summary of today's key events and their BVC relevance
- AI Picks — discovery stocks with BUY/WATCH/AVOID label, strategy recommendation, full educational explanation per pick
- This Week — 3–5 forward-looking events to monitor

**Real-Time Alerts (during market hours 10:00–15:30 MET):**
- Price move alert — stock moves >3% in either direction within a single session (configurable in `config.py`)
- Breaking news alert — central bank decision, earnings release, major announcement
- Commodity shock alert — oil/gold/phosphate spike with which BVC stocks are affected
- Watchlist trigger alert — a followed stock hits a noted price level

Every alert includes: what happened → what it means for the user's stocks → one educational lesson.

### Layer 4 — Scheduler
`scheduler/jobs.py` uses APScheduler to run:
- 07:30 AM — collect all data
- 08:00 AM — run AI analysis → send morning briefing
- Every 30 minutes (10:00–15:30 MET) — run alert monitor
- Daily — persist price data to SQLite

---

## Watchlist Management

The user manages their watchlist via a plain `watchlist.json` file at the project root. Format:

```json
[
  { "ticker": "OCP", "name": "OCP Group", "note_price": 261.0 },
  { "ticker": "ATW", "name": "Attijariwafa Bank", "note_price": null }
]
```

- `ticker` — BVC stock code
- `note_price` — optional price level to trigger a watchlist alert (null = monitor news only)

The file is the single source of truth. The user edits it directly. No UI or CLI needed in Phase 1.

---

## Data Storage

Local SQLite database (`storage/stocks.db`) with three tables:

- **prices** — daily OHLCV for all BVC stocks (enables historical technical analysis)
- **briefings** — each morning's full AI analysis stored for reference and continuity
- **alerts** — log of every alert sent, timestamp, trigger reason, and stock ticker

No cloud database required in Phase 1. Historical price data enables the technical analysis layer and gives the AI agent longitudinal context ("this stock has been declining for 3 weeks").

---

## Containerization

The system runs in a single Docker container:

- **`Dockerfile`** — Python 3.12 base image, installs all dependencies, copies source
- **`docker-compose.yml`** — one service (`bvc-agent`), restart policy `always`, mounts a local volume for the SQLite database and logs

Single command to run: `docker compose up -d`

The same setup works locally and on a cheap VPS (~$5/month on DigitalOcean or Hetzner).

`.env` file holds secrets (Claude API key, Gmail credentials) and is never committed to git.

---

## Error Handling

| Failure | Behavior |
|---|---|
| BVC scraper down | Use previous day's cached prices, note gap in email |
| News feed unavailable | Skip that source, continue with others |
| Claude API call fails | Retry once; on second failure, send simplified briefing with raw data only |
| Email delivery fails | Log locally, retry at next scheduled cycle |
| yfinance timeout | Retry with exponential backoff (3 attempts) |

All errors logged to `logs/errors.log` with timestamps and stack traces. The system never fails silently.

---

## Testing

- **Unit tests** — each collector tested independently with mock/fixture data
- **Dry-run mode** — full pipeline runs without sending emails; output printed to terminal instead
- **Fixture data** — saved snapshots of real BVC data for offline development and testing
- **AI calls mocked in tests** — Claude responses stubbed to avoid API cost during development

---

## Project Structure

```
stocks/
├── Dockerfile
├── docker-compose.yml
├── .env                    # Secrets — never committed
├── config.py               # Non-secret configuration
├── main.py                 # Entry point
├── collectors/
│   ├── bvc.py
│   ├── news.py
│   ├── commodities.py
│   ├── macro.py
│   └── technical.py
├── agent/
│   ├── analyst.py
│   ├── prompts.py
│   └── formatter.py
├── delivery/
│   ├── email.py
│   └── templates/
├── scheduler/
│   └── jobs.py
├── storage/
│   └── db.py
├── tests/
│   ├── fixtures/
│   └── test_collectors.py
└── logs/
    └── errors.log
```

---

## External Dependencies & Cost

| Dependency | Purpose | Cost |
|---|---|---|
| Claude API (Anthropic) | AI analysis engine | ~$5–10/month |
| yfinance | Commodities, forex, global indices | Free |
| Gmail SMTP | Email delivery | Free |
| bvc.ma scraper | BVC stock prices | Free |
| pandas-ta | Technical indicator computation | Free |
| APScheduler | Job scheduling | Free |
| SQLite | Local data storage | Free |

Total estimated monthly cost: **$5–10** (Claude API only).

---

## Out of Scope (Phase 2)

- Web dashboard with charts and interactive portfolio tracker
- Telegram bot notifications
- Backtesting engine (Rust candidate for this)
- Mobile app
- Multi-user support
