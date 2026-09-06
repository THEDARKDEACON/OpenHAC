"""Parse and merge saved KiCad files as an artwork overlay (LIVE-001…006).

Python / the native circuit remains the electrical source of truth. Last-saved
``.kicad_sch`` / ``.kicad_pcb`` supply symbol/footprint pose and user wires,
tracks, vias, and zones. Overlay objects whose refdes or net vanished from the
graph are dropped, not resurrected.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from openhac.core.exceptions import ArtworkParityError, OpenHaCError
from openhac.schematic.parity import parse_kicad_sch_net_labels, parse_kicad_sch_wire_segments
from openhac.schematic.util import net_name, part_ref, pin_num, sorted_net_pins

logger = logging.getLogger("openhac.kicad_artwork")

_PIN_SNAP_MM = 1.27
# Conflict checks need a tighter hit than layout snap: 1.27 mm can land on the
# neighbour pin of the same symbol (LIVE-006 false shorts on recompile).
_CONFLICT_SNAP_MM = 0.51

_AT_RE = re.compile(r"\(at\s+([-0-9.]+)\s+([-0-9.]+)(?:\s+([-0-9.]+))?\)")
_CRTYD_START_RE = re.compile(r"\(start\s+([-0-9.]+)\s+([-0-9.]+)\)")
_CRTYD_END_RE = re.compile(r"\(end\s+([-0-9.]+)\s+([-0-9.]+)\)")
_UNIT_RE = re.compile(r"\(unit\s+(\d+)\)")
_UUID_RE = re.compile(r'\(uuid\s+"([^"]+)"\)')
_REF_PROP_RE = re.compile(r'\(property\s+"Reference"\s+"([^"]*)"')
_LIB_ID_RE = re.compile(r'\(lib_id\s+"([^"]+)"\)')
_NET_TABLE_RE = re.compile(r'\(net\s+(\d+)\s+"([^"]*)"\)')
_SEG_RE = re.compile(
    r'\(segment\s+\(start\s+([-0-9.]+)\s+([-0-9.]+)\)\s+\(end\s+([-0-9.]+)\s+([-0-9.]+)\)'
    r'\s+\(width\s+([-0-9.]+)\)\s+\(layer\s+"([^"]+)"\)\s+\(net\s+(\d+)\)'
)
_VIA_RE = re.compile(
    r'\(via\s+\(at\s+([-0-9.]+)\s+([-0-9.]+)\)\s+\(size\s+([-0-9.]+)\)\s+\(drill\s+([-0-9.]+)\)'
    r'\s+\(layers\s+"([^"]+)"\s+"([^"]+)"\)\s+\(net\s+(\d+)\)'
)
_ZONE_NET_RE = re.compile(r'\(net\s+(\d+)\)')
_ZONE_NAME_RE = re.compile(r'\(net_name\s+"([^"]*)"\)')
_FP_HEAD_RE = re.compile(r'\(footprint\s+"([^"]+)"')
_LABEL_KIND_RE = re.compile(
    r'\((global_label|hierarchical_label|label)\s+"([^"]+)"'
    r'(?:\s+\(shape\s+\w+\))?\s+\(at\s+([-0-9.]+)\s+([-0-9.]+)'
)
_INSTANCES_REF_RE = re.compile(r'\(instances\b[\s\S]*?\(reference\s+"([^"]*)"')


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def extract_sexp(text: str, start: int) -> tuple[str, int]:
    """Return the s-expression starting at ``text[start] == '('`` and the index after it."""
    if start < 0 or start >= len(text) or text[start] != "(":
        raise ValueError("extract_sexp: start is not '('")
    depth = 0
    in_str = False
    escape = False
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1], i + 1
        i += 1
    raise ValueError("extract_sexp: unmatched '('")


def iter_top_level_blocks(text: str, keyword: str) -> list[str]:
    """Yield depth-0/1 ``(keyword …)`` forms (sheet/pcb children, not ``lib_symbols``)."""
    needle = f"({keyword}"
    out: list[str] = []
    depth = 0
    in_str = False
    escape = False
    i = 0
    n = len(text)
    kn = len(keyword)
    while i < n:
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch == "(":
            after = i + 1 + kn
            is_kw = (
                depth in (0, 1)
                and text.startswith(needle, i)
                and (after >= n or not (text[after].isalnum() or text[after] in "_-"))
            )
            if is_kw:
                try:
                    block, end = extract_sexp(text, i)
                except ValueError:
                    break
                out.append(block)
                i = end
                continue
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
        i += 1
    return out


@dataclass
class SchSymbolPose:
    ref: str
    x: float
    y: float
    rot: float = 0.0
    unit: int = 1
    uuid: str = ""
    lib_id: str = ""


@dataclass
class FpPose:
    ref: str
    x: float
    y: float
    rot: float = 0.0
    footprint: str = ""
    crtyd_local: tuple[float, float, float, float] | None = None


@dataclass
class TrackSeg:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    layer: str
    net: str


@dataclass
class ViaRec:
    x: float
    y: float
    size: float
    drill: float
    layers: tuple[str, str]
    net: str


@dataclass
class ZoneRec:
    net: str
    sexp: str


@dataclass
class SchWire:
    x1: float
    y1: float
    x2: float
    y2: float
    sheet: str = ""


@dataclass
class SchLabel:
    name: str
    x: float
    y: float
    kind: str = "local"
    sheet: str = ""


@dataclass
class KicadArtworkOverlay:
    """Parsed last-saved KiCad artwork (LIVE-001)."""

    symbols: dict[str, SchSymbolPose] = field(default_factory=dict)
    symbols_by_uuid: dict[str, SchSymbolPose] = field(default_factory=dict)
    footprints: dict[str, FpPose] = field(default_factory=dict)
    tracks: list[TrackSeg] = field(default_factory=list)
    vias: list[ViaRec] = field(default_factory=list)
    zones: list[ZoneRec] = field(default_factory=list)
    sch_wires: list[SchWire] = field(default_factory=list)
    sch_labels: list[SchLabel] = field(default_factory=list)
    sch_graphics: list[str] = field(default_factory=list)
    source_sch: str | None = None
    source_pcb: str | None = None
    merged: bool = False

    def has_files(self) -> bool:
        return bool(self.source_sch or self.source_pcb)

    def is_empty(self) -> bool:
        return not (
            self.symbols
            or self.symbols_by_uuid
            or self.footprints
            or self.tracks
            or self.vias
            or self.zones
            or self.sch_wires
            or self.sch_labels
            or self.sch_graphics
        )

    def has_pcb_copper(self) -> bool:
        return bool(self.tracks or self.vias or self.zones)


def _usable_refdes(ref: str) -> bool:
    """True for R1/C12; false for #PWR, R?, or library placeholders like C."""
    if not ref or ref.startswith("#"):
        return False
    if ref.endswith("?"):
        return False
    return bool(re.search(r"[0-9]", ref))


