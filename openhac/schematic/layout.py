"""Schematic placement and connectivity IR (SSO-002, SSO-022, SSO-031)."""

from __future__ import annotations

import os

from openhac.schematic.ir import (
    BusEntry,
    BusSeg,
    HierPin,
    NetLabel,
    NoConnect,
    PowerPort,
    SchematicIR,
    SheetBox,
    SymbolInstance,
    WireSeg,
)
from openhac.schematic.resolve import (
    make_pin_resolver,
    pin_offset,
    resolve_part_symbol,
    schematic_symbol_lib_key,
)
from openhac.schematic.kicad_links import sheet_instance_uuid, symbol_instance_uuid
from openhac.schematic.util import (
    bus_member_prefix,
    is_gnd_net_name,
    is_nc_net,
    iter_pins,
    module_field,
    net_name,
    net_openhac_type,
    part_datasheet,
    part_footprint,
    part_manufacturer,
    part_mpn,
    part_ref,
    part_rotation_deg,
    part_value,
    pin_num,
    pin_is_power_out,
    pin_type,
    pin_unit,
    pinout_records,
    rotate_offset,
    sheet_field,
    snap,
    sorted_net_pins,
    want_multi_sheet,
)


def schematic_geometry(circuit, *, symbol_resolver=None) -> dict:
    """Placement/wire/label geometry from IR (SSO-031 round-trip)."""
    from openhac.schematic.collect import collect_parts_and_nets, harvest_nets_from_parts

    parts = list(getattr(circuit, "parts", []) or [])
    nets = list(getattr(circuit, "nets", []) or [])
    if not parts:
        parts, nets = collect_parts_and_nets(None)
    elif not nets:
        nets = harvest_nets_from_parts(parts)

    class _Board:
        project_name = "OpenHaC"
        release_tag = "v1.0"
        modules = []

    ir = build_ir(parts, nets, _Board(), resolver=symbol_resolver)
    return {
        "part_placements": {inst.part: (inst.x, inst.y) for inst in ir.instances},
        "wires": [(w.x1, w.y1, w.x2, w.y2) for w in ir.wires],
        "labels": [(lb.name, lb.x, lb.y) for lb in ir.labels],
        "ir": ir,
    }


def pin_world_xy(pin, part, origin: tuple[float, float], rot: float, resolver, symbol_name: str | None = None) -> tuple[float, float, float]:
    name = symbol_name or schematic_symbol_lib_key(part)
    dx, dy, prot = pin_offset(resolver, part, pin, symbol_name=name)
    rdx, rdy = rotate_offset(dx, dy, rot)
    # KiCad schematic sheet Y is opposite symbol-local Y: world = (inst_x + dx, inst_y - dy).
    return origin[0] + rdx, origin[1] - rdy, prot + rot


# 50 mil grid. Stubs must not land on a neighbor pin (column pitch / part gap).
_STUB_MM = 2.54
_COL_PITCH_MM = 152.4
_PART_GAP_MM = 20.32
_MOD_GAP_MM = 38.1
_CELL_H_PAD_MM = 20.32


def _stub_delta_from_rot(prot: float) -> tuple[float, float]:
    """Continue one grid step past the pin tip (library rotation), not along the pin column.

    Origin-based 'away from body' picks the long axis, so top-right pins stub
    vertically down the pin stack and KiCad T-joins unrelated nets.
    """
    r = float(prot or 0.0) % 360.0
    if r < 45.0 or r >= 315.0:
        return _STUB_MM, 0.0
    if 45.0 <= r < 135.0:
        return 0.0, -_STUB_MM  # symbol +Y is up; sheet Y grows down
    if 135.0 <= r < 225.0:
        return -_STUB_MM, 0.0
    return 0.0, _STUB_MM


def _outward_delta(wx: float, wy: float, ox: float, oy: float, prot: float | None = None) -> tuple[float, float]:
    """One-grid stub from the pin tip, perpendicular to the body edge."""
    if prot is not None:
        return _stub_delta_from_rot(prot)
    if abs(wx - ox) >= abs(wy - oy):
        return (_STUB_MM if wx >= ox else -_STUB_MM), 0.0
    return 0.0, (_STUB_MM if wy >= oy else -_STUB_MM)


def _snap_key(x: float, y: float) -> tuple[float, float]:
    return (round(snap(x), 4), round(snap(y), 4))


