# OpenHaC — SPICE Sign-Off Specification (SPS)

**Purpose:** Normative contract for a **physics-correct** analog path: Kirchhoff-faithful ngspice decks, **vendor (or open physics) SPICE models** as the device source, datasheet benches, and a fail-closed `--spice-signoff` gate on `openhac simulate` and `openhac compile`.

**Audience:** Core maintainers implementing SPICE generation, model registry, and CI goldens.

**Status:** Normative. Progress tracked in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) (SPS table).

**Relationship:** Phase-1 **SIM-001…003** remain **closed**. This document uses the **`SPS-*`** prefix. It does **not** reopen SIM acceptance. Handoff `openhac simulate` may still write a generic `.cir`; **SPS** is an additive `spice_signoff` gate set. Analogous to [SCHEMATIC_SIGN_OFF_SPEC.md](./SCHEMATIC_SIGN_OFF_SPEC.md) (**SSO-***).

**Product scope:** [SCOPE.md](./SCOPE.md).

---

## Honest claim

When `Board.spice_signoff` is true (CLI `--spice-signoff` on `simulate` or `compile`):

> Simulate either instantiates the native graph as a Kirchhoff-correct ngspice deck — ground is `0`, every non-primitive uses a **registered vendor (or waived physics) model** with a datasheet-validated pin map, declared rails are sources, the solver converges, and declared probes / model benches match datasheet windows — or exits non-zero.

OpenHaC **does** claim: topology fidelity, vendor-model *instantiation* (right file, subckt, pins), and **encoded datasheet DC/OP checkpoints**.

OpenHaC does **not** claim the vendor macromodel is a perfect physical twin, SI/PI, EMC, MCU digital internals, corners/Monte Carlo, or that an unannotated board is simulatable.

**Analog islands (SPS-043):** `--spice-signoff` on a mixed compute board does not require an ESP32 SPICE twin. `Board.declare_spice_island(...)` / `--spice-island MODULE` stamps only those modules. Digital cores are omitted even without an island. Analog ICs inside the island still fail closed without a vendor/physics model.

**Behavioral models are not the sign-off default.** `kind=behavioral` is allowed only with an explicit waiver (`quality_gates["allow_behavioral_spice_models"]=True`, CLI `--allow-behavioral-spice-models`, or per-part). Bundled behavioral fixtures exist **only** to unit-test the generator, never to satisfy device-physics sign-off.

Python `Board` remains the authoring source of truth. The native circuit graph remains the electrical source of truth. The generated `.cir` plus ngspice log / probe table is the analog stamp artifact. `--production` does **not** imply SPICE sign-off.

---

## Physics layers (both required under sign-off)

1. **Circuit physics (Kirchhoff)** — the deck is isomorphic to the native graph: every pin maps to the right node, ground is node `0`, no dropped subckt terminals, legal node names, rails have sources. A wrong pin order is a **wrong circuit**, even if ngspice converges.
2. **Device physics** — semiconductors and other non-primitives use **vendor (or vendor-equivalent physics) SPICE models**, not a `U1 n1 n2 ESP32` value line and not an unmarked behavioral `E` source. A behavioral LDO that forces 3.3 V has no dropout, PSRR, or current limit.

| Element | Physics-correct under sign-off | Not physics-correct |
|---------|--------------------------------|---------------------|
| Passives R/C/L | Lumped ideal values from the part (v1). Optional ESR/C0 later. | Invented values; 1-pin dropped parts |
| Ground | One reference node `0`; merged grounds via recorded hints | Net named `GND` that is not `0`; silent AGND/DGND short |
| MOSFET / LDO / IC | Vendor `.lib`/`.subckt` (or foundry/physics model) + `pin_map` + bench | Value-line `U1 … ESP32`; unmarked behavioral E-source |
| Pins | Every subckt terminal present in `pin_map` order | Sort-by-pin-number; omit unconnected pins |
| Rails | Independent voltage sources to `0` | Preset `.dc V1` when `V1` does not exist |
| Checks | Datasheet DC windows (Vout, Vth, Id at a bias) | Solver exit 0 with no numbers |

**Temperature (v1):** TNOM = 27 °C. Benches must record `temp_c`. Optional `.temp` corners are stretch.

---

## Modes and severity

