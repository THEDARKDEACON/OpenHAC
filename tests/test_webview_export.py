"""Tests for the Interactive WebView exporter (Phase 5)."""

import os
import tempfile
import pytest

from openhac.core.board import Board
from openhac.core.base import Module
from openhac.core.part import Pin, Part
from openhac.core.net import Net

def test_export_webview_html():
    """Verify that WebView exporter generates a valid HTML file with Cytoscape payloads."""
    from openhac.core.compile_context import OpenHaCCompileContext, compile_context_set, compile_context_reset
    board = Board(size_mm=(100, 100))
    ctx = OpenHaCCompileContext(board)
    tok = compile_context_set(ctx)
    
    try:
        class TestSystem(Module):
            def __init__(self):
                super().__init__("TestSys")
                
                mcu = Part("U1", "Generic:MCU", {"Manufacturer": "Generic"}, [
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
            html_path = os.path.join(tmpdir, "graph_explorer.html")
            with pytest.warns(DeprecationWarning, match="FAB-041"):
                board.export_webview(html_path)
            
            assert os.path.exists(html_path)
            with open(html_path, "r") as f:
                content = f.read()
                
            assert "<!DOCTYPE html>" in content
            assert "cytoscape.min.js" in content
            
            
            # Verify the JSON payload got embedded
            assert "U1" in content
            assert "R1" in content
            assert "DATA_BUS" in content
            
    finally:
        compile_context_reset(tok)
