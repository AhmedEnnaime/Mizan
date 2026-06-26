import pytest
from unittest.mock import patch, MagicMock
import enrichment


def _noop_enrich(context):
    return context


def test_enrich_calls_all_enrichers():
    """All 5 sub-enrichers are invoked; enrich() returns (dict, stats) without raising."""
    no_op = MagicMock(side_effect=_noop_enrich)

    with (
        patch("enrichment.company_profiles.enrich", no_op),
        patch("enrichment.sector_map.enrich", no_op),
        patch("enrichment.outcome_tracker.enrich", no_op),
        patch("enrichment.masi_history.enrich", no_op),
        patch("enrichment.reddit.enrich", no_op),
    ):
        context, stats = enrichment.enrich({})

    assert isinstance(context, dict)
    assert stats == {"ok": 5, "total": 5, "failed": []}
    assert no_op.call_count == 5


def test_failing_enricher_does_not_abort_others():
    """A single failing enricher does not prevent the remaining ones from running."""
    failing = MagicMock(side_effect=Exception("boom"))
    succeeding = MagicMock(side_effect=_noop_enrich)

    # company_profiles raises; the other four must still run
    with (
        patch("enrichment.company_profiles.enrich", failing),
        patch("enrichment.sector_map.enrich", succeeding),
        patch("enrichment.outcome_tracker.enrich", succeeding),
        patch("enrichment.masi_history.enrich", succeeding),
        patch("enrichment.reddit.enrich", succeeding),
    ):
        context, stats = enrichment.enrich({})

    assert isinstance(context, dict)
    assert stats["ok"] == 4
    assert stats["total"] == 5
    assert "company_profiles" in stats["failed"]
    assert failing.call_count == 1
    assert succeeding.call_count == 4
