"""Semantic Design Rule Check (DRC) Engine.

This module validates the electrical semantics (logic levels, voltage limits) 
of the compiled hardware graph before physical layout begins.
"""

from __future__ import annotations

import logging
from typing import Any

import openhac.core.circuit
from openhac.core.board import Board
from openhac.core.net import Net

logger = logging.getLogger("openhac.semantic_drc")


class SemanticDRCError(Exception):
    """Raised when a semantic DRC check fails."""
    pass


def check_semantic_rules(board: Board, strict: bool = False) -> list[str]:
    """Run semantic design rule checks on the compiled circuit.
    
    Args:
        board: The compiled Board object.
        strict: If True, raises SemanticDRCError on the first failure.
                If False, returns a list of error strings.
                
    Returns:
        List of error strings. Empty if all checks pass.
    """
    errors = []
    
    # We inspect the global default circuit where all nets and pins reside after compilation.
    circuit = openhac.core.circuit.default_circuit
    nets: list[Net] = getattr(circuit, "nets", [])
    
    for net in nets:
        net_name = getattr(net, "name", "Unnamed")
        pins = getattr(net, "pins", [])
        
        # Collect semantic properties across all pins on this net
        logic_levels = set()
        voltage_ratings = []
        
        for pin in pins:
            # pin.part gives us the component refdes
            refdes = getattr(pin.part, "refdes", "?") if hasattr(pin, "part") else "?"
            pin_name = getattr(pin, "name", "?")
            pin_id = f"{refdes}.{pin_name}"
            
            # Logic levels
            ll = getattr(pin, "logic_level", None)
            if ll is not None:
                logic_levels.add((ll, pin_id))
                
            # Voltage ratings
            vr = getattr(pin, "voltage_rating", None)
            if vr is not None:
                voltage_ratings.append((vr, pin_id))
                
        # --- Rule 1: Logic Level Mismatch ---
        # If multiple pins on the same net specify different logic levels, that's a collision.
        unique_levels = {ll for ll, _ in logic_levels}
        if len(unique_levels) > 1:
            details = ", ".join(f"{pid}({ll}V)" for ll, pid in logic_levels)
            err = f"Logic Level Mismatch on net '{net_name}': {details}"
            errors.append(err)
            
        # --- Rule 2: Voltage Rating Exceeded ---
        # If any pin's voltage rating is lower than the max logic level on the net, it will fry.
        if unique_levels and voltage_ratings:
            max_logic_level = max(unique_levels)
            for vr, pid in voltage_ratings:
                if max_logic_level > vr:
                    err = f"Voltage Rating Exceeded on net '{net_name}': Pin {pid} is rated for {vr}V but net logic level is {max_logic_level}V."
                    errors.append(err)

    if strict and errors:
        raise SemanticDRCError("\n".join(errors))
        
    return errors
