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
openhac compile hello_world.py --auto-enrich-board
```

### Key CLI Flags:
- `--auto-enrich-board`: Automatically fetches missing footprints and 3D models from LCSC/EasyEDA.
- `--name <name>`: Sets the output project name.
- `--output-dir <dir>`: Sets where the KiCad files are saved.
- `--deoverlap-iters <N>`: Sets the number of iterations for the spatial solver (default 100).

---

## 4. Advanced Features

Once you've mastered the basics, explore these advanced capabilities:

- **[3D Model Automation](3D_MODELS_AND_FOOTPRINTS.md)**: How OpenHaC JIT-generates your physical assets.
- **[API Reference](API_REFERENCE.md)**: Detailed guide on Interfaces, Modules, and Schematic hints.
- **Simulation**: Use `b.simulate()` to generate SPICE netlists for electrical verification.

---

## 5. Manufacturing Handoff

OpenHaC produces standard KiCad files. You can open the generated `.kicad_pcb` in KiCad to:
1.  Fine-tune component placement.
2.  Adjust routing or trace widths.
3.  Generate Gerbers via `openhac export fab`, `kicad-cli`, or the GUI.

Prefer **webview / IR** for connectivity review; auto-generated `.kicad_sch` is optional and not the electrical source of truth.

For capability tiers and non-goals, see **[SCOPE](internal/SCOPE.md)**. For the Phase-2 fail-closed **code → fab** contract (`FAB-*` IDs), see **[Fabrication Readiness Spec](internal/FABRICATION_READINESS_SPEC.md)** and status in **[Implementation Status](internal/IMPLEMENTATION_STATUS.md)**. Release steps: **[RELEASE_CHECKLIST](internal/RELEASE_CHECKLIST.md)**.
