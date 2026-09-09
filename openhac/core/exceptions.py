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


class ModulePropertyError(OpenHaCError):
    """Raised when propagating module or schematic properties onto child parts fails in production mode."""


class ERCDriverContentionError(OpenHaCError):
    """Raised when multiple driving outputs conflict on the same net (ERC-001)."""


class ERCUnconnectedPinError(OpenHaCError):
    """Raised when pins are left unconnected without explicit NoConnect marker."""


class ERCFloatingInputError(ERCUnconnectedPinError):
    """Raised when an input or load signal/pin is left unconnected in strict checks (ERC-002)."""


class ERCDomainMismatchError(OpenHaCError):
    """Raised when incompatible electrical voltage/logic domains are interconnected (ERC-003)."""


class ERCMissingTerminationError(OpenHaCError):
    """Raised when an open-drain bus lacks necessary pull-up/termination (ERC-004)."""


class ProtocolCompatibilityError(OpenHaCError):
    """Raised when connecting two protocols with incompatible signal interfaces."""