| Mode | Intent |
|------|--------|
| **handoff** (`openhac simulate` without the flag) | Write `.cir`; may warn; may be electrically unsolvable; generic value lines allowed |
| **`spice_signoff`** | Kirchhoff + vendor/physics models + ngspice + benches/probes |
| **`--production` / fabrication** | Unchanged fab gates. Does **not** imply SPICE sign-off |

| Severity | Meaning |
|----------|---------|
| **P0** | Silent wrong physics (wrong pins, wrong ground, fake IC primitive) |
| **P1** | Blocks CI confidence or audit |
| **P2** | Docs / polish |

Each requirement includes: **problem**, **current state**, **target state**, **acceptance criteria**, and **approach**.

---

## Default policy matrix

| Policy | handoff | spice_signoff | `--production` alone |
|--------|---------|---------------|----------------------|
| `.cir` export | Yes | **Required** | n/a |
| Ground → node `0` | Yes (Kirchhoff even in handoff) | **Required** | n/a |
| Legal node names (`3V3` → `N_3V3`) | Yes | **Required**; collisions **fail** | n/a |
| Non-primitive without model | Generic value line | **Hard fail** unless omitted (connector / digital core / out of island) | n/a |
| `kind=behavioral` | Allowed | **Fail** unless waived | n/a |
| Vendor `.lib` missing / checksum mismatch | Warn | **Hard fail** | n/a |
| ngspice | Optional `--run-ngspice` | **Required** | n/a |
| Datasheet benches / probes | Optional | **Required** when declared | n/a |
| Drop unconnected subckt pins | Allowed (legacy) | **Forbidden** | n/a |

---

## Architecture

```mermaid
flowchart TD
  graph[Native circuit graph]
  pinout[pinout_json]
  registry[Model registry JSON]
  vendorDir[OPENHAC_SPICE_VENDOR_DIR]
  resolve[ModelResolver]
  gen[generate_spice]
  cir[".cir"]
  ng[ngspice -b]
  kirchhoff[Kirchhoff pin and ground checks]
  benches[Datasheet physics benches]
  probes[Board OP probes]
  prim[Ideal R C L V I]
  waiver[Behavioral waiver only]

  graph --> kirchhoff
  pinout --> resolve
  registry --> resolve
  vendorDir --> resolve
  waiver -.-> resolve
  resolve --> gen
  prim --> gen
  kirchhoff --> gen
  gen --> cir
  cir --> ng
  ng --> benches
  ng --> probes
```

Implementation lives in `openhac/compiler/spice_gen.py`, `spice_models.py`, `spice_nodes.py`, `spice_physics.py`, `ngspice_runner.py`. Registry JSON under `openhac/database/spice_model_overlays/`. Shipped **open/physics** netlists (not proprietary vendor IP) under `openhac/database/spice_models/`. Vendor macromodels live in **`OPENHAC_SPICE_VENDOR_DIR`** at run time.

The compiler must not hardcode MPN → pin maps in Python. Pin permutation is **data**.

---

## Vendor models (first-class)

Cannot commit TI / Infineon / NXP / Diodes Inc. macromodels (copyright). Physics sign-off still **requires** them at run time for `kind=vendor` parts:

- **`OPENHAC_SPICE_VENDOR_DIR`** (CLI `--spice-vendor-dir`) holds vendor files.
- Registry JSON **is** in-repo: MPN, subckt, `pin_map`, SPDX license, **sha256**, manufacturer URL, `physics_checks[]`.
- Missing file, checksum mismatch, or ngspice-incompatible dialect → **hard fail** under sign-off.
- A model is not registered until its **`physics_checks[]` bench** passes. Wrong `pin_map` fails the bench even if the `.lib` is authentic.
- No network fetch of `.lib` in v1 (license / reproducibility).
- CI Kirchhoff tests always run. Vendor physics goldens run when the vendor dir is present; `--require-vendor-models` **fails** if it is absent. Default CI **skips** vendor-file goldens rather than silently substituting behavioral models.

### Model `kind`

| `kind` | Meaning under sign-off |
|--------|-------------------------|
| `primitive` | R/C/L/V/I value lines only |
| `vendor` | Manufacturer macromodel; file in vendor dir; benches required |
| `physics` | Open / foundry / in-repo SPICE that uses device equations (e.g. LEVEL-1 MOSFET); treated like vendor for benches |
| `behavioral` | Controlled-source stub; **waiver only** |

### Registry record schema

