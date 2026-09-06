"""Catalog completeness grades and coverage report (CAT-001, CAT-006, 3D-004).

A packed catalog is depth, not SKU count. Grades are ``compile_ready`` or
``warehouse``. This module does not fetch.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from openhac.database.kicad_3d import (
    expand_3d_path,
    library_3d_file_exists,
    library_3d_relpath_for_footprint,
)
from openhac.database.pin_policy import (
    is_two_terminal_category,
    pinout_is_named,
    pinout_is_numeric_only,
)

GRADE_COMPILE_READY = "compile_ready"
GRADE_WAREHOUSE = "warehouse"

PLACEHOLDER_FOOTPRINTS = frozenset(
    {
        "Device:Q",
        "Device:IC",
        "Device:R",
        "Device:C",
        "Device:L",
        "Device:LED",
        "MCU_Module:Generic_MCU",
        "Regulator_Linear:AMS1117-5.0",
        "Connector_Generic:Conn_01x04",
        "Sensor:Generic",
        "Sensor_Motion:Generic_Accelerometer",
    }
)

COVERAGE_SCHEMA = "openhac.catalog_coverage.v1"


def _norm(s: Any) -> str:
    return str(s or "").strip()


def footprint_is_resolvable(row: dict) -> bool:
    """True when ``kicad_footprint`` is a real library id, not a placeholder."""
    fp = _norm(row.get("kicad_footprint") or row.get("footprint_resolved"))
    if not fp or ":" not in fp:
        return False
    if fp in PLACEHOLDER_FOOTPRINTS:
        return False
    lib, _, name = fp.partition(":")
    if not lib or not name:
        return False
    if name.upper() in {"Q", "IC", "GENERIC_MCU", "GENERIC"}:
        return False
    return True


def _expand_3d_path(raw: str) -> str:
    return expand_3d_path(raw)


def threed_is_ok(row: dict) -> bool:
    """3D pointer exists on disk, is a KiCad library model, or is a documented pattern.

    Missing 3D is not silently bound to a fake cube (3D-004).
    """
    src = _norm(row.get("model_3d_source")).lower()
    local = _norm(row.get("model_3d_local"))
    if src == "kicad_lib":
        if local:
            expanded = _expand_3d_path(local)
            if os.path.isfile(expanded):
                return True
            # Library models may omit a live file when the path pattern is stock.
            if "${KICAD" in local or library_3d_relpath_for_footprint(row.get("kicad_footprint")):
                return True
        fp = _norm(row.get("kicad_footprint"))
        return library_3d_relpath_for_footprint(fp) is not None or library_3d_file_exists(fp)
    if local:
        expanded = _expand_3d_path(local)
        if os.path.isfile(expanded):
            fp = _norm(row.get("kicad_footprint"))
            if fp:
                try:
                    from openhac.database.cad_ids import is_stock_kicad_id
                    from openhac.database.kicad_3d import fillin_mesh_ok_for_footprint

                    if is_stock_kicad_id(fp) and not fillin_mesh_ok_for_footprint(expanded, fp):
                        return False
                except Exception:
                    pass
            return True
        if "${KICAD" in local and library_3d_relpath_for_footprint(row.get("kicad_footprint")):
            return True
    return False


def named_pinout_ok(row: dict) -> bool:
    return pinout_is_named(
        row.get("pinout_json"),
        category=row.get("category"),
        generic_name=row.get("generic_name"),
    )


def catalog_grade(row: dict | None) -> str:
    """Return ``compile_ready`` or ``warehouse`` (CAT-001).

    Consults ``catalog_tier`` when set: an explicit ``warehouse`` IC/MCU row
    stays warehouse even if a numeric table is present. Two-terminal passives
    that meet the pin/FP/3D bar still grade ``compile_ready``.
    """
    if not row:
        return GRADE_WAREHOUSE
    gn = _norm(row.get("generic_name"))
    cat = _norm(row.get("category"))
    named = named_pinout_ok(row)
    fp_ok = footprint_is_resolvable(row)
    d3_ok = threed_is_ok(row)
    fields_ok = bool(named and fp_ok and d3_ok)

    tier = _norm(row.get("catalog_tier")).lower()
    if pinout_is_numeric_only(row.get("pinout_json")) and not is_two_terminal_category(cat, gn):
        return GRADE_WAREHOUSE
    if not fields_ok:
        return GRADE_WAREHOUSE
    if tier == GRADE_WAREHOUSE and not is_two_terminal_category(cat, gn):
        return GRADE_WAREHOUSE
    return GRADE_COMPILE_READY


def spice_registry_hit(row: dict) -> bool:
    try:
        from openhac.compiler.spice_models import lookup_registry
    except Exception:
        return False
    gn = _norm(row.get("generic_name"))
    mpn = _norm(row.get("mpn"))
    rec = lookup_registry(generic_name=gn, mpn=mpn)
    return rec is not None and rec.kind != "primitive"


def stamp_spice_registry_on_row(row: dict) -> dict:
    """SPS-055: stamp spice_include / spice_subckt from the registry on get_component.

    ``OPENHAC_NO_BUNDLED_SPICE_MODELS=1`` must not stamp bundled physics (the
    registry loader already omits bundled JSON in that mode).
    Overlay-applied spice_* keys already on *row* win.
    """
    out = dict(row)
    if _norm(out.get("spice_include")) or _norm(out.get("spice_subckt")):
        return out
    try:
        from openhac.compiler.spice_models import lookup_registry
    except Exception:
        return out
    rec = lookup_registry(
        generic_name=_norm(out.get("generic_name")),
        mpn=_norm(out.get("mpn")),
    )
    if rec is None or rec.kind == "primitive":
        return out
    if rec.include:
        out["spice_include"] = rec.include
    if rec.subckt:
        out["spice_subckt"] = rec.subckt
    if rec.kind:
        out["spice_kind"] = rec.kind
    if rec.sha256:
        out["spice_sha256"] = rec.sha256
    return out


def sha256_file(path: str | os.PathLike[str]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def missing_3d_row(row: dict) -> dict | None:
    if threed_is_ok(row):
        return None
    return {
        "generic_name": _norm(row.get("generic_name")),
        "mpn": _norm(row.get("mpn")),
        "kicad_footprint": _norm(row.get("kicad_footprint")),
        "model_3d_local": _norm(row.get("model_3d_local")),
        "model_3d_source": _norm(row.get("model_3d_source")),
    }


def iter_component_rows(db) -> list[dict]:
    with db._tx() as conn:
        conn.row_factory = __import__("sqlite3").Row
        cur = conn.execute("SELECT * FROM components")
        return [dict(r) for r in cur.fetchall()]


def collect_catalog_coverage(db) -> dict[str, Any]:
    """Build ``openhac.catalog_coverage.v1`` from the local SQLite catalog. No fetch."""
    from openhac.database.catalog_overlay import merge_overlay_into_row

    rows_raw = iter_component_rows(db)
    compile_ready = 0
    warehouse = 0
    named = 0
    fp_ok = 0
    d3_ok = 0
    spice_hits = 0
    missing_3d: list[dict] = []
    by_grade = {GRADE_COMPILE_READY: 0, GRADE_WAREHOUSE: 0}

    for raw in rows_raw:
        row = stamp_spice_registry_on_row(merge_overlay_into_row(raw))
        grade = catalog_grade(row)
        by_grade[grade] = by_grade.get(grade, 0) + 1
        if grade == GRADE_COMPILE_READY:
            compile_ready += 1
        else:
            warehouse += 1
        if named_pinout_ok(row):
            named += 1
        if footprint_is_resolvable(row):
            fp_ok += 1
        if threed_is_ok(row):
            d3_ok += 1
        else:
            miss = missing_3d_row(row)
            if miss:
                missing_3d.append(miss)
        if spice_registry_hit(row) or _norm(row.get("spice_include")):
            spice_hits += 1

    return {
        "schema": COVERAGE_SCHEMA,
        "total": len(rows_raw),
        "compile_ready": compile_ready,
        "warehouse": warehouse,
        "named_pinout": named,
        "resolvable_footprint": fp_ok,
        "threed_ok": d3_ok,
        "spice_registry_hit": spice_hits,
        "missing_3d": missing_3d,
        "grades": by_grade,
    }


def coverage_text_report(report: dict[str, Any]) -> str:
    lines = [
        "OpenHaC catalog coverage (depth, not SKU count)",
        f"  schema: {report.get('schema')}",
        f"  total rows: {report.get('total', 0)}",
        f"  compile_ready: {report.get('compile_ready', 0)}",
        f"  warehouse: {report.get('warehouse', 0)}",
        f"  named pinout: {report.get('named_pinout', 0)}",
        f"  resolvable footprint: {report.get('resolvable_footprint', 0)}",
        f"  3D on disk or kicad_lib: {report.get('threed_ok', 0)}",
        f"  spice registry hit: {report.get('spice_registry_hit', 0)}",
        f"  missing 3D: {len(report.get('missing_3d') or [])}",
    ]
    return "\n".join(lines) + "\n"


def write_coverage_json(report: dict[str, Any], path: str | os.PathLike[str]) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest
