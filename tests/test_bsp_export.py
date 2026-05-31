"""Tests for the Firmware Board Support Package (BSP) generator (Phase 2)."""

import os
import tempfile
import pytest

from openhac.core.board import Board
from openhac.core.base import Module
from openhac.core.part import Pin, Part
from openhac.core.net import Net

def test_export_bsp_macros():
    """Verify that BSP exporter correctly maps MCU GPIOs to Sensor pins."""
    from openhac.core.compile_context import OpenHaCCompileContext, compile_context_set, compile_context_reset
    board = Board(size_mm=(50, 50))
    ctx = OpenHaCCompileContext(board)
    tok = compile_context_set(ctx)
    
    try:
        class TestSystem(Module):
            def __init__(self):
                super().__init__("TestSys")
                
                # Mock a Microcontroller
                mcu = Part("U1", "Generic:MCU", {}, [
                    Pin("1", "PA4"),   # MCU GPIO
                    Pin("2", "PB12"),  # MCU GPIO
                ])
                
                # Mock a Temperature Sensor
                temp_sensor = Part("U2", "Generic:Sensor", {}, [
                    Pin("1", "I2C_SDA"),
                    Pin("2", "I2C_SCL"),
                ])
                
                # Mock an LED
                led = Part("D1", "Generic:LED", {}, [
                    Pin("1", "ANODE"),
                ])
                
                self.components.append(mcu)
                self.components.append(temp_sensor)
                self.components.append(led)
                
                # Wire them up using native Net assignments to bypass SKiDL bugs in tests
                sda_net = Net("I2C_SDA_BUS")
                scl_net = Net("I2C_SCL_BUS")
                led_net = Net("STATUS_LED")
                
                mcu["PA4"] += sda_net
                temp_sensor["I2C_SDA"] += sda_net
                
                mcu["PB12"] += scl_net
                temp_sensor["I2C_SCL"] += scl_net
                
                # Assume another MCU pin for LED (e.g. PC13)
                mcu.add_pin(Pin("3", "PC13"))
                mcu["PC13"] += led_net
                led["ANODE"] += led_net

        mod = TestSystem()
        board.add_module(mod)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            header_path = os.path.join(tmpdir, "board_config.h")
            board.export_bsp(header_path)
            
            assert os.path.exists(header_path)
            with open(header_path, "r") as f:
                content = f.read()
                
            # Verify the generated macros exist
            assert "#define U2_I2C_SDA_PIN       PA4" in content
            assert "#define U2_I2C_SCL_PIN       PB12" in content
            assert "#define D1_ANODE_PIN         PC13" in content
            
    finally:
        compile_context_reset(tok)
