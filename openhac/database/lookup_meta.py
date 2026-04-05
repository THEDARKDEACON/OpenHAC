"""Internal metadata for JIT / live part resolution (LIB-003).

``_openhac_*`` keys must never be persisted to SQLite; strip before ``INSERT``.
"""

from __future__ import annotations

INTERNAL_PREFIX = "_openhac_"
LOOKUP_CONFIDENCE_KEY = "_openhac_lookup_confidence"

# high: local DB row or strong JIT match (known footprint map + query matched part)
# medium: JIT with query↔part match but heuristic symbol/footprint
# low: weak JIT (e.g. first API hit only, or generic_name live lookup with Device:Q)
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


def strip_openhac_internal_fields(data: dict) -> dict:
    return {k: v for k, v in data.items() if not k.startswith(INTERNAL_PREFIX)}


def get_lookup_confidence(data: dict) -> str:
    return data.get(LOOKUP_CONFIDENCE_KEY, CONFIDENCE_HIGH)


def confidence_numeric(conf: str) -> float:
    """Rough 0–1 score for BOM / manifest (LIB-003 phase-1); not a statistical confidence."""
    return {
        CONFIDENCE_HIGH: 1.0,
        CONFIDENCE_MEDIUM: 0.65,
        CONFIDENCE_LOW: 0.25,
    }.get(conf, 1.0)


def is_low_confidence(confidence: str) -> bool:
    return confidence == CONFIDENCE_LOW


def is_medium_confidence(confidence: str) -> bool:
    return confidence == CONFIDENCE_MEDIUM
