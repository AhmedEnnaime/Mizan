import pytest
import storage.db as db_module
import enrichment.outcome_tracker as ot


@pytest.fixture(autouse=True)
def reset_db(test_db, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db()


def test_returns_null_when_fewer_than_3_picks():
    context = {"bvc": {"data": {"stocks": []}}}
    db_module.insert_ai_pick("2026-06-24", "OCP", "BUY", 261.0, "test")
    db_module.insert_ai_pick("2026-06-24", "ATW", "WATCH", 685.0, "test")
    result = ot.enrich(context)
    assert result["past_performance"] is None


def test_computes_correct_outcome_for_buy_pick():
    db_module.insert_ai_pick("2026-06-10", "OCP", "BUY", 260.0, "test")
    db_module.insert_ai_pick("2026-06-11", "ATW", "AVOID", 700.0, "test")
    db_module.insert_ai_pick("2026-06-12", "MNG", "WATCH", 430.0, "test")
    context = {
        "bvc": {
            "data": {
                "stocks": [
                    {"ticker": "OCP", "close": 270.0},
                    {"ticker": "ATW", "close": 680.0},
                    {"ticker": "MNG", "close": 435.0},
                ]
            }
        }
    }
    result = ot.enrich(context)
    pp = result["past_performance"]
    assert pp is not None
    ocp_pick = next(p for p in pp["picks"] if p["ticker"] == "OCP")
    assert ocp_pick["outcome"] == "correct"
    assert ocp_pick["change_pct"] == pytest.approx(3.85, abs=0.1)

    atw_pick = next(p for p in pp["picks"] if p["ticker"] == "ATW")
    assert atw_pick["outcome"] == "correct"

    mng_pick = next(p for p in pp["picks"] if p["ticker"] == "MNG")
    assert mng_pick["outcome"] == "neutral"


def test_accuracy_summary_string_format():
    db_module.insert_ai_pick("2026-06-10", "OCP", "BUY", 260.0, "r")
    db_module.insert_ai_pick("2026-06-11", "ATW", "AVOID", 700.0, "r")
    db_module.insert_ai_pick("2026-06-12", "MNG", "BUY", 430.0, "r")
    context = {
        "bvc": {
            "data": {
                "stocks": [
                    {"ticker": "OCP", "close": 270.0},
                    {"ticker": "ATW", "close": 680.0},
                    {"ticker": "MNG", "close": 420.0},
                ]
            }
        }
    }
    result = ot.enrich(context)
    summary = result["past_performance"]["accuracy_summary"]
    assert "BUY" in summary
    assert "AVOID" in summary


def test_record_picks_writes_to_db():
    analysis = {
        "ai_picks": [
            {"ticker": "OCP", "label": "BUY", "explanation": "Strong phosphate signal"},
            {"ticker": "ATW", "label": "WATCH", "explanation": "Wait for data"},
        ]
    }
    context = {
        "bvc": {
            "data": {
                "stocks": [
                    {"ticker": "OCP", "close": 261.0},
                    {"ticker": "ATW", "close": 685.0},
                ]
            }
        }
    }
    ot.record_picks(analysis, context)
    picks = db_module.get_recent_ai_picks(days=1)
    assert len(picks) == 2
    ocp = next(p for p in picks if p["ticker"] == "OCP")
    assert ocp["pick"] == "BUY"
    assert ocp["price_at_pick"] == 261.0
