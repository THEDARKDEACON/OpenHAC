"""SW-005 / FAB-004: single entry point for the active circuit (native by default)."""

import builtins

import openhac.core  # noqa: F401
import skidl  # noqa: F401

from openhac.circuit import get_circuit, get_default_circuit


def test_get_circuit_is_alias_of_get_default_circuit():
    assert get_circuit() is get_default_circuit()


def test_default_circuit_is_native_unless_legacy_opt_in(monkeypatch):
    monkeypatch.delenv("OPENHAC_LEGACY_SKIDL", raising=False)
    c = get_default_circuit()
    assert type(c).__module__.startswith("openhac.core")
    if hasattr(builtins, "default_circuit"):
        assert c is not builtins.default_circuit


def test_legacy_skidl_opt_in_uses_builtins(monkeypatch):
    monkeypatch.setenv("OPENHAC_LEGACY_SKIDL", "1")
    assert hasattr(builtins, "default_circuit")
    assert get_default_circuit() is builtins.default_circuit
    assert type(get_default_circuit()).__module__.startswith("skidl")
