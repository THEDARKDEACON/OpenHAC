"""SPICE model registry, vendor dir resolution, and pin maps (SPS-010…018)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openhac.core.base import OpenHaCError

_PACKAGE_OVERLAY_DIR = Path(__file__).resolve().parent.parent / "database" / "spice_model_overlays"
_PACKAGE_MODELS_DIR = Path(__file__).resolve().parent.parent / "database" / "spice_models"

KINDS = frozenset({"primitive", "vendor", "physics", "behavioral"})
PRIMITIVE_PREFIXES = frozenset({"R", "C", "L", "V", "I"})

_registry_cache: list["SpiceModelRecord"] | None = None


@dataclass
class SpicePinMapEntry:
    num: str
    name: str
    subckt_index: int


@dataclass
class SpicePhysicsCheck:
    name: str
    analysis: str
    rails: dict[str, float]
    probe: str
    vmin: float
    vmax: float
    temp_c: float = 27.0
    load_ohm: float | None = None
    load_from: str | None = None


@dataclass
class SpiceModelRecord:
    generic_name: str = ""
    mpn: str = ""
    kind: str = "vendor"
    include: str = ""
    subckt: str = ""
    sha256: str = ""
    license: str = ""
    pin_map: list[SpicePinMapEntry] = field(default_factory=list)
    physics_checks: list[SpicePhysicsCheck] = field(default_factory=list)
    subckt_pin_count: int | None = None
    simulator: str = "ngspice"
    notes: str = ""

    def pin_map_hash(self) -> str:
        blob = json.dumps(
            [{"num": p.num, "name": p.name, "subckt_index": p.subckt_index} for p in self.pin_map],
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def ref_prefix(ref: str) -> str:
    m = re.match(r"^([A-Za-z]+)", str(ref or ""))
    return (m.group(1) if m else "X").upper()


def is_primitive_ref(ref: str) -> bool:
    return ref_prefix(ref) in PRIMITIVE_PREFIXES


def vendor_dir() -> Path | None:
    raw = (os.environ.get("OPENHAC_SPICE_VENDOR_DIR") or "").strip()
    if not raw:
        return None
    return Path(os.path.expanduser(raw))


def reset_spice_model_registry_cache() -> None:
    global _registry_cache
    _registry_cache = None


def _parse_pin_map(raw: Any) -> list[SpicePinMapEntry]:
    if not isinstance(raw, list) or not raw:
        raise OpenHaCError("SPS-010: pin_map must be a non-empty list.")
    out: list[SpicePinMapEntry] = []
    seen_idx: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise OpenHaCError("SPS-010: pin_map entries must be objects.")
        try:
            idx = int(item.get("subckt_index"))
        except (TypeError, ValueError) as e:
            raise OpenHaCError("SPS-010: pin_map.subckt_index must be an integer.") from e
        if idx < 1:
            raise OpenHaCError("SPS-010: pin_map.subckt_index is 1-based.")
        if idx in seen_idx:
            raise OpenHaCError(f"SPS-010: duplicate subckt_index {idx}.")
        seen_idx.add(idx)
        out.append(
            SpicePinMapEntry(
                num=str(item.get("num") or "").strip(),
                name=str(item.get("name") or "").strip(),
                subckt_index=idx,
            )
        )
    out.sort(key=lambda p: p.subckt_index)
    expected = list(range(1, len(out) + 1))
    got = [p.subckt_index for p in out]
    if got != expected:
        raise OpenHaCError(f"SPS-010: pin_map subckt_index must be contiguous 1..N, got {got}.")
    return out


def _parse_checks(raw: Any) -> list[SpicePhysicsCheck]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise OpenHaCError("SPS-010: physics_checks must be a list.")
    out: list[SpicePhysicsCheck] = []
    for item in raw:
        if not isinstance(item, dict):
            raise OpenHaCError("SPS-010: physics_checks entries must be objects.")
        rails = item.get("rails") or {}
        if not isinstance(rails, dict) or not all(isinstance(k, str) for k in rails):
            raise OpenHaCError("SPS-010: physics_checks.rails must be a string→number map.")
        try:
            vmin = float(item["vmin"])
            vmax = float(item["vmax"])
        except (KeyError, TypeError, ValueError) as e:
            raise OpenHaCError("SPS-010: physics_checks need numeric vmin/vmax.") from e
        load = item.get("load_ohm")
        out.append(
            SpicePhysicsCheck(
                name=str(item.get("name") or "check").strip() or "check",
                analysis=str(item.get("analysis") or ".op").strip() or ".op",
                rails={str(k): float(v) for k, v in rails.items()},
                probe=str(item.get("probe") or "").strip(),
                vmin=vmin,
                vmax=vmax,
                temp_c=float(item.get("temp_c") or 27.0),
                load_ohm=float(load) if load is not None else None,
                load_from=str(item.get("load_from") or item.get("probe") or "").strip() or None,
            )
        )
    return out


def parse_model_record(raw: dict[str, Any]) -> SpiceModelRecord:
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise OpenHaCError(f"SPS-010: kind must be one of {sorted(KINDS)}, got {kind!r}.")
    gn = str(raw.get("generic_name") or "").strip()
    mpn = str(raw.get("mpn") or "").strip()
    if not gn and not mpn:
        raise OpenHaCError("SPS-010: record needs generic_name and/or mpn.")
    rec = SpiceModelRecord(
        generic_name=gn,
        mpn=mpn,
        kind=kind,
        include=str(raw.get("include") or "").strip(),
        subckt=str(raw.get("subckt") or "").strip(),
        sha256=str(raw.get("sha256") or "").strip().lower(),
        license=str(raw.get("license") or "").strip(),
        simulator=str(raw.get("simulator") or "ngspice").strip() or "ngspice",
        notes=str(raw.get("notes") or "").strip(),
    )
    if kind != "primitive":
        rec.pin_map = _parse_pin_map(raw.get("pin_map"))
        if not rec.subckt:
            raise OpenHaCError("SPS-010: non-primitive records need subckt.")
        if not rec.include:
            raise OpenHaCError("SPS-010: non-primitive records need include.")
        rec.physics_checks = _parse_checks(raw.get("physics_checks"))
        if kind in ("vendor", "physics") and not rec.physics_checks:
            raise OpenHaCError("SPS-010: vendor/physics records need physics_checks.")
    spc = raw.get("subckt_pin_count")
    if spc is not None:
        rec.subckt_pin_count = int(spc)
        if rec.pin_map and rec.subckt_pin_count != len(rec.pin_map):
            raise OpenHaCError("SPS-018: subckt_pin_count must equal len(pin_map).")
    return rec


def _parse_overlay_payload(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        if "models" in raw and isinstance(raw["models"], list):
            return [x for x in raw["models"] if isinstance(x, dict)]
        return [raw]
    return []


def _load_json_records(path: Path) -> list[SpiceModelRecord]:
    text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    return [parse_model_record(d) for d in _parse_overlay_payload(raw)]


def load_spice_model_registry(*, extra_paths: list[Path] | None = None) -> list[SpiceModelRecord]:
    global _registry_cache
    if _registry_cache is not None and not extra_paths:
        return list(_registry_cache)
    records: list[SpiceModelRecord] = []
    if _PACKAGE_OVERLAY_DIR.is_dir() and os.environ.get("OPENHAC_NO_BUNDLED_SPICE_MODELS", "").strip() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        for p in sorted(_PACKAGE_OVERLAY_DIR.glob("*.json")):
            records.extend(_load_json_records(p))
    env_ov = (os.environ.get("OPENHAC_SPICE_MODEL_OVERLAY") or "").strip()
    paths: list[Path] = []
    if env_ov:
        for chunk in env_ov.split(os.pathsep):
            if chunk.strip():
                paths.append(Path(chunk.strip()))
    for p in extra_paths or ():
        paths.append(Path(p))
    for p in paths:
        if p.is_dir():
            for f in sorted(p.glob("*.json")):
                records.extend(_load_json_records(f))
        elif p.is_file():
            records.extend(_load_json_records(p))
    if extra_paths:
        return records
    _registry_cache = records
    return list(records)


def expand_include_path(include: str) -> Path:
    s = str(include or "").strip()
    vdir = vendor_dir()
    if "${OPENHAC_SPICE_VENDOR_DIR}" in s:
        if vdir is None:
            raise OpenHaCError(
                "SPS-011: include uses ${OPENHAC_SPICE_VENDOR_DIR} but OPENHAC_SPICE_VENDOR_DIR is unset."
            )
        s = s.replace("${OPENHAC_SPICE_VENDOR_DIR}", str(vdir))
    p = Path(os.path.expanduser(s))
    if not p.is_absolute():
        # Bundled physics/behavioral models live next to overlays.
        bundled = _PACKAGE_MODELS_DIR / p.name if p.name == p.as_posix() else _PACKAGE_MODELS_DIR / p
        if bundled.is_file():
            return bundled
        if vdir is not None:
            cand = vdir / p
            if cand.is_file():
                return cand
    return p


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_subckt_pin_count(text: str, subckt: str) -> int | None:
    """Return arity of `.subckt NAME n1 n2 ...` or None if not found."""
    name = (subckt or "").strip()
    if not name:
        return None
    pat = re.compile(rf"^\s*\.subckt\s+{re.escape(name)}\s+(.*)$", re.IGNORECASE | re.MULTILINE)
    m = pat.search(text or "")
    if not m:
        return None
    rest = m.group(1).strip()
    if not rest:
        return 0
    # Stop at params like PARAMS: ...
    rest = re.split(r"\bparams\s*:", rest, maxsplit=1, flags=re.IGNORECASE)[0]
    toks = [t for t in rest.split() if t]
    return len(toks)


def verify_record_file(rec: SpiceModelRecord, *, signoff: bool) -> Path | None:
    """Resolve include path; under sign-off require existence + checksum for vendor."""
    if rec.kind == "primitive" or not rec.include:
        return None
    path = expand_include_path(rec.include)
    if not path.is_file():
        if signoff or rec.kind == "vendor":
            raise OpenHaCError(f"SPS-014: SPICE model file not found: {path} (kind={rec.kind}).")
        return None
    if rec.kind == "vendor" and rec.sha256:
        digest = file_sha256(path)
        if digest.lower() != rec.sha256.lower():
            raise OpenHaCError(
                f"SPS-011: sha256 mismatch for {path}: expected {rec.sha256}, got {digest}."
            )
    if rec.kind != "primitive":
        text = path.read_text(encoding="utf-8", errors="replace")
        arity = parse_subckt_pin_count(text, rec.subckt)
        if arity is not None and rec.pin_map and arity != len(rec.pin_map):
            raise OpenHaCError(
                f"SPS-018: .subckt {rec.subckt!r} has {arity} terminals but pin_map has {len(rec.pin_map)}."
            )
        if rec.subckt_pin_count is not None and arity is not None and rec.subckt_pin_count != arity:
            raise OpenHaCError(
                f"SPS-018: subckt_pin_count={rec.subckt_pin_count} but file arity is {arity}."
            )
    return path


def record_from_part_fields(part) -> SpiceModelRecord | None:
    fields = getattr(part, "fields", None) or {}
    subckt = str(fields.get("Spice_Subckt") or "").strip()
    include = str(fields.get("Spice_Include") or fields.get("spice_model_path") or "").strip()
    kind = str(fields.get("Spice_Kind") or "").strip().lower()
    raw_map = fields.get("Spice_Pin_Map") or fields.get("spice_pin_map_json") or ""
    if not subckt and not include and not raw_map:
        return None
    pin_map: list[SpicePinMapEntry] = []
    if raw_map:
        parsed = json.loads(raw_map) if isinstance(raw_map, str) else raw_map
        pin_map = _parse_pin_map(parsed)
    if not kind:
        kind = "vendor" if subckt else "primitive"
    rec = SpiceModelRecord(
        kind=kind if kind in KINDS else "vendor",
        include=include,
        subckt=subckt,
        sha256=str(fields.get("Spice_Model_Sha256") or "").strip().lower(),
        pin_map=pin_map,
        license=str(fields.get("Spice_License") or "").strip(),
    )
    return rec


def lookup_registry(
    *,
    generic_name: str = "",
    mpn: str = "",
    extra_paths: list[Path] | None = None,
) -> SpiceModelRecord | None:
    gn = (generic_name or "").strip()
    mp = (mpn or "").strip()
    for rec in load_spice_model_registry(extra_paths=extra_paths):
        if gn and rec.generic_name and rec.generic_name == gn:
            return rec
        if mp and rec.mpn and rec.mpn == mp:
            return rec
    return None


def stamp_part_from_record(part, rec: SpiceModelRecord, *, resolved_include: Path | None) -> None:
    if not hasattr(part, "fields") or part.fields is None:
        part.fields = {}
    if rec.include:
        inc = str(resolved_include) if resolved_include is not None else rec.include
        part.fields["Spice_Include"] = inc
    if rec.subckt:
        part.fields["Spice_Subckt"] = rec.subckt
    if rec.pin_map:
        part.fields["Spice_Pin_Map"] = json.dumps(
            [{"num": p.num, "name": p.name, "subckt_index": p.subckt_index} for p in rec.pin_map]
        )
    part.fields["Spice_Kind"] = rec.kind
    if rec.sha256:
        part.fields["Spice_Model_Sha256"] = rec.sha256
    if resolved_include is not None and rec.kind == "vendor":
        part.fields["Spice_Model_Sha256"] = file_sha256(resolved_include)


def resolve_part_model(
    part,
    *,
    signoff: bool,
    extra_paths: list[Path] | None = None,
) -> SpiceModelRecord | None:
    """Resolve a model for *part*; stamp fields; verify files under sign-off."""
    ref = str(getattr(part, "refdes", None) or getattr(part, "ref", "") or "")
    if is_primitive_ref(ref):
        return SpiceModelRecord(kind="primitive")
    fields = getattr(part, "fields", None) or {}
    rec = record_from_part_fields(part)
    if rec is None or (not rec.subckt and not rec.include):
        gn = str(fields.get("Value") or getattr(part, "name", "") or "").strip()
        mpn = str(fields.get("MPN") or fields.get("mpn") or "").strip()
        rec = lookup_registry(generic_name=gn, mpn=mpn, extra_paths=extra_paths)
    if rec is None:
        return None
    path = verify_record_file(rec, signoff=signoff)
    stamp_part_from_record(part, rec, resolved_include=path)
    return rec
