"""Graph ECO / diff report (ECO-001). Native circuit is SoT; KiCad is overlay only."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openhac.core.dnp import part_is_dnp

logger = logging.getLogger("openhac.eco")

ECO_SCHEMA = "openhac.eco.v1"


def _ref_of(part) -> str:
    return str(getattr(part, "refdes", None) or getattr(part, "ref", None) or "").strip()


def _fields(part) -> dict:
    f = getattr(part, "fields", None)
    return f if isinstance(f, dict) else {}


def collect_graph_snapshot(board=None, overlay=None) -> dict[str, Any]:
    """Current native-graph identity for ECO (refs, nets, cheap pinout grades)."""
    refs: dict[str, dict[str, Any]] = {}
    nets: list[str] = []
    grades: dict[str, str] = {}
    try:
        from openhac.core.circuit import default_circuit

        circuit = default_circuit
        for part in list(getattr(circuit, "parts", None) or []):
            ref = _ref_of(part)
            if not ref:
                continue
            fields = _fields(part)
            gn = str(fields.get("generic_name") or getattr(part, "name", "") or "").strip()
            refs[ref] = {
                "value": str(getattr(part, "value", "") or ""),
                "footprint": str(getattr(part, "footprint", "") or ""),
                "sku": str(fields.get("Supplier_SKU") or fields.get("supplier_sku") or ""),
                "generic_name": gn,
                "dnp": part_is_dnp(part),
            }
        nets = sorted(
            {
                str(getattr(n, "name", "") or "").strip()
                for n in list(getattr(circuit, "nets", None) or [])
                if str(getattr(n, "name", "") or "").strip()
            }
        )
    except Exception as e:
        logger.debug("ECO snapshot circuit read failed: %s", e)

    try:
        from openhac.database.catalog_coverage import catalog_grade
        from openhac.core.base import Component

        seen: set[str] = set()
        mods = []
        if board is not None:
            try:
                mods = list(board._get_all_modules())
            except Exception:
                mods = list(getattr(board, "modules", None) or [])
        for mod in mods:
            for comp in getattr(mod, "components", None) or []:
                gn = str(getattr(comp, "generic_name", "") or "").strip()
                if not gn or gn in seen:
                    continue
                seen.add(gn)
                row = None
                try:
                    row = Component.db.get_component(gn)
                except Exception:
                    row = getattr(comp, "_comp_data", None)
                if row:
                    grades[gn] = catalog_grade(dict(row))
    except Exception:
        pass

    dropped_cu, dropped_w = overlay_drops(overlay, set(nets))
    return {
        "refs": refs,
        "nets": nets,
        "pinout_grades": grades,
        "overlay_copper_dropped": dropped_cu,
        "overlay_wires_dropped": dropped_w,
    }


def overlay_drops(overlay, graph_nets: set[str]) -> tuple[list[dict], list[dict]]:
    copper: list[dict] = []
    wires: list[dict] = []
    if overlay is None:
        return copper, wires
    live = {str(n) for n in graph_nets if str(n)}
    for t in list(getattr(overlay, "tracks", None) or []):
        net = str(getattr(t, "net", "") or "")
        if net and net not in live:
            copper.append({"kind": "track", "net": net})
    for v in list(getattr(overlay, "vias", None) or []):
        net = str(getattr(v, "net", "") or "")
        if net and net not in live:
            copper.append({"kind": "via", "net": net})
    for z in list(getattr(overlay, "zones", None) or []):
        net = str(getattr(z, "net", "") or "")
        if net and net not in live:
            copper.append({"kind": "zone", "net": net})
    for lb in list(getattr(overlay, "sch_labels", None) or []):
        name = str(getattr(lb, "name", "") or "")
        if name and name not in live:
            wires.append({"kind": "label", "net": name})
    return copper, wires


def _extract_manifest_snapshot(manifest: dict) -> dict[str, Any]:
    refs: dict[str, dict[str, Any]] = {}
    for rec in manifest.get("unverified_parts") or []:
        if isinstance(rec, dict) and rec.get("ref"):
            refs[str(rec["ref"])] = {
                "value": str(rec.get("value") or ""),
                "footprint": str(rec.get("footprint") or ""),
                "sku": "",
                "generic_name": "",
                "dnp": False,
            }
    nets = [str(x) for x in (manifest.get("nets") or []) if str(x)]
    grades = dict(manifest.get("pinout_grades") or {})
    return {"refs": refs, "nets": nets, "pinout_grades": grades}


def load_baseline(output_dir: str | Path | None, project_name: str) -> tuple[str, dict[str, Any]]:
    base = Path(output_dir) if output_dir is not None else Path.cwd()
    eco = base / f"{project_name}.openhac-eco.json"
    graph = base / f"{project_name}.openhac-graph.json"
    manifest = base / f"{project_name}.openhac-manifest.json"
    if eco.is_file():
        try:
            data = json.loads(eco.read_text(encoding="utf-8"))
            cur = data.get("current")
            if isinstance(cur, dict) and (cur.get("refs") is not None or cur.get("nets") is not None):
                return "previous_eco", cur
        except Exception:
            pass
    if graph.is_file():
        try:
            data = json.loads(graph.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return "previous_graph", data
        except Exception:
            pass
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return "previous_manifest", _extract_manifest_snapshot(data)
        except Exception:
            pass
    return "none", {"refs": {}, "nets": [], "pinout_grades": {}}


def diff_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev_refs = dict(previous.get("refs") or {})
    cur_refs = dict(current.get("refs") or {})
    added = sorted(set(cur_refs) - set(prev_refs))
    removed = sorted(set(prev_refs) - set(cur_refs))
    changed: list[dict[str, Any]] = []
    for ref in sorted(set(prev_refs) & set(cur_refs)):
        a, b = prev_refs[ref], cur_refs[ref]
        if not isinstance(a, dict):
            a = {}
        if not isinstance(b, dict):
            b = {}
        fields = {}
        for k in ("value", "footprint", "sku", "dnp"):
            if a.get(k) != b.get(k):
                fields[k] = {"from": a.get(k), "to": b.get(k)}
        if fields:
            changed.append({"ref": ref, "fields": fields})
    prev_nets = {str(n) for n in (previous.get("nets") or [])}
    cur_nets = {str(n) for n in (current.get("nets") or [])}
    prev_g = dict(previous.get("pinout_grades") or {})
    cur_g = dict(current.get("pinout_grades") or {})
    grade_changes = []
    for gn in sorted(set(prev_g) | set(cur_g)):
        if prev_g.get(gn) != cur_g.get(gn):
            grade_changes.append({"generic_name": gn, "from": prev_g.get(gn), "to": cur_g.get(gn)})
    return {
        "added_refs": added,
        "removed_refs": removed,
        "changed_refs": changed,
        "nets_appeared": sorted(cur_nets - prev_nets),
        "nets_vanished": sorted(prev_nets - cur_nets),
        "pinout_grade_changes": grade_changes,
    }


def _empty_diff() -> dict[str, Any]:
    return {
        "added_refs": [],
        "removed_refs": [],
        "changed_refs": [],
        "nets_appeared": [],
        "nets_vanished": [],
        "pinout_grade_changes": [],
    }


def _diff_has_changes(diff: dict[str, Any]) -> bool:
    return any(
        diff.get(k)
        for k in (
            "added_refs",
            "removed_refs",
            "changed_refs",
            "nets_appeared",
            "nets_vanished",
            "pinout_grade_changes",
        )
    )


def write_eco_report(
    output_dir: str | Path | None,
    project_name: str,
    *,
    board=None,
    overlay=None,
    snapshot: dict[str, Any] | None = None,
) -> Path:
    base = Path(output_dir) if output_dir is not None else Path.cwd()
    base.mkdir(parents=True, exist_ok=True)
    baseline_kind, previous = load_baseline(base, project_name)
    current = snapshot if snapshot is not None else collect_graph_snapshot(board, overlay)
    # Spec: first compile (no baseline) still writes current + empty diffs — not "everything added".
    if baseline_kind == "none":
        diff = _empty_diff()
    else:
        diff = diff_snapshots(previous, current)
    payload = {
        "schema": ECO_SCHEMA,
        "project": project_name,
        "source_of_truth": "native_graph",
        **diff,
        "overlay_copper_dropped": list(current.get("overlay_copper_dropped") or []),
        "overlay_wires_dropped": list(current.get("overlay_wires_dropped") or []),
        "current": {
            "refs": current.get("refs") or {},
            "nets": current.get("nets") or [],
            "pinout_grades": current.get("pinout_grades") or {},
        },
    }
    # Only stamp baseline when something actually moved, so identical recompiles stay byte-stable.
    if baseline_kind != "none" and _diff_has_changes(diff):
        payload["baseline"] = baseline_kind
    eco_path = base / f"{project_name}.openhac-eco.json"
    graph_path = base / f"{project_name}.openhac-graph.json"
    text = json.dumps(payload, indent=2, sort_keys=True)
    eco_path.write_text(text, encoding="utf-8")
    graph_path.write_text(
        json.dumps(payload["current"], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    logger.info("Wrote %s (baseline=%s)", eco_path, baseline_kind)
    return eco_path