| Field | Required | Meaning |
|-------|----------|---------|
| `generic_name` and/or `mpn` | one of | Match key |
| `kind` | yes | See table above |
| `include` | yes if not primitive | Path; `${OPENHAC_SPICE_VENDOR_DIR}` expanded |
| `subckt` | yes if not primitive | `.subckt` name |
| `pin_map` | yes if not primitive | `{num, name, subckt_index}` 1-based terminal order |
| `sha256` | yes for vendor files | Hex digest of the include file |
| `license` | yes | SPDX id |
| `physics_checks` | yes for vendor/physics | Bench list |
| `subckt_pin_count` | no | If set, must equal `len(pin_map)` and parsed `.subckt` arity |
| `simulator` | no | Default `ngspice` |

Example:

```yaml
mpn: AP2112K-3.3
kind: vendor
include: "${OPENHAC_SPICE_VENDOR_DIR}/diodes/AP2112.lib"
subckt: AP2112K
sha256: "..."
license: LicenseRef-Vendor-NoRedistribute
pin_map:
  - {name: VIN, num: "1", subckt_index: 1}
  - {name: GND, num: "2", subckt_index: 2}
physics_checks:
  - name: vout_10mA
    analysis: .op
    rails: {VIN: 5.0}
    load_ohm: 330
    probe: VOUT
    vmin: 3.201
    vmax: 3.399
    temp_c: 27
```

### Resolution order

1. Per-part fields (`Spice_Include`, `Spice_Subckt`, `Spice_Pin_Map`, `Spice_Kind`)
2. SQLite `spice_include` / `spice_subckt` / `spice_model_path`
3. Bundled registry JSON (`openhac/database/spice_model_overlays/`)
4. User overlay `OPENHAC_SPICE_MODEL_OVERLAY`

Primitives (`R`/`C`/`L`/`V`/`I` ref prefixes): value lines only. Never emit an IC as a primitive.

---

## Golden commands

Kirchhoff (no vendor IP):

```bash
OPENHAC_NO_NETWORK=1 openhac simulate board.py \
  --name sps_rc \
  --spice-signoff \
  -o dist/sps_rc
```

Vendor physics (requires local `.lib` files):

```bash
OPENHAC_NO_NETWORK=1 OPENHAC_SPICE_VENDOR_DIR=/path/to/vendor-libs \
  openhac simulate board.py \
  --name sps_ldo \
  --spice-signoff \
  --require-vendor-models \
  -o dist/sps_ldo
```

---

## Current state (honest)

As of this spec’s first implementation, the following defects in `spice_gen` / `Board.simulate` / `ngspice_runner` are the **problems** the IDs close:

- `GND` was not aliased to `0`
- Unconnected pins omitted; instance order was pin-number sort
- `spice_model_path` unused; no `pin_map`; no vendor dir; no checksum
- `require_spice_models` existed on `Board.simulate` but was off and not on the CLI
- `--run-ngspice` only checked process exit; log parser counted the substring `error`
- ngspice smoke used a **hand-written** RC deck, not `generate_spice` output
- Catalog overlay merge keys omitted SPICE fields
- No datasheet benches

---

## A. Kirchhoff / topology (SPS-001…006)

### SPS-001 — Ground is SPICE node `0`

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | A net named `GND` is not the SPICE reference. Decks float or fail. |
| **Current state** | `_sanitize_net_name("GND")` stays `GND`. |
| **Target state** | `GND` / `VSS` / `PGND` / `EARTH` map to `0`. Nets with `declare_net_merge_hint` to those names also map to `0`. Isolated `AGND`/`DGND` stay named unless merged. |
| **Acceptance criteria** | Generated deck uses `0` on ground pins; pytest asserts no ground pin left as token `GND` under sign-off. |
| **Approach** | `openhac/compiler/spice_nodes.py`. |

### SPS-002 — Never drop subckt terminals

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Omitting an unconnected pin shifts later arguments → wrong device physics. |
| **Target state** | Instance lists **every** `pin_map` terminal in order. Unconnected non-ground terminals fail under sign-off (do not elide). |
| **Acceptance criteria** | Fixture with NC pin still emits N terminals; dropping a pin fails the test. |
| **Approach** | `generate_spice` sign-off path. |

### SPS-003 — Pin permutation is data

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Sort-by-symbol-pin-number ≠ vendor `.subckt` order. |
| **Target state** | `pin_map` from registry / `Spice_Pin_Map` / `pinout_json`. No compiler MPN tables. |
| **Acceptance criteria** | Two-pin subckt with swapped map changes instance node order. |
| **Approach** | `spice_models.py` + part fields. |

