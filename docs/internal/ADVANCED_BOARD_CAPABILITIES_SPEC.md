# OpenHaC — Advanced Board Capabilities Specification (ABC)

**Purpose:** Normative contract for five capability areas beyond Phase-2 ordinary digital/power fab:

1. Reliable place → FreeRouting → KiCad PCB DRC on multi-IC digital/power boards  
2. Fab-quality API / enrich libraries (footprints + ratings)  
3. BGA escape policy and handoff (not a full escape router in v1)  
4. Impedance / high-speed constraint completeness and handoff  
5. RF / EMC **policy** (keepouts, checklists) without lab sign-off claims  

**Status tracking:** [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) (ABC table).  
**Product scope:** [SCOPE.md](./SCOPE.md).  
**Phase-2 fab gates:** [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md).  
**Validation matrix:** [PRODUCTION_VALIDATION.md](./PRODUCTION_VALIDATION.md).

**Relationship:** Phase-2 **FAB-*** IDs remain closed. This document uses the **`ABC-*`** prefix. ABC does **not** reopen FAB acceptance; it extends supported board classes progressively.

---

## Honest claim

| Capability | Claim when ABC Done |
|------------|---------------------|
| Route+DRC (ABC-001…015) | Named multi-IC **digital/power** examples pass place → FreeRouting → `unrouted=0` → KiCad PCB DRC → Gerbers under `--production`. |
| API libs (ABC-016…025) | Live/enrich path can produce stock or EasyEDA footprints + `voltage_rating` / power fields; live lookup respects network policy. |
| BGA (ABC-026…035) | Fabrication **fails closed** on BGA without waiver; with waiver, fanout nets are excluded from FreeRouting and handoff artifacts exist. **No** automated escape routing claim. |
| HS / impedance (ABC-036…045) | `board_class=highspeed` requires stackup + Z0 metadata; emits netclass/rules handoff. **No** field-solver / SI certification claim. |
| RF / EMC (ABC-046…050) | `board_class=rf` requires keepouts/pours/checklist. **No** EMC/RF performance or lab pass claim (**SIG-004**). |

---

## Phase 1A — Route + PCB DRC reliability (ABC-001…015)

| ID | Severity | Requirement | Acceptance |
|----|----------|-------------|------------|
| **ABC-001** | P0 | Inject fab-profile min hole / clearance / track width into pcbnew design settings **before** FreeRouting | Settings visible on board; vias below min drill rejected by KiCad DRC consistently |
| **ABC-002** | P1 | Fill copper pour zones (`ZONE_FILLER`) after pour intents | Zones filled before route and/or before PCB DRC |
| **ABC-003** | P1 | Thermal-relief defaults on pad↔zone connections | Pads connect to pours with relief (not solid) unless overridden |
| **ABC-004** | P1 | Routability-aware placement knobs (channel gap / denser pack for signal boards) | Env/CLI documented; complex subset routes with fewer unrouted nets |
| **ABC-005** | P1 | Pre-route footprint audit for fab min-drill violations on module FPs | Warning or rematerialize/refuse under fabrication |
| **ABC-006** | P0 | Harden `unrouted_net_count` — never silent `0` on connectivity API failure | Metrics record error / treat as fail under fab |
| **ABC-007** | P2 | One repair retry on unrouted/PCB DRC fail (gap / board expand) | `run_compile_loop` attempts documented repair |
| **ABC-008** | P1 | CI / script green subset: multi-IC boards pass `--place --route` | `ci_validate_complex_boards.py --place --route --route-subset …` |
| **ABC-009** | P2 | Document WROOM thermal-via / min-hole ceiling; prefer C3 or FP override for route claims | PRODUCTION_VALIDATION ceiling table |
| **ABC-010…015** | P2 | Reserved stretch: per-net FreeRouting exclude without skipping entire autoroute; density metric gate | Spec placeholders |

---

## Phase 1B — API / enrich library quality (ABC-016…025)

| ID | Severity | Requirement | Acceptance |
|----|----------|-------------|------------|
| **ABC-016** | P0 | `Component._live_lookup` calls `network_allowed()`; no network under fab/no-network | Unit test |
| **ABC-017** | P0 | Prefer stock KiCad footprint map; else EasyEDA; never fab-bind `Device:Q` without risky flag | Live/enrich rows have resolvable FP |
| **ABC-018** | P1 | Populate `voltage_rating` / `power_watts` from jlcsearch / attributes / enrich | DB columns set; REL-001 can pass |
| **ABC-019** | P1 | Record `footprint_source` + confidence on enrich/live | Manifest / DB fields |
| **ABC-020** | P1 | `complex_lcsc_api_mixed_node` + `--api` validator remain green; enrich path documented | Script + tests |
| **ABC-021…025** | P2 | Stretch: trusted override tier; courtyard QA checklist | Spec placeholders |

---

## Phase 2 — BGA escape policy (ABC-026…035)

| ID | Severity | Requirement | Acceptance |
|----|----------|-------------|------------|
| **ABC-026** | P0 | Detect BGA / fine-pitch ball packages from footprint or metadata | Heuristic + tests |
| **ABC-027** | P0 | Fabrication fails unless `quality_gates["allow_manual_bga_fanout"]=True` | Fixture fails / passes with waiver |
| **ABC-028** | P1 | `Board.declare_fanout_intent(...)` → manifest + autoroute exclusions | Artifacts written |
| **ABC-029** | P2 | Fanout constraints JSON for external tools | File beside PCB |
| **ABC-030** | P2 | `board_profiles` note for dense packages | Profile text / gate |
| **ABC-031…035** | P3 | Stretch: automated escape templates | Out of v1 Done |

---

## Phase 3 — Impedance / high-speed (ABC-036…045)

| ID | Severity | Requirement | Acceptance |
|----|----------|-------------|------------|
| **ABC-036** | P0 | `highspeed` profile requires stackup reference under fabrication | Fail without |
| **ABC-037** | P0 | Declared diff pairs require Z0 metadata under fabrication + highspeed | Fail without |
| **ABC-038** | P1 | HS nets excluded from FreeRouting unless waived | Policy + skip |
| **ABC-039** | P1 | Emit netclass / custom-rules handoff file beside PCB | Artifact exists |
| **ABC-040** | P2 | Length-match **intent** recording (no auto tune) | Manifest / JSON |
| **ABC-041…045** | P3 | Stretch: KiCad `.kicad_pro` netclass merge; field solver | Out of v1 Done |

---

## Phase 4 — RF / EMC policy (ABC-046…050)

| ID | Severity | Requirement | Acceptance |
|----|----------|-------------|------------|
| **ABC-046** | P0 | `rf` profile: RF_Module without keepout → fab error unless waived | Fixture |
| **ABC-047** | P1 | Default / required ground-pour intent under `rf` | DRC or checklist |
| **ABC-048** | P1 | Fab handoff RF/EMC checklist section (human/lab) | Manifest / MD |
| **ABC-049** | P2 | Courtyard inflate keepout helper for RF modules | API or auto |
| **ABC-050** | P0 | SCOPE remains: no EMC/RF performance claim | Docs only |

---

## Non-goals (this revision)

- Commercial field solvers / eye diagrams / PDN sign-off  
- Full automated BGA escape routing  
- Antenna matching optimization  
- Claiming “any board” including HS/RF performance from autoroute alone  

---

## Implementation order

1. This spec + SCOPE / VALIDATION / STATUS links  
2. Phase 1A code  
3. Phase 1B code  
4. Phases 2–4 policy gates + fixtures + handoff emitters  
