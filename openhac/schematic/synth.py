"""Generic box-and-pins symbol synthesizer (SSO-005). Pin records only."""

from __future__ import annotations

from pathlib import Path

from openhac.schematic.resolve import schematic_symbol_lib_key
from openhac.schematic.util import (
    iter_pins,
    kicad_string_escape,
    pin_name,
    pin_num,
    pin_type,
    pin_unit,
    power_symbol_short_name,
)


_VALID_TYPES = {
    "input", "output", "bidirectional", "tri_state", "passive",
    "unspecified", "power_in", "power_out", "open_collector",
    "open_emitter", "free", "no_connect",
}
_TYPE_MAP = {
    "power": "power_in",
    "analog": "passive",
    "digital": "bidirectional",
    "tristate": "tri_state",
    "3state": "tri_state",
    "nc": "no_connect",
    "ground": "power_in",
}


def _norm_type(raw: str, *, signoff: bool = False) -> str:
    t = _TYPE_MAP.get(str(raw or "").lower().replace(" ", "_"), str(raw or "").lower().replace(" ", "_"))
    if t not in _VALID_TYPES:
        return "unspecified" if signoff else "passive"
    return t


def _side_for_record(rec: dict) -> str:
    side = str(rec.get("side") or "").strip().lower()
    if side in ("left", "right", "top", "bottom"):
        return side
    t = _norm_type(str(rec.get("type") or ""))
    name = str(rec.get("name") or "").upper()
    if t == "power_in" and name not in ("GND", "VSS", "AGND", "DGND", "PGND"):
        return "top"
    if t == "power_out" or name in ("GND", "VSS", "AGND", "DGND", "PGND"):
        return "bottom"
    return ""  # assigned by pin-number order later


def _records_from_part(part) -> list[dict]:
    recs = []
    for p in iter_pins(part):
        recs.append({
            "num": pin_num(p),
            "name": pin_name(p),
            "type": pin_type(p),
            "side": "",
            "unit": pin_unit(p),
        })
    return recs


def _record_unit(rec: dict) -> int:
    try:
        return max(1, int(rec.get("unit") or 1))
    except (TypeError, ValueError):
        return 1


def _natural_num_key(num: str):
    try:
        return (0, int(num))
    except ValueError:
        return (1, num.lower())


