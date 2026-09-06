# Production validation matrix (software)

**Purpose:** Define what OpenHaC **proves in CI / headless validation** before a board is claimed **fabrication-ready** for *supported* board classes — and what it does **not** claim.

**Normative gates:** [FABRICATION_READINESS_SPEC.md](./FABRICATION_READINESS_SPEC.md).  
**Status tracking:** [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md).

---

## Honest production claim

For **the CI golden fixture** — two 0805 resistors (`tests/fixtures/fab_golden_board.py`), not multi-IC / HS / RF boards:

> A green `scripts/ci_validate_production.py --require-all` (or the `kicad-production-validation` CI job) proves a **fail-closed software path** on that **2-pin passive class**: declarative code → native ERC/DRC → placed PCB → autorouted copper → KiCad PCB DRC → Gerbers/drill/pos, with audited pin/pad/net parity on the compile manifest.

`--require-all` does **not** imply HS, RF, EMC, or multi-IC production readiness. Complex boards use a separate matrix; default `--route` covers only `esp32c3_usb` and `rs485_node` (**ABC-008**).

This is **software fabrication readiness**, not a substitute for:

- Physical bring-up / functional test
- High-speed / EMC / RF design review
- CM DFM sign-off beyond exported fab pack checks

Autorouting remains **assistive**. See SCOPE **PCB-007**.

---

## Validation stages

| Stage | What runs | Pass means | Script / test |
|-------|-----------|------------|---------------|
| **V0 Unit FAB gates** | FAB-001/002/003/010 unit tests | Pin/network/pad policy holds offline | `tests/test_fab_phase2_gates.py` |
| **V1 Native ERC** | `run_erc` during compile | No electrical rule violations on native circuit | compile of golden (`--skip-layout` ok) |
| **V2 Native DRC** | `run_drc` during compile | Board geometry / catalog gates pass | same |
| **V3 Negatives** | FAB-001 corrupt pins, FAB-003 missing FP | Fail-closed refusals | fixtures under `tests/fixtures/fab_bad_*.py` |
| **V4 Schematic ERC** | `kicad-cli sch erc` on SCH-003 golden | Zero KiCad schematic ERC errors | `scripts/ci_kicad_sch_erc_golden.py` |
| **V5 Place + fab_audit** | pcbnew place, manifest `fab_audit` | Footprints placed; no omissions; `openhac.fab_audit.v1` clean | golden `--production` |
| **V6 Route + PCB DRC** | FreeRouting + `kicad-cli pcb drc` | `unrouted_net_count=0`, track gates, **zero** PCB DRC errors | requires `FREEROUTING_JAR` |
| **V7 Fab export** | `openhac export fab --zip` | Gerbers/drill/pos zip produced | after V5/V6 |

Orchestrator: **`scripts/ci_validate_production.py`**.

Legacy / subset: `scripts/ci_validate_fab_gates.py` (place + Gerbers; route optional).

---

## Golden design

- Fixture: [`tests/fixtures/fab_golden_board.py`](../../tests/fixtures/fab_golden_board.py)
- Mirror: [`examples/fab_golden_resistor_bridge.py`](../../examples/fab_golden_resistor_bridge.py)

Two 0805 resistors, explicit pinouts, stock KiCad footprint, offline `comp_data` — small enough for CI routing + DRC.

**GLD-001** tracks a separate analog-island golden (`examples/spice_island_golden.py`) that uses bundled Apache physics (diode / opto / in-amp). That is **not** part of `--require-all` and does **not** change the 2R fab claim. Schematic ERC golden remains `examples/sso041_signoff_node.py`. See [WORKFLOW_GATES_SPEC.md](./WORKFLOW_GATES_SPEC.md).

---

## Complex multi-IC boards (stress / ceiling)

Inspired offline examples (not the V0–V7 golden claim):