def _courtyard_local_from_fp_block(block: str) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for line in block.splitlines():
        if "CrtYd" not in line:
            continue
        sm = _CRTYD_START_RE.search(line)
        em = _CRTYD_END_RE.search(line)
        if sm:
            xs.append(float(sm.group(1)))
            ys.append(float(sm.group(2)))
        if em:
            xs.append(float(em.group(1)))
            ys.append(float(em.group(2)))
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def parse_sch_symbol_records(text: str) -> list[SchSymbolPose]:
    """LIVE-002: every instance with ``(lib_id)`` + ``(at)``, including KiCad 9 ``R?``."""
    out: list[SchSymbolPose] = []
    for block in iter_top_level_blocks(text, "symbol"):
        head = block.split("(property", 1)[0]
        lib_m = _LIB_ID_RE.search(head) or _LIB_ID_RE.search(block[:800])
        if not lib_m:
            continue
        at_m = _AT_RE.search(head) or _AT_RE.search(block)
        if not at_m:
            continue
        ref_m = _REF_PROP_RE.search(block)
        ref = str(ref_m.group(1) if ref_m else "").strip()
        if not _usable_refdes(ref):
            inst_m = _INSTANCES_REF_RE.search(block)
            alt = str(inst_m.group(1) if inst_m else "").strip()
            if _usable_refdes(alt):
                ref = alt
        if ref.startswith("#"):
            continue
        rot = float(at_m.group(3) or 0.0)
        unit_m = _UNIT_RE.search(head) or _UNIT_RE.search(block)
        uid_m = _UUID_RE.search(head) or _UUID_RE.search(block)
        out.append(
            SchSymbolPose(
                ref=ref,
                x=float(at_m.group(1)),
                y=float(at_m.group(2)),
                rot=rot,
                unit=int(unit_m.group(1)) if unit_m else 1,
                uuid=uid_m.group(1) if uid_m else "",
                lib_id=lib_m.group(1) if lib_m else "",
            )
        )
    return out


