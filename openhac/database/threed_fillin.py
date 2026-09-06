"""Footprint-keyed 3D fill-in cache (3D-006).

KiCad library meshes stay SoT when the pack has a file. Missing bodies are a
STEP at ``~/.kiro/openhac/3d_models/<Lib>/<Footprint>.step``. Prefetch fills
that path from the bundled map, catalog ``C…`` SKUs, or jlcsearch by MPN.
Compile only reads the pack or that path. It does not glob EasyEDA/JLC folders.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("openhac.threed_fillin")

_MAP_NAME = "3d_fillin_map.json"
_DISCOVERED_NAME = "3d_fillin_discovered.json"
_SCHEMA = "openhac.3d-fillin.v1"
_JLCSEARCH_LIST = "https://jlcsearch.tscircuit.com/components/list.json"

_index_cache: tuple[str, dict[str, dict[str, str]]] | None = None
_MPN_ALNUM = re.compile(r"[^A-Z0-9]+")


def reset_fillin_map_cache() -> None:
    global _index_cache
    _index_cache = None


def _bundled_map_path() -> Path:
    return Path(__file__).resolve().parent / _MAP_NAME


def fillin_root() -> Path:
    extra = (os.environ.get("OPENHAC_3D_FILLIN_DIR") or "").strip()
    if extra:
        p = Path(os.path.expanduser(extra))
    else:
        p = Path.home() / ".kiro" / "openhac" / "3d_models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def parse_footprint_id(footprint: str | None) -> tuple[str, str] | None:
    s = str(footprint or "").strip()
    if ":" not in s:
        return None
    lib, _, name = s.partition(":")
    lib, name = lib.strip(), name.strip()
    if not lib or not name:
        return None
    return lib, name


def fillin_step_path(footprint: str | None) -> Path | None:
    parsed = parse_footprint_id(footprint)
    if not parsed:
        return None
    lib, name = parsed
    safe = name.replace("/", "_").replace("\\", "_")
    return fillin_root() / lib / f"{safe}.step"


def fillin_step_on_disk(footprint: str | None) -> bool:
    dest = fillin_step_path(footprint)
    if dest is None or not dest.is_file():
        return False
    from openhac.database.kicad_3d import fillin_mesh_ok_for_footprint

    return fillin_mesh_ok_for_footprint(dest, footprint)


def fillin_available(footprint: str | None) -> bool:
    """True when the footprint cache file exists, or a ``file:`` source is on disk.

    Does not copy or glob (safe for coverage reports).
    """
    fp = str(footprint or "").strip()
    if fillin_step_on_disk(fp):
        return True
    entry = load_fillin_map().get(fp)
    if not entry:
        return False
    parsed = parse_fillin_source(entry.get("source"))
    if parsed and parsed[0] == "file":
        return Path(parsed[1]).is_file()
    return False


def _parse_entry(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, str):
        src = raw.strip()
        if not src:
            return None
        return {"source": src}
    if isinstance(raw, dict):
        src = str(raw.get("source") or "").strip()
        if not src:
            return None
        out = {"source": src}
        note = str(raw.get("note") or "").strip()
        if note:
            out["note"] = note
        rejected = str(raw.get("rejected_skus") or "").strip()
        if rejected:
            out["rejected_skus"] = rejected
        return out
    return None


def _load_map_file(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load 3D fill-in map %s: %s", path, e)
        return {}
    if isinstance(data, dict):
        schema = str(data.get("schema") or "").strip()
        if schema and schema != _SCHEMA:
            logger.warning("Unexpected 3D fill-in schema %s in %s (expected %s)", schema, path, _SCHEMA)
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for fp, raw in entries.items():
        key = str(fp or "").strip()
        parsed = _parse_entry(raw)
        if key and ":" in key and parsed:
            out[key] = parsed
    return out


def discovered_map_path() -> Path:
    """User-local discoveries (not git). Isolated when ``OPENHAC_3D_FILLIN_DIR`` is set."""
    override = (os.environ.get("OPENHAC_3D_FILLIN_DISCOVERED") or "").strip()
    if override:
        return Path(os.path.expanduser(override))
    extra = (os.environ.get("OPENHAC_3D_FILLIN_DIR") or "").strip()
    if extra:
        return Path(os.path.expanduser(extra)).expanduser().parent / _DISCOVERED_NAME
    return Path.home() / ".kiro" / "openhac" / _DISCOVERED_NAME


def _cache_key() -> str:
    extra = (os.environ.get("OPENHAC_3D_FILLIN_MAP") or "").strip()
    return f"{extra}|{discovered_map_path()}"


def load_fillin_map() -> dict[str, dict[str, str]]:
    """Bundled map, then discoveries (no override of bundled), then ``OPENHAC_3D_FILLIN_MAP``."""
    global _index_cache
    key = _cache_key()
    if _index_cache is not None and _index_cache[0] == key:
        return dict(_index_cache[1])
    merged = _load_map_file(_bundled_map_path())
    for fp, entry in _load_map_file(discovered_map_path()).items():
        if fp not in merged:
            merged[fp] = entry
    extra = (os.environ.get("OPENHAC_3D_FILLIN_MAP") or "").strip()
    if extra:
        p = Path(os.path.expanduser(extra))
        if p.is_dir():
            for f in sorted(p.glob("*.json")):
                merged.update(_load_map_file(f))
        elif p.is_file():
            merged.update(_load_map_file(p))
    _index_cache = (key, merged)
    return dict(merged)


def _write_map_file(path: Path, entries: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": _SCHEMA, "entries": entries}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def remember_discovered_lcsc(footprint: str, sku: str, *, note: str = "") -> None:
    """Persist a jlcsearch hit. Never overrides a bundled footprint key."""
    fp = str(footprint or "").strip()
    s = str(sku or "").strip()
    if not fp or ":" not in fp:
        return
    if not (s.upper().startswith("C") and s[1:].isdigit()):
        return
    if fp in _load_map_file(_bundled_map_path()):
        return
    path = discovered_map_path()
    existing = _load_map_file(path)
    prev = existing.get(fp) or {}
    parsed = parse_fillin_source(prev.get("source"))
    if parsed and parsed[0] == "lcsc":
        return
    sku_n = "C" + s[1:] if s.upper().startswith("C") else s
    rejected = _sku_set(prev.get("rejected_skus"))
    if sku_n.upper() in {x.upper() for x in rejected}:
        return
    entry = {"source": f"lcsc:{s}"}
    if rejected:
        entry["rejected_skus"] = ",".join(sorted(rejected))
    n = str(note or "").strip()
    if n:
        entry["note"] = n
    existing[fp] = entry
    _write_map_file(path, existing)
    reset_fillin_map_cache()
    logger.info("3D fill-in remembered %s → %s", fp, s)


def parse_fillin_source(source: str | None) -> tuple[str, str] | None:
    raw = str(source or "").strip()
    if not raw:
        return None
    if raw.lower() in ("kicad", "reject") or raw.lower().startswith("reject:"):
        kind = "kicad" if raw.lower() == "kicad" else "reject"
        extra = raw.split(":", 1)[1].strip() if ":" in raw else ""
        return (kind, extra)
    if raw.lower().startswith("lcsc:"):
        sku = raw.split(":", 1)[1].strip()
        if sku.upper().startswith("C") and sku[1:].isdigit():
            return ("lcsc", sku)
        return None
    if raw.lower().startswith("file:"):
        return ("file", os.path.expanduser(raw.split(":", 1)[1].strip()))
    if raw.upper().startswith("C") and raw[1:].isdigit():
        return ("lcsc", raw.strip())
    return None


def lcsc_for_footprint(footprint: str | None) -> str | None:
    fp = str(footprint or "").strip()
    entry = load_fillin_map().get(fp)
    if not entry:
        return None
    parsed = parse_fillin_source(entry.get("source"))
    if parsed and parsed[0] == "lcsc":
        sku = parsed[1]
        if sku in rejected_skus_for_footprint(fp):
            return None
        return sku
    return None


def _sku_set(raw: str | None) -> set[str]:
    out: set[str] = set()
    for part in str(raw or "").split(","):
        s = part.strip().upper()
        if s.startswith("C") and s[1:].isdigit():
            out.add("C" + s[1:])
        elif s.isdigit():
            out.add(f"C{s}")
    return out


def rejected_skus_for_footprint(footprint: str | None) -> set[str]:
    fp = str(footprint or "").strip()
    skus: set[str] = set()
    for path in (_bundled_map_path(), discovered_map_path()):
        entry = _load_map_file(path).get(fp) or {}
        skus |= _sku_set(entry.get("rejected_skus"))
        parsed = parse_fillin_source(entry.get("source"))
        if parsed and parsed[0] == "reject" and parsed[1]:
            skus |= _sku_set(parsed[1])
    extra = (os.environ.get("OPENHAC_3D_FILLIN_MAP") or "").strip()
    if extra:
        p = Path(os.path.expanduser(extra))
        if p.is_file():
            entry = _load_map_file(p).get(fp) or {}
            skus |= _sku_set(entry.get("rejected_skus"))
    return skus


def remember_rejected_lcsc(footprint: str, sku: str, *, note: str = "") -> None:
    """Forget a discovered SKU so prefetch will not replay a chip-on-module mesh."""
    fp = str(footprint or "").strip()
    s = str(sku or "").strip().upper()
    if s.startswith("C") and s[1:].isdigit():
        s = "C" + s[1:]
    elif s.isdigit():
        s = f"C{s}"
    else:
        s = ""
    if not fp or ":" not in fp:
        return
    if fp in _load_map_file(_bundled_map_path()):
        logger.warning("3D fill-in will not reject bundled map entry %s", fp)
        return
    path = discovered_map_path()
    existing = _load_map_file(path)
    entry = dict(existing.get(fp) or {})
    rejected = _sku_set(entry.get("rejected_skus"))
    parsed = parse_fillin_source(entry.get("source"))
    if parsed and parsed[0] == "lcsc" and parsed[1]:
        rejected.add(parsed[1])
    if s:
        rejected.add(s)
    entry["source"] = "reject"
    if rejected:
        entry["rejected_skus"] = ",".join(sorted(rejected))
    n = str(note or "").strip()
    if n:
        entry["note"] = n
    existing[fp] = {k: v for k, v in entry.items() if v}
    _write_map_file(path, existing)
    reset_fillin_map_cache()
    logger.info("3D fill-in rejected %s for %s", ",".join(sorted(rejected)) or "mesh", fp)


def evict_fillin_step(footprint: str | None, *, reason: str = "") -> bool:
    dest = fillin_step_path(footprint)
    if dest is None or not dest.is_file():
        return False
    try:
        dest.unlink()
    except OSError as e:
        logger.warning("3D fill-in could not evict %s: %s", dest, e)
        return False
    logger.warning("3D fill-in evicted %s (%s)", footprint, reason or "invalid mesh")
    return True


def install_fillin_step(footprint: str | None, src: str | Path) -> str | None:
    dest = fillin_step_path(footprint)
    src_p = Path(src)
    if dest is None or not src_p.is_file():
        return None
    from openhac.database.kicad_3d import fillin_mesh_ok_for_footprint, is_jedec_placeholder_3d

    if is_jedec_placeholder_3d(str(src_p)):
        logger.warning("3D fill-in refused JEDEC cube %s for %s", src_p.name, footprint)
        return None
    if not fillin_mesh_ok_for_footprint(src_p, footprint):
        logger.warning("3D fill-in refused %s for %s (package/body mismatch)", src_p.name, footprint)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.resolve() != src_p.resolve():
        shutil.copy2(src_p, dest)
    if not fillin_mesh_ok_for_footprint(dest, footprint):
        evict_fillin_step(footprint, reason="package/body mismatch after copy")
        return None
    logger.info("3D fill-in installed %s → %s", footprint, dest)
    return str(dest.resolve())


def seed_fillin_from_legacy_cache(footprint: str | None) -> str | None:
    """Copy a name-matched EasyEDA/JLC STEP into the footprint cache once."""
    dest = fillin_step_path(footprint)
    if dest is None:
        return None
    from openhac.database.kicad_3d import fillin_mesh_ok_for_footprint, find_cached_generated_3d, is_jedec_placeholder_3d

    if dest.is_file():
        if fillin_mesh_ok_for_footprint(dest, footprint):
            return str(dest.resolve())
        evict_fillin_step(footprint, reason="invalid cached fill-in")
    legacy = find_cached_generated_3d(footprint)
    if not legacy or is_jedec_placeholder_3d(legacy):
        return None
    if not fillin_mesh_ok_for_footprint(legacy, footprint):
        return None
    return install_fillin_step(footprint, legacy)


def resolve_fillin_step(footprint: str | None) -> str | None:
    dest = fillin_step_path(footprint)
    if dest is None:
        return None
    from openhac.database.kicad_3d import fillin_mesh_ok_for_footprint

    if dest.is_file():
        if fillin_mesh_ok_for_footprint(dest, footprint):
            return str(dest.resolve())
        evict_fillin_step(footprint, reason="invalid cached fill-in")
    entry = load_fillin_map().get(str(footprint or "").strip())
    if entry:
        parsed = parse_fillin_source(entry.get("source"))
        if parsed and parsed[0] == "file":
            p = Path(parsed[1])
            if p.is_file():
                return install_fillin_step(footprint, p)
    return seed_fillin_from_legacy_cache(footprint)


def _alnum_mpn(value: str | None) -> str:
    return _MPN_ALNUM.sub("", str(value or "").upper())


def _lcsc_sku_from_item(item: dict) -> str | None:
    raw = item.get("lcsc")
    if raw is None:
        raw = item.get("sku")
    s = str(raw or "").strip()
    if not s:
        return None
    if s[:1].upper() == "C" and s[1:].isdigit():
        return "C" + s[1:]
    if s.isdigit():
        return f"C{s}"
    return None


def pick_lcsc_matching_mpn(
    mpn: str,
    items: list[dict] | None,
    *,
    footprint: str | None = None,
    skip_skus: set[str] | None = None,
) -> str | None:
    """Return ``C…`` only when an item's ``mfr`` equals or contains the MPN (len≥5)."""
    from openhac.database.kicad_3d import jlc_item_ok_for_footprint

    needle = _alnum_mpn(mpn)
    if len(needle) < 5:
        return None
    skip = {s.strip().upper() for s in (skip_skus or set()) if s}
    ranked: list[tuple[int, int, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        hay = _alnum_mpn(str(item.get("mfr") or item.get("mpn") or ""))
        if not hay:
            continue
        if hay == needle:
            exact = 0
        elif needle in hay:
            exact = 1
        elif hay in needle and len(hay) >= 5:
            exact = 2
        else:
            continue
        sku = _lcsc_sku_from_item(item)
        if not sku or sku.upper() in skip:
            continue
        if footprint and not jlc_item_ok_for_footprint(footprint, item):
            continue
        try:
            stock = int(item.get("stock") or 0)
        except (TypeError, ValueError):
            stock = 0
        ranked.append((exact, -stock, sku))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


def _jlcsearch_components(query: str) -> list[dict]:
    try:
        from openhac.database.enrich import network_allowed

        if not network_allowed():
            return []
    except Exception:
        return []
    q = str(query or "").strip()
    if len(_alnum_mpn(q)) < 5:
        return []
    from openhac.version_info import user_agent

    url = f"{_JLCSEARCH_LIST}?search={urllib.parse.quote(q)}&limit=20&full=true"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent(), "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("jlcsearch 3D lookup failed for %s: %s", q, e)
        return []
    if isinstance(data, dict):
        items = data.get("components") or data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [x for x in items if isinstance(x, dict)]


def discover_lcsc_for_mpn(
    mpn: str,
    *,
    search: Callable[[str], list[dict]] | None = None,
    footprint: str | None = None,
    skip_skus: set[str] | None = None,
) -> str | None:
    needle = str(mpn or "").strip()
    if len(_alnum_mpn(needle)) < 5:
        return None
    fetch = search if search is not None else _jlcsearch_components
    return pick_lcsc_matching_mpn(
        needle, fetch(needle), footprint=footprint, skip_skus=skip_skus
    )


def footprints_from_board(board) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    try:
        modules = board._get_all_modules() if hasattr(board, "_get_all_modules") else getattr(board, "modules", []) or []
    except Exception:
        modules = getattr(board, "modules", []) or []
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            fp = ""
            part = getattr(comp, "part", None)
            if part is not None:
                fp = str(getattr(part, "footprint", "") or "")
            if not fp:
                cd = getattr(comp, "_comp_data", None) or {}
                fp = str(cd.get("kicad_footprint") or "")
            fp = fp.strip()
            if fp and fp not in seen:
                seen.add(fp)
                out.append(fp)
    return out


def prefetch_fillin_for_footprint(
    footprint: str,
    *,
    sku: str | None = None,
    fetch_lcsc=None,
    force: bool = False,
) -> bool:
    """Download/copy fill-in STEP for one footprint. Returns True if cache file exists after."""
    from openhac.database.kicad_3d import (
        fillin_mesh_ok_for_footprint,
        is_jedec_passive_footprint,
        library_3d_file_exists,
        skip_3d_fillin_footprint,
    )

    fp = str(footprint or "").strip()
    if not fp or skip_3d_fillin_footprint(fp) or is_jedec_passive_footprint(fp) or library_3d_file_exists(fp):
        return False
    dest = fillin_step_path(fp)
    if dest is not None and dest.is_file():
        if not force and fillin_mesh_ok_for_footprint(dest, fp):
            return True
        evict_fillin_step(fp, reason="--force" if force else "invalid cached fill-in")
    entry = load_fillin_map().get(fp)
    source = (entry or {}).get("source") if entry else None
    parsed = parse_fillin_source(source)
    if parsed and parsed[0] in ("kicad", "reject"):
        return False
    if parsed and parsed[0] == "file":
        return install_fillin_step(fp, parsed[1]) is not None
    map_sku = parsed[1] if parsed and parsed[0] == "lcsc" else None
    sku = map_sku or (str(sku).strip() if sku else None)
    if sku and sku.upper() in {x.upper() for x in rejected_skus_for_footprint(fp)}:
        logger.warning("3D fill-in skipping rejected SKU %s for %s", sku, fp)
        sku = None
    if not sku:
        return seed_fillin_from_legacy_cache(fp) is not None
    if fetch_lcsc is None:
        from openhac.database.easyeda_integration import generate_footprint_from_lcsc

        fetch_lcsc = generate_footprint_from_lcsc
    got = fetch_lcsc(sku)
    if not got:
        model_path = None
    else:
        _fp_id, model_path = got
    if not model_path or not os.path.isfile(str(model_path)):
        return seed_fillin_from_legacy_cache(fp) is not None
    if install_fillin_step(fp, model_path):
        return True
    remember_rejected_lcsc(fp, sku, note="package/body mismatch")
    return seed_fillin_from_legacy_cache(fp) is not None


def prefetch_fillin_from_board(
    board,
    *,
    db=None,
    search: Callable[[str], list[dict]] | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """Prefetch fill-ins for footprints on *board* (map, catalog LCSC, then MPN search)."""
    from openhac.database.kicad_3d import (
        fillin_mesh_ok_for_footprint,
        is_jedec_passive_footprint,
        library_3d_file_exists,
        skip_3d_fillin_footprint,
    )

    attempted = 0
    updated = 0
    for fp in footprints_from_board(board):
        if skip_3d_fillin_footprint(fp) or is_jedec_passive_footprint(fp) or library_3d_file_exists(fp):
            continue
        dest = fillin_step_path(fp)
        if dest is not None and dest.is_file():
            if not force and fillin_mesh_ok_for_footprint(dest, fp):
                updated += 1
                continue
            evict_fillin_step(fp, reason="--force" if force else "invalid cached fill-in")
            disc = _load_map_file(discovered_map_path()).get(fp) or {}
            parsed_disc = parse_fillin_source(disc.get("source"))
            if parsed_disc and parsed_disc[0] == "lcsc":
                remember_rejected_lcsc(fp, parsed_disc[1], note="invalid cached fill-in")
        skip = rejected_skus_for_footprint(fp)
        sku = lcsc_for_footprint(fp)
        if sku and sku.upper() in {x.upper() for x in skip}:
            sku = None
        if not sku:
            sku = _catalog_lcsc_for_footprint(board, fp, db)
            if sku and sku.upper() in {x.upper() for x in skip}:
                sku = None
        discovered_mpn = None
        if not sku:
            for mpn in _mpns_for_footprint(board, fp, db=db):
                sku = discover_lcsc_for_mpn(
                    mpn, search=search, footprint=fp, skip_skus=skip
                )
                if sku:
                    discovered_mpn = mpn
                    break
        if not sku:
            if seed_fillin_from_legacy_cache(fp):
                updated += 1
            continue
        attempted += 1
        if prefetch_fillin_for_footprint(fp, sku=sku, force=force):
            dest = fillin_step_path(fp)
            if dest is not None and dest.is_file() and fillin_mesh_ok_for_footprint(dest, fp):
                updated += 1
                if discovered_mpn:
                    remember_discovered_lcsc(fp, sku, note=f"jlcsearch mpn:{discovered_mpn}")
                if db is not None:
                    _stamp_catalog_3d(db, board, fp, dest)
        else:
            remember_rejected_lcsc(fp, sku, note="prefetch install refused")
    return attempted, updated


def prefetch_fillin_for_skus(skus: list[str], *, db=None, force: bool = False) -> tuple[int, int]:
    """Fetch LCSC SKUs and install onto every map footprint that names that SKU."""
    from openhac.database.easyeda_integration import generate_footprint_from_lcsc
    from openhac.database.kicad_3d import (
        is_jedec_passive_footprint,
        library_3d_file_exists,
        should_skip_easyeda_3d,
        skip_3d_fillin_footprint,
    )

    attempted = 0
    updated = 0
    fmap = load_fillin_map()
    sku_to_fps: dict[str, list[str]] = {}
    for fp, entry in fmap.items():
        parsed = parse_fillin_source(entry.get("source"))
        if parsed and parsed[0] == "lcsc":
            sku_to_fps.setdefault(parsed[1], []).append(fp)
    for sku in skus:
        s = str(sku or "").strip()
        if not s.startswith("C"):
            continue
        attempted += 1
        fps = [
            fp
            for fp in (sku_to_fps.get(s) or [])
            if not is_jedec_passive_footprint(fp)
            and not skip_3d_fillin_footprint(fp)
            and not library_3d_file_exists(fp)
        ]
        row = None
        if db is not None:
            try:
                row = db.get_component_by_supplier_sku(s)
            except Exception:
                row = None
        if row and should_skip_easyeda_3d(row) and not fps:
            continue
        if force:
            for fp in fps:
                evict_fillin_step(fp, reason="--force")
        if fps and not force and all(fillin_step_on_disk(fp) for fp in fps):
            updated += 1
            continue
        _gen_fp, model_path = generate_footprint_from_lcsc(s)
        if not model_path or not os.path.isfile(str(model_path)):
            continue
        if fps:
            ok = False
            for fp in fps:
                if install_fillin_step(fp, model_path):
                    ok = True
            if ok:
                updated += 1
        elif row:
            fp = str(row.get("kicad_footprint") or "").strip()
            if (
                fp
                and not skip_3d_fillin_footprint(fp)
                and not is_jedec_passive_footprint(fp)
                and not library_3d_file_exists(fp)
            ):
                if install_fillin_step(fp, model_path):
                    updated += 1
    return attempted, updated


def _iter_board_comps(board):
    try:
        modules = board._get_all_modules() if hasattr(board, "_get_all_modules") else getattr(board, "modules", []) or []
    except Exception:
        modules = getattr(board, "modules", []) or []
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            yield comp


def _comp_footprint(comp) -> str:
    part = getattr(comp, "part", None)
    fp = str(getattr(part, "footprint", "") or "") if part is not None else ""
    if not fp:
        cd = getattr(comp, "_comp_data", None) or {}
        fp = str(cd.get("kicad_footprint") or "")
    return fp.strip()


def _catalog_lcsc_for_footprint(board, footprint: str, db) -> str | None:
    if db is None:
        return None
    for gn in _generics_for_footprint(board, footprint):
        try:
            row = db.get_component(gn)
        except Exception:
            row = None
        if not row:
            continue
        for key in ("easyeda_sku", "supplier_sku"):
            s = str(row.get(key) or "").strip()
            if s.upper().startswith("C") and s[1:].isdigit():
                return s
    return None


def _mpns_for_footprint(board, footprint: str, *, db=None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def _push(raw: Any) -> None:
        s = str(raw or "").strip()
        if not s or s in seen or len(_alnum_mpn(s)) < 5:
            return
        seen.add(s)
        out.append(s)

    for comp in _iter_board_comps(board):
        if _comp_footprint(comp) != footprint:
            continue
        cd = getattr(comp, "_comp_data", None) or {}
        part = getattr(comp, "part", None)
        fields = getattr(part, "fields", None) or {} if part is not None else {}
        for key in ("mpn", "manufacturer_mpn", "part_number", "Manufacturer_Part"):
            _push(cd.get(key))
        if isinstance(fields, dict):
            for key in ("MPN", "mpn", "Manufacturer_Part"):
                _push(fields.get(key))
        _push(getattr(part, "mpn", None) if part is not None else None)
        if db is not None:
            gn = str(getattr(comp, "generic_name", "") or "").strip()
            if gn:
                try:
                    row = db.get_component(gn)
                except Exception:
                    row = None
                if row:
                    _push(row.get("mpn"))
    return out


def _generics_for_footprint(board, footprint: str) -> list[str]:
    names: list[str] = []
    try:
        modules = board._get_all_modules() if hasattr(board, "_get_all_modules") else []
    except Exception:
        modules = []
    for mod in modules:
        for comp in getattr(mod, "components", []) or []:
            gn = str(getattr(comp, "generic_name", "") or "").strip()
            part = getattr(comp, "part", None)
            fp = str(getattr(part, "footprint", "") or "") if part is not None else ""
            if not fp:
                cd = getattr(comp, "_comp_data", None) or {}
                fp = str(cd.get("kicad_footprint") or "")
            if gn and fp.strip() == footprint:
                names.append(gn)
    return names


def _stamp_catalog_3d(db, board, footprint: str, dest: Path) -> None:
    from openhac.database.catalog_coverage import sha256_file

    fields = {
        "model_3d_local": str(dest.resolve()),
        "model_3d_source": "easyeda",
        "model_3d_license": "EasyEDA",
    }
    try:
        if dest.is_file():
            fields["model_3d_sha256"] = sha256_file(dest)
    except Exception:
        pass
    for gn in _generics_for_footprint(board, footprint):
        try:
            db.update_component_fields(gn, fields)
        except Exception:
            pass
