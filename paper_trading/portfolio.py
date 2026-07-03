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