def _add_stub_label(
    ir: SchematicIR,
    *,
    sheet: str,
    ref: str,
    wx: float,
    wy: float,
    ox: float,
    oy: float,
    name: str,
    kind: str = "local",
    prot: float | None = None,
    pin_num_s: str = "",
) -> None:
    """Wire from the pin (exact library coords) out one grid step, label on the end.

    Do not independently snap the far end: that collapses off-grid pins into
    ~0.025 mm segments that miss the pin (unconnected + off-grid ERC).
    """
    if prot is None:
        prot = ir.pin_rot.get((ref, str(pin_num_s)))
    dx, dy = _outward_delta(wx, wy, ox, oy, prot)
    lx, ly = wx + dx, wy + dy
    if abs(lx - wx) + abs(ly - wy) < 1.0:
        lx, ly = wx + _STUB_MM, wy
    ir.wires.append(WireSeg(wx, wy, lx, ly, sheet=sheet, net=name))
    ir.labels.append(NetLabel(name, lx, ly, kind, sheet=sheet, owner_ref=ref))


def _stretch_wire_to_label(ir: SchematicIR, lb: NetLabel, nx: float, ny: float) -> None:
    """Keep the stub electrically on the label after a collision nudge (up to one grid)."""
    best = None
    best_d = 1e9
    for w in ir.wires:
        if w.net != lb.name or w.sheet != lb.sheet:
            continue
        d2 = abs(w.x2 - lb.x) + abs(w.y2 - lb.y)
        d1 = abs(w.x1 - lb.x) + abs(w.y1 - lb.y)
        if d2 < best_d:
            best_d, best = d2, (w, "2")
        if d1 < best_d:
            best_d, best = d1, (w, "1")
    if best is None or best_d > (_STUB_MM + 0.2):
        return
    w, which = best
    if which == "2":
        w.x2, w.y2 = nx, ny
    else:
        w.x1, w.y1 = nx, ny


def _separate_colliding_nets(ir: SchematicIR) -> None:
    """If two different nets share a snapped point, nudge the later primitive +X."""
    occupied: dict[tuple[float, float], str] = {}

    def _claim(x: float, y: float, net: str) -> tuple[float, float, bool]:
        k = _snap_key(x, y)
        cx, cy = x, y
        moved = False
        for _ in range(12):
            owner = occupied.get(k)
            if owner is None or owner == net:
                occupied[k] = net
                return cx, cy, moved
            cx = snap(cx + _STUB_MM)
            k = _snap_key(cx, cy)
            moved = True
        occupied[k] = net
        return cx, cy, moved

    for nc in ir.no_connects:
        occupied.setdefault(_snap_key(nc.x, nc.y), "__NC__")

    for p in ir.power_ports:
        nx, ny, moved = _claim(p.x, p.y, p.net)
        if moved:
            ir.wires.append(WireSeg(p.x, p.y, nx, ny, sheet=p.sheet, net=p.net))
            p.x, p.y = nx, ny

    for lb in ir.labels:
        nx, ny, moved = _claim(lb.x, lb.y, lb.name)
        if moved:
            _stretch_wire_to_label(ir, lb, nx, ny)
            lb.x, lb.y = nx, ny


def _flow_from_tag(tag: str) -> int | None:
    t = str(tag or "").strip().lower()
    if t in ("0", "power", "pwr", "left"):
        return 0
    if t in ("2", "io", "right"):
        return 2
    if t in ("1", "compute", "mid", "middle"):
        return 1
    return None


