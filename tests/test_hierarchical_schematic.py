from __future__ import annotations

import re
from pathlib import Path
import pytest
from skidl import Net, Part

from openhac.compiler.elaborator import elaborate
from openhac.compiler.schematic_gen import generate_schematic
from openhac.core.base import Module
from openhac.core.board import Board
from openhac.core.circuit import Circuit
from openhac.schematic.hierarchical_layout import (
    generate_hierarchical_schematic,
    summarize_hierarchical_schematic,
)
from openhac.schematic.parity import assert_graph_schematic_parity


class PowerSubsystem(Module):
    def __init__(self, name: str, vin_net: Net, vout_net: Net, gnd_net: Net):
        super().__init__(name)
        # Power regulator parts
        self.r1 = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
        self.r2 = self.add(Part("Device", "R", value="20k", footprint="Resistor_SMD:R_0603_1608Metric"))
        # Pin 1 = input, Pin 2 = output
        self.r1[1] += vin_net
        self.r1[2] += vout_net
        self.r2[1] += vout_net
        self.r2[2] += gnd_net
        self.declare_interface("power_in", vin_net)
        self.declare_interface("power_out", vout_net)


class SensorSubsystem(Module):
    def __init__(self, name: str, vdd_net: Net, gnd_net: Net, data_net: Net):
        super().__init__(name)
        self.rs = self.add(Part("Device", "R", value="4.7k", footprint="Resistor_SMD:R_0603_1608Metric"))
        self.cs = self.add(Part("Device", "R", value="100k", footprint="Resistor_SMD:R_0603_1608Metric"))
        self.rs[1] += vdd_net
        self.rs[2] += data_net
        self.cs[1] += data_net
        self.cs[2] += gnd_net
        self.declare_interface("power", vdd_net)
        self.declare_interface("data_out", data_net)


def test_hierarchical_schematic_generation_under_25_parts(tmp_path: Path):
    """Subsystems with few components (< 25) must generate hierarchical sheets when hierarchical=True."""
    vin = Net("VIN")
    v3v3 = Net("VCC_3V3")
    gnd = Net("GND")
    data = Net("SENSOR_DATA")

    board = Board((50, 50))
    pwr = PowerSubsystem("PowerSupply", vin, v3v3, gnd)
    sns = SensorSubsystem("SensorFrontend", v3v3, gnd, data)
    board.add_module(pwr)
    board.add_module(sns)

    out_file = tmp_path / "sys_test.kicad_sch"
    ir = generate_hierarchical_schematic(str(out_file), board)

    assert out_file.is_file()
    root_sch = out_file.read_text(encoding="utf-8")

    # Verify sheet blocks on root schematic
    assert '(sheet (at ' in root_sch
    assert 'PowerSupply' in root_sch
    assert 'SensorFrontend' in root_sch

    # Verify child files exist
    pwr_sch_file = tmp_path / "sys_test.PowerSupply.kicad_sch"
    sns_sch_file = tmp_path / "sys_test.SensorFrontend.kicad_sch"
    assert pwr_sch_file.is_file()
    assert sns_sch_file.is_file()

    # Verify child IRs and sheet boxes
    assert len(ir.sheets) == 2
    assert "PowerSupply" in ir.child_sheets
    assert "SensorFrontend" in ir.child_sheets


