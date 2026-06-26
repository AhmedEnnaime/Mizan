import logging

logger = logging.getLogger(__name__)


def enrich(context: dict) -> tuple[dict, dict]:
    from enrichment import (
        company_profiles,
        sector_map,
        outcome_tracker,
        masi_history,
        reddit,
    )
    enrichers = [company_profiles, sector_map, outcome_tracker, masi_history, reddit]
    failed: list[str] = []
    for enricher in enrichers:
        try:
            context = enricher.enrich(context)
        except Exception as exc:
            logger.warning(f"Enricher {enricher.__name__} failed: {exc}")
            failed.append(enricher.__name__.split(".")[-1])
    stats = {"ok": len(enrichers) - len(failed), "total": len(enrichers), "failed": failed}
    return context, stats
