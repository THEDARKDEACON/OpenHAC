# OpenHaC — Workflow gates (ECO / LOCK / MFG / PWR / PIN / VAR / LIVE-010 / PLC / TST / GLD)

**Purpose:** Normative contract for the **operator workflow** after catalog depth and live KiCad overlay: graph ECO diffs, catalog lockfiles, assembler-shaped fab packs, a first-class power tree, pinout authoring, board variants/DNP, best-effort KiCad 10 PCB IPC revert, placement-intent vs overlay parity, declared testpoints, and a tracked SPICE-island golden that uses in-repo Apache physics. Not a second HDL. Not a browser live view. Not a native schematic renderer. Not SI/EMC/digital twins.

**Audience:** Core maintainers implementing compile/preview CLI, lock/export tooling, ERC, and CI goldens.

**Status:** Normative. Progress tracked in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) (workflow-gates table). Product scope: [SCOPE.md](./SCOPE.md).

**Relationship:** Does **not** reopen closed FAB/PERF/SSO/LIVE-001…008/SPS-010…044/CAT/3D/SPS-05x rows except as **pointers**. `--production` stays offline (**FAB-010**). HTTP fetch of vendor SPICE `.lib` stays forbidden (**SPS-019** reserved unused). `--require-all` stays the **2×0805 resistor** class only (**FAB-051**). Analogous to [LIVE_KICAD_SPEC.md](./LIVE_KICAD_SPEC.md) and [CATALOG_DEPTH_SPEC.md](./CATALOG_DEPTH_SPEC.md): additive IDs, not a rewrite of closed tables.

---

## Product lock

- **Electrical source of truth:** native circuit / `Board` (Python HDL). Adding or rewiring parts happens in the `.py`.
- **Artwork overlay:** last-saved `.kicad_sch` / `.kicad_pcb` (LIVE). KiCad is not SoT for ECO, lock, variants, or pinout.
- **Catalog lock is a BOM pin:** SKU / pinout hash / footprint recorded from the resolved catalog, checked offline. Production must not HTTP-refresh a lock.
- **Assembler packs do not invent SKUs.** Missing LCSC under a JLC/strict profile fails closed.
- **Power tree does not claim converter efficiency.** Declared `max_amp` vs declared draws only.
- **Pinout CLI does not scrape datasheets.** Catalog row and/or KiCad symbol oracle (**CAT-013**) only. Numeric-only IC tables are refused.
- **DNP stays on the BOM** (flagged) and is omitted from ERC connectivity / placement.
- **PCB IPC revert is best-effort KiCad 10.** Missing API / KiCad 9 / no socket must not crash preview. Schematic IPC is KiCad 11 — do not fake it.
- **No new autorouter.** Placement intent reuses LIVE overlay parse + existing DRC/fit.
- **SPICE still omits `TP*`** (**SPS-005**).

```
board.py ──► native graph (SoT) ──► ERC / lock / ECO / BOM
                │                         │
                │                         ▼
                └──► emit + LIVE overlay ──► KiCad artwork
                                              │
                         KiCad 10 PCB IPC revert (best-effort) ◄── preview --pcb --watch
```

---

## Honest claims

**ECO.** Compile writes a graph diff against the previous snapshot in the output directory. It reports refs/nets/overlay copper dropped because **graph** nets vanished. It does not treat KiCad as electrical truth.

**Lock.** `openhac lock` records catalog identity (SKU, pinout hash, footprint, optional 3D/SPICE hashes, `catalog_tier`). Fabrication fails closed when a lock file is present and the resolved BOM disagrees, or when `--require-lock` is set and the lock is missing. No network under `--production`.

**JLC pack.** `openhac export jlc` reshapes existing BOM/CPL. It does not invent LCSC C-codes.

**Power tree.** Declared rails with declared draws that exceed `max_amp` fail ERC. Unnamed power nets may still warn. Efficiency is not modeled here.

**Pinout CLI.** Writes an overlay JSON stub a human can edit. It will not persist a numeric-only IC pin table.

**Variants.** One Python board, variant name in the manifest, DNP on the BOM. Pin tables are not cloned per variant.

**IPC.** Preview still writes files if KiCad cannot reload. That is success for the compiler.

**Goldens.** Schematic stamp golden remains `examples/sso041_signoff_node.py`. SPICE-island golden uses bundled Apache decks. `--require-all` remains 2R.

---

## Modes and severity

