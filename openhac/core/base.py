import urllib.parse
from skidl import Part, Net, Bus
from openhac.database.db_manager import DatabaseManager


class OpenHaCError(Exception):
    """Base exception for all OpenHaC errors."""


class SchematicGenerationError(OpenHaCError):
    """Raised by schematic_gen.py when schematic generation fails."""


class UnconnectedInterfaceError(OpenHaCError):
    """Raised by Board.compile() when a required interface net has fewer than two pins."""


class InterfaceNotFoundError(OpenHaCError):
    """Raised by Module.expose_interface() when the named interface is not registered."""


class FreeRoutingNotFoundError(OpenHaCError):
    """Raised by autoroute_cli.py when the FreeRouting jar cannot be found."""


class AutorouterFailedError(OpenHaCError):
    """Raised by autoroute_cli.py when FreeRouting exits with a non-zero code or produces no SES output."""


class Component:
    db = DatabaseManager()

    def __init__(self, generic_name: str, **kwargs):
        self.generic_name = generic_name
        # Store the owning module; set by Module.add() when the component is registered.
        self._owning_module: "Module | None" = None

        comp_data = self.db.get_component(generic_name)
        if not comp_data:
            comp_data = self._live_lookup(generic_name)
        if not comp_data:
            raise ValueError(
                f"Component '{generic_name}' not found in database or LCSC catalog. "
                f"Run sync_catalog() to refresh the component database, or check the part name."
            )

        sym_lib, sym_name = comp_data['kicad_symbol'].split(':', 1)
        try:
            import skidl
            skidl.config.github_search = False
            self.part = Part(sym_lib, sym_name, footprint=comp_data['kicad_footprint'], **kwargs)
        except Exception as e:
            # Fallback for environments without KiCad libraries installed
            import skidl
            from skidl import Pin
            print(f"Warning: Could not load KiCad library for {sym_lib}:{sym_name}. Creating synthetic part.")
            pins = [Pin(num=str(i), name=str(i)) for i in range(1, 100)]
            self.part = Part(tool=skidl.SKIDL, name=sym_name, ref_prefix='U', pins=pins, footprint=comp_data['kicad_footprint'])

        self.part.fields['Manufacturer'] = comp_data['manufacturer'] or ""
        self.part.fields['MPN'] = comp_data['mpn']
        self.part.fields['Supplier_SKU'] = comp_data['supplier_sku'] or ""
        self.part.fields['Value'] = generic_name

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

        API_BASE = "https://jlcsearch.tscircuit.com"
        HEADERS = {"User-Agent": "OpenHaC/1.0", "Accept": "application/json"}

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

        # Take the best match: prefer items where mfr or description contains the query
        best = None
        query_lower = generic_name.lower()
        for item in items:
            mfr = (item.get("mfr") or "").lower()
            desc = (item.get("description") or "").lower()
            if query_lower in mfr or query_lower in desc:
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
        except Exception:
            pass  # caching failure is non-fatal

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
        return self.part[key]

    def __setitem__(self, key, value):
        self.part[key] = value

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

    def add(self, component):
        self.components.append(component)
        if isinstance(component, Component):
            component._owning_module = self
        return component

    def declare_interface(self, name: str, *nets) -> "Interface":
        """Register a named Interface as a required connection point."""
        iface = Interface(name, *nets)
        self.required_interfaces[name] = iface
        return iface

    def expose_interface(self, name: str) -> "Interface":
        """Return the named Interface, raising InterfaceNotFoundError if absent."""
        try:
            return self.required_interfaces[name]
        except KeyError:
            raise InterfaceNotFoundError(
                f"Interface '{name}' is not registered on module '{self.name}'."
            )
