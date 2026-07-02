# Paper Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add virtual paper-trading — CLI commands to log simulated BVC trades, position tracking with live P&L, a portfolio section in the morning briefing email, and AI prompt enrichment with current holdings.

**Architecture:** New `paper_trading/` package holds portfolio logic and CLI entry points. The existing `storage/db.py` gains a `paper_trades` table and two helper functions. The morning briefing pipeline enriches the AI context with open positions, the Jinja2 template renders a conditional portfolio card, and three Makefile targets expose the CLI.

**Tech Stack:** SQLite (existing), Python 3.13, Jinja2 (existing), pytest, unittest.mock.

## Global Constraints
- No cash limit — positions are tracked with no virtual cash balance.
- Tickers stored and compared uppercased at all times.
- Selling more shares than currently held must print an error and call `sys.exit(1)` without writing to the DB.
- Portfolio email card is omitted entirely when there are no open positions.
- No new pip dependencies.
- Run tests with: `.venv/bin/python -m pytest tests/ -v`
- Commit style: short one-line messages, no body, no Claude/AI mentions.

---

### Task 1: DB schema and storage functions

**Files:**
- Modify: `storage/db.py`
- Create: `tests/paper_trading/__init__.py` (empty)
- Create: `tests/paper_trading/test_store.py`

**Interfaces:**
- Produces:
  - `add_paper_trade(ticker: str, action: str, shares: int, price_mad: float) -> None`
  - `get_paper_trades(ticker: str | None = None) -> list[dict]`
  - Each returned dict has keys: `id`, `ticker`, `action`, `shares`, `price_mad`, `date`, `created_at`

- [ ] **Step 1: Create the empty test package**

```bash
touch tests/paper_trading/__init__.py
```

- [ ] **Step 2: Write failing tests**

Create `tests/paper_trading/test_store.py`:

```python
from unittest.mock import patch


def test_add_and_get_paper_trades(tmp_path):
    db = tmp_path / "test.db"
    with patch("storage.db.DB_PATH", db):
        from storage.db import init_db, add_paper_trade, get_paper_trades
        init_db()
        add_paper_trade("OCP", "buy", 10, 261.0)
        trades = get_paper_trades()
    assert len(trades) == 1
    assert trades[0]["ticker"] == "OCP"
    assert trades[0]["action"] == "buy"
    assert trades[0]["shares"] == 10
    assert trades[0]["price_mad"] == 261.0
    assert trades[0]["date"] is not None


def test_get_paper_trades_filters_by_ticker(tmp_path):
    db = tmp_path / "test.db"
    with patch("storage.db.DB_PATH", db):
        from storage.db import init_db, add_paper_trade, get_paper_trades
        init_db()
        add_paper_trade("OCP", "buy", 10, 261.0)
        add_paper_trade("ATW", "buy", 5, 540.0)
        ocp_trades = get_paper_trades("OCP")
    assert len(ocp_trades) == 1
    assert ocp_trades[0]["ticker"] == "OCP"


def test_ticker_stored_uppercased(tmp_path):
    db = tmp_path / "test.db"
    with patch("storage.db.DB_PATH", db):
        from storage.db import init_db, add_paper_trade, get_paper_trades
        init_db()
        add_paper_trade("ocp", "buy", 10, 261.0)
        trades = get_paper_trades()
    assert trades[0]["ticker"] == "OCP"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/paper_trading/test_store.py -v
```

Expected: FAIL with `ImportError` or `AttributeError` (functions don't exist yet).

- [ ] **Step 4: Add `paper_trades` table to `init_db()` in `storage/db.py`**

`init_db()` currently calls `conn.executescript("""...""")`. Append the new table to the end of that script, before the closing `"""`):

```python
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

- [ ] **Step 5: Add `add_paper_trade` and `get_paper_trades` to `storage/db.py`**

Add these two functions after `get_recent_ai_picks`:

```python
def add_paper_trade(ticker: str, action: str, shares: int, price_mad: float) -> None:
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO paper_trades (ticker, action, shares, price_mad, date, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticker.upper(), action, shares, price_mad,
             now.date().isoformat(), now.isoformat()),
        )


