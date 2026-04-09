from __future__ import annotations


def effective_routing_quality_thresholds(board) -> dict:
    """Return routing-quality thresholds from board settings.

    This is intentionally small at first; later phases will add per-board-class policy.
    """
    gates = dict(getattr(board, "quality_gates", None) or {})
    # Defaults: only require that some tracks exist when autoroute is enabled.
    return {
        "min_track_count": int(gates.get("min_track_count", 1) or 1),
        "max_via_count": int(gates.get("max_via_count", 10_000) or 10_000),
    }

