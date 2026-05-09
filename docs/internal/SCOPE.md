# OpenHaC — product scope (capability tiers)

This document (**STR-001**) states what the toolchain aims to do today versus what is explicitly out of scope. It complements the normative gap list in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md).

## Tier A — Logic & manufacturing data

- Declarative Python (`Module`, `Interface`, `Board`) driving **SKiDL** netlists.
- **Hierarchical KiCad schematics** — default `.kicad_sch` export is **flat**. Optional **multi-sheet** export is available via `OPENHAC_SCHEMATIC_MULTI_SHEET=1`, which emits one subsheet per `OpenHaC_Module` tag and uses **global labels** for cross-sheet connectivity (**SCH-002 stretch**).
- **BOM** (`.csv`) with LCSC-oriented fields where the database provides them.
- **ERC** (floating nets, unconnected pins, power flags, power budget) and **DRC** (board bounds, IPC-2152 vs design min trace width). OpenHaC ERC is a **pre-check** on the SKiDL graph; optional **`kicad-cli sch erc`** (``openhac compile --kicad-erc``) runs KiCad's schematic ERC on the exported ``.kicad_sch``.
- **SQLite** component catalog + optional **jlcsearch** sync / JIT lookup.

## Tier B — KiCad PCB & placement

- **`.kicad_pcb`**: board outline, **footprint instances** from SKiDL, **pad ↔ net** assignment for ratsnest, **Z3** module-level placement hints.
- Requires **KiCad Python (`pcbnew`)** and on-disk **`*.pretty`** libraries (`KICAD8_FOOTPRINT_DIR` / install paths).

## Tier C — KiCad ecosystem & fabrication handoff

- Optional **schematic** (`.kicad_sch`) + **project stub** (`.kicad_pro`); optional **KiCad schematic ERC** report via CLI.
- **Autorouting** via **FreeRouting** + **`kicad-cli`** DSN/SES (when enabled).
- **`openhac export fab`**: **Gerbers**, **Excellon drill**, **CSV position** via **`kicad-cli`**; optional **`--ipc2581`**.
- **`{name}.openhac-manifest.json`** after a successful **`compile`** (output inventory); optional **`compile(..., output_dir=...)`** / **`openhac compile -o DIR`** groups artifacts (**MFG-005** / **STR-002**).

## SPICE (parallel path)

- **`.cir`** generation from the same SKiDL graph (limited model fidelity; not a full analog sign-off flow).

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

When README or marketing copy refers to “tiers,” **Tier 1–3** there means **internal architecture** (database / core / compiler), not the capability levels above.
