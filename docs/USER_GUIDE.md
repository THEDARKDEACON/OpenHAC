# OpenHaC User Guide

Welcome to **OpenHaC (Hardware as Code)**. This guide will walk you through the workflow of designing, simulating, and compiling physical hardware using Python.

---

## 1. Installation

OpenHaC requires Python 3.11+ and KiCad 8.0+.

```bash
pip install openhac
```

For 3D model and footprint automation, ensure `easyeda2kicad` is installed:

```bash
pip install easyeda2kicad
```

---

## 2. Your First Board

Designing hardware in OpenHaC is like writing a software library. You define **Modules**, instantiate **Components**, and wire them together.

### Example: `hello_world.py`

```python
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net

class Blinky(Module):
    def __init__(self, name: str):
        super().__init__(name)
        
        # Define nets
        vcc = Net("VCC")
        gnd = Net("GND")
        
        # Add components
        r = self.add(Component("R_1K_0603"))
        led = self.add(Component("LED_RED_0603"))
        
        # Wire them up
        r["1"] += vcc
        r["2"] += led["A"]
        led["K"] += gnd

# Build the board
b = Board(size_mm=(20, 20))
b.add_module(Blinky("LED1"))
b.compile()
```

---

## 3. Compiling and Synthesis

To generate KiCad schematic and PCB files, use the `openhac` CLI:

```bash
openhac compile hello_world.py
```

If the board ships `{stem}.openhac-seed.json` or `{stem}.openhac.json` beside the `.py`, those parts are loaded before the script runs. `openhac sync` is warehouse maintenance, not a compile prerequisite.

### Optional CLI flags:
- `--auto-enrich-board`: Fetches missing footprints and 3D models from LCSC/EasyEDA (needs network).
- `--name <name>`: Sets the output project name.
- `--output-dir <dir>`: Sets where the KiCad files are saved.
- `--deoverlap-iters <N>`: Sets the number of iterations for the spatial solver (default 100).

---

## 4. Advanced Features

Once you've mastered the basics, explore these advanced capabilities:

- **[3D Model Automation](3D_MODELS_AND_FOOTPRINTS.md)**: How OpenHaC JIT-generates your physical assets.
- **[API Reference](API_REFERENCE.md)**: Detailed guide on Interfaces, Modules, and Schematic hints.
- **Simulation**: Use `b.simulate()` to generate SPICE netlists for electrical verification. Analog **sign-off** is `--spice-signoff` (not implied by `--production`).

---

## 5. Catalog depth (`compile_ready` vs `warehouse`)

Packed catalog is **depth**, not SKU count: a named pin table, a real footprint, and a 3D pointer. `openhac sync` and LCSC CSV dumps fill **warehouse** rows. ICs without named pinouts stay warehouse — the compiler does not invent pin names from pin count.

```bash
# Depth report (no network). JSON schema: openhac.catalog_coverage.v1
openhac catalog coverage --json
openhac catalog coverage -o build/catalog_coverage.json

# Named pinouts from vendor APIs (never invoked by --production)
openhac database enrich --missing-pinouts
# alias: openhac database enrich --from-db

# Prefetch 3D for stock footprints that have no KiCad pack mesh
# (map / catalog C… / jlcsearch by MPN). Forbidden under OPENHAC_NO_NETWORK.
# Compile then attaches that file or the KiCad pack.
openhac catalog prefetch-3d board.py
openhac catalog prefetch-3d --skus C165948,C164170

# Optional Extended JLC parts (default sync stays Basic in-stock)
openhac sync --include-extended --max-per-category 200
```

`import_lcsc_csv` is a **warehouse import**: rows without pinouts are not compile-ready. SKU count is not a success metric.

Maintainers (not a user compile phase, not `--production`): `python scripts/catalog_snapshot.py -o build/catalog_coverage.json`. User CI must not require live jlcsearch; use `--skip-sync` for coverage-only. Spec: **[CATALOG_DEPTH_SPEC.md](internal/CATALOG_DEPTH_SPEC.md)**.

---

## 6. SPICE operator path (vendor `.lib` stays off git)

Git does **not** ship proprietary SPICE macromodels. The compiler does not fetch `.lib` files. Analog islands stay **SPS-043** (see `examples/spice_island_golden.py`). `--production` does **not** imply SPICE sign-off.

Operator path:

1. Drop an ngspice-compatible vendor `.lib` in `OPENHAC_SPICE_VENDOR_DIR` (or pass `--spice-vendor-dir`). Encrypted LTspice and `.asc` files are refused.
2. Point an overlay JSON at it: `kind=vendor`, `${OPENHAC_SPICE_VENDOR_DIR}/…`, `sha256`, `pin_map`, `physics_checks`, `license`. A documentation template is `examples/fundi_mig_spice/vendor_ad620.json.example` (`notes.download_page` is human-only; the loader never HTTP-fetches it).
3. Check the files locally: `openhac spice verify-vendor-dir` (and `--overlay path` if needed).
4. Gate the analog island: `openhac compile board.py --spice-signoff` (or `openhac simulate … --spice-signoff`).

Coverage without running ngspice:

```bash
openhac spice coverage board.py --json
openhac spice verify-vendor-dir
```

