"""SW-005: single entry point for the active SKiDL circuit."""

import openhac.core  # noqa: F401
import skidl  # noqa: F401

from openhac.circuit import get_circuit, get_default_circuit


def test_get_circuit_is_alias_of_get_default_circuit():
    assert get_circuit() is get_default_circuit()
