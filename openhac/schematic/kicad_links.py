"""KiCad 9 project membership: schematic UUID ↔ footprint path (no GUI required).

KiCad links a project by stem plus:

- ``.kicad_pro`` ``sheets``: ``[[uuid, name], ...]`` (Root first)
- footprint ``(path "/symbol-uuid")`` or ``(path "/sheet-uuid/symbol-uuid")``

UUIDs are the same ``det_uuid`` keys ``emit_kicad`` / ``layout`` already use, so
the PCB can be stamped during placement before the ``.kicad_sch`` exists.
"""

from __future__ import annotations

from openhac.schematic.util import det_uuid, part_ref, sheet_field, want_multi_sheet

ROOT_SHEET_TITLE = "Root"


def root_schematic_uuid() -> str:
    return det_uuid("schematic:file")


def sheet_instance_uuid(sheet_name: str) -> str:
    return det_uuid(f"sheet:{sheet_name}")


def symbol_instance_uuid(part, unit: int = 1) -> str:
    ref = part_ref(part)
    try:
        u = max(1, int(unit or 1))
    except (TypeError, ValueError):
        u = 1
    return det_uuid(f"part_id:{getattr(part, '_part_id', ref)}:u{u}")


def schematic_sheet_names(parts) -> list[str]:
    return sorted({sheet_field(p) for p in (parts or []) if sheet_field(p)})


def is_hierarchical_schematic(parts) -> bool:
    names = schematic_sheet_names(parts)
    return want_multi_sheet(list(parts or []), names) and bool(names)


def footprint_schematic_path(part, *, parts=None) -> str:
    """Return the KiCad footprint ``path`` string matching ``symbol_instances``."""
    inst = symbol_instance_uuid(part, 1)
    if parts is not None and is_hierarchical_schematic(parts):
        sh = sheet_field(part)
        if sh:
            return f"/{sheet_instance_uuid(sh)}/{inst}"
    return f"/{inst}"


def project_sheet_table(*, ir=None, parts=None) -> list[list[str]]:
    """``kicad_pro`` ``sheets`` array: Root UUID plus hierarchical sheet boxes."""
    rows: list[list[str]] = [[root_schematic_uuid(), ROOT_SHEET_TITLE]]
    if ir is not None:
        for sh in getattr(ir, "sheets", None) or []:
            name = str(getattr(sh, "name", "") or "").strip()
            uid = str(getattr(sh, "uuid", "") or "").strip()
            if name and not uid:
                uid = sheet_instance_uuid(name)
            if name and uid:
                rows.append([uid, name])
        return rows
    names = schematic_sheet_names(parts)
    if want_multi_sheet(list(parts or []), names) and names:
        for name in names:
            rows.append([sheet_instance_uuid(name), name])
    return rows


def bind_footprint_schematic_path(fp, part, pcbnew_mod, *, parts=None) -> bool:
    """Set pcbnew footprint path so Update PCB from Schematic can match by UUID."""
    path = footprint_schematic_path(part, parts=parts)
    try:
        kiid_path_cls = getattr(pcbnew_mod, "KIID_PATH", None)
        if kiid_path_cls is not None:
            fp.SetPath(kiid_path_cls(path))
            return True
        fp.SetPath(path)
        return True
    except Exception:
        return False
