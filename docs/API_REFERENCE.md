# OpenHaC Language Reference Guide

OpenHaC (Hardware as Code) is a Python-based framework that allows you to construct modular, production-ready PCBs completely through code. This guide serves as the official reference for defining components, modules, interfaces, and controlling schematic outputs.

---

## 1. Core Concepts

Hardware in OpenHaC is built using three primary primitives:
1. **Board**: The top-level container that represents the physical PCB.
2. **Module**: Reusable, logical blocks of hardware (e.g., a Power Supply, an MCU subsystem).
3. **Component**: Individual physical footprints and symbols (e.g., resistors, microcontrollers).

### Example: Defining a Module

A Module is a standard Python class that inherits from `b.Module`. You instantiate `Net`s to wire components together inside the module's `__init__`.

```python
from openhac.core import Board
from openhac.core.base import Component, Module
from openhac.core.net import Net

class StatusLED(Module):
    def __init__(self, name: str, *, net_name: str) -> None:
        super().__init__(name)
        
        # 1. Define Local Nets
        self.v3v3 = Net("3V3")
        self.gnd = Net("GND")
        self.sig = Net(net_name)
        
        # 2. Add Components
        self.led = self.add(Component("LED_BLUE_0603"))
        self.r = self.add(Component("R_1K_0603"))
        
        # 3. Wire Component Pins to Nets using the `+=` operator
        self.r["1"] += self.v3v3
        self.r["2"] += self.sig
        self.led["A"] += self.sig
        self.led["K"] += self.gnd
        
        # 4. Declare Interfaces for cross-module wiring
        self.pwr = self.declare_interface("pwr", self.v3v3, self.gnd)
```

---

## 2. Cross-Module Wiring (Interfaces)

OpenHaC forces you to define strict **Interfaces** if you want to wire modules together. This prevents "spaghetti wiring" across different blocks.

In the example above, `StatusLED` declares a power interface `pwr` consisting of `3V3` and `GND`. 

If we have another module that provides power (e.g., `PowerTree`), we wire their interfaces together at the `Board` level:

```python
def build_board():
    b = Board(size_mm=(50, 50))
    pwr = PowerTree()
    led = StatusLED("LED", net_name="STATUS_TX")
    
    b.add_module(pwr)
    b.add_module(led)
    
    # Connect the exposed interfaces
    b.connect(pwr.pwr_3v3, led.pwr)
    return b
```

---

## 3. Schematic Generation & Layout

When compiling, OpenHaC generates a `.kicad_sch` file. OpenHaC supports two advanced layout strategies to generate highly professional, readable schematics.

### 3.1. DAG / Flow-Based Layout (Recommended for Single-Sheet)

If you are viewing all your modules on a single schematic sheet, OpenHaC can arrange them in a "Flow-Based" layout (Left-to-Right). This is the industry standard (Inputs on left, Processor in middle, Outputs on right).

To use this, simply set the `self.schematic_layer` hint in your module's `__init__`:

```python
class PowerTree(Module):
    def __init__(self):
        super().__init__("PowerTree")
        self.schematic_layer = 0  # 0 = Far Left

class HostMCU(Module):
    def __init__(self):
        super().__init__("HostMCU")
        self.schematic_layer = 1  # 1 = Middle

class StatusLED(Module):
    def __init__(self):
        super().__init__("StatusLED")
        self.schematic_layer = 2  # 2 = Far Right
```
The compiler will detect these hints and automatically pack the module components into clean, left-to-right columns.

### 3.2. Hierarchical Layout (Multi-Sheet)

For extremely large projects, a single sheet becomes unreadable. OpenHaC natively supports **Hierarchical Schematics**.

When enabled, OpenHaC will generate a root schematic sheet containing "Module Blocks" (one block per `Module`). Double-clicking a block in KiCad opens a sub-sheet containing only the components for that specific module!

**How to Enable:**
Hierarchical layout requires zero code changes as long as you used `b.Module`. You simply pass the environment flag during compilation:

```bash
OPENHAC_SCHEMATIC_MULTI_SHEET=1 openhac compile my_script.py
```
*(The compiler will also automatically enable this if your board exceeds 25 components).*

---

## 4. Power & Common Nets

OpenHaC automatically identifies common power nets by their name (e.g., `GND`, `VCC`, `3V3`, `5V`, `VBAT`, `PWR`). 

When generating the schematic, it will **not** draw messy wires connecting every ground pin together. Instead, it generates a clean `5.08mm` wire stub for each pin and attaches a KiCad `(global_label)`. This ensures true electrical connectivity for DRC while maintaining a beautiful visual presentation.
