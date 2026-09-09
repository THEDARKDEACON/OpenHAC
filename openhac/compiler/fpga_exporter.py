"""
FPGA and Digital HDL Co-Design Exporter for OpenHaC v2.

Eliminates pinout mismatches between FPGA firmware (Verilog/SystemVerilog)
and PCB hardware definitions by parsing RTL ports and generating physical
constraint files for major FPGA toolchains:
- AMD / Xilinx Vivado (.xdc)
- Gowin EDA (.cst)
- Lattice Radiant / Diamond (.pdc / .lpf)
- Intel Quartus Prime (.qsf)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from openhac.core.protocol import SignalDirection
from openhac.ir.circuit_ir import CircuitIR, ComponentNode

logger = logging.getLogger("openhac.compiler.fpga_exporter")


# -------------------------------------------------------------------------
# Verilog RTL Port Parser
# -------------------------------------------------------------------------

@dataclass(frozen=True)
class VerilogPort:
    """Parsed Verilog / SystemVerilog module port."""
    name: str
    direction: SignalDirection
    width: int = 1
    msb: int = 0
    lsb: int = 0
    data_type: str = "wire"

    @property
    def is_vector(self) -> bool:
        return self.width > 1


def _strip_comments(code: str) -> str:
    """Remove line comments and block comments from Verilog source."""
    # Remove block comments /* ... */
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    # Remove single line comments // ...
    code = re.sub(r"//.*", "", code)
    return code


def parse_verilog_ports(source_code: str) -> Tuple[str, List[VerilogPort]]:
    """Parse Verilog or SystemVerilog top-level module header into structured ports.
    
    Supports both ANSI (Verilog-2001/SV) and non-ANSI (Verilog-1995) module declarations.
    
    Returns:
        (module_name, list_of_ports)
    """
    clean_code = _strip_comments(source_code)

    # Match module definition: module <name> ... ; or module <name> #(...) (...);
    mod_match = re.search(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\s*(?:#\s*\([^;]*?\)\s*)?\((.*?)\)\s*;", clean_code, re.DOTALL)
    if not mod_match:
        # Check non-ANSI style module <name> (...); ... endmodule
        mod_match_alt = re.search(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\s*\((.*?)\)\s*;", clean_code, re.DOTALL)
        if not mod_match_alt:
            raise ValueError("No valid Verilog module declaration found in source.")
        mod_match = mod_match_alt

    module_name = mod_match.group(1).strip()
    ports_block = mod_match.group(2).strip()

    ports: List[VerilogPort] = []

    # Check if ANSI-style: ports contain 'input', 'output', or 'inout' inside parentheses
    has_ansi_directions = any(w in ports_block for w in ("input", "output", "inout"))

    if has_ansi_directions:
        # Split port declarations by commas (avoiding commas inside parentheses if any)
        # Standard port items
        raw_items = [p.strip() for p in re.split(r",\s*(?![^\[]*\])", ports_block) if p.strip()]

        current_dir = SignalDirection.INPUT
        current_width = 1
        current_msb = 0
        current_lsb = 0
        current_type = "wire"

        for item in raw_items:
            # Pattern: [direction] [type] [range] name
            m = re.match(
                r"^(?:(input|output|inout)\s+)?(?:(wire|reg|logic)\s+)?(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s+)?([A-Za-z_][A-Za-z0-9_$]*)$",
                item,
            )
            if m:
                dir_str, type_str, msb_str, lsb_str, name = m.groups()

                if dir_str:
                    if dir_str == "input":
                        current_dir = SignalDirection.INPUT
                    elif dir_str == "output":
                        current_dir = SignalDirection.OUTPUT
                    elif dir_str == "inout":
                        current_dir = SignalDirection.INOUT

                if type_str:
                    current_type = type_str

                if msb_str is not None and lsb_str is not None:
                    current_msb = int(msb_str)
                    current_lsb = int(lsb_str)
                    current_width = abs(current_msb - current_lsb) + 1
                elif dir_str or type_str:
                    # Explicit new declaration without vector range defaults to scalar
                    current_msb = 0
                    current_lsb = 0
                    current_width = 1

                ports.append(
                    VerilogPort(
                        name=name,
                        direction=current_dir,
                        width=current_width,
                        msb=current_msb,
                        lsb=current_lsb,
                        data_type=current_type,
                    )
                )
    else:
        # Non-ANSI port declaration: find declarations inside module body
        body_after = clean_code[mod_match.end():]
        decl_pattern = re.compile(r"\b(input|output|inout)\s+(?:(wire|reg|logic)\s+)?(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s+)?([^;]+);")
        for m in decl_pattern.finditer(body_after):
            dir_str, type_str, msb_str, lsb_str, names_str = m.groups()
            d = (
                SignalDirection.INPUT if dir_str == "input"
                else (SignalDirection.OUTPUT if dir_str == "output" else SignalDirection.INOUT)
            )
            dt = type_str or "wire"
            if msb_str is not None and lsb_str is not None:
                msb = int(msb_str)
                lsb = int(lsb_str)
                width = abs(msb - lsb) + 1
            else:
                msb, lsb, width = 0, 0, 1

            for name in [n.strip() for n in names_str.split(",") if n.strip()]:
                ports.append(
                    VerilogPort(
                        name=name,
                        direction=d,
                        width=width,
                        msb=msb,
                        lsb=lsb,
                        data_type=dt,
                    )
                )

    return module_name, ports


def parse_verilog_file(path: Union[Path, str]) -> Tuple[str, List[VerilogPort]]:
    """Read a Verilog/SystemVerilog file and return (module_name, ports)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Verilog file not found: {p}")
    return parse_verilog_ports(p.read_text(encoding="utf-8", errors="replace"))


