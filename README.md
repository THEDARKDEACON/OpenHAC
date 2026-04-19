# OpenHaC — Open Hardware-as-Code

Python compiler that turns declarative hardware code into **netlists**, **BOMs**, **KiCad PCB/schematic** outputs, optional **FreeRouting**, and **SPICE** — no GUI required.

## Outputs

- `.net` / `.csv` — SKiDL netlist and BOM (LCSC-oriented fields when available)
- `.kicad_pcb` — placement, pad nets; optional autoroute (FreeRouting or minimal `pcbnew` fallback)
- `.kicad_sch` / `.kicad_pro` — optional schematic + project (when enabled)
- Generated symbol stubs (`*.openhac-generated.kicad_sym`) and manifest / handoff JSON when configured
- `.cir` — SPICE from `Board.simulate()`

**Docs:** [docs/SCOPE.md](docs/SCOPE.md) (capabilities and limits), [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md), [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

Autorouting is **assistive** (not a substitute for HS/EMC review). See SCOPE for **PCB-007** / differential-pair notes.

---

## Requirements

- **Python** 3.11+
- **KiCad** with **Python bindings** (`import pcbnew`) for layout/schematic — not only `kicad-cli` on `PATH`
- **Footprint libraries:** set `KICAD8_FOOTPRINT_DIR`, `KICAD9_FOOTPRINT_DIR`, or `KICAD_FOOTPRINT_DIR` to the directory that contains `*.pretty` trees (e.g. `/usr/share/kicad/footprints` on Linux)
- **FreeRouting (optional):** JRE + `FREEROUTING_JAR`. KiCad **9** has no `kicad-cli pcb export-dsn`; OpenHaC falls back to `pcbnew.ExportSpecctraDSN` / `ImportSpecctraSES` for the DSN/SES round trip.

---

## Install

```bash
pip install -e .
pip install -e ".[dev]"   # optional: tests, ruff, mypy
```

Dependencies live in **`pyproject.toml`**. Copy **`.env.example`** → **`.env`** for vendor keys, DB path, and FreeRouting (loaded automatically by the CLI).

---

## Environment (quick reference)

| Variable | Purpose |
|----------|---------|
| `OPENHAC_DB_PATH` | SQLite catalog path (default under `openhac/database/`) |
| `OPENHAC_SKIP_LAYOUT` | Skip PCB layout + autoroute (netlist/BOM/manifest only) |
| `OPENHAC_COMPILE_GOAL` | `handoff` vs stricter `fabrication` |
| `OPENHAC_DETERMINISTIC` | More stable outputs for CI/golden tests |
| `FREEROUTING_JAR` | Path to FreeRouting `.jar` |
| `KICAD9_FOOTPRINT_DIR` / `KICAD8_FOOTPRINT_DIR` | Footprint search roots |

Vendor API variables (DigiKey, Mouser, TME, JLC) are documented in **`.env.example`**. Fabrication export also uses KiCad env vars as usual.

---

## Quick start

**1. Optional — sync JLC/LCSC-oriented parts into SQLite** (one-time or periodic):

```bash
python3 -m openhac.database.sync_jlc
```

**2. Optional — seed a small baseline** (`python3 -m openhac.database.seed_data`).

**3. Compile** a design that defines a top-level `board`:

```bash
python3 -m openhac doctor --strict-layout   # optional preflight
openhac compile my_design.py --name my_board -o out/
```

See **`openhac compile` flags and examples** below. The authoritative list is `openhac compile --help`.

**FreeRouting:**

```bash
export FREEROUTING_JAR=/path/to/freerouting.jar
```

**Fabrication (Gerbers / drill / position)** after you have a `.kicad_pcb`:

```bash
openhac export fab my_board.kicad_pcb -o ./gerbers
```

---

## `openhac compile` flags

Run `openhac compile --help` for the full list. Common flags:

| Flag | Purpose |
|------|---------|
| `script` | Path to the hardware `.py` file (required). |
| `-o`, `--output-dir` | Directory for netlist, BOM, PCB, manifest, schematic, project. |
| `--name` | Project basename (default: script stem). |
| `--no-route`, `--no-autoroute`, `--skip-autoroute` | Same behavior: skip FreeRouting / autorouter (PCB placement still runs unless layout is skipped). |
| `--skip-layout` | Skip `pcbnew` PCB generation and autoroute (sets `OPENHAC_SKIP_LAYOUT=1` for the run). |
| `--no-schematic` | Skip `.kicad_sch` / `.kicad_pro` export. |
| `--compile-goal` | `handoff` or `fabrication` (stricter gates). |
| `--bbox-padding-mm` | Extra mm around footprint bboxes for clamp, de-overlap, and fit checks (default `0.5`). |
| `--deoverlap-iters`, `--deoverlap-step-mm` | De-overlap post-process knobs (defaults `200` and `0.75`). |
| `--strict-footprint-pads` | Fail compile if any netted pin has no matching pad on the KiCad footprint (PCB-002); same as `Board(strict_footprint_pin_pad_match=True)` or `OPENHAC_STRICT_FOOTPRINT_PIN_PAD=1`. |
| `--allow-risky-parts` | Allow low-confidence JIT symbol/footprint guesses. |
| `--strict-kicad` | Fail if KiCad symbols cannot load. |
| `--strict-jit` | Stricter JIT unless combined with `--allow-risky-parts`. |
| `--production`, `--strict` | Same option: strict KiCad + strict JIT. |
| `--require-verified-parts` | Fail if unverified JIT parts are present. |
| `--kicad-erc` | After schematic export, run `kicad-cli sch erc`. |
| `--kicad-erc-json` | With `--kicad-erc`, ERC report as JSON. |
| `--kicad-symbol-dir`, `--kicad-symbol-dirs`, `--kicad-footprint-dir` | Override KiCad search paths for this run. |
| `--release-tag`, `--build-profile`, `--bom-profile` | Manifest metadata. |
| `--zip-release`, `--zip-release-path` | Bundle outputs into a zip. |
| `--deterministic` | Set `OPENHAC_DETERMINISTIC=1` for more stable artifacts. |
| `--manifest-sha256-sidecar` | Write manifest `.sha256` sidecar. |
| `--sync-jlc-before`, `--sync-jlc-categories` | Run JLC catalog sync before compile. |
| `--pre-seed-file` | Seed the DB from JSON before compile. |
| `--pre-enrich-json`, `--pre-enrich-vendor`, `--pre-enrich-limit` | Batch enrich from JSON before compile. |
| `--auto-enrich-board`, `--auto-enrich-vendor`, `--auto-enrich-limit` | Discover missing DB metadata and enrich after loading the board. |

**Environment (not on the CLI):** placement (`OPENHAC_PLACEMENT_*`), PCB overlap checks (`OPENHAC_PCB_CHECK_FP_OVERLAP`, `OPENHAC_FP_OVERLAP_CLEARANCE_MM`), strict pin↔pad (`OPENHAC_STRICT_FOOTPRINT_PIN_PAD`), schematic spacing / embed (`OPENHAC_SCHEMATIC_*`), FreeRouting timeout (`OPENHAC_FREEROUTING_TIMEOUT_S`). See **`.env.example`**. Compile also writes **`*.openhac-pin-pad-report.json`** (preflight pin keys vs `.kicad_mod` pads) when layout runs.

### Examples

```bash
# Default-style compile with outputs under ./build
openhac compile my_design.py -o build --name my_board

# Fast iteration: place PCB + schematic, skip autorouting
openhac compile my_design.py -o build --no-autoroute

# Same as above (aliases)
openhac compile my_design.py -o build --skip-autoroute

# Netlist / BOM / manifest only (no PCB, no route)
openhac compile my_design.py -o build --skip-layout

# Stricter pipeline
openhac compile my_design.py -o build --compile-goal fabrication --production

# Fail on pin↔footprint pad mismatches before pcbnew (fix DB pinout vs footprint)
openhac compile my_design.py -o build --strict-footprint-pads

# De-overlap and padding when footprints still crowd
openhac compile my_design.py -o build --bbox-padding-mm 1.0 --deoverlap-iters 400 --deoverlap-step-mm 1.0

# Schematic ERC, then optional JSON report
openhac compile my_design.py -o build --kicad-erc --kicad-erc-json

# Release bundle
openhac compile my_design.py -o dist --zip-release --release-tag v1.0.0

# Deterministic artifacts + manifest sha256 sidecar
openhac compile my_design.py -o out --deterministic --manifest-sha256-sidecar
```

---

## Usage sketch

```python
from openhac.core import Board
from openhac.stdlib.power import XT60_Input, LDO_5V
from openhac.stdlib.mcu import ESP32_WROOM

board = Board(size_mm=(60, 40), layers=2)
power, ldo, mcu = XT60_Input(), LDO_5V(), ESP32_WROOM()
board.add_module(power)
board.add_module(ldo)
board.add_module(mcu)
board.connect(power.v_out, ldo.v_in)
board.connect(ldo.v_out, mcu.power)

board.compile(project_name="my_board", generate_bom=True, auto_route=True, export_schematic=True)
```

Preflight: `openhac doctor --json` (add `--strict-layout`, `--strict-routing`, etc. as needed).

---


## Errors

Common compiler exceptions live in `openhac.core.base` and `openhac.compiler.rule_check` — e.g. floating/unconnected nets, interface not wired, power budget, FreeRouting missing/failed, layout/schematic failures, DRC violations, risky JIT lookups. See docstrings and tests for details.

---

## Layout

```
openhac/
  core/           # Component, Module, Board
  stdlib/         # Reusable modules
  compiler/       # Netlist, layout, PCB, schematic, SPICE, export, manifest
  database/       # SQLite catalog, sync_jlc, seed
tests/
scripts/          # CI smoke, examples, report build
```

---

## License

Open source — see **LICENSE**.
