"""OpenHaC schematic sign-off package (SSO)."""

from openhac.schematic.emit_kicad import generate_schematic
from openhac.schematic.layout import pin_world_xy
from openhac.schematic.parity import (
    assert_graph_schematic_parity,
    net_connectivity_signatures,
    parse_kicad_sch_net_labels,
    parse_kicad_sch_wire_segments,
    schematic_wire_endpoint_pairs,
)
from openhac.schematic.synth import write_generated_symbol_library
from openhac.schematic.util import (
    kicad_sch_unescape_label,
    kicad_string_escape,
    sorted_net_pins,
    want_multi_sheet,
)

__all__ = [
    "generate_schematic",
    "write_generated_symbol_library",
    "pin_world_xy",
    "assert_graph_schematic_parity",
    "net_connectivity_signatures",
    "parse_kicad_sch_net_labels",
    "parse_kicad_sch_wire_segments",
    "schematic_wire_endpoint_pairs",
    "kicad_sch_unescape_label",
    "kicad_string_escape",
    "sorted_net_pins",
    "want_multi_sheet",
]
