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