### SPS-004 — Legal SPICE node names

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `3V3` can parse as `3`; `A-B` and `A_B` collide after sanitization. |
| **Target state** | Leading-digit nets get `N_` prefix. Distinct graph nets that sanitize to the same token **fail**. |
| **Acceptance criteria** | `3V3` → `N_3V3`; collision fixture raises. |
| **Approach** | `spice_nodes.py`. |

### SPS-005 — Non-primitives need a real model

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | ICs emit `U1 n1 n2 ESP32`, which is not a SPICE device. Connectors (`J*`) were incorrectly in the same bucket; ngspice letter `J` is a JFET. |
| **Target state** | Under sign-off, missing vendor/physics model **hard-fails** unless behavioral waiver. **Connectors, test points, and mounting hardware are omitted** (interface, not a device) unless they carry an explicit `Spice_Subckt`. **Digital cores** (MCU/FPGA/USB-UART) are omitted (SIM-003) unless they carry an explicit model. **`declare_spice_island` / `--spice-island`** limits the analog deck to named modules; other modules are omitted (`out_of_island`). |
| **Acceptance criteria** | Unannotated analog IC (LDO) simulate `--spice-signoff` exits non-zero. Unannotated header `J1` and MCU `ESP32` do **not**. Island-only passives sign off while an unmodeled LDO on another module is omitted. |
| **Approach** | Coverage gate + `kind` check in `generate_spice`. |

### SPS-006 — Graph↔deck pin-net isomorphism

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | No check that each connected graph pin appears as that SPICE node on the instance (SSO-001 analog). |
| **Target state** | Parity helper: connected pin → sanitized node on the emitted line. |
| **Acceptance criteria** | Pytest on a 3V3/GND resistor; mismatch raises. |
| **Approach** | `spice_gen.graph_deck_pin_parity` (or equivalent) used under sign-off. |

### SPS-007…009 — Reserved

Stretch: multi-ground islands with explicit coupling networks.

---

## B. Device physics / vendor registry (SPS-010…018)

### SPS-010 — Registry JSON schema

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | No first-class model catalog. |
| **Target state** | Loader for the schema above; invalid records raise. |
| **Acceptance criteria** | Unit test loads overlay; rejects missing `kind` / `pin_map`. |
| **Approach** | `openhac/compiler/spice_models.py`. |

### SPS-011 — Vendor dir + checksum

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `spice_model_path` unused; paths not verified. |
| **Target state** | Expand `${OPENHAC_SPICE_VENDOR_DIR}`; sha256 must match for `kind=vendor`. |
| **Acceptance criteria** | Wrong hash fails; missing file fails under sign-off. |
| **Approach** | Resolver in `spice_models.py`. |

### SPS-012 — Stamp resolved model onto the part

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | BOM/hint can disagree with what was simulated. |
| **Target state** | Stamp `Spice_Include`, `Spice_Subckt`, `Spice_Pin_Map`, `Spice_Kind`, `Spice_Model_Sha256`. |
| **Acceptance criteria** | After resolve, part fields match the registry hit. |
| **Approach** | Resolver called from `generate_spice` / `Board.simulate`. |

### SPS-013 — Behavioral fixtures are generator-only

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Easy to treat an E-source LDO as physics. |
| **Target state** | Bundled `kind=behavioral` models under `openhac/database/spice_models/`; cannot close sign-off without waiver. |
| **Acceptance criteria** | Sign-off with only behavioral LDO fails unless `--allow-behavioral-spice-models`. |
| **Approach** | Overlay + `kind` gate. |

### SPS-014 — No silent missing vendor file; no v1 download

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Missing `.include` path only fails inside ngspice, if at all. |
| **Target state** | File must exist before ngspice. No HTTP fetch of `.lib`. |
| **Acceptance criteria** | Missing include raises `OpenHaCError` under sign-off. |
| **Approach** | Resolver. |

### SPS-015 — Primitive R/C/L values

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | ICs must not ride the value-line path. |
| **Target state** | Ref prefixes R/C/L/V/I pass `part.value` through (ngspice suffixes `k`/`u` allowed). Other prefixes need a model. |
| **Acceptance criteria** | `R1 N_3V3 0 1k` golden; `U1 …` fails sign-off. |
| **Approach** | `spice_gen` primitive detector. |

