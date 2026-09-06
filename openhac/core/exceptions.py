"""OpenHaC exception hierarchy.

All compiler, layout, ERC, and toolchain exceptions live here so they can be
imported without pulling in the heavyweight ``Component`` / ``Module`` trees.
"""


class OpenHaCError(Exception):
    """Base exception for all OpenHaC errors."""


class SchematicGenerationError(OpenHaCError):
    """Raised by schematic_gen.py when schematic generation fails."""


class ArtworkParityError(OpenHaCError):
    """Raised when saved KiCad artwork shorts nets that the graph keeps distinct (LIVE-006)."""


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


class CatalogLockError(OpenHaCError):
    """Raised when a catalog lockfile is missing or disagrees with the resolved BOM (LOCK-001)."""


class PlacementIntentError(OpenHaCError):
    """Raised when overlay footprint pose fails placement-intent checks (PLC-001)."""


class PinoutAuthoringError(OpenHaCError):
    """Raised when ``openhac pinout init`` cannot write a named pin table (PIN-001)."""


class JlcExportError(OpenHaCError):
    """Raised when a JLCPCB-shaped BOM/CPL pack cannot be written (MFG-010)."""
