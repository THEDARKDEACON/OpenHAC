"""Compile orchestration phases (thin slices for testing and future plugins).

``Board.compile`` builds a :class:`CompileState` and runs ordered phase callables.
Earlier phases (ERC, netlist) are independent of later ones (zip); failures still
leave prior artifacts on disk.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from openhac.core.board import Board

logger = logging.getLogger("openhac.compile_pipeline")


def _stamp_board(board: object, name: str, value: object) -> None:
    try:
        setattr(board, name, value)
    except Exception:
        pass


@dataclass
class CompileState:
    board: Board
    project_name: str
    generate_bom: bool
    auto_route: bool
    export_schematic: bool
    allow_risky_part_lookups: bool
    compile_goal: str = field(init=False)
    board_class: str = field(init=False)
    quality_gates: dict = field(init=False)
    kicad_sch_erc: bool
    kicad_sch_erc_format: str
    source_script_path: str | os.PathLike[str] | None
    output_dir: str | os.PathLike[str] | None
    release_zip_path: str | os.PathLike[str] | None
    bbox_padding_mm: float = 0.5
    module_clearance_mm: float = 0.0
    keep_kicad_artwork: bool = False
    regenerate_artwork: bool = False
    require_lock: bool = False
    lock_file: str | os.PathLike[str] | None = None
    placement_intent: bool = False
    require_testpoints: bool = False
    skip_layout: bool = field(init=False)
    net_path: str = field(init=False)
    bom_path: str | None = field(init=False)
    pcb_path: str = field(init=False)
    sch_path: str | None = field(init=False)
    pro_path: str | None = field(init=False)
    erc_report_name: str | None = field(default=None, init=False)
    pcb_metrics: dict = field(default_factory=dict, init=False)
    enrich_metrics: dict = field(default_factory=lambda: {"poisoned_parts": []}, init=False)
    omitted_footprint_refs: list[str] = field(default_factory=list, init=False)
    enrich_failures: list[dict] = field(default_factory=list, init=False)
    pad_pin_warnings: list[str] = field(default_factory=list, init=False)
    network_allowed_at_compile: bool | None = field(default=None, init=False)
    kicad_pcb_drc_report: str | None = field(default=None, init=False)
    schematic_signoff: bool = field(default=False, init=False)
    compile_profile: str = field(default="", init=False)
    lean_manifest: bool = field(default=False, init=False)
    phase_ms: dict = field(default_factory=dict, init=False)
    pcbnew_board: object | None = field(default=None, init=False)
    _owned_defer_pours: bool = field(default=False, init=False)
    _prev_defer_pours: str | None = field(default=None, init=False)
    artwork_overlay: object | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.skip_layout = os.environ.get("OPENHAC_SKIP_LAYOUT", "").lower() in ("1", "true", "yes")
        from openhac.core.board import _artifact_path
        self.compile_goal = self.board.effective_compile_goal()
        self.board_class = str(getattr(self.board, "board_class", "generic") or "generic")
        self.quality_gates = dict(getattr(self.board, "quality_gates", None) or {})
        env_sso = os.environ.get("OPENHAC_SCHEMATIC_SIGNOFF", "").strip().lower() in ("1", "true", "yes", "on")
        self.schematic_signoff = bool(getattr(self.board, "schematic_signoff", False)) or env_sso or bool(
            self.quality_gates.get("schematic_signoff")
        )
        if self.schematic_signoff:
            self.export_schematic = True
            self.kicad_sch_erc = True
        if self.require_testpoints:
            try:
                self.board._require_testpoints = True
            except Exception:
                pass
        if self.require_lock:
            try:
                self.board._require_lock = True
            except Exception:
                pass
        try:
            self.bbox_padding_mm = float(self.bbox_padding_mm or 0.0)  # STYLE-001: direct field access
        except Exception:
            self.bbox_padding_mm = 0.5

        self.net_path = _artifact_path(self.project_name, ".net", self.output_dir)
        self.bom_path = (
            _artifact_path(self.project_name, ".csv", self.output_dir) if self.generate_bom else None
        )
        self.pcb_path = _artifact_path(self.project_name, ".kicad_pcb", self.output_dir)
        # Autosize boards lock size_mm during layout; restore on fabrication retry.
        self.started_with_autosize = bool(getattr(self.board, "_size_mm_unspecified", False))


def phase_enrich_parts(state: CompileState) -> None:
    """Online enrichment phase to fill missing pinout/symbol metadata before pin access.

    This is best-effort in handoff mode, and required in fabrication mode (because implicit
    pins and pad mismatches make outputs non-fabricable).
    """
    attempted = 0
    updated = 0
    skipped = 0
    failed = 0
    try:
        from openhac.database.enrich import enrich_component_in_db, needs_pinout_database_enrich, network_allowed
    except Exception as e:
        logger.exception("Enrich module import failed (FAB-013)")
        state.enrich_failures.append({"generic_name": "*", "reason": f"import_failed:{e}"})
        state.enrich_metrics.update(
            {"attempted": 0, "updated": 0, "skipped": 0, "failed": 1, "network": None, "import_error": str(e)}
        )
        if state.compile_goal == "fabrication":
            raise RuntimeError(f"FAB-013: enrich import failed in fabrication mode: {e}") from e
        return

    allow_net = network_allowed()
    state.network_allowed_at_compile = bool(allow_net)
    if not allow_net and state.compile_goal == "fabrication":
        # Still allow the existing pinout gate to fail with a clearer list later.
        state.enrich_metrics.update({"attempted": 0, "updated": 0, "skipped": 0, "failed": 0, "network": False})
        return

    try:
        modules = state.board._get_all_modules()
    except Exception:
        modules = getattr(state.board, "modules", []) or []

    seen: set[str] = set()
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            gn = str(getattr(comp, "generic_name", "") or "").strip()
            if not gn or gn in seen:
                continue
            seen.add(gn)
            try:
                cd = getattr(comp, "_comp_data", {}) or {}
                row = None
                try:
                    row = comp.db.get_component(gn)  # type: ignore[attr-defined]
                except Exception:
                    row = None
                row_d = dict(row) if row else None
                from openhac.database.enrich import _get_override_asset
                has_override = _get_override_asset(gn) or _get_override_asset(cd.get("supplier_sku") or "")
                is_poisoned = gn in state.enrich_metrics.get("poisoned_parts", [])
                
                if not has_override and not is_poisoned and not needs_pinout_database_enrich(cd.get("pinout_json"), catalog_row=row_d):
                    skipped += 1
                    continue
            except Exception:
                pass
            try:
                res = enrich_component_in_db(db=comp.db, generic_name=gn)  # type: ignore[attr-defined]
                if res.attempted:
                    attempted += 1
                if res.updated:
                    updated += 1
                elif res.attempted and not res.updated and (res.reason or "").startswith("lookup_failed"):
                    failed += 1
                    state.enrich_failures.append({"generic_name": gn, "reason": res.reason or "lookup_failed"})
            except Exception as e:
                failed += 1
                state.enrich_failures.append({"generic_name": gn, "reason": str(e)})
                logger.warning("Enrich failed for %s: %s", gn, e)

    state.enrich_metrics.update({
        "attempted": attempted,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "network": bool(allow_net),
    })
    
    # [Professional Grade] Sync enriched metadata back to live objects
    # This ensures that 3D model overrides and footprint fixes are visible to the layout engine
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            if hasattr(comp, "refresh_from_db"):
                comp.refresh_from_db()

    if attempted or updated or failed:
        logger.info(
            "Enrichment: attempted=%s updated=%s skipped=%s failed=%s network=%s",
            attempted,
            updated,
            skipped,
            failed,
            bool(allow_net),
        )

    if state.compile_goal == "fabrication" and state.enrich_failures:
        reasons = ", ".join(
            f"{x.get('generic_name')}:{x.get('reason')}" for x in state.enrich_failures[:12]
        )
        raise RuntimeError(
            "FAB-013: enrich lookup failed in fabrication mode "
            f"({len(state.enrich_failures)} failure(s): {reasons})"
        )

def phase_audit_database(state: CompileState) -> None:
    """Enterprise Data Integrity Phase: Audit database for poisoned or missing assets.
    
    Identifies components that need re-enrichment due to file loss or suspicious heuristics.
    """
    logger.info("Enterprise Phase 0: Auditing Database Integrity...")
    
    try:
        modules = state.board._get_all_modules()
    except Exception:
        modules = getattr(state.board, "modules", []) or []

    gns = []
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            gn = str(getattr(comp, "generic_name", "") or "").strip()
            if gn:
                gns.append(gn)
    
    if not gns:
        return

    # Check the first component's DB (all components share the same DB connection usually)
    first_comp = None
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            if hasattr(comp, "db"):
                first_comp = comp
                break
        if first_comp:
                break  # STYLE-003: expanded for readability
    
    if not first_comp:
        return

    poisoned = first_comp.db.audit_data_integrity(gns)
    if poisoned:
        logger.warning("Audit found %s poisoned or incomplete part(s) in DB: %s", len(poisoned), poisoned)
        # Store poisoned list in state for phase_enrich_parts to consume
        state.enrich_metrics["poisoned_parts"] = poisoned
    else:
        logger.info("Audit: Database integrity verified for %s components.", len(gns))


def phase_propagate_currents(state: CompileState) -> None:
    """Heuristic current propagation for physics-based trace width generation (IPC-2152).
    
    Discovers current ratings from component generic names, values, or metadata 
    and applies them to the connected nets.
    """
    import re
    try:
        modules = state.board._get_all_modules()
    except Exception:
        modules = getattr(state.board, "modules", []) or []

    net_currents: dict[str, float] = {}

    def _extract_amps(s: str | None) -> float | None:
        if not s: return None
        # Match 10A, 5.5A, 500mA with word boundaries to avoid 74AHCT -> 74A
        m = re.search(r"\b(\d+\.?\d*)\s*([mM]?[aA])\b", str(s))
        if m:
            val = float(m.group(1))
            unit = m.group(2).lower()
            if unit == "ma":
                return val / 1000.0
            return val
        return None

    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            # Check generic name and value for current hints
            rating = _extract_amps(getattr(comp, "generic_name", ""))
            if rating is None:
                rating = _extract_amps(getattr(comp, "value", ""))
            
            if rating is not None and rating > 0:
                # Apply this rating to all 'power_out', 'bidirectional', or 'passive' pins 
                # (to catch fuses/sensors) of this component if they aren't already set higher.
                for pin in comp.part.get_pins():
                    if pin.net and pin.pin_type in ("power_out", "bidirectional", "passive"):
                        curr = getattr(pin.net, "current_a", 0.0)
                        if rating > curr:
                            pin.net.set_current(rating)
                            net_currents[pin.net.name] = rating

    if net_currents:
        logger.info("Current Propagation: identified %s net(s) with physics-based current ratings.", len(net_currents))
        for name, amps in net_currents.items():
            logger.debug("  - Net %s: %.3f A", name, amps)


def phase_post_layout_checks(state: CompileState) -> None:
    """Post-layout checks gated by compile goal.

    Handoff mode: warnings are acceptable to preserve artifacts for review.
    Fabrication mode: later phases will treat violations as build-stopping errors.
    """
    if state.skip_layout:
        return
    if not Path(state.pcb_path).is_file():
        return
    from openhac.compiler.pcb_fit import pcb_fit_violations_for_pcb_path
    from openhac.compiler.rule_check import DRCViolationError

    margin_mm = float(getattr(state, "bbox_padding_mm", 0.5) or 0.0)

    env_ov = os.environ.get("OPENHAC_PCB_CHECK_FP_OVERLAP", "").strip().lower()
    if env_ov in ("0", "false", "no", "off"):
        check_fp_overlap = False
    elif env_ov in ("1", "true", "yes", "on"):
        check_fp_overlap = True
    else:
        check_fp_overlap = state.compile_goal == "fabrication"
    try:
        clr_env = os.environ.get("OPENHAC_FP_OVERLAP_CLEARANCE_MM", "").strip()
        fp_clr = float(clr_env) if clr_env else margin_mm
    except Exception:
        fp_clr = margin_mm

    viols = pcb_fit_violations_for_pcb_path(
        state.pcb_path,
        state.board,
        margin_mm=margin_mm,
        check_keepouts=True,
        check_fp_overlap=check_fp_overlap,
        fp_overlap_clearance_mm=fp_clr,
    )
    if not viols:
        return
    if state.compile_goal == "fabrication":
        raise DRCViolationError("PCB fit gate failed (fabrication mode):\n" + "\n".join(f"  • {v}" for v in viols))
    for v in viols:
        logger.warning("%s", v)
    return


def phase_groom_metadata(state: CompileState) -> None:
    """Enterprise Phase A: Deterministic RefDes Assignment and Net Categorization.
    
    Locks all component designators and identifies semantic net types before synthesis.
    """
    logger.info("Enterprise Phase A: Grooming Project Metadata (RefDes & Net Typing)...")
    
    # 1. Deterministic RefDes Assignment (Recursive Tree Order)
    seen_parts = set()
    ref_counters: dict[str, int] = {}
    
    from openhac.core.base import Component
    from openhac.core.module import Module

    def _groom_node(node, current_path=""):
        # Determine child items (Modules have 'components', Board has 'modules')
        if isinstance(node, Module):
            items = getattr(node, "components", []) or []
            mod_name = str(node.name)
            current_path = f"{current_path}.{mod_name}" if current_path else mod_name
        elif hasattr(node, "modules"): # Top-level Board
            items = getattr(node, "modules", []) or []
        else:
            items = []
        
        # 1. Process Components at this level
        # We sort by generic_name then by the stable part ID to ensure deterministic but unique order
        comps = sorted([i for i in items if isinstance(i, Component)], key=lambda x: (getattr(x, "generic_name", ""), getattr(getattr(x, "part", object()), "_part_id", id(x))))
        for c in comps:
            p = getattr(c, "part", None)
            pid = getattr(p, "_part_id", id(p)) if p else None
            if p and pid not in seen_parts:
                seen_parts.add(pid)
                # Tag the part with the module name for the schematic emitter
                p._module_name = current_path
                if hasattr(p, "fields") and isinstance(p.fields, dict):
                    p.fields["OpenHaC_Module"] = current_path
                from openhac.core.refdes import get_refdes_prefix
                cat = getattr(c, "_comp_data", {}).get("category")
                pref = get_refdes_prefix(cat, generic_name=c.generic_name, mpn=getattr(c, "generic_name", ""))
                
                count = ref_counters.get(pref, 0) + 1
                ref_counters[pref] = count
                p.refdes = f"{pref}{count}"
                if hasattr(p, "ref"): p.ref = p.refdes
                logger.info("Groomed: %s -> %s (Sheet: %s)", c.generic_name, p.refdes, current_path)  # STYLE-007
        
        # 2. Recurse into Sub-Modules
        submods = sorted([i for i in items if isinstance(i, Module)], key=lambda x: getattr(x, "name", ""))
        for sm in submods:
            _groom_node(sm, current_path=current_path)

    _groom_node(state.board)
    
    # 2. Semantic Net Categorization
    from openhac.circuit import get_default_circuit
    circuit = get_default_circuit()
    nets = getattr(circuit, "nets", [])
    for net in nets:
        n_upper = (getattr(net, "name", "") or str(net)).upper()
        
        net_type = "signal"
        if any(p in n_upper for p in ("GND", "VSS", "EARTH", "RETURN", "COMMON")):
            net_type = "gnd"
        elif any(p in n_upper for p in ("VCC", "VDD", "3V3", "5V", "12V", "VIN", "PWR", "BAT")):
            net_type = "power"
        elif "[" in n_upper and "]" in n_upper:
            net_type = "bus"
            
        if net_type == "signal":
            for p in getattr(net, "pins", []):
                pt = getattr(p, "pin_type", "").lower()
                if "ground" in pt:
                    net_type = "gnd"
                    break
                if "power" in pt:
                    net_type = "power"
                    break
        
        setattr(net, "_openhac_net_type", net_type)
        logger.debug(f"Net {n_upper} categorized as {net_type}")

    logger.info(f"Grooming complete: {len(seen_parts)} parts named, {len(nets)} nets categorized.")


def phase_fixup_power_flags(state: CompileState) -> None:
    """Automatically add PWR_FLAG components to nets categorized as 'power' or 'gnd' (SCH-004)."""
    from openhac.compiler.rule_check import ensure_power_flags

    ensure_power_flags(state.board)


def phase_warn_multilayer_stackup(state: CompileState) -> None:
    b = state.board
    if int(b.layers) > 2:
        logger.info(
            "Board.layers=%s: KiCad copper layers are enabled from this count (PCB-003). "
            "Declare inner-plane pours with declare_copper_pour_intent (In1.Cu / In2.Cu); "
            "see docs/stackup_template.yaml (SIG-001).",
            b.layers,
        )


def phase_kicad_pcb_drc(state: CompileState) -> None:
    """Fabrication-mode PCB DRC gate via `kicad-cli pcb drc`."""
    if state.compile_goal != "fabrication":
        return
    if state.skip_layout:
        return
    if not state.auto_route:
        # --no-route leaves ratsnest unconnected; KiCad DRC then fails on "unconnected items".
        # Connectivity DRC is meaningful after autoroute (FAB-021/022).
        logger.info("Skipping KiCad PCB DRC while auto_route is disabled (--no-route).")
        return
    if not Path(state.pcb_path).is_file():
        return
    from openhac.compiler.kicad_pcb_drc import run_kicad_pcb_drc

    # Write a report artifact next to other outputs for debugging.
    report = None
    try:
        report = Path(state.output_dir) / f"{state.project_name}.kicad_pcb.drc.txt" if state.output_dir else None
    except Exception:
        report = None
    run_kicad_pcb_drc(state.pcb_path, output_report=report, strict=True)
    if report is not None:
        state.kicad_pcb_drc_report = str(report)
        try:
            _stamp_board(state.board, "_last_kicad_pcb_drc_report", str(report))
        except Exception:
            pass


def phase_catalog_lock(state: CompileState) -> None:
    """LOCK-001: fail-closed when a lock is present under fabrication / --require-lock."""
    from openhac.database.catalog_lock import discover_lock_path, enforce_lock
    from openhac.core.exceptions import CatalogLockError

    require = bool(getattr(state, "require_lock", False)) or bool(
        getattr(state.board, "_require_lock", False)
    )
    fab = str(getattr(state, "compile_goal", "") or "").strip().lower() in ("fabrication", "fab")
    lock = discover_lock_path(
        script_path=state.source_script_path,
        output_dir=state.output_dir,
        project_name=state.project_name,
        explicit=getattr(state, "lock_file", None),
    )
    lock_exists = bool(lock) and Path(lock).is_file()
    if require and not lock_exists:
        raise CatalogLockError(
            "LOCK-001: --require-lock / OPENHAC_REQUIRE_LOCK set but no openhac.lock "
            f"(or {{project}}.openhac-lock.json) found for {state.project_name}"
        )
    if not lock_exists:
        profile = str(getattr(state, "compile_profile", "") or "")
        preview = profile in ("preview", "preview_pcb", "preview-pcb", "logic")
        if preview or bool(getattr(state, "lean_manifest", False)):
            return
        logger.warning(
            "LOCK-001: no catalog lockfile next to the board; handoff continues. "
            "Pass --require-lock to fail closed, or run `openhac lock`."
        )
        try:
            state.board._lock_missing_warning = True
        except Exception:
            pass
        return
    fail_closed = bool(require or fab)
    msgs = enforce_lock(state.board, lock, fail_closed=fail_closed)
    try:
        state.board._lock_mismatch = list(msgs)
        state.board._lock_path = str(lock)
    except Exception:
        pass


def phase_placement_intent(state: CompileState) -> None:
    """PLC-001: overlay pose vs outline / courtyard when freeze or --placement-intent."""
    keep = bool(getattr(state, "keep_kicad_artwork", False))
    intent = bool(getattr(state, "placement_intent", False)) or bool(
        getattr(state.board, "_placement_intent", False)
    )
    if not (keep or intent):
        return
    overlay = getattr(state, "artwork_overlay", None) or getattr(state.board, "_kicad_artwork_overlay", None)
    if overlay is None:
        return
    from openhac.compiler.placement_intent import check_overlay_placement

    check_overlay_placement(overlay, state.board, fail=True)


def phase_eco(state: CompileState) -> None:
    """ECO-001: graph diff vs previous snapshot in the output dir."""
    profile = str(getattr(state, "compile_profile", "") or "")
    overlay = getattr(state, "artwork_overlay", None) or getattr(state.board, "_kicad_artwork_overlay", None)
    preview = profile in ("preview", "preview_pcb", "preview-pcb")
    if preview and (overlay is None or not getattr(overlay, "merged", False)):
        return
    from openhac.compiler.eco import write_eco_report

    try:
        path = write_eco_report(
            state.output_dir,
            state.project_name,
            board=state.board,
            overlay=overlay,
        )
        try:
            state.board._last_eco_path = str(path)
        except Exception:
            pass
    except Exception as e:
        logger.warning("ECO-001: failed to write eco report: %s", e)


def phase_erc_drc(state: CompileState) -> None:
    logger.info("Executing Pre-Compilation Rule Verification...")
    from openhac.compiler.rule_check import run_drc, run_erc

    run_erc(state.board)
    run_drc(state.board)


def phase_pinout_coverage(state: CompileState) -> None:
    """Fail early when named-pin access will break due to missing pinout_json.

    In fabrication mode we treat missing explicit pinout as build-stopping: designs
    using named pins (e.g. `part['VIN']`) cannot be trusted when pin names are
    synthesized from footprint heuristics.
    """
    # Allow opting out explicitly.
    gate = state.quality_gates.get("require_explicit_pinout_json", None)
    if gate is False:
        return
    if state.compile_goal != "fabrication" and gate is not True:
        return

    missing: list[str] = []
    try:
        for mod in state.board._get_all_modules():
            for comp in getattr(mod, "components", []) or []:
                try:
                    cd = getattr(comp, "_comp_data", {})  # if cached
                    pinout_json = (cd or {}).get("pinout_json")
                    symbol_data = (cd or {}).get("symbol_data")
                    explicit = getattr(comp, "_explicit_pins", None)
                except Exception:
                    pinout_json = None
                    symbol_data = None
                    explicit = None
                if explicit:
                    continue
                if pinout_json:
                    continue
                if symbol_data:
                    continue
                # Component stores DB row in ctor local; fall back to DB lookup.
                try:
                    row = comp.db.get_component(getattr(comp, "generic_name", ""))  # type: ignore[attr-defined]
                except Exception:
                    row = None
                if not row or not (row.get("pinout_json") or row.get("symbol_data")):
                    gn = getattr(comp, "generic_name", "?")
                    missing.append(str(gn))
    except Exception:
        # If inspection fails, do not block by accident.
        return

    if not missing:
        return
    msg = (
        "Pinout coverage gate failed: components missing explicit pinout_json in DB:\n"
        + "\n".join(f"  - {m}" for m in sorted(set(missing)))
        + "\n\nFix: run `python3 -m openhac.database.sync_jlc --skus-file PATH.json` to enrich pinouts "
        "for these parts, or seed them via `--seed-file`."
    )
    raise RuntimeError(msg)


def phase_interface_validation(state: CompileState) -> None:
    state.board._validate_interfaces()


def phase_netlist_bom(state: CompileState) -> None:
    from openhac.compiler.netlist_gen import generate_logic_and_bom

    generate_logic_and_bom(
        state.net_path,
        bom_path=state.bom_path,
        bom_profile=getattr(state.board, "bom_profile", None),
    )


def phase_catalog_overlay_info(state: CompileState) -> None:
    """Log active JSON catalog overlay sources (bundled always; user via env / CLI / Board.compile)."""
    try:
        from openhac.database import catalog_overlay as co

        co.log_active_overlay_sources()
    except Exception:
        pass


def phase_footprint_pin_pad(state: CompileState) -> None:
    """PCB-002: optional strict pin↔footprint pad check before pcbnew (fail fast)."""
    if state.skip_layout:
        return
    from openhac.compiler.layout_gen import assert_footprint_pin_pad_or_raise

    assert_footprint_pin_pad_or_raise(state.board)


def _maybe_set_defer_copper_pours(state: CompileState) -> None:
    """ABC-002 / CODE-001: defer pours for autoroute; restore in run_compile_phases."""
    if state.skip_layout or not state.auto_route:
        return
    if (os.environ.get("OPENHAC_DEFER_COPPER_POURS") or "").strip():
        return
    if not state._owned_defer_pours:
        state._prev_defer_pours = os.environ.get("OPENHAC_DEFER_COPPER_POURS")
        os.environ["OPENHAC_DEFER_COPPER_POURS"] = "1"
        state._owned_defer_pours = True


def restore_owned_defer_pours(state: CompileState) -> None:
    """CODE-001: put OPENHAC_DEFER_COPPER_POURS back after compile."""
    if not getattr(state, "_owned_defer_pours", False):
        return
    prev = getattr(state, "_prev_defer_pours", None)
    if prev is None:
        os.environ.pop("OPENHAC_DEFER_COPPER_POURS", None)
    else:
        os.environ["OPENHAC_DEFER_COPPER_POURS"] = prev
    state._owned_defer_pours = False


def phase_layout(state: CompileState) -> None:
    if state.skip_layout:
        logger.warning(
            "OPENHAC_SKIP_LAYOUT is set: skipping PCB layout generation and autoroute "
            "(headless CI / logic-only builds; SW-006)."
        )
        return
    try:
        from openhac.compiler.placement_profile import apply_named_placement_profile

        apply_named_placement_profile()
    except Exception:
        pass
    _maybe_set_defer_copper_pours(state)
    if not bool(getattr(state.board, "_size_mm_unspecified", False)):
        logger.info(
            "Applying geometric layout constraints. Target: %sx%smm, %s layers",
            state.board.size_mm[0],
            state.board.size_mm[1],
            state.board.layers,
        )
    else:
        logger.info(
            "Applying geometric layout constraints. Target: <unspecified>, %s layers",
            state.board.layers,
        )

    # Auto-calculate module bounding boxes from component footprints
    for mod in state.board._get_all_modules():
        mod.recalculate_bbox_from_components()

    # pcbnew / SKiDL resolve ``Library:Footprint`` via fp-lib-table in the project directory.
    # Schematic phase used to write this *after* layout; without it, placement warns and pad
    # discovery can fail. Write the same table early next to the upcoming .kicad_pcb.
    try:
        from pathlib import Path

        from openhac.compiler.project_gen import footprint_library_names_from_board, write_fp_lib_table

        pcb_parent = str(Path(state.pcb_path).resolve().parent)
        fp_libs = footprint_library_names_from_board(state.board)
        if fp_libs:
            write_fp_lib_table(output_dir=pcb_parent, footprint_libs=fp_libs)
            logger.info(
                "Wrote fp-lib-table (%s footprint libraries) before PCB layout.",
                len(fp_libs),
            )
    except Exception as e:
        logger.warning("Early fp-lib-table write failed (continuing): %s", e)

    try:
        from openhac.compiler.fab_design_settings import apply_routability_env_defaults

        # Apply densify defaults *before* layout so packing/clearance affect Z3/autosize.
        apply_routability_env_defaults()
    except Exception as e:
        logger.debug("routability env defaults (pre-layout) skipped: %s", e)

    try:
        from openhac.compiler.pcb_placement import apply_pcbnew_pack_to_module_bboxes

        n_pack = apply_pcbnew_pack_to_module_bboxes(state.board)
        if n_pack:
            logger.info("Module bbox refinement (pcbnew footprint pack): %s module(s) enlarged.", n_pack)
    except Exception as e:
        logger.debug("pcbnew module bbox pack skipped: %s", e)

    # After pack sizes are known: merge IC↔LocalCaps into hierarchical Z3 rooms.
    try:
        from openhac.compiler.cluster_affinity import apply_cluster_affinity

        apply_cluster_affinity(state.board)
    except Exception as e:
        logger.warning("Cluster affinity skipped: %s", e)

    # If the user left board size unspecified, auto-size now that module bboxes are refined.
    try:
        from openhac.compiler.autosize_board import maybe_autosize_board

        maybe_autosize_board(state.board)
    except Exception as e:
        logger.debug("Auto board sizing skipped: %s", e)

    from openhac.compiler.layout_gen import generate_layout

    generate_layout_result = generate_layout(state.net_path, state.pcb_path, state.board)
    if generate_layout_result is not None:
        state.pcbnew_board = generate_layout_result

    # Persist IPC netclasses into .kicad_pro even when schematic export is skipped.
    try:
        from openhac.compiler.project_gen import (
            footprint_library_names_from_board,
            generate_project_file,
        )
        from openhac.core.board import _artifact_path

        pro_path = _artifact_path(state.project_name, ".kicad_pro", state.output_dir)
        state.pro_path = pro_path
        generate_project_file(
            pro_path,
            footprint_libs=footprint_library_names_from_board(state.board),
            board=state.board,
        )
        logger.info("Wrote .kicad_pro with IPC netclasses (layout phase): %s", pro_path)
    except Exception as e:
        logger.debug("Early .kicad_pro write skipped: %s", e)

    try:
        from openhac.compiler.pcb_placement import drain_omitted_footprint_refs

        omitted = drain_omitted_footprint_refs()
        state.omitted_footprint_refs = list(omitted)
        try:
            _stamp_board(state.board, "_last_omitted_footprint_refs", list(omitted))
        except Exception:
            pass
        pad_w = getattr(state.board, "_last_pad_pin_warnings", None)
        if isinstance(pad_w, list):
            state.pad_pin_warnings = list(pad_w)
    except Exception as e:
        logger.debug("omitted footprint drain skipped: %s", e)
    if state.compile_goal == "fabrication" and state.omitted_footprint_refs:
        from openhac.core.base import LayoutGenerationError

        raise LayoutGenerationError(
            "FAB-003: omitted footprints in fabrication mode:\n"
            + "\n".join(f"  - {r}" for r in state.omitted_footprint_refs)
        )


def _dsn_ipc_width_args(state: CompileState) -> tuple[dict | None, bool | None]:
    """IPC-2152 class/net widths to patch into Specctra DSN (autoroute or --no-route)."""
    req_w: dict = dict(getattr(state.board, "_last_ipc_netclass_widths_mm", None) or {})
    net_currents = dict(getattr(state.board, "_last_ipc_net_currents_a", None) or {})
    if net_currents:
        from openhac.compiler.pcb_physics import _ipc2152_width_mm

        req_w["__net_widths_mm__"] = {n: _ipc2152_width_mm(a) for n, a in net_currents.items()}
    gates = dict(getattr(state.board, "quality_gates", None) or {})
    require_dsn = gates.get("require_dsn_ipc_widths")
    if require_dsn is None and state.compile_goal == "fabrication" and net_currents:
        require_dsn = True
    return (req_w or None, bool(require_dsn) if require_dsn is not None else None)


def phase_autoroute(state: CompileState) -> None:
    if state.skip_layout:
        return
    if Path(state.pcb_path).is_file():
        try:
            import pcbnew
            from openhac.compiler.pcb_physics import apply_physics_net_classes
            from openhac.compiler.pcb_postprocess import apply_high_current_polygons

            board_obj = getattr(state, "pcbnew_board", None)
            if board_obj is None:
                board_obj = pcbnew.LoadBoard(str(state.pcb_path))
            if board_obj is None:
                raise RuntimeError(f"pcbnew failed to load board from {state.pcb_path}")

            try:
                apply_physics_net_classes(board_obj, state.board, pcbnew)
            except Exception as e:
                if state.compile_goal == "fabrication":
                    raise
                logger.warning("Failed to apply physics constraints: %s", e)
            # CODE-001: pcbnew.SaveBoard SIGSEGV is not catchable in-process.
            # Zone fill already runs in a child process; we reuse state.pcbnew_board
            # (PERF-008) and restore OPENHAC_DEFER_COPPER_POURS in run_compile_phases.

            from openhac.compiler.fab_design_settings import (
                apply_fab_design_settings,
                apply_routability_env_defaults,
                audit_footprint_min_drills,
                fill_copper_zones,
            )

            apply_routability_env_defaults()
            apply_fab_design_settings(board_obj, state.board, pcbnew)
            try:
                from openhac.compiler.pcb_postprocess import sync_duplicate_pad_nets

                sync_duplicate_pad_nets(board_obj, pcbnew)
            except Exception as e:
                logger.debug("ABC-005 duplicate pad sync skipped: %s", e)
            drill_viols = audit_footprint_min_drills(board_obj, state.board, pcbnew)
            if drill_viols:
                for msg in drill_viols[:12]:
                    logger.warning("%s", msg)
                if state.compile_goal == "fabrication" and os.environ.get(
                    "OPENHAC_FAB_STRICT_FP_DRILL", "1"
                ).strip().lower() not in ("0", "false", "no", "off"):
                    # Soft by default for stock RF modules; hard-fail when OPENHAC_FAB_STRICT_FP_DRILL=force
                    if os.environ.get("OPENHAC_FAB_STRICT_FP_DRILL", "").strip().lower() in (
                        "force",
                        "2",
                        "error",
                    ):
                        from openhac.compiler.rule_check import DRCViolationError

                        raise DRCViolationError(
                            "ABC-005 footprint min-drill audit failed:\n"
                            + "\n".join(f"  • {v}" for v in drill_viols[:24])
                        )

            defer_pours = (os.environ.get("OPENHAC_DEFER_COPPER_POURS") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            if defer_pours:
                # Board-wide pours before FreeRouting leave plane nets unrouted and
                # thrash (ABC-002). Inject after tracks exist.
                logger.info("ABC-002: deferring high-current copper zones until after autoroute.")
                pcbnew.SaveBoard(str(state.pcb_path), board_obj)
                logger.info(
                    "Physics-Based Layout: Persisted NetClasses to %s (zones deferred).",
                    Path(state.pcb_path).name,
                )
            else:
                n_zones = apply_high_current_polygons(board_obj, state.board, pcbnew)
                if n_zones:
                    logger.info("Physics-Based Layout: Injected %d high-current copper zone(s).", n_zones)
                fill_copper_zones(board_obj, pcbnew)
                pcbnew.SaveBoard(str(state.pcb_path), board_obj)
                from openhac.compiler.fab_design_settings import fill_copper_zones_file

                fill_copper_zones_file(str(state.pcb_path))
                logger.info(
                    "Physics-Based Layout: Persisted NetClasses and Polygons to %s.",
                    Path(state.pcb_path).name,
                )
            try:
                from openhac.compiler.project_gen import (
                    footprint_library_names_from_board,
                    generate_project_file,
                )

                generate_project_file(
                    str(Path(state.pcb_path).with_suffix(".kicad_pro")),
                    footprint_libs=footprint_library_names_from_board(state.board),
                    board=state.board,
                )
            except Exception as pro_e:
                logger.debug("KiCad 9 net_settings rewrite after physics skipped: %s", pro_e)
            state.pcbnew_board = board_obj
        except Exception as e:
            logger.warning("Failed to apply physics constraints: %s", e)

    if not Path(state.pcb_path).is_file():
        logger.warning(
            "PCB autoroute skipped: PCB file was not generated at %s (layout phase failed or was mocked).",
            state.pcb_path,
        )
        return
    from openhac.compiler.autoroute_cli import (
        export_dsn_with_ipc_widths,
        fallback_route_with_pcbnew,
        run_freerouting,
    )
    from openhac.core.base import FreeRoutingNotFoundError, AutorouterFailedError

    req_w, require_dsn = _dsn_ipc_width_args(state)

    if not state.auto_route:
        # Placement-only: still write Specctra DSN with IPC widths for KiCad / FreeRouting later.
        try:
            dsn_path = export_dsn_with_ipc_widths(
                state.pcb_path,
                required_netclass_widths_mm=req_w,
                require_dsn_widths=require_dsn,
            )
            logger.info(
                "Skipping FreeRouting (--no-route); Specctra DSN written at %s",
                dsn_path,
            )
        except AutorouterFailedError as e:
            if state.compile_goal == "fabrication":
                raise
            logger.warning("Specctra DSN export failed (--no-route): %s", e)
        return

    logger.info("Running auto-router...")
    try:
        if state.board._no_autoroute_net_names:
            # Stretch: FreeRouting cannot be told about per-net exclusions here, so we conservatively
            # skip FreeRouting but still attempt a pcbnew fallback that can avoid those nets.
            if state.compile_goal == "fabrication":
                raise AutorouterFailedError(
                    "Fabrication mode requires a production-grade routing flow; "
                    "per-net no-autoroute exclusions are not supported in this handoff. "
                    f"Blocked nets: {state.board._no_autoroute_net_names}."
                )
            raise FreeRoutingNotFoundError(
                f"PCB-007: declare_no_autoroute_net() set for {state.board._no_autoroute_net_names}."
            )
        run_freerouting(
            state.pcb_path,
            required_netclass_widths_mm=req_w,
            require_dsn_widths=require_dsn,
        )
    except FreeRoutingNotFoundError as e:
        if state.compile_goal == "fabrication":
            raise AutorouterFailedError(
                f"Fabrication mode routing gate failed: {str(e).strip()} "
                "(install/configure FreeRouting or switch compile_goal=handoff)."
            ) from e
        # CI / dev machines often have pcbnew but not FreeRouting. Provide a best-effort
        # fallback so the emitted .kicad_pcb contains tracks (useful for demos/tests),
        # while still encouraging real routing via FreeRouting or KiCad for production.
        logger.warning("%s Falling back to pcbnew minimal router.", str(e).strip())
        fallback_route_with_pcbnew(
            state.pcb_path, no_autoroute_nets=list(getattr(state.board, "_no_autoroute_net_names", None) or [])
        )

    # A* leftover is opt-in only. It is a grid maze, not a PCB router; FreeRouting
    # owns copper. Set OPENHAC_ASTAR_LEFTOVER=1 to re-enable.
    try:
        if (os.environ.get("OPENHAC_ASTAR_LEFTOVER") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ) and Path(state.pcb_path).is_file():
            from openhac.compiler.astar_router import route_leftover_nets

            n_left = route_leftover_nets(state.pcb_path)
            if n_left:
                logger.info("A* leftover router added %s copper item(s).", n_left)
    except Exception as e:
        logger.warning("A* leftover router failed: %s", e)

    # ABC-002: apply deferred copper pours after tracks exist, then safe-fill.
    if (os.environ.get("OPENHAC_DEFER_COPPER_POURS") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ) and Path(state.pcb_path).is_file():
        try:
            import pcbnew
            from openhac.compiler.pcb_postprocess import apply_copper_pour_intents
            from openhac.compiler.fab_design_settings import fill_copper_zones_file

            board_obj = pcbnew.LoadBoard(str(state.pcb_path))
            n = apply_copper_pour_intents(board_obj, state.board, pcbnew)
            from openhac.compiler.pcb_postprocess import apply_high_current_polygons

            n_hi = apply_high_current_polygons(board_obj, state.board, pcbnew)
            pcbnew.SaveBoard(str(state.pcb_path), board_obj)
            fill_copper_zones_file(str(state.pcb_path))
            logger.info(
                "ABC-002: applied %s deferred copper pour(s) and %s high-current zone(s) after autoroute.",
                n,
                n_hi,
            )
        except Exception as e:
            logger.warning("ABC-002 deferred copper pours failed: %s", e)


def phase_routing_metrics(state: CompileState) -> None:
    """Collect routing metrics and enforce minimal quality thresholds."""
    if state.skip_layout:
        return
    if not Path(state.pcb_path).is_file():
        return
    from openhac.compiler.pcb_metrics import compute_pcb_metrics
    from openhac.compiler.routing_policy import effective_routing_quality_thresholds
    from openhac.core.base import AutorouterFailedError

    metrics = compute_pcb_metrics(state.pcb_path)
    state.pcb_metrics = dict(metrics or {})
    try:
        _stamp_board(state.board, "_last_pcb_metrics", dict(state.pcb_metrics))
    except Exception:
        pass

    if not state.auto_route:
        return
    if state.compile_goal != "fabrication":
        return

    thr = effective_routing_quality_thresholds(state.board)
    tc = int(state.pcb_metrics.get("track_count", 0) or 0)
    vc = int(state.pcb_metrics.get("via_count", 0) or 0)
    if state.pcb_metrics.get("unrouted_net_count_unknown"):
        raise AutorouterFailedError(
            "ABC-006/FAB-021: unrouted_net_count unavailable "
            f"({state.pcb_metrics.get('unrouted_net_count_error')}); refusing silent pass."
        )
    if tc < int(thr["min_track_count"]):
        raise AutorouterFailedError(
            f"Fabrication mode routing gate: track_count={tc} below min_track_count={thr['min_track_count']}."
        )
    if vc > int(thr["max_via_count"]):
        raise AutorouterFailedError(
            f"Fabrication mode routing gate: via_count={vc} exceeds max_via_count={thr['max_via_count']}."
        )
    # FAB-021: unrouted connectivity fails fabrication (unless quality_gates allow).
    allow_unrouted = bool(state.quality_gates.get("allow_unrouted_nets", False))
    ur = int(state.pcb_metrics.get("unrouted_net_count", 0) or 0)
    if ur > 0 and not allow_unrouted:
        raise AutorouterFailedError(
            f"FAB-021: fabrication mode routing gate: unrouted_net_count={ur} "
            "(set Board.quality_gates['allow_unrouted_nets']=True only for intentional open nets)."
        )


def phase_schematic(state: CompileState) -> None:
    if not state.export_schematic:
        return
    from openhac.compiler.project_gen import generate_project_file
    from openhac.compiler.schematic_gen import generate_schematic, write_generated_symbol_library
    from openhac.core.board import _artifact_path

    state.sch_path = _artifact_path(state.project_name, ".kicad_sch", state.output_dir)
    state.pro_path = _artifact_path(state.project_name, ".kicad_pro", state.output_dir)
    pinpos_report = _artifact_path(state.project_name, ".openhac-sch-pinpos-report.json", state.output_dir)

    # Generate project-local symbol library for board parts so KiCad renders them.
    gen_sym_path = _artifact_path(state.project_name, ".openhac-generated.kicad_sym", state.output_dir)
    sym_path = None
    embed_syms: str | None = None
    # Use board-derived parts, not SKiDL default_circuit.
    parts: list[object] = []
    try:
        seen: set[int] = set()
        # Use recursive traversal to find ALL parts, including nested modules
        try:
            all_mods = state.board._get_all_modules()
        except Exception:
            all_mods = getattr(state.board, "modules", []) or []
            
        for mod in all_mods:
            for child in getattr(mod, "components", []) or []:
                p = getattr(child, "part", None)
                if p is None and not isinstance(child, type(None)):
                    from openhac.core.base import Component as _Comp

                    if not isinstance(child, _Comp) and hasattr(child, "pins"):
                        p = child
                if p is None:
                    continue
                pid = id(p)
                if pid in seen:
                    continue
                seen.add(pid)
                parts.append(p)
        sym_path, embed_syms = write_generated_symbol_library(
            gen_sym_path, parts, nickname="OpenHaC",
            signoff=bool(state.schematic_signoff),
        )
    except Exception:
        logger.exception("OpenHaC generated symbol library failed; schematic may show missing symbols (?)")
        sym_path, embed_syms = None, None

    if sym_path is None and parts:
        logger.warning(
            "No project-local .kicad_sym was produced; schematic symbols may show as '?' in KiCad. "
            "Check component pin data and prior errors."
        )

    sch_ir = generate_schematic(
        state.sch_path,
        state.board,
        pinpos_report_path=pinpos_report,
        generated_symbol_lib_path=sym_path,
        embedded_lib_symbols=embed_syms,
        signoff=bool(state.schematic_signoff),
        project_name=state.project_name,
    )

    if state.schematic_signoff:
        from openhac.schematic.collect import collect_parts_and_nets
        from openhac.schematic.parity import assert_graph_schematic_parity

        _parts, nets = collect_parts_and_nets(state.board)
        assert_graph_schematic_parity(nets, sch_ir, include_power=True)

    from openhac.compiler.project_gen import footprint_library_names_from_board

    generate_project_file(
        state.pro_path,
        # Only the generated OpenHaC nick — system symbols are cached in lib_symbols.
        # Listing Device/MCU/… here makes KiCad prefer the stock copy over a flattened
        # embed and yields lib_symbol_mismatch + pin/NC misses.
        sym_lib_path=sym_path or getattr(sch_ir, "generated_sym_path", None),
        sym_lib_nick="OpenHaC",
        footprint_libs=footprint_library_names_from_board(state.board),
        board=state.board,
        schematic_ir=sch_ir,
    )

    if not state.kicad_sch_erc:
        return
    from openhac.compiler.kicad_erc_report import summarize_kicad_erc_report
    from openhac.compiler.kicad_sch_erc import run_kicad_schematic_erc
    from openhac.core.exceptions import KiCadSchErcError

    fmt = (state.kicad_sch_erc_format or "report").strip().lower()
    signoff = bool(state.schematic_signoff)
    if signoff:
        fmt = "json"
    if fmt == "json":
        state.erc_report_name = f"{state.project_name}.kicad_sch.erc.json"
        erc_suffix = ".kicad_sch.erc.json"
    else:
        state.erc_report_name = f"{state.project_name}.kicad_sch.erc.txt"
        erc_suffix = ".kicad_sch.erc.txt"
    erc_report_path = _artifact_path(state.project_name, erc_suffix, state.output_dir)
    run_kicad_schematic_erc(
        state.sch_path,
        output_report=erc_report_path,
        report_format="json" if fmt == "json" else "report",
        strict=not signoff,
    )
    if signoff:
        summary = summarize_kicad_erc_report(erc_report_path)
        err_n = int(summary.get("error_count") or 0)
        if err_n:
            raise KiCadSchErcError(
                f"KiCad schematic ERC reported {err_n} error(s). See {erc_report_path}"
            )


def phase_manifest(state: CompileState) -> None:
    from openhac.compiler.compile_manifest import write_compile_manifest
    from openhac.core.board import _artifact_path
    from openhac.compiler.post_report import write_compile_post_report

    try:
        from openhac.compiler.advanced_board_policy import (
            write_fanout_constraints_json,
            write_hs_netclass_handoff,
            write_rf_emc_checklist,
        )

        out_dir = Path(state.output_dir or ".")
        write_fanout_constraints_json(state.board, out_dir, state.project_name)
        write_hs_netclass_handoff(state.board, out_dir, state.project_name)
        write_rf_emc_checklist(state.board, out_dir, state.project_name)
    except Exception as e:
        logger.debug("ABC handoff artifacts skipped: %s", e)

    sidecar = bool(getattr(state.board, "write_manifest_sha256_sidecar", False))
    if os.environ.get("OPENHAC_MANIFEST_SHA256_SIDECAR", "").lower() in ("1", "true", "yes"):
        sidecar = True

    # Compile post-report: best-effort diagnostics summary for review/follow-up.
    try:
        write_compile_post_report(state)
    except Exception as e:
        logger.debug("Post-report generation failed (continuing): %s", e)

    try:
        _stamp_board(state.board, "_last_enrich_metrics", dict(state.enrich_metrics or {}))
        _stamp_board(state.board, "_last_enrich_failures", list(state.enrich_failures or []))
        _stamp_board(state.board, "_last_omitted_footprint_refs", list(state.omitted_footprint_refs or []))
        _stamp_board(state.board, "_last_pad_pin_warnings", list(state.pad_pin_warnings or []))
        _stamp_board(state.board, "_last_network_allowed", state.network_allowed_at_compile)
        _stamp_board(state.board, "_last_kicad_pcb_drc_report", state.kicad_pcb_drc_report)
        _stamp_board(state.board, "_last_phase_ms", dict(state.phase_ms or {}))
        _stamp_board(state.board, "_lean_manifest", bool(state.lean_manifest))
        _stamp_board(state.board, "_compile_profile", str(getattr(state, "compile_profile", "") or ""))
    except Exception:
        pass

    write_compile_manifest(
        state.project_name,
        state.board,
        generate_bom=state.generate_bom,
        export_schematic=state.export_schematic,
        extra_outputs=[state.erc_report_name] if state.erc_report_name else None,
        source_script_path=state.source_script_path,
        output_dir=state.output_dir,
        write_sha256_sidecar=sidecar,
        auto_route=state.auto_route,
        skip_layout=state.skip_layout,
        release_zip_path=state.release_zip_path,
    )


def phase_release_zip(state: CompileState) -> None:
    if not state.release_zip_path:
        return
    omitted = list(state.omitted_footprint_refs or []) or list(
        getattr(state.board, "_last_omitted_footprint_refs", None) or []
    )
    if omitted and state.compile_goal == "fabrication":
        raise RuntimeError(
            "FAB-003: refusing --zip-release in fabrication mode with omitted footprints:\n"
            + "\n".join(f"  - {r}" for r in omitted)
        )
    from openhac.compiler.compile_manifest import patch_manifest_release_zip_sha256
    from openhac.compiler.release_bundle import zip_project_outputs

    base = Path(state.output_dir).resolve() if state.output_dir is not None else Path.cwd().resolve()
    out = zip_project_outputs(base, state.project_name, Path(state.release_zip_path))
    # Deterministic mode: avoid patching the manifest and rebuilding the zip.
    # The normal two-pass flow intentionally creates a self-reference mismatch (see mfg005_release_zip_sha256_note).
    if os.environ.get("OPENHAC_DETERMINISTIC", "").strip().lower() in ("1", "true", "yes", "on"):
        return
    sidecar = bool(getattr(state.board, "write_manifest_sha256_sidecar", False))
    if os.environ.get("OPENHAC_MANIFEST_SHA256_SIDECAR", "").lower() in ("1", "true", "yes"):
        sidecar = True
    patch_manifest_release_zip_sha256(
        base,
        state.project_name,
        out,
        write_sha256_sidecar=sidecar,
    )
    zip_project_outputs(base, state.project_name, Path(state.release_zip_path))


DEFAULT_COMPILE_PHASES: tuple[Callable[[CompileState], None], ...] = (
    phase_audit_database,
    phase_warn_multilayer_stackup,
    phase_enrich_parts,
    phase_catalog_lock,
    phase_propagate_currents,
    phase_groom_metadata,
    phase_fixup_power_flags,  # Must run after phase_groom_metadata so net types are set (CODE-005)
    phase_placement_intent,
    phase_erc_drc,
    phase_pinout_coverage,
    phase_interface_validation,
    phase_netlist_bom,
    phase_catalog_overlay_info,
    phase_footprint_pin_pad,
    phase_layout,
    phase_post_layout_checks,
    phase_autoroute,
    phase_routing_metrics,
    phase_kicad_pcb_drc,
    phase_schematic,
    phase_eco,
    phase_manifest,
    phase_release_zip,
)

# Stable ordered names for manifest / audit (STR-002 / SW-006).
COMPILE_PIPELINE_PHASE_NAMES: tuple[str, ...] = tuple(fn.__name__ for fn in DEFAULT_COMPILE_PHASES)


PREVIEW_COMPILE_PHASES: tuple[Callable[[CompileState], None], ...] = (
    phase_groom_metadata,
    phase_fixup_power_flags,
    phase_placement_intent,
    phase_schematic,
    phase_eco,
    phase_manifest,
)

# LIVE-007: schematic + place-only layout; no enrich, ERC, autoroute, or DRC stamp.
PREVIEW_PCB_COMPILE_PHASES: tuple[Callable[[CompileState], None], ...] = (
    phase_groom_metadata,
    phase_fixup_power_flags,
    phase_placement_intent,
    phase_netlist_bom,
    phase_layout,
    phase_schematic,
    phase_eco,
    phase_manifest,
)


def phases_for_profile(profile: str) -> tuple[Callable[[CompileState], None], ...]:
    """PERF-006: preview skips enrich/layout/route/ERC; logic uses skip-layout default phases.

    LIVE-007 ``preview_pcb``: schematic + layout, skip autoroute and ERC.
    """
    p = (profile or "").strip().lower()
    if p == "preview":
        return PREVIEW_COMPILE_PHASES
    if p in ("preview_pcb", "preview-pcb"):
        return PREVIEW_PCB_COMPILE_PHASES
    return DEFAULT_COMPILE_PHASES


def run_compile_phases(state: CompileState, phases: tuple[Callable[[CompileState], None], ...]) -> None:
    try:
        for fn in phases:
            t0 = time.perf_counter()
            try:
                fn(state)
            finally:
                state.phase_ms[fn.__name__] = int((time.perf_counter() - t0) * 1000)
    finally:
        restore_owned_defer_pours(state)


def run_compile_loop(
    state: CompileState,
    *,
    generate_phases: tuple[Callable[[CompileState], None], ...] = DEFAULT_COMPILE_PHASES,
    max_attempts: int = 1,
) -> None:
    """Explicit generate→gate→repair scaffold.

    Phase-0 behavior is intentionally conservative: run the existing phase list once.
    Later todos will split phases into generate vs gate and add repair/backtracking.
    """
    if max_attempts < 1:
        max_attempts = 1
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            run_compile_phases(state, generate_phases)
            return
        except Exception as e:
            last_err = e
            # Repair hook (Phase-0/2 foundation): apply small, safe mutations and retry.
            if attempt >= max_attempts:
                raise
            try:
                _repair_after_failure(state, e)
            except Exception as repair_e:
                logger.warning("Repair hook failed (continuing): %s", repair_e)
            try:
                _reset_layout_transients_for_retry(state)
            except Exception as reset_e:
                logger.warning("Layout-state reset before retry failed: %s", reset_e)
            logger.warning("Compile attempt %s/%s failed; retrying after repair hook: %s", attempt, max_attempts, e)
            continue
    if last_err is not None:
        raise last_err


def _reset_layout_transients_for_retry(state: CompileState) -> None:
    """Drop compiler placement so pre-layout DRC cannot see leftover coords.

    Fabrication runs ``max_attempts=2``. Attempt 1 layout (and the repair hook)
    assign ``placed_x`` / lock ``size_mm``. Attempt 2 starts at ERC/DRC, which
    then aborts on those transients before FreeRouting can export a Specctra DSN
    with IPC netclass widths.
    """
    board = state.board
    try:
        mods = board._get_all_modules() if hasattr(board, "_get_all_modules") else list(getattr(board, "modules", []) or [])
    except Exception:
        mods = list(getattr(board, "modules", []) or [])
    n = 0
    for mod in mods:
        if getattr(mod, "placed_x", None) is not None or getattr(mod, "placed_y", None) is not None:
            n += 1
        mod.placed_x = None
        mod.placed_y = None
        if hasattr(mod, "_z3_skip"):
            mod._z3_skip = False
        if hasattr(mod, "_placement_anchor"):
            mod._placement_anchor = None
    if getattr(state, "started_with_autosize", False):
        board._size_mm_unspecified = True
        board.size_mm = (1.0, 1.0)
    if n:
        logger.info("Retry: cleared placement on %s module(s); autosize=%s", n, bool(getattr(state, "started_with_autosize", False)))


def _repair_after_failure(state: CompileState, err: Exception) -> None:
    """Best-effort repair actions before retrying the compile loop."""
    # Placement heuristics are cheap and safe to (re)apply.
    try:
        from openhac.compiler.layout_heuristics import apply_layout_heuristics

        apply_layout_heuristics(state.board)
    except Exception:
        pass

    # Optional: auto-expand board outline on fit violations (useful for early iterations).
    try:
        from openhac.compiler.rule_check import DRCViolationError

        msg = str(err)
        gates = dict(getattr(state.board, "quality_gates", None) or {})
        expand = float(gates.get("auto_expand_board_mm", 0.0) or 0.0)
        if expand <= 0:
            # Leftover nets / unconnected DRC are not a too-small-outline bug.
            # Footprint legalize grows Edge.Cuts when courtyards need room.
            pass
        if isinstance(err, DRCViolationError) and "outside Edge.Cuts" in msg:
            expand = max(expand, float(gates.get("auto_expand_board_mm", 5.0) or 5.0))
        if isinstance(err, DRCViolationError) and (
            "footprint bboxes overlap" in msg or "overlaps keepout" in msg.lower()
        ):
            # ABC-007: nudge FP gap; prefer re-autosize over locking a too-small outline.
            # Keep pack inflate stable — growing it while freezing size_mm is counterproductive.
            try:
                gap = float(os.environ.get("OPENHAC_PLACEMENT_FP_GAP_MM", "4") or 4)
                os.environ["OPENHAC_PLACEMENT_FP_GAP_MM"] = str(gap + 1.0)
                clr = float(os.environ.get("OPENHAC_MODULE_CLEARANCE_MM", "5") or 5)
                os.environ["OPENHAC_MODULE_CLEARANCE_MM"] = str(clr + 1.0)
                # Keep pack inflate stable — growing it while freezing size_mm is counterproductive.
                # Do NOT setdefault PACK_INFLATE=2.2 (that permanently sparsifies subsequent boards).
            except Exception:
                pass
            try:
                # Re-enable autosize so the next attempt can grow the outline.
                _stamp_board(state.board, "_size_mm_unspecified", True)
                state.board.size_mm = (1.0, 1.0)
                expand = 0.0
            except Exception:
                expand = max(expand, float(os.environ.get("OPENHAC_REPAIR_EXPAND_BOARD_MM", "15") or 15))

        # Cap cumulative repair expansion so boards don't ratchet forever.
        try:
            max_expand_total = float(os.environ.get("OPENHAC_REPAIR_EXPAND_BOARD_MAX_MM", "40") or 40)
        except Exception:
            max_expand_total = 40.0
        already = float(getattr(state.board, "_repair_expand_mm_total", 0.0) or 0.0)
        if expand > 0 and already + expand > max_expand_total:
            expand = max(0.0, max_expand_total - already)
            if expand <= 0:
                logger.warning(
                    "ABC-007 repair: expand capped (already +%.1f mm of max %.1f); skipping further growth.",
                    already,
                    max_expand_total,
                )

        if expand > 0 and (
            "outside Edge.Cuts" in msg
            or "footprint bboxes overlap" in msg
            or "overlaps keepout" in msg.lower()
        ):
            w, h = getattr(state.board, "size_mm", (0.0, 0.0))
            state.board.size_mm = (float(w) + expand, float(h) + expand)
            try:
                _stamp_board(state.board, "_size_mm_unspecified", False)
                _stamp_board(state.board, "_repair_expand_mm_total", already + expand)
            except Exception:
                pass
            # Nudge placement gaps for retry
            import os as _os

            try:
                gap = float(_os.environ.get("OPENHAC_PLACEMENT_FP_GAP_MM", "2") or 2)
                _os.environ["OPENHAC_PLACEMENT_FP_GAP_MM"] = str(gap + 0.5)
            except Exception:
                pass
            logger.warning(
                "ABC-007 repair: expanded board size to %sx%smm (expand=%s, cumulative=%.1f).",
                *state.board.size_mm,
                expand,
                getattr(state.board, "_repair_expand_mm_total", expand),
            )
    except Exception:
        pass