### SPS-016 — `physics_checks[]` runner

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | A `.lib` can be authentic and still be instantiated on the wrong pins. |
| **Target state** | Build a bench deck from the check record; ngspice `.op`/`.dc`; assert `[vmin, vmax]`. |
| **Acceptance criteria** | In-repo `kind=physics` MOSFET or tmp vendor-like `.lib` bench passes; swapped pin_map fails. |
| **Approach** | `openhac/compiler/spice_physics.py`. |

### SPS-017 — Refuse behavioral unless waived

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Default sign-off would otherwise accept stubs. |
| **Target state** | `allow_behavioral_spice_models` gate (quality_gates / CLI / env). |
| **Acceptance criteria** | CLI/API test both fail and pass-with-waiver. |
| **Approach** | `Board.simulate` / CLI. |

### SPS-018 — `pin_map` covers `.subckt` terminals

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Short maps omit terminals. |
| **Target state** | `len(pin_map)` equals parsed `.subckt` arity and optional `subckt_pin_count`. |
| **Acceptance criteria** | Truncated map fails. |
| **Approach** | Parse `.subckt` line from include file. |

### SPS-019 — Reserved

Stretch: auto-download with license allow-list.

---

## C. Stimulus (SPS-020…023)

### SPS-020 — Declared rails become `V` sources

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Boards have named rails but no SPICE sources. |
| **Target state** | `Board.declare_spice_rail(net, voltage_v)` and/or `declared_supply_voltages_v` emit `V… <rail_node> 0 DC <v>`. Power net with no source and not ground **fails** sign-off. |
| **Acceptance criteria** | Divider golden includes a V source to `0`. |
| **Approach** | `Board` + `generate_spice`. |

### SPS-021 — Analysis must name real devices/nodes

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Presets `.dc V1` / `.noise V(out) V1` assume a different circuit. |
| **Target state** | Under sign-off, analysis tokens `V1` / node `out` fail unless present. Default analysis is `.op` plus probes. |
| **Acceptance criteria** | `--spice-preset dc` on a board without `V1` fails sign-off. |
| **Approach** | Validator in `spice_gen` / `Board.simulate`. |

### SPS-022 — Board-level OP probes

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | No numeric assertion on the user’s circuit. |
| **Target state** | `Board.declare_spice_probe(net, vmin, vmax)` compared to parsed OP voltages. |
| **Acceptance criteria** | Divider Vmid window passes; inverted window fails. |
| **Approach** | `spice_physics.py` + ngspice print. |

### SPS-023 — TNOM documented on benches

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Temperature is part of device physics. |
| **Target state** | Decks set `TEMP`/`TNOM` 27 °C unless overridden; each bench records `temp_c`. |
| **Acceptance criteria** | Generated sign-off `.cir` contains TNOM 27; registry checks include `temp_c`. |
| **Approach** | Header lines in `generate_spice`. |

---

## D. Fail-closed simulate (SPS-030…034)

### SPS-030 — `--spice-signoff` implies the full gate set

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Optional `require_spice_models` / `run_ngspice` are easy to omit. |
| **Target state** | Flag sets `Board.spice_signoff`; implies ngspice, model coverage, benches, probes. |
| **Acceptance criteria** | CLI help + subprocess test. |
| **Approach** | `cli.py`, `Board.simulate`. |

### SPS-031 — ngspice missing or solver error fails

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Easy to skip the solver. |
| **Target state** | No skip under sign-off. Non-zero ngspice exit fails. |
| **Acceptance criteria** | Mock missing binary raises. |
| **Approach** | `ngspice_runner.py`. |

### SPS-032 — Parse OP **numbers**

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | `parse_ngspice_log` counts the word `error`. |
| **Target state** | Extract `v(node)=` / print table floats; compare probe windows. |
| **Acceptance criteria** | Parser unit test + divider golden. |
| **Approach** | `parse_ngspice_op_voltages`. |

### SPS-033 — Kirchhoff golden from **generated** deck

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | Existing ngspice smoke is hand-written RC, not `generate_spice`. |
| **Target state** | Generated source + R + C or divider; node `0`; Vout window. |
| **Acceptance criteria** | `tests/test_sps_spice_signoff.py` (skip if no ngspice). |
| **Approach** | Pytest. |

### SPS-034 — Vendor physics golden policy

