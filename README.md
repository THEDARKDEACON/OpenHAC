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

Use `openhac compile --help` for flags (`--no-route`, `--skip-layout`, `--deterministic`, `--compile-goal fabrication`, auto-enrich, etc.).

**FreeRouting:**

```bash
export FREEROUTING_JAR=/path/to/freerouting.jar
```

**Fabrication (Gerbers / drill / position)** after you have a `.kicad_pcb`:

```bash
openhac export fab my_board.kicad_pcb -o ./gerbers
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

## LaTeX report

Long-form write-up: `docs/report/`. Build PDF: `python3 scripts/build_latex_report.py` (needs a LaTeX engine).

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