| Mode | Network | Lock | ECO | JLC pack | Power / TP |
|------|---------|------|-----|----------|------------|
| **handoff** | Allowed unless `OPENHAC_NO_NETWORK` | Warn if missing or mismatch | Write report | Optional | ERC as declared |
| **`--production` / fabrication** | **Denied** | Fail if lock present and BOM disagrees; fail if `--require-lock` and lock missing | Write report | Fail closed on missing LCSC when assembler=`jlc` | Declared rails / declared TPs fail closed |
| **preview** | n/a | Not enforced | Write when overlay exists | n/a | n/a |
| **`openhac lock` / `pinout init`** | Denied under no-network; lock never fetches to refresh | Write lock from local catalog | n/a | n/a | n/a |

| Severity | Meaning |
|----------|---------|
| **P0** | Silent BOM drift, invented SKUs, lock refresh over HTTP, DNP still netted |
| **P1** | Operator polish: IPC revert, placement-intent freeze, pinout CLI, goldens |

Each requirement includes: **problem**, **current state**, **target state**, **acceptance criteria**, and **approach**.

---

## A. ECO-001 — Graph ECO / diff report

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Recompiling after a Python edit does not tell the operator which refs/nets appeared or vanished, or which overlay copper was dropped because a net left the graph. Easy to think KiCad still owns the netlist. |
| **Current state** | Manifest lists outputs. Overlay drop policy exists (LIVE-004/005) but is not a standalone ECO artifact. |
| **Target state** | On `compile` (and `preview` when a LIVE overlay exists), write `{project}.openhac-eco.json` with schema **`openhac.eco.v1`**: added/removed/changed refs, nets that appeared/vanished, overlay copper/wires dropped because nets vanished, pinout grade changes when cheap (catalog grade on unique `generic_name`s). Compare against previous ECO / previous graph snapshot / previous manifest in the **output dir**. Native graph is SoT — do not parse KiCad as the electrical baseline. |
| **Acceptance criteria** | Unit test: previous snapshot has `R2` + net `GONE`; new graph has `R3` not `R2`, net `GONE` absent → ECO lists removed `R2`, added `R3`, vanished `GONE`, and overlay track on `GONE` under `overlay_copper_dropped`. First compile with no baseline still writes `current` + empty diffs. |
| **Approach** | `openhac/compiler/eco.py`; compile phase before manifest. Baseline precedence: previous `.openhac-eco.json` `current` → `.openhac-graph.json` → refs/nets in previous manifest. |

---

## B. LOCK-001 — Catalog lockfile

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Catalog JIT/enrich can change SKU, footprint, or pin table between a review compile and a fab compile with no recorded pin. |
| **Current state** | No lockfile. Coverage grades exist (**CAT-001**). `--production` is offline (**FAB-010**) but does not pin resolved BOM identity. |
| **Target state** | `openhac.lock` and/or `{project}.openhac-lock.json` (schema **`openhac.lock.v1`**) records per unique `generic_name`: SKU, MPN, pinout hash, footprint, 3D sha256 if present, spice include/sha256 if present, `catalog_tier`. `openhac lock BOARD.py` writes it from the **local** catalog + board instances (no HTTP). Fabrication: if a lock is present next to the board script (or `--lock-file`) **fail** when resolved BOM disagrees on pinout hash / SKU / footprint. `--require-lock` fails if the lock is missing. If no lock: **warn** in handoff (do not fail fabrication solely for a missing lock unless `--require-lock`). Must not refresh the lock over the network under production. |
| **Acceptance criteria** | Test: lock SKU `C1` + compile resolves `C2` under fabrication → non-zero. Test: `--require-lock` and no file → non-zero. Test: `OPENHAC_NO_NETWORK=1` lock write does not open a socket. Handoff without a lock logs a warning. |
| **Approach** | `openhac/database/catalog_lock.py`; pin hash in `pin_policy.pinout_hash`. Discovery: `--lock-file`, `openhac.lock` beside the script, `{stem}.openhac-lock.json` beside the script, then `{project}.openhac-lock.json` in the output dir. |

---

## C. MFG-010 — Assembler-shaped release pack (JLC)

| Field | Content |
|-------|---------|
| **Severity** | P0 / P1 |
| **Problem** | `export fab` writes KiCad gerbers/pos, not JLCPCB SMT BOM columns (`Comment` / `Designator` / `Footprint` / `LCSC`). Operators reformat by hand and invent C-codes. |
| **Current state** | `openhac export fab` / `export assembly` wrap `kicad-cli`. BOM CSV has `Supplier_SKU` (**MFG-001/002**). |
| **Target state** | `openhac export jlc` (and `export fab --assembler jlc`) writes a JLC-shaped BOM and CPL/position CSV. Reuse gerber/pos export. Fail closed if LCSC SKU is missing under assembler `jlc` / `--strict`. **Do not invent SKUs.** |
| **Acceptance criteria** | Test: BOM with `Supplier_SKU=C17513` → JLC row `LCSC Part #`/`LCSC` = `C17513`. Test: missing C-code + strict/jlc → error, empty LCSC not fabricated. Test: no HTTP. |
| **Approach** | `openhac/compiler/export_jlc.py`; reshape OpenHaC BOM + KiCad pos CSV. |