def parse_sch_symbol_poses(text: str) -> dict[str, SchSymbolPose]:
    """LIVE-002: instance symbols keyed by stable Reference (skip #PWR / R?)."""
    out: dict[str, SchSymbolPose] = {}
    for pose in parse_sch_symbol_records(text):
        if _usable_refdes(pose.ref):
            out[pose.ref] = pose
    return out


def parse_sch_graphics(text: str) -> list[str]:
    """Sheet-level polyline / rectangle / image / text (not symbol properties)."""
    chunks: list[str] = []
    for kw in ("polyline", "rectangle", "image", "bezier"):
        chunks.extend(iter_top_level_blocks(text, kw))
    for block in iter_top_level_blocks(text, "text"):
        if '(property "' in block[:40]:
            continue
        chunks.append(block)
    return chunks


def parse_sch_overlay(
    text: str,
    *,
    sheet: str = "",
) -> tuple[dict[str, SchSymbolPose], dict[str, SchSymbolPose], list[SchWire], list[SchLabel], list[str]]:
    records = parse_sch_symbol_records(text)
    symbols: dict[str, SchSymbolPose] = {}
    by_uuid: dict[str, SchSymbolPose] = {}
    for pose in records:
        if pose.uuid:
            by_uuid[pose.uuid] = pose
        if _usable_refdes(pose.ref):
            symbols[pose.ref] = pose
    wires = [SchWire(*seg, sheet=sheet) for seg in parse_kicad_sch_wire_segments(text)]
    labels: list[SchLabel] = []
    for m in _LABEL_KIND_RE.finditer(text):
        kind_raw, name, x, y = m.group(1), m.group(2), float(m.group(3)), float(m.group(4))
        kind = "global" if kind_raw == "global_label" else "hierarchical" if kind_raw == "hierarchical_label" else "local"
        labels.append(SchLabel(name=name, x=x, y=y, kind=kind, sheet=sheet))
    if not labels:
        labels = [SchLabel(name=n, x=x, y=y, sheet=sheet) for n, x, y in parse_kicad_sch_net_labels(text)]
    graphics = parse_sch_graphics(text)
    return symbols, by_uuid, wires, labels, graphics


def parse_pcb_net_table(text: str) -> dict[int, str]:
    return {int(m.group(1)): m.group(2) for m in _NET_TABLE_RE.finditer(text)}


def parse_pcb_footprints(text: str) -> dict[str, FpPose]:
    """LIVE-003: footprint pose keyed by Reference."""
    out: dict[str, FpPose] = {}
    for block in iter_top_level_blocks(text, "footprint"):
        head = _FP_HEAD_RE.search(block)
        at_m = _AT_RE.search(block)
        ref_m = _REF_PROP_RE.search(block)
        if not at_m or not ref_m:
            continue
        ref = str(ref_m.group(1) or "").strip()
        if not ref or ref.startswith("#"):
            continue
        rot = float(at_m.group(3) or 0.0)
        crtyd = _courtyard_local_from_fp_block(block)
        out[ref] = FpPose(
            ref=ref,
            x=float(at_m.group(1)),
            y=float(at_m.group(2)),
            rot=rot,
            footprint=head.group(1) if head else "",
            crtyd_local=crtyd,
        )
    return out


