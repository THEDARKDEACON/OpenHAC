# OpenHaC — Open Hardware-as-Code

A Python compiler that turns declarative hardware code into manufacturable PCB designs, routed netlists, and SPICE simulations — no GUI required.

## What it does

Write your hardware design in Python. Define components, wire modules together, set spatial constraints, and the compiler produces:

- `.kicad_pcb` — fully placed and routed PCB layout
- `.kicad_sch` — KiCad 7/8 schematic with symbol instances and wires
- `.csv` — Bill of Materials with real LCSC supplier SKUs
- `.cir` — ngspice-compatible SPICE netlist

The pipeline is built on SKiDL for netlist generation, KiCad for PCB/schematic output, FreeRouting for autorouting, and standard SPICE for simulation.

---

## Architecture

**Tier 1 — Component Database (`openhac/database/`)**

SQLite-backed catalog of real, orderable components. Every `Component("name")` call resolves to a real MPN, LCSC supplier SKU, KiCad symbol, and footprint.

- `sync_catalog()` fetches live in-stock parts from the [jlcsearch API](https://jlcsearch.tscircuit.com) (backed by the JLCPCB catalog) across 9 categories: resistors, capacitors, LEDs, MOSFETs, microcontrollers, voltage regulators, diodes, switches, accelerometers
- Components not in the local DB are resolved via live LCSC API lookup and cached automatically — no manual entry needed
- `db.search_components(query, category)` for parametric search

**Tier 2 — Core Abstraction (`openhac/core/`, `openhac/stdlib/`)**

- `Component(generic_name)` — resolves a part name to a real SKiDL `Part` with MPN/footprint injected from the DB
- `Module` — groups components, declares named `Interface` connection points, tracks power budget (`max_current_draw_ma`, `source_current_max_ma`)
- `Board` — connects modules, applies spatial constraints, drives the full compiler pipeline
- `stdlib/` — pre-wired module classes for common parts (ESP32-WROOM, LDO regulators, XT60 connectors, passives)

**Tier 3 — Compiler Pipeline (`openhac/compiler/`)**

- **ERC** (`rule_check.py`): floating nets, unconnected pins, missing power flags, power budget overload
- **Interface validation**: all declared module interfaces must be connected before netlist generation proceeds
- **Netlist** (`netlist_gen.py`): SKiDL → `.net` + BOM `.csv`
- **Layout** (`layout_gen.py`): Z3 constraint solver → KiCad PCB placement
- **Autorouter** (`autoroute_cli.py`): FreeRouting jar via subprocess, DSN/SES workflow
- **Schematic** (`schematic_gen.py`): KiCad S-expression `.kicad_sch` with symbol instances and wire geometry
- **SPICE** (`spice_gen.py`): `.cir` netlist using `Part.ref_prefix` for correct SPICE element identifiers

---

## Installation

```bash
pip install -e .
```

**Requirements:**
- Python 3.11+
- KiCad 7 or 8 with Python bindings (for PCB/schematic output)
- Java runtime (for FreeRouting autorouter)

---

## Setup

### 1. Sync the component database

Pull ~1,400 real in-stock JLCPCB components into the local SQLite cache:

```bash
python -m openhac.database.sync_jlc
```

This is a one-time operation. Re-run periodically to pick up new parts. Any component not in the cache is resolved automatically via live lookup when first used.

### 2. (Optional) Seed baseline parts

The seed script pre-loads a small set of hand-verified parts (ESP32-WROOM, AMS1117, XT60, common passives):

```bash
python -m openhac.database.seed_data
```

---

## Usage

### Defining a Module

A `Module` groups related components and exposes named `Interface` connection points. Internal pin wiring stays private; external connections go through interfaces.

```python
from openhac.core.base import Module, Component
from skidl import Net

class MyMCU(Module):
    def __init__(self):
        super().__init__("MyMCU")

        self.ic = self.add(Component("ESP32_WROOM"))

        vcc = Net("3V3")
        gnd = Net("GND")

        # Internal wiring — raw pin access is fine inside __init__
        self.ic['2'] += vcc
        self.ic['1'] += gnd

        # Declare the external interface — this is what other modules connect to
        self.power = self.declare_interface("power", vcc, gnd)
```

Accessing a module's internal pins from outside its `__init__` emits a `DeprecationWarning` — use `expose_interface()` instead.

### Using stdlib Modules

Pre-wired modules are ready to use directly:

```python
from openhac.stdlib.mcu import ESP32_WROOM
from openhac.stdlib.power import XT60_Input, LDO_5V
from openhac.stdlib.passives import Resistor, Capacitor

mcu   = ESP32_WROOM()   # exposes: mcu.power (vcc, gnd)
ldo   = LDO_5V()        # exposes: ldo.v_in, ldo.v_out
power = XT60_Input()    # exposes: power.v_out

r = Resistor(value="10k", package="0805")
c = Capacitor(value="100nF", package="0603")
```

### Building a Board

```python
from openhac.core import Board
from openhac.stdlib.mcu import ESP32_WROOM
from openhac.stdlib.power import XT60_Input, LDO_5V

board = Board(size_mm=(60, 40), layers=2)

power = XT60_Input()
ldo   = LDO_5V()
mcu   = ESP32_WROOM()

board.add_module(power)
board.add_module(ldo)
board.add_module(mcu)

# Connect interfaces — no raw pin numbers needed at the board level
board.connect(power.v_out, ldo.v_in)
board.connect(ldo.v_out,   mcu.power)
```

### Spatial Constraints

```python
# Keep the power connector on the board edge
board.constrain_edge(power, "TOP")

# Regulator must be at least 8mm from the MCU (thermal isolation)
board.constrain_distance_min(ldo, mcu, 8)

# But no more than 15mm away (trace length)
board.constrain_distance_max(ldo, mcu, 15)
```

### Power Budget

```python
ldo.source_current_max_ma = 500   # LDO can supply 500mA
mcu.max_current_draw_ma   = 250   # ESP32 draws 250mA peak

# If total draw exceeds total supply, ERC raises ERCPowerBudgetError at compile time
```

### Compiling

```python
board.compile(
    project_name="my_board",   # output file prefix
    generate_bom=True,         # write my_board.csv
    auto_route=True,           # invoke FreeRouting (requires FREEROUTING_JAR env var)
    export_schematic=True,     # write my_board.kicad_sch + my_board.kicad_pro
)
```

**FreeRouting autorouter** requires the jar path:

```bash
export FREEROUTING_JAR=/path/to/freerouting.jar
```

Or pass it directly:

```python
from openhac.compiler.autoroute_cli import run_freerouting
run_freerouting("my_board.kicad_pcb", freerouting_jar_path="/path/to/freerouting.jar")
```

### SPICE Simulation

Skip the PCB pipeline entirely and go straight to a SPICE netlist:

```python
from openhac.core import Board
from openhac.core.base import Module, Component
from skidl import Net

class RCFilter(Module):
    def __init__(self):
        super().__init__("RC_LowPass")
        self.r = self.add(Component("R_1k_0603"))
        self.c = self.add(Component("C_10uF_0805"))

        vin  = Net("VIN")
        vout = Net("VOUT")
        gnd  = Net("0")   # SPICE ground is always node 0

        self.r['1'] += vin
        self.r['2'] += vout
        self.c['1'] += vout
        self.c['2'] += gnd

        self.r.part.value = "1k"
        self.c.part.value = "10uF"

board = Board(size_mm=(10, 10))
board.add_module(RCFilter())
board.simulate("rc_filter")   # writes rc_filter.cir
```

### Searching the Component Database

```python
from openhac.database.db_manager import DatabaseManager

db = DatabaseManager()

# Exact lookup by generic name
part = db.get_component("R_10k_0805")
print(part["mpn"], part["supplier_sku"])   # RC0805FR-0710KL  C17513

# Parametric search
results = db.search_components(query="3.3V", category="voltage_regulators", limit=10)
for r in results:
    print(r["generic_name"], r["supplier_sku"])
```

### Adding a Custom Component

Any component not in the DB can be added manually:

```python
from openhac.database.db_manager import DatabaseManager

db = DatabaseManager()
db.insert_component({
    "generic_name":    "OLED_128x64_I2C",
    "kicad_symbol":    "Display:SSD1306",
    "kicad_footprint": "Display:OLED_128x64_I2C",
    "manufacturer":    "Solomon Systech",
    "mpn":             "SSD1306",
    "supplier_sku":    "C5443",
    "description":     "128x64 OLED display, I2C, 3.3V",
})
```

---

## Error Handling

The compiler raises structured exceptions from `openhac.core.base`:

| Exception | When |
|---|---|
| `ERCFloatingNetError` | A net has fewer than 2 connected pins |
| `ERCUnconnectedPinError` | A pin has no net assignment |
| `ERCMissingPowerFlagError` | A power net has no PWR_FLAG |
| `ERCPowerBudgetError` | Total current draw exceeds supply |
| `UnconnectedInterfaceError` | A required module interface is not connected |
| `InterfaceNotFoundError` | `expose_interface()` called with unknown name |
| `FreeRoutingNotFoundError` | FreeRouting jar not found |
| `AutorouterFailedError` | FreeRouting exited with error or produced no SES |
| `SchematicGenerationError` | SKiDL circuit unavailable at schematic generation time |

---

## Project Structure

```
openhac/
  core/
    base.py       # Component, Module, Interface, all exceptions
    board.py      # Board — compiler entry point
  stdlib/
    mcu.py        # ESP32_WROOM
    power.py      # XT60_Input, LDO_5V
    passives.py   # Resistor, Capacitor
  compiler/
    rule_check.py     # ERC + DRC
    netlist_gen.py    # SKiDL → .net + BOM
    layout_gen.py     # Z3 → KiCad PCB placement
    autoroute_cli.py  # FreeRouting subprocess integration
    schematic_gen.py  # KiCad S-expression schematic
    spice_gen.py      # SPICE .cir netlist
    project_gen.py    # .kicad_pro project file
  database/
    db_manager.py  # SQLite CRUD
    sync_jlc.py    # JLCPCB catalog sync via jlcsearch API
    seed_data.py   # Baseline hand-verified parts
    schema.sql     # DB schema
tests/             # pytest + Hypothesis property tests
build.py           # Example integration build
```

---

## License

Open source. See LICENSE.
