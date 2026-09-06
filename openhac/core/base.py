"""OpenHaC core base module.

Historically this file contained *everything* — exceptions, Component, Module,
Interface.  The heavy classes have been extracted into submodules; this file
re-exports them so ``from openhac.core.base import X`` continues to work.
"""
from __future__ import annotations

import logging
import re
import urllib.parse

from openhac.core.part import Part, Pin
from openhac.core.net import Net, Bus
import openhac.core.circuit
from openhac.database.db_manager import DatabaseManager
from openhac.core.compile_context import get_compile_context

# --- Re-exports from extracted submodules (backward compat) ---
from openhac.core.exceptions import (          # noqa: F401
    OpenHaCError,
    SchematicGenerationError,
    ArtworkParityError,
    LayoutGenerationError,
    UnconnectedInterfaceError,
    InterfaceNotFoundError,
    FreeRoutingNotFoundError,
    AutorouterFailedError,
    FabExportError,
    RiskyPartLookupError,
    PartDatabaseWriteError,
    KiCadCliNotFoundError,
    KiCadSchErcError,
    KicadLibraryLoadError,
    CatalogLockError,
    PlacementIntentError,
    PinoutAuthoringError,
    JlcExportError,
)
from openhac.core.interface import Interface   # noqa: F401
from openhac.core.module import Module         # noqa: F401
from openhac.core.refdes import (
    component_pin_access_aliases as _component_pin_access_aliases,  # noqa: F401
    get_refdes_prefix,
)

logger = logging.getLogger("openhac.core")

# Best-effort compile post-report capture (dev/handoff diagnostics).
_IMPLICIT_PIN_EVENTS: list[dict] = []


# (Exceptions and _component_pin_access_aliases now imported from submodules above.)


class _SharedCatalogDb:
    """PERF-002: one SQLite connection per catalog path; follows live ``OPENHAC_DB_PATH``."""

    def __get__(self, obj, objtype=None):
        return DatabaseManager()


