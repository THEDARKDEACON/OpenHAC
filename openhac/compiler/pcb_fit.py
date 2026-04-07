from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("openhac.pcb_fit")


@dataclass(frozen=True)
class _BBox:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def contains(self, other: "_BBox") -> bool:
        return (
            self.left <= other.left
            and self.top <= other.top
            and self.right >= other.right
            and self.bottom >= other.bottom
        )

    def overlaps(self, other: "_BBox") -> bool:
        if self.right <= other.left:
            return False
        if other.right <= self.left:
            return False
        if self.bottom <= other.top:
            return False
        if other.bottom <= self.top:
            return False
        return True


def _bbox_from_any(bb) -> _BBox:
    """Extract bbox edges from KiCad-style BOX2I-ish objects or simple fakes."""
    # KiCad BOX2I often provides: GetX/GetY/GetWidth/GetHeight (top-left) or GetLeft/Right/Top/Bottom
    for attr_set in (
        ("GetLeft", "GetTop", "GetRight", "GetBottom"),
        ("GetX", "GetY", "GetWidth", "GetHeight"),
    ):
        if all(hasattr(bb, a) for a in attr_set):
            if attr_set[0] == "GetX":
                x = int(bb.GetX())
                y = int(bb.GetY())
                w = int(bb.GetWidth())
                h = int(bb.GetHeight())
                return _BBox(left=x, top=y, right=x + w, bottom=y + h)
            return _BBox(
                left=int(bb.GetLeft()),
                top=int(bb.GetTop()),
                right=int(bb.GetRight()),
                bottom=int(bb.GetBottom()),
            )
    # Some KiCad types expose Left/Right/Top/Bottom properties.
    if all(hasattr(bb, a) for a in ("Left", "Top", "Right", "Bottom")):
        return _BBox(left=int(bb.Left), top=int(bb.Top), right=int(bb.Right), bottom=int(bb.Bottom))
    raise TypeError(f"Unsupported bbox type: {type(bb)!r}")


def pcb_fit_violations_from_pcbnew_board(
    pcb,
    board,
    *,
    pcbnew_mod,
    margin_mm: float = 0.0,
    check_keepouts: bool = True,
) -> list[str]:
    """Return PCB fit violations from a loaded pcbnew board.

    This is a **best-effort** geometry check intended as a pipeline gate:
    - footprints must lie within the `Edge.Cuts` bounding box (bbox approximation)
    - footprints should not overlap declared keepout rectangles (bbox approximation)
    """
    violations: list[str] = []

    try:
        edges_bb = _bbox_from_any(pcb.GetBoardEdgesBoundingBox())
    except Exception as e:
        return [f"PCB fit: could not read board outline bounding box: {e}"]

    try:
        margin_iu = int(pcbnew_mod.FromMM(float(margin_mm)))
    except Exception:
        margin_iu = 0

    # Shrink allowable outline by margin (copper-to-edge style).
    allowed = _BBox(
        left=edges_bb.left + margin_iu,
        top=edges_bb.top + margin_iu,
        right=edges_bb.right - margin_iu,
        bottom=edges_bb.bottom - margin_iu,
    )

    keepouts: list[_BBox] = []
    if check_keepouts:
        for rec in (getattr(board, "_keepout_rect_intents", None) or []):
            if not isinstance(rec, dict):
                continue
            try:
                x = float(rec["x_mm"])
                y = float(rec["y_mm"])
                w = float(rec["w_mm"])
                h = float(rec["h_mm"])
            except Exception:
                continue
            try:
                x0 = int(pcbnew_mod.FromMM(x))
                y0 = int(pcbnew_mod.FromMM(y))
                x1 = int(pcbnew_mod.FromMM(x + w))
                y1 = int(pcbnew_mod.FromMM(y + h))
            except Exception:
                continue
            keepouts.append(_BBox(left=min(x0, x1), top=min(y0, y1), right=max(x0, x1), bottom=max(y0, y1)))

    fps = []
    try:
        fps = list(pcb.GetFootprints())
    except Exception:
        try:
            fps = list(pcb.Footprints())
        except Exception:
            fps = []

    for fp in fps:
        try:
            ref = str(fp.GetReference())
        except Exception:
            ref = "?"
        try:
            fbb = _bbox_from_any(fp.GetBoundingBox())
        except Exception as e:
            violations.append(f"PCB fit: footprint {ref} has no bounding box ({e}).")
            continue

        if not allowed.contains(fbb):
            violations.append(
                f"PCB fit: footprint {ref} is outside Edge.Cuts bbox "
                f"(fp=({fbb.left},{fbb.top})..({fbb.right},{fbb.bottom}), "
                f"edge=({allowed.left},{allowed.top})..({allowed.right},{allowed.bottom}), "
                f"margin_mm={margin_mm})."
            )

        for i, kb in enumerate(keepouts):
            if fbb.overlaps(kb):
                violations.append(f"PCB fit: footprint {ref} overlaps keepout_rect[{i}] (bbox approximation).")

    return violations


def pcb_fit_violations_for_pcb_path(
    pcb_path: str,
    board,
    *,
    margin_mm: float = 0.0,
    check_keepouts: bool = True,
) -> list[str]:
    """Load a `.kicad_pcb` and return fit violations; returns empty if pcbnew is unavailable."""
    try:
        import pcbnew  # type: ignore
    except Exception:
        return []
    try:
        pcb = pcbnew.LoadBoard(str(pcb_path))
    except Exception as e:
        return [f"PCB fit: failed to load PCB at {pcb_path!r}: {e}"]
    return pcb_fit_violations_from_pcbnew_board(
        pcb,
        board,
        pcbnew_mod=pcbnew,
        margin_mm=margin_mm,
        check_keepouts=check_keepouts,
    )

