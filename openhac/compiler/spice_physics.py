"""Datasheet benches and operating-point probe assertions (SPS-016, SPS-022, SPS-032)."""

from __future__ import annotations

import re
from pathlib import Path

from openhac.compiler.ngspice_runner import parse_ngspice_op_voltages, run_ngspice_headless
from openhac.compiler.spice_models import SpiceModelRecord, SpicePhysicsCheck, expand_include_path
from openhac.compiler.spice_nodes import spice_token
from openhac.core.base import OpenHaCError

TNOM_C = 27.0


def _voltage_for_probe(voltages: dict[str, float], probe: str) -> float | None:
    key = spice_token(probe)
    if key in voltages:
        return voltages[key]
    low = {k.lower(): v for k, v in voltages.items()}
    if key.lower() in low:
        return low[key.lower()]
    # ngspice sometimes prints v(n_3v3)
    alt = f"v({key})".lower()
    if alt in low:
        return low[alt]
    return voltages.get(probe)


def assert_probe_window(voltages: dict[str, float], probe: str, vmin: float, vmax: float) -> float:
    val = _voltage_for_probe(voltages, probe)
    if val is None:
        raise OpenHaCError(
            f"SPS-032: probe {probe!r} not found in ngspice OP (have {sorted(voltages)})."
        )
    if val < float(vmin) or val > float(vmax):
        raise OpenHaCError(
            f"SPS-022: probe {probe!r}={val} outside [{vmin}, {vmax}]."
        )
    return val


def write_physics_bench_deck(
    dest: Path,
    rec: SpiceModelRecord,
    check: SpicePhysicsCheck,
) -> Path:
    """Write a tiny datasheet bench `.cir` for *check* (SPS-016)."""
    include = expand_include_path(rec.include)
    lines = [
        f"* OpenHaC physics bench {rec.subckt} {check.name}",
        f".options TEMP={check.temp_c} TNOM={check.temp_c}",
        f".include {include}",
    ]
    # Nodes named after pin names (sanitized) except ground → 0.
    node_for: dict[int, str] = {}
    for p in rec.pin_map:
        raw = p.name or p.num or f"T{p.subckt_index}"
        node_for[p.subckt_index] = spice_token(raw)

    for rail, volts in (check.rails or {}).items():
        node = spice_token(rail)
        vname = "V" + re.sub(r"[^A-Za-z0-9_]", "_", node)[:20]
        if vname[0].isdigit():
            vname = "V_" + vname
        lines.append(f"{vname} {node} 0 DC {float(volts)}")

    if check.load_ohm is not None:
        load_node = spice_token(check.load_from or check.probe)
        lines.append(f"RLOAD {load_node} 0 {float(check.load_ohm)}")

    inst_nodes = " ".join(node_for[i] for i in range(1, len(rec.pin_map) + 1))
    lines.append(f"XDUUT {inst_nodes} {rec.subckt}")
    probe_tok = spice_token(check.probe)
    lines.append(".op")
    lines.append(".control")
    lines.append("op")
    lines.append(f"print v({probe_tok})")
    lines.append("quit")
    lines.append(".endc")
    lines.append(".end")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def run_physics_check(
    rec: SpiceModelRecord,
    check: SpicePhysicsCheck,
    *,
    work_dir: Path,
    timeout_s: float = 30.0,
) -> dict:
    cir = work_dir / f"bench_{rec.subckt}_{check.name}.cir"
    write_physics_bench_deck(cir, rec, check)
    log = Path(run_ngspice_headless(cir, timeout_s=timeout_s))
    text = log.read_text(encoding="utf-8", errors="replace")
    volts = parse_ngspice_op_voltages(text)
    val = assert_probe_window(volts, check.probe, check.vmin, check.vmax)
    return {
        "name": check.name,
        "probe": check.probe,
        "value": val,
        "vmin": check.vmin,
        "vmax": check.vmax,
        "temp_c": check.temp_c,
        "passed": True,
    }


def run_record_physics_checks(
    rec: SpiceModelRecord,
    *,
    work_dir: Path,
    timeout_s: float = 30.0,
) -> list[dict]:
    if rec.kind not in ("vendor", "physics"):
        return []
    out = []
    for chk in rec.physics_checks:
        out.append(run_physics_check(rec, chk, work_dir=work_dir, timeout_s=timeout_s))
    return out
