"""Write a JSON manifest after a successful ``Board.compile()`` (STR-002)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from openhac.compiler.release_bundle import _RELEASE_SUFFIXES
from openhac.version_info import get_version

logger = logging.getLogger("openhac.manifest")


def _logical_modules_manifest(board) -> list[dict]:
    """Top-level OpenHaC modules → SKiDL refs for SCH-002 hierarchy handoff."""
    from openhac.core.base import Module

    out: list[dict] = []
    for mod in getattr(board, "modules", None) or []:
        refs: set[str] = set()

        def walk(m):
            for c in getattr(m, "components", None) or []:
                if isinstance(c, Module):
                    walk(c)
                else:
                    p = getattr(c, "part", None)
                    if p is not None:
                        refs.add(str(getattr(p, "ref", "?")))

        walk(mod)
        out.append({"name": str(getattr(mod, "name", "?")), "references": sorted(refs)})
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _try_git_head(cwd: Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=cwd,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _try_git_branch(cwd: Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=cwd,
        )
        if r.returncode == 0:
            b = r.stdout.strip()
            return b if b and b != "HEAD" else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _spice_annotation_summary() -> dict:
    """Count BOM-visible SPICE fields on SKiDL parts (SIM-001 visibility)."""
    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
    except Exception:
        return {}

    def _nz(part, key: str) -> bool:
        try:
            v = part.fields.get(key, "") if hasattr(part, "fields") else ""
        except Exception:
            return False
        return bool(str(v or "").strip())

    inc = sub = 0
    for part in getattr(circuit, "parts", []) or []:
        if _nz(part, "Spice_Include"):
            inc += 1
        if _nz(part, "Spice_Subckt"):
            sub += 1
    return {"parts_with_spice_include": inc, "parts_with_spice_subckt": sub}


def _diff_pairs_from_board(board) -> list[dict]:
    out: list[dict] = []
    for c in getattr(board, "constraints", ()) or ():
        if c.get("type") != "diff_pair":
            continue
        args = c.get("args") or ()
        if len(args) < 2:
            continue
        p_net, n_net = args[0], args[1]
        z0 = float(args[2]) if len(args) > 2 else 90.0
        out.append(
            {
                "p_net": str(getattr(p_net, "name", p_net)),
                "n_net": str(getattr(n_net, "name", n_net)),
                "target_z0_ohms": z0,
            }
        )
    return out


def _jlc_class_line_summary_from_circuit() -> dict[str, int]:
    """Count BOM line items by JLC assembly class (LIB-005 manifest visibility)."""
    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
    except Exception:
        return {}
    ext = basic = unset = 0
    for part in getattr(circuit, "parts", []) or []:
        raw = str(part.fields.get("JLC_Class", "") if hasattr(part, "fields") else "").strip().lower()
        if raw == "extended":
            ext += 1
        elif raw == "basic":
            basic += 1
        else:
            unset += 1
    return {
        "extended_line_items": ext,
        "basic_line_items": basic,
        "unset_line_items": unset,
    }


def _write_mixed_signal_hint_md(base: Path, project_name: str, board) -> None:
    """SIG-006: human-readable net roles / merge hints for mixed-signal handoff."""
    roles = getattr(board, "_net_roles", None) or []
    merges = getattr(board, "_net_merge_hints", None) or []
    if not roles and not merges:
        return
    out = base / f"{project_name}.openhac-mixed-signal-hint.md"
    lines = [
        "# Mixed-signal / grounding handoff (SIG-006)",
        "",
        "OpenHaC records design intent only — implement star points, splits, and ferrite bridges in KiCad.",
        "",
    ]
    if roles:
        lines.append("## Net roles")
        lines.append("")
        for r in roles:
            lines.append(f"- **{r.get('net', '?')}** → `{r.get('role', '?')}`")
        lines.append("")
    if merges:
        lines.append("## Merge hints (star-point / ferrite)")
        lines.append("")
        for m in merges:
            lines.append(
                f"- `{m.get('net_a', '?')}` ↔ `{m.get('net_b', '?')}` via {m.get('via', '?')}"
            )
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_bom_alternates_json(base: Path, project_name: str, board) -> None:
    """LIB-002: machine-readable alternate rows from DB per BOM generic (Value)."""
    from openhac.core.base import Component

    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
    except Exception:
        return

    by_generic: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for part in getattr(circuit, "parts", []) or []:
        try:
            fv = part.fields.get("Value", "") if hasattr(part, "fields") else ""
        except Exception:
            fv = ""
        g = str(fv or getattr(part, "value", "") or "").strip()
        if not g or g in seen:
            continue
        seen.add(g)
        rows = Component.db.list_part_alternates(g)
        if not rows:
            continue
        by_generic[g] = [
            {
                "rank": int(r.get("rank") or 0),
                "alternate_mpn": r.get("alternate_mpn"),
                "alternate_supplier_sku": r.get("alternate_supplier_sku"),
                "note": r.get("note"),
                "alternate_group_id": r.get("alternate_group_id"),
            }
            for r in rows
        ]

    if not by_generic:
        return
    payload = {"schema": "openhac.bom_alternates.v1", "by_generic": by_generic}
    out = base / f"{project_name}.openhac-bom-alternates.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_si_stackup_reminder_md(base: Path, project_name: str, board, diff_pairs: list[dict]) -> None:
    """SIG-001 / PCB-003: short checklist when stackup or SI-relevant metadata exists."""
    reasons: list[str] = []
    if int(getattr(board, "layers", 2) or 2) > 2:
        reasons.append(f"**PCB-003:** {int(board.layers)} copper layers — complete stackup in KiCad; see `docs/stackup_template.yaml`.")
    if getattr(board, "_stackup_references", None):
        reasons.append("**SIG-001 / PCB-004:** stackup reference paths are recorded — correlate Dk/Df with impedance targets.")
    if diff_pairs:
        reasons.append("**SIG-002:** differential pairs declared — set controlled impedance / spacing in KiCad netclasses.")
        for dp in diff_pairs:
            reasons.append(
                f"  - Pair `{dp.get('p_net', '?')}` / `{dp.get('n_net', '?')}` → target **Z0 ≈ {dp.get('target_z0_ohms', '?')} Ω** (intent only)."
            )
    if getattr(board, "_copper_pour_intents", None):
        reasons.append("**PCB-009:** copper pour intent recorded — add zones and return paths in the layout tool.")
    if not reasons:
        return
    out = base / f"{project_name}.openhac-si-stackup-reminder.md"
    lines = [
        "# Stackup & SI reminder (SIG-001 / PCB-003)",
        "",
        "OpenHaC records design intent only; verify against your fab and SI tools.",
        "",
    ]
    for r in reasons:
        lines.append(f"- {r}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_bom_expand_hint_md(base: Path, project_name: str, board) -> None:
    """LIB-002: human note for CM BOM expand / collapse using alternates JSON."""
    altp = base / f"{project_name}.openhac-bom-alternates.json"
    if not altp.is_file():
        return
    out = base / f"{project_name}.openhac-bom-expand-hint.md"
    lines = [
        "# BOM alternates — CM handoff (LIB-002)",
        "",
        f"Machine list: `{project_name}.openhac-bom-alternates.json` (schema `openhac.bom_alternates.v1`).",
        "Use it to expand ranked alternates per `generic_name` into separate BOM rows or CM-specific templates.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_spice_model_hint_md(base: Path, project_name: str, board) -> None:
    """SIM-001: short SPICE / vendor model checklist when design uses SPICE fields."""
    s = _spice_annotation_summary()
    if not s or not (
        s.get("parts_with_spice_include", 0) or s.get("parts_with_spice_subckt", 0)
    ):
        return
    out = base / f"{project_name}.openhac-spice-model-hint.md"
    lines = [
        "# SPICE model handoff (SIM-001)",
        "",
        f"- Parts with **Spice_Include**: {s.get('parts_with_spice_include', 0)}",
        f"- Parts with **Spice_Subckt**: {s.get('parts_with_spice_subckt', 0)}",
        "",
        "Place vendor `.lib` / `.subckt` files on disk paths referenced by BOM fields; verify ngspice/Xyce compatibility.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_autoroute_policy_md(
    base: Path,
    project_name: str,
    board,
    diff_pairs: list[dict],
    *,
    auto_route: bool,
    skip_layout: bool,
) -> None:
    """PCB-007: document FreeRouting vs manual policy for this compile."""
    nar = list(getattr(board, "_no_autoroute_net_names", None) or [])
    # Skip file only for the vanilla case: layout ran, autoroute enabled, no special nets/pairs.
    if not skip_layout and not nar and not diff_pairs and auto_route:
        return
    out = base / f"{project_name}.openhac-autoroute-policy.md"
    lines = [
        "# Autoroute policy (PCB-007)",
        "",
        "OpenHaC FreeRouting is **routing assistance**, not high-speed or RF sign-off.",
        "",
    ]
    if skip_layout:
        lines.append("**Layout:** skipped (`OPENHAC_SKIP_LAYOUT` or headless build) — no placement/autoroute ran.")
        lines.append("")
    if nar:
        lines.append(f"**No-autoroute nets (manual in KiCad):** {', '.join(f'`{n}`' for n in nar)}")
        lines.append("")
    if diff_pairs:
        lines.append("**Differential pairs** are recorded for handoff — complete impedance-controlled routing in KiCad.")
        lines.append("")
    if not auto_route and not skip_layout:
        lines.append("**Auto-route:** disabled for this compile (`auto_route=False`).")
        lines.append("")
    elif not nar and auto_route and not skip_layout:
        lines.append("This build allowed auto-route on remaining nets (if layout ran).")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _openhac_env_keys_present() -> list[str]:
    """STR-002: which OPENHAC_* environment keys are set (names only)."""
    return sorted(k for k in os.environ if k.startswith("OPENHAC_"))


def _jit_confidence_histogram_from_circuit() -> dict[str, int]:
    """LIB-003: count BOM lines by OpenHaC JIT confidence label."""
    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
    except Exception:
        return {}
    hist: dict[str, int] = {}
    for part in getattr(circuit, "parts", []) or []:
        try:
            raw = part.fields.get("OpenHaC_JIT_Confidence", "") if hasattr(part, "fields") else ""
        except Exception:
            raw = ""
        lab = str(raw or "").strip().lower() or "unset"
        hist[lab] = hist.get(lab, 0) + 1
    return hist


def _stackup_json_summaries(board) -> list[dict]:
    """PCB-004: lightweight parse of referenced ``*.json`` stackup files."""
    out: list[dict] = []
    for ref in getattr(board, "_stackup_references", None) or []:
        p = Path(str(ref.get("path", "")))
        if p.suffix.lower() != ".json" or not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        layers = data.get("layers")
        out.append(
            {
                "path": str(p.resolve()),
                "role": ref.get("role"),
                "vendor_profile": data.get("vendor_profile"),
                "total_thickness_mm": data.get("total_thickness_mm"),
                "layer_count": len(layers) if isinstance(layers, list) else None,
            }
        )
    return out


def _kicad_symbol_dirs_configured() -> bool:
    """SCH-001: True if typical KiCad symbol dir env hints are present."""
    for k in os.environ:
        if "SYMBOL" in k.upper() and "KICAD" in k.upper():
            v = os.environ.get(k, "").strip()
            if v:
                return True
    v = os.environ.get("OPENHAC_KICAD_SYMBOL_DIRS", "").strip()
    return bool(v)


def _write_length_match_hint_md(base: Path, project_name: str, board) -> None:
    """SIG-005: human-readable length-match list for KiCad / external router."""
    lmg = getattr(board, "_length_match_groups", None) or []
    if not lmg:
        return
    out = base / f"{project_name}.openhac-length-match-hint.md"
    lines = [
        "# Length-match handoff (SIG-005)",
        "",
        "Declare these groups as matched-length in KiCad or your router; OpenHaC records intent only.",
        "",
    ]
    for g in lmg:
        name = g.get("name", "?")
        nets = g.get("nets") or []
        lines.append(f"## {name}")
        lines.append("")
        for n in nets:
            lines.append(f"- `{n}`")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def _write_pcb_routing_handoff_json(
    base: Path, project_name: str, board, diff_pairs: list[dict]
) -> None:
    """PCB-007 / SIG-002 / SIG-006: routing + diff + length + mixed-signal intent."""
    nar = list(getattr(board, "_no_autoroute_net_names", None) or [])
    lmg = list(getattr(board, "_length_match_groups", None) or [])
    nroles = list(getattr(board, "_net_roles", None) or [])
    nmh = list(getattr(board, "_net_merge_hints", None) or [])
    pours = list(getattr(board, "_copper_pour_intents", None) or [])
    mounts = list(getattr(board, "_mounting_hole_intents", None) or [])
    if not nar and not diff_pairs and not lmg and not nroles and not nmh and not pours and not mounts:
        return
    payload = {
        "schema": "openhac.pcb_routing_handoff.v1",
        "no_autoroute_nets": nar,
        "diff_pair_intent": list(diff_pairs),
        "length_match_groups": lmg,
        "net_roles": nroles,
        "net_merge_hints": nmh,
        "copper_pour_intents": pours,
        "mounting_hole_intents": mounts,
    }
    out = base / f"{project_name}.openhac-pcb-routing-handoff.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Wrote %s", out)


def _try_git_worktree_dirty(cwd: Path) -> bool | None:
    """Return True/False if *cwd* is a git checkout with a clean/dirty worktree; None if unknown."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=cwd,
        )
        if r.returncode != 0:
            return None
        return bool(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return None


def _source_input_record(path: str | os.PathLike[str] | None) -> dict | None:
    """Return path + hash for the compiled hardware description script, if present."""
    if path is None:
        return None
    p = Path(path).resolve()
    if not p.is_file():
        logger.warning("source_script_path is not a readable file: %s", p)
        return None
    return {
        "path": str(p),
        "bytes": p.stat().st_size,
        "sha256": _sha256_file(p),
    }


def _write_fab_stackup_handoff_md(base: Path, project_name: str, board) -> None:
    """Human-editable fab stackup stub when ``declare_stackup_reference`` was used (MFG-003)."""
    stack = getattr(board, "_stackup_references", None) or []
    if not stack:
        return
    out = base / f"{project_name}.openhac-fab-handoff.md"
    lines = [
        "# Fabrication stackup handoff (MFG-003)",
        "",
        "OpenHaC recorded these stackup / dielectric documentation paths at compile time.",
        "Complete a stackup table for your CM; see `examples/fab_stackup_table.md`.",
        "",
    ]
    for ref in stack:
        lines.append(f"- **{ref.get('role', '?')}**: `{ref.get('path', '?')}`")
        note = ref.get("documentation_note")
        if note:
            lines.append(f"  - Note: {note}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", out)


def write_compile_manifest(
    project_name: str,
    board,
    *,
    generate_bom: bool,
    export_schematic: bool,
    extra_outputs: list[str] | None = None,
    source_script_path: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    write_sha256_sidecar: bool = False,
    auto_route: bool = True,
    skip_layout: bool = False,
    release_zip_path: str | os.PathLike[str] | None = None,
) -> None:
    """Emit ``{project_name}.openhac-manifest.json`` listing outputs that exist on disk."""
    cwd = Path.cwd()
    base = Path(output_dir).resolve() if output_dir is not None else cwd
    outputs: list[dict] = []
    _write_fab_stackup_handoff_md(base, project_name, board)
    diff_pairs_early = _diff_pairs_from_board(board)
    _write_length_match_hint_md(base, project_name, board)
    _write_mixed_signal_hint_md(base, project_name, board)
    _write_si_stackup_reminder_md(base, project_name, board, diff_pairs_early)
    _write_pcb_routing_handoff_json(base, project_name, board, diff_pairs_early)
    if generate_bom:
        _write_bom_alternates_json(base, project_name, board)
    _write_bom_expand_hint_md(base, project_name, board)
    _write_spice_model_hint_md(base, project_name, board)
    _write_autoroute_policy_md(
        base, project_name, board, diff_pairs_early, auto_route=auto_route, skip_layout=skip_layout
    )

    def add_if_exists(rel_name: str) -> None:
        p = (base / rel_name).resolve()
        if not p.is_file():
            return
        try:
            display = str(p.relative_to(cwd))
        except ValueError:
            display = str(p)
        outputs.append(
            {
                "path": display,
                "bytes": p.stat().st_size,
                "sha256": _sha256_file(p),
            }
        )

    add_if_exists(f"{project_name}.openhac-fab-handoff.md")
    add_if_exists(f"{project_name}.openhac-length-match-hint.md")
    add_if_exists(f"{project_name}.openhac-mixed-signal-hint.md")
    add_if_exists(f"{project_name}.openhac-pcb-routing-handoff.json")
    add_if_exists(f"{project_name}.openhac-bom-alternates.json")
    add_if_exists(f"{project_name}.openhac-si-stackup-reminder.md")
    add_if_exists(f"{project_name}.openhac-bom-expand-hint.md")
    add_if_exists(f"{project_name}.openhac-spice-model-hint.md")
    add_if_exists(f"{project_name}.openhac-autoroute-policy.md")
    add_if_exists(f"{project_name}.net")
    add_if_exists(f"{project_name}.kicad_pcb")
    if generate_bom:
        add_if_exists(f"{project_name}.csv")
    if export_schematic:
        add_if_exists(f"{project_name}.kicad_sch")
        add_if_exists(f"{project_name}.kicad_pro")

    for rel in extra_outputs or []:
        add_if_exists(rel)

    gh = _try_git_head(cwd)
    gbr = _try_git_branch(cwd)
    dirty = _try_git_worktree_dirty(cwd)
    manifest: dict = {
        "manifest_schema_version": "1.0",
        "openhac_version": get_version(),
        "project_name": project_name,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "board_size_mm": [float(board.size_mm[0]), float(board.size_mm[1])],
        "layers": int(board.layers),
        "git_commit": gh,
        "outputs": sorted(outputs, key=lambda x: x["path"]),
    }
    if gbr:
        manifest["git_branch"] = gbr
    if int(board.layers) > 2:
        manifest["pcb_stackup_layer_note"] = (
            f"PCB-003: {int(board.layers)} copper layers declared; OpenHaC does not emit KiCad stackup metadata. "
            "Use Board.declare_stackup_reference() and docs/stackup_template.yaml for fab / SI handoff."
        )
    nar = getattr(board, "_no_autoroute_net_names", None) or []
    if nar:
        manifest["no_autoroute_nets"] = list(nar)
    if dirty is not None:
        manifest["git_worktree_dirty"] = dirty
    net_roles = getattr(board, "_net_roles", None) or []
    if net_roles:
        manifest["net_roles"] = list(net_roles)
    lmg = getattr(board, "_length_match_groups", None) or []
    if lmg:
        manifest["length_match_groups"] = list(lmg)
        manifest["length_match_group_count"] = len(lmg)
    diff_pairs = diff_pairs_early
    if diff_pairs:
        manifest["diff_pair_intent"] = diff_pairs
    stack = getattr(board, "_stackup_references", None) or []
    if stack:
        manifest["stackup_references"] = list(stack)
    sj = _stackup_json_summaries(board)
    if sj:
        manifest["stackup_json_summaries"] = sj
    dfm = getattr(board, "_dfm_references", None) or []
    if dfm:
        manifest["dfm_references"] = list(dfm)
    pours_m = getattr(board, "_copper_pour_intents", None) or []
    if pours_m:
        manifest["copper_pour_intents"] = list(pours_m)
    mounts_m = getattr(board, "_mounting_hole_intents", None) or []
    if mounts_m:
        manifest["mounting_hole_intents"] = list(mounts_m)
    lmods = _logical_modules_manifest(board)
    if lmods:
        manifest["logical_modules"] = lmods
        manifest["schematic_hierarchy_handoff"] = {
            "logical_module_count": len(lmods),
            "note": (
                "OpenHaC emits a flat .kicad_sch; use logical_modules[].name and references[] "
                "to partition symbols across KiCad hierarchical sheets (SCH-002)."
            ),
        }
    if output_dir is not None:
        manifest["output_directory"] = str(base)
    src = _source_input_record(source_script_path)
    if src is not None:
        manifest["source_input"] = src

    tag = (getattr(board, "release_tag", None) or "").strip() or (
        os.environ.get("OPENHAC_RELEASE_TAG") or ""
    ).strip()
    if tag:
        manifest["release_tag"] = tag
    profile = (getattr(board, "build_profile", None) or "").strip() or (
        os.environ.get("OPENHAC_BUILD_PROFILE") or ""
    ).strip()
    if profile:
        manifest["build_profile"] = profile
    bom_prof = (getattr(board, "bom_profile", None) or "").strip()
    if bom_prof:
        manifest["bom_profile"] = bom_prof
        if bom_prof.lower() in ("prod", "production", "cm"):
            from openhac.compiler.netlist_gen import BOM_PROFILE_PROD_OMITTED_COLUMNS

            manifest["bom_prod_omitted_columns"] = sorted(BOM_PROFILE_PROD_OMITTED_COLUMNS)

    manifest["build_environment"] = {
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
    }
    manifest["openhac_env_keys_present"] = _openhac_env_keys_present()
    manifest["sch_kicad_symbol_dirs_configured"] = _kicad_symbol_dirs_configured()
    manifest["pcb_pipeline_handoff"] = {
        "placement": "PCB-001: footprints placed via generate_layout (pcbnew); coords from solver + module grid.",
        "netlist_to_pcb": "PCB-002: pad nets from SKiDL; use strict_footprint_pin_pad_match for pad-name parity.",
    }
    fp = getattr(board, "fab_profile", None)
    if fp:
        manifest["fab_profile"] = str(fp)
    jith = _jit_confidence_histogram_from_circuit()
    if jith:
        manifest["jit_confidence_histogram"] = jith
    manifest["compile_options"] = {
        "auto_route": bool(auto_route),
        "skip_layout": bool(skip_layout),
        "release_zip_requested": bool(release_zip_path),
    }
    if release_zip_path:
        manifest["release_zip_path"] = str(Path(release_zip_path).resolve())
    manifest["compile_strictness"] = {
        "board_strict_umbrella": bool(getattr(board, "strict", False)),
        "strict_kicad": bool(getattr(board, "strict_kicad", False)),
        "strict_jit_lookups": bool(getattr(board, "strict_jit_lookups", False)),
    }
    jlc_sum = _jlc_class_line_summary_from_circuit()
    if jlc_sum and sum(jlc_sum.values()) > 0:
        manifest["jlc_assembly_line_summary"] = jlc_sum
    nmh = getattr(board, "_net_merge_hints", None) or []
    if nmh:
        manifest["net_merge_hints"] = list(nmh)

    spice_sum = _spice_annotation_summary()
    if spice_sum and (
        spice_sum.get("parts_with_spice_include", 0) or spice_sum.get("parts_with_spice_subckt", 0)
    ):
        manifest["spice_annotation_summary"] = spice_sum

    manifest["release_bundle_suffixes"] = list(_RELEASE_SUFFIXES)

    out_path = base / f"{project_name}.openhac-manifest.json"
    text = json.dumps(manifest, indent=2, sort_keys=True)
    out_path.write_text(text, encoding="utf-8")
    logger.info("Wrote %s", out_path)
    if write_sha256_sidecar:
        hx = hashlib.sha256(text.encode("utf-8")).hexdigest()
        side = out_path.with_name(out_path.name + ".sha256")
        side.write_text(hx + "\n", encoding="utf-8")
        logger.info("Wrote %s", side)