def _flow_column(mod_name: str, board) -> int:
    """0=power/left, 1=compute/mid, 2=IO/right — from module tags / interface kinds."""
    if board is not None:
        for m in getattr(board, "modules", []) or []:
            if str(getattr(m, "name", "")) != mod_name:
                continue
            tagged = _flow_from_tag(getattr(m, "schematic_flow", None) or "")
            if tagged is not None:
                return tagged
            kinds = []
            for d in (
                getattr(m, "required_interfaces", {}) or {},
                getattr(m, "optional_interfaces", {}) or {},
            ):
                for iface in d.values():
                    kinds.append(str(getattr(iface, "kind", "") or getattr(iface, "name", "") or "").lower())
            blob = " ".join(kinds)
            left = any(t in blob for t in ("pwr", "power", "supply", "vin", "vbat"))
            right = any(t in blob for t in ("uart", "spi", "i2c", "can", "usb", "gpio", "io"))
            if left and not right:
                return 0
            if right and not left:
                return 2
            break
    if os.environ.get("OPENHAC_SCHEMATIC_FLOW_NAME_TOKENS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        keys = [str(mod_name or "").lower()]
        blob = " ".join(keys)
        left = any(
            t in blob
            for t in ("pwr", "power", "vcc", "3v3", "gnd", "vbus", "vin", "ldo", "reg", "supply", "batt")
        )
        right = any(
            t in blob
            for t in ("uart", "spi", "i2c", "can", "rs485", "usb", "gpio", "jtag", "header", "conn", "eth", "io")
        )
        if left and not right:
            return 0
        if right and not left:
            return 2
    return 1


def _assign_positions(parts, resolver, board=None, overlay=None) -> dict:
    """Module-grouped left-to-right flow columns; 50 mil snap. No NetworkX.

    LIVE-002: overlay symbol ``(at x y rot)`` wins for surviving refdes.
    """
    groups: dict[str, list] = {}
    for p in parts:
        groups.setdefault(module_field(p), []).append(p)
    names = sorted(groups.keys(), key=lambda s: (not s, s))
    cols: dict[int, list[str]] = {0: [], 1: [], 2: []}
    for m in names:
        cols[_flow_column(m, board)].append(m)
    positions: dict = {}
    rotations: dict = {}
    for col, mod_names in cols.items():
        cur_mod_y = 25.4
        px_base = 40.64 + col * _COL_PITCH_MM
        for m in mod_names:
            m_parts = sorted(groups[m], key=lambda p: (str(part_ref(p)).upper(), getattr(p, "_part_id", 0)))
            cur_y = 0.0
            for p in m_parts:
                rot = part_rotation_deg(p)
                n_pins = max(len(iter_pins(p)), 2)
                cell_h = min(150.0, max(25.4, (n_pins / 2) * 5.08 + _CELL_H_PAD_MM))
                px, py = px_base, cur_mod_y + cur_y
                pins = iter_pins(p)
                if pins and resolver is not None:
                    dx, dy, _ = pin_offset(resolver, p, pins[0], symbol_name=schematic_symbol_lib_key(p))
                    rdx, rdy = rotate_offset(dx, dy, rot)
                    px = snap(px + rdx) - rdx
                    py = snap(py - rdy) + rdy
                positions[p] = (px, py)
                rotations[p] = rot
                cur_y += cell_h + _PART_GAP_MM
            cur_mod_y += cur_y + _MOD_GAP_MM
    if overlay is None and board is not None:
        overlay = getattr(board, "_kicad_artwork_overlay", None)
    if overlay is not None:
        from openhac.compiler.kicad_artwork import apply_symbol_overlay

        apply_symbol_overlay(positions, rotations, parts, overlay)
    return positions, rotations


def _collect_bus_groups(nets: list) -> dict[str, list]:
    """Group nets that belong to a named bus (native Bus or NAME[i] labels)."""
    groups: dict[str, list] = {}
    seen: set[int] = set()
    try:
        from openhac.core.circuit import default_circuit

        for bus in getattr(default_circuit, "buses", []) or []:
            prefix = str(getattr(bus, "name", "") or "")
            if not prefix:
                continue
            members = []
            for n in list(getattr(bus, "nets", []) or []):
                if id(n) in seen:
                    continue
                seen.add(id(n))
                members.append(n)
            if len(members) >= 2:
                groups.setdefault(prefix, []).extend(members)
    except Exception:
        pass
    for net in nets:
        if id(net) in seen:
            continue
        nn = net_name(net)
        prefix = bus_member_prefix(nn)
        if not prefix:
            continue
        groups.setdefault(prefix, []).append(net)
        seen.add(id(net))
    return {k: v for k, v in groups.items() if len(v) >= 2}


def _draw_bus(ir: SchematicIR, prefix: str, members: list, inst_xy: dict) -> None:
    """KiCad bus spine + bus_entry + member labels (SSO bus gate)."""
    pts: list[tuple[float, float, object]] = []
    for net in members:
        nn = net_name(net)
        for p in sorted_net_pins(net):
            xy = ir.pin_xy.get((part_ref(p.part), pin_num(p)))
            if xy:
                pts.append((xy[0], xy[1], p, nn))
    if len(pts) < 2:
        for x, y, pin, nn in pts:
            sh = sheet_field(pin.part)
            ref = part_ref(pin.part)
            ox, oy = inst_xy.get(ref, (x, y))
            _add_stub_label(
                ir, sheet=sh, ref=ref, wx=x, wy=y, ox=ox, oy=oy, name=nn,
                pin_num_s=pin_num(pin),
            )
        return
    max_x = max(p[0] for p in pts)
    min_y = min(p[1] for p in pts)
    max_y = max(p[1] for p in pts)
    bx = snap(max_x + 7.62)
    if abs(max_y - min_y) < 0.01:
        max_y = min_y + 2.54
    spine_sheet = sheet_field(pts[0][2].part)
    ir.buses.append(BusSeg(bx, snap(min_y), bx, snap(max_y), sheet=spine_sheet))
    for wx, wy, pin, nn in pts:
        ref = part_ref(pin.part)
        sh = sheet_field(pin.part)
        ox, oy = inst_xy.get(ref, (wx, wy))
        dx, dy = _outward_delta(wx, wy, ox, oy, ir.pin_rot.get((ref, pin_num(pin))))
        sx, sy = snap(wx + dx), snap(wy + dy)
        if abs(sx - wx) > 0.001 or abs(sy - wy) > 0.001:
            ir.wires.append(WireSeg(wx, wy, sx, sy, sheet=sh, net=nn))
        if abs(sx - (bx - _STUB_MM)) > 0.001:
            ir.wires.append(WireSeg(sx, sy, bx - _STUB_MM, sy, sheet=sh, net=nn))
        ir.bus_entries.append(
            BusEntry(bx - _STUB_MM, sy, _STUB_MM, _STUB_MM if sy <= (min_y + max_y) / 2 else -_STUB_MM, sheet=sh)
        )
        ir.labels.append(NetLabel(nn, sx, sy, "local", sheet=sh, owner_ref=ref))


def _on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float, eps: float = 0.2) -> bool:
    """True if (px,py) lies on the open segment (ax,ay)-(bx,by), not on an endpoint."""
    if abs(px - ax) < eps and abs(py - ay) < eps:
        return False
    if abs(px - bx) < eps and abs(py - by) < eps:
        return False
    if abs(ax - bx) < eps:
        if abs(px - ax) > eps:
            return False
        return min(ay, by) - eps <= py <= max(ay, by) + eps
    if abs(ay - by) < eps:
        if abs(py - ay) > eps:
            return False
        return min(ax, bx) - eps <= px <= max(ax, bx) + eps
    return False