def get_paper_trades(ticker: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if ticker is not None:
            rows = conn.execute(
                "SELECT id, ticker, action, shares, price_mad, date, created_at "
                "FROM paper_trades WHERE ticker = ? ORDER BY created_at ASC",
                (ticker.upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, ticker, action, shares, price_mad, date, created_at "
                "FROM paper_trades ORDER BY created_at ASC"
            ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/paper_trading/test_store.py -v
```

Expected: all 3 PASS.

- [ ] **Step 7: Run the full suite to check for regressions**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all existing tests still PASS.

- [ ] **Step 8: Commit**

```bash
git add storage/db.py tests/paper_trading/__init__.py tests/paper_trading/test_store.py
git commit -m "add paper_trades table and storage functions"
```

---

### Task 2: Portfolio computation

**Files:**
- Create: `paper_trading/__init__.py` (empty)
- Create: `paper_trading/portfolio.py`
- Create: `tests/paper_trading/test_portfolio.py`

**Interfaces:**
- Consumes from Task 1: each trade dict has `ticker: str`, `action: str`, `shares: int`, `price_mad: float`
- Produces:
  - `compute_positions(trades: list[dict], current_prices: dict[str, float]) -> list[dict]`
    - Each returned position dict: `{"ticker": str, "shares": int, "avg_cost_mad": float, "current_price": float | None, "pnl_mad": float | None, "pnl_pct": float | None}`
  - `format_portfolio_text(positions: list[dict]) -> str`

- [ ] **Step 1: Create the package marker**

```bash
touch paper_trading/__init__.py
```

- [ ] **Step 2: Write failing tests**

Create `tests/paper_trading/test_portfolio.py`:

```python
from paper_trading.portfolio import compute_positions, format_portfolio_text


def _t(ticker, action, shares, price_mad):
    return {"ticker": ticker, "action": action, "shares": shares, "price_mad": price_mad}


def test_basic_buy_position():
    positions = compute_positions([_t("OCP", "buy", 10, 261.0)], {"OCP": 275.0})
    assert len(positions) == 1
    assert positions[0]["ticker"] == "OCP"
    assert positions[0]["shares"] == 10
    assert positions[0]["avg_cost_mad"] == 261.0


def test_weighted_avg_cost():
    trades = [_t("OCP", "buy", 10, 260.0), _t("OCP", "buy", 10, 280.0)]
    positions = compute_positions(trades, {"OCP": 275.0})
    assert positions[0]["avg_cost_mad"] == 270.0


def test_partial_sell_reduces_shares():
    trades = [_t("OCP", "buy", 10, 261.0), _t("OCP", "sell", 3, 275.0)]
    positions = compute_positions(trades, {"OCP": 275.0})
    assert positions[0]["shares"] == 7


def test_full_sell_excludes_position():
    trades = [_t("OCP", "buy", 10, 261.0), _t("OCP", "sell", 10, 275.0)]
    assert compute_positions(trades, {"OCP": 275.0}) == []


def test_pnl_calculation():
    positions = compute_positions([_t("OCP", "buy", 10, 261.0)], {"OCP": 275.0})
    assert positions[0]["pnl_mad"] == round((275.0 - 261.0) * 10, 2)
    assert positions[0]["pnl_pct"] == round(((275.0 - 261.0) / 261.0) * 100, 2)


def test_missing_price_gives_none_pnl():
    positions = compute_positions([_t("OCP", "buy", 10, 261.0)], {})
    assert positions[0]["pnl_mad"] is None
    assert positions[0]["pnl_pct"] is None
    assert positions[0]["current_price"] is None


def test_format_portfolio_text_no_positions():
    assert format_portfolio_text([]) == "No open positions."


def test_format_portfolio_text_renders_ticker():
    positions = [
        {"ticker": "OCP", "shares": 10, "avg_cost_mad": 261.0,
         "current_price": 275.0, "pnl_mad": 140.0, "pnl_pct": 5.36}
    ]
    text = format_portfolio_text(positions)
    assert "OCP" in text
    assert "10" in text
    assert "261.00" in text
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/paper_trading/test_portfolio.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `paper_trading/portfolio.py`**

Create `paper_trading/portfolio.py`:

```python
from collections import defaultdict


def compute_positions(trades: list[dict], current_prices: dict[str, float]) -> list[dict]:
    buy_cost: dict[str, float] = defaultdict(float)
    buy_shares: dict[str, int] = defaultdict(int)
    held_shares: dict[str, int] = defaultdict(int)

    for t in trades:
        ticker = t["ticker"]
        if t["action"] == "buy":
            buy_cost[ticker] += t["shares"] * t["price_mad"]
            buy_shares[ticker] += t["shares"]
            held_shares[ticker] += t["shares"]
        elif t["action"] == "sell":
            held_shares[ticker] -= t["shares"]

    positions = []
    for ticker, shares in held_shares.items():
        if shares <= 0:
            continue
        avg_cost = buy_cost[ticker] / buy_shares[ticker]
        current_price = current_prices.get(ticker)
        if current_price is not None:
            pnl_mad = round((current_price - avg_cost) * shares, 2)
            pnl_pct = round(((current_price - avg_cost) / avg_cost) * 100, 2)
        else:
            pnl_mad = None
            pnl_pct = None
        positions.append({
            "ticker": ticker,
            "shares": shares,
            "avg_cost_mad": round(avg_cost, 2),
            "current_price": current_price,
            "pnl_mad": pnl_mad,
            "pnl_pct": pnl_pct,
        })

    positions.sort(
        key=lambda p: abs(p["pnl_mad"]) if p["pnl_mad"] is not None else 0,
        reverse=True,
    )
    return positions


def format_portfolio_text(positions: list[dict]) -> str:
    if not positions:
        return "No open positions."
    header = f"{'TICKER':<8} {'SHARES':>6} {'AVG COST':>10} {'TODAY':>10} {'P&L MAD':>10} {'P&L %':>8}"
    sep = "-" * 58
    lines = [header, sep]
    for p in positions:
        today = f"{p['current_price']:.2f}" if p["current_price"] is not None else "N/A"
        pnl_mad = f"{p['pnl_mad']:+.0f}" if p["pnl_mad"] is not None else "N/A"
        pnl_pct = f"{p['pnl_pct']:+.1f}%" if p["pnl_pct"] is not None else "N/A"
        lines.append(
            f"{p['ticker']:<8} {p['shares']:>6} {p['avg_cost_mad']:>10.2f}"
            f" {today:>10} {pnl_mad:>10} {pnl_pct:>8}"
        )
    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/paper_trading/test_portfolio.py -v
```

Expected: all 8 PASS.

- [ ] **Step 6: Run the full suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add paper_trading/__init__.py paper_trading/portfolio.py tests/paper_trading/test_portfolio.py
git commit -m "add portfolio computation module"
```

---

### Task 3: CLI entry points and Makefile targets

**Files:**
- Create: `paper_trading/cli.py`
- Modify: `Makefile`
- Create: `tests/paper_trading/test_cli.py`

**Interfaces:**
- Consumes from Task 1: `add_paper_trade`, `get_paper_trades`, `get_connection` (all from `storage.db`)
- Consumes from Task 2: `compute_positions`, `format_portfolio_text` (from `paper_trading.portfolio`)
- Produces three functions called by Makefile: `cmd_buy`, `cmd_sell`, `cmd_portfolio`

- [ ] **Step 1: Write failing tests**

Create `tests/paper_trading/test_cli.py`:

```python
import sys
from unittest.mock import patch, MagicMock
import pytest
from paper_trading.cli import cmd_buy, cmd_sell, cmd_portfolio


def _trades(n_shares):
    return [{"ticker": "OCP", "action": "buy", "shares": n_shares, "price_mad": 261.0}]


def test_cmd_buy_records_trade(capsys):
    with patch("paper_trading.cli.init_db"), \
         patch("paper_trading.cli.add_paper_trade") as mock_add:
        cmd_buy("OCP", 10, 261.0)
        mock_add.assert_called_once_with("OCP", "buy", 10, 261.0)
    out = capsys.readouterr().out
    assert "OCP" in out
    assert "261.00" in out


def test_cmd_sell_rejects_oversell(capsys):
    with patch("paper_trading.cli.init_db"), \
         patch("paper_trading.cli.get_paper_trades", return_value=_trades(5)), \
         patch("paper_trading.cli.add_paper_trade") as mock_add:
        with pytest.raises(SystemExit) as exc_info:
            cmd_sell("OCP", 10, 275.0)
        assert exc_info.value.code == 1
        mock_add.assert_not_called()
    assert "5" in capsys.readouterr().out


def test_cmd_sell_records_valid_sell(capsys):
    with patch("paper_trading.cli.init_db"), \
         patch("paper_trading.cli.get_paper_trades", return_value=_trades(10)), \
         patch("paper_trading.cli.add_paper_trade") as mock_add:
        cmd_sell("OCP", 5, 275.0)
        mock_add.assert_called_once_with("OCP", "sell", 5, 275.0)


def test_cmd_portfolio_prints_text(capsys):
    trades = [{"ticker": "OCP", "action": "buy", "shares": 10, "price_mad": 261.0}]
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = [
        {"ticker": "OCP", "close": 275.0}
    ]
    with patch("paper_trading.cli.init_db"), \
         patch("paper_trading.cli.get_paper_trades", return_value=trades), \
         patch("paper_trading.cli.get_connection", return_value=mock_conn):
        cmd_portfolio()
    out = capsys.readouterr().out
    assert "OCP" in out
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/paper_trading/test_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `paper_trading/cli.py`**

Create `paper_trading/cli.py`:

```python
import sys
from storage.db import init_db, add_paper_trade, get_paper_trades, get_connection
from paper_trading.portfolio import compute_positions, format_portfolio_text


def cmd_buy(ticker: str, shares: int, price: float) -> None:
    init_db()
    add_paper_trade(ticker, "buy", int(shares), float(price))
    print(f"Recorded: BUY {shares} x {ticker.upper()} @ {price:.2f} MAD")


def cmd_sell(ticker: str, shares: int, price: float) -> None:
    init_db()
    trades = get_paper_trades(ticker)
    positions = compute_positions(trades, {})
    held = next((p["shares"] for p in positions if p["ticker"] == ticker.upper()), 0)
    if int(shares) > held:
        print(f"Error: you only hold {held} shares of {ticker.upper()}, cannot sell {shares}.")
        sys.exit(1)
    add_paper_trade(ticker, "sell", int(shares), float(price))
    print(f"Recorded: SELL {shares} x {ticker.upper()} @ {price:.2f} MAD")


def cmd_portfolio() -> None:
    init_db()
    trades = get_paper_trades()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT p.ticker, p.close FROM prices p "
            "INNER JOIN (SELECT ticker, MAX(date) AS max_date FROM prices GROUP BY ticker) latest "
            "ON p.ticker = latest.ticker AND p.date = latest.max_date"
        ).fetchall()
    current_prices = {r["ticker"]: r["close"] for r in rows if r["close"] is not None}
    positions = compute_positions(trades, current_prices)
    print(format_portfolio_text(positions))
```

- [ ] **Step 4: Add Makefile targets**

In `Makefile`, add these three targets after the existing `alert-check-dry` target:

```makefile
buy:
	$(PYTHON) -c "from paper_trading.cli import cmd_buy; cmd_buy('$(TICKER)', $(SHARES), $(PRICE))"

sell:
	$(PYTHON) -c "from paper_trading.cli import cmd_sell; cmd_sell('$(TICKER)', $(SHARES), $(PRICE))"

portfolio:
	$(PYTHON) -c "from paper_trading.cli import cmd_portfolio; cmd_portfolio()"
```

Also add `buy sell portfolio` to the `.PHONY` line at the bottom of the Makefile.

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/paper_trading/test_cli.py -v
```

Expected: all 4 PASS.

- [ ] **Step 6: Manual smoke test**

```bash
make buy TICKER=OCP SHARES=10 PRICE=261
make portfolio
```

Expected output of `make buy`: `Recorded: BUY 10 x OCP @ 261.00 MAD`
Expected output of `make portfolio`: table showing OCP position (P&L may show N/A if no price data in local DB yet).

- [ ] **Step 7: Run full suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add paper_trading/cli.py Makefile tests/paper_trading/test_cli.py
git commit -m "add paper trading CLI commands"
```

---

### Task 4: AI prompt enrichment

**Files:**
- Modify: `agent/prompts.py`
- Modify: `scheduler/jobs.py`
- Modify: `tests/test_agent.py` (add 2 tests)

**Interfaces:**
- Consumes from Task 2: `compute_positions` from `paper_trading.portfolio`
- Consumes from Task 1: `get_paper_trades` from `storage.db`
- Context key `"paper_portfolio"` is `list[dict]` of position dicts (same shape as `compute_positions` output)

- [ ] **Step 1: Write failing tests**

Append these two tests to the end of `tests/test_agent.py`:

```python
def test_prompt_includes_portfolio_when_present():
    from agent.prompts import build_morning_briefing_prompt
    context = {
        "bvc": {"data": {"stocks": [], "masi": {}}},
        "paper_portfolio": [
            {
                "ticker": "OCP",
                "shares": 10,
                "avg_cost_mad": 261.0,
                "current_price": 275.0,
                "pnl_mad": 140.0,
                "pnl_pct": 5.36,
            }
        ],
    }
    prompt = build_morning_briefing_prompt(context)
    assert "PAPER PORTFOLIO" in prompt
    assert "OCP" in prompt
    assert "261.00" in prompt


def test_prompt_omits_portfolio_when_empty():
    from agent.prompts import build_morning_briefing_prompt
    context = {
        "bvc": {"data": {"stocks": [], "masi": {}}},
        "paper_portfolio": [],
    }
    prompt = build_morning_briefing_prompt(context)
    assert "PAPER PORTFOLIO" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_agent.py::test_prompt_includes_portfolio_when_present tests/test_agent.py::test_prompt_omits_portfolio_when_empty -v
```

Expected: FAIL — `assert "PAPER PORTFOLIO" in prompt`.

- [ ] **Step 3: Add `_build_portfolio_block` to `agent/prompts.py`**

Add this function after `_build_reddit_block`:

```python
def _build_portfolio_block(context: dict) -> str:
    positions = context.get("paper_portfolio")
    if not positions:
        return ""
    lines = ["PAPER PORTFOLIO (your virtual BVC positions — reference these when making picks):"]
    for p in positions:
        line = f"  {p['ticker']}: {p['shares']} shares @ avg {p['avg_cost_mad']:.2f} MAD"
        if p.get("current_price") is not None:
            sign = "+" if p["pnl_pct"] >= 0 else ""
            line += (
                f" | today {p['current_price']:.2f} MAD"
                f" | {sign}{p['pnl_pct']:.1f}% ({sign}{p['pnl_mad']:.0f} MAD unrealised)"
            )
        else:
            line += " | today N/A"
        lines.append(line)
    return "\n".join(lines)
```

- [ ] **Step 4: Add `"paper_portfolio"` to `_ENRICHMENT_KEYS` and call the new block**

In `agent/prompts.py`, update the set at line 4:

```python
_ENRICHMENT_KEYS = {"sector_map", "past_performance", "reddit_discussions", "paper_portfolio"}
```

In `build_morning_briefing_prompt`, add `_build_portfolio_block(context)` to the `blocks` list:

```python
def build_morning_briefing_prompt(context: dict) -> str:
    blocks = [
        _build_company_profiles_block(context),
        _build_sector_map_block(context),
        _build_past_performance_block(context),
        _build_reddit_block(context),
        _build_portfolio_block(context),
    ]
    enrichment_section = "\n\n".join(b for b in blocks if b)
    ...
```

(The rest of `build_morning_briefing_prompt` is unchanged.)

- [ ] **Step 5: Enrich context with paper portfolio in `scheduler/jobs.py`**

In `run_morning_briefing`, find this section (around line 193–196):

```python
    except Exception as exc:
        logger.warning(f"Enrichment pipeline failed: {exc}")
        health.add_warning(f"enrichment pipeline: {exc}")

    analysis = run_morning_analysis(context)
```

Insert the portfolio enrichment between the except block and the `analysis = ...` line:

```python
    except Exception as exc:
        logger.warning(f"Enrichment pipeline failed: {exc}")
        health.add_warning(f"enrichment pipeline: {exc}")

    try:
        from storage.db import get_paper_trades
        from paper_trading.portfolio import compute_positions
        trades = get_paper_trades()
        if trades:
            stocks = context["bvc"]["data"].get("stocks", [])
            current_prices = {s["ticker"]: s["close"] for s in stocks if s.get("close")}
            context["paper_portfolio"] = compute_positions(trades, current_prices)
    except Exception as exc:
        logger.warning(f"Paper portfolio enrichment failed: {exc}")

    analysis = run_morning_analysis(context)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_agent.py -v
```

Expected: all tests including the two new ones PASS.

- [ ] **Step 7: Run full suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add agent/prompts.py scheduler/jobs.py tests/test_agent.py
git commit -m "enrich morning briefing prompt with paper portfolio"
```

---

### Task 5: Email template and formatter

**Files:**
- Modify: `agent/formatter.py`
- Modify: `delivery/templates/morning_briefing.html`
- Modify: `scheduler/jobs.py`
- Create: `tests/test_formatter.py`

**Interfaces:**
- Consumes from Task 2: position dicts from `compute_positions`
- `format_morning_briefing(analysis: dict, date: str, portfolio: list[dict] | None = None) -> str`

- [ ] **Step 1: Write failing tests**

Create `tests/test_formatter.py`:

```python
from agent.formatter import format_morning_briefing

_ANALYSIS = {
    "market_pulse": {
        "masi": {"value": 13245.5, "change_pct": 0.3, "comment": "Stable."},
    },
    "whats_happening": "Quiet day.",
    "ai_picks": [],
    "this_week": [],
}


def test_portfolio_section_appears_when_positions_given():
    positions = [
        {
            "ticker": "OCP",
            "shares": 10,
            "avg_cost_mad": 261.0,
            "current_price": 275.0,
            "pnl_mad": 140.0,
            "pnl_pct": 5.36,
        }
    ]
    html = format_morning_briefing(_ANALYSIS, "2026-07-03", portfolio=positions)
    assert "Paper Portfolio" in html
    assert "OCP" in html
    assert "261.00" in html


def test_portfolio_section_absent_when_empty():
    html = format_morning_briefing(_ANALYSIS, "2026-07-03", portfolio=[])
    assert "Paper Portfolio" not in html


def test_portfolio_section_absent_when_omitted():
    html = format_morning_briefing(_ANALYSIS, "2026-07-03")
    assert "Paper Portfolio" not in html


def test_pnl_na_when_no_current_price():
    positions = [
        {
            "ticker": "ATW",
            "shares": 5,
            "avg_cost_mad": 540.0,
            "current_price": None,
            "pnl_mad": None,
            "pnl_pct": None,
        }
    ]
    html = format_morning_briefing(_ANALYSIS, "2026-07-03", portfolio=positions)
    assert "ATW" in html
    assert "N/A" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_formatter.py -v
```

Expected: FAIL — `assert "Paper Portfolio" in html`.

- [ ] **Step 3: Update `agent/formatter.py`**

Replace the current `format_morning_briefing` function (lines 11–13) with:

```python
def format_morning_briefing(analysis: dict, date: str, portfolio: list[dict] | None = None) -> str:
    template = _env.get_template("morning_briefing.html")
    return template.render(date=date, portfolio=portfolio or [], **analysis)
```

- [ ] **Step 4: Add CSS for the portfolio table to `morning_briefing.html`**

Inside the `<style>` block (before the closing `</style>` tag at line 33), add:

```css
    .portfolio-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    .portfolio-table th { color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; padding: 4px 0; text-align: right; }
    .portfolio-table th:first-child { text-align: left; }
    .portfolio-table td { padding: 6px 0; border-top: 1px solid #eee; text-align: right; }
    .portfolio-table td:first-child { text-align: left; font-weight: bold; }
```

- [ ] **Step 5: Add the portfolio card to `morning_briefing.html`**

Insert the following block between the closing `</div>` of the "What's Happening" card (line 62) and the opening `<div class="card">` of the "AI Picks" card (line 64):

```html
  {% if portfolio %}
  <div class="card">
    <div class="section-title">Paper Portfolio</div>
    <table class="portfolio-table">
      <tr>
        <th>Ticker</th>
        <th>Shares</th>
        <th>Avg Cost</th>
        <th>Today</th>
        <th>P&amp;L</th>
      </tr>
      {% for p in portfolio %}
      <tr>
        <td>{{ p.ticker }}</td>
        <td>{{ p.shares }}</td>
        <td>{{ "%.2f"|format(p.avg_cost_mad) }} MAD</td>
        <td>{{ "%.2f"|format(p.current_price) ~ " MAD" if p.current_price is not none else "N/A" }}</td>
        <td class="{{ 'up' if p.pnl_mad is not none and p.pnl_mad >= 0 else 'down' if p.pnl_mad is not none else '' }}">
          {% if p.pnl_mad is not none %}
            {{ "%+.0f"|format(p.pnl_mad) }} MAD ({{ "%+.1f"|format(p.pnl_pct) }}%)
          {% else %}
            N/A
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}
```

- [ ] **Step 6: Update `format_morning_briefing` call in `scheduler/jobs.py`**

Find this line in `run_morning_briefing` (around line 229):

```python
    html = format_morning_briefing(analysis, date_str)
```

Replace with:

```python
    html = format_morning_briefing(analysis, date_str, portfolio=context.get("paper_portfolio", []))
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_formatter.py -v
```

Expected: all 4 PASS.

- [ ] **Step 8: Run full suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 9: Manual end-to-end smoke test**

Add a trade and run a dry-run to confirm the portfolio section appears:

```bash
make buy TICKER=OCP SHARES=10 PRICE=261
make dry-run
```

In the dry-run HTML output (printed to stdout), confirm a "Paper Portfolio" section is present with OCP.

- [ ] **Step 10: Commit**

```bash
git add agent/formatter.py delivery/templates/morning_briefing.html scheduler/jobs.py tests/test_formatter.py
git commit -m "add portfolio card to morning briefing email"
```
