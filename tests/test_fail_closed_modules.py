"""Unit tests for fail-closed exception handling in Module and pcb_placement (Task 1.3)."""

import pytest

from openhac.core.exceptions import ModulePropertyError, OpenHaCError
from openhac.core.module import Module, _is_production_mode


class MockBrokenPart:
    """Mock component item with broken fields attribute to trigger exceptions."""
    def __init__(self):
        self.refdes = "BROKEN1"

    @property
    def fields(self):
        raise RuntimeError("Simulated broken fields dictionary access")


def test_module_property_error_hierarchy():
    assert issubclass(ModulePropertyError, OpenHaCError)
    assert issubclass(ModulePropertyError, Exception)


def test_module_set_schematic_sheet_dev_mode_warns_and_passes(monkeypatch):
    monkeypatch.delenv("OPENHAC_COMPILE_GOAL", raising=False)
    m = Module("TestMod")
    m.components.append(MockBrokenPart())

    # In dev mode, should log warning and not raise
    m.set_schematic_sheet("SheetA")
    assert m.schematic_sheet == "SheetA"


def test_module_set_schematic_sheet_production_fails_closed(monkeypatch):
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    m = Module("TestMod")
    m.components.append(MockBrokenPart())

    # In fabrication mode, must fail-closed
    with pytest.raises(ModulePropertyError, match="Failed setting schematic sheet"):
        m.set_schematic_sheet("SheetA")


def test_module_add_production_fails_closed(monkeypatch):
    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    m = Module("TestMod")

    with pytest.raises(ModulePropertyError, match="Failed setting module fields"):
        m.add(MockBrokenPart())


def test_is_production_mode_detection(monkeypatch):
    monkeypatch.delenv("OPENHAC_COMPILE_GOAL", raising=False)
    assert not _is_production_mode()

    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fabrication")
    assert _is_production_mode()

    monkeypatch.setenv("OPENHAC_COMPILE_GOAL", "fab")
    assert _is_production_mode()

    monkeypatch.delenv("OPENHAC_COMPILE_GOAL", raising=False)
    class MockBoard:
        compile_goal = "fabrication"
        strict_mode = True

    assert _is_production_mode(MockBoard())
