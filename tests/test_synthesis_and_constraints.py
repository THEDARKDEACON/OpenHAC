"""
Tests for Phase 4: Generative Parametric Synthesis, First-Class Constraints,
KiCad 8/9 Custom DRC Rules, and FPGA Co-Design Exporter.
"""

from __future__ import annotations

import math
from pathlib import Path
import pytest

from openhac.compiler.elaborator import elaborate
from openhac.compiler.fpga_exporter import (
    PinMapping,
    VerilogPort,
    export_fpga_bundle,
    export_gowin_cst,
    export_lattice_pdc,
    export_quartus_qsf,
    export_vivado_xdc,
    parse_verilog_ports,
    resolve_fpga_pin_mappings,
)
from openhac.compiler.kicad_rules import (
    export_circuit_dru,
    extract_dsn_differential_pairs,
    generate_kicad_dru,
)
from openhac.compiler.parametric_solvers import (
    BuckSolution,
    DividerSolution,
    FilterSolution,
    LCSolution,
    RCLowPassFilterModule,
    VoltageDividerModule,
    find_closest_e_series,
    format_capacitance,
    format_inductance,
    format_resistance,
    get_e_series,
    solve_buck_converter,
    solve_e_series_divider,
    solve_lc_resonance,
    solve_rc_highpass,
    solve_rc_lowpass,
)
from openhac.core.board import Board
from openhac.core.circuit import Circuit, DesignContext
from openhac.core.constraints import (
    ClearanceConstraint,
    Constraint,
    DifferentialPairConstraint,
    KeepoutConstraint,
    LengthMatchConstraint,
    TraceWidthConstraint,
    constraint,
    evaluate_constraints,
)
from openhac.core.part import Part, Pin
from openhac.core.net import Net
from openhac.core.protocol import SignalDirection
from openhac.ir.circuit_ir import CircuitIR, ConstraintNode


# =========================================================================
# 1. Parametric E-Series Generation & Formatting Tests
# =========================================================================

class TestParametricESeries:
    def test_get_e_series_bounds_and_ordering(self):
        e24 = get_e_series("E24", min_val=10.0, max_val=100.0)
        assert len(e24) > 0
        assert all(10.0 <= v <= 100.0 for v in e24)
        assert e24 == sorted(e24)
        assert 10.0 in e24
        assert 47.0 in e24
        assert 100.0 in e24

    def test_get_e_series_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported E-series"):
            get_e_series("E50")

    def test_find_closest_e_series(self):
        # 4.6k should match 4.7k closely in E24
        val, err = find_closest_e_series(4600.0, series="E24", min_val=100.0, max_val=1e5)
        assert val == 4700.0
        assert pytest.approx(err, 0.01) == abs(4700 - 4600) / 4600 * 100.0

    def test_engineering_formatters(self):
        assert format_resistance(4700.0) == "4.7k"
        assert format_resistance(10000.0) == "10k"
        assert format_resistance(100.0) == "100R"
        assert format_resistance(1e6) == "1M"
        assert format_resistance(2.2e6) == "2.2M"

        assert format_capacitance(100e-9) == "100nF"
        assert format_capacitance(10e-6) == "10uF"
        assert format_capacitance(22e-12) == "22pF"
        assert format_capacitance(1e-3) == "1mF"

        assert format_inductance(10e-6) == "10uH"
        assert format_inductance(4.7e-9) == "4.7nH"
        assert format_inductance(1e-3) == "1mH"


# =========================================================================
# 2. Resistor Divider Solver & Module Tests
# =========================================================================

class TestDividerSolver:
    def test_solve_5v_to_3v3_e96(self):
        sol = solve_e_series_divider(vin=5.0, vout=3.3, series="E96", i_max=1e-3)
        assert isinstance(sol, DividerSolution)
        assert pytest.approx(sol.vout_actual, rel=1e-2) == 3.3
        assert sol.error_pct < 1.0
        assert sol.quiescent_current_a <= 1.5e-3
        assert sol.r1 > 0 and sol.r2 > 0

    def test_invalid_voltages_raise(self):
        with pytest.raises(ValueError, match="strictly between 0 and Vin"):
            solve_e_series_divider(vin=3.3, vout=5.0)

        with pytest.raises(ValueError, match="strictly between 0 and Vin"):
            solve_e_series_divider(vin=3.3, vout=-1.0)

    def test_tolerance_threshold_enforcement(self):
        # E6 series might not hit 0.001% tolerance for arbitrary ratio
        with pytest.raises(ValueError, match="exceeds tolerance threshold"):
            solve_e_series_divider(vin=12.0, vout=3.14159, series="E6", target_tolerance_pct=0.01)

    def test_voltage_divider_module(self):
        with DesignContext() as ctx:
            vdm = VoltageDividerModule(vin=5.0, vout=3.3, name="SensDiv")
            assert vdm.r1.refdes == "R1"
            assert vdm.r2.refdes == "R2"
            assert vdm.r1.value is not None
            assert len(vdm.components) == 2
            assert vdm.vin_net.name == "SensDiv_VIN"
            assert vdm.vout_net.name == "SensDiv_VOUT"
            assert vdm.gnd_net.name == "GND"


