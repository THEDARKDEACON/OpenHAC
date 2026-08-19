"""Compatibility shim — schematic emission lives in ``openhac.schematic`` (SSO-004)."""

from __future__ import annotations

from openhac.compiler.kicad_sym_pinpos import EmptySymbolPinResolver
from openhac.schematic.collect import interface_nets_for_module as _interface_nets_for_module
from openhac.schematic.emit_kicad import generate_schematic
from openhac.schematic.layout import pin_world_xy as _layout_pin_world_xy
from openhac.schematic.layout import schematic_geometry
from openhac.schematic.parity import (
    net_connectivity_signatures,
    parse_kicad_sch_net_labels,
    parse_kicad_sch_wire_segments,
    schematic_wire_endpoint_pairs,
)
from openhac.schematic.resolve import schematic_symbol_lib_key
from openhac.schematic.synth import write_generated_symbol_library
from openhac.schematic.util import (
    kicad_sch_unescape_label,
    kicad_string_escape,
    part_rotation_deg,
    pin_sort_key as _pin_sort_key,
    sorted_net_pins,
    want_multi_sheet as _want_multi_sheet,
)

__all__ = [
    "EmptySymbolPinResolver",
    "generate_schematic",
    "write_generated_symbol_library",
    "schematic_geometry",
    "schematic_symbol_lib_key",
    "net_connectivity_signatures",
    "parse_kicad_sch_net_labels",
    "parse_kicad_sch_wire_segments",
    "schematic_wire_endpoint_pairs",
    "kicad_sch_unescape_label",
    "kicad_string_escape",
    "sorted_net_pins",
    "_pin_sort_key",
    "_want_multi_sheet",
    "_interface_nets_for_module",
    "_pin_world_xy",
]


def _pin_world_xy(pin, part, part_xy, resolver):
    rot = part_rotation_deg(part)
    return _layout_pin_world_xy(pin, part, part_xy, rot, resolver)
