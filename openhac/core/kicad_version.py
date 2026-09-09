"""Universal KiCad version detection, target resolution, and cross-version asset mapping.

Provides a unified abstraction across KiCad 6, 7, 8, 9, 10, and future releases.
Supports:
  - Automatic host KiCad detection via kicad-cli or filesystem heuristics.
  - Explicit target version selection (--target-kicad or OPENHAC_TARGET_KICAD).
  - Version-specific S-expression format dates for schematics, symbols, and PCBs.
  - Cross-version asset discovery (symbols, footprints, 3D shapes) across Linux, macOS, and Windows.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

logger = logging.getLogger("openhac.kicad_version")

# Official KiCad S-Expression Format Dates by Major Version
_SCH_FORMAT_DATES = {
    6: 20211123,
    7: 20230121,
    8: 20231120,
    9: 20241209,
    10: 20250101,
}

_PCB_FORMAT_DATES = {
    6: 20211014,
    7: 20221018,
    8: 20240108,
    9: 20240108,
    10: 20250101,
}

_DEFAULT_MAJOR = 8
_DEFAULT_SCH_DATE = 20231120
_DEFAULT_PCB_DATE = 20240108


@dataclass(frozen=True)
class KiCadVersion:
    """Represents a validated KiCad semantic version and its format attributes."""

    major: int
    minor: int = 0
    patch: int = 0
    raw: str = ""

    @property
    def sch_format_date(self) -> int:
        """S-expression format date for .kicad_sch and .kicad_sym headers."""
        return _SCH_FORMAT_DATES.get(self.major, _DEFAULT_SCH_DATE)

    @property
    def pcb_format_date(self) -> int:
        """S-expression format date for .kicad_pcb headers."""
        return _PCB_FORMAT_DATES.get(self.major, _DEFAULT_PCB_DATE)

    @property
    def supports_cli(self) -> bool:
        """True if this KiCad version provides the official `kicad-cli` tool (KiCad 7+)."""
        return self.major >= 7

    @property
    def supports_ipc_api(self) -> bool:
        """True if this KiCad version supports the language-agnostic IPC socket API (KiCad 10+)."""
        return self.major >= 10

    @property
    def swig_deprecated(self) -> bool:
        """True if legacy in-process SWIG Python bindings are deprecated (KiCad 9+)."""
        return self.major >= 9

    @property
    def version_string(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __str__(self) -> str:
        return f"KiCad {self.version_string}"


_DETECTED_VERSION: KiCadVersion | None = None
_DETECTION_ATTEMPTED: bool = False


def parse_kicad_version_str(text: str) -> KiCadVersion | None:
    """Extract major, minor, patch from a KiCad version string."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(text or ""))
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3)) if m.group(3) else 0
    return KiCadVersion(major=major, minor=minor, patch=patch, raw=text.strip())


