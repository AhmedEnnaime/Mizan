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
