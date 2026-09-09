"""Unit tests for DesignContext and thread-safe scoped circuit compilation (Option A)."""

import threading
import pytest

from openhac import DesignContext, get_active_circuit, get_active_design_context
from openhac.circuit import get_default_circuit
from openhac.core.base import Component
from openhac.core.circuit import Circuit, default_circuit, reset_default_circuit
from openhac.core.net import Net


def make_test_component(name: str) -> Component:
    """Helper to instantiate a valid component with explicit offline data."""
    return Component(
        name,
        comp_data={
            "generic_name": name,
            "kicad_symbol": "Device:R",
            "kicad_footprint": "Resistor_SMD:R_0603",
            "pins": {"1": ("1", "passive"), "2": ("2", "passive")},
        },
        pins={"1": ("1", "passive"), "2": ("2", "passive")},
    )


def test_design_context_basic_isolation():
    reset_default_circuit()
    initial_parts_count = len(default_circuit.parts)

    with DesignContext("isolated_test") as ctx:
        assert get_active_design_context() is ctx
        assert get_active_circuit() is ctx.circuit
        assert get_default_circuit() is ctx.circuit
        assert ctx.circuit.name == "isolated_test"

        c1 = make_test_component("R_10k_ISO")
        n1 = Net("VCC_ISOLATED")

        assert c1.part in ctx.circuit.parts
        assert n1 in ctx.circuit.nets
        assert c1.part in default_circuit.parts
        assert len(ctx.circuit.parts) == 1

    # After exiting context, global state is not polluted
    assert get_active_design_context() is None
    assert len(default_circuit.parts) == initial_parts_count
    assert get_default_circuit() is not ctx.circuit


def test_nested_design_contexts():
    reset_default_circuit()

    with DesignContext("outer") as outer_ctx:
        c_outer = make_test_component("R_OUTER")
        assert len(outer_ctx.circuit.parts) == 1

        with DesignContext("inner") as inner_ctx:
            assert get_active_design_context() is inner_ctx
            assert get_active_circuit() is inner_ctx.circuit
            c_inner = make_test_component("R_INNER")
            assert len(inner_ctx.circuit.parts) == 1
            assert c_inner.part in inner_ctx.circuit.parts
            assert c_inner.part not in outer_ctx.circuit.parts

        # Exiting inner restores outer
        assert get_active_design_context() is outer_ctx
        assert get_active_circuit() is outer_ctx.circuit
        assert len(outer_ctx.circuit.parts) == 1
        assert c_outer.part in outer_ctx.circuit.parts


def test_design_context_reset():
    with DesignContext("reset_test") as ctx:
        make_test_component("R_RESET_1")
        assert len(ctx.circuit.parts) == 1
        reset_default_circuit()
        assert len(ctx.circuit.parts) == 0


def test_circuit_proxy_compatibility():
    assert isinstance(default_circuit, Circuit)
    with DesignContext("proxy_test") as ctx:
        c = make_test_component("R_PROXY")
        # Test iterator delegation
        parts_list = list(default_circuit)
        assert len(parts_list) == 1
        assert parts_list[0] is c.part
        assert default_circuit.name == "proxy_test"


def test_multithreaded_context_isolation():
    """Verify concurrent threads using DesignContext do not collide."""
    thread_results = {}
    errors = []

    def worker(worker_id, part_count):
        try:
            with DesignContext(f"worker_{worker_id}") as ctx:
                for i in range(part_count):
                    make_test_component(f"R_{worker_id}_{i}")
                thread_results[worker_id] = len(ctx.circuit.parts)
        except Exception as e:
            import traceback
            errors.append((worker_id, traceback.format_exc()))

    t1 = threading.Thread(target=worker, args=(1, 5))
    t2 = threading.Thread(target=worker, args=(2, 3))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Thread errors: {errors}"
    assert thread_results[1] == 5
    assert thread_results[2] == 3
