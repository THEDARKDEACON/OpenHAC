"""KiCad library 3D pointers for stock footprints (3D-002).

Do not EasyEDA-JIT a second cube when a stock ``${KICAD*_3DMODEL_DIR}`` model
exists or the footprint uses a documented library path pattern.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from openhac.database.cad_ids import is_generated_cad_id, is_stock_kicad_id

_JEDEC_IMPERIAL = {
    "0201": "0603Metric",
    "0402": "1005Metric",
    "0603": "1608Metric",
    "0805": "2012Metric",
    "1206": "3216Metric",
    "1210": "3225Metric",
    "1812": "4532Metric",
    "2010": "5025Metric",
    "2512": "6332Metric",
}

_LIB_DIR_ENVS = (
    "KICAD10_3DMODEL_DIR",
    "KICAD9_3DMODEL_DIR",
    "KICAD8_3DMODEL_DIR",
    "KICAD7_3DMODEL_DIR",
    "KICAD6_3DMODEL_DIR",
    "KICAD_3DMODEL_DIR",
)

# Stock .kicad_mod files on KiCad 9 (and many 10 installs) expand KICAD9_*.
_TOKEN_ENV_PREF = (
    "KICAD9_3DMODEL_DIR",
    "KICAD10_3DMODEL_DIR",
    "KICAD8_3DMODEL_DIR",
    "KICAD7_3DMODEL_DIR",
    "KICAD6_3DMODEL_DIR",
    "KICAD_3DMODEL_DIR",
)

_GENERATED_3D_MARKERS = (
    "jlc2kicad_generated",
    "easyeda_generated",
    "easyeda_generated.3dshapes",
)

_DEFAULT_3D_DIRS = {
    "linux": (
        "/usr/share/kicad/3dmodels",
        "/usr/share/kicad/packages3d",
        "/usr/local/share/kicad/3dmodels",
        os.path.expanduser("~/.local/share/kicad/9.0/3dmodels"),
        os.path.expanduser("~/.local/share/kicad/8.0/3dmodels"),
        os.path.expanduser("~/.local/share/kicad/10.0/3dmodels"),
    ),
    "win32": (
        r"C:\Program Files\KiCad\10.0\share\kicad\3dmodels",
        r"C:\Program Files\KiCad\9.0\share\kicad\3dmodels",
        r"C:\Program Files\KiCad\8.0\share\kicad\3dmodels",
        r"C:\Program Files (x86)\KiCad\9.0\share\kicad\3dmodels",
    ),
    "darwin": (
        "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels",
        "/Applications/KiCad.app/Contents/SharedSupport/3dmodels",
    ),
}


def _dir_looks_like_3dmodels(path: str) -> bool:
    p = Path(os.path.expanduser(path))
    if not p.is_dir():
        return False
    try:
        return any(p.glob("*.3dshapes"))
    except OSError:
        return False


def _platform_3d_candidates() -> list[str]:
    plat = sys.platform
    if plat.startswith("linux"):
        keys = ("linux",)
    elif plat == "win32":
        keys = ("win32",)
    elif plat == "darwin":
        keys = ("darwin",)
    else:
        keys = ("linux", "darwin", "win32")
    out: list[str] = []
    for k in keys:
        out.extend(_DEFAULT_3D_DIRS.get(k, ()))
    return out


def _sibling_3dmodels_from_footprint_env() -> list[str]:
    out: list[str] = []
    for key in (
        "KICAD10_FOOTPRINT_DIR",
        "KICAD9_FOOTPRINT_DIR",
        "KICAD8_FOOTPRINT_DIR",
        "KICAD_FOOTPRINT_DIR",
    ):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        parent = Path(os.path.expanduser(raw)).resolve().parent
        out.append(str(parent / "3dmodels"))
        out.append(str(parent / "packages3d"))
    return out


def kicad_3dmodel_dir() -> str | None:
    """Absolute KiCad 3D pack root, from env or a known install path."""
    for key in _LIB_DIR_ENVS:
        raw = (os.environ.get(key) or "").strip()
        if raw and _dir_looks_like_3dmodels(raw):
            return str(Path(os.path.expanduser(raw)).resolve())
        if raw and os.path.isdir(os.path.expanduser(raw)):
            return str(Path(os.path.expanduser(raw)).resolve())
    for cand in _sibling_3dmodels_from_footprint_env() + _platform_3d_candidates():
        if _dir_looks_like_3dmodels(cand):
            return str(Path(os.path.expanduser(cand)).resolve())
    return None


def kicad_3dmodel_env_key() -> str:
    for key in _TOKEN_ENV_PREF:
        if (os.environ.get(key) or "").strip():
            return key
    for n in (9, 10, 8, 7, 6):
        if (os.environ.get(f"KICAD{n}_SYMBOL_DIR") or "").strip() or (
            os.environ.get(f"KICAD{n}_FOOTPRINT_DIR") or ""
        ).strip():
            return f"KICAD{n}_3DMODEL_DIR"
    return "KICAD9_3DMODEL_DIR"


def kicad_3dmodel_env_token() -> str:
    return "${%s}" % kicad_3dmodel_env_key()


def ensure_kicad_3d_env() -> str | None:
    """Seed ``KICAD*_3DMODEL_DIR`` when unset so pcbnew and audits can expand tokens."""
    d = kicad_3dmodel_dir()
    if not d:
        return None
    # Do not setdefault KICAD10 on a KiCad 9 install — footprints expand KICAD9.
    for key in (
        "KICAD9_3DMODEL_DIR",
        "KICAD8_3DMODEL_DIR",
        "KICAD7_3DMODEL_DIR",
        "KICAD6_3DMODEL_DIR",
        "KICAD_3DMODEL_DIR",
    ):
        os.environ.setdefault(key, d)
    return d


def kicad_project_3d_env_vars() -> dict[str, str]:
    """Project-file path map so KiCad GUI can expand ``${KICAD*_3DMODEL_DIR}``."""
    d = kicad_3dmodel_dir()
    if not d:
        return {}
    key = kicad_3dmodel_env_key()
    out = {key: d, "KICAD9_3DMODEL_DIR": d}
    return out


def expand_3d_path(raw: str | None) -> str:
    """Replace ``${KICAD*_3DMODEL_DIR}`` using env or the detected 3D pack root."""
    s = str(raw or "").strip()
    if not s:
        return ""
    root = kicad_3dmodel_dir() or ""
    for key in _LIB_DIR_ENVS:
        token = "${%s}" % key
        if token not in s:
            continue
        val = (os.environ.get(key) or "").strip() or root
        if val:
            s = s.replace(token, val)
    return os.path.expanduser(s)


def is_kicad_lib_3d_pointer(path: str | None) -> bool:
    s = str(path or "")
    return "${KICAD" in s and "3DMODEL_DIR" in s


def is_generated_3d_path(path: str | None) -> bool:
    s = str(path or "").replace("\\", "/").lower()
    if not s:
        return False
    if is_generated_cad_id(s):
        return True
    return any(m in s for m in _GENERATED_3D_MARKERS)


def _imperial_from_footprint(fp: str) -> str | None:
    m = re.search(r"(0201|0402|0603|0805|1206|1210|1812|2010|2512)", fp)
    return m.group(1) if m else None


def library_3d_relpath_for_footprint(footprint: str | None) -> str | None:
    """Return ``Lib.3dshapes/Name.wrl`` relative to KICAD*_3DMODEL_DIR, or None."""
    fp = str(footprint or "").strip()
    if not fp or ":" not in fp:
        return None
    lib, _, name = fp.partition(":")
    lib = lib.strip()
    name = name.strip()
    if not lib or not name or is_generated_cad_id(fp):
        return None

    if lib in ("Resistor_SMD", "Capacitor_SMD", "Inductor_SMD", "LED_SMD", "Diode_SMD"):
        return f"{lib}.3dshapes/{name}.wrl"
    if lib == "Crystal" or lib.startswith("Crystal"):
        return f"{lib}.3dshapes/{name}.wrl"
    if lib == "Package_SO":
        return f"Package_SO.3dshapes/{name}.wrl"
    if lib == "Package_TO_SOT_SMD":
        return f"Package_TO_SOT_SMD.3dshapes/{name}.wrl"
    if lib == "Package_DIP":
        return f"Package_DIP.3dshapes/{name}.wrl"
    imperial = _imperial_from_footprint(name)
    if imperial and lib.startswith("Resistor"):
        metric = _JEDEC_IMPERIAL[imperial]
        return f"Resistor_SMD.3dshapes/R_{imperial}_{metric}.wrl"
    if re.match(r"^[A-Za-z0-9_.-]+$", lib) and name:
        return f"{lib}.3dshapes/{name}.wrl"
    return None


def _alias_stems(stem: str) -> list[str]:
    """KiCad footprint vs 3D pack name mismatches (VSSOP-10 vs MSOP-10)."""
    names = [stem]
    if stem.startswith("VSSOP-"):
        names.append("MSOP-" + stem[len("VSSOP-") :])
    elif stem.startswith("HVSSOP-"):
        names.append("MSOP-" + stem[len("HVSSOP-") :])
    elif stem.startswith("MSOP-") and not stem.startswith("MSOP-10-1EP"):
        names.append("VSSOP-" + stem[len("MSOP-") :])
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def candidate_3d_relpaths(rel: str | None) -> list[str]:
    """Ordered ``Lib.3dshapes/Name.ext`` guesses (.step first; VSSOP↔MSOP)."""
    s = str(rel or "").strip()
    if not s:
        return []
    p = Path(s)
    parent = p.parent
    stems = _alias_stems(p.stem)
    out: list[str] = []
    seen: set[str] = set()
    for stem in stems:
        for suf in (".step", ".wrl", ".stp"):
            cand = str(parent / f"{stem}{suf}") if str(parent) != "." else f"{stem}{suf}"
            cand = cand.replace("\\", "/")
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
    return out


_QFN_EP = re.compile(
    r"^(?P<pre>(?:HV)?QFN-\d+(?:-1EP)?_\d+(?:\.\d+)?x\d+(?:\.\d+)?mm_P\d+(?:\.\d+)?mm)"
    r"_EP(?P<ew>\d+(?:\.\d+)?)x(?P<eh>\d+(?:\.\d+)?)mm$",
    re.I,
)
_JEDEC_STEM = re.compile(
    r"^(?:HV)?QFN-|VQFN-|WQFN-|LGA-|BGA-|SOIC-|SOT-|LQFP-|TQFP-|DIP-|MSOP-|VSSOP-",
    re.I,
)
_VENDOR_PREFIX = re.compile(r"^(?:InvenSense|Bosch|Texas|TI)_", re.I)


def _rel_under_pack(path: Path, root: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return str(rel).replace("\\", "/")


def tokenize_pack_3d_path(abs_path: str | Path) -> str:
    """Prefer ``${KICAD*_3DMODEL_DIR}/rel`` when *abs_path* is inside the pack."""
    raw = str(abs_path)
    root = kicad_3dmodel_dir()
    if not root:
        return raw
    rel = _rel_under_pack(Path(raw), Path(root))
    if rel:
        return f"{kicad_3dmodel_env_token()}/{rel}"
    return os.path.abspath(raw)


def _ep_near_miss_relpath(base: Path, rel: str) -> str | None:
    """Same QFN body/pitch; exposed pad within 0.2 mm (KiCad pack naming drift)."""
    p = Path(rel)
    folder = base / p.parent
    if not folder.is_dir():
        return None
    m = _QFN_EP.match(p.stem)
    if not m:
        return None
    pre = m.group("pre")
    ew, eh = float(m.group("ew")), float(m.group("eh"))
    best: Path | None = None
    best_d = 0.21
    pat = re.compile(
        rf"^{re.escape(pre)}_EP(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)mm$",
        re.I,
    )
    try:
        names = list(folder.iterdir())
    except OSError:
        return None
    for cand in names:
        if cand.suffix.lower() not in (".step", ".wrl", ".stp"):
            continue
        mm = pat.match(cand.stem)
        if not mm:
            continue
        d = max(abs(float(mm.group(1)) - ew), abs(float(mm.group(2)) - eh))
        rank = (d, cand.suffix.lower() != ".step")
        if best is None or rank < (best_d, best.suffix.lower() != ".step"):
            best_d = d
            best = cand
    if best is None or best_d > 0.2:
        return None
    return str(p.parent / best.name).replace("\\", "/")


def _vendor_stripped_relpath(base: Path, rel: str) -> str | None:
    p = Path(rel)
    stem = _VENDOR_PREFIX.sub("", p.stem)
    if stem == p.stem or not _JEDEC_STEM.match(stem):
        return None
    folder = base / p.parent
    for suf in (".step", ".wrl", ".stp"):
        cand = folder / f"{stem}{suf}"
        if cand.is_file():
            return str(p.parent / cand.name).replace("\\", "/")
    return None


def resolve_relpath_in_pack(rel: str | None) -> str | None:
    """Resolve a ``Lib.3dshapes/Name.ext`` guess to a file that exists in the pack."""
    s = str(rel or "").strip()
    if not s:
        return None
    root = kicad_3dmodel_dir()
    if not root:
        return None
    base = Path(root)
    for cand in candidate_3d_relpaths(s):
        if (base / cand).is_file():
            return cand
    hit = _ep_near_miss_relpath(base, s)
    if hit:
        return hit
    return _vendor_stripped_relpath(base, s)


def resolve_declared_3d_filename(raw: str | None) -> str | None:
    """Resolve a path copied from a stock ``.kicad_mod`` (token or absolute).

    Uses the footprint's own 3D library folder (e.g. Package_DFN_QFN for an
    InvenSense sensor), then VSSOP/MSOP and QFN-EP near-miss aliases.
    """
    s = str(raw or "").strip()
    if not s:
        return None
    expanded = Path(expand_3d_path(s))
    if expanded.is_file():
        return tokenize_pack_3d_path(expanded)
    root = kicad_3dmodel_dir()
    if not root:
        return None
    rel = None
    if "${KICAD" in s and "3DMODEL_DIR" in s:
        _, _, tail = s.partition("}/")
        rel = tail.replace("\\", "/").lstrip("/")
    else:
        rel = _rel_under_pack(expanded, Path(root))
    if not rel:
        return None
    hit = resolve_relpath_in_pack(rel)
    if not hit:
        return None
    return f"{kicad_3dmodel_env_token()}/{hit}"


def resolve_library_3d_relpath(footprint: str | None) -> str | None:
    """Relative 3D path that exists on disk, or None."""
    rel = library_3d_relpath_for_footprint(footprint)
    if not rel:
        return None
    return resolve_relpath_in_pack(rel)


def library_3d_pointer_for_footprint(footprint: str | None) -> str | None:
    """Token path only when the pack file exists (3D-004: no dangling pointers)."""
    resolved = resolve_library_3d_relpath(footprint)
    if resolved:
        return f"{kicad_3dmodel_env_token()}/{resolved}"
    return resolve_declared_3d_filename(stock_mod_3d_filename(footprint))


def is_jedec_passive_footprint(footprint: str | None) -> bool:
    """Two-terminal chip passives — never EasyEDA-JIT a second cube (3D-002)."""
    fp = str(footprint or "")
    if fp.startswith(
        (
            "Resistor_SMD:",
            "Capacitor_SMD:",
            "Inductor_SMD:",
            "LED_SMD:",
            "Diode_SMD:",
            "Fuse:",
        )
    ):
        return True
    if _imperial_from_footprint(fp) and any(
        tag in fp for tag in ("Resistor", "Capacitor", "Inductor", "LED", "Diode", "Fuse")
    ):
        return True
    return False


def skip_3d_fillin_footprint(footprint: str | None) -> bool:
    """Pads / holes have no body to fetch."""
    fp = str(footprint or "")
    return fp.startswith(
        (
            "TestPoint:",
            "MountingHole:",
            "Fiducial:",
            "Mechanical:",
        )
    )


def _footprint_pretty_roots() -> list[Path]:
    out: list[Path] = []
    for key in (
        "KICAD10_FOOTPRINT_DIR",
        "KICAD9_FOOTPRINT_DIR",
        "KICAD8_FOOTPRINT_DIR",
        "KICAD_FOOTPRINT_DIR",
    ):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            out.append(Path(os.path.expanduser(raw)))
    out.append(Path("/usr/share/kicad/footprints"))
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        k = str(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def stock_mod_3d_filename(footprint: str | None) -> str | None:
    """First ``(model "...")`` from the stock ``Lib.pretty/Name.kicad_mod``, if any."""
    fp = str(footprint or "").strip()
    if ":" not in fp or is_generated_cad_id(fp):
        return None
    lib, _, name = fp.partition(":")
    lib, name = lib.strip(), name.strip()
    if not lib or not name:
        return None
    for root in _footprint_pretty_roots():
        p = root / f"{lib}.pretty" / f"{name}.kicad_mod"
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = re.search(r'\(model\s+"([^"]+)"', text)
        if m:
            return m.group(1)
    return None


def library_3d_file_exists(footprint: str | None) -> bool:
    if resolve_library_3d_relpath(footprint) is not None:
        return True
    return resolve_declared_3d_filename(stock_mod_3d_filename(footprint)) is not None


def should_skip_easyeda_3d(row: dict) -> bool:
    """True when EasyEDA must not supply 3D (KiCad mesh exists, or JEDEC passive).

    Stock connectors with no KiCad STEP (HRO USB-C, Molex microSD) may fill in an
    EasyEDA mesh. The stock KiCad footprint is never replaced.
    """
    fp = str(row.get("kicad_footprint") or "").strip()
    if is_jedec_passive_footprint(fp):
        return True
    if skip_3d_fillin_footprint(fp):
        return True
    if is_stock_kicad_id(fp) and library_3d_file_exists(fp):
        return True
    src = str(row.get("model_3d_source") or "").strip().lower()
    if src == "kicad_lib" and library_3d_file_exists(fp):
        return True
    return False


def library_3d_fields_for_row(row: dict) -> dict:
    fp = str(row.get("kicad_footprint") or "").strip()
    pointer = library_3d_pointer_for_footprint(fp)
    if not pointer:
        return {}
    return {
        "model_3d_local": pointer,
        "model_3d_source": "kicad_lib",
    }


_JEDEC_CUBE_STEM = re.compile(
    r"^(R|C|L|LED)(0201|0402|0603|0805|1206|1210|1812|2010|2512)(?:[_.\-]|$)",
    re.I,
)


def is_jedec_placeholder_3d(path: str | None) -> bool:
    """True for leftover R0805/C0805 cubes that must not land on a connector."""
    stem = Path(str(path or "")).stem
    if not stem:
        return False
    if _JEDEC_CUBE_STEM.match(stem):
        return True
    return bool(re.match(r"^(R|C|L)\d{4}$", stem, re.I))


_PKG_TOKEN = re.compile(
    r"\b(QFN|DFN|BGA|LGA|WLCSP|SOIC|SSOP|TSSOP|MSOP|VSSOP|LQFP|TQFP|QFP|SOP|"
    r"SOT(?:[\-_]?\d+)?)\b",
    re.I,
)
_CARTESIAN_PT = re.compile(
    r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*([-0-9.eE]+)\s*,\s*([-0-9.eE]+)\s*,\s*([-0-9.eE]+)"
)
_FP_LINE_XY = re.compile(
    r"\(fp_line\s+\(start\s+([-0-9.]+)\s+([-0-9.]+)\)\s+\(end\s+([-0-9.]+)\s+([-0-9.]+)\)"
)
_STEP_FILE_NAME = re.compile(r"FILE_NAME\s*\(\s*'([^']+)'", re.I)
_STEP_PRODUCT = re.compile(r"PRODUCT\s*\(\s*'([^']+)'", re.I)
_IC_PKG = frozenset(
    {
        "QFN",
        "DFN",
        "BGA",
        "LGA",
        "WLCSP",
        "SOIC",
        "SOP",
        "SSOP",
        "TSSOP",
        "MSOP",
        "VSSOP",
        "LQFP",
        "TQFP",
        "QFP",
        "SOT",
    }
)


def _canonical_pkg(token: str | None) -> str | None:
    if not token:
        return None
    t = str(token).upper().replace("_", "-")
    if t.startswith("SOT"):
        return "SOT"
    if t in ("SOP", "SOIC"):
        return "SOIC"
    if t in _IC_PKG:
        return t
    return None


def package_kind_from_text(text: str | None) -> str | None:
    """SOIC / QFN / SOT / … from a footprint name, STEP id, or LCSC package string."""
    blob = str(text or "")
    m = _PKG_TOKEN.search(blob)
    if not m:
        return None
    return _canonical_pkg(m.group(1))


def footprint_body_class(footprint: str | None) -> str:
    """``skip`` | ``passive`` | ``connector`` | ``module`` | ``ic``."""
    fp = str(footprint or "").strip()
    lib, _, name = fp.partition(":")
    lib, name = lib.strip(), name.strip()
    blob = f"{lib} {name}".lower()
    if skip_3d_fillin_footprint(fp):
        return "skip"
    if is_jedec_passive_footprint(fp):
        return "passive"
    if lib.startswith("Connector") or "usb" in blob or "microsd" in blob or "tf-card" in blob:
        return "connector"
    if lib in {"RF_Module", "RF"} or any(
        t in blob for t in ("breakout", "module", "wroom", "adafruit", "hoperf", "rfm9")
    ):
        return "module"
    if lib.startswith("Display"):
        return "module"
    if lib.startswith("Package_") or package_kind_from_text(name):
        return "ic"
    if "breakout" in name.lower() or "module" in name.lower():
        return "module"
    return "ic"


def step_identity_text(path: str | Path | None) -> str:
    """FILE_NAME / PRODUCT / stem — enough to spot a QFN cube vs a connector body."""
    p = Path(str(path or ""))
    parts = [p.stem, p.name]
    try:
        head = p.read_bytes()[:12288].decode("utf-8", "ignore")
    except OSError:
        return " ".join(parts)
    for cre in (_STEP_FILE_NAME, _STEP_PRODUCT):
        m = cre.search(head)
        if m:
            parts.append(m.group(1))
    return " ".join(parts)


def step_xy_span_mm(path: str | Path | None) -> tuple[float, float] | None:
    p = Path(str(path or ""))
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for m in _CARTESIAN_PT.finditer(text):
        try:
            xs.append(float(m.group(1)))
            ys.append(float(m.group(2)))
        except (TypeError, ValueError):
            continue
        if len(xs) >= 8000:
            break
    if len(xs) < 2:
        return None
    return (max(xs) - min(xs), max(ys) - min(ys))


def footprint_courtyard_span_mm(footprint: str | None) -> tuple[float, float] | None:
    fp = str(footprint or "").strip()
    if ":" not in fp or is_generated_cad_id(fp):
        return None
    lib, _, name = fp.partition(":")
    lib, name = lib.strip(), name.strip()
    if not lib or not name:
        return None
    for root in _footprint_pretty_roots():
        p = root / f"{lib}.pretty" / f"{name}.kicad_mod"
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        xs: list[float] = []
        ys: list[float] = []
        for m in _FP_LINE_XY.finditer(text):
            window = text[m.start() : m.start() + 480]
            if "CrtYd" not in window:
                continue
            try:
                x1, y1, x2, y2 = (float(m.group(i)) for i in range(1, 5))
            except (TypeError, ValueError):
                continue
            xs.extend((x1, x2))
            ys.extend((y1, y2))
        if len(xs) >= 2:
            return (max(xs) - min(xs), max(ys) - min(ys))
    return None


def fillin_mesh_ok_for_footprint(path: str | Path | None, footprint: str | None) -> bool:
    """False when a fill-in STEP is the wrong body (QFN on a TH module, R0805 cube, …)."""
    raw = str(path or "").strip()
    if not raw:
        return False
    p = Path(raw)
    if not p.is_file():
        return False
    if is_jedec_placeholder_3d(str(p)):
        return False
    fp = str(footprint or "").strip()
    fp_class = footprint_body_class(fp)
    if fp_class == "skip":
        return False
    ident = step_identity_text(p)
    mesh_pkg = package_kind_from_text(ident)
    fp_pkg = package_kind_from_text(fp.partition(":")[2] or fp)
    if fp_class in {"module", "connector"} and mesh_pkg in _IC_PKG:
        return False
    if fp_class == "ic" and mesh_pkg and fp_pkg and mesh_pkg != fp_pkg:
        return False
    if fp_class in {"module", "connector"}:
        span = step_xy_span_mm(p)
        court = footprint_courtyard_span_mm(fp)
        if span and court:
            step_max = max(span)
            court_min = min(d for d in court if d > 0.5) if any(d > 0.5 for d in court) else 0.0
            if court_min >= 8.0 and step_max < 0.5 * court_min:
                return False
    return True


def jlc_item_ok_for_footprint(footprint: str | None, item: dict | None) -> bool:
    """Skip bare IC packages when the KiCad footprint is a module or connector."""
    if not isinstance(item, dict):
        return False
    fp = str(footprint or "").strip()
    if not fp:
        return True
    fp_class = footprint_body_class(fp)
    pkg = str(item.get("package") or item.get("Package") or item.get("footprint") or "")
    item_pkg = package_kind_from_text(pkg)
    if fp_class in {"module", "connector"} and item_pkg in _IC_PKG:
        return False
    fp_pkg = package_kind_from_text(fp.partition(":")[2] or fp)
    if fp_class == "ic" and fp_pkg and item_pkg and fp_pkg != item_pkg:
        return False
    return True


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def footprint_3d_match_keys(footprint: str | None) -> list[str]:
    name = str(footprint or "")
    if ":" in name:
        name = name.partition(":")[2]
    keys: list[str] = []
    for pat in (
        r"TYPE-?C-?31-?M-?1[27]",
        r"47219-?2001",
        r"MICROSD",
        r"TF-?CARD",
    ):
        m = re.search(pat, name, re.I)
        if m:
            keys.append(_alnum(m.group(0)))
    return keys


def easyeda_mesh_ok_for_stock_footprint(path: str | None, footprint: str | None) -> bool:
    """Allow EasyEDA/JLC STEP on a stock footprint only when the filename matches the part."""
    raw = str(path or "").strip()
    if not raw or is_jedec_placeholder_3d(raw):
        return False
    stem_c = _alnum(Path(raw).stem)
    if not stem_c:
        return False
    keys = footprint_3d_match_keys(footprint)
    for k in keys:
        if len(k) >= 6 and k in stem_c:
            return True
    fp_c = _alnum(str(footprint or "").partition(":")[2] or str(footprint or ""))
    if "microsd" in fp_c or "472192001" in fp_c:
        return any(x in stem_c for x in ("microsd", "tfcard", "472192001", "sdcard"))
    return False


def generated_3d_search_dirs() -> list[Path]:
    extra = (os.environ.get("OPENHAC_3D_CACHE_DIRS") or "").strip()
    out: list[Path] = []
    if extra:
        out.extend(Path(p.strip()) for p in extra.split(os.pathsep) if p.strip())
    home = Path.home() / ".kiro" / "openhac"
    out.extend(
        [
            home / "easyeda_generated.3dshapes",
            home / "jlc2kicad_generated" / "jlc2kicad_generated" / "packages3d",
            home / "jlc2kicad_generated" / "packages3d",
            home / "3d_models",
        ]
    )
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def find_cached_generated_3d(footprint: str | None) -> str | None:
    """Pick a cached EasyEDA/JLC STEP whose name matches *footprint* (not a JEDEC cube)."""
    fp = str(footprint or "").strip()
    if not fp or not footprint_3d_match_keys(fp):
        return None
    hits: list[Path] = []
    for d in generated_3d_search_dirs():
        if not d.is_dir():
            continue
        for p in list(d.glob("*.step")) + list(d.glob("*.stp")) + list(d.glob("*.wrl")):
            if easyeda_mesh_ok_for_stock_footprint(str(p), fp):
                hits.append(p)
    if not hits:
        return None
    hits.sort(key=lambda p: (p.suffix.lower() != ".step", len(p.name)))
    return str(hits[0].resolve())


def catalog_3d_is_on_disk(row: dict | None) -> bool:
    """True when the catalog 3D pointer is a real file or a resolvable KiCad library mesh."""
    row = row or {}
    fp = str(row.get("kicad_footprint") or "").strip()
    if library_3d_file_exists(fp):
        return True
    try:
        from openhac.database.threed_fillin import fillin_available

        if fillin_available(fp):
            return True
    except Exception:
        pass
    local = str(row.get("model_3d_local") or "").strip()
    if not local:
        return False
    if is_kicad_lib_3d_pointer(local):
        return library_3d_file_exists(fp)
    expanded = expand_3d_path(local)
    if not os.path.isfile(expanded):
        return False
    if fp and is_stock_kicad_id(fp) and not fillin_mesh_ok_for_footprint(expanded, fp):
        return False
    return True


def pcb_3d_model_filename(
    footprint: str | None,
    model_3d_local: str | None,
    declared_model: str | None = None,
) -> str | None:
    """Filename for ``FP_3DMODEL`` on the compiled board.

    Stock footprints: KiCad pack file (including the path in the loaded
    ``.kicad_mod``), then fill-in cache. Missing pack files are not attached.
    """
    fp = str(footprint or "").strip()
    local = str(model_3d_local or "").strip()
    if is_stock_kicad_id(fp):
        lib_fn = library_3d_pointer_for_footprint(fp)
        if lib_fn:
            return lib_fn
        declared = resolve_declared_3d_filename(declared_model)
        if declared:
            return declared
        try:
            from openhac.database.threed_fillin import resolve_fillin_step

            cached = resolve_fillin_step(fp)
            if cached:
                return cached
        except Exception:
            pass
        if local:
            expanded = expand_3d_path(local)
            if os.path.isfile(expanded) and easyeda_mesh_ok_for_stock_footprint(expanded, fp):
                return os.path.abspath(expanded)
        return None
    if not local:
        return None
    if is_generated_3d_path(local) or os.path.isfile(expand_3d_path(local)):
        expanded = expand_3d_path(local)
        if os.path.isfile(expanded):
            return os.path.abspath(expanded)
    return None
