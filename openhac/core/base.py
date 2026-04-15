from __future__ import annotations

import logging
import re
import urllib.parse

from openhac.core.part import Part, Pin
from openhac.core.net import Net, Bus
from openhac.core.circuit import default_circuit
from openhac.database.db_manager import DatabaseManager
from openhac.core.compile_context import get_compile_context

logger = logging.getLogger("openhac.core")


class OpenHaCError(Exception):
    """Base exception for all OpenHaC errors."""


class SchematicGenerationError(OpenHaCError):
    """Raised by schematic_gen.py when schematic generation fails."""


class LayoutGenerationError(OpenHaCError):
    """Raised when KiCad pcbnew layout cannot be generated (e.g. bindings missing)."""


class UnconnectedInterfaceError(OpenHaCError):
    """Raised by Board.compile() when a required interface net has fewer than two pins."""


class InterfaceNotFoundError(OpenHaCError):
    """Raised by Module.expose_interface() when the named interface is not registered."""


class FreeRoutingNotFoundError(OpenHaCError):
    """Raised by autoroute_cli.py when the FreeRouting jar cannot be found."""


class AutorouterFailedError(OpenHaCError):
    """Raised by autoroute_cli.py when FreeRouting exits with a non-zero code or produces no SES output."""


class FabExportError(OpenHaCError):
    """Raised when ``kicad-cli`` fabrication export fails."""


class RiskyPartLookupError(OpenHaCError):
    """Raised when a live/JIT part mapping is low-confidence and risky lookups are disallowed (LIB-003)."""


class PartDatabaseWriteError(OpenHaCError):
    """Raised when persisting a JIT-resolved component to the local database fails."""


class KiCadCliNotFoundError(OpenHaCError):
    """Raised when ``kicad-cli`` is required but not on PATH (SCH-003 / fab export)."""


class KiCadSchErcError(OpenHaCError):
    """Raised when ``kicad-cli sch erc`` fails or reports violations (SCH-003)."""


class KicadLibraryLoadError(OpenHaCError):
    """Raised when a KiCad symbol cannot be loaded and synthetic fallback is disabled (LIB-004)."""