def _through_wire_hits_foreign(ir: SchematicIR, ax: float, ay: float, bx: float, by: float) -> bool:
    """A collinear 2-pin wire must not pass through another pin (child-sheet T-join)."""
    for xy in ir.pin_xy.values():
        if _on_segment(xy[0], xy[1], ax, ay, bx, by):
            return True
    return False


def _nc_extra_library_pins(ir: SchematicIR, part, inst: SymbolInstance, resolver, lib_id: str) -> None:
    """Place no-connect on library pins the graph does not own (name-mapped)."""
    from openhac.compiler.kicad_sym_pinpos import (
        find_symbol_library_file,
        load_symbol_pin_positions,
        map_graph_pin_to_library_number,
        parse_kicad_symbol_id,
        pinout_from_kicad_symbol_id,
    )

    parsed = parse_kicad_symbol_id(lib_id)
    if not parsed or parsed[0] in ("OpenHaC", "power"):
        return
    path = find_symbol_library_file(parsed[0])
    if path is None:
        return
    pmap = load_symbol_pin_positions(path, parsed[1]) or {}
    po = pinout_from_kicad_symbol_id(lib_id) or []
    by_num = {str(r.get("num") or ""): r for r in po if r.get("num") not in (None, "")}
    owned = set()
    for pin in iter_pins(part):
        libn = map_graph_pin_to_library_number(pin, pmap, by_num)
        if libn:
            owned.add(str(libn))
    for num, rec in pmap.items():
        if str(num) in owned:
            continue
        if str((by_num.get(str(num)) or {}).get("type") or "").lower() in ("no_connect", "free"):
            continue
        dx, dy = float(rec[0]), float(rec[1])
        rdx, rdy = rotate_offset(dx, dy, inst.rot)
        wx, wy = inst.x + rdx, inst.y - rdy
        if any(abs(px - wx) < 0.01 and abs(py - wy) < 0.01 for px, py in ir.pin_xy.values()):
            continue
        if not any(abs(nc.x - wx) < 0.01 and abs(nc.y - wy) < 0.01 for nc in ir.no_connects):
            ir.no_connects.append(NoConnect(wx, wy, sheet=inst.sheet))


def _hier_pin_type(net) -> str:
    types = []
    for p in sorted_net_pins(net):
        t = pin_type(p)
        if t:
            types.append(t)
    uniq = {t for t in types if t not in ("unspecified", "")}
    if len(uniq) == 1:
        t = next(iter(uniq))
        if t in ("input", "output", "bidirectional", "tri_state", "passive", "power_in", "power_out"):
            return "passive" if t in ("power_in", "power_out") else t
    return "passive"