---

## D. PWR-010 — Power tree as a first-class API

| Field | Content |
|-------|---------|
| **Severity** | P0 / P1 |
| **Problem** | Rail ERC exists as `source_current_max_ma` / `max_current_draw_ma` dicts and `declare_rail_conversion` (efficiency). There is no first-class `declare_rail(name, voltage_v, max_amp)` + module `draws_from`. Easy to over-claim converter efficiency. |
| **Current state** | **PWR-001/002** in `rule_check.py` / `Board.declare_rail_conversion`. `declare_spice_rail` for SPS. Unnamed power nets warn via prefixes. |
| **Target state** | `Board.declare_power_tree` / `Board.declare_rail(name, voltage_v, max_amp)` + `Module.draws_from(rail, amp=…)` (or `ma=`). Compile ERC: unnamed power nets may still warn; declared rails whose declared draws sum above `max_amp` **fail**. Optional: declared rails feed existing `declare_spice_rail` when `spice_signoff` is on. **Do not claim converter efficiency** in this API. |
| **Acceptance criteria** | Test: rail `3V3` max 0.1 A, module draws 0.2 A → `ERCPowerBudgetError`. Test: draws 0.05 A → pass. Efficiency is not a parameter on `declare_rail`. |
| **Approach** | `openhac/core/power_tree.py`; ERC in `rule_check._run_power_tree`. Reuse draw collection. |

---

## E. PIN-001 — Pinout authoring CLI

| Field | Content |
|-------|---------|
| **Severity** | P0 / P1 |
| **Problem** | IC pin tables still get written by hand or by numeric-only accident. No supported way to stub an overlay from the catalog / KiCad symbol oracle. |
| **Current state** | Overlays are JSON arrays (**CAT-008**). **CAT-013** fills names from a real `Library:Name`. **CAT-004** refuses numeric-only IC pinouts on sync/enrich. |
| **Target state** | `openhac pinout init REF_OR_GENERIC` writes an overlay JSON stub from the catalog row and/or KiCad symbol pin names when `kicad_symbol` is a real lib id. Hash the pin table. Refuse to write numeric-only IC pinouts. Document in USER_GUIDE. **No datasheet scrape.** |
| **Acceptance criteria** | Test: catalog row with named KiCad symbol → stub contains names ≠ numbers and a `pinout_hash`. Test: numeric-only MCU table → CLI non-zero, no file. Test: `Device:IC` is not treated as an oracle. |
| **Approach** | Reuse `fill_pin_names_from_kicad_symbol` / `pinout_from_kicad_symbol_id` + `pinout_hash`. Output catalog-overlay shape (`generic_name` + `pinout` list). |

---

## F. VAR-001 — Board variants / DNP

| Field | Content |
|-------|---------|
| **Severity** | P0 / P1 |
| **Problem** | Shipping a “lite” BOM means cloning the board or deleting modules. No DNP flag driven by a variant name. |
| **Current state** | BOM has a `DNP` column (test points / value substring). No `Board.variant`. |
| **Target state** | `Board(variant=…)` / `Board.set_variant` selects which modules are included / which parts are DNP. DNP parts **appear on the BOM marked DNP**, are **not netted** (ERC) and **not placed**. Variant name in the manifest. Do **not** clone pinouts. |
| **Acceptance criteria** | Test: two variants produce different BOM DNP (or included) sets. DNP part is absent from ERC connectivity (disconnected) and skipped in placement. Manifest contains `variant`. |
| **Approach** | `Module.include_in_variants` / `dnp_in_variants`; `openhac/core/variant.py` applied at compile start. |

---

## G. LIVE-010 — KiCad 10 PCB revert via IPC

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | After `preview --pcb --watch` rewrites `.kicad_pcb`, KiCad 9 often never prompts Reload. KiCad 10 has an API socket; ignoring it leaves the GUI stale even when IPC exists. A pcbnew `SaveBoard` daemon is still forbidden (SIGSEGV). |
| **Current state** | [LIVE_KICAD_SPEC.md](./LIVE_KICAD_SPEC.md) documents File → Revert. `kicad_live.py` spawns the GUI and watches `.py`. No IPC. Schematic IPC is a KiCad 11 topic. |
| **Target state** | After preview writes `.kicad_pcb`, try KiCad API board revert/reload if a socket exists (`ipc:///tmp/kicad/api-*.sock` or `kicad-python`). **Best-effort:** missing API / KiCad 9 / no socket → no crash, files still written. Do **not** fake schematic hot-reload. Do **not** add a pcbnew SaveBoard daemon. |
| **Acceptance criteria** | Test: no socket → `{attempted: false, reloaded: false}` and no exception. Test: mock client + socket → `reloaded true`. Test: client raises → caught, files already written. Schematic path is never claimed reloaded. |
| **Approach** | `try_pcb_revert_via_ipc` in `openhac/compiler/kicad_live.py`; call from `cmd_preview` after PCB write. Injectable client for tests. |