# =========================================================================
# 3. Passive RC and LC Filter Solver Tests
# =========================================================================

class TestFilterSolvers:
    def test_solve_rc_lowpass_auto(self):
        fc_target = 10_000.0  # 10 kHz
        sol = solve_rc_lowpass(fc=fc_target, series_r="E24", series_c="E12")
        assert isinstance(sol, FilterSolution)
        assert sol.filter_type == "lowpass"
        assert pytest.approx(sol.fc_actual, rel=0.1) == fc_target
        assert sol.r_val > 0
        assert sol.c_val > 0

    def test_solve_rc_highpass_with_preferred_c(self):
        fc_target = 1_000.0  # 1 kHz
        c_pref = 100e-9      # 100 nF
        sol = solve_rc_highpass(fc=fc_target, c_preferred=c_pref, series_r="E24")
        assert sol.filter_type == "highpass"
        assert sol.c_val == c_pref
        assert pytest.approx(sol.fc_actual, rel=0.1) == fc_target

    def test_rc_lowpass_module(self):
        with DesignContext() as ctx:
            rc = RCLowPassFilterModule(fc=5000.0, name="AudioLPF")
            assert rc.r.refdes == "R1"
            assert rc.c.refdes == "C1"
            assert len(rc.components) == 2
            assert rc.in_net.name == "AudioLPF_IN"
            assert rc.out_net.name == "AudioLPF_OUT"

    def test_solve_lc_resonance(self):
        f0_target = 1e6  # 1 MHz
        sol = solve_lc_resonance(f0=f0_target, series_l="E12", series_c="E12")
        assert isinstance(sol, LCSolution)
        assert pytest.approx(sol.f0_actual, rel=0.15) == f0_target
        assert sol.characteristic_impedance_z0 > 0


# =========================================================================
# 4. Buck Converter Sizing Solver Tests
# =========================================================================

class TestBuckConverterSolver:
    def test_solve_12v_to_3v3_buck(self):
        sol = solve_buck_converter(
            vin_min=10.0,
            vin_max=14.0,
            vout=3.3,
            iout_max=2.0,
            fsw_hz=500e3,
            ripple_ratio=0.3,
            vout_ripple_max_v=0.03,
        )
        assert isinstance(sol, BuckSolution)
        assert sol.l_min_henry > 0
        assert sol.l_recommended_henry >= sol.l_min_henry
        assert sol.c_out_min_farad > 0
        assert sol.c_out_recommended_farad >= sol.c_out_min_farad
        assert sol.i_peak_a > 2.0
        assert sol.i_sat_min_a >= 1.3 * sol.i_peak_a
        assert 0.2 < sol.duty_cycle_nom < 0.4

    def test_invalid_buck_specs_raise(self):
        with pytest.raises(ValueError, match="Invalid voltage specification"):
            solve_buck_converter(vin_min=3.3, vin_max=5.0, vout=12.0, iout_max=1.0, fsw_hz=100e3)


# =========================================================================
# 5. First-Class Constraints & KiCad DRC Rules Tests
# =========================================================================

