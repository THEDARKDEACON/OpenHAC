"""
Backward-compatible entry point for catalog row merging.

Overlays are defined in JSON under :mod:`openhac.database.catalog_overlay` (bundled + user paths).
"""

from __future__ import annotations

from openhac.database.catalog_overlay import merge_overlay_into_row as merge_catalog_fixup

__all__ = ["merge_catalog_fixup"]
