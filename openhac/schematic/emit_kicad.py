"""Single KiCad schematic emitter (SSO-004, SSO-031)."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from openhac.schematic.collect import collect_parts_and_nets
from openhac.schematic.ir import SchematicIR
from openhac.schematic.layout import build_ir
from openhac.schematic.resolve import make_pin_resolver, resolve_part_symbol
from openhac.schematic.synth import (
    embed_used_lib_symbols,
    shared_bus_pin_type_overrides,
    synthesize_power_symbol,
    write_generated_symbol_library,
)
from openhac.schematic.kicad_links import root_schematic_uuid, sheet_instance_uuid
from openhac.schematic.util import (
    det_uuid,
    fmt_mm,
    kicad_string_escape,
    truthy_env,
)

logger = logging.getLogger("openhac.schematic")

_PWR_FLAG_EMBED = """    (symbol "power:PWR_FLAG" (power) (pin_names (offset 0)) (in_bom no) (on_board yes)
      (property "Reference" "#FLG" (at 0 1.27 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Value" "PWR_FLAG" (at 0 3.556 0) (effects (font (size 1.27 1.27))))
      (symbol "PWR_FLAG_0_1"
        (polyline (pts (xy 0 0) (xy 0 1.27)) (stroke (width 0)))
        (polyline (pts (xy -1.27 1.27) (xy 0 2.54) (xy 1.27 1.27) (xy -1.27 1.27)) (stroke (width 0)) (fill (type none)))
      )
      (symbol "PWR_FLAG_1_1"
        (pin power_out line (at 0 0 90) (length 0)
          (name "pwr" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
      )
    )
"""


def _power_symbol_pin_offset(lib_id: str) -> tuple[float, float]:
    """Library-local pin 1 offset so the power pin lands on the net (SSO-021)."""
    from openhac.compiler.kicad_sym_pinpos import (
        find_symbol_library_file,
        load_symbol_pin_positions,
        parse_kicad_symbol_id,
    )

    parsed = parse_kicad_symbol_id(lib_id)
    if not parsed:
        return 0.0, 0.0
    lib, name = parsed
    path = find_symbol_library_file(lib)
    if path is None:
        return 0.0, 0.0
    pmap = load_symbol_pin_positions(path, name) or {}
    if not pmap:
        return 0.0, 0.0
    rec = pmap.get("1") or next(iter(pmap.values()), None)
    if rec is None:
        return 0.0, 0.0
    return float(rec[0]), float(rec[1])


def _title_block(f, title: str, rev: str, company: str = "") -> None:
    if truthy_env("OPENHAC_DETERMINISTIC") or truthy_env("OPENHAC_DETERMINISTIC_SCHEMATIC"):
        date_str = "1970-01-01"
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
    f.write("  (title_block\n")
    f.write(f'    (title "{kicad_string_escape(title)}")\n')
    f.write(f'    (date "{date_str}")\n')
    f.write(f'    (rev "{kicad_string_escape(rev)}")\n')
    f.write(f'    (company "{kicad_string_escape(company)}")\n')
    f.write("  )\n")


def _header(f, file_uuid: str, ir: SchematicIR, extra_power_syms: str) -> None:
    f.write("(kicad_sch (version 20231120) (generator openhac)\n")
    f.write(f'  (uuid "{file_uuid}")\n')
    paper = str(getattr(ir, "paper", None) or "A4")
    f.write(f'  (paper "{kicad_string_escape(paper)}")\n')
    f.write("  (lib_symbols\n")
    from openhac.compiler.kicad_sym_pinpos import find_symbol_library_file

    if find_symbol_library_file("power") is None:
        f.write(_PWR_FLAG_EMBED)
    if extra_power_syms:
        f.write(extra_power_syms)
    if ir.embedded_lib_symbols:
        f.write(ir.embedded_lib_symbols)
        if not str(ir.embedded_lib_symbols).endswith("\n"):
            f.write("\n")
    f.write("  )\n")


def _emit_instance(f, inst) -> None:
    unit = int(getattr(inst, "unit", 1) or 1)
    f.write(
        f'  (symbol (lib_id "{kicad_string_escape(inst.lib_id)}") '
        f'(at {fmt_mm(inst.x)} {fmt_mm(inst.y)} {fmt_mm(inst.rot)}) (unit {unit})\n'
    )
    f.write("    (in_bom yes) (on_board yes) (fields_autoplaced yes)\n")
    f.write(f'    (uuid "{inst.uuid}")\n')
    f.write(
        f'    (property "Reference" "{kicad_string_escape(inst.ref)}" '
        f'(at {fmt_mm(inst.x)} {fmt_mm(inst.y - 5.08)} 0)\n'
    )
    f.write("      (effects (font (size 1.27 1.27) (thickness 0.15)))\n    )\n")
    f.write(
        f'    (property "Value" "{kicad_string_escape(inst.value)}" '
        f'(at {fmt_mm(inst.x)} {fmt_mm(inst.y + 5.08)} 0)\n'
    )
    f.write("      (effects (font (size 1.27 1.27) (thickness 0.15)))\n    )\n")
    f.write(
        f'    (property "Footprint" "{kicad_string_escape(inst.footprint)}" '
        f'(at {fmt_mm(inst.x)} {fmt_mm(inst.y + 7.62)} 0) '
        f'(effects (font (size 1.27 1.27)) (hide yes)))\n'
    )
    ds = str(getattr(inst, "datasheet", "") or "")
    f.write(
        f'    (property "Datasheet" "{kicad_string_escape(ds)}" '
        f'(at {fmt_mm(inst.x)} {fmt_mm(inst.y)} 0) '
        f'(effects (font (size 1.27 1.27)) (hide yes)))\n'
    )
    mpn = str(getattr(inst, "mpn", "") or "")
    if mpn:
        f.write(
            f'    (property "MPN" "{kicad_string_escape(mpn)}" '
            f'(at {fmt_mm(inst.x)} {fmt_mm(inst.y)} 0) '
            f'(effects (font (size 1.27 1.27)) (hide yes)))\n'
        )
    mfr = str(getattr(inst, "manufacturer", "") or "")
    if mfr:
        f.write(
            f'    (property "Manufacturer" "{kicad_string_escape(mfr)}" '
            f'(at {fmt_mm(inst.x)} {fmt_mm(inst.y)} 0) '
            f'(effects (font (size 1.27 1.27)) (hide yes)))\n'
        )
    for num in getattr(inst, "pin_nums", None) or []:
        if not str(num).strip():
            continue
        uid = det_uuid(f"pin:{inst.uuid}:{num}")
        f.write(f'    (pin "{kicad_string_escape(str(num))}"\n')
        f.write(f'      (uuid "{uid}")\n    )\n')
    f.write("  )\n")


def _emit_wire(f, x1, y1, x2, y2) -> None:
    if ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 < 0.5:
        return
    uid = det_uuid(f"wire:{x1:.4f},{y1:.4f}:{x2:.4f},{y2:.4f}")
    f.write(f'  (wire (pts (xy {fmt_mm(x1)} {fmt_mm(y1)}) (xy {fmt_mm(x2)} {fmt_mm(y2)}))\n')
    f.write('    (stroke (width 0) (type default))\n')
    f.write(f'    (uuid "{uid}")\n  )\n')


def _emit_bus(f, x1, y1, x2, y2) -> None:
    if abs(x1 - x2) < 0.001 and abs(y1 - y2) < 0.001:
        return
    uid = det_uuid(f"bus:{x1:.4f},{y1:.4f}:{x2:.4f},{y2:.4f}")
    f.write(f'  (bus (pts (xy {fmt_mm(x1)} {fmt_mm(y1)}) (xy {fmt_mm(x2)} {fmt_mm(y2)}))\n')
    f.write('    (stroke (width 0) (type default))\n')
    f.write(f'    (uuid "{uid}")\n  )\n')


def _emit_bus_entry(f, x, y, dx=2.54, dy=2.54) -> None:
    uid = det_uuid(f"bentry:{x:.4f},{y:.4f}:{dx:.3f}:{dy:.3f}")
    f.write(
        f'  (bus_entry (at {fmt_mm(x)} {fmt_mm(y)}) (size {fmt_mm(dx)} {fmt_mm(dy)})\n'
    )
    f.write('    (stroke (width 0) (type default))\n')
    f.write(f'    (uuid "{uid}")\n  )\n')


def _emit_label(f, name: str, x: float, y: float, kind: str) -> None:
    uid = det_uuid(f"label:{kind}:{name}:{x:.4f}:{y:.4f}")
    esc = kicad_string_escape(name)
    if kind == "hierarchical":
        f.write(f'  (hierarchical_label "{esc}" (shape passive) (at {fmt_mm(x)} {fmt_mm(y)} 0)\n')
    elif kind == "global":
        f.write(f'  (global_label "{esc}" (shape passive) (at {fmt_mm(x)} {fmt_mm(y)} 0)\n')
    else:
        f.write(f'  (label "{esc}" (at {fmt_mm(x)} {fmt_mm(y)} 0)\n')
    f.write('    (effects (font (size 1.27 1.27)) (justify left))\n')
    f.write(f'    (uuid "{uid}")\n  )\n')


def _emit_power_port(f, port) -> None:
    uid = det_uuid(f"pwr:{port.net}:{port.x:.4f}:{port.y:.4f}:{port.is_pwr_flag}")
    dx, dy = _power_symbol_pin_offset(port.lib_id)
    # Sheet Y is flipped vs symbol-local: world_y = inst_y - dy ⇒ inst_y = world_y + dy.
    sx, sy = port.x - dx, port.y + dy
    lib = port.lib_id
    f.write(f'  (symbol (lib_id "{kicad_string_escape(lib)}") (at {fmt_mm(sx)} {fmt_mm(sy)} 0) (unit 1)\n')
    f.write("    (in_bom no) (on_board yes) (fields_autoplaced yes)\n")
    f.write(f'    (uuid "{uid}")\n')
    tag = uid.replace("-", "")[:8]
    ref = f"#FLG{tag}" if port.is_pwr_flag else f"#PWR{tag}"
    f.write(
        f'    (property "Reference" "{ref}" (at {fmt_mm(sx)} {fmt_mm(sy + 1.27)} 0) '
        f'(effects (font (size 1.27 1.27)) (hide yes)))\n'
    )
    val = "PWR_FLAG" if port.is_pwr_flag else port.net
    f.write(
        f'    (property "Value" "{kicad_string_escape(val)}" '
        f'(at {fmt_mm(sx)} {fmt_mm(sy + (2.54 if port.is_gnd else -2.54))} 0) '
        f'(effects (font (size 1.27 1.27))))\n'
    )
    f.write("  )\n")


def _emit_nc(f, x, y) -> None:
    uid = det_uuid(f"noconn:{x:.4f},{y:.4f}")
    f.write(f'  (no_connect (at {fmt_mm(x)} {fmt_mm(y)}) (uuid "{uid}"))\n')


def _write_sheet_body(f, ir: SchematicIR, *, file_uuid: str, extra_power: str, sheet_paths=None, sym_paths=None) -> None:
    _header(f, file_uuid, ir, extra_power)
    for inst in ir.instances:
        _emit_instance(f, inst)
    for w in ir.wires:
        _emit_wire(f, w.x1, w.y1, w.x2, w.y2)
    for b in getattr(ir, "buses", None) or []:
        _emit_bus(f, b.x1, b.y1, b.x2, b.y2)
    for e in getattr(ir, "bus_entries", None) or []:
        _emit_bus_entry(f, e.x, e.y, e.dx, e.dy)
    for lb in ir.labels:
        _emit_label(f, lb.name, lb.x, lb.y, lb.kind)
    for p in ir.power_ports:
        _emit_power_port(f, p)
    for nc in ir.no_connects:
        _emit_nc(f, nc.x, nc.y)
    for sh in ir.sheets:
        f.write(f'  (sheet (at {fmt_mm(sh.x)} {fmt_mm(sh.y)}) (size {fmt_mm(sh.w)} {fmt_mm(sh.h)})\n')
        f.write(
            f'    (property "Sheetname" "{kicad_string_escape(sh.name)}" '
            f'(at {fmt_mm(sh.x)} {fmt_mm(sh.y - 2)} 0) '
            f'(effects (font (size 1.27 1.27)) (justify left bottom)))\n'
        )
        f.write(
            f'    (property "Sheetfile" "{kicad_string_escape(sh.filename)}" '
            f'(at {fmt_mm(sh.x)} {fmt_mm(sh.y + sh.h + 2)} 0) '
            f'(effects (font (size 1.27 1.27)) (justify left top) (hide yes)))\n'
        )
        f.write(f'    (uuid "{sh.uuid}")\n')
        for i, pin in enumerate(sh.pins):
            rot = int(getattr(pin, "rot", 180) or 180)
            justify = "right" if rot == 180 else "left"
            f.write(
                f'    (pin "{kicad_string_escape(pin.name)}" {pin.pin_type} '
                f'(at {fmt_mm(pin.x)} {fmt_mm(pin.y)} {rot})\n'
            )
            f.write(f'      (effects (font (size 1.27 1.27)) (justify {justify}))\n')
            f.write(f'      (uuid "{det_uuid(f"hpin:{sh.name}:{pin.name}:{i}")}")\n    )\n')
        f.write("  )\n")
    _title_block(f, ir.title, ir.rev, ir.company)
    f.write("  (sheet_instances\n    (path \"/\" (page \"1\"))\n")
    for pth, page in (sheet_paths or []):
        f.write(f'    (path "{kicad_string_escape(pth)}" (page "{kicad_string_escape(str(page))}"))\n')
    f.write("  )\n")
    f.write("  (symbol_instances\n")
    for row in (sym_paths or []):
        if len(row) >= 5:
            path, ref, val, fp, unit = row[0], row[1], row[2], row[3], row[4]
        else:
            path, ref, val, fp, unit = row[0], row[1], row[2], row[3], 1
        f.write(
            f'    (path "{kicad_string_escape(path)}" (reference "{kicad_string_escape(ref)}") '
            f'(unit {int(unit or 1)}) (value "{kicad_string_escape(val)}") '
            f'(footprint "{kicad_string_escape(fp)}"))\n'
        )
    f.write("  )\n)\n")


def _write_openhac_power_lib(sch_path: Path, ir: SchematicIR, extra_power: str, gen_path: str | None) -> str | None:
    """Ensure OpenHaC.kicad_sym exists so project tables can resolve synthesized rails."""
    if not extra_power:
        return gen_path
    dest = Path(gen_path) if gen_path else sch_path.with_suffix(".openhac-generated.kicad_sym")
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    bodies = []
    seen: set[str] = set()
    for p in ir.power_ports:
        if p.is_pwr_flag or not str(p.lib_id).startswith("OpenHaC:"):
            continue
        short = str(p.lib_id).split(":", 1)[1]
        if short in seen:
            continue
        seen.add(short)
        chunk = synthesize_power_symbol(p.lib_id, p.pin_name or p.net, is_gnd=p.is_gnd)
        chunk = chunk.replace(f'(symbol "{p.lib_id}"', f'(symbol "{short}"', 1)
        chunk = "\n".join(ln[4:] if ln.startswith("    ") else ln for ln in chunk.splitlines())
        bodies.append(chunk.rstrip() + "\n")
    if not bodies:
        return gen_path
    if existing.strip().startswith("(kicad_symbol_lib"):
        merged = existing.rstrip()
        if merged.endswith(")"):
            merged = merged[:-1]
        dest.write_text(merged + "".join(bodies) + ")\n", encoding="utf-8")
    else:
        dest.write_text(
            "(kicad_symbol_lib (version 20231120) (generator openhac)\n"
            + "".join(bodies)
            + ")\n",
            encoding="utf-8",
        )
    return str(dest)


def _synth_power_embed(ir: SchematicIR) -> str:
    seen: set[str] = set()
    chunks = []
    for p in ir.power_ports:
        if p.is_pwr_flag:
            continue
        if p.lib_id in seen:
            continue
        seen.add(p.lib_id)
        # Embed synthesized rails (power:<net>) always so pin name == net even if
        # KiCad's power:+3V3 exists — we still instance the library id when matched.
        from openhac.compiler.kicad_sym_pinpos import find_symbol_library_file, parse_kicad_symbol_id
        parsed = parse_kicad_symbol_id(p.lib_id)
        if parsed and parsed[0] == "power" and find_symbol_library_file("power") is not None:
            continue  # system power lib — never embed a conflicting copy
        chunks.append(synthesize_power_symbol(p.lib_id, p.pin_name or p.net, is_gnd=p.is_gnd))
    return "".join(chunks)


def generate_schematic(
    output_path: str,
    board,
    *,
    symbol_resolver=None,
    pinpos_report_path: str | None = None,
    generated_symbol_lib_path: str | None = None,
    embedded_lib_symbols: str | None = None,
    signoff: bool = False,
    circuit=None,
) -> SchematicIR:
    logger.info("Generating schematic (SSO) -> %s", output_path)
    if circuit is not None and list(getattr(circuit, "parts", []) or []):
        from openhac.schematic.util import iter_pins
        parts = list(circuit.parts)
        nets = list(getattr(circuit, "nets", []) or [])
        if not nets:
            seen: dict[int, object] = {}
            for part in parts:
                for pin in iter_pins(part):
                    n = getattr(pin, "net", None)
                    if n is not None:
                        seen[id(n)] = n
            nets = list(seen.values())
    else:
        parts, nets = collect_parts_and_nets(board)
    if signoff:
        for p in parts:
            resolve_part_symbol(p, signoff=True)

    embed = embedded_lib_symbols
    gen_path = generated_symbol_lib_path
    if gen_path is None and parts:
        outp = Path(output_path)
        gen_path = str(outp.with_suffix(".openhac-generated.kicad_sym"))
        gp, embed_auto = write_generated_symbol_library(gen_path, parts, nickname="OpenHaC", signoff=signoff)
        gen_path = gp
        if embed is None:
            embed = embed_auto

    resolver = symbol_resolver or make_pin_resolver(generated_sym_path=gen_path)
    ir = build_ir(
        parts, nets, board,
        resolver=resolver,
        signoff=signoff,
        embedded_lib_symbols=embed or "",
        generated_sym_path=gen_path,
    )
    extra_power = _synth_power_embed(ir)
    lib_ids = [inst.lib_id for inst in ir.instances]
    lib_ids.extend(p.lib_id for p in ir.power_ports)
    type_ov = shared_bus_pin_type_overrides(parts, nets)
    cached = embed_used_lib_symbols(lib_ids, pin_type_overrides=type_ov)
    if cached:
        ir.embedded_lib_symbols = (ir.embedded_lib_symbols or "") + cached
    gen_written = _write_openhac_power_lib(Path(output_path), ir, extra_power, gen_path)
    if gen_written:
        ir.generated_sym_path = gen_written

    root = Path(output_path)
    root.parent.mkdir(parents=True, exist_ok=True)
    file_uuid = root_schematic_uuid()

    if ir.child_sheets:
        stem = root.stem
        sheet_paths = []
        for i, sh in enumerate(ir.sheets):
            sh.filename = f"{stem}.{sh.name}.kicad_sch"
            sheet_paths.append((f"/{sh.uuid}", str(i + 2)))
        global_sym = []
        for inst in ir.instances:
            sh = next((s for s in ir.sheets if s.name == inst.sheet), None)
            path = f"/{sh.uuid}/{inst.uuid}" if sh else f"/{inst.uuid}"
            global_sym.append((path, inst.ref, inst.value, inst.footprint, inst.unit))
        with open(root, "w", encoding="utf-8") as f:
            # Root holds sheet boxes + parent-side pin stubs (no component instances).
            for child in ir.child_sheets.values():
                child_ids = [inst.lib_id for inst in child.instances]
                child_ids.extend(p.lib_id for p in child.power_ports)
                child.embedded_lib_symbols = embed_used_lib_symbols(
                    child_ids, pin_type_overrides=type_ov,
                ) or ""
            root_ir = SchematicIR(title=ir.title, rev=ir.rev, company=ir.company,
                                  embedded_lib_symbols=ir.embedded_lib_symbols)
            root_ir.sheets = ir.sheets
            root_ir.wires = list(ir.root_wires)
            root_ir.labels = list(ir.root_labels)
            from openhac.schematic.layout import _paper_for_ir
            root_ir.paper = _paper_for_ir(root_ir)
            _write_sheet_body(f, root_ir, file_uuid=file_uuid, extra_power=extra_power,
                              sheet_paths=sheet_paths, sym_paths=global_sym)
        for name, child in ir.child_sheets.items():
            child_path = root.parent / f"{stem}.{name}.kicad_sch"
            seen_h: set[str] = set()
            kept = []
            for lb in child.labels:
                if lb.kind == "hierarchical":
                    if lb.name in seen_h:
                        continue
                    seen_h.add(lb.name)
                kept.append(lb)
            child.labels = kept
            sym_paths = [(f"/{inst.uuid}", inst.ref, inst.value, inst.footprint, inst.unit) for inst in child.instances]
            with open(child_path, "w", encoding="utf-8") as cf:
                _write_sheet_body(
                    cf, child, file_uuid=sheet_instance_uuid(name), extra_power=extra_power, sym_paths=sym_paths,
                )
    else:
        sym_paths = [(f"/{inst.uuid}", inst.ref, inst.value, inst.footprint, inst.unit) for inst in ir.instances]
        with open(root, "w", encoding="utf-8") as f:
            _write_sheet_body(f, ir, file_uuid=file_uuid, extra_power=extra_power, sym_paths=sym_paths)

    if pinpos_report_path:
        import json
        try:
            n_pins = sum(1 for _ in ir.pin_xy)
            stub = truthy_env("OPENHAC_SCHEMATIC_STUB_ONLY")
            report = {
                "schema": "openhac.sch_pinpos_report.v1",
                "resolved_pin_count": 0 if stub else n_pins,
                "stub_pin_count": n_pins if stub else 0,
                "by_symbol": {},
            }
            Path(pinpos_report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Could not write pinpos report: %s", e)

    return ir
