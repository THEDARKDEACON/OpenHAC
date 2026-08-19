"""ABC-026…050: BGA / highspeed / RF advanced board policy helpers."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("openhac.advanced_board_policy")

_BGA_RE = re.compile(r"\bBGA\b|Ball.?Grid|_BGA_|UBGA|FBGA|WLCSP|CSP[_-]?\d", re.I)


def footprint_looks_like_bga(footprint: str, package: str = "", description: str = "") -> bool:
    """ABC-026: heuristic BGA / ball-grid detection."""
    blob = f"{footprint} {package} {description}"
    return bool(_BGA_RE.search(blob))


def board_has_bga_parts(board) -> list[str]:
    """Return refs/names of components that look like BGA packages."""
    hits: list[str] = []
    try:
        mods = board._get_all_modules()
    except Exception:
        mods = list(getattr(board, "modules", []) or [])
    for mod in mods:
        for comp in getattr(mod, "components", []) or []:
            fp = ""
            pkg = ""
            desc = ""
            try:
                part = getattr(comp, "part", None)
                fp = str(getattr(part, "footprint", "") or "")
                data = getattr(comp, "comp_data", None) or {}
                if isinstance(data, dict):
                    fp = fp or str(data.get("kicad_footprint") or "")
                    pkg = str(data.get("package") or "")
                    desc = str(data.get("description") or "")
                gn = str(getattr(comp, "generic_name", "") or getattr(comp, "name", "") or "?")
            except Exception:
                continue
            if footprint_looks_like_bga(fp, pkg, desc):
                hits.append(gn)
    return hits


def check_bga_fab_gate(board) -> list[str]:
    """ABC-027: fab violations for BGA without waiver."""
    gates = dict(getattr(board, "quality_gates", None) or {})
    if gates.get("allow_manual_bga_fanout"):
        return []
    hits = board_has_bga_parts(board)
    if not hits:
        return []
    return [
        "ABC-027: BGA/ball-grid package(s) detected without quality_gates['allow_manual_bga_fanout']=True: "
        + ", ".join(hits[:12])
    ]


def check_highspeed_fab_gate(board) -> list[str]:
    """ABC-036/037: highspeed profile requires stackup + Z0 on diff pairs."""
    bc = str(getattr(board, "board_class", "") or "").strip().lower()
    if bc != "highspeed":
        return []
    v: list[str] = []
    stack_refs = list(getattr(board, "_stackup_references", None) or [])
    gates = dict(getattr(board, "quality_gates", None) or {})
    if not stack_refs and not gates.get("stackup_ref") and not getattr(board, "_sipi_stackup_path", None):
        v.append("ABC-036: board_class=highspeed requires declare_stackup_reference (or quality_gates['stackup_ref']) under fabrication.")
    pairs = list(getattr(board, "_diff_pair_intents", None) or [])
    for p in pairs:
        z0 = None
        if isinstance(p, dict):
            z0 = p.get("z0_ohm") or p.get("impedance_ohm") or p.get("z0")
        if z0 is None:
            v.append("ABC-037: differential pair missing Z0 metadata under highspeed fabrication.")
            break
    # Also inspect legacy constraints
    for c in getattr(board, "constraints", ()) or []:
        if isinstance(c, dict) and c.get("type") == "diff_pair":
            args = c.get("args") or ()
            if len(args) >= 3 and args[2] is None:
                v.append("ABC-037: differential pair missing Z0 metadata under highspeed fabrication.")
                break
    return v


def check_rf_fab_gate(board) -> list[str]:
    """ABC-046/047: rf profile requires keepout for RF modules + ground pour."""
    bc = str(getattr(board, "board_class", "") or "").strip().lower()
    if bc != "rf":
        return []
    gates = dict(getattr(board, "quality_gates", None) or {})
    if gates.get("allow_rf_without_keepout"):
        return []
    v: list[str] = []
    has_rf_mod = False
    try:
        mods = board._get_all_modules()
    except Exception:
        mods = list(getattr(board, "modules", []) or [])
    for mod in mods:
        for comp in getattr(mod, "components", []) or []:
            fp = ""
            try:
                part = getattr(comp, "part", None)
                fp = str(getattr(part, "footprint", "") or "")
                data = getattr(comp, "comp_data", None) or {}
                if isinstance(data, dict):
                    fp = fp or str(data.get("kicad_footprint") or "")
            except Exception:
                continue
            if "RF_Module" in fp or "WROOM" in fp.upper() or "ESP32" in fp.upper():
                has_rf_mod = True
                break
    keepouts = list(getattr(board, "_keepout_rect_intents", None) or [])
    if has_rf_mod and not keepouts:
        v.append("ABC-046: board_class=rf with RF module footprint requires declare_keepout_rect (or allow_rf_without_keepout).")
    pours = list(getattr(board, "_copper_pour_intents", None) or [])
    if has_rf_mod and not pours:
        v.append("ABC-047: board_class=rf requires declare_copper_pour_intent for ground.")
    return v


def apply_fanout_exclusions(board) -> list[str]:
    """ABC-028: merge fanout intent nets into no-autoroute set."""
    intents = list(getattr(board, "_fanout_intents", None) or [])
    names: list[str] = []
    for rec in intents:
        for key in ("nets", "net_names"):
            for n in list(rec.get(key) or []):
                names.append(str(n))
        if rec.get("net"):
            names.append(str(rec["net"]))
    for n in names:
        try:
            board.declare_no_autoroute_net(n)
        except Exception:
            # may need Net object — store on board list
            lst = getattr(board, "_no_autoroute_net_names", None)
            if lst is None:
                board._no_autoroute_net_names = []
                lst = board._no_autoroute_net_names
            if n not in lst:
                lst.append(n)
    return names


def write_fanout_constraints_json(board, out_dir: str | Path, project_name: str) -> Path | None:
    """ABC-029: emit fanout constraints JSON beside project."""
    intents = list(getattr(board, "_fanout_intents", None) or [])
    if not intents:
        return None
    path = Path(out_dir) / f"{project_name}.openhac-fanout-constraints.json"
    payload = {"schema_ref": "openhac.fanout_constraints.v1", "intents": intents}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_hs_netclass_handoff(board, out_dir: str | Path, project_name: str) -> Path | None:
    """ABC-039: emit netclass/rules handoff for highspeed boards."""
    bc = str(getattr(board, "board_class", "") or "").strip().lower()
    pairs = list(getattr(board, "_diff_pair_intents", None) or []) or list(
        getattr(board, "_differential_pairs", None) or []
    )
    if bc != "highspeed" and not pairs:
        return None
    path = Path(out_dir) / f"{project_name}.openhac-hs-netclass-handoff.json"
    payload = {
        "schema_ref": "openhac.hs_netclass_handoff.v1",
        "board_class": bc,
        "stackup_ref": getattr(board, "_stackup_ref", None) or getattr(board, "stackup_ref", None),
        "differential_pairs": pairs,
        "length_match_intents": list(getattr(board, "_length_match_intents", None) or []),
        "notes": "Apply as KiCad netclasses / custom rules; OpenHaC does not SI-certify geometry.",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_rf_emc_checklist(board, out_dir: str | Path, project_name: str) -> Path | None:
    """ABC-048: RF/EMC human/lab checklist markdown."""
    bc = str(getattr(board, "board_class", "") or "").strip().lower()
    if bc != "rf" and not list(getattr(board, "_keepout_rect_intents", None) or []):
        # still emit if RF modules present
        if not board_has_bga_parts(board):
            # check rf module cheaply
            pass
    if bc != "rf":
        return None
    path = Path(out_dir) / f"{project_name}.openhac-rf-emc-checklist.md"
    path.write_text(
        "\n".join(
            [
                "# RF / EMC handoff checklist (ABC-048 / SIG-004)",
                "",
                "OpenHaC does **not** claim EMC or RF performance sign-off.",
                "",
                "- [ ] Antenna matching network reviewed",
                "- [ ] RF keepouts verified vs module datasheet",
                "- [ ] Ground pour continuity under RF section",
                "- [ ] Cable / connector shield bonding plan",
                "- [ ] Enclosure and lab EMC test plan",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def suggest_rf_module_keepout(board, *, margin_mm: float = 5.0) -> list[dict]:
    """ABC-049: helper returning suggested keepout rects (caller may declare)."""
    # Placeholder suggestions near board corners — real placement needs FP bboxes post-layout.
    w, h = getattr(board, "size_mm", (100.0, 80.0))
    return [
        {
            "x_mm": margin_mm,
            "y_mm": margin_mm,
            "w_mm": min(40.0, float(w) * 0.3),
            "h_mm": min(40.0, float(h) * 0.3),
            "purpose": "rf_module_courtyard",
            "note": "ABC-049 suggested RF keepout — adjust to module placement",
        }
    ]
