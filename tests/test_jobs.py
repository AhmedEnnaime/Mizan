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
             patch("enrichment.enrich", return_value=(ctx, {"ok": 5, "total": 5, "failed": []})) as mock_enrich, \
             patch("enrichment.outcome_tracker.record_picks"), \
             patch("agent.analyst.run_morning_analysis", return_value=analysis), \
             patch("agent.formatter.format_morning_briefing", return_value="<html/>"), \
             patch("storage.db.save_briefing"), \
             patch("storage.db.get_masi_history", return_value=[]), \
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
             patch("enrichment.enrich", return_value=(enriched, {"ok": 5, "total": 5, "failed": []})), \
             patch("enrichment.outcome_tracker.record_picks") as mock_record, \
             patch("agent.analyst.run_morning_analysis", return_value=analysis), \
             patch("agent.formatter.format_morning_briefing", return_value="<html/>"), \
             patch("storage.db.save_briefing"), \
             patch("storage.db.get_masi_history", return_value=[]), \
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
             patch("enrichment.enrich", return_value=(ctx, {"ok": 5, "total": 5, "failed": []})), \
             patch("enrichment.outcome_tracker.record_picks", side_effect=Exception("db gone")), \
             patch("agent.analyst.run_morning_analysis", return_value=analysis), \
             patch("agent.formatter.format_morning_briefing", return_value="<html/>") as mock_fmt, \
             patch("storage.db.save_briefing"), \
             patch("storage.db.get_masi_history", return_value=[]), \
             patch("delivery.email.send_morning_briefing"):
            from scheduler import jobs
            jobs.run_morning_briefing(dry_run=True)  # must not raise

        mock_fmt.assert_called_once()

    def test_record_picks_not_called_on_ai_error(self):
        """record_picks() must NOT be called when analysis contains an 'error' key."""
        ctx = _make_context()

        with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
             patch("enrichment.enrich", return_value=(ctx, {"ok": 5, "total": 5, "failed": []})), \
             patch("enrichment.outcome_tracker.record_picks") as mock_record, \
             patch("agent.analyst.run_morning_analysis", return_value={"error": "timeout"}), \
             patch("storage.db.save_briefing"), \
             patch("storage.db.get_masi_history", return_value=[]), \
             patch("delivery.email.send_morning_briefing"):
            from scheduler import jobs
            jobs.run_morning_briefing(dry_run=True)

        mock_record.assert_not_called()


# ---------------------------------------------------------------------------
# _write_debug_snapshot
# ---------------------------------------------------------------------------

class TestWriteDebugSnapshot:
    def test_creates_file_with_correct_structure(self, tmp_path, monkeypatch):
        """Snapshot JSON is written to logs/debug/ with expected top-level keys."""
        import json
        from observability.health import RunHealthCollector

        monkeypatch.setattr("scheduler.jobs.LOG_PATH", tmp_path / "logs" / "mizan.log")

        from scheduler.jobs import _write_debug_snapshot

        health = RunHealthCollector(run_id="run-0830", date="2026-06-26")
        health.stocks_collected = 5
        health.ai_ok = True

        context = {
            "bvc": {"data": {"stocks": [{"ticker": "OCP", "close": 262.0}]}},
            "news": {"data": {"articles": []}},
            "sector_map": {"Banking": {}},
        }

        _write_debug_snapshot(
            run_id="run-0830",
            date="2026-06-26",
            failed_at="email_delivery",
            exc=Exception("SMTP auth failed"),
            context=context,
            health=health,
        )

        debug_dir = tmp_path / "logs" / "debug"
        snapshots = list(debug_dir.glob("*.json"))
        assert len(snapshots) == 1

        data = json.loads(snapshots[0].read_text())
        assert data["run_id"] == "run-0830"
        assert data["failed_at"] == "email_delivery"
        assert "SMTP auth failed" in data["exception"]
        assert "traceback" in data
        assert "health" in data
        assert "context_snapshot" in data
        # sector_map must be stripped from snapshot
        assert "sector_map" not in data["context_snapshot"]

    def test_silent_fail_on_permission_error(self, tmp_path, monkeypatch, caplog):
        """If the debug dir cannot be written, a warning is logged and no exception propagates."""
        import logging
        from observability.health import RunHealthCollector

        # Point LOG_PATH to a path that cannot be created (file exists at parent location)
        bad_parent = tmp_path / "not_a_dir.txt"
        bad_parent.write_text("block")
        monkeypatch.setattr(
            "scheduler.jobs.LOG_PATH", bad_parent / "logs" / "mizan.log"
        )

        from scheduler.jobs import _write_debug_snapshot

        health = RunHealthCollector(run_id="run-0830", date="2026-06-26")

        with caplog.at_level(logging.WARNING, logger="scheduler.jobs"):
            _write_debug_snapshot(
                run_id="run-0830",
                date="2026-06-26",
                failed_at="ai_analysis",
                exc=Exception("oops"),
                context={},
                health=health,
            )

        assert any("debug snapshot" in r.message.lower() for r in caplog.records)