def test_hierarchical_pin_directions_and_label_shapes(tmp_path: Path):
    """Pins placed on right edge (rot=0) must be outputs; left edge (rot=180) inputs/passives."""
    v3v3 = Net("VCC_3V3")
    gnd = Net("GND")
    sig_tx = Net("UART_TX")
    sig_rx = Net("UART_RX")

    class Controller(Module):
        def __init__(self, name: str, vcc: Net, gnd_net: Net, tx: Net, rx: Net):
            super().__init__(name)
            self.u1 = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            self.u2 = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            self.u1[1] += vcc
            self.u1[2] += tx
            self.u2[1] += rx
            self.u2[2] += gnd_net
            self.declare_interface("uart_tx", tx)
            self.declare_interface("uart_rx", rx)

    class Peripheral(Module):
        def __init__(self, name: str, vcc: Net, gnd_net: Net, rx_in: Net, tx_out: Net):
            super().__init__(name)
            self.p1 = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            self.p2 = self.add(Part("Device", "R", value="10k", footprint="Resistor_SMD:R_0603_1608Metric"))
            self.p1[1] += rx_in
            self.p1[2] += gnd_net
            self.p2[1] += vcc
            self.p2[2] += tx_out
            self.declare_interface("rx_in", rx_in)
            self.declare_interface("tx_out", tx_out)

    board = Board((50, 50))
    ctrl = Controller("Controller", v3v3, gnd, sig_tx, sig_rx)
    periph = Peripheral("Peripheral", v3v3, gnd, sig_tx, sig_rx)
    board.add_module(ctrl)
    board.add_module(periph)

    out_file = tmp_path / "pins_test.kicad_sch"
    ir = generate_hierarchical_schematic(str(out_file), board)

    # Inspect Controller sheet pins
    ctrl_sheet = next(s for s in ir.sheets if s.name == "Controller")
    assert len(ctrl_sheet.pins) >= 2

    # Check pin direction and placement
    for p in ctrl_sheet.pins:
        assert p.shape in ("input", "output", "bidirectional", "passive")
        assert p.rot in (0, 180)
        if p.rot == 0:
            # Output placed on right edge
            assert p.x == pytest.approx(ctrl_sheet.x + ctrl_sheet.w, abs=1e-2)
        elif p.rot == 180:
            # Input placed on left edge
            assert p.x == pytest.approx(ctrl_sheet.x, abs=1e-2)

    # Check child sheet hierarchical labels
    ctrl_child = ir.child_sheets["Controller"]
    ctrl_hier_labels = [lb for lb in ctrl_child.labels if lb.kind == "hierarchical"]
    assert len(ctrl_hier_labels) >= 2
    for lb in ctrl_hier_labels:
        assert lb.shape in ("input", "output", "bidirectional", "passive")

    child_txt = (tmp_path / "pins_test.Controller.kicad_sch").read_text(encoding="utf-8")
    assert "(hierarchical_label " in child_txt
    assert '(shape ' in child_txt


def test_root_components_preserved_on_parent_sheet(tmp_path: Path):
    """Top-level / board-level parts (e.g. connectors) must remain on the root schematic."""
    vin = Net("VIN")
    v3v3 = Net("VCC_3V3")
    gnd = Net("GND")

    board = Board((60, 60))
    # Top-level connector J1 not inside any subsystem module
    j1 = Part("Connector", "Conn_01x02_Pin", footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")
    # Add J1 to the default circuit / board
    vin += j1[1]
    gnd += j1[2]

    # Subsystem module
    pwr = PowerSubsystem("Regulator", vin, v3v3, gnd)
    board.add_module(pwr)

    out_file = tmp_path / "root_parts_test.kicad_sch"
    ir = generate_hierarchical_schematic(str(out_file), board)

    root_txt = out_file.read_text(encoding="utf-8")
    # Both the subsystem sheet AND the connector J1 must appear on the root sheet
    assert '(sheet (at ' in root_txt
    assert 'Regulator' in root_txt
    assert j1.ref in root_txt

    # Root IR must contain J1 in instances
    root_refs = [inst.ref for inst in ir.instances if not inst.sheet or inst.sheet == "root"]
    assert j1.ref in root_refs


def test_hierarchical_circuit_ir_and_summary(tmp_path: Path):
    """Direct CircuitIR elaboration and hierarchical schematic summarization."""
    vin = Net("VIN")
    v3v3 = Net("VCC_3V3")
    gnd = Net("GND")
    data = Net("DATA_BUS")

    board = Board((50, 50))
    pwr = PowerSubsystem("PowerMod", vin, v3v3, gnd)
    sns = SensorSubsystem("SensorMod", v3v3, gnd, data)
    board.add_module(pwr)
    board.add_module(sns)

    # Elaborate into CircuitIR
    cir = elaborate(board=board, name="TestHierarchicalDesign")
    assert cir.name == "TestHierarchicalDesign"
    assert len(cir.modules) == 2

    out_file = tmp_path / "cir_test.kicad_sch"
    ir = generate_hierarchical_schematic(str(out_file), board, circuit_ir=cir)

    summary = summarize_hierarchical_schematic(ir)
    assert summary["subsystem_sheet_count"] == 2
    assert "PowerMod" in summary["child_sheets"]
    assert "SensorMod" in summary["child_sheets"]
    assert summary["child_sheets"]["PowerMod"]["instance_count"] == 2
    assert summary["child_sheets"]["SensorMod"]["instance_count"] == 2


def test_hierarchical_parity_passes(tmp_path: Path):
    """Multi-sheet hierarchical design must pass electrical graph parity checks."""
    vin = Net("VIN")
    v3v3 = Net("VCC_3V3")
    gnd = Net("GND")
    data = Net("DATA")

    board = Board((50, 50))
    pwr = PowerSubsystem("Pwr", vin, v3v3, gnd)
    sns = SensorSubsystem("Sns", v3v3, gnd, data)
    board.add_module(pwr)
    board.add_module(sns)

    out_file = tmp_path / "parity_test.kicad_sch"
    ir = generate_hierarchical_schematic(str(out_file), board)

    # Must pass without raising ParityError
    assert_graph_schematic_parity(board, ir)