# -------------------------------------------------------------------------
# Pin-To-Net and Pin-To-Port Mapping Resolver
# -------------------------------------------------------------------------

@dataclass
class PinMapping:
    """Resolved physical mapping between an FPGA pin, board net, and RTL port."""
    pin_number: str
    net_name: str
    port_name: str
    direction: SignalDirection = SignalDirection.PASSIVE
    iostandard: str = "LVCMOS33"
    drive_strength: Optional[int] = None
    pull: Optional[str] = None  # "UP", "DOWN", or None


def resolve_fpga_pin_mappings(
    circuit_or_ir: Any,
    fpga_refdes: str,
    port_map: Optional[Dict[str, str]] = None,
    default_iostandard: str = "LVCMOS33",
) -> List[PinMapping]:
    """Extract physical pin-to-port mappings for a specific FPGA component.
    
    Args:
        circuit_or_ir: CircuitIR, Circuit, or Board instance.
        fpga_refdes: Reference designator of the FPGA (e.g. "U1").
        port_map: Optional explicit mapping of pin numbers or net names to RTL port names.
        default_iostandard: Default IO standard for FPGA pins (e.g. "LVCMOS33").
        
    Returns:
        List of PinMapping records.
    """
    mappings: List[PinMapping] = []
    port_map = port_map or {}

    # If it's a CircuitIR
    if isinstance(circuit_or_ir, CircuitIR):
        comp = circuit_or_ir.get_component(fpga_refdes)
        if comp is None:
            raise ValueError(f"Component '{fpga_refdes}' not found in CircuitIR")

        # Map each pin to its connected net in CircuitIR
        for pin_num, pin_node in sorted(comp.pins.items(), key=lambda x: x[0]):
            pin_path = f"{comp.refdes}.{pin_num}"
            # Find net that contains this pin
            connected_net = None
            for net in circuit_or_ir.nets.values():
                if pin_path in net.connected_pin_paths:
                    connected_net = net
                    break

            net_name = connected_net.name if connected_net else ""
            if not net_name:
                continue

            # Resolve port name: explicit pin mapping, explicit net mapping, or net name
            port_name = (
                port_map.get(pin_num)
                or port_map.get(net_name)
                or net_name
            )

            # Clean port name for RTL vector index if needed: e.g. LED_0 -> led[0]
            m_vec = re.match(r"^([A-Za-z_][A-Za-z0-9_$]*)_(\d+)$", port_name)
            if m_vec and port_name not in port_map:
                port_name = f"{m_vec.group(1)}[{m_vec.group(2)}]"

            mappings.append(
                PinMapping(
                    pin_number=pin_num,
                    net_name=net_name,
                    port_name=port_name,
                    direction=pin_node.direction,
                    iostandard=default_iostandard,
                )
            )

    else:
        # Duck-typed Circuit or Board
        from openhac.compiler.elaborator import elaborate
        cir = elaborate(circuit_or_ir if not hasattr(circuit_or_ir, "circuit") else getattr(circuit_or_ir, "circuit"), board=circuit_or_ir if hasattr(circuit_or_ir, "modules") else None)
        return resolve_fpga_pin_mappings(
            cir, fpga_refdes, port_map=port_map, default_iostandard=default_iostandard
        )

    return mappings


# -------------------------------------------------------------------------
# Toolchain Constraint File Generators
# -------------------------------------------------------------------------

def export_vivado_xdc(
    mappings: Sequence[PinMapping],
    out_path: Optional[Union[Path, str]] = None,
) -> str:
    """Generate AMD / Xilinx Vivado Physical Constraints (.xdc) format."""
    lines: List[str] = [
        "## =====================================================================",
        "## AMD / Xilinx Vivado Physical Constraints (.xdc)",
        "## Generated automatically by OpenHaC v2 FPGA Co-Design Compiler",
        "## =====================================================================",
        "",
    ]

    for m in mappings:
        lines.append(f"set_property PACKAGE_PIN {m.pin_number} [get_ports {{{m.port_name}}}]")
        lines.append(f"set_property IOSTANDARD {m.iostandard} [get_ports {{{m.port_name}}}]")
        if m.drive_strength is not None:
            lines.append(f"set_property DRIVE {m.drive_strength} [get_ports {{{m.port_name}}}]")
        if m.pull == "UP":
            lines.append(f"set_property PULLUP TRUE [get_ports {{{m.port_name}}}]")
        elif m.pull == "DOWN":
            lines.append(f"set_property PULLDOWN TRUE [get_ports {{{m.port_name}}}]")
        lines.append("")

    full_text = "\n".join(lines)
    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(full_text, encoding="utf-8")
        logger.info(f"Emitted Vivado XDC constraints to {p}")
    return full_text