def parse_pcb_copper(text: str, net_table: dict[int, str] | None = None) -> tuple[list[TrackSeg], list[ViaRec], list[ZoneRec]]:
    names = net_table if net_table is not None else parse_pcb_net_table(text)
    tracks = [
        TrackSeg(
            float(m.group(1)),
            float(m.group(2)),
            float(m.group(3)),
            float(m.group(4)),
            float(m.group(5)),
            m.group(6),
            names.get(int(m.group(7)), ""),
        )
        for m in _SEG_RE.finditer(text)
    ]
    vias = [
        ViaRec(
            float(m.group(1)),
            float(m.group(2)),
            float(m.group(3)),
            float(m.group(4)),
            (m.group(5), m.group(6)),
            names.get(int(m.group(7)), ""),
        )
        for m in _VIA_RE.finditer(text)
    ]
    zones: list[ZoneRec] = []
    for block in iter_top_level_blocks(text, "zone"):
        nm = _ZONE_NAME_RE.search(block)
        if nm:
            net = nm.group(1)
        else:
            num_m = _ZONE_NET_RE.search(block)
            net = names.get(int(num_m.group(1)), "") if num_m else ""
        zones.append(ZoneRec(net=net, sexp=block))
    return tracks, vias, zones


def sibling_sheet_name(project_stem: str, path: Path) -> str:
    """``board.ANALOG.kicad_sch`` → ``ANALOG``; empty if not a sibling sheet file."""
    name = path.name
    prefix = f"{project_stem}."
    suffix = ".kicad_sch"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return ""
    mid = name[len(prefix) : -len(suffix)]
    return mid if mid and "/" not in mid else ""


def load_overlay_from_dir(output_dir: str | os.PathLike[str] | None, project_name: str) -> KicadArtworkOverlay:
    """Parse saved KiCad files next to compile artifacts (before they are overwritten)."""
    overlay = KicadArtworkOverlay()
    if not project_name:
        return overlay
    base = Path(output_dir) if output_dir is not None else Path.cwd()
    sch = base / f"{project_name}.kicad_sch"
    pcb = base / f"{project_name}.kicad_pcb"
    nested = base / project_name
    if not sch.is_file() and (nested / f"{project_name}.kicad_sch").is_file():
        sch = nested / f"{project_name}.kicad_sch"
        pcb = nested / f"{project_name}.kicad_pcb"
        base = nested

    if sch.is_file():
        overlay.source_sch = str(sch)
        try:
            text = sch.read_text(encoding="utf-8")
            symbols, by_uuid, wires, labels, graphics = parse_sch_overlay(text, sheet="")
            overlay.symbols.update(symbols)
            overlay.symbols_by_uuid.update(by_uuid)
            overlay.sch_wires.extend(wires)
            overlay.sch_labels.extend(labels)
            overlay.sch_graphics.extend(graphics)
        except Exception as e:
            logger.warning("LIVE-001: could not parse schematic overlay %s: %s", sch, e)
        stem = sch.stem
        for sibling in sorted(base.glob(f"{stem}.*.kicad_sch")):
            try:
                sheet = sibling_sheet_name(stem, sibling)
                text = sibling.read_text(encoding="utf-8")
                symbols, by_uuid, wires, labels, graphics = parse_sch_overlay(text, sheet=sheet)
                overlay.symbols.update(symbols)
                overlay.symbols_by_uuid.update(by_uuid)
                overlay.sch_wires.extend(wires)
                overlay.sch_labels.extend(labels)
                overlay.sch_graphics.extend(graphics)
            except Exception as e:
                logger.debug("LIVE-001: sibling sheet %s skipped: %s", sibling, e)

    if pcb.is_file():
        overlay.source_pcb = str(pcb)
        try:
            text = pcb.read_text(encoding="utf-8")
            overlay.footprints.update(parse_pcb_footprints(text))
            overlay.tracks, overlay.vias, overlay.zones = parse_pcb_copper(text)
        except Exception as e:
            logger.warning("LIVE-001: could not parse PCB overlay %s: %s", pcb, e)
    return overlay


