import storage.db as db_module


def test_init_creates_all_tables(test_db):
    with db_module.get_connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
    assert tables == {"prices", "briefings", "alerts"}


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
