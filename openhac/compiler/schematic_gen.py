import builtins
import uuid
from dataclasses import dataclass, field

from openhac.core.base import SchematicGenerationError

_COLS_PER_ROW = 10
_CELL_SPACING = 10.0


@dataclass
class PartPlacement:
    part: object
    x: float
    y: float
    uuid: str


def _assign_grid_positions(parts) -> dict:
    """Row-major grid assignment with 10-unit cell spacing, 10 columns per row."""
    positions = {}
    for idx, part in enumerate(parts):
        col = idx % _COLS_PER_ROW
        row = idx // _COLS_PER_ROW
        positions[part] = (col * _CELL_SPACING, row * _CELL_SPACING)
    return positions


def _emit_symbol_instance(f, part, x, y, uuid_str: str) -> None:
    """Write a (symbol ...) S-expression block for a single part."""
    lib = getattr(part, 'lib', None) or ''
    name = getattr(part, 'name', '') or ''
    lib_id = f"{lib}:{name}" if lib else name
    f.write(f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1)\n')
    f.write(f'    (in_bom yes) (on_board yes)\n')
    f.write(f'    (uuid "{uuid_str}")\n')
    f.write(f'  )\n')


def _emit_wire(f, x1, y1, x2, y2) -> None:
    """Write a (wire ...) S-expression block."""
    wire_uuid = str(uuid.uuid4())
    f.write(f'  (wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n')
    f.write(f'    (stroke (width 0) (type default))\n')
    f.write(f'    (uuid "{wire_uuid}")\n')
    f.write(f'  )\n')


def _emit_net_label(f, net_name: str, x, y) -> None:
    """Write a (label ...) S-expression block for nets with > 2 pins."""
    label_uuid = str(uuid.uuid4())
    f.write(f'  (label "{net_name}" (at {x} {y} 0)\n')
    f.write(f'    (effects (font (size 1.27 1.27)))\n')
    f.write(f'    (uuid "{label_uuid}")\n')
    f.write(f'  )\n')


def generate_schematic(output_path: str, board) -> None:
    """Generate a KiCad S-expression schematic file from the current default_circuit."""
    print(f"Synthesizing Logic Graph into 2D Schematic Array -> {output_path}")

    try:
        circuit = builtins.default_circuit
    except AttributeError:
        raise SchematicGenerationError(
            "default_circuit is unavailable; cannot generate schematic. "
            "Ensure SKiDL has been initialised before calling generate_schematic()."
        )

    file_uuid = str(uuid.uuid4())

    with open(output_path, 'w', encoding='utf-8') as f:
        # Header
        f.write('(kicad_sch (version 20231120) (generator openhac)\n')
        f.write(f'  (uuid "{file_uuid}")\n')
        f.write('  (paper "A4")\n')

        # Assign grid positions and emit symbol instances
        positions = _assign_grid_positions(circuit.parts)
        part_placements: dict = {}
        for part in circuit.parts:
            x, y = positions[part]
            part_uuid = str(uuid.uuid4())
            _emit_symbol_instance(f, part, x, y, part_uuid)
            part_placements[part] = (x, y)

        # Emit wires and labels for each net
        for net in circuit.nets:
            pins = list(net.pins)
            if len(pins) < 2:
                continue

            # Emit wire segments connecting consecutive pin stub endpoints.
            # Each pin stub endpoint is the owning part's grid position offset
            # vertically by pin_index * 2.54 units.
            for i in range(len(pins) - 1):
                pin_a = pins[i]
                pin_b = pins[i + 1]

                part_a = getattr(pin_a, 'part', None)
                part_b = getattr(pin_b, 'part', None)

                if part_a is None or part_b is None:
                    continue

                ax, ay = part_placements.get(part_a, (0.0, 0.0))
                bx, by = part_placements.get(part_b, (0.0, 0.0))

                # Offset vertically by pin index * 2.54
                pin_a_idx = i
                pin_b_idx = i + 1
                ay_stub = ay + pin_a_idx * 2.54
                by_stub = by + pin_b_idx * 2.54

                _emit_wire(f, ax, ay_stub, bx, by_stub)

            # Emit a net label for nets with more than 2 pins
            if len(pins) > 2:
                # Place label at the first pin's stub position
                first_pin = pins[0]
                first_part = getattr(first_pin, 'part', None)
                if first_part is not None:
                    lx, ly = part_placements.get(first_part, (0.0, 0.0))
                    _emit_net_label(f, net.name, lx, ly)

        # Close root S-expression
        f.write(')\n')

    print("Schematic S-Expression document generated successfully.")
