import pytest
import storage.db as db_module
import enrichment.masi_history as mh


@pytest.fixture(autouse=True)
def reset_db(test_db, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db()


def _make_context(masi_value):
    return {"bvc": {"data": {"masi": {"value": masi_value}}}}


def test_returns_context_unchanged_when_fewer_than_5_rows():
    context = _make_context(17984.0)
    db_module.insert_masi_daily("2026-06-24", 17984.0, None)
    result = mh.enrich(context)
    assert result["bvc"]["data"]["masi"] == {"value": 17984.0}


def test_computes_30d_trend_correctly():
    for i in range(35):
        date = f"2026-05-{i+1:02d}" if i < 31 else f"2026-06-{i-30:02d}"
        value = 17000.0 + i * 10
        db_module.insert_masi_daily(date, value, None)
    context = _make_context(17350.0)
    result = mh.enrich(context)
    masi = result["bvc"]["data"]["masi"]
    assert "change_30d_pct" in masi
    assert "week52_high" in masi
    assert "week52_low" in masi
    assert masi["week52_high"] >= masi["week52_low"]


def test_trend_label_rising():
    for i in range(35):
        db_module.insert_masi_daily(f"2026-05-{i+1:02d}" if i < 31 else f"2026-06-{i-30:02d}", 17000.0 + i * 50, None)
    context = _make_context(19000.0)
    result = mh.enrich(context)
    assert result["bvc"]["data"]["masi"]["trend"] == "rising"


def test_returns_unchanged_when_no_masi_value_in_context():
    for i in range(10):
        db_module.insert_masi_daily(f"2026-06-{i+1:02d}", 17000.0 + i * 10, None)
    context = {"bvc": {"data": {"masi": {}}}}
    result = mh.enrich(context)
    assert "change_30d_pct" not in result["bvc"]["data"]["masi"]
