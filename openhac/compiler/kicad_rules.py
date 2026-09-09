"""
KiCad 8/9 Custom DRC Rules and FreeRouting Constraint Generator.

Translates first-class OpenHaC constraints and CircuitIR ConstraintNodes into:
1. KiCad 8/9 Custom Design Rule files (.kicad_dru) S-expressions
2. FreeRouting Specctra DSN class and pair rules
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Union

from openhac.core.constraints import Constraint
from openhac.ir.circuit_ir import CircuitIR, ConstraintNode

logger = logging.getLogger("openhac.compiler.kicad_rules")


def constraint_node_to_kicad_dru(node: ConstraintNode, index: int = 1) -> str:
    """Convert an immutable CircuitIR ConstraintNode to KiCad 8/9 custom rule S-expression."""
    kind = node.kind.lower()
    params = node.parameters

    if kind in ("differential_pair", "diff_pair"):
        targets = node.target_ids
        p_net = params.get("net_p", targets[0] if len(targets) > 0 else "P")
        n_net = params.get("net_n", targets[1] if len(targets) > 1 else "N")
        min_g = params.get("min_gap_mm", 0.15)
        opt_g = params.get("opt_gap_mm", 0.18)
        max_g = params.get("max_gap_mm", 0.22)
        rule_name = f"DiffPair_{p_net}_{n_net}"
        return (
            f'(rule "{rule_name}"\n'
            f'  (constraint diff_pair_gap (min {min_g}mm) (opt {opt_g}mm) (max {max_g}mm))\n'
            f'  (condition "A.NetName == \'{p_net}\' && B.NetName == \'{n_net}\'"))'
        )

    elif kind in ("clearance", "min_clearance"):
        min_c = params.get("min_clearance_mm", params.get("clearance_mm", 0.2))
        netclass_a = params.get("netclass_a")
        netclass_b = params.get("netclass_b")
        targets = node.target_ids

        if netclass_a and netclass_b:
            cond = f"A.hasNetclass('{netclass_a}') && B.hasNetclass('{netclass_b}')"
            rname = f"Clearance_{netclass_a}_{netclass_b}"
        elif netclass_a:
            cond = f"A.hasNetclass('{netclass_a}') && !B.hasNetclass('{netclass_a}')"
            rname = f"Clearance_{netclass_a}"
        elif len(targets) >= 2:
            cond = f"(A.NetName == '{targets[0]}' && B.NetName == '{targets[1]}') || (A.NetName == '{targets[1]}' && B.NetName == '{targets[0]}')"
            rname = f"Clearance_{targets[0]}_{targets[1]}"
        elif len(targets) == 1 and targets[0] != "*":
            cond = f"A.NetName == '{targets[0]}' && B.NetName != '{targets[0]}'"
            rname = f"Clearance_{targets[0]}"
        else:
            cond = "true"
            rname = f"Clearance_Global_{int(min_c * 1000)}um"

        return (
            f'(rule "{rname}"\n'
            f'  (constraint clearance (min {min_c}mm))\n'
            f'  (condition "{cond}"))'
        )

    elif kind in ("trace_width", "min_trace_width", "width"):
        min_w = params.get("min_width_mm", 0.2)
        opt_w = params.get("opt_width_mm")
        max_w = params.get("max_width_mm")
        net = params.get("net", node.target_ids[0] if node.target_ids and node.target_ids[0] != "*" else None)
        netclass = params.get("netclass")

        parts = [f"min {min_w}mm"]
        if opt_w is not None:
            parts.append(f"opt {opt_w}mm")
        if max_w is not None:
            parts.append(f"max {max_w}mm")
        body = " ".join(parts)

        if net:
            cond = f"A.NetName == '{net}'"
            rname = f"Width_{net}"
        elif netclass:
            cond = f"A.hasNetclass('{netclass}')"
            rname = f"Width_{netclass}"
        else:
            cond = "true"
            rname = f"Width_Rule_{index}"

        return (
            f'(rule "{rname}"\n'
            f'  (constraint track_width ({body}))\n'
            f'  (condition "{cond}"))'
        )

    elif kind in ("length_match", "length"):
        targets = node.target_ids
        tol = params.get("tolerance_mm", 0.5)
        target_len = params.get("target_length_mm")
        rname = f"LengthMatch_{index}"

        if target_len is not None:
            min_l = max(0.0, target_len - tol)
            max_l = target_len + tol
            body = f"(constraint length (min {min_l:.3f}mm) (max {max_l:.3f}mm))"
        else:
            body = f"(constraint length (max {tol:.3f}mm))"

        if targets:
            cond = " || ".join(f"A.NetName == '{t}'" for t in targets)
        else:
            cond = "true"

        return (
            f'(rule "{rname}"\n'
            f'  {body}\n'
            f'  (condition "{cond}"))'
        )

    elif kind == "keepout":
        layers = params.get("layers", ["F.Cu", "B.Cu"])
        x_min = params.get("x_min", 0.0)
        y_min = params.get("y_min", 0.0)
        x_max = params.get("x_max", 0.0)
        y_max = params.get("y_max", 0.0)
        disallows = []
        if params.get("disallow_tracks", True):
            disallows.append("track")
        if params.get("disallow_vias", True):
            disallows.append("via")
        if params.get("disallow_copperpour", True):
            disallows.append("copper_pour")

        disallow_str = " ".join(disallows)
        layers_str = " ".join(f"'{l}'" for l in layers)
        rname = f"Keepout_{index}"

        return (
            f'(rule "{rname}"\n'
            f'  (constraint disallow {disallow_str})\n'
            f'  (condition "A.intersectsArea([{x_min}mm, {y_min}mm, {x_max}mm, {y_max}mm]) && A.Layer.isMember({layers_str})"))'
        )

    else:
        # Generic fallback
        return f'# Note: Unhandled constraint kind {kind!r} ({params})'


def generate_kicad_dru(
    constraints: Iterable[Union[Constraint, ConstraintNode]],
    out_path: Optional[Union[Path, str]] = None,
) -> str:
    """Generate a KiCad 8/9 custom DRC rule file (.kicad_dru) content."""
    lines: List[str] = [
        "(version 1)",
        "# Generated automatically by OpenHaC v2 Constraint Compiler",
        "",
    ]

    for idx, c in enumerate(constraints, start=1):
        if isinstance(c, Constraint):
            rule_text = c.to_kicad_dru_rule()
        elif isinstance(c, ConstraintNode):
            rule_text = constraint_node_to_kicad_dru(c, index=idx)
        else:
            continue

        if rule_text.strip():
            lines.append(rule_text)
            lines.append("")

    full_text = "\n".join(lines)

    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(full_text, encoding="utf-8")
        logger.info(f"Emitted KiCad custom DRC rules to {p}")

    return full_text


def export_circuit_dru(cir: CircuitIR, out_path: Union[Path, str]) -> Path:
    """Export all constraints from a CircuitIR instance into a KiCad .kicad_dru file."""
    path = Path(out_path)
    generate_kicad_dru(cir.constraints, out_path=path)
    return path


def extract_dsn_differential_pairs(
    constraints: Iterable[Union[Constraint, ConstraintNode]],
) -> List[Tuple[str, str]]:
    """Extract (net_p, net_n) differential pair tuples suitable for Specctra DSN (pair ...) entries."""
    pairs: List[Tuple[str, str]] = []
    for c in constraints:
        if isinstance(c, Constraint):
            node = c.to_circuit_ir_node()
        else:
            node = c

        if node.kind.lower() in ("differential_pair", "diff_pair"):
            targets = node.target_ids
            p = node.parameters.get("net_p", targets[0] if len(targets) > 0 else None)
            n = node.parameters.get("net_n", targets[1] if len(targets) > 1 else None)
            if p and n:
                pairs.append((str(p), str(n)))
    return pairs