def overlay_files_exist(output_dir: str | os.PathLike[str] | None, project_name: str) -> bool:
    ov = KicadArtworkOverlay()
    if not project_name:
        return False
    base = Path(output_dir) if output_dir is not None else Path.cwd()
    sch = base / f"{project_name}.kicad_sch"
    pcb = base / f"{project_name}.kicad_pcb"
    nested = base / project_name
    return sch.is_file() or pcb.is_file() or (nested / f"{project_name}.kicad_sch").is_file() or (
        nested / f"{project_name}.kicad_pcb"
    ).is_file()


def attach_overlay_to_state(state) -> KicadArtworkOverlay:
    """LIVE-001/006: load overlay, stamp the board, fail-closed when keep + empty."""
    keep = bool(getattr(state, "keep_kicad_artwork", False)) or _truthy("OPENHAC_KEEP_KICAD_ARTWORK")
    regen = bool(getattr(state, "regenerate_artwork", False)) or _truthy("OPENHAC_REGENERATE_ARTWORK")
    state.keep_kicad_artwork = keep
    state.regenerate_artwork = regen
    goal = str(getattr(state, "compile_goal", "") or "").strip().lower()

    if regen:
        overlay = KicadArtworkOverlay()
        state.artwork_overlay = overlay
        try:
            setattr(state.board, "_kicad_artwork_overlay", overlay)
            setattr(state.board, "_keep_kicad_artwork", False)
            setattr(state.board, "_live_kicad_artwork", {"merged": False, "regenerate": True})
        except Exception:
            pass
        return overlay

    overlay = load_overlay_from_dir(state.output_dir, state.project_name)
    missing = not overlay.has_files() or overlay.is_empty()
    if keep and missing:
        raise OpenHaCError(
            "LIVE-006: --keep-kicad-artwork requires saved KiCad overlay files "
            f"({state.project_name}.kicad_sch and/or .kicad_pcb) with parseable artwork; "
            "got an empty overlay. Save in KiCad first, or pass --regenerate-artwork."
        )
    if keep and goal in ("fabrication", "fab") and missing:
        raise OpenHaCError("LIVE-006: fabrication + --keep-kicad-artwork refused an empty overlay.")

    overlay.merged = bool(overlay.has_files()) and not overlay.is_empty()
    state.artwork_overlay = overlay
    if overlay.merged and overlay.has_pcb_copper():
        state.auto_route = False
    if keep:
        state.auto_route = False
    try:
        setattr(state.board, "_kicad_artwork_overlay", overlay)
        setattr(state.board, "_keep_kicad_artwork", keep)
        setattr(
            state.board,
            "_live_kicad_artwork",
            {
                "schema": "openhac.kicad_artwork.v1",
                "merged": overlay.merged,
                "keep": keep,
                "regenerate": False,
                "sch": overlay.source_sch,
                "pcb": overlay.source_pcb,
                "symbol_count": len(overlay.symbols),
                "symbol_uuid_count": len(overlay.symbols_by_uuid),
                "footprint_count": len(overlay.footprints),
                "track_count": len(overlay.tracks),
            },
        )
    except Exception:
        pass
    if overlay.merged:
        logger.info(
            "LIVE: merging KiCad artwork overlay (%s refs, %s uuids, %s footprints, %s tracks)",
            len(overlay.symbols),
            len(overlay.symbols_by_uuid),
            len(overlay.footprints),
            len(overlay.tracks),
        )
    return overlay


def overlay_covers_all_footprints(overlay: KicadArtworkOverlay | None, board) -> bool:
    """LIVE-003: skip Z3 when every placeable ref already has overlay coords."""
    if overlay is None or not overlay.footprints:
        return False
    try:
        from openhac.compiler.pcb_placement import circuit_view_from_board, parse_footprint_id
    except Exception:
        return False
    try:
        circuit = circuit_view_from_board(board)
        parts = list(getattr(circuit, "parts", []) or [])
    except Exception:
        return False
    needed: list[str] = []
    for part in parts:
        if parse_footprint_id(getattr(part, "footprint", None)) is None:
            continue
        needed.append(part_ref(part))
    if not needed:
        return False
    return all(r in overlay.footprints for r in needed)


