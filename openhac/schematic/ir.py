"""Schematic intermediate representation (SSO-031)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SymbolInstance:
    part: object
    lib_id: str
    x: float
    y: float
    rot: float
    uuid: str
    ref: str
    value: str
    footprint: str
    sheet: str = ""
    synthesized_body: str | None = None
    unit: int = 1
    pin_nums: list[str] = field(default_factory=list)
    datasheet: str = ""
    mpn: str = ""
    manufacturer: str = ""


@dataclass
class WireSeg:
    x1: float
    y1: float
    x2: float
    y2: float
    sheet: str = ""
    net: str = ""


@dataclass
class BusSeg:
    x1: float
    y1: float
    x2: float
    y2: float
    sheet: str = ""


@dataclass
class BusEntry:
    x: float
    y: float
    dx: float = 2.54
    dy: float = 2.54
    sheet: str = ""


@dataclass
class NetLabel:
    name: str
    x: float
    y: float
    kind: str = "local"  # local | hierarchical | global
    sheet: str = ""
    owner_ref: str = ""


@dataclass
class PowerPort:
    net: str
    lib_id: str
    pin_name: str
    x: float
    y: float
    is_gnd: bool = False
    is_pwr_flag: bool = False
    sheet: str = ""


@dataclass
class NoConnect:
    x: float
    y: float
    sheet: str = ""


@dataclass
class HierPin:
    name: str
    pin_type: str
    x: float
    y: float
    rot: int = 180  # 0=right, 90=top, 180=left, 270=bottom


@dataclass
class SheetBox:
    name: str
    filename: str
    uuid: str
    x: float
    y: float
    w: float
    h: float
    pins: list[HierPin] = field(default_factory=list)


@dataclass
class SchematicIR:
    title: str = "OpenHaC"
    rev: str = "v1.0"
    company: str = ""
    instances: list[SymbolInstance] = field(default_factory=list)
    wires: list[WireSeg] = field(default_factory=list)
    buses: list[BusSeg] = field(default_factory=list)
    bus_entries: list[BusEntry] = field(default_factory=list)
    labels: list[NetLabel] = field(default_factory=list)
    power_ports: list[PowerPort] = field(default_factory=list)
    no_connects: list[NoConnect] = field(default_factory=list)
    sheets: list[SheetBox] = field(default_factory=list)
    embedded_lib_symbols: str = ""
    generated_sym_path: str | None = None
    paper: str = "A4"
    # pin world coords: (ref, pin_num) -> (x, y); KiCad pin rotation (0=right, 90=up, …)
    pin_xy: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    pin_rot: dict[tuple[str, str], float] = field(default_factory=dict)
    child_sheets: dict[str, "SchematicIR"] = field(default_factory=dict)
    # Parent-sheet only (hierarchical pin stubs / global labels).
    root_wires: list[WireSeg] = field(default_factory=list)
    root_labels: list[NetLabel] = field(default_factory=list)