---

## H. PLC-001 — Placement intent vs overlay parity

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `--keep-kicad-artwork` can freeze footprints parked off-board or stacked on top of each other. Python already has keepout / no-autoroute / cluster APIs; freeze does not check overlay pose against them. |
| **Current state** | `declare_keepout_rect`, `declare_no_autoroute_net`, `cluster_with`. `pcb_fit` after layout. Overlay pose wins and skips the legalizer (LIVE-003). |
| **Target state** | Keep existing Python region/keepout/keep-together / no-autoroute declarations. **Minimum:** fail `--keep-kicad-artwork` or `--placement-intent` when an overlay footprint pose is outside the board outline, or two overlay refs have catastrophic courtyard overlap. Reuse LIVE overlay parse + existing DRC. **Do not write a new autorouter.** |
| **Acceptance criteria** | Test: overlay pose x=999 on a 20×20 mm board + keep/placement-intent → error. Test: two overlay refs at the same xy with overlapping courtyards → error. Test: in-board separated refs pass. |
| **Approach** | `openhac/compiler/placement_intent.py`; compile phase when keep or `--placement-intent`. `Module.keep_together` aliases `cluster_with`. |

---

## I. TST-001 — Testability compile

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | REL-003 can require a count of heuristic TPs, but there is no `declare_testpoint(net)` that ensures a TP footprint on that net and gates `--production`. |
| **Current state** | `min_test_points`, `require_test_point_on_nets`, `test_point_min_count_by_net`. SPICE omits `TP*` (**SPS-005**). |
| **Target state** | `Board.declare_testpoint(net)` (and a Module helper) ensures a TP footprint exists on that net. `--production` or `--require-testpoints` fails if declared testpoints are missing from the graph (and PCB when a board was emitted). SPICE still omits `TP*`. |
| **Acceptance criteria** | Test: declare TP on `3V3`, part present → pass. Test: declare then remove/DNP the TP + `--require-testpoints` → fail. Spice coverage still `omitted` for `TP1`. |
| **Approach** | Record + instantiate a `testability` TP part; DRC gate; reuse spice omit prefixes. |

---

## J. GLD-001 — Grow golden class (SPICE island, not `--require-all`)

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | `--require-all` is honestly 2R (**FAB-051**). Analog-island CI used resistors only; bundled Apache diode/opto/in-amp decks (**SPS-053**) were not a tracked golden. |
| **Current state** | `examples/spice_island_golden.py` is SPS-045 resistors + ignored digital. Bundled `d_1n4007.cir` / `pc817.cir` / `ad620.cir`. Schematic golden is `sso041_signoff_node.py` (**SSO-041**). |
| **Target state** | Grow/track a SPICE-island CI golden that instantiates bundled Apache physics (diode / opto / in-amp). Wire into tests or `scripts/ci_validate_*.py`. **Do not** change `--require-all` from 2R. Pair docs: USER_GUIDE / PRODUCTION_VALIDATION pointer. Schematic golden stays `sso041_signoff_node.py`. |
| **Acceptance criteria** | Test: golden script references `D_1N4007` / `OPTO_PC817` / `AD620` and bundled overlay includes those physics decks. `--require-all` help/docs still say 2R. No vendor `.lib` HTTP. |
| **Approach** | Extend `examples/spice_island_golden.py`; pytest in `tests/test_workflow_gates.py`; optional `--spice-island-golden` on production validator **not** implied by `--require-all`. |

---

## Out of scope

- HTTP fetch of vendor SPICE `.lib` / analog.com / ti.com scrape (**SPS-019** unused).
- Treating KiCad connectivity as compile SoT (LIVE parity still fails closed).
- Browser live editor or native schematic renderer (**SSO-012** / **FAB-041**).
- SI / EMC / digital twins / converter efficiency modeling.
- Schematic IPC hot-reload (KiCad 11).
- pcbnew in-process `SaveBoard` daemon (**CODE-001**).
- Inventing LCSC C-codes or numeric-only IC pin names.
- Changing `--require-all` to a multi-IC fab claim (**FAB-051**).