class Component:
    db = _SharedCatalogDb()
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
        comp_data: dict | None = None,
        *,
        parent_module: "Module | None" = None,
        pins: dict | None = None,
        **kwargs,
    ):
        """Initialize a Component.
        
        Args:
            generic_name: Component identifier (e.g., "BUCK_TPS63001DRCR" or "C28060")
            comp_data: Optional pre-fetched component data from database
            parent_module: Owning module for strict flag inheritance
            pins: Optional explicit pin definitions dict:
                  {pin_number: ("pin_name", "pin_type"), ...}
                  pin_type can be: "power_in", "power_out", "input", "output", 
                  "bidirectional", "ground", "no_connect"
            **kwargs: Additional arguments (refdes, etc.)
        
        Examples:
            # Simple component - pins from database or package template
            r = Component("C21190")
            
            # Complex component with explicit pin definition
            buck = Component("C28060", pins={
                1: ("VIN", "power_in"),
                2: ("GND", "ground"),
                3: ("SW", "bidirectional"),
                4: ("VOUT", "power_out"),
                5: ("EN", "input"),
                6: ("FB", "input"),
                7: ("PG", "output"),
                8: ("PGND", "ground"),
                9: ("NC", "no_connect"),
                10: ("EP", "ground"),
            })
        """
        self.generic_name = generic_name
        #: Set by :meth:`Module.add` / :meth:`Module.add_part`, or pass ``parent_module=`` so host
        #: :class:`~openhac.core.board.Board` strict flags apply during construction (LIB-003/004).
        self._owning_module: Module | None = parent_module
        
        # Store explicit pin definitions for later use
        self._explicit_pins = pins

        if comp_data is None:
            comp_data = self.db.get_component(generic_name)
            if not comp_data:
                comp_data = self._live_lookup(generic_name)
            if not comp_data:
                # Try to dynamically infer pin count from standard naming conventions
                if not pins:
                    import re
                    match = re.search(r"(\d+)PIN", generic_name.upper())
                    if match:
                        pin_count = int(match.group(1))
                        pins = {str(i): (f"P{i}", "passive") for i in range(1, pin_count + 1)}

                # If pins provided explicitly or inferred, create minimal component record
                if pins:
                    comp_data = self._create_from_explicit_pins(generic_name, pins)
                else:
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
        # Keep a copy for later (e.g. pinout coverage / implicit pin policy).
        self._comp_data = dict(comp_data)

        # Get pinout from database (best-effort auto-enrich if missing and network allowed).
        pin_objs = self._get_pins_from_data(comp_data) 
        # Get or generate reference designator
        ref_prefix = self._get_refdes_prefix(
            comp_data.get("category"),
            generic_name=generic_name,
            mpn=comp_data.get("mpn"),
        )
        import openhac.core.circuit
        refdes = kwargs.get('refdes') or openhac.core.circuit.default_circuit.auto_generate_refdes(ref_prefix)
        
        footprint = str(kwargs.get("footprint") or comp_data.get("kicad_footprint") or "")
        
        try:
            self.part = Part(
                refdes=refdes,
                footprint=footprint,
                fields={},
                pins=list(pin_objs or []),
                value=generic_name,
            )
        except Exception as e:
            if self._effective_require_kicad_symbols():
                raise KicadLibraryLoadError(f"strict KiCad check failed: {e}") from e
            raise
        
        # Add part to the default circuit
        openhac.core.circuit.default_circuit.add_part(self.part)

        # Stamp constructor catalog fields onto the part before DB refresh
        # (refresh no-ops when the generic_name is not in the database).
        ks = str(comp_data.get("kicad_symbol") or "").strip()
        if ks:
            self.part.fields["kicad_symbol"] = ks
            self.part.fields["kiCad_symbol"] = ks
        if not getattr(self.part, "kicad_symbol", None):
            try:
                setattr(self.part, "kicad_symbol", ks)
            except Exception:
                pass

        self._stamp_catalog_fields(self._comp_data)

        self.layout_zone = None

        si = comp_data.get("spice_include")
        self.part.fields["Spice_Include"] = str(si).strip() if si else ""
        ss = comp_data.get("spice_subckt")
        self.part.fields["Spice_Subckt"] = str(ss).strip() if ss else ""
        desc = str(comp_data.get("description") or "").strip()
        if desc:
            self.part.fields["Description"] = desc
        self.part.fields["OpenHaC_JIT_Confidence"] = conf
        self.part.fields["OpenHaC_JIT_Score"] = f"{jit_score:.2f}"

        alt_rows = list(self.db.list_part_alternates(generic_name))
        alt_parts: list[str] = []
        alt_notes: list[str] = []
        alt_group_ids: list[str] = []
        for a in alt_rows:
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
        alt_line_count = sum(
            1
            for a in alt_rows
            if (str(a.get("alternate_supplier_sku") or "").strip() or str(a.get("alternate_mpn") or "").strip())
        )
        self.part.fields["Alternate_Count"] = str(alt_line_count)

        offer_bits: list[tuple[int, str]] = []
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
        import urllib.parse
        import urllib.request
        import json
        import warnings

        from openhac.version_info import user_agent

        # ABC-016: respect network policy (FAB-010)
        try:
            from openhac.database.enrich import network_allowed

            if not network_allowed():
                return None
        except Exception:
            pass

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
        from openhac.database.passive_ratings import enrich_comp_data_from_jlc_item

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

        # Prefer stock KiCad FP + ratings (ABC-017/018/019)
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
        enrich_comp_data_from_jlc_item(comp_data, best)

        # Cache it so subsequent lookups are instant
        warnings.warn(
            f"Component '{generic_name}' was not in the local database. "
            f"Found via live LCSC lookup (SKU: C{lcsc}). "
            f"Run sync_catalog() to pre-populate the database.",
            UserWarning,
            stacklevel=4,
        )
        try:
            cls.db.insert_component(
                comp_data,
                ignore_duplicate=True,
            )
        except Exception as e:
            msg = (
                f"Could not store JIT-resolved component {generic_name!r} in the local database."
            )
            import os

            goal = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
            strict_db = (os.environ.get("OPENHAC_STRICT_DB_WRITES") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            if goal in ("fabrication", "fab") or strict_db:
                logger.exception("Failed to cache live lookup for %r", generic_name)
                raise PartDatabaseWriteError(msg) from e
            logger.warning("%s (%s)", msg, e)
            warnings.warn(msg, UserWarning, stacklevel=4)

        return comp_data

    def __getattr__(self, name):
        return getattr(self.part, name)

    def dnp_in_variants(self, *names: str):
        """VAR-001: this part is DNP for the named board variants."""
        self._dnp_in_variants = tuple(str(n).strip() for n in names if str(n).strip())
        return self

    def __getitem__(self, key):
        import inspect
        import os
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

        try:
            return self.part[key if isinstance(key, str) else str(key)]
        except KeyError:
            key_s = str(key)
            for alt in _component_pin_access_aliases(key_s):
                try:
                    return self.part[alt]
                except KeyError:
                    continue
            # Best-effort: if pinout is missing, try to enrich and refresh pins once before
            # falling back to implicit pins (handoff/dev only).
            try:
                if not getattr(self, "_enrich_on_getitem_attempted", False):
                    setattr(self, "_enrich_on_getitem_attempted", True)
                    from openhac.database.enrich import enrich_component_in_db

                    res = enrich_component_in_db(db=self.db, generic_name=str(getattr(self, "generic_name", "") or ""))
                    if res.attempted and res.updated:
                        fresh = self.db.get_component(str(getattr(self, "generic_name", "") or ""))
                        if fresh:
                            try:
                                new_pins = self._get_pins_from_data(dict(fresh))
                                # Replace pins mapping with enriched pins (best-effort).
                                try:
                                    self.part.pins.clear()
                                except Exception:
                                    self.part.pins = {}
                                for p in new_pins:
                                    try:
                                        self.part.add_pin(p)
                                    except Exception:
                                        pass
                                try:
                                    return self.part[key_s]
                                except KeyError:
                                    for alt in _component_pin_access_aliases(key_s):
                                        try:
                                            return self.part[alt]
                                        except KeyError:
                                            continue
                            except Exception:
                                pass
            except Exception:
                pass

            # Optional implicit pin creation for designs that use named pins but
            # do not yet have explicit pinout_json coverage in the DB.
            if (os.environ.get("OPENHAC_SCHEMATIC_STRICT") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            ):
                raise
            raw_allow = (os.environ.get("OPENHAC_ALLOW_IMPLICIT_PINS") or "").strip().lower()
            raw_goal = (os.environ.get("OPENHAC_COMPILE_GOAL") or "").strip().lower()
            # Defaults:
            # - fabrication: implicit pins are OFF unless explicitly enabled
            # - handoff/unspecified: implicit pins are ON unless explicitly disabled
            allow_explicit = raw_allow in ("1", "true", "yes", "on")
            deny_explicit = raw_allow in ("0", "false", "no", "off")
            in_fabrication = raw_goal == "fabrication"
            allow_implicit = allow_explicit or (not deny_explicit and not in_fabrication)
            pinout_json = None
            symbol_data = None
            try:
                cd = getattr(self, "_comp_data", None) or {}
                pinout_json = cd.get("pinout_json")
                symbol_data = cd.get("symbol_data")
            except Exception:
                pinout_json = None
                symbol_data = None
            if not allow_implicit or pinout_json or symbol_data:
                raise

            warnings.warn(
                f"Implicit pin {key!r} created on component {getattr(self, 'generic_name', '?')!r} "
                "(no pinout_json/symbol_data in DB). This is allowed only for dev/handoff; "
                "fix by enriching pinouts via `python3 -m openhac.database.sync_jlc --seed-file ...` "
                "(or vendor lookup enrichment).",
                UserWarning,
                stacklevel=2,
            )

            try:
                _IMPLICIT_PIN_EVENTS.append(
                    {
                        "generic_name": str(getattr(self, "generic_name", "") or ""),
                        "refdes": str(getattr(self.part, "refdes", "") or ""),
                        "pin_name": str(key),
                    }
                )
            except Exception:
                pass

            # Bind a new pin. Prefer ``number == name`` for non-numeric keys so PCB pad
            # matching can use KiCad pad names (implicit pins used wrong auto-incrementing
            # numbers like 224 that never exist on the footprint).
            key_s = str(key)
            if key_s.isdigit():
                used_nums = {k for k in self.part.pins.keys() if str(k).isdigit()}
                n = 1
                while str(n) in used_nums:
                    n += 1
                new_pin = Pin(str(n), key_s, "bidirectional")
            else:
                new_pin = Pin(key_s, key_s, "bidirectional")
            self.part.add_pin(new_pin)
            return self.part[key_s]

    def __setitem__(self, key, value):
        """Connect ``value`` to pin ``key``, resolving the same aliases as :meth:`__getitem__`.

        Python rewrites ``comp[alias] += net`` as getitem → iadd(pin, net) → setitem(alias, pin).
        The final store must not require ``alias`` to exist on the underlying :class:`Part`
        when ``alias`` only maps to a canonical symbol pin (e.g. ``PH0_OSC_IN`` → ``PH0``).
        """
        from openhac.core.part import Pin as PinType

        if isinstance(value, PinType):
            return
        pin = self.__getitem__(key)
        pin += value

    def _get_pins_from_data(self, comp_data: dict) -> list[Pin]:
        """Get pinout via :func:`openhac.core.pin_resolution.get_pins_from_data` (FAB-001)."""
        from openhac.core.pin_resolution import get_pins_from_data

        return get_pins_from_data(
            comp_data,
            explicit_pins=getattr(self, "_explicit_pins", None),
        )
    
    def _pins_from_explicit(self, pins: dict) -> list[Pin]:
        """Convert explicit pin definitions to Pin objects."""
        result = []
        for num, info in pins.items():
            if isinstance(info, tuple):
                name, pin_type = info
                result.append(Pin(str(num), name, pin_type))
            else:
                # Simple string name
                result.append(Pin(str(num), info, "bidirectional"))
        return result
    
    def _get_package_template_pins(self, package: str, category: str) -> list[Pin] | None:
        """Get pins from package templates for standard packages."""
        from openhac.templates.packages import get_package_template
        return get_package_template(package, category)
    
    def _generate_generic_pins(self, comp_data: dict) -> list[Pin]:
        """Generate generic numbered pins as fallback."""
        # Try to determine pin count from package
        package = comp_data.get("package", "")
        pin_count = self._estimate_pin_count(package)
        return [Pin(str(i), f"Pin_{i}", "bidirectional") for i in range(1, pin_count + 1)]
    
    def _estimate_pin_count(self, package: str) -> int:
        """Estimate number of pins from package name."""
        if not package:
            return 2
        import re
        # Try to extract pin count from package name (e.g., "QFN-10", "SOIC-8", "CB-2-3")
        if '-' in str(package):
            parts = package.split('-')
            nums = []
            for p in parts:
                m = re.search(r'(\d+)', p)
                if m:
                    nums.append(int(m.group(1)))
            if len(nums) > 1:
                # For CB-2-3 or similar, sum the parts
                return sum(nums)
            elif nums:
                return nums[0]
        
        match = re.search(r'(\d+)', str(package))
        if match:
            return int(match.group(1))
        # Default guesses based on package type
        pkg = str(package).upper()
        if any(x in pkg for x in ['SOT-23', 'SOT23']):
            return 3
        if any(x in pkg for x in ['SOT-223', 'SOT223']):
            return 4
        if any(x in pkg for x in ['0805', '0603', '0402', '1206']):
            return 2
        return 8  # Default
    
    def _create_from_explicit_pins(self, generic_name: str, pins: dict) -> dict:
        """Create minimal component data from explicit pin definitions."""
        import json
        
        # Build pinout_json
        pinout = [{"num": str(k), "name": v[0] if isinstance(v, tuple) else v, 
                   "type": v[1] if isinstance(v, tuple) else "bidirectional"}
                  for k, v in pins.items()]
        
        # Infer package from pin count
        pin_count = len(pins)
        package = self._infer_package(pin_count)
        
        from openhac.core.pin_resolution import _fallback_footprint
        comp_data = {
            "generic_name": generic_name,
            "mpn": generic_name.split("_")[-1] if "_" in generic_name else generic_name,
            "manufacturer": "",
            "description": f"User-defined component with {pin_count} pins",
            "category": "unknown",
            "package": package,
            "kicad_symbol": "Device:IC_Generic",
            "kicad_footprint": _fallback_footprint(pin_count),
            "pinout_json": json.dumps(pinout),
        }
        
        # Store in database for reuse
        try:
            self.db.insert_component(comp_data, ignore_duplicate=True)
            logger.info(f"Created component '{generic_name}' with {pin_count} explicit pins")
        except Exception as e:
            logger.warning(f"Could not cache component '{generic_name}': {e}")
        
        return comp_data
    
    def _infer_package(self, pin_count: int) -> str:
        """Infer package name from pin count."""
        if pin_count <= 2:
            return "0805"
        if pin_count <= 3:
            return "SOT-23"
        if pin_count <= 8:
            return "SOIC-8"
        if pin_count <= 16:
            return "QFN-16"
        return f"QFP-{pin_count}"

    # NOTE: _old_get_pins_from_data was removed in the WS2 decomposition.
    # The deprecated auto-enrich approach is superseded by the enrich-on-getitem
    # path in __getitem__ and the `openhac database enrich` CLI command.
    
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

    def assign_to(self, zone) -> "Component":
        """Assign this component to a specific LayoutZone."""
        self.layout_zone = zone
        zone.add_member(self)
        return self

    def _stamp_catalog_fields(self, comp_data: dict) -> None:
        if not comp_data or not getattr(self, "part", None):
            return
        self.part.fields["Value"] = self.generic_name
        self.part.fields["Manufacturer"] = comp_data.get("manufacturer") or ""
        self.part.fields["MPN"] = comp_data.get("mpn") or ""
        self.part.fields["Supplier_SKU"] = comp_data.get("supplier_sku") or ""
        self.part.fields["kiCad_symbol"] = comp_data.get("kicad_symbol") or ""
        jc = comp_data.get("jlc_class")
        self.part.fields["JLC_Class"] = str(jc) if jc is not None else ""
        self.part.fields["Mouser_SKU"] = comp_data.get("mouser_sku") or ""
        self.part.fields["DigiKey_SKU"] = comp_data.get("digikey_sku") or ""
        self.part.fields["Model_3D_Local"] = comp_data.get("model_3d_local") or ""
        new_fp = comp_data.get("kicad_footprint")
        if new_fp and (not self.part.footprint or "easyeda_generated" in str(new_fp)):
            self.part.footprint = new_fp

    def refresh_from_db(self):
        """Re-read component metadata from the database and update Part fields."""
        try:
            from openhac.database.lookup_meta import strip_openhac_internal_fields
            fresh = self.db.get_component(self.generic_name)
            if not fresh:
                return
            comp_data = strip_openhac_internal_fields(fresh)
            self._comp_data = dict(comp_data)
            self._stamp_catalog_fields(comp_data)
        except Exception as e:
            logger.debug("Failed to refresh component %s from DB: %s", self.generic_name, e)

    def _get_refdes_prefix(
        self,
        category: str | None,
        *,
        generic_name: str | None = None,
        mpn: str | None = None,
    ) -> str:
        """Delegate to :func:`openhac.core.refdes.get_refdes_prefix`."""
        return get_refdes_prefix(category, generic_name=generic_name, mpn=mpn)

    def nc_unused_pins(self) -> None:
        """Connect all currently unconnected pins of this component to the NC (No Connect) net."""
        from openhac.core.net import NC

        pins = self.part.get_pins() if hasattr(self.part, "get_pins") else []
        for pin in pins:
            if hasattr(pin, "is_connected") and not pin.is_connected():
                pin += NC
            elif getattr(pin, "net", None) is None:
                pin += NC

# Interface and Module classes are now in their own submodules.
# They are re-exported at the top of this file for backward compatibility.