class Component:
    db = DatabaseManager()
    #: When False (default), :class:`RiskyPartLookupError` is raised for low-confidence JIT parts
    #: unless ``OPENHAC_ALLOW_RISKY_PARTS`` is set. Default False = strict mode requires pre-populated DB.
    allow_risky_part_lookups: bool = False
    #: When True, failure to instantiate a KiCad library symbol raises :class:`KicadLibraryLoadError`
    #: instead of creating a synthetic 99-pin stub. Default True = strict mode requires real KiCad symbols.
    require_kicad_symbols: bool = True
    #: When True (set during ``Board.compile`` / ``simulate``), medium-confidence JIT rows raise
    #: :class:`RiskyPartLookupError` unless risky lookups are explicitly allowed (LIB-003).
    strict_jit_lookups: bool = True

    @classmethod
    def _strict_kicad_from_env(cls) -> bool:
        import os

        return os.environ.get("OPENHAC_STRICT_KICAD", "").lower() in ("1", "true", "yes")

    @classmethod
    def _strict_jit_from_env(cls) -> bool:
        import os

        return os.environ.get("OPENHAC_STRICT_JIT", "").lower() in ("1", "true", "yes")

    @classmethod
    def _risky_lookups_allowed(cls) -> bool:
        import os

        ctx = get_compile_context()
        if ctx is not None and ctx.allow_risky_part_lookups:
            return True
        if cls.allow_risky_part_lookups:
            return True
        return os.environ.get("OPENHAC_ALLOW_RISKY_PARTS", "").lower() in ("1", "true", "yes")

    def _active_host_board(self):
        """Board from active compile context or module tree (:meth:`Board.add_module` / :meth:`Module.add`)."""
        ctx = get_compile_context()
        if ctx is not None:
            return ctx.board
        m = self._owning_module
        while m is not None:
            b = getattr(m, "_openhac_host_board", None)
            if b is not None:
                return b
            break
        return None

    def _effective_strict_jit_lookups(self) -> bool:
        b = self._active_host_board()
        if b is not None:
            return bool(getattr(b, "strict_jit_lookups", False))
        return bool(getattr(Component, "strict_jit_lookups", False)) or self._strict_jit_from_env()

    def _effective_require_kicad_symbols(self) -> bool:
        b = self._active_host_board()
        if b is not None:
            return bool(getattr(b, "strict_kicad", False))
        return bool(getattr(Component, "require_kicad_symbols", False)) or self._strict_kicad_from_env()

    def __init__(
        self,
        generic_name: str,
        comp_data: dict = None,
        *,
        parent_module: "Module | None" = None,
        **kwargs,
    ):
        self.generic_name = generic_name
        #: Set by :meth:`Module.add` / :meth:`Module.add_part`, or pass ``parent_module=`` so host
        #: :class:`~openhac.core.board.Board` strict flags apply during construction (LIB-003/004).
        self._owning_module: Module | None = parent_module

        if comp_data is None:
            comp_data = self.db.get_component(generic_name)
            if not comp_data:
                comp_data = self._live_lookup(generic_name)
            if not comp_data:
                raise ValueError(
                    f"Component '{generic_name}' not found in database or LCSC catalog. "
                    f"Run sync_catalog() to refresh the component database, or check the part name."
                )

        from openhac.database.lookup_meta import (
            confidence_numeric,
            get_lookup_confidence,
            is_low_confidence,
            is_medium_confidence,
            strip_openhac_internal_fields,
        )

        conf = get_lookup_confidence(comp_data)
        jit_score = confidence_numeric(conf)
        strict_jit = self._effective_strict_jit_lookups()
        if strict_jit and is_medium_confidence(conf) and not self._risky_lookups_allowed():
            raise RiskyPartLookupError(
                f"Component {generic_name!r} was resolved via a medium-confidence live lookup. "
                f"Pre-populate the database, disable Board.strict_jit_lookups, or use --allow-risky-parts / "
                f"OPENHAC_ALLOW_RISKY_PARTS=1 (LIB-003 strict JIT)."
            )

        if is_low_confidence(conf) and not self._risky_lookups_allowed():
            raise RiskyPartLookupError(
                f"Component {generic_name!r} was resolved via a low-confidence live lookup "
                f"(KiCad symbol/footprint may be wrong). Pre-populate the database (seed/sync), "
                f"or use `openhac compile --allow-risky-parts`, or set OPENHAC_ALLOW_RISKY_PARTS=1."
            )

        comp_data = strip_openhac_internal_fields(comp_data)

        # Get pinout from database or fetch from vendor APIs
        pins = self._get_pins_from_data(comp_data)
        
        # Get or generate reference designator
        ref_prefix = self._get_refdes_prefix(comp_data['category'])
        refdes = kwargs.get('refdes') or default_circuit.auto_generate_refdes(ref_prefix)
        
        self.part = Part(
            refdes=refdes,
            footprint=comp_data['kicad_footprint'],
            fields={},
            pins=pins,
            value=generic_name,
        )
        
        # Add part to the default circuit
        default_circuit.add_part(self.part)

        # Set fields on the native Part
        self.part.fields['Manufacturer'] = comp_data['manufacturer'] or ""
        self.part.fields['MPN'] = comp_data['mpn']
        self.part.fields['Supplier_SKU'] = comp_data['supplier_sku'] or ""
        self.part.fields['Value'] = generic_name
        self.part.fields['kiCad_symbol'] = comp_data['kicad_symbol']
        jc = comp_data.get("jlc_class")
        self.part.fields["JLC_Class"] = str(jc) if jc is not None else ""
        self.part.fields["Mouser_SKU"] = comp_data.get("mouser_sku") or ""
        self.part.fields["DigiKey_SKU"] = comp_data.get("digikey_sku") or ""
        si = comp_data.get("spice_include")
        self.part.fields["Spice_Include"] = str(si).strip() if si else ""
        ss = comp_data.get("spice_subckt")
        self.part.fields["Spice_Subckt"] = str(ss).strip() if ss else ""
        self.part.fields["OpenHaC_JIT_Confidence"] = conf
        self.part.fields["OpenHaC_JIT_Score"] = f"{jit_score:.2f}"

        alt_parts: list[str] = []
        alt_notes: list[str] = []
        alt_group_ids: list[str] = []
        for a in self.db.list_part_alternates(generic_name):
            sku = (a.get("alternate_supplier_sku") or "").strip()
            mpn = (a.get("alternate_mpn") or "").strip()
            if sku or mpn:
                alt_parts.append(f"{sku or '?'}:{mpn or '?'}")
            note = (a.get("note") or "").strip()
            if note:
                alt_notes.append(note)
            gid = (a.get("alternate_group_id") or "").strip()
            if gid and gid not in alt_group_ids:
                alt_group_ids.append(gid)
        self.part.fields["Alternate_SKUs"] = "; ".join(alt_parts)
        self.part.fields["Alternate_Notes"] = " | ".join(alt_notes)
        self.part.fields["Alternate_Group_ID"] = "; ".join(alt_group_ids)
        alt_rows = self.db.list_part_alternates(generic_name)
        alt_line_count = sum(
            1
            for a in alt_rows
            if (str(a.get("alternate_supplier_sku") or "").strip() or str(a.get("alternate_mpn") or "").strip())
        )
        self.part.fields["Alternate_Count"] = str(alt_line_count)

        offer_bits: list[str] = []
        for row in self.db.list_part_offers(generic_name):
            sup = (row.get("supplier") or "").strip()
            if not sup:
                continue
            sku = (row.get("supplier_sku") or "").strip()
            mpn = (row.get("mpn") or "").strip()
            token = sku or mpn
            if not token:
                continue
            rk = int(row.get("rank") or 0)
            offer_bits.append((rk, f"{sup}:{token}"))
        offer_bits.sort(key=lambda x: (x[0], x[1]))
        self.part.fields["Ranked_Offers"] = "; ".join(s for _, s in offer_bits)
        self.part.fields["Primary_Offer"] = offer_bits[0][1] if offer_bits else ""
        self.part.fields["Secondary_Offer"] = offer_bits[1][1] if len(offer_bits) > 1 else ""
        self.part.fields["Offer_Count"] = str(len(offer_bits))

    @classmethod
    def _live_lookup(cls, generic_name: str) -> dict | None:
        """Attempt to find a component by searching the LCSC/jlcsearch API directly.

        Searches by the generic_name as a query string. If a match is found,
        caches it in the local database and returns the component dict.
        Returns None if no match found or network unavailable.
        """
        import urllib.request
        import json
        import warnings

        from openhac.version_info import user_agent

        API_BASE = "https://jlcsearch.tscircuit.com"
        HEADERS = {"User-Agent": user_agent(), "Accept": "application/json"}

        # Try the generic components search endpoint
        query = urllib.parse.quote(generic_name)
        url = f"{API_BASE}/components/list.json?search={query}&limit=5&full=true"

        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            items = data.get("components", [])
        except Exception:
            # Network unavailable or API error — fail silently, caller will raise
            return None

        if not items:
            return None

        from openhac.database.api_fallback import _query_matches_item
        from openhac.database.lookup_meta import CONFIDENCE_LOW, LOOKUP_CONFIDENCE_KEY

        best = None
        for item in items:
            if _query_matches_item(generic_name, item):
                best = item
                break
        if best is None:
            best = items[0]

        lcsc = best.get("lcsc", "")
        mpn = best.get("mfr") or str(lcsc)
        package = best.get("package") or ""
        description = best.get("description") or ""

        # Build a minimal component record — use generic KiCad symbol/footprint
        # since we don't know the exact category
        comp_data = {
            "generic_name":    generic_name,
            "kicad_symbol":    "Device:Q",   # generic fallback
            "kicad_footprint": f"Package_TO_SOT_SMD:{package}" if package else "Package_TO_SOT_SMD:SOT-23",
            "manufacturer":    "",
            "mpn":             mpn,
            "supplier_sku":    f"C{lcsc}" if lcsc else "",
            "description":     description,
            "category":        "live_lookup",
            "attributes_json": json.dumps({k: v for k, v in best.items() if k not in ("lcsc", "mfr", "description", "package")}),
            LOOKUP_CONFIDENCE_KEY: CONFIDENCE_LOW,
        }

        # Cache it so subsequent lookups are instant
        warnings.warn(
            f"Component '{generic_name}' was not in the local database. "
            f"Found via live LCSC lookup (SKU: C{lcsc}). "
            f"Run sync_catalog() to pre-populate the database.",
            UserWarning,
            stacklevel=4,
        )
        try:
            cls.db.insert_component(comp_data, ignore_duplicate=True)
        except Exception as e:
            logger.exception("Failed to cache live lookup for %r", generic_name)
            raise PartDatabaseWriteError(
                f"Could not store JIT-resolved component {generic_name!r} in the local database."
            ) from e

        return comp_data

    def __getattr__(self, name):
        return getattr(self.part, name)

    def __getitem__(self, key):
        import inspect
        import warnings
        owning_module = object.__getattribute__(self, '_owning_module')
        if owning_module is not None:
            # Check whether the caller is inside the owning module's __init__
            frame = inspect.currentframe()
            try:
                caller_frame = frame.f_back
                caller_self = caller_frame.f_locals.get('self')
                caller_func = caller_frame.f_code.co_name
                if not (caller_self is owning_module and caller_func == '__init__'):
                    warnings.warn(
                        f"Direct pin access via raw pin number is deprecated. "
                        f"Use named interfaces via expose_interface() instead.",
                        DeprecationWarning,
                        stacklevel=2,
                    )
            finally:
                del frame

        # Dynamic pin creation for synthetic parts (Demo mode / Headless CI)
        from openhac.core.part import Pin
        
        # Handle multi-pin requests (tuples or lists)
        if isinstance(key, (tuple, list)):
            pins = []
            for k in key:
                p = self.__getitem__(k)
                if isinstance(p, list):
                    pins.extend(p)
                elif p:
                    pins.append(p)
            return pins

        res = self.part[key]
        if res is None or (isinstance(res, list) and not res):
             if getattr(self, '_is_synthetic', False):
                 # Duck-type: if key is a string like 'VDD', it's a name. 
                 # If it's a number, it's a pin number.
                 pin_num = key if str(key).isdigit() else str(len(self.part.pins) + 1)
                 new_pin = Pin(num=pin_num, name=str(key), part=self.part)
                 self.part.add_pins(new_pin)
                 return self.part[key]
        return res

    def __setitem__(self, key, value):
        self.part[key] = value

    def _get_pins_from_data(self, comp_data: dict) -> list[Pin]:
        """Get pinout from database or fetch from vendor APIs.
        
        First checks the database pinout_json field. If not available,
        attempts to fetch from Digi-Key/Mouser/TME APIs.
        Falls back to generic pin generation based on footprint.
        """
        import json
        
        # Try database pinout first
        pinout_json = comp_data.get("pinout_json")
        if pinout_json:
            try:
                pinout = json.loads(pinout_json)
                return [Pin(p["num"], p["name"], p.get("type", "bidirectional")) for p in pinout]
            except (json.JSONDecodeError, KeyError):
                pass  # Fall through to vendor lookup
        
        # Try to fetch from vendor APIs using MPN
        mpn = comp_data.get("mpn")
        if mpn:
            pins = self._fetch_pinout_from_vendors(mpn)
            if pins:
                return pins
        
        # Fallback: generate based on footprint
        return self._generate_fallback_pins(comp_data)
    
    def _fetch_pinout_from_vendors(self, mpn: str) -> list[Pin]:
        """Fetch pinout from vendor APIs (Digi-Key, Mouser, TME).
        
        Returns list of Pins if successful, empty list otherwise.
        """
        # TODO: Implement vendor API pinout fetching
        # This requires extending vendor_apis.py to get pinout data
        return []
    
    def _generate_fallback_pins(self, comp_data: dict) -> list[Pin]:
        """Generate generic pins based on footprint as last resort."""
        footprint = comp_data.get("kicad_footprint", "").lower()
        
        # Extract pin count from common footprints
        import re
        
        # SOIC/SOP packages
        match = re.search(r'so(?:ic|-)?(?:\D+)?(\d+)', footprint)
        if match:
            count = int(match.group(1))
            return [Pin(str(i), str(i), "bidirectional") for i in range(1, count + 1)]
        
        # QFN/QFP packages
        match = re.search(r'q(?:fn|fp)-?(?:\D+)?(\d+)', footprint)
        if match:
            count = int(match.group(1))
            return [Pin(str(i), str(i), "bidirectional") for i in range(1, count + 1)]
        
        # Passive components (resistors, capacitors, inductors, LEDs, diodes)
        if any(x in footprint for x in ['_r_', '_c_', '_l_', 'led_', 'd_']):
            return [Pin("1", "1", "passive"), Pin("2", "2", "passive")]
        
        # Default: 8 pins
        return [Pin(str(i), str(i), "bidirectional") for i in range(1, 9)]

    def _get_refdes_prefix(self, category: str) -> str:
        """Get reference designator prefix based on component category."""
        category_map = {
            "resistor": "R",
            "capacitor": "C",
            "inductor": "L",
            "led": "D",
            "diode": "D",
            "transistor": "Q",
            "mosfet": "Q",
            "ic": "U",
            "mcu": "U",
            "microcontroller": "U",
            "connector": "J",
            "header": "J",
            "crystal": "X",
            "switch": "S",
            "button": "S",
            "relay": "K",
            "fuse": "F",
            "transformer": "T",
        }
        
        cat_lower = category.lower()
        for key, prefix in category_map.items():
            if key in cat_lower:
                return prefix
        return "U"  # Default to IC prefix

