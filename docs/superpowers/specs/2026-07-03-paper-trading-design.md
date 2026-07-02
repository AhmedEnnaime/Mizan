# Paper Trading — Design Spec

## Goal

Add a virtual paper-trading layer to Mizan so the user can log simulated BVC trades, track open positions with live P&L, see their portfolio in the morning briefing email, and give the AI context about what they "hold" when making picks.

---

## Context

- **User level:** Beginner investor; in observation/learning mode, no real positions yet.
- **Scope:** Virtual positions only — no real brokerage integration, no cash limit.
- **Interface:** Three Makefile targets (`make buy`, `make sell`, `make portfolio`).
- **Storage:** New table in the existing SQLite DB (same `DB_PATH`, same `init_db` pattern).
- **Morning email:** A new portfolio section, rendered only when at least one position exists.
- **AI enrichment:** Current positions are injected into the morning briefing prompt so Claude can reference what the user holds when making picks.

---

## Data Model

### `paper_trades` table (added to existing SQLite DB)

```sql
CREATE TABLE IF NOT EXISTS paper_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL,
    action      TEXT    NOT NULL CHECK(action IN ('buy', 'sell')),
    shares      INTEGER NOT NULL CHECK(shares > 0),
    price_mad   REAL    NOT NULL CHECK(price_mad > 0),
    date        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
```

Positions are **derived at runtime** from this raw trade log — no separate positions table. This avoids sync bugs and keeps the data model append-only.

### Derived position (Python dict)

```python
{
    "ticker":        "OCP",
    "shares":        10,
    "avg_cost_mad":  261.0,
    "current_price": 275.0,   # None if ticker not in today's BVC data
    "pnl_mad":       140.0,   # None if current_price is None
    "pnl_pct":       5.36,    # None if current_price is None
}
```

Avg cost = weighted average of all buy prices (total buy cost / total buy shares, ignoring sells for simplicity). Sells reduce `shares` held. When `shares` reaches 0 the position is excluded from output.

---

## Files

### New files

| File | Purpose |
|------|---------|
| `paper_trading/__init__.py` | Empty package marker |
| `paper_trading/portfolio.py` | `compute_positions()` and `format_portfolio_text()` |
| `paper_trading/cli.py` | `cmd_buy()`, `cmd_sell()`, `cmd_portfolio()` — entry points for Makefile |
| `tests/paper_trading/__init__.py` | Empty |
| `tests/paper_trading/test_portfolio.py` | Unit tests for position computation |

### Modified files

| File | What changes |
|------|-------------|
| `storage/db.py` | Add `paper_trades` table to `init_db()`; add `add_paper_trade()`, `get_paper_trades()` |
| `Makefile` | Add `buy`, `sell`, `portfolio` targets |
| `agent/prompts.py` | Add `_build_portfolio_block()`, call it in `build_morning_briefing_prompt()` |
| `scheduler/jobs.py` | Load paper positions into context before AI analysis |
| `delivery/templates/morning_briefing.html` | Add conditional portfolio section |
| `agent/formatter.py` | Add `portfolio` param to `format_morning_briefing()` |

---

## Module: `paper_trading/portfolio.py`

```python
def compute_positions(trades: list[dict], current_prices: dict[str, float]) -> list[dict]:
    ...

def format_portfolio_text(positions: list[dict]) -> str:
    ...
```

**`compute_positions` logic:**
1. Group trades by ticker.
2. Per ticker: accumulate `total_buy_cost` and `total_buy_shares` across all `buy` trades; subtract shares for each `sell` trade to get `shares_held`.
3. If `shares_held <= 0`, skip (position closed).
4. `avg_cost_mad = total_buy_cost / total_buy_shares`.
5. Look up `current_price` from the `current_prices` dict; compute `pnl_mad` and `pnl_pct` if available.
6. Return list sorted by `abs(pnl_mad)` descending (biggest mover first in email).

**`format_portfolio_text` logic:**
Renders a terminal-friendly table, used by `make portfolio`. Returns multi-line string.

---

## Module: `paper_trading/cli.py`

```python
def cmd_buy(ticker: str, shares: int, price: float) -> None:
    ...

def cmd_sell(ticker: str, shares: int, price: float) -> None:
    ...

def cmd_portfolio() -> None:
    ...
```

**`cmd_buy`:** Calls `init_db()`, then `add_paper_trade(ticker, "buy", shares, price)`. Prints confirmation.

**`cmd_sell`:**
1. Calls `init_db()`, then `get_paper_trades(ticker)` to compute current shares held.
2. If `shares_to_sell > shares_held`: prints an error message and calls `sys.exit(1)`.
3. Otherwise calls `add_paper_trade(ticker, "sell", shares, price)`. Prints confirmation.

**`cmd_portfolio`:**
1. Calls `init_db()`, then `get_paper_trades()` (all tickers).
2. Builds `current_prices: dict[str, float]` by querying the `prices` table for the most recent `close` per ticker: `SELECT ticker, close FROM prices WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM prices GROUP BY ticker)`.
3. Calls `compute_positions(trades, current_prices)`, then `format_portfolio_text(positions)`.
4. Prints to stdout.

---

## Storage changes (`storage/db.py`)

```python
def add_paper_trade(ticker: str, action: str, shares: int, price_mad: float) -> None:
    ...

def get_paper_trades(ticker: str | None = None) -> list[dict]:
    # If ticker is None, returns all trades. If ticker given, returns only that ticker's trades.
    ...
```