def apply_symbol_overlay(positions: dict, rotations: dict, parts: Iterable, overlay: KicadArtworkOverlay | None) -> set[str]:
    """Overwrite auto-layout xy/rot. Match UUID first (KiCad 9 may save Reference as R?)."""
    applied: set[str] = set()
    if overlay is None:
        return applied
    if not overlay.symbols and not overlay.symbols_by_uuid:
        return applied
    from openhac.schematic.kicad_links import symbol_instance_uuid

    for part in parts:
        ref = part_ref(part)
        pose = None
        try:
            uid = symbol_instance_uuid(part, 1)
        except Exception:
            uid = ""
        if uid:
            pose = overlay.symbols_by_uuid.get(uid)
        if pose is None:
            pose = overlay.symbols.get(ref)
        if pose is None:
            continue
        positions[part] = (pose.x, pose.y)
        rotations[part] = pose.rot
        applied.add(ref)
    return applied


def _dist2(ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = ax - bx, ay - by
    return dx * dx + dy * dy


def nearest_pin(
    x: float,
    y: float,
    pin_xy: dict[tuple[str, str], tuple[float, float]],
    radius_mm: float = _PIN_SNAP_MM,
) -> tuple[str, str] | None:
    best = None
    best_d = radius_mm * radius_mm
    for key, (px, py) in pin_xy.items():
        d = _dist2(x, y, px, py)
        if d <= best_d:
            best_d = d
            best = key
    return best


def _pin_xy_for_wire(
    wire: SchWire,
    pin_xy: dict[tuple[str, str], tuple[float, float]],
    pin_xy_by_sheet: dict[str, dict[tuple[str, str], tuple[float, float]]] | None,
    hierarchical: bool,
) -> dict[tuple[str, str], tuple[float, float]]:
    """Child-sheet wires live in that page's coordinates, not the packed parent canvas."""
    if hierarchical and not wire.sheet:
        return {}
    if wire.sheet and pin_xy_by_sheet is not None:
        return pin_xy_by_sheet.get(wire.sheet) or {}
    return pin_xy


def _seg_key(x1: float, y1: float, x2: float, y2: float, nd: int = 2) -> tuple:
    a = (round(x1, nd), round(y1, nd))
    b = (round(x2, nd), round(y2, nd))
    return (a, b) if a <= b else (b, a)


def ir_wire_echo_keys(ir) -> set[tuple]:
    """Canonical overlay-wire keys for segments the graph IR already emits."""
    keys: set[tuple] = set()
    children = getattr(ir, "child_sheets", None) or {}

    def harvest(obj, sheet: str) -> None:
        for w in list(getattr(obj, "wires", None) or []):
            sh = getattr(w, "sheet", None)
            if sh is None or sh == "":
                sh = sheet
            keys.add((sh, _seg_key(w.x1, w.y1, w.x2, w.y2)))

    harvest(ir, "")
    for name, child in children.items():
        harvest(child, name)
    return keys


def overlay_wire_conflicts(
    overlay: KicadArtworkOverlay,
    pin_xy: dict[tuple[str, str], tuple[float, float]],
    pin_to_net: dict[tuple[str, str], str],
    *,
    pin_xy_by_sheet: dict[str, dict[tuple[str, str], tuple[float, float]]] | None = None,
    hierarchical: bool = False,
    echo_keys: set[tuple] | None = None,
) -> list[str]:
    """LIVE-005/006: user wires whose endpoints sit on two different graph nets.

    Segments the current IR already draws (OpenHaC stubs / power-port leads) are
    not user shorts — re-ingesting last compile's ``.kicad_sch`` must not abort.
    """
    conflicts: list[str] = []
    for w in overlay.sch_wires:
        if echo_keys is not None and (w.sheet, _seg_key(w.x1, w.y1, w.x2, w.y2)) in echo_keys:
            continue
        xy = _pin_xy_for_wire(w, pin_xy, pin_xy_by_sheet, hierarchical)
        if not xy:
            continue
        a = nearest_pin(w.x1, w.y1, xy, _CONFLICT_SNAP_MM)
        b = nearest_pin(w.x2, w.y2, xy, _CONFLICT_SNAP_MM)
        if a is None or b is None:
            continue
        na, nb = pin_to_net.get(a), pin_to_net.get(b)
        if na and nb and na != nb:
            conflicts.append(
                f"LIVE-006: overlay wire shorts graph nets {na!r} and {nb!r} "
                f"({a[0]}.{a[1]} ↔ {b[0]}.{b[1]})"
            )
    return conflicts


def pin_to_net_map(nets: Iterable) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for net in nets:
        nn = net_name(net)
        for pin in sorted_net_pins(net):
            part = getattr(pin, "part", None)
            if part is None:
                continue
            out[(part_ref(part), pin_num(pin))] = nn
    return out


def merge_schematic_overlay(ir, overlay: KicadArtworkOverlay | None, nets: Iterable) -> list[str]:
    """LIVE-005: keep overlay wires/labels/graphics for nets still in the graph.

    Returns conflict messages (empty if overlay is clean). Graph IR connectivity is
    already on ``ir``; this only appends extra artwork that does not contradict it.
    """
    if overlay is None or overlay.is_empty():
        return []
    graph_nets = {net_name(n) for n in nets if net_name(n)}
    pin_to_net = pin_to_net_map(nets)
    pin_xy = dict(getattr(ir, "pin_xy", None) or {})
    children = getattr(ir, "child_sheets", None) or {}
    hierarchical = bool(children)
    pin_xy_by_sheet = {name: dict(getattr(child, "pin_xy", None) or {}) for name, child in children.items()}
    conflicts = overlay_wire_conflicts(
        overlay,
        pin_xy,
        pin_to_net,
        pin_xy_by_sheet=pin_xy_by_sheet,
        hierarchical=hierarchical,
        echo_keys=ir_wire_echo_keys(ir),
    )
    from openhac.schematic.ir import NetLabel, WireSeg

    def _target(sheet: str):
        if hierarchical and sheet and sheet in children:
            return children[sheet]
        return ir

    existing = {
        (round(w.x1, 3), round(w.y1, 3), round(w.x2, 3), round(w.y2, 3))
        for dest in [ir, *children.values()]
        for w in list(getattr(dest, "wires", None) or [])
    }
    for w in overlay.sch_wires:
        dest = _target(w.sheet)
        xy = _pin_xy_for_wire(w, pin_xy, pin_xy_by_sheet, hierarchical)
        a = nearest_pin(w.x1, w.y1, xy) if xy else None
        b = nearest_pin(w.x2, w.y2, xy) if xy else None
        net_a = pin_to_net.get(a) if a else None
        net_b = pin_to_net.get(b) if b else None
        if net_a and net_b and net_a != net_b:
            continue  # conflict; do not emit the short
        keep_net = net_a or net_b
        if keep_net is None:
            labels = [
                lb
                for lb in overlay.sch_labels
                if (not w.sheet or not getattr(lb, "sheet", "") or lb.sheet == w.sheet)
            ]
            for lb in labels:
                if lb.name not in graph_nets:
                    continue
                if _dist2(lb.x, lb.y, w.x1, w.y1) <= _PIN_SNAP_MM ** 2 or _dist2(lb.x, lb.y, w.x2, w.y2) <= _PIN_SNAP_MM ** 2:
                    keep_net = lb.name
                    break
        if keep_net is None or keep_net not in graph_nets:
            continue
        key = (round(w.x1, 3), round(w.y1, 3), round(w.x2, 3), round(w.y2, 3))
        if key in existing:
            continue
        dest.wires.append(WireSeg(w.x1, w.y1, w.x2, w.y2, net=keep_net))
        existing.add(key)

    have_labels = {
        (lb.name, round(lb.x, 3), round(lb.y, 3))
        for dest in [ir, *children.values()]
        for lb in list(getattr(dest, "labels", None) or [])
    }
    for lb in overlay.sch_labels:
        if lb.name not in graph_nets:
            continue
        dest = _target(getattr(lb, "sheet", "") or "")
        key = (lb.name, round(lb.x, 3), round(lb.y, 3))
        if key in have_labels:
            continue
        dest.labels.append(NetLabel(lb.name, lb.x, lb.y, lb.kind))
        have_labels.add(key)

    extra = list(getattr(ir, "overlay_sexp", None) or [])
    extra.extend(overlay.sch_graphics)
    ir.overlay_sexp = extra
    return conflicts


def raise_if_overlay_conflicts(conflicts: list[str]) -> None:
    if conflicts:
        raise ArtworkParityError("\n".join(conflicts))


def _fmt_num(x: float) -> str:
    s = f"{float(x):.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def format_pcb_copper(overlay: KicadArtworkOverlay, name_to_num: dict[str, int], graph_nets: set[str]) -> str:
    """LIVE-004: copper sexp for nets that still exist; drop vanished nets."""
    lines: list[str] = []
    for t in overlay.tracks:
        if t.net not in graph_nets:
            continue
        num = name_to_num.get(t.net)
        if num is None:
            continue
        lines.append(
            f'\t(segment (start {_fmt_num(t.x1)} {_fmt_num(t.y1)}) '
            f'(end {_fmt_num(t.x2)} {_fmt_num(t.y2)}) (width {_fmt_num(t.width)}) '
            f'(layer "{t.layer}") (net {num}))\n'
        )
    for v in overlay.vias:
        if v.net not in graph_nets:
            continue
        num = name_to_num.get(v.net)
        if num is None:
            continue
        lines.append(
            f'\t(via (at {_fmt_num(v.x)} {_fmt_num(v.y)}) (size {_fmt_num(v.size)}) '
            f'(drill {_fmt_num(v.drill)}) (layers "{v.layers[0]}" "{v.layers[1]}") (net {num}))\n'
        )
    for z in overlay.zones:
        if z.net not in graph_nets:
            continue
        num = name_to_num.get(z.net)
        if num is None:
            continue
        sexp = z.sexp
        sexp = _ZONE_NET_RE.sub(f"(net {num})", sexp, count=1)
        if _ZONE_NAME_RE.search(sexp):
            sexp = _ZONE_NAME_RE.sub(f'(net_name "{z.net}")', sexp, count=1)
        lines.append("\t" + sexp.strip() + "\n")
    return "".join(lines)


def splice_pcb_copper(pcb_text: str, overlay: KicadArtworkOverlay, graph_nets: Iterable[str]) -> str:
    """Insert remapped overlay copper before the closing paren of a .kicad_pcb."""
    live = {str(n) for n in graph_nets if str(n)}
    names = parse_pcb_net_table(pcb_text)
    name_to_num = {v: k for k, v in names.items() if v}
    chunk = format_pcb_copper(overlay, name_to_num, live)
    if not chunk:
        return pcb_text
    stripped = pcb_text.rstrip()
    if not stripped.endswith(")"):
        return pcb_text + "\n" + chunk
    return stripped[:-1] + chunk + ")\n"


def splice_pcb_artwork_file(pcb_path: str | os.PathLike[str], overlay: KicadArtworkOverlay | None, graph_nets: Iterable[str]) -> None:
    if overlay is None or not overlay.has_pcb_copper():
        return
    path = Path(pcb_path)
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    path.write_text(splice_pcb_copper(text, overlay, graph_nets), encoding="utf-8")


def graph_net_names_from_board(board) -> set[str]:
    names: set[str] = set()
    try:
        from openhac.compiler.pcb_placement import circuit_view_from_board

        circuit = circuit_view_from_board(board)
        for net in list(getattr(circuit, "nets", []) or []):
            n = net_name(net)
            if n:
                names.add(n)
        if names:
            return names
        for part in list(getattr(circuit, "parts", []) or []):
            pins = []
            if hasattr(part, "get_pins"):
                try:
                    pins = list(part.get_pins())
                except Exception:
                    pins = []
            if not pins:
                pins = list(getattr(part, "pins", None) or [])
                if isinstance(getattr(part, "pins", None), dict):
                    pins = list(part.pins.values())
            for pin in pins:
                n = getattr(getattr(pin, "net", None), "name", None)
                if n:
                    names.add(str(n))
    except Exception:
        pass
    return names
