# OpenHaC — product scope (capability tiers)

This document (**STR-001**) states what the toolchain aims to do today versus what is explicitly out of scope. It complements the Phase-1 gap list in [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md), the Phase-2 fabrication contract in [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md), progressive advanced-board work in [ADVANCED_BOARD_CAPABILITIES_SPEC.md](./ADVANCED_BOARD_CAPABILITIES_SPEC.md) (**ABC-***), schematic stamp in [SCHEMATIC_SIGN_OFF_SPEC.md](./SCHEMATIC_SIGN_OFF_SPEC.md) (**SSO-***), analog physics gate in [SPICE_SIGN_OFF_SPEC.md](./SPICE_SIGN_OFF_SPEC.md) (**SPS-***), live KiCad artwork overlay in [LIVE_KICAD_SPEC.md](./LIVE_KICAD_SPEC.md) (**LIVE-***), catalog depth / 3D pointers / SPICE operator follow-on in [CATALOG_DEPTH_SPEC.md](./CATALOG_DEPTH_SPEC.md) (**CAT-***, **3D-***, **SPS-05x**), and operator workflow gates in [WORKFLOW_GATES_SPEC.md](./WORKFLOW_GATES_SPEC.md) (**ECO-***, **LOCK-***, **MFG-010**, **PWR-010**, **PIN-001**, **VAR-001**, **LIVE-010**, **PLC-001**, **TST-001**, **GLD-001**).

## Compile goals

| Goal | Meaning |
|------|---------|
| **handoff** | Reviewable KiCad / netlist / BOM artifacts; some gaps may warn and continue. |
| **fabrication** | Fail-closed path toward a fab package (pins, pads, footprints, routing completeness, PCB DRC, offline catalog). See **FAB-*** IDs. |

`--production` today tightens KiCad + JIT strictness; Phase-2 **FAB-030** requires it to imply the full fabrication gate set.

**Honest fab claim (Phase-2):** `--require-all` is the **2×0805 resistor golden** only ([PRODUCTION_VALIDATION.md](./PRODUCTION_VALIDATION.md)). A fabrication compile for that class either emits audited release/Gerber outputs or exits non-zero. OpenHaC does **not** claim production-ready copper from autoroute alone for HS/RF/multi-IC (see non-goals / **PCB-007**, **FAB-051**, **ABC-008**).

## Tier A — Logic & manufacturing data

- Declarative Python (`Module`, `Interface`, `Board`) driving a **native** circuit graph (`openhac.core.circuit`) as the electrical source of truth (**FAB-004**). Residual SKiDL usage is legacy/handoff only until migration completes.
- **BOM** (`.csv`) with LCSC-oriented fields where the database provides them.
- **ERC** (floating nets, unconnected pins, power flags, power budget) and **DRC** (board bounds, IPC-2152 vs design min trace width) on the native graph.
- **SQLite** component catalog + optional sync / JIT lookup (JIT blocked or fail-closed under fabrication — **FAB-010**, **FAB-011**). Catalog **depth** (named pin table, real footprint, 3D pointer) is the success metric, not SKU count — [CATALOG_DEPTH_SPEC.md](./CATALOG_DEPTH_SPEC.md) (**CAT-***, **3D-***). `openhac sync` / enrich / overlay run **before** `--production`; a warehouse dump without pinouts is not compile-ready.
- **Human review:** native circuit graph is the **compile** source of truth. Cytoscape **webview** is deprecated (**FAB-041**); live preview is KiCad SVG from the schematic emitter (**SSO-012**); Hardware IR JSON may remain as a machine dump. When **`schematic_signoff`** / `--schematic-signoff` is set, the **EE stamp artifact** is the generated **`.kicad_sch`** (KiCad ERC clean, graph isomorphism) — see [SCHEMATIC_SIGN_OFF_SPEC.md](./SCHEMATIC_SIGN_OFF_SPEC.md) (**SSO-***). Fabrication compiles may still omit the drawing (**FAB-040**). Flat export by default; optional multi-sheet via `OPENHAC_SCHEMATIC_MULTI_SHEET=1` (**SCH-002** / **SSO-030**). **`kicad-cli sch erc`** is required under sign-off (**SSO-040**) and is **not** replaced by preview; optional otherwise (**SCH-003**).

## Tier B — KiCad PCB & placement

- **`.kicad_pcb`**: board outline, **footprint instances**, **pad ↔ net** assignment for ratsnest, **Z3** module-level placement hints.
- Requires **KiCad Python (`pcbnew`)** and on-disk **`*.pretty`** libraries (`KICAD8_FOOTPRINT_DIR` / install paths).
- Fabrication mode requires footprint presence and pad↔pin parity (**FAB-002**, **FAB-003**, **FAB-020**).

## Tier C — KiCad ecosystem & fabrication handoff