| Board | Script | Mode |
|-------|--------|------|
| ESP32 DevKit–class | [`examples/complex_esp32_devkit_node.py`](../../examples/complex_esp32_devkit_node.py) | fab offline |
| STM32 CAN | [`examples/complex_stm32_can_node.py`](../../examples/complex_stm32_can_node.py) | fab offline |
| STM32 RS-485 | [`examples/complex_rs485_node.py`](../../examples/complex_rs485_node.py) | fab offline |
| ESP32-C3 USB | [`examples/complex_esp32c3_usb_node.py`](../../examples/complex_esp32c3_usb_node.py) | fab offline |
| Sensor hub (BMP280) | [`examples/complex_sensor_hub.py`](../../examples/complex_sensor_hub.py) | fab offline |
| Industrial mesh gateway | [`examples/complex_industrial_mesh_gateway.py`](../../examples/complex_industrial_mesh_gateway.py) | fab offline |
| AMR / AGV compute brick | [`examples/complex_amr_compute_brick.py`](../../examples/complex_amr_compute_brick.py) | fab offline |
| LCSC live API mixed | [`examples/complex_lcsc_api_mixed_node.py`](../../examples/complex_lcsc_api_mixed_node.py) | **network** jlcsearch |

Orchestrator: **`scripts/ci_validate_complex_boards.py`**.

```bash
# All fab boards — logic ERC/DRC
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_complex_boards.py

# Place + Gerbers (needs pcbnew)
OPENHAC_NO_NETWORK=1 python3 scripts/ci_validate_complex_boards.py --place

# Live LCSC/jlcsearch API path (needs network)
python3 scripts/ci_validate_complex_boards.py --api --only lcsc_api_mixed
```

Pytest matrix: `tests/test_complex_boards_matrix.py` (logic always; place/API behind `OPENHAC_TEST_COMPLEX_PLACE` / `OPENHAC_TEST_COMPLEX_API`).

**Observed ceiling (local validation):**

| Stage | Fab complex boards (×7) | API mixed |
|-------|-------------------------|-----------|
| Logic ERC/DRC | **PASS** | handoff compile (**PASS** with `--allow-risky-parts`) |
| Place + Gerbers | **PASS** (autosize + split modules) | N/A unless enriched |
| FreeRouting + KiCad PCB DRC | **Green subset** (`esp32c3_usb`, `rs485_node`) under ABC-008; WROOM-32 thermal-via / min-hole still a known ceiling (**ABC-009**) | N/A |

Advanced capabilities: [ADVANCED_BOARD_CAPABILITIES_SPEC.md](./ADVANCED_BOARD_CAPABILITIES_SPEC.md) (**ABC-***).

**“Any board” honesty:** OpenHaC handles multi-IC digital/power maker boards in this class when pinouts+stock footprints are explicit. It does **not** guarantee BGA escape, impedance-controlled HS, RF antenna sign-off, or clean autoroute of every module footprint (SCOPE / PCB-007 / ABC Phases 2–4).

Design tips that made place pass: one large IC per module, `Board(size_mm=None)` autosize, avoid fixed mounting-hole coords under autosize, generous packing knobs (set by the complex validator).

Route subset (ABC-008):

```bash
FREEROUTING_JAR=... OPENHAC_NO_NETWORK=1 \
  python3 scripts/ci_validate_complex_boards.py --place --route --route-subset esp32c3_usb,rs485_node
```

---

## Commands

```bash
# Full claim (needs KiCad + pcbnew + kicad-cli + FreeRouting JAR + Java)
export FREEROUTING_JAR=/path/to/freerouting-2.2.4.jar
export OPENHAC_NO_NETWORK=1
python3 scripts/ci_validate_production.py --require-all

# CI helper: download pinned FreeRouting JAR if missing
python3 scripts/ci_validate_production.py --require-all --fetch-freerouting

# Logic-only (no pcbnew): unit + native ERC/DRC + negatives
python3 scripts/ci_validate_production.py --logic-only
```

---

## Mapping to FAB IDs

| Stages | FAB IDs |
|--------|---------|
| V0–V3 | FAB-001, FAB-002, FAB-003, FAB-010, FAB-011 |
| V4 | FAB-040 / SCH-003 |
| V5 | FAB-020, FAB-032, FAB-003 |
| V6 | FAB-021, FAB-022, FAB-031 prerequisites |
| V7 | FAB-031 |
| CI hard gates | FAB-050, FAB-051 |