def _unit_body_sexp(
    *,
    inner_base: str,
    unit_index: int,
    recs: list[dict],
    signoff: bool,
) -> str:
    """One KiCad unit child: rectangle + pins. ``unit_index`` 0 = common ``_0_1``."""
    buckets: dict[str, list[dict]] = {"left": [], "right": [], "top": [], "bottom": []}
    unassigned: list[dict] = []
    for r in recs:
        side = _side_for_record(r)
        if side:
            buckets[side].append(r)
        else:
            unassigned.append(r)
    unassigned.sort(key=lambda r: _natural_num_key(str(r.get("num") or "")))
    for i, r in enumerate(unassigned):
        buckets["left" if i < (len(unassigned) + 1) // 2 else "right"].append(r)

    n_side = max(len(buckets["left"]), len(buckets["right"]), 1)
    spacing = 7.62 if len(recs) > 20 else 5.08
    h_mm = max((n_side + 1) * spacing, 15.24)
    max_left = max([len(str(p.get("name") or "")) for p in buckets["left"]] + [0])
    max_right = max([len(str(p.get("name") or "")) for p in buckets["right"]] + [0])
    w_mm = max(20.32, (max_left + max_right) * 1.8 + 10.16)
    h = h_mm / 2
    w = w_mm / 2

    def _pin_block(rec: dict, x: float, y: float, rot: int) -> str:
        num = kicad_string_escape(str(rec.get("num") or ""))
        name = kicad_string_escape(str(rec.get("name") or num))
        t = _norm_type(str(rec.get("type") or ""), signoff=signoff)
        hide = str(rec.get("name") or "").strip().upper() in (f"P{num}", f"PIN_{num}", f"PIN{num}", num.upper())
        ne = (
            '(effects (font (size 1.27 1.27)) (hide yes))'
            if hide
            else '(effects (font (size 1.27 1.27)))'
        )
        return (
            f'      (pin {t} line (at {x:.3f} {y:.3f} {rot}) (length 2.54)\n'
            f'        (name "{name}" {ne})\n'
            f'        (number "{num}" (effects (font (size 1.27 1.27))))\n'
            f'      )'
        )

    def _dist(plist: list[dict], x_fixed: float, y_fixed: float, rot: int, vertical: bool) -> list[str]:
        if not plist:
            return []
        start = -((len(plist) - 1) * spacing) / 2
        length = 2.54
        lines = []
        for i, rec in enumerate(plist):
            off = start + i * spacing
            if vertical:
                tx = x_fixed - length if rot == 180 else x_fixed + length
                lines.append(_pin_block(rec, tx, off, rot))
            else:
                ty = y_fixed + length if rot == 90 else y_fixed - length
                lines.append(_pin_block(rec, off, ty, rot))
        return lines

    pin_lines: list[str] = []
    pin_lines.extend(_dist(buckets["left"], -w, 0, 180, True))
    pin_lines.extend(_dist(buckets["right"], w, 0, 0, True))
    pin_lines.extend(_dist(buckets["top"], 0, h, 90, False))
    pin_lines.extend(_dist(buckets["bottom"], 0, -h, 270, False))
    child = f"{kicad_string_escape(inner_base)}_{unit_index}_1"
    body = (
        f'    (symbol "{child}"\n'
        f'      (rectangle (start {-w:.3f} {-h:.3f}) (end {w:.3f} {h:.3f}) '
        f'(stroke (width 0.254)) (fill (type background)))\n'
    )
    return body + "\n".join(pin_lines) + "\n    )\n"


def synthesize_symbol_sexp(
    *,
    outer_key: str,
    inner_base: str,
    ref_prefix: str,
    records: list[dict],
    signoff: bool = False,
) -> str:
    """Rectangle + pins. Multi-unit when records carry ``unit`` > 1."""
    recs = [dict(r) for r in records if str(r.get("num") or "").strip()]
    units = sorted({_record_unit(r) for r in recs}) or [1]
    multi = len(units) > 1

    # Header height from the largest unit so Reference/Value don't overlap.
    probe = recs if not multi else [r for r in recs if _record_unit(r) == units[0]] or recs
    n_side = max(len(probe) // 2, 1)
    spacing = 7.62 if len(recs) > 20 else 5.08
    h = max((n_side + 1) * spacing, 15.24) / 2

    header = (
        f'  (symbol "{kicad_string_escape(outer_key)}" (in_bom yes) (on_board yes)\n'
        f'    (property "Reference" "{kicad_string_escape(ref_prefix)}?" '
        f'(at 0 {h + 2.54:.3f} 0) (effects (font (size 1.27 1.27))))\n'
        f'    (property "Value" "{kicad_string_escape(inner_base)}" '
        f'(at 0 -{h + 2.54:.3f} 0) (effects (font (size 1.27 1.27))))\n'
    )
    if not multi:
        return header + _unit_body_sexp(
            inner_base=inner_base, unit_index=0, recs=recs, signoff=signoff,
        ) + "  )\n"
    bodies = []
    for u in units:
        urecs = [r for r in recs if _record_unit(r) == u]
        bodies.append(_unit_body_sexp(
            inner_base=inner_base, unit_index=u, recs=urecs, signoff=signoff,
        ))
    return header + "".join(bodies) + "  )\n"


def synthesize_power_symbol(lib_id: str, net_name: str, *, is_gnd: bool) -> str:
    """One-pin power symbol whose pin name equals the net (SSO-003). KiCad 9 unit layout."""
    short = power_symbol_short_name(lib_id.split(":", 1)[-1] if ":" in lib_id else net_name)
    key = lib_id if ":" in lib_id else f"OpenHaC:{short}"
    if ":" in key:
        inner = kicad_string_escape(key.split(":", 1)[1])
    else:
        inner = kicad_string_escape(short)
    pname = kicad_string_escape(net_name)
    if is_gnd:
        graphic = (
            f'      (symbol "{inner}_0_1"\n'
            "        (polyline (pts (xy 0 0) (xy 0 -1.27)) (stroke (width 0) (type default)) (fill (type none)))\n"
            "        (polyline (pts (xy -1.27 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27)) "
            "(stroke (width 0) (type default)) (fill (type outline)))\n"
            "      )\n"
        )
        pin_at = "0 0 270"
    else:
        graphic = (
            f'      (symbol "{inner}_0_1"\n'
            "        (polyline (pts (xy 0 0) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))\n"
            "        (polyline (pts (xy -0.762 1.27) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))\n"
            "        (polyline (pts (xy 0 2.54) (xy 0.762 1.27)) (stroke (width 0) (type default)) (fill (type none)))\n"
            "      )\n"
        )
        pin_at = "0 0 90"
    val_y = "-3.81" if is_gnd else "3.556"
    return (
        f'    (symbol "{kicad_string_escape(key)}" (power)\n'
        "      (pin_numbers (hide yes))\n"
        "      (pin_names (offset 0) (hide yes))\n"
        "      (in_bom no) (on_board yes)\n"
        f'      (property "Reference" "#PWR" (at 0 -3.81 0) '
        f'(effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'      (property "Value" "{pname}" (at 0 {val_y} 0) '
        f'(effects (font (size 1.27 1.27))))\n'
        f"{graphic}"
        f'      (symbol "{inner}_1_1"\n'
        f"        (pin power_in line (at {pin_at}) (length 0)\n"
        f'          (name "{pname}" (effects (font (size 1.27 1.27))))\n'
        f'          (number "1" (effects (font (size 1.27 1.27))))\n'
        "        )\n"
        "      )\n"
        "    )\n"
    )


def embed_used_lib_symbols(
    lib_ids: list[str] | set[str],
    pin_type_overrides: dict[str, dict[str, str]] | None = None,
) -> str:
    """Cache every instanced KiCad library symbol into ``lib_symbols`` (no graphics tables)."""
    from openhac.compiler.kicad_sym_pinpos import (
        rewrite_symbol_pin_electrical_types,
        schematic_lib_symbol_sexp,
    )

    overrides = pin_type_overrides or {}
    chunks: list[str] = []
    seen: set[str] = set()
    for lib_id in sorted({str(x).strip() for x in lib_ids if str(x).strip()}):
        if lib_id in seen or lib_id.startswith("OpenHaC:"):
            continue
        tree = schematic_lib_symbol_sexp(lib_id)
        if not tree:
            continue
        ov = overrides.get(lib_id)
        if ov:
            tree = rewrite_symbol_pin_electrical_types(tree, ov)
        seen.add(lib_id)
        nested = "\n".join(("    " + ln if ln.strip() else ln) for ln in tree.strip().splitlines())
        chunks.append(nested + "\n")
    return "".join(chunks)


_OUTPUT_LIKE = frozenset({"output", "open_emitter"})


def shared_bus_pin_type_overrides(parts, nets) -> dict[str, dict[str, str]]:
    """KiCad library MISO/etc. is often ``output``; a shared net of two such pins is a bus.

    Rewrite those library pins to ``tri_state`` in the embedded copy so ERC matches
    the graph (chip-select gated IO) without inventing symbol graphics.
    """
    from openhac.compiler.kicad_sym_pinpos import (
        map_graph_pin_to_library_number,
        pinout_from_kicad_symbol_id,
    )
    from openhac.schematic.resolve import resolve_part_symbol
    from openhac.schematic.util import is_nc_net, net_openhac_type, sorted_net_pins

    overrides: dict[str, dict[str, str]] = {}
    for net in nets or []:
        if is_nc_net(net) or net_openhac_type(net) in ("power", "gnd"):
            continue
        found: list[tuple[str, str]] = []
        for pin in sorted_net_pins(net):
            part = getattr(pin, "part", None)
            if part is None:
                continue
            lib_id = resolve_part_symbol(part).lib_id
            po = pinout_from_kicad_symbol_id(lib_id) or []
            by_num = {str(r.get("num") or ""): r for r in po if r.get("num") not in (None, "")}
            if not by_num:
                continue
            libn = map_graph_pin_to_library_number(pin, by_num, by_num)
            gtype = pin_type(pin)
            ltype = str((by_num.get(str(libn)) or {}).get("type") or "")
            if gtype in _OUTPUT_LIKE or ltype in _OUTPUT_LIKE:
                found.append((lib_id, str(libn or "")))
        if len({pair for pair in found if pair[1]}) >= 2:
            for lib_id, libn in found:
                if libn:
                    overrides.setdefault(lib_id, {})[libn] = "tri_state"
    return overrides


def write_generated_symbol_library(
    output_path: str,
    parts,
    *,
    nickname: str = "OpenHaC",
    signoff: bool = False,
    only_synth_lib_ids: set[str] | None = None,
) -> tuple[str | None, str | None]:
    """Write project-local .kicad_sym for parts that need OpenHaC: boxes."""
    part_list = list(getattr(parts, "parts", None) or parts or [])
    if not part_list:
        return None, None

    from openhac.schematic.resolve import resolve_part_symbol

    chunks: list[str] = []
    embed: list[str] = []
    names_done: set[str] = set()
    for part in part_list:
        resolved = resolve_part_symbol(part, signoff=signoff)
        if resolved.source != "synth":
            continue
        if only_synth_lib_ids is not None and resolved.lib_id not in only_synth_lib_ids:
            continue
        name = schematic_symbol_lib_key(part)
        if name in names_done:
            continue
        names_done.add(name)
        recs = _records_from_part(part)
        ref = str(getattr(part, "refdes", None) or getattr(part, "ref", None) or "U")
        prefix = "".join(c for c in ref if c.isalpha()) or "U"
        chunks.append(synthesize_symbol_sexp(
            outer_key=name, inner_base=name, ref_prefix=prefix, records=recs, signoff=signoff,
        ))
        embed.append(synthesize_symbol_sexp(
            outer_key=f"{nickname}:{name}", inner_base=name, ref_prefix=prefix, records=recs, signoff=signoff,
        ))

    if not chunks:
        return None, None

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "(kicad_symbol_lib (version 20231120) (generator openhac)\n" + "".join(chunks) + ")\n"
    out.write_text(text, encoding="utf-8")

    def _nest(body: str) -> str:
        return "\n".join("  " + line if line.strip() else line for line in body.splitlines())

    return str(out), _nest("".join(embed))
