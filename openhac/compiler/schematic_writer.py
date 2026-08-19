"""KiCad schematic writer — delegates to ``openhac.schematic`` (SSO-004)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("openhac.schematic")


class SchematicWriter:
    """Thin wrapper around the single SSO emitter."""

    def write(self, circuit, filepath: str | Path) -> Path:
        filepath = Path(filepath)
        from openhac.schematic.emit_kicad import generate_schematic

        class _Board:
            project_name = str(getattr(circuit, "name", None) or "OpenHaC")
            release_tag = "v1.0"
            modules: list = []
            schematic_signoff = False

        generate_schematic(str(filepath), _Board(), circuit=circuit)
        logger.info("Generated schematic: %s", filepath)
        return filepath
