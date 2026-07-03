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