In-repo Apache physics decks (diode, optocoupler LED-side, simple in-amp) are **not vendor parts**. Spec: **[SPICE_SIGN_OFF_SPEC.md](internal/SPICE_SIGN_OFF_SPEC.md)** (**SPS-010…044**) and **[CATALOG_DEPTH_SPEC.md](internal/CATALOG_DEPTH_SPEC.md)** (**SPS-050…057**). HTTP fetch of vendor SPICE `.lib` stays out of scope.

---

## 7. Manufacturing Handoff

OpenHaC produces standard KiCad files. You can open the generated `.kicad_pcb` in KiCad to:
1.  Fine-tune component placement.
2.  Adjust routing or trace widths.
3.  Generate Gerbers via `openhac export fab`, `kicad-cli`, or the GUI.

Prefer **`openhac preview --watch`** for a live sheet: KiCad draws the `.kicad_sch` to SVG, and a localhost page refreshes when you save the `.py`. That is **not** ERC-stamped and **not** an editor.

```bash
# live SVG viewer (browser). Stop the existing preview first (Ctrl+C).
openhac preview examples/sso041_signoff_node.py -o build/preview --watch

# also open KiCad to nudge pose (Save in KiCad; the SVG is the live look)
openhac preview examples/sso041_signoff_node.py -o build/preview --watch --kicad --pcb
```

Print the URL without opening a browser: `--no-browser` (or `OPENHAC_PREVIEW_NO_BROWSER=1`).

1. Do **not** open KiCad first. Preview writes `.kicad_pro` / `.kicad_sch`, starts the SVG viewer, and optionally launches KiCad (`--kicad`).
2. Watch the browser tab. Save the Python script → the SVG updates. The watcher only sees `.py` saves.
3. To move symbols or footprints, use KiCad, then **Save in KiCad** (overlay is the last saved file). Closing the sheet without Save discards the arrangement.
4. KiCad 9 often **does not prompt Reload**. After a Python rebuild, the SVG is already new; in eeschema use **File → Revert** or close and reopen the sheet.
5. Stop the watcher with Ctrl+C. Freeze with `openhac compile … --keep-kicad-artwork` (parity fail-closed). Full rewrite: `--regenerate-artwork`.

Python remains the electrical source of truth; KiCad is the artwork overlay. Spec: **[LIVE_KICAD_SPEC.md](internal/LIVE_KICAD_SPEC.md)** (**LIVE-001…008**). KiCad 10 may reload the PCB over IPC after `preview --pcb --watch` (**LIVE-010**); missing API is not an error. The electrical stamp is still `openhac compile --schematic-signoff`. Cytoscape `--webview` is deprecated (**FAB-041**).

---

## 8. Workflow gates (lock, ECO, JLC pack, pinout, variants)

Compile writes `{project}.openhac-eco.json` (graph diff vs the previous snapshot in the output dir). KiCad is not the electrical baseline.

```bash
# Pin catalog identity (SKU, pinout hash, footprint). No network.
openhac lock board.py                     # writes openhac.lock next to the script
openhac compile board.py --production --require-lock
openhac compile board.py --lock-file path/openhac.lock

# JLCPCB-shaped BOM + CPL. Does not invent LCSC C-codes.
openhac export jlc board.csv -o fab/jlc
openhac export fab board.kicad_pcb -o gerbers --assembler jlc

# Overlay stub from catalog / KiCad symbol pin names (no datasheet scrape)
openhac pinout init MCU_GENERIC_NAME -o catalog_overlays/mcu.json

# Freeze placement: fail if overlay footprints sit off-board
openhac compile board.py --keep-kicad-artwork --placement-intent
```

`Board(variant="lite")` / `--variant lite` marks excluded modules DNP on the BOM (not netted, not placed). `Board.declare_rail("3V3", voltage_v=3.3, max_amp=0.5)` plus `module.draws_from("3V3", amp=0.1)` is ERC-gated (**PWR-010**); it does not model converter efficiency. `Board.declare_testpoint(net)` plus `--require-testpoints` (or `--production` when testpoints were declared) fails if the TP is missing. SPICE still omits `TP*`.

SPICE-island CI golden: `examples/spice_island_golden.py` (bundled Apache diode/opto/in-amp). That is **not** `--require-all` (still the 2×0805 resistor class). Schematic stamp golden: `examples/sso041_signoff_node.py`. Workflow-gates stress board: `examples/complex_grid_edge_rtu.py` — `openhac compile examples/complex_grid_edge_rtu.py` loads recorded vendor JSON via `complex_grid_edge_rtu.openhac.json` (not `_offline_parts`). Spec: **[WORKFLOW_GATES_SPEC.md](internal/WORKFLOW_GATES_SPEC.md)**.

For capability tiers and non-goals, see **[SCOPE](internal/SCOPE.md)**. For the Phase-2 fail-closed **code → fab** contract (`FAB-*` IDs), see **[Fabrication Readiness Spec](internal/FABRICATION_READINESS_SPEC.md)** and status in **[Implementation Status](internal/IMPLEMENTATION_STATUS.md)**. Release steps: **[RELEASE_CHECKLIST](internal/RELEASE_CHECKLIST.md)**.
