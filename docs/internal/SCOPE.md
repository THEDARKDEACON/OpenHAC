# OpenHaC — product scope (capability tiers)

This document (**STR-001**) states what the toolchain aims to do today versus what is explicitly out of scope. It complements the Phase-1 gap list in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md) and the Phase-2 fabrication contract in [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md).

## Compile goals

| Goal | Meaning |
|------|---------|
| **handoff** | Reviewable KiCad / netlist / BOM artifacts; some gaps may warn and continue. |
| **fabrication** | Fail-closed path toward a fab package (pins, pads, footprints, routing completeness, PCB DRC, offline catalog). See **FAB-*** IDs. |

`--production` today tightens KiCad + JIT strictness; Phase-2 **FAB-030** requires it to imply the full fabrication gate set.

**Honest fab claim (Phase-2 target):** for supported part and board classes, a fabrication compile either emits audited release/Gerber outputs or exits non-zero. OpenHaC does **not** claim production-ready copper from autoroute alone (see non-goals / **PCB-007**).

## Tier A — Logic & manufacturing data

- Declarative Python (`Module`, `Interface`, `Board`) driving a **native** circuit graph (`openhac.core.circuit`) as the electrical source of truth (**FAB-004**). Residual SKiDL usage is legacy/handoff only until migration completes.
- **BOM** (`.csv`) with LCSC-oriented fields where the database provides them.
- **ERC** (floating nets, unconnected pins, power flags, power budget) and **DRC** (board bounds, IPC-2152 vs design min trace width) on the native graph.
- **SQLite** component catalog + optional sync / JIT lookup (JIT blocked or fail-closed under fabrication — **FAB-010**, **FAB-011**).
- **Human review:** interactive **webview** / Hardware IR preferred over auto-drawn sheets (**FAB-041**). Optional **`.kicad_sch`** export remains available but is **not** the electrical SoT (**FAB-040**). Flat export by default; optional multi-sheet via `OPENHAC_SCHEMATIC_MULTI_SHEET=1` (**SCH-002** stretch). Optional **`kicad-cli sch erc`** when a schematic is exported (**SCH-003**).

## Tier B — KiCad PCB & placement

- **`.kicad_pcb`**: board outline, **footprint instances**, **pad ↔ net** assignment for ratsnest, **Z3** module-level placement hints.
- Requires **KiCad Python (`pcbnew`)** and on-disk **`*.pretty`** libraries (`KICAD8_FOOTPRINT_DIR` / install paths).
- Fabrication mode requires footprint presence and pad↔pin parity (**FAB-002**, **FAB-003**, **FAB-020**).

## Tier C — KiCad ecosystem & fabrication handoff

- Optional **schematic** (`.kicad_sch`) + **project stub** (`.kicad_pro`); not required for fab claim.
- **Autorouting** via **FreeRouting** + **`kicad-cli`** DSN/SES (when enabled). Fabrication requires routing completeness (**FAB-021**) and **KiCad PCB DRC** (**FAB-022**).
- **`openhac export fab`**: **Gerbers**, **Excellon drill**, **CSV position** via **`kicad-cli`**; optional **`--ipc2581`** (**FAB-031** CI golden).
- **`{name}.openhac-manifest.json`** after **`compile`**, including Phase-2 **fab_audit** fields when implemented (**FAB-032** / **MFG-005** / **STR-002**).

## SPICE (parallel path)

- **`.cir`** generation from the same circuit graph (limited model fidelity; not a full analog sign-off flow).

## Non-goals (today)

- **SI/PI sign-off** — no impedance, eye, or PDN targets in core (see **SIG-001** / **SIG-003** in the production spec).
- **EMC / EMI compliance** — shielding, return paths, and emissions are **manual** engineering plus test lab; OpenHaC does not assert EMC sign-off (**SIG-004**).
- **Digital verification** — timing, CDC, formal methods, and gate-level sign-off are **out of scope** for the core toolchain (**SIM-003**); SPICE covers analog-only subsets.
- **Multi-rail power trees** with full converter efficiency modeling (partial rail ERC exists; see **PWR-002**).
- **Automated fab DFM** beyond what **KiCad** / **`kicad-cli`** exports provide.
- **Guarantee** of production-ready **high-speed** or **RF** layouts from **autoroute alone** (**PCB-007**): FreeRouting is **routing assistance**, not USB HS/PCIe-grade constraint solving. **`Board.route_differential_pair()`** records intent but **does not** drive impedance-controlled geometry in the exporter (**SIG-002**); finish pair rules in KiCad.
- **Stackup / SI handoff** — use a human-edited stackup file (see **`../stackup_template.yaml`**, **SIG-001**); OpenHaC does not solve impedance from geometry alone.
- **Mains / reinforced isolation** — not a certified mains or creepage tool; IEC spacing needs expert review (**REL-002**).
- **BGA / dense fanout** — no automated escape routing; plan fanout manually or in external CAD (**PCB-008**).
- **Pretty auto-generated schematics as SoT** — algorithmic sheet drawing is optional legacy; connectivity review is native graph / webview / IR (**FAB-040**, **FAB-041**).
- **Phase-3 ecosystem items** (pip-installable hermetic modules, split backend packages, release signing) — listed in [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md); not Phase-2 acceptance.

When README or marketing copy refers to “tiers,” **Tier 1–3** there means **internal architecture** (database / core / compiler), not the capability levels above.