- Optional **schematic** (`.kicad_sch`) + **project stub** (`.kicad_pro`); not required for the fab claim (**FAB-040**). Required and ERC-gated under `--schematic-signoff` (**SSO-040**).
- **Autorouting** via **FreeRouting** + **`kicad-cli`** DSN/SES (when enabled). Fabrication requires routing completeness (**FAB-021**) and **KiCad PCB DRC** (**FAB-022**).
- **`openhac export fab`**: **Gerbers**, **Excellon drill**, **CSV position** via **`kicad-cli`**; optional **`--ipc2581`** (**FAB-031** CI golden).
- **`{name}.openhac-manifest.json`** after **`compile`**, including Phase-2 **fab_audit** fields when implemented (**FAB-032** / **MFG-005** / **STR-002**).

## SPICE (parallel path)

- **Handoff:** `.cir` generation from the same circuit graph (`openhac simulate`, or `openhac compile --run-ngspice`). May be unsolvable; generic IC value lines are not physics-correct.
- **`--spice-signoff` (SPS-*):** on `compile` or `simulate`; fail-closed Kirchhoff deck for the **analog island** (default: whole board minus connectors and digital cores). `declare_spice_island` / `--spice-island` stamps named modules only. In-island analog ICs still need **vendor or in-repo physics models**. See [SPICE_SIGN_OFF_SPEC.md](./SPICE_SIGN_OFF_SPEC.md). Git does **not** ship proprietary vendor `.lib` files; they live in `OPENHAC_SPICE_VENDOR_DIR`. Behavioral E-source stubs are **not** physics-correct unless explicitly waived. `--production` does **not** imply SPICE sign-off. Operator follow-on (coverage CLI, vendor-dir verify, more in-repo physics decks — **not** HTTP fetch of `.lib`) is **SPS-05x** in [CATALOG_DEPTH_SPEC.md](./CATALOG_DEPTH_SPEC.md).

## Non-goals (today)

- **SI/PI sign-off** — no impedance, eye, or PDN targets in core (see **SIG-001** / **SIG-003** in the production spec).
- **EMC / EMI compliance** — shielding, return paths, and emissions are **manual** engineering plus test lab; OpenHaC does not assert EMC sign-off (**SIG-004**).
- **Digital verification** — timing, CDC, formal methods, and gate-level sign-off are **out of scope** for the core toolchain (**SIM-003**); analog SPICE sign-off is **SPS-*** and does not cover digital cores.
- **Multi-rail power trees** with full converter efficiency modeling (partial rail ERC exists; named rails + `draws_from` vs `max_amp` is **PWR-010** in [WORKFLOW_GATES_SPEC.md](./WORKFLOW_GATES_SPEC.md) and does **not** claim converter efficiency).
- **Automated fab DFM** beyond what **KiCad** / **`kicad-cli`** exports provide.
- **Guarantee** of production-ready **high-speed** or **RF** layouts from **autoroute alone** (**PCB-007**): FreeRouting is **routing assistance**, not USB HS/PCIe-grade constraint solving. **`Board.route_differential_pair()`** records intent but **does not** drive impedance-controlled geometry in the exporter (**SIG-002**); finish pair rules in KiCad.
- **Stackup / SI handoff** — use a human-edited stackup file (see **`../stackup_template.yaml`**, **SIG-001**); OpenHaC does not solve impedance from geometry alone.
- **Mains / reinforced isolation** — not a certified mains or creepage tool; IEC spacing needs expert review (**REL-002**).
- **BGA / dense fanout** — no automated escape routing; plan fanout manually or in external CAD (**PCB-008**). Fabrication may **fail closed** on detected BGA without `allow_manual_bga_fanout` (**ABC-026…028**).
- **Advanced board capabilities** — multi-IC route+DRC reliability, API library quality, HS/RF **policy** gates: [ADVANCED_BOARD_CAPABILITIES_SPEC.md](./ADVANCED_BOARD_CAPABILITIES_SPEC.md). Does not override the SI/EMC/BGA non-goals above until each ABC acceptance is met.
- **Schematic vs compile SoT** — the native graph remains the compile source of truth. Algorithmic sheets are not a substitute for that graph. Saved KiCad files are an **artwork overlay** (pose + user wires/copper), not a second HDL ([LIVE_KICAD_SPEC.md](./LIVE_KICAD_SPEC.md)). When **`schematic_signoff`** is requested, the stamped **review** artifact is `.kicad_sch` ([SCHEMATIC_SIGN_OFF_SPEC.md](./SCHEMATIC_SIGN_OFF_SPEC.md)). Fab packages may still omit the drawing (**FAB-040**). Cytoscape webview is deprecated; preview is KiCad SVG (**SSO-012**); ERC remains `kicad-cli sch erc` (**SSO-040** / **FAB-041**). Live preview does not replace that stamp.
- **Phase-3 ecosystem items** (pip-installable hermetic modules, split backend packages, release signing) — listed in [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md); not Phase-2 acceptance.

When README or marketing copy refers to “tiers,” **Tier 1–3** there means **internal architecture** (database / core / compiler), not the capability levels above.