class TestConstraintsAndKiCadRules:
    def test_diff_pair_constraint_rendering(self):
        dp = DifferentialPairConstraint(
            net_p="USB_DP",
            net_n="USB_DM",
            target_impedance_ohms=90.0,
            min_gap_mm=0.15,
            opt_gap_mm=0.18,
            max_gap_mm=0.22,
        )
        node = dp.to_circuit_ir_node()
        assert isinstance(node, ConstraintNode)
        assert node.kind == "differential_pair"
        assert node.target_ids == ("USB_DP", "USB_DM")
        assert node.parameters["target_impedance_ohms"] == 90.0

        rule_text = dp.to_kicad_dru_rule()
        assert '(rule "DiffPair_USB_DP_USB_DM"' in rule_text
        assert "(constraint diff_pair_gap (min 0.15mm) (opt 0.18mm) (max 0.22mm))" in rule_text
        assert "A.NetName == 'USB_DP' && B.NetName == 'USB_DM'" in rule_text

    def test_clearance_and_width_constraints(self):
        clr = ClearanceConstraint(min_clearance_mm=1.5, netclass_a="HighVoltage")
        c_rule = clr.to_kicad_dru_rule()
        assert "clearance (min 1.5mm)" in c_rule
        assert "A.hasNetclass('HighVoltage')" in c_rule

        tw = TraceWidthConstraint(min_width_mm=0.8, opt_width_mm=1.0, max_width_mm=2.5, netclass="Power")
        tw_rule = tw.to_kicad_dru_rule()
        assert "track_width (min 0.8mm opt 1.0mm max 2.5mm)" in tw_rule

        lm = LengthMatchConstraint(nets=("DDR_D0", "DDR_D1", "DDR_D2"), tolerance_mm=0.2)
        lm_rule = lm.to_kicad_dru_rule()
        assert "length (max 0.200mm)" in lm_rule

        ko = KeepoutConstraint(x_min=10.0, y_min=10.0, x_max=30.0, y_max=30.0)
        ko_rule = ko.to_kicad_dru_rule()
        assert "disallow track via copper_pour" in ko_rule

    def test_constraint_decorator_and_discovery(self):
        class MyBoard(Board):
            @constraint
            def enforce_rf_clearance(self):
                return ClearanceConstraint(min_clearance_mm=2.0, net_a="RF_FEED")

        b = MyBoard(size_mm=(100, 100))
        discovered = evaluate_constraints(b)
        assert len(discovered) == 1
        assert isinstance(discovered[0], ClearanceConstraint)
        assert discovered[0].min_clearance_mm == 2.0

    def test_elaborator_collects_typed_and_legacy_constraints(self):
        b = Board(size_mm=(100, 100))
        b.min_trace_width_mm = 0.25
        b.min_clearance_mm = 0.20
        b.add_constraint(
            DifferentialPairConstraint(net_p="ETH_TX_P", net_n="ETH_TX_N", target_impedance_ohms=100.0)
        )
        b.constrain_distance_max("U1", "C1", 5.0)

        cir = elaborate(board=b)
        assert isinstance(cir, CircuitIR)
        assert len(cir.constraints) >= 4

        kinds = [c.kind for c in cir.constraints]
        assert "min_trace_width" in kinds
        assert "min_clearance" in kinds
        assert "differential_pair" in kinds
        assert "distance_max" in kinds

        # Generate KiCad DRU from CircuitIR
        dru = generate_kicad_dru(cir.constraints)
        assert "(version 1)" in dru
        assert "DiffPair_ETH_TX_P_ETH_TX_N" in dru

    def test_export_circuit_dru_file(self, tmp_path: Path):
        dp = DifferentialPairConstraint(net_p="DP", net_n="DM")
        cir = CircuitIR(name="TestDru", constraints=(dp.to_circuit_ir_node(),))
        out_file = tmp_path / "TestDru.kicad_dru"
        res_path = export_circuit_dru(cir, out_file)
        assert res_path.is_file()
        content = res_path.read_text(encoding="utf-8")
        assert "DiffPair_DP_DM" in content

    def test_extract_dsn_differential_pairs(self):
        dp1 = DifferentialPairConstraint(net_p="P1", net_n="N1")
        dp2 = DifferentialPairConstraint(net_p="P2", net_n="N2")
        pairs = extract_dsn_differential_pairs([dp1, dp2])
        assert pairs == [("P1", "N1"), ("P2", "N2")]


# =========================================================================
# 6. Verilog RTL Parser & FPGA Co-Design Exporter Tests
# =========================================================================

