"""Compile orchestration phases (thin slices for testing and future plugins).

``Board.compile`` builds a :class:`CompileState` and runs ordered phase callables.
Earlier phases (ERC, netlist) are independent of later ones (zip); failures still
leave prior artifacts on disk.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from openhac.core.board import Board

logger = logging.getLogger("openhac.compile_pipeline")


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
    skip_layout: bool = field(init=False)
    net_path: str = field(init=False)
    bom_path: str | None = field(init=False)
    pcb_path: str = field(init=False)
    sch_path: str | None = field(init=False)
    pro_path: str | None = field(init=False)
    erc_report_name: str | None = field(default=None, init=False)
    pcb_metrics: dict = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.skip_layout = os.environ.get("OPENHAC_SKIP_LAYOUT", "").lower() in ("1", "true", "yes")
        from openhac.core.board import _artifact_path
        self.compile_goal = self.board.effective_compile_goal()
        self.board_class = str(getattr(self.board, "board_class", "generic") or "generic")
        self.quality_gates = dict(getattr(self.board, "quality_gates", None) or {})

        self.net_path = _artifact_path(self.project_name, ".net", self.output_dir)
        self.bom_path = (
            _artifact_path(self.project_name, ".csv", self.output_dir) if self.generate_bom else None
        )
        self.pcb_path = _artifact_path(self.project_name, ".kicad_pcb", self.output_dir)


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

    # Use the same geometry min-edge default as DRC baseline unless overridden later.
    margin_mm = 0.0
    try:
        from openhac.compiler.rule_check import _effective_drc_defaults

        margin_mm = float(_effective_drc_defaults(state.board).get("min_edge_clearance_mm", 0.0))
    except Exception:
        margin_mm = 0.0

    viols = pcb_fit_violations_for_pcb_path(
        state.pcb_path,
        state.board,
        margin_mm=margin_mm,
        check_keepouts=True,
    )
    if not viols:
        return
    if state.compile_goal == "fabrication":
        raise DRCViolationError("PCB fit gate failed (fabrication mode):\n" + "\n".join(f"  • {v}" for v in viols))
    for v in viols:
        logger.warning("%s", v)
    return


def phase_warn_multilayer_stackup(state: CompileState) -> None:
    b = state.board
    if int(b.layers) > 2:
        logger.warning(
            "Board.layers=%s: stackup and inner planes are not generated from layer count (PCB-003). "
            "Finish stackup in KiCad; see docs/stackup_template.yaml (SIG-001).",
            b.layers,
        )


def phase_kicad_pcb_drc(state: CompileState) -> None:
    """Fabrication-mode PCB DRC gate via `kicad-cli pcb drc`."""
    if state.compile_goal != "fabrication":
        return
    if state.skip_layout:
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


def phase_erc_drc(state: CompileState) -> None:
    logger.info("Executing Pre-Compilation Rule Verification...")
    from openhac.compiler.rule_check import run_drc, run_erc

    run_erc(state.board)
    run_drc(state.board)


def phase_interface_validation(state: CompileState) -> None:
    state.board._validate_interfaces()


def phase_netlist_bom(state: CompileState) -> None:
    from openhac.compiler.netlist_gen import generate_logic_and_bom

    generate_logic_and_bom(
        state.net_path,
        bom_path=state.bom_path,
        bom_profile=getattr(state.board, "bom_profile", None),
    )


def phase_layout(state: CompileState) -> None:
    if state.skip_layout:
        logger.warning(
            "OPENHAC_SKIP_LAYOUT is set: skipping PCB layout generation and autoroute "
            "(headless CI / logic-only builds; SW-006)."
        )
        return
    logger.info(
        "Applying geometric layout constraints. Target: %sx%smm, %s layers",
        state.board.size_mm[0],
        state.board.size_mm[1],
        state.board.layers,
    )
    from openhac.compiler.layout_gen import generate_layout

    generate_layout(state.net_path, state.pcb_path, state.board)


def phase_autoroute(state: CompileState) -> None:
    if state.skip_layout or not state.auto_route:
        return
    if not Path(state.pcb_path).is_file():
        logger.warning(
            "PCB autoroute skipped: PCB file was not generated at %s (layout phase failed or was mocked).",
            state.pcb_path,
        )
        return
    from openhac.compiler.autoroute_cli import run_freerouting, fallback_route_with_pcbnew
    from openhac.core.base import FreeRoutingNotFoundError, AutorouterFailedError

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
        run_freerouting(state.pcb_path)
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
        state.board._last_pcb_metrics = dict(state.pcb_metrics)
    except Exception:
        pass

    if not state.auto_route:
        return
    if state.compile_goal != "fabrication":
        return

    thr = effective_routing_quality_thresholds(state.board)
    tc = int(state.pcb_metrics.get("track_count", 0) or 0)
    vc = int(state.pcb_metrics.get("via_count", 0) or 0)
    if tc < int(thr["min_track_count"]):
        raise AutorouterFailedError(
            f"Fabrication mode routing gate: track_count={tc} below min_track_count={thr['min_track_count']}."
        )
    if vc > int(thr["max_via_count"]):
        raise AutorouterFailedError(
            f"Fabrication mode routing gate: via_count={vc} exceeds max_via_count={thr['max_via_count']}."
        )


def phase_schematic(state: CompileState) -> None:
    if not state.export_schematic:
        return
    from openhac.compiler.project_gen import generate_project_file
    from openhac.compiler.schematic_gen import generate_schematic, write_generated_symbol_library
    from openhac.core.board import _artifact_path
    from openhac.circuit import get_default_circuit

    state.sch_path = _artifact_path(state.project_name, ".kicad_sch", state.output_dir)
    state.pro_path = _artifact_path(state.project_name, ".kicad_pro", state.output_dir)
    pinpos_report = _artifact_path(state.project_name, ".openhac-sch-pinpos-report.json", state.output_dir)

    # Generate project-local symbol library for SKiDL-native parts so KiCad renders them.
    gen_sym_path = _artifact_path(state.project_name, ".openhac-generated.kicad_sym", state.output_dir)
    sym_path = None
    try:
        sym_path = write_generated_symbol_library(gen_sym_path, get_default_circuit(), nickname="OpenHaC")
    except Exception:
        sym_path = None

    generate_schematic(
        state.sch_path,
        state.board,
        pinpos_report_path=pinpos_report,
        generated_symbol_lib_path=sym_path,
    )
    generate_project_file(state.pro_path, sym_lib_path=sym_path, sym_lib_nick="OpenHaC")

    if not state.kicad_sch_erc:
        return
    from openhac.compiler.kicad_sch_erc import run_kicad_schematic_erc

    fmt = (state.kicad_sch_erc_format or "report").strip().lower()
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
    )


def phase_manifest(state: CompileState) -> None:
    from openhac.compiler.compile_manifest import write_compile_manifest
    from openhac.core.board import _artifact_path

    sidecar = bool(getattr(state.board, "write_manifest_sha256_sidecar", False))
    if os.environ.get("OPENHAC_MANIFEST_SHA256_SIDECAR", "").lower() in ("1", "true", "yes"):
        sidecar = True

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
    from openhac.compiler.compile_manifest import patch_manifest_release_zip_sha256
    from openhac.compiler.release_bundle import zip_project_outputs

    base = Path(state.output_dir).resolve() if state.output_dir is not None else Path.cwd().resolve()
    out = zip_project_outputs(base, state.project_name, state.release_zip_path)
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
    zip_project_outputs(base, state.project_name, state.release_zip_path)


DEFAULT_COMPILE_PHASES: tuple[Callable[[CompileState], None], ...] = (
    phase_warn_multilayer_stackup,
    phase_erc_drc,
    phase_interface_validation,
    phase_netlist_bom,
    phase_layout,
    phase_post_layout_checks,
    phase_autoroute,
    phase_routing_metrics,
    phase_kicad_pcb_drc,
    phase_schematic,
    phase_manifest,
    phase_release_zip,
)

# Stable ordered names for manifest / audit (STR-002 / SW-006).
COMPILE_PIPELINE_PHASE_NAMES: tuple[str, ...] = tuple(fn.__name__ for fn in DEFAULT_COMPILE_PHASES)


def run_compile_phases(state: CompileState, phases: tuple[Callable[[CompileState], None], ...]) -> None:
    for fn in phases:
        fn(state)


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
            logger.warning("Compile attempt %s/%s failed; retrying after repair hook: %s", attempt, max_attempts, e)
            continue
    if last_err is not None:
        raise last_err


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

        if isinstance(err, DRCViolationError):
            gates = dict(getattr(state.board, "quality_gates", None) or {})
            expand = float(gates.get("auto_expand_board_mm", 0.0) or 0.0)
            if expand > 0 and "outside Edge.Cuts" in str(err):
                w, h = getattr(state.board, "size_mm", (0.0, 0.0))
                state.board.size_mm = (float(w) + expand, float(h) + expand)
                logger.warning("Repair: expanded board size to %sx%smm (auto_expand_board_mm=%s).", *state.board.size_mm, expand)
    except Exception:
        pass