class Interface:
    def __init__(self, name: str, *signals):
        self.name = name
        self.signals = list(signals)

    def connect(self, other_interface):
        for sig1, sig2 in zip(self.signals, other_interface.signals):
            sig1 += sig2

class Module:
    def __init__(self, name=None):
        self.name = name or self.__class__.__name__
        self.components = []
        self.required_interfaces: dict[str, "Interface"] = {}
        self.width = 10.0
        self.height = 10.0
        self.placed_x = None
        self.placed_y = None

        # Physics / ERC / DRC properties
        self.max_current_draw_ma = 0.0
        self.source_current_max_ma = 0.0
        #: Optional extra draw (mA) attributed to named rails for converters / loss (PWR-002 hook).
        self.extra_input_draw_by_rail_ma: dict[str, float] = {}

    def __iter__(self):
        """Yield direct child nodes (:class:`Component` or nested :class:`Module`) for tree walks (ERC/DRC)."""
        return iter(self.components)

    def add(self, component):
        self.components.append(component)
        if isinstance(component, Component):
            component._owning_module = self
            # Tag the underlying SKiDL part so schematic/BOM tooling can group by module.
            try:
                p = getattr(component, "part", None)
                if p is not None and hasattr(p, "fields") and isinstance(p.fields, dict):
                    p.fields.setdefault("OpenHaC_Module", str(self.name))
            except Exception:
                pass
        elif isinstance(component, Module):
            hb = getattr(self, "_openhac_host_board", None)
            if hb is not None:
                hb._propagate_board_ref(component)
        else:
            # Allow direct SKiDL Parts to be added to modules (common in stress-test scripts).
            try:
                if hasattr(component, "fields") and isinstance(component.fields, dict):
                    component.fields.setdefault("OpenHaC_Module", str(self.name))
            except Exception:
                pass
        return component

    def add_part(self, generic_name: str, **kwargs):
        """Like ``add(Component(...))`` but passes *this* module as ``parent_module`` so board strict flags apply at construction."""
        c = Component(generic_name, parent_module=self, **kwargs)
        self.components.append(c)
        try:
            p = getattr(c, "part", None)
            if p is not None and hasattr(p, "fields") and isinstance(p.fields, dict):
                p.fields.setdefault("OpenHaC_Module", str(self.name))
        except Exception:
            pass
        return c

    def declare_interface(self, name: str, *nets) -> "Interface":
        """Register a named Interface as a required connection point."""
        iface = Interface(name, *nets)
        self.required_interfaces[name] = iface
        return iface

    def recalculate_bbox_from_components(self) -> None:
        """Update width/height based on actual component footprints.

        Uses heuristics based on common package names to estimate area requirements.
        Adds margin for component spacing and routing.
        """
        if not self.components:
            return

        total_area_mm2 = 0.0
        footprint_sizes = {
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

        for comp in self.components:
            fp_name = ""
            part = getattr(comp, 'part', comp)  # Handle both Component and Part
            if part and hasattr(part, 'footprint'):
                fp_name = str(part.footprint).lower()

            # Find matching footprint size
            matched = False
            for pattern, (w, h) in footprint_sizes.items():
                if re.search(pattern, fp_name):
                    total_area_mm2 += w * h
                    matched = True
                    break

            if not matched:
                # Default estimate: 5x5mm for unknown components
                total_area_mm2 += 25.0

        # Add spacing margin (30% extra area for component spacing and routing)
        total_area_mm2 *= 1.3

        # Convert to roughly rectangular bbox with 1.2:1 aspect ratio
        # side = sqrt(area / 1.2) for height, 1.2*side for width
        h = (total_area_mm2 / 1.2) ** 0.5
        w = h * 1.2

        # Update with minimum bounds
        self.width = max(self.width, w)
        self.height = max(self.height, h)

        logger.debug(f"Module '{self.name}' bbox: {self.width:.1f}x{self.height:.1f}mm from {len(self.components)} components")

    def expose_interface(self, name: str) -> "Interface":
        """Return the named Interface, raising InterfaceNotFoundError if absent."""
        try:
            return self.required_interfaces[name]
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
