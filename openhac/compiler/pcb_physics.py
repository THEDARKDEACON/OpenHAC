"""
pcb_physics.py

IPC-2152 physics-based net-class application to pcbnew boards.

Reads per-net current ratings (set via Net.set_current() / phase_propagate_currents)
and assigns KiCad net-classes with appropriately sized trace widths so Specctra DSN
export (and FreeRouting) honour them via class ``(rule (width …))``.

This module is intentionally import-safe when pcbnew is not present — all pcbnew
access happens inside the functions that receive pcbnew as an argument.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("openhac.pcb_physics")

# IPC-2152 trace-width calculation (mirrors core/physics.py for zero-import overhead here).
def _ipc2152_width_mm(
    current_a: float,
    temp_rise_c: float = 10.0,
    thickness_oz: float = 1.0,
    min_width_mm: float = 0.25,
) -> float:
    """Return IPC-2152 minimum trace width in mm for *current_a* Amperes."""
    if current_a <= 0:
        return min_width_mm
    k, b, c = 0.048, 0.44, 0.725
    area_mils2 = (current_a / (k * (temp_rise_c**b))) ** (1.0 / c)
    thickness_mils = thickness_oz * 1.37
    width_mm = (area_mils2 / thickness_mils) * 0.0254
    return max(width_mm, min_width_mm)


# Net-class name thresholds (Amperes → class name).  These match the naming used
# in the schematic SI stackup reminder and the autoroute policy generator.
_NETCLASS_THRESHOLDS: list[tuple[float, str]] = [
    (30.0, "HighCurrent_30A"),
    (15.0, "HighCurrent_15A"),
    (10.0, "HighCurrent_10A"),
    (5.0, "HighCurrent_5A"),
    (2.0, "Power_2A"),
    (1.0, "Power_1A"),
    (0.5, "Signal_500mA"),
    (0.0, "Signal"),
]


def _netclass_for_current(current_a: float) -> str:
    for threshold, name in _NETCLASS_THRESHOLDS:
        if current_a >= threshold:
            return name
    return "Signal"


def _find_existing_netclass(ncs, class_name: str):
    """Return an existing NETCLASS object by name, or None."""
    try:
        if hasattr(ncs, "Find"):
            nc = ncs.Find(class_name)
            if nc is not None:
                return nc
    except Exception:
        pass
    try:
        if hasattr(ncs, "values"):
            for nc in ncs.values():
                if str(nc.GetName()) == class_name:
                    return nc
    except Exception:
        pass
    try:
        if hasattr(ncs, "has_key") and ncs.has_key(class_name):
            return ncs[class_name]
    except Exception:
        pass
    try:
        return ncs[class_name]
    except Exception:
        return None


def _ensure_netclass(pcb, pcbnew_mod, class_name: str, width_mm: float, clearance_mm: float = 0.2) -> bool:
    """Create or raise *class_name* so its trace width is at least *width_mm*."""
    try:
        ncs = pcb.GetNetClasses()
    except Exception:
        return False

    existing = _find_existing_netclass(ncs, class_name)
    if existing is not None:
        try:
            cur_iu = int(existing.GetTrackWidth()) if hasattr(existing, "GetTrackWidth") else int(existing.GetTraceWidth())
        except Exception:
            try:
                cur_iu = int(existing.GetTraceWidth())
            except Exception:
                cur_iu = 0
        need_iu = int(pcbnew_mod.FromMM(float(width_mm)))
        if need_iu > cur_iu:
            try:
                if hasattr(existing, "SetTrackWidth"):
                    existing.SetTrackWidth(need_iu)
                else:
                    existing.SetTraceWidth(need_iu)
                if hasattr(existing, "SetClearance"):
                    existing.SetClearance(int(pcbnew_mod.FromMM(float(clearance_mm))))
                logger.info(
                    "NetClass %r: raised track width to %.3f mm (IPC-2152 max in bucket).",
                    class_name,
                    width_mm,
                )
            except Exception as e:
                logger.debug("Failed to raise net-class %r width: %s", class_name, e)
                return False
        return True

    try:
        nc_cls = getattr(pcbnew_mod, "NETCLASS", None)
        if nc_cls is None:
            return False
        nc = nc_cls(class_name)
        set_w = getattr(nc, "SetTrackWidth", None) or getattr(nc, "SetTraceWidth", None)
        if callable(set_w):
            set_w(int(pcbnew_mod.FromMM(width_mm)))
        nc.SetClearance(int(pcbnew_mod.FromMM(clearance_mm)))
        # Via sizes default to the net-class trace width.
        nc.SetViaDiameter(int(pcbnew_mod.FromMM(max(width_mm * 2.0, 0.8))))
        nc.SetViaDrill(int(pcbnew_mod.FromMM(max(width_mm * 0.8, 0.4))))

        if hasattr(ncs, "Add"):
            ncs.Add(nc)
        else:
            ncs[class_name] = nc
        return True
    except Exception as e:
        logger.debug("Failed to create net-class %r: %s", class_name, e)
        return False


def _assign_netclass_to_net(pcb, net_name: str, class_name: str) -> bool:
    """Assign *class_name* to the net named *net_name* on *pcb*."""
    try:
        nets = pcb.GetNetsByName()
        ni = nets.get(net_name) or nets.get(str(net_name))
        if ni is None:
            return False
        ni.SetNetClassName(class_name)
        return True
    except Exception as e:
        logger.debug("Failed to assign net-class %r to net %r: %s", class_name, net_name, e)
        return False


def collect_net_currents_a(board) -> dict[str, float]:
    """Gather net_name → current_a from board annotations and live Net objects."""
    net_currents: dict[str, float] = {}

    for net_name, info in (getattr(board, "_high_current_nets", None) or {}).items():
        if isinstance(info, dict):
            amps = float(info.get("current_a", 0.0) or 0.0)
        else:
            amps = float(info or 0.0)
        if amps > 0:
            net_currents[str(net_name)] = max(net_currents.get(str(net_name), 0.0), amps)

    try:
        from openhac.circuit import get_default_circuit

        circuit = get_default_circuit()
        for net in getattr(circuit, "nets", []):
            name = str(getattr(net, "name", None) or "").strip()
            if not name:
                continue
            amps = float(getattr(net, "current_a", 0.0) or 0.0)
            if amps > 0:
                net_currents[name] = max(net_currents.get(name, 0.0), amps)
    except Exception:
        pass

    try:
        mods = board._get_all_modules()
    except Exception:
        mods = getattr(board, "modules", []) or []
    for mod in mods:
        for comp in getattr(mod, "components", []) or []:
            for pin in getattr(getattr(comp, "part", None), "get_pins", lambda: [])():
                net = getattr(pin, "net", None)
                if net is None:
                    continue
                name = str(getattr(net, "name", None) or "").strip()
                amps = float(getattr(net, "current_a", 0.0) or 0.0)
                if name and amps > 0:
                    net_currents[name] = max(net_currents.get(name, 0.0), amps)
    return net_currents


def apply_physics_net_classes(pcb, board, pcbnew_mod) -> int:
    """Apply IPC-2152-derived net-classes to *pcb* for all nets with a current rating.

    Creates / updates KiCad net-classes whose trace widths satisfy IPC-2152 at a
    10 °C temperature rise. Specctra DSN export embeds these as class width rules
    that FreeRouting honours.

    Returns:
        Number of nets that received a non-default net-class assignment.
    """
    net_currents = collect_net_currents_a(board)
    if not net_currents:
        logger.debug("apply_physics_net_classes: no nets with current annotations found; skipping.")
        return 0

    # Board copper thickness (oz) — read from board stackup if available.
    copper_oz = 1.0
    try:
        stackup = pcb.GetDesignSettings().GetStackupDescriptor()
        for i in range(stackup.GetCount()):
            layer = stackup.GetStackupLayer(i)
            if "Cu" in str(layer.GetName() or ""):
                copper_oz = float(layer.GetThickness()) / 35000.0  # nm → oz (approx)
                copper_oz = max(0.5, min(copper_oz, 4.0))
                break
    except Exception:
        copper_oz = 1.0

    # Per class: use MAX current in the bucket so early low members don't undersize.
    class_max_a: dict[str, float] = {}
    for amps in net_currents.values():
        class_name = _netclass_for_current(amps)
        class_max_a[class_name] = max(class_max_a.get(class_name, 0.0), float(amps))

    created: set[str] = set()
    for class_name, amps in class_max_a.items():
        width_mm = _ipc2152_width_mm(amps, temp_rise_c=10.0, thickness_oz=copper_oz)
        clearance_mm = max(0.2, width_mm * 0.5)
        if _ensure_netclass(pcb, pcbnew_mod, class_name, width_mm, clearance_mm):
            created.add(class_name)
            logger.info(
                "NetClass %r: %.3f A (bucket max) → %.3f mm trace (IPC-2152, %s oz Cu)",
                class_name,
                amps,
                width_mm,
                copper_oz,
            )

    assigned = 0
    for net_name, amps in net_currents.items():
        class_name = _netclass_for_current(amps)
        if class_name in created and _assign_netclass_to_net(pcb, net_name, class_name):
            assigned += 1
            logger.debug("Net %r → net-class %r (%.2f A)", net_name, class_name, amps)

    try:
        board._last_ipc_netclass_widths_mm = {
            cn: _ipc2152_width_mm(a, thickness_oz=copper_oz) for cn, a in class_max_a.items()
        }
        board._last_ipc_net_currents_a = dict(net_currents)
    except Exception:
        pass

    if assigned:
        logger.info(
            "apply_physics_net_classes: assigned IPC-2152 net-classes to %d net(s) across %d class(es).",
            assigned,
            len(created),
        )
    return assigned


def collect_net_widths_mm_from_pcb(pcb_path: str | Path) -> dict[str, float]:
    """Per-net track widths (mm) from a saved ``.kicad_pcb`` / sibling ``.kicad_pro``.

    Used to re-patch Specctra DSN after KiCad placement edits. KiCad's own DSN
    export often flattens every net to ``kicad_default`` 0.2 mm; the PCB/project
    still hold OpenHaC IPC netclasses.
    """
    path = Path(pcb_path)
    merged: dict[str, float] = {}
    for src in (
        _net_widths_mm_from_openhac_sidecar(path),
        _net_widths_mm_from_pcbnew(path),
        _net_widths_mm_from_kicad_pro(path.with_suffix(".kicad_pro")),
        _net_widths_mm_from_pcb_sexpr(path),
        _net_widths_mm_from_specctra_rules(path.with_suffix(".rules")),
    ):
        for net, w in src.items():
            try:
                ww = float(w)
            except (TypeError, ValueError):
                continue
            if ww <= 0:
                continue
            merged[net] = max(merged.get(net, 0.0), ww)
    return merged


def _skip_dsn_net_name(name: str) -> bool:
    n = (name or "").strip()
    if not n or n in (".", "NoNet", "<no net>"):
        return True
    low = n.lower()
    return low.startswith("unconnected") or low.startswith("no_connect")


def _net_widths_mm_from_openhac_sidecar(pcb_path: Path) -> dict[str, float]:
    """Compile-time netclass map KiCad will not rewrite on PCB save."""
    side = pcb_path.with_name(pcb_path.stem + ".openhac-netclasses.json")
    if not side.is_file():
        return {}
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    raw = data.get("widths_mm")
    if isinstance(raw, dict):
        for net, w in raw.items():
            if _skip_dsn_net_name(str(net)):
                continue
            try:
                ww = float(w)
            except (TypeError, ValueError):
                continue
            if ww > 0:
                out[str(net)] = ww
    if out:
        return out
    classes = data.get("classes") if isinstance(data.get("classes"), dict) else {}
    assignments = data.get("assignments") if isinstance(data.get("assignments"), dict) else {}
    for net, cls in assignments.items():
        if _skip_dsn_net_name(str(net)):
            continue
        rec = classes.get(cls) if isinstance(classes.get(cls), dict) else {}
        tw = rec.get("track_width")
        try:
            ww = float(tw)
        except (TypeError, ValueError):
            continue
        if ww > 0:
            out[str(net)] = ww
    return out


def _net_widths_mm_from_pcbnew(pcb_path: Path) -> dict[str, float]:
    try:
        import pcbnew  # type: ignore
    except Exception:
        return {}
    try:
        board = pcbnew.LoadBoard(str(pcb_path))
    except Exception as e:
        logger.debug("IPC/DSN: pcbnew could not load %s: %s", pcb_path, e)
        return {}
    if board is None:
        return {}

    def _to_mm(iu: int) -> float:
        try:
            return float(pcbnew.ToMM(int(iu)))
        except Exception:
            try:
                return float(pcbnew.Iu2Millimeter(int(iu)))
            except Exception:
                return int(iu) / 1_000_000.0

    out: dict[str, float] = {}
    try:
        nets = board.GetNetsByName()
    except Exception as e:
        logger.debug("IPC/DSN: GetNetsByName failed: %s", e)
        return {}
    try:
        keys = list(nets.keys())
    except Exception:
        try:
            keys = list(nets)
        except Exception:
            keys = []
    for key in keys:
        try:
            ni = nets[key] if not isinstance(key, tuple) else nets.get(key)
            name = str(getattr(ni, "GetNetname", lambda: key)() if ni is not None else key)
        except Exception:
            name = str(key)
        if _skip_dsn_net_name(name):
            continue
        w_mm = 0.0
        try:
            nc = ni.GetNetClass()
            iu = int(nc.GetTrackWidth() if hasattr(nc, "GetTrackWidth") else nc.GetTraceWidth())
            w_mm = _to_mm(iu)
        except Exception:
            try:
                cname = str(ni.GetNetClassName())
                ncs = board.GetNetClasses()
                existing = _find_existing_netclass(ncs, cname)
                if existing is not None:
                    iu = int(
                        existing.GetTrackWidth()
                        if hasattr(existing, "GetTrackWidth")
                        else existing.GetTraceWidth()
                    )
                    w_mm = _to_mm(iu)
            except Exception:
                continue
        if w_mm > 0:
            out[name] = w_mm
    return out


def _parse_kicad_pro_netclasses(data: dict) -> tuple[dict[str, float], dict[str, str]]:
    """Return (class_name → width_mm, net_name → class_name) from ``.kicad_pro`` JSON."""
    classes: dict[str, float] = {}
    assignments: dict[str, str] = {}

    def _ingest_class_list(rows) -> None:
        if not isinstance(rows, list):
            return
        for c in rows:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            tw = c.get("track_width")
            if not name or tw is None:
                continue
            try:
                classes[name] = float(tw)
            except (TypeError, ValueError):
                continue

    ns = data.get("net_settings") if isinstance(data.get("net_settings"), dict) else {}
    _ingest_class_list(ns.get("classes"))
    nca = ns.get("netclass_assignments") or ns.get("net_class_assignments") or {}
    if isinstance(nca, dict):
        for net, cls in nca.items():
            n, c = str(net).strip(), str(cls).strip()
            if n and c:
                assignments[n.lstrip("/")] = c
    for row in ns.get("netclass_patterns") or []:
        if not isinstance(row, dict):
            continue
        cls = str(row.get("netclass") or "").strip()
        pat = str(row.get("pattern") or "").strip().lstrip("/")
        if not cls or not pat or any(ch in pat for ch in "*?[]"):
            continue
        assignments[pat] = cls

    nested = (
        ((data.get("board") or {}) if isinstance(data.get("board"), dict) else {}).get("design_settings")
        or {}
    )
    if isinstance(nested, dict):
        nc = nested.get("net_classes") if isinstance(nested.get("net_classes"), dict) else {}
        _ingest_class_list(nc.get("classes"))
        for row in nc.get("setup") or []:
            if not isinstance(row, dict):
                continue
            n, c = str(row.get("net") or "").strip(), str(row.get("class") or "").strip()
            if n and c:
                assignments[n] = c
    return classes, assignments


def _net_widths_mm_from_kicad_pro(pro_path: Path) -> dict[str, float]:
    if not pro_path.is_file():
        return {}
    try:
        data = json.loads(pro_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("IPC/DSN: cannot parse %s: %s", pro_path, e)
        return {}
    if not isinstance(data, dict):
        return {}
    classes, assignments = _parse_kicad_pro_netclasses(data)
    out: dict[str, float] = {}
    for net, cls in assignments.items():
        if _skip_dsn_net_name(net):
            continue
        w = classes.get(cls)
        if w is not None and float(w) > 0:
            out[net] = float(w)
    return out


_RULES_CLASS_RE = re.compile(
    r'\(\s*class\s+"?([^"\s]+)"?\s*(.*?)\(\s*rule\s*\(\s*width\s+([0-9.]+)\s*\)',
    re.IGNORECASE | re.DOTALL,
)


def _net_widths_mm_from_specctra_rules(rules_path: Path) -> dict[str, float]:
    """Recover per-net widths from a sibling Specctra ``.rules`` file (FreeRouting / prior patch)."""
    if not rules_path.is_file():
        return {}
    try:
        text = rules_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, float] = {}
    for m in _RULES_CLASS_RE.finditer(text):
        body = m.group(2) or ""
        try:
            um = float(m.group(3))
        except (TypeError, ValueError):
            continue
        w_mm = um / 1000.0 if um >= 10.0 else um
        if w_mm <= 0:
            continue
        for tok in re.findall(r'"([^"]+)"|([A-Za-z_][A-Za-z0-9_\[\]./-]*)', body):
            net = (tok[0] or tok[1] or "").strip()
            if _skip_dsn_net_name(net) or net.lower() in {
                "class",
                "rule",
                "width",
                "clearance_class",
                "via_rule",
                "circuit",
                "use_layer",
            }:
                continue
            out[net] = max(out.get(net, 0.0), w_mm)
    return out


_PCB_ASSIGN_RE = re.compile(
    r'\(\s*(?:assignment\s+)?(?:"([^"]+)"|(\S+))\s+(?:"([^"]+)"|(\S+))\s*\)',
)
_PCB_CLASS_WIDTH_RE = re.compile(
    r'\(\s*class\s+"?([^"\s]+)"?.*?\(\s*trace_width\s+([0-9.]+)\s*\)',
    re.IGNORECASE | re.DOTALL,
)
_PCB_ADD_NET_RE = re.compile(r'\(\s*add_net\s+(?:"([^"]+)"|(\S+))\s*\)', re.I)


def _net_widths_mm_from_pcb_sexpr(pcb_path: Path) -> dict[str, float]:
    """Best-effort parse of netclass assignments stored in the ``.kicad_pcb`` file."""
    if not pcb_path.is_file():
        return {}
    try:
        text = pcb_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    classes: dict[str, float] = {}
    for m in _PCB_CLASS_WIDTH_RE.finditer(text):
        try:
            classes[str(m.group(1))] = float(m.group(2))
        except (TypeError, ValueError):
            continue
    out: dict[str, float] = {}
    idx = text.find("net_class_assignments")
    if idx >= 0:
        chunk = text[idx : idx + 50_000]
        for m in _PCB_ASSIGN_RE.finditer(chunk):
            net = (m.group(1) or m.group(2) or "").strip()
            cls = (m.group(3) or m.group(4) or "").strip()
            if _skip_dsn_net_name(net) or cls in ("net_class_assignments",):
                continue
            w = classes.get(cls)
            if w is not None and w > 0:
                out[net] = w
    # Legacy ``(net_class Name … (add_net X) (trace_width …))``
    for m in re.finditer(r"\(\s*net_class\s+(\S+)\b", text, re.I):
        start = m.start()
        depth = 0
        end = start
        for i, ch in enumerate(text[start:], start):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        block = text[start:end]
        cls = m.group(1).strip().strip('"')
        wm = re.search(r"\(\s*trace_width\s+([0-9.]+)\s*\)", block, re.I)
        if not wm:
            continue
        try:
            w = float(wm.group(1))
        except ValueError:
            continue
        for nm in _PCB_ADD_NET_RE.finditer(block):
            net = (nm.group(1) or nm.group(2) or "").strip()
            if not _skip_dsn_net_name(net) and w > 0:
                out[net] = w
        if cls:
            classes[cls] = w
    return out


_DSN_WIDTH_RE = re.compile(
    r"\(\s*class\s+(\S+).*?\(\s*rule\b.*?\(\s*width\s+([0-9.]+)\s*\)",
    re.IGNORECASE | re.DOTALL,
)


def patch_dsn_ipc_widths(
    dsn_path: str | Path,
    net_widths_mm: dict[str, float],
    *,
    clearance_factor: float = 0.5,
    min_clearance_mm: float = 0.2,
) -> int:
    """Rewrite Specctra ``(class …)`` rules so FreeRouting sees IPC widths.

    KiCad's Specctra export often collapses everything into ``kicad_default``.
    When OpenHaC has per-net IPC widths, this patches the DSN so FreeRouting
    gets explicit ``(rule (width …))`` entries (widths in micrometres, matching
    KiCad's DSN convention: ``200`` → 0.2 mm).

    Returns number of nets placed into width-specific classes.
    """
    path = Path(dsn_path)
    if not path.is_file() or not net_widths_mm:
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    # Find the class block(s) inside (network …)
    net_idx = text.find("(network")
    if net_idx < 0:
        logger.warning("IPC/DSN patch: no (network …) section in %s", path)
        return 0

    # Bucket nets by rounded width (µm) for stable class names
    buckets: dict[str, list[str]] = {}
    width_um: dict[str, int] = {}
    clear_um: dict[str, int] = {}
    for net, w_mm in sorted(net_widths_mm.items()):
        w = max(float(w_mm), 0.15)
        um = int(round(w * 1000.0))
        clr = int(round(max(min_clearance_mm, w * clearance_factor) * 1000.0))
        cls = f"IPC_{um}um"
        buckets.setdefault(cls, []).append(str(net))
        width_um[cls] = um
        clear_um[cls] = clr

    # Collect all net names already declared so leftovers stay in default
    declared = set(re.findall(r"\(\s*net\s+(\S+)", text))
    assigned = {n for nets in buckets.values() for n in nets}
    leftover = sorted(n for n in declared if n not in assigned)

    class_blocks: list[str] = []
    for cls, nets in buckets.items():
        net_list = " ".join(nets)
        class_blocks.append(
            "    (class "
            f"{cls} {net_list}\n"
            "      (rule\n"
            f"        (width {width_um[cls]})\n"
            f"        (clearance {clear_um[cls]})\n"
            "      )\n"
            "    )"
        )
        logger.info(
            "IPC/DSN: class %s → width %d µm (%.3f mm) for %d net(s)",
            cls,
            width_um[cls],
            width_um[cls] / 1000.0,
            len(nets),
        )
    if leftover:
        class_blocks.append(
            "    (class kicad_default "
            + " ".join(leftover)
            + "\n      (rule\n        (width 200)\n        (clearance 200)\n      )\n    )"
        )

    new_classes = "\n".join(class_blocks)

    # Replace existing (class …) blocks inside network section with our classes.
    # Match from first "(class " after (network to just before closing of network+wiring.
    class_start = text.find("(class ", net_idx)
    if class_start < 0:
        wiring = text.find("(wiring", net_idx)
        insert_at = wiring if wiring > 0 else text.rfind(")", net_idx)
        text = text[:insert_at] + new_classes + "\n  " + text[insert_at:]
    else:
        i = class_start
        depth = 0
        end = class_start
        while i < len(text):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    j = end
                    while j < len(text) and text[j] in " \t\n\r":
                        j += 1
                    if text.startswith("(class ", j):
                        i = j
                        continue
                    break
            i += 1
        text = text[:class_start] + new_classes + text[end:]

    path.write_text(text, encoding="utf-8")
    return len(assigned)


def assert_dsn_netclass_widths(
    dsn_path: str | Path,
    *,
    required_widths_mm: dict[str, float] | None = None,
    net_widths_mm: dict[str, float] | None = None,
    min_width_mm: float = 0.0,
    strict: bool = True,
) -> list[str]:
    """Verify Specctra DSN embeds usable width rules for FreeRouting.

    KiCad emits widths in **micrometres** (``200`` = 0.2 mm). After
    :func:`patch_dsn_ipc_widths`, classes are named ``IPC_<um>um``.
    """
    path = Path(dsn_path)
    viols: list[str] = []
    if not path.is_file():
        viols.append(f"IPC/DSN: missing Specctra DSN at {path}")
    else:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            viols.append(f"IPC/DSN: cannot read {path}: {e}")
            text = ""
        widths_um: list[int] = []
        if text:
            for m in re.finditer(r"\(\s*width\s+([0-9.]+)\s*\)", text, re.I):
                try:
                    widths_um.append(int(round(float(m.group(1)))))
                except Exception:
                    continue
            if not widths_um:
                viols.append(
                    "IPC/DSN: no (width …) rules found — FreeRouting may use a default width."
                )
            if net_widths_mm:
                for net, w_mm in net_widths_mm.items():
                    um = int(round(max(float(w_mm), 0.15) * 1000.0))
                    marker = f"IPC_{um}um"
                    if marker not in text and um not in widths_um:
                        viols.append(
                            f"IPC/DSN: net {net!r} expected ~{um} µm width rule missing after patch."
                        )
            if required_widths_mm:
                for cls, need_mm in required_widths_mm.items():
                    need_um = int(round(float(need_mm) * 1000.0))
                    if not any(u + 1 >= need_um for u in widths_um):
                        viols.append(
                            f"IPC/DSN: no width ≥ {need_um} µm for required class {cls!r} "
                            f"({need_mm:.3f} mm)."
                        )
            if min_width_mm > 0 and widths_um:
                min_um = int(round(float(min_width_mm) * 1000.0))
                if max(widths_um) < min_um:
                    viols.append(
                        f"IPC/DSN: max embedded width {max(widths_um)} µm < fab min {min_um} µm."
                    )

    if viols and strict:
        from openhac.core.base import AutorouterFailedError

        raise AutorouterFailedError(
            "IPC-2152 / Specctra standards gate failed (widths must reach FreeRouting):\n"
            + "\n".join(f"  • {v}" for v in viols)
        )
    for v in viols:
        logger.warning("%s", v)
    return viols
