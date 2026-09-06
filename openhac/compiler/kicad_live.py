"""Open a KiCad GUI session on a generated schematic (SSO-012 live preview).

KiCad 9 does not hot-reload, and often does not prompt while a sheet is locked.
OpenHaC rewrites ``.kicad_sch`` / ``.kicad_pro`` on Python save; use File → Revert
or close and reopen the sheet. Overlay is always the last **saved** KiCad file.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("openhac.kicad_live")


def reset_preview_runtime() -> None:
    """Clear native + SKiDL circuits so a board script can be exec'd again."""
    from openhac.core.circuit import reset_default_circuit

    reset_default_circuit()
    try:
        import skidl

        skidl.reset()
    except Exception:
        pass
    sys.modules.pop("__user_board__", None)


def kicad_gui_binary() -> str | None:
    """Return a KiCad GUI executable on PATH, or None."""
    for name in ("kicad", "eeschema"):
        found = shutil.which(name)
        if found:
            return found
    return None


def spawn_kicad(project_or_sch: str | os.PathLike[str]) -> subprocess.Popen | None:
    """Launch KiCad on *project_or_sch*. Returns None if no GUI binary is found."""
    path = Path(project_or_sch)
    exe = kicad_gui_binary()
    if not exe:
        logger.error(
            "KiCad GUI not found on PATH (tried kicad, eeschema). "
            "Install KiCad or open %s from the KiCad project manager.",
            path,
        )
        return None
    logger.info("Opening KiCad: %s %s", exe, path)
    return subprocess.Popen(
        [exe, str(path)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def prefer_kicad_open_path(out_dir: str | os.PathLike[str], project_name: str) -> Path:
    """Prefer ``.kicad_pro`` so KiCad opens a project session; else the schematic."""
    base = Path(out_dir)
    pro = base / f"{project_name}.kicad_pro"
    if pro.is_file():
        return pro
    nested = base / project_name / f"{project_name}.kicad_pro"
    if nested.is_file():
        return nested
    sch = base / f"{project_name}.kicad_sch"
    if sch.is_file():
        return sch
    nested_sch = base / project_name / f"{project_name}.kicad_sch"
    return nested_sch if nested_sch.is_file() else sch


def watch_debounce_s(*, pcb: bool = False) -> float:
    """LIVE-007: wait until the script mtime is stable before merging (PCB emit is slower)."""
    raw = (os.environ.get("OPENHAC_PREVIEW_DEBOUNCE_S") or "").strip()
    if raw:
        try:
            return max(0.2, float(raw))
        except ValueError:
            pass
    return 0.8 if pcb else 0.4


KICAD_API_SOCK_GLOB = "api-*.sock"
_DEFAULT_KICAD_API_DIR = "/tmp/kicad"


def kicad_api_socket_dir() -> Path:
    raw = (os.environ.get("OPENHAC_KICAD_API_DIR") or "").strip()
    return Path(raw) if raw else Path(_DEFAULT_KICAD_API_DIR)


def discover_kicad_api_sockets(*, root: Path | None = None) -> list[Path]:
    """LIVE-010: KiCad 10 IPC sockets. Missing dir → empty list, never raises."""
    base = root if root is not None else kicad_api_socket_dir()
    try:
        if not base.is_dir():
            return []
        return sorted(p for p in base.glob(KICAD_API_SOCK_GLOB) if p.exists())
    except Exception:
        return []


def try_pcb_revert_via_ipc(
    pcb_path: str | os.PathLike[str],
    *,
    sockets: list[Path] | None = None,
    client=None,
) -> dict:
    """Best-effort KiCad 10 PCB revert/reload. Never raises. Does not touch schematic IPC.

    Schematic hot-reload is a KiCad 11 API and is not faked here.
    """
    result = {
        "attempted": False,
        "reloaded": False,
        "reason": "no_socket",
        "sockets": [],
        "schematic_reload": False,
        "note": "Schematic IPC is KiCad 11; OpenHaC does not fake schematic hot-reload.",
        "pcb": str(pcb_path),
    }
    found = list(sockets) if sockets is not None else discover_kicad_api_sockets()
    result["sockets"] = [str(s) for s in found]
    if not found:
        return result
    result["attempted"] = True
    ipc_client = client
    if ipc_client is None:
        ipc_client = _default_kicad_ipc_client()
    if ipc_client is None:
        result["reason"] = "kicad_api_unavailable"
        return result
    try:
        ok = False
        # Prefer named PCB methods over callable(): mock clients and kicad.KiCad()
        # instances are often callable and would otherwise swallow revert_pcb errors.
        if hasattr(ipc_client, "revert_pcb"):
            ok = bool(ipc_client.revert_pcb(str(pcb_path)))
        elif hasattr(ipc_client, "reload_board"):
            ok = bool(ipc_client.reload_board(str(pcb_path)))
        elif callable(ipc_client):
            ok = bool(ipc_client(str(pcb_path), found))
        else:
            result["reason"] = "kicad_api_unavailable"
            return result
        result["reloaded"] = bool(ok)
        result["reason"] = "reloaded" if ok else "revert_failed"
    except Exception as e:
        logger.info("LIVE-010: KiCad PCB IPC revert failed (continuing): %s", e)
        result["reloaded"] = False
        result["reason"] = f"ipc_error:{type(e).__name__}"
    return result


def _default_kicad_ipc_client():
    """Import kicad-python IPC client if present. Never imports pcbnew SaveBoard."""
    try:
        import importlib

        mod = importlib.import_module("kicad")
    except Exception:
        return None
    for name in ("KiCad", "Client"):
        cls = getattr(mod, name, None)
        if cls is None:
            continue
        try:
            return cls()
        except Exception:
            continue
    return None