def build_ir(
    parts: list,
    nets: list,
    board,
    *,
    resolver=None,
    signoff: bool = False,
    embedded_lib_symbols: str = "",
    generated_sym_path: str | None = None,
) -> SchematicIR:
    from openhac.compiler.kicad_sym_pinpos import (
        find_symbol_library_file,
        load_symbol_pin_positions,
        map_graph_pin_to_library_number,
        parse_kicad_symbol_id,
        pinout_from_kicad_symbol_id,
    )
    from openhac.schematic.resolve import match_power_symbol  # defined below in resolve — imported late

    if resolver is None:
        resolver = make_pin_resolver(generated_sym_path=generated_sym_path)

    overlay = getattr(board, "_kicad_artwork_overlay", None)
    positions, rotations = _assign_positions(parts, resolver, board, overlay=overlay)
    overlaid_refs = set(getattr(overlay, "symbols", None) or {})
    overlaid_uuids = set(getattr(overlay, "symbols_by_uuid", None) or {})
    title = str(getattr(board, "project_name", None) or "OpenHaC")
    rev = str(getattr(board, "release_tag", None) or "v1.0")
    company = str(getattr(board, "company", None) or getattr(board, "manufacturer", None) or "")
    ir = SchematicIR(title=title, rev=rev, company=company, embedded_lib_symbols=embedded_lib_symbols,
                     generated_sym_path=generated_sym_path)

    sheet_names = sorted({sheet_field(p) for p in parts if sheet_field(p)})
    multi = want_multi_sheet(parts, sheet_names) and bool(sheet_names)

    for part in parts:
        resolved = resolve_part_symbol(part, signoff=signoff)
        ref = part_ref(part)
        uid = symbol_instance_uuid(part, 1)
        if overlay is not None and (ref in overlaid_refs or uid in overlaid_uuids):
            x, y = positions[part][0], positions[part][1]
        else:
            x, y = snap(positions[part][0]), snap(positions[part][1])
        rot = rotations[part]
        recs = pinout_records(part)
        units = sorted({max(1, int(r.get("unit") or 1)) for r in recs if str(r.get("num") or "").strip()}) or [1]
        if len(units) <= 1:
            units = [1]
        ds = part_datasheet(part)
        mpn = part_mpn(part)
        mfr = part_manufacturer(part)
        for ui, unit in enumerate(units):
            overlaid = overlay is not None and (ref in overlaid_refs or uid in overlaid_uuids)
            if overlaid:
                ux = x if ui == 0 else x + ui * 38.1
                uy = y
            else:
                ux = snap(x + ui * 38.1)
                uy = y
            unit_pins = [pn for pn in iter_pins(part) if pin_unit(pn) == unit] if len(units) > 1 else list(iter_pins(part))
            inst = SymbolInstance(
                part=part,
                lib_id=resolved.lib_id,
                x=ux,
                y=uy,
                rot=rot,
                uuid=symbol_instance_uuid(part, unit),
                ref=ref,
                value=part_value(part) or ref,
                footprint=part_footprint(part),
                sheet=sheet_field(part),
                unit=unit,
                pin_nums=[pin_num(pn) for pn in unit_pins if pin_num(pn)],
                datasheet=ds,
                mpn=mpn,
                manufacturer=mfr,
            )
            ir.instances.append(inst)
            parsed = parse_kicad_symbol_id(resolved.lib_id)
            pmap, by_num = {}, {}
            if parsed and parsed[0] not in ("OpenHaC", "power"):
                path = find_symbol_library_file(parsed[0])
                if path is not None:
                    pmap = load_symbol_pin_positions(path, parsed[1]) or {}
                po = pinout_from_kicad_symbol_id(resolved.lib_id) or []
                by_num = {str(r.get("num") or ""): r for r in po if r.get("num") not in (None, "")}
            for pin in unit_pins:
                if pmap:
                    libn = map_graph_pin_to_library_number(pin, pmap, by_num)
                    if libn is None:
                        continue
                wx, wy, prot = pin_world_xy(
                    pin, part, (ux, uy), rot, resolver, symbol_name=resolved.lib_id,
                )
                ir.pin_xy[(ref, pin_num(pin))] = (wx, wy)
                ir.pin_rot[(ref, pin_num(pin))] = prot
            _nc_extra_library_pins(ir, part, inst, resolver, resolved.lib_id)

    # Connectivity
    bus_groups = _collect_bus_groups(nets)
    bus_net_ids = {id(n) for members in bus_groups.values() for n in members}

    for net in nets:
        nn = net_name(net)
        pins = sorted_net_pins(net)
        ntype = net_openhac_type(net)
        if is_nc_net(net):
            for p in pins:
                xy = ir.pin_xy.get((part_ref(p.part), pin_num(p)))
                if xy:
                    ir.no_connects.append(NoConnect(xy[0], xy[1], sheet=sheet_field(p.part)))
            continue

        if ntype in ("power", "gnd") or (not pins and False):
            lib_id, pin_name, is_gnd = match_power_symbol(nn)
            for p in pins:
                xy = ir.pin_xy.get((part_ref(p.part), pin_num(p)))
                if not xy:
                    continue
                ir.power_ports.append(PowerPort(
                    net=nn, lib_id=lib_id, pin_name=pin_name, x=xy[0], y=xy[1], is_gnd=is_gnd,
                    sheet=sheet_field(p.part),
                ))
            sheet_pins = [
                p for p in pins
                if ir.pin_xy.get((part_ref(p.part), pin_num(p)))
            ]
            if sheet_pins and not any(pin_is_power_out(p) for p in sheet_pins):
                xy0 = ir.pin_xy[(part_ref(sheet_pins[0].part), pin_num(sheet_pins[0]))]
                ir.power_ports.append(PowerPort(
                    net=nn, lib_id="power:PWR_FLAG", pin_name="1",
                    x=xy0[0], y=xy0[1], is_pwr_flag=True, is_gnd=is_gnd_net_name(nn),
                    sheet=sheet_field(sheet_pins[0].part),
                ))
            continue

        if id(net) in bus_net_ids:
            continue

        inst_xy = {inst.ref: (inst.x, inst.y) for inst in ir.instances}

        def _stub_label(pin) -> None:
            ref = part_ref(pin.part)
            xy = ir.pin_xy.get((ref, pin_num(pin)))
            if not xy:
                return
            ox, oy = inst_xy.get(ref, xy)
            _add_stub_label(
                ir, sheet=sheet_field(pin.part), ref=ref,
                wx=xy[0], wy=xy[1], ox=ox, oy=oy, name=nn,
                pin_num_s=pin_num(pin),
            )

        if len(pins) >= 3:
            for p in pins:
                _stub_label(p)
            continue

        if len(pins) == 2:
            a, b = pins[0], pins[1]
            axy = ir.pin_xy.get((part_ref(a.part), pin_num(a)))
            bxy = ir.pin_xy.get((part_ref(b.part), pin_num(b)))
            if not axy or not bxy:
                continue
            ax, ay = axy
            bx, by = bxy
            same_sheet = sheet_field(a.part) == sheet_field(b.part)
            aligned = abs(ax - bx) < 0.01 or abs(ay - by) < 0.01
            if (
                same_sheet
                and aligned
                and (abs(ax - bx) > 0.001 or abs(ay - by) > 0.001)
                and not _through_wire_hits_foreign(ir, ax, ay, bx, by)
            ):
                sh = sheet_field(a.part)
                ir.wires.append(WireSeg(ax, ay, bx, by, sheet=sh, net=nn))
            else:
                _stub_label(a)
                _stub_label(b)

    inst_xy = {inst.ref: (inst.x, inst.y) for inst in ir.instances}
    for prefix, members in bus_groups.items():
        _draw_bus(ir, prefix, members, inst_xy)

    # Unused pins → no_connect (SSO-020). Do not NC a pin that already has a real net
    # (nc_unused_pins may run before later += connections).
    for part in parts:
        for pin in iter_pins(part):
            n = getattr(pin, "net", None)
            if n is not None and not is_nc_net(n):
                continue
            xy = ir.pin_xy.get((part_ref(part), pin_num(pin)))
            if xy and not any(abs(nc.x - xy[0]) < 0.01 and abs(nc.y - xy[1]) < 0.01 for nc in ir.no_connects):
                ir.no_connects.append(NoConnect(xy[0], xy[1], sheet=sheet_field(part)))

    _separate_colliding_nets(ir)

    if multi:
        _apply_hierarchy(ir, parts, nets, board, sheet_names)

    ir.paper = _paper_for_ir(ir)
    return ir