`init_db()` gets the `paper_trades` table added to its `executescript` block.

---

## Makefile targets

```makefile
buy:
	$(PYTHON) -c "from paper_trading.cli import cmd_buy; cmd_buy('$(TICKER)', $(SHARES), $(PRICE))"

sell:
	$(PYTHON) -c "from paper_trading.cli import cmd_sell; cmd_sell('$(TICKER)', $(SHARES), $(PRICE))"

portfolio:
	$(PYTHON) -c "from paper_trading.cli import cmd_portfolio; cmd_portfolio()"
```

Usage examples:
```bash
make buy TICKER=OCP SHARES=10 PRICE=261
make sell TICKER=OCP SHARES=5 PRICE=275
make portfolio
```

---

## AI prompt enrichment

`_build_portfolio_block(context: dict) -> str` in `agent/prompts.py`:

```
PAPER PORTFOLIO (virtual positions — reference these when making picks):
  OCP: 10 shares @ avg 261.00 MAD | today 275.00 MAD | +5.4% (+140 MAD)
  ATW: 5 shares @ avg 540.00 MAD | today N/A
```

Returned empty string when no positions exist (block is silently omitted from prompt).

`scheduler/jobs.py`: In `run_morning_briefing`, after `collect_and_persist()` returns, build `current_prices` from `context["bvc"]["data"]["stocks"]` as `{s["ticker"]: s["close"] for s in stocks if s.get("close")}`. Call `get_paper_trades()` and `compute_positions(trades, current_prices)`. Set `context["paper_portfolio"] = positions` before calling `run_morning_analysis`.

`agent/prompts.py`: `build_morning_briefing_prompt()` calls `_build_portfolio_block()` and appends the block before the JSON schema instructions if non-empty.

---

## Morning email section

`agent/formatter.py` — `format_morning_briefing()` gains an optional `portfolio: list[dict] | None = None` parameter, passed through to the Jinja2 template.

`morning_briefing.html` — a new card section, rendered only when `portfolio` is non-empty:

```html
{% if portfolio %}
<div class="card">
  <div class="section-title">Paper Portfolio</div>
  <table style="width:100%; border-collapse:collapse; font-size:14px;">
    <tr style="color:#888; font-size:11px; text-transform:uppercase;">
      <th align="left">Ticker</th>
      <th align="right">Shares</th>
      <th align="right">Avg Cost</th>
      <th align="right">Today</th>
      <th align="right">P&amp;L</th>
    </tr>
    {% for p in portfolio %}
    <tr style="border-top:1px solid #eee; padding:6px 0;">
      <td style="padding:6px 0; font-weight:bold;">{{ p.ticker }}</td>
      <td align="right">{{ p.shares }}</td>
      <td align="right">{{ "%.2f"|format(p.avg_cost_mad) }} MAD</td>
      <td align="right">{{ "%.2f"|format(p.current_price) ~ " MAD" if p.current_price else "N/A" }}</td>
      <td align="right" class="{{ 'up' if p.pnl_mad and p.pnl_mad >= 0 else 'down' if p.pnl_mad else '' }}">
        {{ ("+%.0f"|format(p.pnl_mad) if p.pnl_mad >= 0 else "%.0f"|format(p.pnl_mad)) ~ " MAD (" ~ ("+%.1f"|format(p.pnl_pct) if p.pnl_pct >= 0 else "%.1f"|format(p.pnl_pct)) ~ "%)" if p.pnl_mad is not none else "N/A" }}
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
{% endif %}
```

---

## Error handling

| Scenario | Behavior |
|---------|---------|
| Sell more shares than held | Print clear error, `sys.exit(1)`, no DB write |
| Ticker not in today's BVC data | Record trade normally; `current_price`, `pnl_mad`, `pnl_pct` are `None` in position output |
| `make buy` called without TICKER/SHARES/PRICE | Python raises `ValueError`/`TypeError`; user sees traceback — acceptable for CLI |
| DB not initialised yet | `init_db()` is always called first in every CLI entry point |

---

## Tests

### `tests/paper_trading/test_portfolio.py`

6 unit tests, no DB required (pass trades list directly):

1. **`test_basic_buy_position`** — one buy → correct shares, avg cost
2. **`test_weighted_avg_cost`** — two buys at different prices → correct weighted average
3. **`test_partial_sell_reduces_shares`** — buy 10, sell 3 → 7 shares remain
4. **`test_full_sell_excludes_position`** — buy 10, sell 10 → position list is empty
5. **`test_pnl_calculation`** — verify MAD and percentage P&L formula
6. **`test_missing_price_gives_none_pnl`** — ticker absent from `current_prices` → `pnl_mad` and `pnl_pct` are `None`

### `tests/paper_trading/test_store.py`

2 integration tests using a temp SQLite file:

1. **`test_add_and_get_trades`** — add buy, verify retrieved row matches
2. **`test_get_trades_filters_by_ticker`** — add two tickers, verify filter works

---

## What this does NOT do (YAGNI)

- No realised P&L tracking for closed positions (sells just reduce shares)
- No cash account or cash limit
- No trade history CLI command (DB is inspectable directly with SQLite)
- No notification when a paper position hits a target price (that's the watchlist feature already built)
- No Docker-specific changes (DB volume already persists)
