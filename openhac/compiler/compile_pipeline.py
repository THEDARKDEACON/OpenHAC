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

    def __post_init__(self) -> None:
        self.skip_layout = os.environ.get("OPENHAC_SKIP_LAYOUT", "").lower() in ("1", "true", "yes")
        from openhac.core.board import _artifact_path

        self.net_path = _artifact_path(self.project_name, ".net", self.output_dir)
        self.bom_path = (
            _artifact_path(self.project_name, ".csv", self.output_dir) if self.generate_bom else None
        )
        self.pcb_path = _artifact_path(self.project_name, ".kicad_pcb", self.output_dir)


def phase_warn_multilayer_stackup(state: CompileState) -> None:
    b = state.board
    if int(b.layers) > 2:
        logger.warning(
            "Board.layers=%s: stackup and inner planes are not generated from layer count (PCB-003). "
            "Finish stackup in KiCad; see docs/stackup_template.yaml (SIG-001).",
            b.layers,
        )


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
    if state.board._no_autoroute_net_names:
        logger.warning(
            "PCB-007: declare_no_autoroute_net() set for %s — skipping FreeRouting "
            "(route high-speed or sensitive nets manually in KiCad).",
            state.board._no_autoroute_net_names,
        )
        return
    from openhac.compiler.autoroute_cli import run_freerouting

    logger.info("Running auto-router...")
    run_freerouting(state.pcb_path)


def phase_schematic(state: CompileState) -> None:
    if not state.export_schematic:
        return
    from openhac.compiler.project_gen import generate_project_file
    from openhac.compiler.schematic_gen import generate_schematic
    from openhac.core.board import _artifact_path

    state.sch_path = _artifact_path(state.project_name, ".kicad_sch", state.output_dir)
    state.pro_path = _artifact_path(state.project_name, ".kicad_pro", state.output_dir)
    generate_schematic(state.sch_path, state.board)
    generate_project_file(state.pro_path)

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
    from openhac.compiler.release_bundle import zip_project_outputs

    base = Path(state.output_dir).resolve() if state.output_dir is not None else Path.cwd().resolve()
    zip_project_outputs(base, state.project_name, state.release_zip_path)


DEFAULT_COMPILE_PHASES: tuple[Callable[[CompileState], None], ...] = (
    phase_warn_multilayer_stackup,
    phase_erc_drc,
    phase_interface_validation,
    phase_netlist_bom,
    phase_layout,
    phase_autoroute,
    phase_schematic,
    phase_manifest,
    phase_release_zip,
)

# Stable ordered names for manifest / audit (STR-002 / SW-006).
COMPILE_PIPELINE_PHASE_NAMES: tuple[str, ...] = tuple(fn.__name__ for fn in DEFAULT_COMPILE_PHASES)


def run_compile_phases(state: CompileState, phases: tuple[Callable[[CompileState], None], ...]) -> None:
    for fn in phases:
        fn(state)