_ISO_PAPER_MM = (
    ("A4", 210.0, 297.0),
    ("A3", 297.0, 420.0),
    ("A2", 420.0, 594.0),
    ("A1", 594.0, 841.0),
    ("A0", 841.0, 1189.0),
)


def _paper_for_ir(ir: SchematicIR) -> str:
    """Smallest ISO sheet that contains all placed primitives (portrait)."""
    xs: list[float] = [25.4]
    ys: list[float] = [25.4]
    for inst in ir.instances:
        xs.append(inst.x)
        ys.append(inst.y)
    for w in list(ir.wires) + list(getattr(ir, "root_wires", None) or []):
        xs.extend((w.x1, w.x2))
        ys.extend((w.y1, w.y2))
    for p in ir.power_ports:
        xs.append(p.x)
        ys.append(p.y)
    for nc in ir.no_connects:
        xs.append(nc.x)
        ys.append(nc.y)
    for lb in ir.labels:
        xs.append(lb.x)
        ys.append(lb.y)
    for lb in getattr(ir, "root_labels", None) or []:
        xs.append(lb.x)
        ys.append(lb.y)
    for sh in getattr(ir, "sheets", None) or []:
        xs.extend((sh.x, sh.x + sh.w))
        ys.extend((sh.y, sh.y + sh.h))
        for hp in sh.pins:
            xs.append(hp.x)
            ys.append(hp.y)
    max_x = max(xs) + 25.4
    max_y = max(ys) + 25.4
    for name, w, h in _ISO_PAPER_MM:
        if max_x <= w and max_y <= h:
            return name
    return "A0"


