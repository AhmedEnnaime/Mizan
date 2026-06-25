import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SECTOR_MAP_PATH = Path(__file__).parent.parent / "knowledge" / "sector_map.json"
_sector_map: dict | None = None


def _load() -> dict:
    global _sector_map
    if _sector_map is None:
        _sector_map = json.loads(_SECTOR_MAP_PATH.read_text())
    return _sector_map


def enrich(context: dict) -> dict:
    try:
        context["sector_map"] = _load()
    except Exception as exc:
        logger.warning(f"sector_map: failed to load sector map: {exc}")
    return context
