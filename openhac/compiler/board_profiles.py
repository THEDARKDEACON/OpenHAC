from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoardProfile:
    name: str
    notes: str
    default_quality_gates: dict


PROFILES: dict[str, BoardProfile] = {
    "generic": BoardProfile(
        name="generic",
        notes="Default profile with minimal assumptions.",
        default_quality_gates={},
    ),
    "digital_2layer": BoardProfile(
        name="digital_2layer",
        notes="2-layer digital MCU boards (moderate speed).",
        default_quality_gates={"min_track_count": 1},
    ),
    "power_motor": BoardProfile(
        name="power_motor",
        notes="Higher current, thermal-sensitive, clearance-aware power/motor control boards.",
        default_quality_gates={"min_track_count": 5},
    ),
    "highspeed": BoardProfile(
        name="highspeed",
        notes="High-speed digital (diff pairs, length matching).",
        default_quality_gates={"min_track_count": 5},
    ),
    "rf": BoardProfile(
        name="rf",
        notes="RF boards (keepouts, controlled impedance handoff).",
        default_quality_gates={"min_track_count": 3},
    ),
    "mixedsignal": BoardProfile(
        name="mixedsignal",
        notes="Mixed-signal (analog + digital partitioning).",
        default_quality_gates={"min_track_count": 3},
    ),
    "safety_power": BoardProfile(
        name="safety_power",
        notes="Safety/isolation-aware power boards (creepage/clearance gates are profile-driven).",
        default_quality_gates={"min_track_count": 5},
    ),
}


def resolve_board_profile(name: str | None) -> BoardProfile:
    key = str(name or "generic").strip() or "generic"
    return PROFILES.get(key, PROFILES["generic"])