def _filter_sheet(items, mod_name: str):
    return [x for x in items if getattr(x, "sheet", "") == mod_name]


def _attach_hier_label(child: SchematicIR, net_name_s: str) -> bool:
    """One hierarchical label per interface net; leave extra locals for on-sheet fanout."""
    for lb in child.labels:
        if lb.name == net_name_s:
            lb.kind = "hierarchical"
            return True
    inst_xy = {inst.ref: (inst.x, inst.y) for inst in child.instances}
    for inst in child.instances:
        for pin in iter_pins(inst.part):
            n = getattr(pin, "net", None)
            if n is None or net_name(n) != net_name_s:
                continue
            xy = child.pin_xy.get((inst.ref, pin_num(pin)))
            if not xy:
                continue
            ox, oy = inst_xy.get(inst.ref, xy)
            _add_stub_label(
                child, sheet=inst.sheet, ref=inst.ref,
                wx=xy[0], wy=xy[1], ox=ox, oy=oy, name=net_name_s, kind="hierarchical",
                pin_num_s=pin_num(pin),
            )
            return True
    return False


def _shift_ir(ir: SchematicIR, dx: float, dy: float) -> None:
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return
    for inst in ir.instances:
        inst.x += dx
        inst.y += dy
    for w in ir.wires:
        w.x1 += dx
        w.y1 += dy
        w.x2 += dx
        w.y2 += dy
    for b in ir.buses:
        b.x1 += dx
        b.y1 += dy
        b.x2 += dx
        b.y2 += dy
    for e in ir.bus_entries:
        e.x += dx
        e.y += dy
    for lb in ir.labels:
        lb.x += dx
        lb.y += dy
    for p in ir.power_ports:
        p.x += dx
        p.y += dy
    for nc in ir.no_connects:
        nc.x += dx
        nc.y += dy
    ir.pin_xy = {k: (x + dx, y + dy) for k, (x, y) in ir.pin_xy.items()}


def _normalize_child_origin(child: SchematicIR) -> None:
    """Each child sheet is its own page — don't keep parent packed coordinates."""
    xs: list[float] = []
    ys: list[float] = []
    for inst in child.instances:
        xs.append(inst.x)
        ys.append(inst.y)
    for w in child.wires:
        xs.extend((w.x1, w.x2))
        ys.extend((w.y1, w.y2))
    for lb in child.labels:
        xs.append(lb.x)
        ys.append(lb.y)
    for p in child.power_ports:
        xs.append(p.x)
        ys.append(p.y)
    for nc in child.no_connects:
        xs.append(nc.x)
        ys.append(nc.y)
    if not xs or not ys:
        return
    dx = snap(25.4 - min(xs))
    dy = snap(25.4 - min(ys))
    _shift_ir(child, dx, dy)


def _sheet_pin_nets(iface_nets: list) -> list:
    """Power/GND are global via power symbols; NC is not an interface."""
    out = []
    for n in iface_nets:
        if is_nc_net(n):
            continue
        if net_openhac_type(n) in ("power", "gnd"):
            continue
        out.append(n)
    return out


