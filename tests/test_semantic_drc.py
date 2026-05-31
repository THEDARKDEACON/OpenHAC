"""Tests for the headless semantic DRC engine (Phase 1)."""

import pytest

from openhac.core.board import Board
from openhac.core.base import Module
from openhac.core.part import Pin, Part
from openhac.compiler.semantic_drc import SemanticDRCError

def test_semantic_logic_level_mismatch():
    """Verify that connecting a 5V pin directly to a 3.3V pin raises an error."""
    # Reset the global circuit state
    from openhac.core.compile_context import OpenHaCCompileContext, compile_context_set, compile_context_reset
    board = Board(size_mm=(50, 50))
    ctx = OpenHaCCompileContext(board)
    tok = compile_context_set(ctx)
    
    try:
        class TestModule(Module):
            def __init__(self):
                super().__init__("TestMod")
                
                s_part = Part("S1", "Generic:Sensor", {}, [
                    Pin("1", "VCC").set_semantics(logic_level=5.0),
                    Pin("2", "GND"),
                    Pin("3", "DATA").set_semantics(logic_level=5.0),
                ])
                
                u_part = Part("U1", "Generic:MCU", {}, [
                    Pin("1", "VCC").set_semantics(logic_level=3.3),
                    Pin("2", "GND"),
                    Pin("3", "GPIO1").set_semantics(logic_level=3.3),
                ])
                
                self.components.append(s_part)
                self.components.append(u_part)
                
                # Direct connection without level shifter - should fail semantic DRC!
                s_part["DATA"] += u_part["GPIO1"]

        mod = TestModule()
        board.add_module(mod)
        
        # Test strict mode
        with pytest.raises(SemanticDRCError, match="Logic Level Mismatch"):
            board.check_semantics(strict=True)
            
        # Test non-strict mode
        errors = board.check_semantics(strict=False)
        assert len(errors) == 1
        assert "Logic Level Mismatch" in errors[0]
        assert "5.0V" in errors[0]
        assert "3.3V" in errors[0]
        
    finally:
        compile_context_reset(tok)


def test_semantic_voltage_rating_exceeded():
    """Verify that exposing a 3.3V rated pin to a 5.0V net raises an error."""
    from openhac.core.compile_context import OpenHaCCompileContext, compile_context_set, compile_context_reset
    board = Board(size_mm=(50, 50))
    ctx = OpenHaCCompileContext(board)
    tok = compile_context_set(ctx)
    
    try:
        class TestModule(Module):
            def __init__(self):
                super().__init__("TestMod")
                
                c_part = Part("U1", "Generic:Chip", {}, [
                    Pin("1", "IN").set_semantics(voltage_rating=3.3),
                ])
                
                p_part = Part("PS1", "Generic:Power", {}, [
                    Pin("1", "OUT").set_semantics(logic_level=5.0),
                ])
                
                self.components.append(c_part)
                self.components.append(p_part)
                
                c_part["IN"] += p_part["OUT"]

        mod = TestModule()
        board.add_module(mod)
        
        with pytest.raises(SemanticDRCError, match="Voltage Rating Exceeded"):
            board.check_semantics(strict=True)
            
    finally:
        compile_context_reset(tok)