class TestFPGACoDesign:
    def test_parse_ansi_verilog_ports(self):
        rtl = """
        // Top-level FPGA module for OpenHaC
        module fpga_top (
            input  wire        clk_100m,
            input  logic       rst_n,
            input  wire [7:0]  adc_data,
            output logic [3:0] user_led,
            inout  wire        i2c_sda
        );
            // internal logic
        endmodule
        """
        name, ports = parse_verilog_ports(rtl)
        assert name == "fpga_top"
        assert len(ports) == 5

        p_map = {p.name: p for p in ports}
        assert p_map["clk_100m"].direction == SignalDirection.INPUT
        assert p_map["clk_100m"].width == 1

        assert p_map["adc_data"].direction == SignalDirection.INPUT
        assert p_map["adc_data"].width == 8
        assert p_map["adc_data"].msb == 7
        assert p_map["adc_data"].lsb == 0

        assert p_map["user_led"].direction == SignalDirection.OUTPUT
        assert p_map["user_led"].width == 4

        assert p_map["i2c_sda"].direction == SignalDirection.INOUT
        assert p_map["i2c_sda"].width == 1

    def test_parse_non_ansi_verilog_ports(self):
        rtl = """
        module legacy_top (clk, data_in, led);
            input clk;
            input [15:0] data_in;
            output [7:0] led;
        endmodule
        """
        name, ports = parse_verilog_ports(rtl)
        assert name == "legacy_top"
        assert len(ports) == 3
        p_map = {p.name: p for p in ports}
        assert p_map["clk"].width == 1
        assert p_map["data_in"].width == 16
        assert p_map["led"].width == 8

    def test_vivado_xdc_export(self):
        mappings = [
            PinMapping(pin_number="E3", net_name="CLK", port_name="clk_100m", iostandard="LVCMOS33"),
            PinMapping(pin_number="H17", net_name="LED0", port_name="user_led[0]", iostandard="LVCMOS33", drive_strength=8),
        ]
        xdc = export_vivado_xdc(mappings)
        assert "set_property PACKAGE_PIN E3 [get_ports {clk_100m}]" in xdc
        assert "set_property IOSTANDARD LVCMOS33 [get_ports {clk_100m}]" in xdc
        assert "set_property PACKAGE_PIN H17 [get_ports {user_led[0]}]" in xdc
        assert "set_property DRIVE 8 [get_ports {user_led[0]}]" in xdc

    def test_gowin_cst_export(self):
        mappings = [
            PinMapping(pin_number="35", net_name="CLK", port_name="clk", iostandard="LVCMOS33"),
            PinMapping(pin_number="16", net_name="TX", port_name="uart_tx", iostandard="LVCMOS33", drive_strength=4),
        ]
        cst = export_gowin_cst(mappings)
        assert 'IO_LOC "clk" 35;' in cst
        assert 'IO_PORT "clk" IO_TYPE=LVCMOS33;' in cst
        assert 'IO_LOC "uart_tx" 16;' in cst
        assert 'IO_PORT "uart_tx" IO_TYPE=LVCMOS33 DRIVE=4;' in cst

    def test_lattice_pdc_and_quartus_qsf(self):
        mappings = [
            PinMapping(pin_number="B2", net_name="IO1", port_name="sig_a", iostandard="LVCMOS33"),
        ]
        pdc = export_lattice_pdc(mappings)
        assert "ldc_set_location -site {B2} [get_ports {sig_a}]" in pdc

        qsf = export_quartus_qsf(mappings)
        assert "set_location_assignment PIN_B2 -to sig_a" in qsf

    def test_export_fpga_bundle(self, tmp_path: Path):
        # Create a circuit with an FPGA part U1
        circuit = Circuit()
        fpga_pins = [
            Pin("A1", "CLK", "input"),
            Pin("B2", "LED_0", "output"),
            Pin("C3", "LED_1", "output"),
        ]
        fpga = Part("U1", "BGA-256", {"mpn": "XC7A35T"}, pins=fpga_pins)
        circuit.add_part(fpga)

        clk_net = Net("FPGA_CLK")
        led0_net = Net("FPGA_LED_0")
        led1_net = Net("FPGA_LED_1")

        fpga.pins["A1"] += clk_net
        fpga.pins["B2"] += led0_net
        fpga.pins["C3"] += led1_net

        cir = elaborate(circuit)
        out_dir = tmp_path / "fpga_out"
        bundle = export_fpga_bundle(
            cir,
            fpga_refdes="U1",
            out_dir=out_dir,
            toolchains=("vivado", "gowin", "lattice", "quartus"),
            port_map={"FPGA_CLK": "clk_in"},
            project_name="TopModule",
        )

        assert "vivado" in bundle
        assert "gowin" in bundle
        assert "lattice" in bundle
        assert "quartus" in bundle

        assert bundle["vivado"].is_file()
        assert bundle["gowin"].is_file()
        assert bundle["lattice"].is_file()
        assert bundle["quartus"].is_file()

        xdc_text = bundle["vivado"].read_text(encoding="utf-8")
        assert "set_property PACKAGE_PIN A1 [get_ports {clk_in}]" in xdc_text