def detect_kicad_version(*, force_refresh: bool = False) -> KiCadVersion | None:
    """Detect the locally installed KiCad version via kicad-cli or filesystem inspection."""
    global _DETECTED_VERSION, _DETECTION_ATTEMPTED
    if _DETECTION_ATTEMPTED and not force_refresh:
        return _DETECTED_VERSION

    _DETECTION_ATTEMPTED = True
    _DETECTED_VERSION = None

    # Strategy 1: Probe `kicad-cli --version`
    cli = shutil.which("kicad-cli")
    if cli:
        try:
            r = subprocess.run(
                [cli, "--version"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if r.returncode == 0 and r.stdout:
                parsed = parse_kicad_version_str(r.stdout)
                if parsed:
                    logger.debug("Detected KiCad via kicad-cli: %s", parsed)
                    _DETECTED_VERSION = parsed
                    return _DETECTED_VERSION
        except (OSError, subprocess.TimeoutExpired):
            pass

    # Strategy 2: Probe `pcbnew.GetBuildVersion()` if already importable
    try:
        import pcbnew  # type: ignore

        build_ver = getattr(pcbnew, "GetBuildVersion", None)
        if callable(build_ver):
            parsed = parse_kicad_version_str(build_ver())
            if parsed:
                logger.debug("Detected KiCad via pcbnew: %s", parsed)
                _DETECTED_VERSION = parsed
                return _DETECTED_VERSION
    except Exception:
        pass

    # Strategy 3: Inspect standard installation directories
    for ver in (10, 9, 8, 7, 6):
        candidates = [
            Path(f"/usr/share/kicad{ver}"),
            Path(f"/usr/share/kicad/{ver}.0"),
            Path(f"/Applications/KiCad/KiCad.app/Contents/SharedSupport"),
            Path(f"C:/Program Files/KiCad/{ver}.0"),
        ]
        for c in candidates:
            if c.is_dir():
                _DETECTED_VERSION = KiCadVersion(major=ver, minor=0, patch=0, raw=str(c))
                logger.debug("Detected KiCad via path %s: %s", c, _DETECTED_VERSION)
                return _DETECTED_VERSION

    # Check unversioned /usr/share/kicad (typically maps to latest installed)
    if Path("/usr/share/kicad/symbols").is_dir() or Path("/usr/share/kicad/footprints").is_dir():
        _DETECTED_VERSION = KiCadVersion(major=9, minor=0, patch=0, raw="/usr/share/kicad")
        return _DETECTED_VERSION

    return None


def resolve_target_kicad_version(
    explicit_target: int | str | None = None,
    board: Any = None,
) -> KiCadVersion:
    """Resolve the target KiCad version using explicit selection, board config, env, or host detection.

    Precedence:
      1. Explicit parameter `explicit_target` (e.g. from `--target-kicad 8`).
      2. `board.target_kicad_version` (if configured on the Board).
      3. `OPENHAC_TARGET_KICAD` or `OPENHAC_KICAD_VERSION` environment variable.
      4. Auto-detected host KiCad version.
      5. Universal default (KiCad 8, 20231120 format).
    """
    raw_candidate: Any = explicit_target

    if isinstance(raw_candidate, KiCadVersion):
        return raw_candidate

    if raw_candidate in (None, "", "auto"):
        raw_candidate = getattr(board, "target_kicad_version", None)

    if isinstance(raw_candidate, KiCadVersion):
        return raw_candidate

    if raw_candidate in (None, "", "auto"):
        raw_candidate = (
            os.environ.get("OPENHAC_TARGET_KICAD")
            or os.environ.get("OPENHAC_KICAD_VERSION")
        )

    if raw_candidate not in (None, "", "auto"):
        parsed = parse_kicad_version_str(str(raw_candidate))
        if parsed:
            return parsed
        try:
            val = int(str(raw_candidate).strip())
            return KiCadVersion(major=val, minor=0, patch=0, raw=str(val))
        except ValueError:
            logger.warning("Unrecognized target KiCad version %r; falling back to detection", raw_candidate)

    detected = detect_kicad_version()
    if detected:
        return detected

    return KiCadVersion(major=_DEFAULT_MAJOR, minor=0, patch=0, raw="default-v8")


def discover_kicad_asset_roots() -> list[Path]:
    """Return all discovered candidate directories containing KiCad libraries across versions."""
    roots: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path | str | None) -> None:
        if not p:
            return
        pth = Path(p).expanduser().resolve()
        if pth.is_dir() and pth not in seen:
            seen.add(pth)
            roots.append(pth)

    # 1. Environment overrides
    for env_k in (
        "KICAD10_SYMBOL_DIR", "KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD7_SYMBOL_DIR", "KICAD6_SYMBOL_DIR",
        "KICAD_SYMBOL_DIR",
    ):
        v = os.environ.get(env_k)
        if v:
            _add(Path(v).parent)
            _add(Path(v))

    # 2. Linux standard locations
    _add("/usr/share/kicad")
    for v in (10, 9, 8, 7, 6):
        _add(f"/usr/share/kicad{v}")
        _add(f"/usr/share/kicad/{v}.0")
        _add(Path.home() / f".local/share/kicad/{v}.0")

    # 3. macOS standard locations
    _add("/Applications/KiCad/KiCad.app/Contents/SharedSupport")
    _add(Path.home() / "Library/Application Support/kicad")

    # 4. Windows standard locations
    for v in (10, 9, 8, 7, 6):
        _add(f"C:/Program Files/KiCad/{v}.0/share/kicad")

    return roots


def apply_universal_kicad_env() -> None:
    """Detect KiCad paths and set environment aliases for all KiCad versions (6 through 10)."""
    roots = discover_kicad_asset_roots()

    sym_dir: Path | None = None
    fp_dir: Path | None = None
    model_dir: Path | None = None

    for root in roots:
        if sym_dir is None and (root / "symbols").is_dir():
            sym_dir = root / "symbols"
        elif sym_dir is None and root.name == "symbols" and root.is_dir():
            sym_dir = root

        if fp_dir is None and (root / "footprints").is_dir():
            fp_dir = root / "footprints"
        elif fp_dir is None and root.name == "footprints" and root.is_dir():
            fp_dir = root

        if model_dir is None and (root / "3dmodels").is_dir():
            model_dir = root / "3dmodels"
        elif model_dir is None and (root / "packages3d").is_dir():
            model_dir = root / "packages3d"

    if sym_dir:
        s_str = str(sym_dir)
        for key in (
            "KICAD_SYMBOL_DIR",
            "KICAD10_SYMBOL_DIR",
            "KICAD9_SYMBOL_DIR",
            "KICAD8_SYMBOL_DIR",
            "KICAD7_SYMBOL_DIR",
            "KICAD6_SYMBOL_DIR",
        ):
            os.environ.setdefault(key, s_str)

    if fp_dir:
        f_str = str(fp_dir)
        for key in (
            "KICAD_FOOTPRINT_DIR",
            "KICAD10_FOOTPRINT_DIR",
            "KICAD9_FOOTPRINT_DIR",
            "KICAD8_FOOTPRINT_DIR",
            "KICAD7_FOOTPRINT_DIR",
            "KICAD6_FOOTPRINT_DIR",
        ):
            os.environ.setdefault(key, f_str)

    if model_dir:
        m_str = str(model_dir)
        target = resolve_target_kicad_version()
        m_keys = [
            "KICAD_3DMODEL_DIR",
            "KICAD9_3DMODEL_DIR",
            "KICAD8_3DMODEL_DIR",
            "KICAD7_3DMODEL_DIR",
            "KICAD6_3DMODEL_DIR",
        ]
        if target.major >= 10:
            m_keys.insert(1, f"KICAD{target.major}_3DMODEL_DIR")
        for key in m_keys:
            os.environ.setdefault(key, m_str)
