"""Unit tests for Phase 3: Circuit Intermediate Representation (CIR) & Elaboration Engine."""

import json
import tempfile
from pathlib import Path
import pytest
from dataclasses import FrozenInstanceError

from openhac import (
    BusNode,
    CircuitIR,
    ComponentNode,
    ConstraintNode,
    DesignContext,
    DigitalDomain,
    ModuleNode,
    NetNode,
    PinNode,
    PowerDomain,
    SPI,
    SignalDirection,
    elaborate,
)
from openhac.core.base import Component, Module
from openhac.core.board import Board
from openhac.compiler.ir_export import export_circuit_ir
from openhac.compiler.netlist_xml import generate_netlist


def make_test_part(name: str, pin_type: str = "passive") -> Component:
    """Helper to instantiate a valid component with explicit offline data."""
    return Component(
        name,
        comp_data={
            "generic_name": name,
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0603",
            "pins": {"1": ("1", pin_type), "2": ("2", "passive")},
        },
        pins={"1": ("1", pin_type), "2": ("2", "passive")},
    )


# ---------------------------------------------------------------------------
# Task 3.1: CircuitIR Dataclass Schemas & Immutability
# ---------------------------------------------------------------------------

class TestCircuitIRSchemas:

    def test_cir_immutability(self):
        p1 = PinNode("1", "GND", direction=SignalDirection.PASSIVE)
        with pytest.raises(FrozenInstanceError):
            p1.name = "NEW_GND"  # type: ignore

        comp = ComponentNode(
            fq_path="root.u1",
            refdes="U1",
            mpn="ATMEGA328P",
            value="MCU",
            footprint="QFP-32",
            pins={"1": p1},
        )
        with pytest.raises(FrozenInstanceError):
            comp.refdes = "U2"  # type: ignore

    def test_cir_json_roundtrip(self):
        p1 = PinNode("1", "VCC", direction=SignalDirection.POWER_IN, domain=PowerDomain(3.3))
        p2 = PinNode("2", "GND", direction=SignalDirection.PASSIVE)
        comp = ComponentNode(
            fq_path="root.pwr.reg",
            refdes="U1",
            mpn="TLV70233",
            value="3.3V LDO",
            footprint="SOT-23-5",
            pins={"1": p1, "2": p2},
            attributes={"kicad_symbol": "Regulator_Linear:TLV70233"},
        )
        net = NetNode(
            net_id="VCC_3V3",
            name="VCC_3V3",
            domain=PowerDomain(3.3),
            connected_pin_paths=("U1.1",),
            is_power=True,
            voltage=3.3,
        )
        cir = CircuitIR(
            name="PowerSupply",
            components={"U1": comp},
            nets={"VCC_3V3": net},
            metadata={"author": "OpenHaC"},
        )

        json_text = cir.to_json()
        assert "TLV70233" in json_text
        assert "VCC_3V3" in json_text

        cir_loaded = CircuitIR.from_json(json_text)
        assert cir_loaded.name == "PowerSupply"
        assert "U1" in cir_loaded.components
        assert cir_loaded.components["U1"].pins["1"].direction == SignalDirection.POWER_IN
        assert cir_loaded.nets["VCC_3V3"].voltage == 3.3
        assert cir_loaded.stats()["components"] == 1
        assert cir_loaded.stats()["pins"] == 2


# ---------------------------------------------------------------------------
# Task 3.2: Elaboration Engine (elaborate)
# ---------------------------------------------------------------------------

class TestElaboratorEngine:

    def test_elaborate_flat_circuit(self):
        with DesignContext("flat_design") as ctx:
            r1 = make_test_part("R1")
            r2 = make_test_part("R2")
            r1["1"] += r2["1"]

            cir = elaborate(ctx.circuit)
            assert cir.name == "flat_design"
            assert len(cir.components) == 2
            assert cir.stats()["components"] == 2
            assert cir.stats()["pins"] == 4
            assert len(cir.nets) >= 1

    def test_elaborate_hierarchical_module_tree(self):
        board = Board(size_mm=(80, 50))
        power_mod = Module("PowerSystem")
        sensor_mod = Module("SensorArray")

        board.add_module(power_mod)
        board.add_module(sensor_mod)

        with DesignContext("hierarchical_design") as ctx:
            u_ldo = make_test_part("U_LDO", pin_type="power_out")
            u_sens = make_test_part("U_SENS", pin_type="input")
            power_mod.add(u_ldo)
            sensor_mod.add(u_sens)

            cir = elaborate(ctx.circuit, board=board)
            assert "PowerSystem" in cir.modules
            assert "SensorArray" in cir.modules
            assert cir.modules["PowerSystem"].name == "PowerSystem"
            assert cir.metadata["board_size_mm"] == (80, 50)

    def test_elaborate_protocol_signals_into_cir_nets(self):
        with DesignContext("spi_proto_design") as ctx:
            spi = SPI("SPI0")
            mcu_part = make_test_part("MCU")
            spi.sck += mcu_part["1"]

            cir = elaborate(ctx.circuit)
            assert "SPI0_SCK" in cir.nets
            net_node = cir.get_net("SPI0_SCK")
            assert net_node is not None
            assert any(p.endswith(".1") for p in net_node.connected_pin_paths)

    def test_cir_query_helpers(self):
        with DesignContext("query_ctx") as ctx:
            r1 = make_test_part("R_PULLUP")
            r2 = make_test_part("R_PULLDOWN")
            r1["1"] += r2["1"]

            cir = elaborate(ctx.circuit)
            comp1 = cir.get_component("U1")
            assert comp1 is not None

            # Find pins on net
            net_name = list(cir.nets.keys())[0]
            pins_on_net = cir.find_pins_on_net(net_name)
            assert len(pins_on_net) >= 1


# ---------------------------------------------------------------------------
# Task 3.3: Decoupled Backends Consuming CircuitIR Directly
# ---------------------------------------------------------------------------

class TestDecoupledBackends:

    def test_netlist_generator_accepts_cir_directly(self):
        with DesignContext("netlist_cir_ctx") as ctx:
            r1 = make_test_part("R_A")
            r2 = make_test_part("R_B")
            r1["1"] += r2["1"]

            # 1. Elaborate to pure CIR
            cir = elaborate(ctx.circuit)

        # 2. Generate KiCad Netlist XML directly from CIR (outside DesignContext)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "decoupled.net"
            generate_netlist(cir, out_file)

            assert out_file.exists()
            content = out_file.read_text(encoding="utf-8")
            assert "OpenHaC CircuitIR Netlist Generator" in content
            assert "export" in content

    def test_export_circuit_ir_to_file(self):
        with DesignContext("export_cir_ctx") as ctx:
            make_test_part("R_EXP1")
            make_test_part("R_EXP2")

            with tempfile.TemporaryDirectory() as tmpdir:
                json_path = Path(tmpdir) / "design_ir.json"
                cir = export_circuit_ir(circuit=ctx.circuit, output_path=json_path)

                assert json_path.exists()
                raw_json = json.loads(json_path.read_text())
                assert raw_json["schema_version"] == "2.0.0"
                assert raw_json["name"] == "export_cir_ctx"
                assert len(raw_json["components"]) == 2