def _iface_nets_for_sheet(mod_name: str, parts, nets, board) -> list:
    iface_nets = []
    try:
        from openhac.schematic.collect import interface_nets_for_module
        mod_obj = next(
            (m for m in (getattr(board, "modules", []) or []) if str(getattr(m, "name", "")) == mod_name),
            None,
        )
        if mod_obj:
            iface_nets = list(interface_nets_for_module(mod_obj) or [])
    except Exception:
        iface_nets = []
    if iface_nets:
        return iface_nets
    seen = set()
    for net in nets:
        pins = sorted_net_pins(net)
        mods = {sheet_field(p.part) for p in pins}
        if mod_name in mods and len(mods) > 1 and id(net) not in seen:
            seen.add(id(net))
            iface_nets.append(net)
    return iface_nets


def _wire_parent_sheet_pins(ir: SchematicIR) -> None:
    """Stub + local label on each parent sheet pin. Same-named locals join the net.

    Do not draw a shared spine: horizontals at the same Y T-join unrelated nets.
    """
    occupied: dict[tuple[float, float], str] = {}
    for sh in ir.sheets:
        for hp in sh.pins:
            hp.x, hp.y = snap(hp.x), snap(hp.y)
            lx, ly = snap(hp.x - _STUB_MM), hp.y
            n = 0
            k = _snap_key(lx, ly)
            while k in occupied and occupied[k] != hp.name and n < 12:
                ly = snap(ly + _STUB_MM)
                k = _snap_key(lx, ly)
                n += 1
            occupied[k] = hp.name
            ir.root_wires.append(WireSeg(hp.x, hp.y, lx, hp.y, sheet="", net=hp.name))
            if abs(ly - hp.y) >= 0.5:
                ir.root_wires.append(WireSeg(lx, hp.y, lx, ly, sheet="", net=hp.name))
            ir.root_labels.append(NetLabel(hp.name, lx, ly, "local", sheet="", owner_ref=sh.name))


def _apply_hierarchy(ir: SchematicIR, parts, nets, board, sheet_names: list[str]) -> None:
    sw = snap(139.7)
    gap = snap(25.4)
    n_sheets = max(1, len(sheet_names))
    # Pack to A0 usable area when possible (generic, not board-specific).
    cols = max(1, min(n_sheets, int(790.0 // (sw + gap)) or 1))
    col_y = [snap(50.8)] * cols
    for i, mod_name in enumerate(sheet_names):
        s_uuid = sheet_instance_uuid(mod_name)
        col = i % cols
        iface_nets = _sheet_pin_nets(_iface_nets_for_sheet(mod_name, parts, nets, board))
        n_pins = min(40, len(iface_nets))
        sh = snap(max(50.8, (max(n_pins, 1) + 3) * 5.08))
        sx = snap(50.8 + col * (sw + gap))
        sy = snap(col_y[col])
        col_y[col] = snap(sy + sh + gap)
        hpins = []
        for j, net in enumerate(iface_nets[:40]):
            nn = net_name(net)
            px, py = sx, snap(sy + (j + 2) * 5.08)
            hpins.append(HierPin(nn, _hier_pin_type(net), px, py, rot=180))
        child = SchematicIR(title=f"{ir.title} - {mod_name}", rev=ir.rev, company=ir.company,
                            embedded_lib_symbols=ir.embedded_lib_symbols)
        child.instances = [inst for inst in ir.instances if inst.sheet == mod_name]
        child_refs = {inst.ref for inst in child.instances}
        child.pin_xy = {k: v for k, v in ir.pin_xy.items() if k[0] in child_refs}
        child.pin_rot = {k: v for k, v in ir.pin_rot.items() if k[0] in child_refs}
        child.wires = _filter_sheet(ir.wires, mod_name)
        child.labels = _filter_sheet(ir.labels, mod_name)
        child.power_ports = _filter_sheet(ir.power_ports, mod_name)
        child.no_connects = _filter_sheet(ir.no_connects, mod_name)
        child.buses = _filter_sheet(ir.buses, mod_name)
        child.bus_entries = _filter_sheet(ir.bus_entries, mod_name)
        kept = []
        for hp in hpins:
            if _attach_hier_label(child, hp.name):
                kept.append(hp)
        hpins = kept
        _separate_colliding_nets(child)
        _normalize_child_origin(child)
        child.paper = _paper_for_ir(child)
        ir.sheets.append(SheetBox(
            name=mod_name,
            filename="",
            uuid=s_uuid,
            x=sx, y=sy, w=sw, h=sh,
            pins=hpins,
        ))
        ir.child_sheets[mod_name] = child

    _wire_parent_sheet_pins(ir)