def export_gowin_cst(
    mappings: Sequence[PinMapping],
    out_path: Optional[Union[Path, str]] = None,
) -> str:
    """Generate Gowin EDA Physical Constraints (.cst) format."""
    lines: List[str] = [
        "// =====================================================================",
        "// Gowin EDA Physical Constraints (.cst)",
        "// Generated automatically by OpenHaC v2 FPGA Co-Design Compiler",
        "// =====================================================================",
        "",
    ]

    for m in mappings:
        lines.append(f'IO_LOC "{m.port_name}" {m.pin_number};')
        opts = [f"IO_TYPE={m.iostandard}"]
        if m.drive_strength is not None:
            opts.append(f"DRIVE={m.drive_strength}")
        if m.pull == "UP":
            opts.append("PULL_MODE=UP")
        elif m.pull == "DOWN":
            opts.append("PULL_MODE=DOWN")
        lines.append(f'IO_PORT "{m.port_name}" {" ".join(opts)};')
        lines.append("")

    full_text = "\n".join(lines)
    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(full_text, encoding="utf-8")
        logger.info(f"Emitted Gowin CST constraints to {p}")
    return full_text


def export_lattice_pdc(
    mappings: Sequence[PinMapping],
    out_path: Optional[Union[Path, str]] = None,
) -> str:
    """Generate Lattice Radiant / Diamond Physical Design Constraints (.pdc) format."""
    lines: List[str] = [
        "## =====================================================================",
        "## Lattice Radiant Physical Design Constraints (.pdc)",
        "## Generated automatically by OpenHaC v2 FPGA Co-Design Compiler",
        "## =====================================================================",
        "",
    ]

    for m in mappings:
        lines.append(f"ldc_set_location -site {{{m.pin_number}}} [get_ports {{{m.port_name}}}]")
        lines.append(f"ldc_set_port -iobuf {{IO_TYPE={m.iostandard}}} [get_ports {{{m.port_name}}}]")
        lines.append("")

    full_text = "\n".join(lines)
    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(full_text, encoding="utf-8")
        logger.info(f"Emitted Lattice PDC constraints to {p}")
    return full_text


def export_quartus_qsf(
    mappings: Sequence[PinMapping],
    out_path: Optional[Union[Path, str]] = None,
) -> str:
    """Generate Intel Quartus Prime Settings File (.qsf) pin assignments."""
    lines: List[str] = [
        "# =====================================================================",
        "# Intel Quartus Settings File (.qsf) Pin Assignments",
        "# Generated automatically by OpenHaC v2 FPGA Co-Design Compiler",
        "# =====================================================================",
        "",
    ]

    for m in mappings:
        # Quartus PIN assignment syntax
        lines.append(f"set_location_assignment PIN_{m.pin_number} -to {m.port_name}")
        # Map LVCMOS33 to Quartus format if necessary
        io_std = "3.3-V LVTTL" if m.iostandard.upper() in ("LVCMOS33", "3V3") else m.iostandard
        lines.append(f'set_instance_assignment -name IO_STANDARD "{io_std}" -to {m.port_name}')
        lines.append("")

    full_text = "\n".join(lines)
    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(full_text, encoding="utf-8")
        logger.info(f"Emitted Quartus QSF constraints to {p}")
    return full_text


def export_fpga_bundle(
    circuit_or_ir: Any,
    fpga_refdes: str,
    out_dir: Union[Path, str],
    toolchains: Sequence[str] = ("vivado", "gowin", "lattice", "quartus"),
    port_map: Optional[Dict[str, str]] = None,
    default_iostandard: str = "LVCMOS33",
    project_name: Optional[str] = None,
) -> Dict[str, Path]:
    """Generate a full bundle of FPGA pin constraint files for all requested toolchains."""
    mappings = resolve_fpga_pin_mappings(
        circuit_or_ir,
        fpga_refdes=fpga_refdes,
        port_map=port_map,
        default_iostandard=default_iostandard,
    )

    out_base = Path(out_dir)
    out_base.mkdir(parents=True, exist_ok=True)
    pname = project_name or fpga_refdes.lower()

    emitted_files: Dict[str, Path] = {}

    for tool in toolchains:
        t = tool.lower().strip()
        if t == "vivado":
            p = out_base / f"{pname}.xdc"
            export_vivado_xdc(mappings, out_path=p)
            emitted_files["vivado"] = p
        elif t == "gowin":
            p = out_base / f"{pname}.cst"
            export_gowin_cst(mappings, out_path=p)
            emitted_files["gowin"] = p
        elif t == "lattice":
            p = out_base / f"{pname}.pdc"
            export_lattice_pdc(mappings, out_path=p)
            emitted_files["lattice"] = p
        elif t == "quartus":
            p = out_base / f"{pname}.qsf"
            export_quartus_qsf(mappings, out_path=p)
            emitted_files["quartus"] = p

    return emitted_files