| Field | Content |
|-------|---------|
| **Severity** | P0 |
| **Problem** | CI cannot ship proprietary `.lib` files. |
| **Target state** | LDO and/or MOSFET from vendor dir + registry benches. **Fail** under `--require-vendor-models` if dir empty. Default CI: skip vendor-file test; run an in-repo `kind=physics` or tmp hashed `.lib` bench instead. Never fall back to behavioral. |
| **Acceptance criteria** | Skip/fail policy tests; tmp vendor-like lib bench passes. |
| **Approach** | Pytest + env. |

### SPS-035…039 — Reserved

Stretch: `.temp` corners, Monte Carlo, Xyce.

---

## E. Audit / docs (SPS-040…044)

### SPS-040 — `spice_signoff_audit`

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | No record of which model/hash was simulated. |
| **Target state** | `{project}.openhac-spice-signoff-audit.json` (and compile-manifest key when present): model kind, sha256, include path, pin_map hash, bench results, probe results, ngspice log path. |
| **Acceptance criteria** | Sign-off run writes the JSON. Coverage rows list each part as `primitive` / `modeled` / `omitted` / `unmodeled`. Failed sign-off still writes the JSON with `passed: false`. |
| **Approach** | `Board.simulate`. |

### SPS-043 — Analog island / subgraph sign-off

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Whole-board `--spice-signoff` demanded a model for every `U*`, including MCUs that have no analog SPICE twin. That blocks stamping a power island on a compute brick. |
| **Target state** | `declare_spice_island` / `--spice-island` restrict the deck to named modules (and their descendant modules). Digital cores omitted (SIM-003). Connectors omitted. In-island analog ICs still SPS-005. |
| **Acceptance criteria** | Pytest: MCU+resistor sign-off succeeds; island of passives succeeds while an unmodeled LDO on another module is omitted; unmodeled LDO *in* the island fails SPS-005. |
| **Approach** | `spice_omit_reason` + `Board.declare_spice_island` + CLI. |

### SPS-044 — Coverage in the sign-off audit

| Field | Content |
|-------|---------|
| **Severity** | P1 |
| **Problem** | Fail-closed errors did not list which refs were omitted vs unmodeled. |
| **Target state** | Audit `coverage[]`: `{ref, value, module, status, reason}` with omit reasons `connector_mechanical` / `digital_core` / `out_of_island`. |
| **Acceptance criteria** | Pytest on coverage helper + failed simulate writes audit JSON. |
| **Approach** | `collect_spice_coverage` in `spice_models.py`. |

### SPS-041 — Docs honesty

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | SCOPE said limited fidelity; README said `.cir` without a physics claim. |
| **Target state** | SCOPE / README / RELEASE_CHECKLIST / IMPLEMENTATION_STATUS / ARCHITECTURE / this spec. Vendor models required for device physics; git does not ship proprietary `.lib`. |
| **Acceptance criteria** | Those files exist and use the honest claim. |
| **Approach** | Docs. |

### SPS-042 — Hint markdown is not a pin_map substitute

| Field | Content |
|-------|---------|
| **Severity** | P2 |
| **Problem** | `{project}.openhac-spice-model-hint.md` asked humans to check pin order. |
| **Target state** | Handoff may still write the hint. Sign-off **enforces** pin_map/benches; the checklist must not be the only control. |
| **Acceptance criteria** | Hint writer unchanged for handoff; sign-off tests do not treat the md as sufficient. |
| **Approach** | Docs + tests. |

---

## Non-goals (v1)

- Digital verification (timing, CDC, formal) — **SIM-003**
- SI/PI, EMC/lab, IBIS
- **Redistributing** proprietary vendor `.lib` in this git repo
- Claiming a vendor macromodel is a perfect physical twin beyond encoded datasheet windows
- Full MCU / digital-core SPICE (omit + coverage; analog islands are the stamp)
- Implying SPICE from `--production`
- Treating unmarked behavioral stubs as physics-correct
- `.temp` corners, Monte Carlo, Xyce, auto-download, passive ESR/C0 networks

---

## Implementation order

1. Node rules + generator Kirchhoff (SPS-001…006, 015, 023)
2. Registry + stamp + checksum (SPS-010…014, 017, 018)
3. Rails / probes / analysis validation (SPS-020…022)
4. ngspice numbers + CLI sign-off (SPS-030…033)
5. Physics benches + vendor policy (SPS-016, 034)
6. Audit JSON + docs (SPS-040…042)
