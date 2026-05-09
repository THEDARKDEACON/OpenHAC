"""Module — a logical grouping of components on a PCB.

Extracted from ``base.py`` so Module and Component live in separate files.
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import TYPE_CHECKING

from openhac.core.exceptions import InterfaceNotFoundError
from openhac.core.interface import Interface

if TYPE_CHECKING:
    from openhac.core.base import Component

logger = logging.getLogger("openhac.core")


class Module:
    """A logical block (power, compute, sensors, …) that owns components."""

    def __init__(self, name=None):
        self.name = name or self.__class__.__name__
        self.components: list = []
        self.required_interfaces: dict[str, Interface] = {}
        self.optional_interfaces: dict[str, Interface] = {}
        self.width = 10.0
        self.height = 10.0
        self.placed_x = None
        self.placed_y = None
        self.schematic_layer = None

        # Physics / ERC / DRC properties
        self.max_current_draw_ma = 0.0
        self.source_current_max_ma = 0.0
        #: Optional extra draw (mA) attributed to named rails for converters / loss (PWR-002 hook).
        self.extra_input_draw_by_rail_ma: dict[str, float] = {}

    def __iter__(self):
        """Yield direct child nodes (:class:`Component` or nested :class:`Module`) for tree walks (ERC/DRC)."""
        return iter(self.components)

    def add(self, component):
        """Add a :class:`Component` or nested :class:`Module`."""
        from openhac.core.base import Component as _Comp

        self.components.append(component)
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
            except Exception:
                pass
        return component

    def add_part(self, generic_name: str, **kwargs):
        """Like ``add(Component(...))`` but passes *this* module as ``parent_module`` so board strict flags apply at construction."""
        from openhac.core.base import Component as _Comp

        c = _Comp(generic_name, parent_module=self, **kwargs)
        self.components.append(c)
        try:
            p = getattr(c, "part", None)
            if p is not None and hasattr(p, "fields") and isinstance(p.fields, dict):
                p.fields.setdefault("OpenHaC_Module", str(self.name))
                layer = getattr(self, "schematic_layer", None)
                if layer is not None:
                    p.fields["OpenHaC_Module_Layer"] = str(layer)
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
            max_w = max(w for w, _ in cell_dims)
            max_h = max(h for _, h in cell_dims)
            cols = max(1, int(math.ceil(math.sqrt(n))))
            rows = int(math.ceil(n / cols))
            pack_w = cols * max_w + max(0, cols - 1) * gap
            pack_h = rows * max_h + max(0, rows - 1) * gap
            w_pack = pack_w * pack_inflate
            h_pack = pack_h * pack_inflate
        else:
            w_pack = h_pack = 0.0

        # Legacy: total area → rectangle (often too small for row-packed parts)
        total_area_mm2 *= 1.3
        h_legacy = (total_area_mm2 / 1.2) ** 0.5
        w_legacy = h_legacy * 1.2

        w_fin = max(w_pack, w_legacy)
        h_fin = max(h_pack, h_legacy)

        self.width = max(self.width, w_fin)
        self.height = max(self.height, h_fin)

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

        If the module contains components, delegates to the first component.
        This provides backward compatibility for scripts that treat modules as parts.
        """
        if self.components:
            return self.components[0][key]
        raise AttributeError(f"Module '{self.name}' has no components to subscript.")

    def __setitem__(self, key, value):
        """Allow setting pins/properties on the module's primary component."""
        if self.components:
            self.components[0][key] = value
        else:
            raise AttributeError(f"Module '{self.name}' has no components to setitem.")
