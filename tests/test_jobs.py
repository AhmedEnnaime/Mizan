"""Tests for scheduler/jobs.py enrichment wiring (Task 10)."""
from unittest.mock import MagicMock, patch, call


def _make_context(masi_value=13500.0, masi_change=0.5):
    return {
        "date": "2026-06-26",
        "bvc": {
            "success": True,
            "data": {
                "stocks": [{"ticker": "OCP", "close": 262.0}],
                "masi": {"value": masi_value, "change_pct": masi_change},
                "madex": {},
            },
        },
        "commodities": {},
        "macro": {},
        "news": {"data": {"articles": []}},
        "technical": {},
        "watchlist": [],
    }


# ---------------------------------------------------------------------------
# collect_and_persist — MASI daily write
# ---------------------------------------------------------------------------

class TestCollectAndPersistMasi:
    def test_inserts_masi_daily_on_success(self, test_db):
        """MASI daily row is written when BVC collect succeeds and masi.value present."""
        import storage.db as db_module

        fake_bvc = {
            "success": True,
            "data": {
                "stocks": [],
                "masi": {"value": 13800.0, "change_pct": 1.2},
                "madex": {},
            },
        }

        with patch("collectors.bvc.collect", return_value=fake_bvc), \
             patch("collectors.commodities.collect", return_value={}), \
             patch("collectors.macro.collect", return_value={}), \
             patch("collectors.news.collect", return_value={"data": {"articles": []}}), \
             patch("collectors.technical.collect", return_value={}):
            from scheduler.jobs import collect_and_persist
            collect_and_persist()

        rows = db_module.get_masi_history(days=5)
        assert len(rows) == 1
        assert abs(rows[0]["value"] - 13800.0) < 0.01
        assert abs(rows[0]["change_pct"] - 1.2) < 0.01

    def test_skips_masi_insert_when_no_value(self, test_db):
        """No DB write happens when masi dict has no 'value' key."""
        import storage.db as db_module

        fake_bvc = {
            "success": True,
            "data": {
                "stocks": [],
                "masi": {},
                "madex": {},
            },
        }

        with patch("collectors.bvc.collect", return_value=fake_bvc), \
             patch("collectors.commodities.collect", return_value={}), \
             patch("collectors.macro.collect", return_value={}), \
             patch("collectors.news.collect", return_value={"data": {"articles": []}}), \
             patch("collectors.technical.collect", return_value={}):
            from scheduler.jobs import collect_and_persist
            collect_and_persist()

        rows = db_module.get_masi_history(days=5)
        assert rows == []

    def test_masi_insert_failure_does_not_raise(self, test_db):
        """A DB error during MASI insert must not propagate — briefing continues."""
        fake_bvc = {
            "success": True,
            "data": {
                "stocks": [],
                "masi": {"value": 13800.0, "change_pct": 0.3},
                "madex": {},
            },
        }

        with patch("collectors.bvc.collect", return_value=fake_bvc), \
             patch("collectors.commodities.collect", return_value={}), \
             patch("collectors.macro.collect", return_value={}), \
             patch("collectors.news.collect", return_value={"data": {"articles": []}}), \
             patch("collectors.technical.collect", return_value={}), \
             patch("storage.db.insert_masi_daily", side_effect=RuntimeError("db boom")):
            from scheduler.jobs import collect_and_persist
            result = collect_and_persist()  # must not raise

        assert result["date"] is not None


# ---------------------------------------------------------------------------
# run_morning_briefing — enrichment + record_picks wiring
# ---------------------------------------------------------------------------

class TestRunMorningBriefingEnrichment:
    def test_enrich_called_after_collect(self):
        """enrich() is called with the context returned by collect_and_persist()."""
        ctx = _make_context()
        analysis = {"headline": "ok", "ai_picks": []}

        with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
             patch("enrichment.enrich", return_value=ctx) as mock_enrich, \
             patch("enrichment.outcome_tracker.record_picks"), \
             patch("agent.analyst.run_morning_analysis", return_value=analysis), \
             patch("agent.formatter.format_morning_briefing", return_value="<html/>"), \
             patch("storage.db.save_briefing"), \
             patch("delivery.email.send_morning_briefing"):
            from scheduler import jobs
            jobs.run_morning_briefing(dry_run=True)

        mock_enrich.assert_called_once_with(ctx)

    def test_record_picks_called_after_analysis(self):
        """record_picks() is called with (analysis, enriched_context) after successful analysis."""
        ctx = _make_context()
        enriched = {**ctx, "enriched": True}
        analysis = {"headline": "ok", "ai_picks": [{"ticker": "OCP", "label": "BUY", "explanation": "test"}]}

        with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
             patch("enrichment.enrich", return_value=enriched), \
             patch("enrichment.outcome_tracker.record_picks") as mock_record, \
             patch("agent.analyst.run_morning_analysis", return_value=analysis), \
             patch("agent.formatter.format_morning_briefing", return_value="<html/>"), \
             patch("storage.db.save_briefing"), \
             patch("delivery.email.send_morning_briefing"):
            from scheduler import jobs
            jobs.run_morning_briefing(dry_run=True)

        mock_record.assert_called_once_with(analysis, enriched)

    def test_enrich_failure_does_not_stop_briefing(self):
        """If enrich() raises, the briefing still runs with the original context."""
        ctx = _make_context()
        analysis = {"headline": "ok", "ai_picks": []}

        with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
             patch("enrichment.enrich", side_effect=RuntimeError("enricher exploded")), \
             patch("enrichment.outcome_tracker.record_picks"), \
             patch("agent.analyst.run_morning_analysis", return_value=analysis) as mock_analysis, \
             patch("agent.formatter.format_morning_briefing", return_value="<html/>"), \
             patch("storage.db.save_briefing"), \
             patch("delivery.email.send_morning_briefing"):
            from scheduler import jobs
            jobs.run_morning_briefing(dry_run=True)  # must not raise

        mock_analysis.assert_called_once()

    def test_record_picks_failure_does_not_stop_briefing(self):
        """If record_picks() raises, the briefing continues to email/dry-run."""
        ctx = _make_context()
        analysis = {"headline": "ok", "ai_picks": []}

        with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
             patch("enrichment.enrich", return_value=ctx), \
             patch("enrichment.outcome_tracker.record_picks", side_effect=Exception("db gone")), \
             patch("agent.analyst.run_morning_analysis", return_value=analysis), \
             patch("agent.formatter.format_morning_briefing", return_value="<html/>") as mock_fmt, \
             patch("storage.db.save_briefing"), \
             patch("delivery.email.send_morning_briefing"):
            from scheduler import jobs
            jobs.run_morning_briefing(dry_run=True)  # must not raise

        mock_fmt.assert_called_once()

    def test_record_picks_not_called_on_ai_error(self):
        """record_picks() must NOT be called when analysis contains an 'error' key."""
        ctx = _make_context()

        with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
             patch("enrichment.enrich", return_value=ctx), \
             patch("enrichment.outcome_tracker.record_picks") as mock_record, \
             patch("agent.analyst.run_morning_analysis", return_value={"error": "timeout"}), \
             patch("storage.db.save_briefing"), \
             patch("delivery.email.send_morning_briefing"):
            from scheduler import jobs
            jobs.run_morning_briefing(dry_run=True)

        mock_record.assert_not_called()
