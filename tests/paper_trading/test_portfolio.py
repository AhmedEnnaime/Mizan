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
