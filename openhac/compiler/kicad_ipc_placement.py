"""KiCad 10+ IPC (kipy) placement / sync helpers.

The compile pipeline still *generates* ``.kicad_pcb`` via pcbnew SWIG
(``FindPlugin`` / ``PCB_IO_KICAD_SEXPR``). When a KiCad GUI session is open with
the IPC API enabled, this module can:

* reload/revert the open board onto the generated file (LIVE-010), and/or
* push OpenHaC placement positions onto footprints already on the open board.

Set ``OPENHAC_PLACEMENT_BACKEND=ipc`` to prefer IPC position push after SWIG
emit, or ``auto`` (default) to push when a socket is available.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("openhac.kicad_ipc")


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def placement_backend() -> str:
    """``swig`` | ``ipc`` | ``auto`` (default)."""
    raw = (os.environ.get("OPENHAC_PLACEMENT_BACKEND") or "auto").strip().lower()
    if raw in ("swig", "pcbnew", "legacy"):
        return "swig"
    if raw in ("ipc", "kipy", "api"):
        return "ipc"
    return "auto"


def ipc_available() -> bool:
    """True when kipy imports and at least one KiCad API socket exists."""
    try:
        from openhac.compiler.kicad_live import discover_kicad_api_sockets

        if not discover_kicad_api_sockets():
            return False
    except Exception:
        return False
    try:
        import kipy  # noqa: F401

        return True
    except Exception:
        return False


def connect_kicad(*, timeout_ms: int = 2000):
    """Return a connected :class:`kipy.KiCad` client, or ``None``."""
    try:
        from kipy import KiCad
    except Exception as e:
        logger.debug("kipy not importable: %s", e)
        return None
    try:
        return KiCad(timeout_ms=timeout_ms)
    except Exception as e:
        logger.info("KiCad IPC connect failed (is Preferences → Plugins → API enabled?): %s", e)
        return None


def sync_generated_pcb_via_ipc(pcb_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Ask a running KiCad session to revert/reload *pcb_path* (LIVE-010)."""
    from openhac.compiler.kicad_live import try_pcb_revert_via_ipc

    return try_pcb_revert_via_ipc(pcb_path)


def push_placement_positions_via_ipc(board) -> dict[str, Any]:
    """Update footprint XY on the open PCB to match OpenHaC module placement.

    Requires KiCad open on the matching board with footprints already present
    (typically after SWIG emit + IPC reload). Never raises — returns a status dict.
    """
    result: dict[str, Any] = {
        "attempted": False,
        "updated": 0,
        "missing": [],
        "reason": "not_run",
    }
    if placement_backend() == "swig":
        result["reason"] = "backend_swig"
        return result
    if placement_backend() == "auto" and not ipc_available():
        result["reason"] = "no_ipc_socket"
        return result

    kicad = connect_kicad()
    if kicad is None:
        result["reason"] = "connect_failed"
        return result
    result["attempted"] = True
    try:
        pcb = kicad.get_board()
    except Exception as e:
        result["reason"] = f"no_open_board:{type(e).__name__}"
        logger.info("IPC placement: no open PCB in KiCad (%s)", e)
        return result

    try:
        from kipy.geometry import Vector2
    except Exception as e:
        result["reason"] = f"geometry_import:{e}"
        return result

    try:
        from openhac.compiler.pcb_placement import collect_skidl_part_positions

        positions = collect_skidl_part_positions(board)
    except Exception as e:
        result["reason"] = f"positions:{e}"
        return result

    fps = {str(fp.reference_field.text.value): fp for fp in pcb.get_footprints()}
    to_update = []
    for ref, (x_mm, y_mm) in positions.items():
        fp = fps.get(str(ref))
        if fp is None:
            result["missing"].append(str(ref))
            continue
        try:
            fp.position = Vector2.from_xy_mm(float(x_mm), float(y_mm))
            to_update.append(fp)
        except Exception as e:
            logger.debug("IPC: could not set position for %s: %s", ref, e)

    if not to_update:
        result["reason"] = "nothing_to_update"
        return result

    try:
        commit = pcb.begin_commit()
        pcb.update_items(to_update)
        pcb.push_commit(commit, "OpenHaC IPC placement sync")
        result["updated"] = len(to_update)
        result["reason"] = "ok"
        logger.info("IPC: updated %d footprint position(s) in open KiCad board.", len(to_update))
    except Exception as e:
        result["reason"] = f"update_failed:{type(e).__name__}"
        logger.warning("IPC placement update failed: %s", e)
    return result


def maybe_sync_after_layout(pcb_path: str | os.PathLike[str], board) -> dict[str, Any]:
    """Post-layout hook: reload generated PCB into KiCad, then push positions."""
    out: dict[str, Any] = {"reload": None, "positions": None}
    if placement_backend() == "swig":
        return out
    if placement_backend() == "auto" and not ipc_available():
        return out
    path = Path(pcb_path)
    if path.is_file():
        out["reload"] = sync_generated_pcb_via_ipc(path)
    out["positions"] = push_placement_positions_via_ipc(board)
    try:
        board._last_kicad_ipc_sync = dict(out)
    except Exception:
        pass
    return out
