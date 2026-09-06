"""Module — a logical grouping of components on a PCB.

Extracted from ``base.py`` so Module and Component live in separate files.
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Any, TYPE_CHECKING

from openhac.core.exceptions import InterfaceNotFoundError
from openhac.core.interface import Interface

if TYPE_CHECKING:
    from openhac.core.base import Component

logger = logging.getLogger("openhac.core")


class Module:
    """A logical block (power, compute, sensors, …) that owns components."""

    def __init__(self, name=None, *, schematic_sheet: str | None = None, schematic_flow: str | None = None):
        self.name = name or self.__class__.__name__
        self.components: list = []
        self.components_by_name: dict[str, Any] = {}
        self.required_interfaces: dict[str, Interface] = {}
        self.optional_interfaces: dict[str, Interface] = {}
        self.width = 10.0
        self.height = 10.0
        self.placed_x = None
        self.placed_y = None
        self.schematic_layer = None
        #: Optional schematic sheet name (SCH-002). When set, overrides ``OpenHaC_Module``
        #: for hierarchical sheet grouping without changing PCB placement modules.
        self.schematic_sheet: str | None = (
            str(schematic_sheet).strip() if schematic_sheet else None
        )
        flow = str(schematic_flow).strip().lower() if schematic_flow else None
        self.schematic_flow: str | None = flow or None

        # Physics / ERC / DRC properties
        self.max_current_draw_ma = 0.0
        self.source_current_max_ma = 0.0
        #: Optional extra draw (mA) attributed to named rails for converters / loss (PWR-002 hook).
        self.extra_input_draw_by_rail_ma: dict[str, float] = {}
        self.layout_zone = None

        # Placement clustering (see ``openhac.compiler.cluster_affinity``)
        self._cluster_parent: Module | None = None
        self._cluster_max_mm: float | None = None
        self._z3_skip = False
        self._placement_anchor = None
        self._placement_offset_mm = (0.0, 0.0)
        self._variants: tuple[str, ...] = ()
        self._dnp_in_variants: tuple[str, ...] = ()

    def assign_to(self, zone) -> Module:
        """Assign this module to a specific LayoutZone."""
        self.layout_zone = zone
        zone.add_member(self)
        return self

    def cluster_with(self, parent: Module, *, max_center_mm: float | None = None) -> Module:
        """Declare this module as a placement satellite of *parent* (IC + LocalCaps).

        Before Z3, ``apply_cluster_affinity`` merges this module into the parent's
        AABB (default) or adds ``constrain_distance_max``. Does not change schematic
        sheet tags unless ``schematic_sheet`` is set separately.
        """
        self._cluster_parent = parent
        self._cluster_max_mm = max_center_mm
        return self

    def keep_together(self, *others: "Module") -> "Module":
        """PLC-001: cluster *others* with this module (existing placement affinity)."""
        for o in others:
            o.cluster_with(self)
        return self

    def include_in_variants(self, *names: str) -> "Module":
        """VAR-001: this module is populated only for the named variants (others DNP)."""
        self._variants = tuple(str(n).strip() for n in names if str(n).strip())
        return self

    def dnp_in_variants(self, *names: str) -> "Module":
        """VAR-001: mark this module's parts DNP for the named variants."""
        self._dnp_in_variants = tuple(str(n).strip() for n in names if str(n).strip())
        return self

    def draws_from(self, rail: str, amp: float | None = None, *, ma: float | None = None) -> "Module":
        """PWR-010: declare current draw on a named rail (amps or milliamps)."""
        if amp is not None:
            draw_ma = float(amp) * 1000.0
        elif ma is not None:
            draw_ma = float(ma)
        else:
            raise ValueError("draws_from requires amp= or ma=")
        key = str(rail).strip()
        if not key:
            raise ValueError("draws_from requires a rail name")
        cur = self.max_current_draw_ma
        if not isinstance(cur, dict):
            self.max_current_draw_ma = {}
            cur = self.max_current_draw_ma
        cur[key] = float(cur.get(key, 0.0) or 0.0) + draw_ma
        return self

    def add_testpoint(self, net, *, footprint: str = "TestPoint:TestPoint_Pad_D1.5mm"):
        """TST-001: add a TP on *net* via the host board when available."""
        board = getattr(self, "_openhac_host_board", None)
        if board is not None and hasattr(board, "declare_testpoint"):
            return board.declare_testpoint(net, footprint=footprint)
        raise RuntimeError("Module.add_testpoint requires the module to be on a Board")

    def set_schematic_sheet(self, sheet_name: str | None) -> Module:
        """Set schematic hierarchy sheet name (``OpenHaC_SchSheet`` on child parts)."""
        self.schematic_sheet = str(sheet_name).strip() if sheet_name else None
        for item in self.components:
            try:
                p = getattr(item, "part", None) or (
                    item if hasattr(item, "fields") else None
                )
                if p is not None and hasattr(p, "fields") and isinstance(p.fields, dict):
                    if self.schematic_sheet:
                        p.fields["OpenHaC_SchSheet"] = self.schematic_sheet
                    else:
                        p.fields.pop("OpenHaC_SchSheet", None)
            except Exception:
                pass
        return self

    def nc_unused_pins(self) -> None:
        """Connect all unconnected pins in all components of this module to NC.
        
        Recursively walks child components and nested modules. Use this to 
        quickly resolve ERC 'unconnected pin' warnings for large MCU headers.
        """
        from openhac.core.base import Component
        import openhac.core.circuit
        from openhac.core.net import Net
        
        nc_net = None
        for n in getattr(openhac.core.circuit.default_circuit, "nets", []):
            if str(getattr(n, "name", "")).upper() == "NC":
                nc_net = n
                break
        if not nc_net:
            nc_net = Net("NC")
            
        for item in self.components:
            if isinstance(item, Component):
                item.nc_unused_pins()
            elif isinstance(item, Module):
                item.nc_unused_pins()
            else:
                # Handle raw Part objects - only connect truly floating, non-power pins
                pins = item.get_pins() if hasattr(item, "get_pins") else []
                for pin in pins:
                    pin_type = str(getattr(pin, "func", "") or getattr(pin, "pin_type", "")).lower()
                    if pin_type in ("pwr", "power", "pwr_out", "power_out", "gnd", "ground", "pwrin", "pwr_in"):
                        continue  # Never tie power/ground pins to NC
                    if hasattr(pin, "is_connected") and not pin.is_connected():
                        pin += nc_net
                    elif getattr(pin, "net", None) is None:
                        pin += nc_net

    def __iter__(self):
        """Yield direct child nodes (:class:`Component` or nested :class:`Module`) for tree walks (ERC/DRC)."""
        return iter(self.components)

    def add(self, component):
        """Add a :class:`Component` or nested :class:`Module`."""
        from openhac.core.base import Component as _Comp

        self.components.append(component)
        
        # [Professional Grade] Index by name or MPN for deep-path access (Module['MCU.PA1'])
        cname = getattr(component, "name", None) or getattr(component, "generic_name", None)
        if cname:
            self.components_by_name[str(cname)] = component
        
        if isinstance(component, _Comp):
            component._owning_module = self
            # Tag the underlying Part so schematic/BOM tooling can group by module.
            try:
                p = getattr(component, "part", None)
                if p is not None and hasattr(p, "fields") and isinstance(p.fields, dict):
                    p.fields.setdefault("OpenHaC_Module", str(self.name))
                    layer = getattr(self, "schematic_layer", None)
                    if layer is not None:
                        p.fields["OpenHaC_Module_Layer"] = str(layer)
                    sheet = getattr(self, "schematic_sheet", None)
                    if sheet:
                        p.fields.setdefault("OpenHaC_SchSheet", str(sheet))
            except Exception:
                pass
        elif isinstance(component, Module):
            hb = getattr(self, "_openhac_host_board", None)
            if hb is not None:
                hb._propagate_board_ref(component)
        else:
            # Allow direct Part objects to be added to modules (common in stress-test scripts).
            try:
                if hasattr(component, "fields") and isinstance(component.fields, dict):
                    component.fields.setdefault("OpenHaC_Module", str(self.name))
                    sheet = getattr(self, "schematic_sheet", None)
                    if sheet:
                        component.fields.setdefault("OpenHaC_SchSheet", str(sheet))
            except Exception:
                pass
        return component

    def add_part(self, generic_name: str, **kwargs):
        """Like ``add(Component(...))`` but passes *this* module as ``parent_module`` so board strict flags apply at construction."""
        from openhac.core.base import Component as _Comp

        c = _Comp(generic_name, parent_module=self, **kwargs)
        self.components.append(c)
        self.components_by_name[str(generic_name)] = c
        try:
            p = getattr(c, "part", None)
            if p is not None and hasattr(p, "fields") and isinstance(p.fields, dict):
                p.fields.setdefault("OpenHaC_Module", str(self.name))
                layer = getattr(self, "schematic_layer", None)
                if layer is not None:
                    p.fields["OpenHaC_Module_Layer"] = str(layer)
                sheet = getattr(self, "schematic_sheet", None)
                if sheet:
                    p.fields.setdefault("OpenHaC_SchSheet", str(sheet))
        except Exception:
            pass
        return c

    def declare_interface(self, name: str, *nets, required: bool = True, **named_nets) -> Interface:
        """Register a named Interface.

        By default interfaces are **required** and must have >=2 pins connected per net.
        Use ``required=False`` for debug/test breakouts that may remain unconnected.
        """
        iface = Interface(name, *nets, **named_nets)
        if required:
            self.required_interfaces[name] = iface
        else:
            self.optional_interfaces[name] = iface
        return iface

    # ------------------------------------------------------------------
    # Bounding-box estimation
    # ------------------------------------------------------------------

    #: Footprint dimensions (mm) keyed by regex pattern matching footprint strings.
    FOOTPRINT_SIZES: dict[str, tuple[float, float]] = {
        # QFP packages
        r'lqfp-64|qfp-64': (10.0, 10.0),
        r'lqfp-48|qfp-48': (7.0, 7.0),
        r'lqfp-32|qfp-32': (7.0, 7.0),
        r'tqfp-44|qfp-44': (10.0, 10.0),
        r'lqfp-100|qfp-100': (14.0, 14.0),
        r'lqfp-128|qfp-128': (14.0, 14.0),
        r'lqfp-144|qfp-144': (20.0, 20.0),
        # QFN packages
        r'qfn-32': (5.0, 5.0),
        r'qfn-48': (6.0, 6.0),
        r'qfn-64': (8.0, 8.0),
        # SOIC packages
        r'soic-8|so-8': (4.9, 3.9),
        r'soic-14|so-14': (8.7, 3.9),
        r'soic-16|so-16': (9.9, 3.9),
        # SOT packages
        r'sot-23-3|sot-23': (2.9, 1.6),
        r'sot-23-5': (2.9, 1.6),
        r'sot-23-6': (2.9, 1.6),
        r'sot-89': (4.5, 2.5),
        r'sot-223': (6.5, 3.5),
        # Passives
        r'0402': (1.0, 0.5),
        r'0603': (1.6, 0.8),
        r'0805': (2.0, 1.25),
        r'1206': (3.2, 1.6),
        r'1210': (3.2, 2.5),
        r'2512': (6.4, 3.2),
        # Diodes
        r'sma|do-214ac': (4.5, 2.7),
        r'smb|do-214aa': (5.3, 3.4),
        r'smc|do-214ab': (7.9, 5.3),
        r'sod-123': (3.6, 1.6),
        # Inductors
        r'l_6.3x6.3': (6.3, 6.3),
        r'l_4x4': (4.0, 4.0),
        r'l_5x5': (5.0, 5.0),
        # Connectors
        r'xt60': (16.0, 8.0),
        r'pinheader_2.54_1x4': (10.0, 2.5),
        r'pinheader_2.54_1x6': (15.0, 2.5),
        r'pinheader_2.54_2x5': (12.5, 5.0),
        r'usb': (10.0, 8.0),
        # Crystals
        r'3225': (3.2, 2.5),
        r'5032': (5.0, 3.2),
        r'7050': (7.0, 5.0),
        # Misc
        r'buzzer': (12.0, 9.5),
        r'testpoint': (2.0, 2.0),
    }

    def recalculate_bbox_from_components(self) -> None:
        """Update width/height based on actual component footprints.

        Combines (1) a **grid packing** estimate — parts are laid out in rows inside the
        module, so a single ``sqrt(sum(area))`` box under-estimates span — with (2) the
        legacy total-area heuristic. The final box is the max of both (conservative).
        """
        if not self.components:
            return

        def _dims_for_footprint_string(fp_name: str) -> tuple[float, float, float]:
            """Return ``(w_mm, h_mm, area_mm2)`` for one footprint id string."""
            for pattern, (w, h) in self.FOOTPRINT_SIZES.items():
                if re.search(pattern, fp_name):
                    wf, hf = float(w), float(h)
                    return wf, hf, wf * hf
            return 5.0, 5.0, 25.0

        cell_dims: list[tuple[float, float]] = []
        total_area_mm2 = 0.0
        for comp in self.components:
            fp_name = ""
            part = getattr(comp, "part", comp)
            if part and hasattr(part, "footprint"):
                fp_name = str(part.footprint).lower()
            w, h, a = _dims_for_footprint_string(fp_name)
            total_area_mm2 += a
            if not isinstance(comp, Module):
                cell_dims.append((w, h))

        try:
            gap = float((os.environ.get("OPENHAC_PLACEMENT_FP_GAP_MM") or "1.0").strip() or 1.0)
        except Exception:
            gap = 1.0
        try:
            pack_inflate = float((os.environ.get("OPENHAC_MODULE_PACK_INFLATE") or "1.15").strip() or 1.15)
        except Exception:
            pack_inflate = 1.15

        if cell_dims:
            n = len(cell_dims)
            cols = max(1, int(math.ceil(math.sqrt(n))))
            # Shelf-pack real cell sizes (not cols*max_w, which inflates mixed IC+passive rooms).
            cells = sorted(cell_dims, key=lambda t: (-(t[0] * t[1]), t[0]))
            x = y = 0.0
            col = 0
            row_h = 0.0
            max_r = max_b = 0.0
            for cw, ch in cells:
                max_r = max(max_r, x + cw)
                max_b = max(max_b, y + ch)
                row_h = max(row_h, ch)
                col += 1
                x += cw + gap
                if col >= cols:
                    col = 0
                    x = 0.0
                    y += row_h + gap
                    row_h = 0.0
            w_pack = max_r * pack_inflate
            h_pack = max_b * pack_inflate
        else:
            w_pack = h_pack = 0.0

        # Legacy: total area → rectangle (often too small for row-packed parts)
        total_area_mm2 *= 1.3
        h_legacy = (total_area_mm2 / 1.2) ** 0.5
        w_legacy = h_legacy * 1.2

        w_fin = max(w_pack, w_legacy)
        h_fin = max(h_pack, h_legacy)

        # Shrink-wrap: never keep a larger leftover default (Module starts at 10×10).
        self.width = w_fin
        self.height = h_fin
        self._cluster_core_wh = (self.width, self.height)

        logger.debug(
            "Module %r bbox: %.1fx%.1f mm (%s components; grid %s, legacy %.1fx%.1f)",
            self.name,
            self.width,
            self.height,
            len(self.components),
            f"{w_pack:.1f}x{h_pack:.1f}" if cell_dims else "n/a",
            w_legacy,
            h_legacy,
        )

    # ------------------------------------------------------------------
    # Interface access
    # ------------------------------------------------------------------

    def expose_interface(self, name: str) -> Interface:
        """Return the named Interface, raising InterfaceNotFoundError if absent."""
        try:
            return self.required_interfaces[name]
        except KeyError:
            try:
                return self.optional_interfaces[name]
            except KeyError:
                raise InterfaceNotFoundError(
                    f"Interface '{name}' is not registered on module '{self.name}'."
                )

    def __getitem__(self, key):
        """Allow subscripting the module to access pins of its internal components.

        Supports:
        1. Component lookup: module["U1"]
        2. Deep pin access: module["U1.1"] or module["U1.VCC"]
        3. Legacy fallback: module["1"] delegates to the first component
        """
        ks = str(key)
        
        # 1. Direct component lookup
        if ks in self.components_by_name:
            return self.components_by_name[ks]
            
        # 2. Deep path access (e.g. "U1.PA1")
        if "." in ks:
            parts = ks.split(".", 1)
            comp_key, pin_key = parts[0], parts[1]
            if comp_key in self.components_by_name:
                return self.components_by_name[comp_key][pin_key]
        
        # 3. Legacy fallback: delegate to first component
        if self.components:
            return self.components[0][key]
            
        raise AttributeError(f"Module '{self.name}' has no component or pin matching '{key}'.")

    def __setitem__(self, key, value):
        """Allow setting pins/properties on the module's components."""
        ks = str(key)
        if ks in self.components_by_name:
            self.components_by_name[ks] = value
            return
            
        if "." in ks:
            parts = ks.split(".", 1)
            comp_key, pin_key = parts[0], parts[1]
            if comp_key in self.components_by_name:
                self.components_by_name[comp_key][pin_key] = value
                return

        if self.components:
            self.components[0][key] = value
        else:
            raise AttributeError(f"Module '{self.name}' has no components to setitem.")
