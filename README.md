# OpenHaC (Open Hardware-as-Code)

OpenHaC is a general-purpose, open-source Python compiler that translates declarative, object-oriented code into physically routed circuit boards and procurable Bills of Materials (BOM).

## Vision & Objective

The core directive of OpenHaC is to eliminate the need for GUI-based PCB layout tools during the standard design phase. The system natively bridges logical intent (using `SKiDL`), real-world procurable supply chains (via a local `SQLite` database), and geometric physical layouts (using the `KiCad` Python API). Every generic component requested in the Python code automatically resolves to a real Manufacturer Part Number (MPN) upon compilation.

## Architecture

OpenHaC operates on a strict 3-Tier Model ensuring clean abstraction constraints:

### 1. Tier 1: Parametric Translation Engine (`openhac/database/`)
The single source of truth for the physical reality of the board. All hardware code requests generic components (e.g., `R_10k_0805`), and the local DB dynamically queries its schema to map them to specific `KiCad` footprints and real-world MPNs from suppliers like LCSC or Yageo.

### 2. Tier 2: Core Abstraction Engine (`openhac/core/` & `openhac/stdlib/`)
The front-facing API that wraps raw `SKiDL` pins in intuitive Object-Oriented patterns.
- `Component`: Overloads dictionary mapping to seamlessly instantiate KiCad paths and inject SKU/MPN definitions directly into SKiDL metadata.
- `Module`: Collects hardware components logically.
- `Board`: Manages the overall logic tree, layout constraints (`size_mm` & `layers`), and invokes the compiler pipelines.

### 3. Tier 3: Compilation Engine (`openhac/compiler/`)
The compiler runtime translates abstract objects into physical manufacturing files across three sequential phases:
- **Logic & BOM Compiler**: Generates SKiDL `.net` netlists and exports a manufactured `.csv` BOM with resolved absolute MPNs.
- **Geometric Layout Compiler**: Utilizes `pcbnew` (the KiCad API) to define physical board constraints and outlines.
- **Routing Compiler**: Operates as a CLI wrapper to invoke `FreeRouting` to route out copper traces out-of-the-box.

## Features
- **Headless Execution**: Compiles everything exclusively from the Python command line without ever starting the KiCad layout GUI.
- **Declarative Hardware Design**: Clean, explicit layout interfaces mimicking standard coding structures (Object-Oriented interfaces, module components).
- **Graceful Fallbacks**: Automatically generates synthetic SKiDL dummy parts upon missing local KiCad footprint libraries (very useful in headless CI/CD integration pipelines).

## Getting Started

1. **Install Requirements**:
   Ensure you have SKiDL, python 3.12, and KiCad installed (alongside its Python bindings).
   ```bash
   pip install -e .
   ```

2. **Seed Local Database**:
   Establish your initial catalog of procurable MPNs.
   ```bash
   python -m openhac.database.seed_data
   ```

3. **Compiler Demonstration**:
   Design your circuit via a declarative Python file (`build.py`) representing an ultimate acceptance integration test.
   ```bash
   python build.py
   ```
   *Expected outputs*: `iot_node.net`, `iot_node.csv`, and `iot_node.kicad_pcb` seamlessly materialized without GUI intervention.
