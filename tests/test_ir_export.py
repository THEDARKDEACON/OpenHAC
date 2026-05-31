"""Tests for the Hardware Intermediate Representation (IR) exporter (Phase 4)."""

import json
import os
import tempfile
import pytest

from openhac.core.board import Board
from openhac.core.base import Module
from openhac.core.part import Pin, Part
from openhac.core.net import Net

def test_export_ir_json_schema():
    """Verify that IR exporter correctly serializes the Board state to JSON."""
    from openhac.core.compile_context import OpenHaCCompileContext, compile_context_set, compile_context_reset
    board = Board(size_mm=(100, 100))
    ctx = OpenHaCCompileContext(board)
    tok = compile_context_set(ctx)
    
    try:
        class TestSystem(Module):
            def __init__(self):
                super().__init__("TestSys")
                
                mcu = Part("U1", "Generic:MCU", {}, [
                    Pin("1", "PA4").set_semantics(logic_level=3.3),
                    Pin("2", "GND"),
                ])
                
                res = Part("R1", "Resistor_SMD:R_0603_1608Metric", {"value": "10k"}, [
                    Pin("1", "1"),
                    Pin("2", "2"),
                ])
                
                self.components.append(mcu)
                self.components.append(res)
                
                gnd_net = Net("GND")
                data_net = Net("DATA_BUS")
                
                mcu["GND"] += gnd_net
                res["2"] += gnd_net
                
                mcu["PA4"] += data_net
                res["1"] += data_net

        mod = TestSystem()
        board.add_module(mod)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "hardware_ir.json")
            board.export_ir(json_path)
            
            assert os.path.exists(json_path)
            with open(json_path, "r") as f:
                ir_data = json.load(f)
                
            assert ir_data["schema_version"] == "1.0"
            assert ir_data["project"]["constraints"]["size_mm"] == [100.0, 100.0]
            
            # Verify Components
            assert len(ir_data["components"]) == 2
            refs = [c["refdes"] for c in ir_data["components"]]
            assert "U1" in refs
            assert "R1" in refs
            
            # Verify Nets
            nets = ir_data["nets"]
            assert len(nets) == 2
            net_names = [n["name"] for n in nets]
            assert "GND" in net_names
            assert "DATA_BUS" in net_names
            
            # Check deep pin reference mapping
            data_bus = next(n for n in nets if n["name"] == "DATA_BUS")
            assert "U1.1" in data_bus["pins"]
            assert "R1.1" in data_bus["pins"]
            
    finally:
        compile_context_reset(tok)
