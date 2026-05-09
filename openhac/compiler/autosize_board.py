from __future__ import annotations

import logging
import math
import os

logger = logging.getLogger("openhac.autosize")


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _pack_extents(items: list[tuple[float, float]], *, cols: int, gap_mm: float) -> tuple[float, float]:
    """Deterministic shelf packer extents for (w,h) items."""
    if not items:
        return (0.0, 0.0)
    cols = max(1, int(cols))
    x_cursor = 0.0
    y_row = 0.0
    row_max_h = 0.0
    col = 0
    max_r = 0.0
    max_b = 0.0
    for w, h in items:
        w = float(w or 0.0)
        h = float(h or 0.0)
        max_r = max(max_r, x_cursor + w)
        max_b = max(max_b, y_row + h)
        row_max_h = max(row_max_h, h + gap_mm)
        col += 1
        x_cursor += w + gap_mm
        if col >= cols:
            col = 0
            x_cursor = 0.0
            y_row += row_max_h
            row_max_h = 0.0
    return (max_r, max_b)


def maybe_autosize_board(board) -> bool:
    """Autosize ``board.size_mm`` only when the user left it unspecified.

    This is intentionally conservative: we do **not** resize boards that already
    have a concrete size set by user code.

    Returns True if autosizing occurred.
    """
    if not bool(getattr(board, "_size_mm_unspecified", False)):
        return False

    # Require module bbox sizes to be present.
    try:
        mods = list(getattr(board, "_get_all_modules", lambda: getattr(board, "modules", []) or [])())
    except Exception:
        mods = list(getattr(board, "modules", []) or [])
    mods = [m for m in mods if m is not None]
    if not mods:
        return False

    # Prefer pcbnew footprint bbox packing to size the board tighter.
    packed = False
    pack_w = 0.0
    pack_h = 0.0
    pack_item_count = 0
    try:
        from openhac.compiler.pcb_placement import (
            circuit_parts_from_board,
            _fp_size_mm_for_part,  # type: ignore
            _get_kicad_sexp_plugin,  # type: ignore
        )

        use_fp = os.environ.get("OPENHAC_PLACEMENT_USE_FP_BBOX", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        if use_fp:
            import pcbnew as pcbnew_mod  # type: ignore

            plugin = _get_kicad_sexp_plugin(pcbnew_mod)
            parts = list(circuit_parts_from_board(board))
            try:
                grid_mm = float(os.environ.get("OPENHAC_PLACEMENT_GRID_MM", "").strip() or 7.0)
            except Exception:
                grid_mm = 7.0
            try:
                gap_mm = float(os.environ.get("OPENHAC_PLACEMENT_FP_GAP_MM", "").strip() or 1.0)
            except Exception:
                gap_mm = 1.0
            fp_cache: dict[tuple[str, str], tuple[float, float]] = {}
            sizes: list[tuple[float, float]] = []
            for p in parts:
                fw, fh = _fp_size_mm_for_part(p, plugin, pcbnew_mod, fp_cache, grid_mm=grid_mm)
                sizes.append((fw, fh))
            if sizes:
                pack_item_count = len(sizes)
                cols = _env_int("OPENHAC_AUTO_BOARD_PACK_COLS", 0)
                if cols <= 0:
                    cols = int(math.ceil(math.sqrt(pack_item_count)))
                pack_w, pack_h = _pack_extents(sizes, cols=cols, gap_mm=gap_mm)
                packed = pack_w > 0 and pack_h > 0
    except Exception:
        packed = False

    margin = _env_float("OPENHAC_AUTO_BOARD_MARGIN_FACTOR", 1.15)
    margin = min(max(margin, 1.0), 3.0)
    pad_mm = _env_float("OPENHAC_AUTO_BOARD_MIN_EDGE_MARGIN_MM", 5.0)
    if packed:
        w = (pack_w * margin) + 2 * pad_mm
        h = (pack_h * margin) + 2 * pad_mm
        source = f"footprint_pack n={pack_item_count}"
    else:
        # Fallback: legacy module-area method.
        areas: list[float] = []
        max_w = 0.0
        max_h = 0.0
        for m in mods:
            try:
                w0 = float(getattr(m, "width", 0.0) or 0.0)
                h0 = float(getattr(m, "height", 0.0) or 0.0)
            except Exception:
                continue
            if w0 <= 0 or h0 <= 0:
                continue
            areas.append(w0 * h0)
            max_w = max(max_w, w0)
            max_h = max(max_h, h0)
        if not areas:
            return False
        total_area = float(sum(areas))
        util = _env_float("OPENHAC_AUTO_BOARD_UTILIZATION", 0.45)
        util = min(max(util, 0.15), 0.85)
        target_area = (total_area / util) * margin
        ar = _env_float("OPENHAC_AUTO_BOARD_ASPECT_RATIO", 1.0)  # w/h
        ar = min(max(ar, 0.3), 3.0)
        w = math.sqrt(target_area * ar)
        h = math.sqrt(target_area / ar)
        w = max(w, max_w + 2 * pad_mm)
        h = max(h, max_h + 2 * pad_mm)
        source = f"module_area {total_area:.1f}mm2"

    # Round up to whole mm for stable outputs.
    w2 = float(math.ceil(w))
    h2 = float(math.ceil(h))

    board.size_mm = (w2, h2)
    try:
        board._size_mm_unspecified = False
    except Exception:
        pass

    logger.info(
        "Auto-sized board to %.0fx%.0f mm (%s, margin=%.2f edge_margin=%.2f).",
        w2,
        h2,
        source,
        margin,
        pad_mm,
    )
    return True

