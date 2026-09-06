"""CAT-012: licence-gated symbol / 3D shop hook.

Without an explicit licence field, do not store the file. Cache locally under
``~/.kiro/openhac/`` like EasyEDA. Never copy into git. No silent redistrib.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("openhac.licensed_cad")

_CACHE = Path(os.path.expanduser("~/.kiro/openhac/licensed_cad"))


def licensed_cad_cache_dir() -> Path:
    _CACHE.mkdir(parents=True, exist_ok=True)
    return _CACHE


def store_licensed_cad_file(
    *,
    filename: str,
    data: bytes,
    license_field: str | None,
    source: str = "shop",
) -> Path | None:
    """Write *data* into the local cache only when *license_field* is non-empty.

    Returns the cache path, or None when refused (CAT-012).
    """
    lic = str(license_field or "").strip()
    if not lic:
        logger.warning(
            "CAT-012: refusing to store %s from %s without an explicit licence field",
            filename,
            source,
        )
        return None
    dest_dir = licensed_cad_cache_dir()
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in os.path.basename(filename))
    dest = dest_dir / safe
    dest.write_bytes(data)
    meta = dest.with_suffix(dest.suffix + ".license.txt")
    meta.write_text(f"source={source}\nlicense={lic}\n", encoding="utf-8")
    return dest


class LicensedCadShop:
    """Optional SnapEDA / UltraLibrarian / SamacSys stub. No silent republish."""

    def fetch_and_cache(
        self,
        *,
        filename: str,
        data: bytes,
        license_field: str | None,
        source: str = "shop",
    ) -> Path | None:
        return store_licensed_cad_file(
            filename=filename,
            data=data,
            license_field=license_field,
            source=source,
        )
