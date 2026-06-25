import storage.db as db_module


def test_init_creates_all_tables(test_db):
    with db_module.get_connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
    assert tables == {"prices", "briefings", "alerts", "ai_picks", "masi_daily"}


def test_upsert_price_and_retrieve(test_db):
    db_module.upsert_price("OCP", "2026-06-24", {
        "open": 260.0, "high": 265.0, "low": 258.0, "close": 262.0, "volume": 15000
    })
    history = db_module.get_price_history("OCP", days=10)
    assert len(history) == 1
    assert history[0]["close"] == 262.0
    assert history[0]["ticker"] == "OCP"


def test_upsert_price_deduplicates(test_db):
    db_module.upsert_price("OCP", "2026-06-24", {"open": 260.0, "high": 265.0, "low": 258.0, "close": 262.0, "volume": 15000})
    db_module.upsert_price("OCP", "2026-06-24", {"open": 260.0, "high": 267.0, "low": 258.0, "close": 263.0, "volume": 16000})
    history = db_module.get_price_history("OCP", days=10)
    assert len(history) == 1
    assert history[0]["close"] == 263.0


def test_save_and_retrieve_briefing(test_db):
    db_module.save_briefing("2026-06-24", "<p>Analysis</p>", {"key": "value"})
    briefing = db_module.get_last_briefing()
    assert briefing["date"] == "2026-06-24"
    assert briefing["content"] == "<p>Analysis</p>"


def test_log_alert_stores_record(test_db):
    db_module.log_alert("OCP", "price_move_4pct", "OCP moved 4%")
    with db_module.get_connection() as conn:
        row = dict(conn.execute("SELECT * FROM alerts").fetchone())
    assert row["ticker"] == "OCP"
    assert row["trigger_reason"] == "price_move_4pct"


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
